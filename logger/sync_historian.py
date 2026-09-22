#!/usr/bin/env python3
"""
Paeraki Yacht Telemetry Backfill Sync Tool (runs on hammer).
Connects to sing via SSH, queries un-synced telemetry from paeraki_buffer.db,
deduplicates against hammer's archive using indexed timestamp lookups,
inserts missing rows, and advances the sync watermark on sing.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import json
import logging
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from typing import Any

logger = logging.getLogger("paeraki.sync_historian")

TABLES_TO_SYNC = [
    "telemetry_72v",
    "telemetry_12v",
    "telemetry_gps",
    "telemetry_charger",
    "telemetry_seatalkng",
    "telemetry_ais",
    "telemetry_fridge",
    "battery_capacity_history",
    "packets",
]


class HistorianSyncer:
    def __init__(
        self,
        sing_host: str = "sing",
        sing_db_path: str = "/home/jh/paeraki/data/paeraki_buffer.db",
        hammer_db_path: str | Path = "/home/jh/paeraki/data/paeraki.db",
        batch_limit: int = 10000,
        ssh_user: str = "jh",
        ssh_timeout: int = 8,
    ):
        self.sing_host = sing_host
        self.sing_db_path = sing_db_path
        self.hammer_db_path = Path(hammer_db_path).resolve()
        self.batch_limit = batch_limit
        self.ssh_user = ssh_user
        self.ssh_timeout = ssh_timeout
        self._conn: sqlite3.Connection | None = None

    def get_hammer_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.hammer_db_path), timeout=30.0)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def is_sing_reachable(self) -> bool:
        """Checks if any configured sing candidate host is reachable via SSH."""
        candidates = [h.strip() for h in self.sing_host.split(",") if h.strip()]
        for candidate in candidates:
            cmd = [
                "ssh",
                "-o", "BatchMode=yes",
                "-o", f"ConnectTimeout={min(3, self.ssh_timeout)}",
                f"{self.ssh_user}@{candidate}",
                "exit 0",
            ]
            try:
                res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if res.returncode == 0:
                    if self.sing_host != candidate:
                        logger.info("Discovered sing at %s", candidate)
                    self.sing_host = candidate
                    return True
            except Exception as e:
                logger.debug("SSH probe to %s failed: %s", candidate, e)
        return False

    def run_remote_query(self, sql: str) -> list[dict[str, Any]]:
        """Runs a read-only query on sing and parses JSON output."""
        ssh_cmd = (
            f"sqlite3 -json '{self.sing_db_path}' {subprocess.list2cmdline([sql])} | gzip -c"
        )
        cmd = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={self.ssh_timeout}",
            f"{self.ssh_user}@{self.sing_host}",
            ssh_cmd,
        ]
        res = subprocess.run(cmd, capture_output=True)
        if res.returncode != 0:
            err = res.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Remote query failed on {self.sing_host}: {err}")

        if not res.stdout:
            return []

        decompressed = gzip.decompress(res.stdout).decode("utf-8")
        if not decompressed.strip():
            return []
        return json.loads(decompressed)

    def get_sing_watermarks(self) -> dict[str, int]:
        """Fetches table sync watermarks currently stored on sing."""
        try:
            rows = self.run_remote_query(
                "SELECT table_name, last_synced_epoch_ms FROM sync_watermark;"
            )
            return {r["table_name"]: r["last_synced_epoch_ms"] for r in rows}
        except Exception as e:
            logger.warning("Could not read sync_watermark table on %s: %s", self.sing_host, e)
            return {}

    def update_sing_watermark(self, table: str, epoch_ms: int) -> None:
        """Advances the sync watermark on sing for the given table."""
        sql = (
            f"INSERT INTO sync_watermark (table_name, last_synced_epoch_ms, updated_at) "
            f"VALUES ('{table}', {epoch_ms}, datetime('now')) "
            f"ON CONFLICT(table_name) DO UPDATE SET "
            f"last_synced_epoch_ms = MAX(sync_watermark.last_synced_epoch_ms, {epoch_ms}), "
            f"updated_at = datetime('now');"
        )
        cmd = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={self.ssh_timeout}",
            f"{self.ssh_user}@{self.sing_host}",
            f"sqlite3 '{self.sing_db_path}' {subprocess.list2cmdline([sql])}",
        ]
        res = subprocess.run(cmd, capture_output=True)
        if res.returncode != 0:
            err = res.stderr.decode("utf-8", errors="replace").strip()
            logger.error("Failed to update watermark for %s on %s: %s", table, self.sing_host, err)

    def sync_table(self, table: str) -> int:
        """Syncs all pending records for a single table in batches."""
        watermarks = self.get_sing_watermarks()
        current_watermark = watermarks.get(table, 0)
        total_synced = 0
        conn = self.get_hammer_conn()

        logger.info(
            "Syncing table '%s' from %s (current watermark: %d)...",
            table, self.sing_host, current_watermark
        )

        while True:
            # Query a batch of records newer than the current watermark
            query = (
                f"SELECT * FROM {table} "
                f"WHERE epoch_ms > {current_watermark} "
                f"ORDER BY epoch_ms ASC LIMIT {self.batch_limit};"
            )
            rows = self.run_remote_query(query)
            if not rows:
                break

            min_epoch = min(r["epoch_ms"] for r in rows)
            max_epoch = max(r["epoch_ms"] for r in rows)

            # Deduplicate against hammer's existing records in this exact time window
            cur = conn.cursor()
            if table == "telemetry_gps":
                cur.execute(
                    "SELECT epoch_ms, coalesce(source, 'rut955') FROM telemetry_gps WHERE epoch_ms BETWEEN ? AND ?",
                    (min_epoch, max_epoch),
                )
                existing = set((r[0], r[1]) for r in cur.fetchall())
                to_insert = [
                    r for r in rows
                    if (r["epoch_ms"], r.get("source") or "rut955") not in existing
                ]
            elif table == "packets":
                cur.execute(
                    "SELECT epoch_ms, topic FROM packets WHERE epoch_ms BETWEEN ? AND ?",
                    (min_epoch, max_epoch),
                )
                existing = set((r[0], r[1]) for r in cur.fetchall())
                to_insert = [
                    r for r in rows
                    if (r["epoch_ms"], r.get("topic")) not in existing
                ]
            elif table == "telemetry_ais":
                cur.execute(
                    "SELECT epoch_ms, mmsi FROM telemetry_ais WHERE epoch_ms BETWEEN ? AND ?",
                    (min_epoch, max_epoch),
                )
                existing = set((r[0], r[1]) for r in cur.fetchall())
                to_insert = [
                    r for r in rows
                    if (r["epoch_ms"], r.get("mmsi")) not in existing
                ]
            else:
                cur.execute(
                    f"SELECT epoch_ms FROM {table} WHERE epoch_ms BETWEEN ? AND ?",
                    (min_epoch, max_epoch),
                )
                existing = set(r[0] for r in cur.fetchall())
                to_insert = [r for r in rows if r["epoch_ms"] not in existing]

            if to_insert:
                # Omit 'id' so hammer autoincrements its own local sequential ID
                cols = [c for c in to_insert[0].keys() if c != "id"]
                placeholders = ", ".join(["?"] * len(cols))
                col_names = ", ".join(cols)
                sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"
                values = [[r[c] for c in cols] for r in to_insert]

                with conn:
                    conn.executemany(sql, values)
                total_synced += len(to_insert)

            # Advance watermark on sing
            self.update_sing_watermark(table, max_epoch)
            current_watermark = max_epoch

            logger.info(
                "Table '%s': batch processed (received %d, inserted %d new, watermark advanced to %d)",
                table, len(rows), len(to_insert), current_watermark
            )

            # If we received fewer than batch_limit, we have caught up to sing's latest records
            if len(rows) < self.batch_limit:
                break

        return total_synced

    def sync_all(self, target_table: str | None = None) -> dict[str, int]:
        """Runs synchronization across all or a specific table."""
        if not self.is_sing_reachable():
            logger.info("Host %s is not reachable over network/SSH. Skipping sync.", self.sing_host)
            return {}

        results = {}
        tables = [target_table] if target_table else TABLES_TO_SYNC

        for tbl in tables:
            try:
                inserted = self.sync_table(tbl)
                results[tbl] = inserted
            except Exception as e:
                logger.error("Error syncing table '%s': %s", tbl, e)
                results[tbl] = 0

        total = sum(results.values())
        if total > 0:
            logger.info("Backfill sync complete. Successfully replicated %d records into hammer.", total)
        else:
            logger.info("Backfill sync complete. Hammer is already up-to-date with %s.", self.sing_host)
        return results

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None


def main():
    parser = argparse.ArgumentParser(description="Paeraki Vessel Telemetry Backfill Sync (hammer)")
    parser.add_argument("--sing-host", default="192.168.50.158", help="Hostname or IP of sing (default: 192.168.50.158)")
    parser.add_argument("--sing-db", default="/home/jh/paeraki/data/paeraki_buffer.db", help="Path to buffer DB on sing")
    parser.add_argument("--hammer-db", default="/home/jh/paeraki/data/paeraki.db", help="Path to permanent DB on hammer")
    parser.add_argument("--table", default=None, help="Sync only a specific table")
    parser.add_argument("--batch-size", type=int, default=10000, help="Batch limit per query (default: 10000)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Log level")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    syncer = HistorianSyncer(
        sing_host=args.sing_host,
        sing_db_path=args.sing_db,
        hammer_db_path=args.hammer_db,
        batch_limit=args.batch_size,
    )
    try:
        syncer.sync_all(target_table=args.table)
    finally:
        syncer.close()


if __name__ == "__main__":
    main()
