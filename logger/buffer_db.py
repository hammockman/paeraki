"""
Buffer Database layer for Paeraki telemetry logging on sing.
Extends TelemetryDatabase with:
- Incremental auto-vacuum for SD card endurance
- Filtering of high-rate redundant scalar subtopics (preserving structured records)
- Sync-aware retention pruning (with disk safety override)
- High-watermark synchronization tracking
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import shutil
import sqlite3
import time
from typing import Any

# Ensure logger directory is in path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from db import TelemetryDatabase, SCHEMA_SQL

logger = logging.getLogger("paeraki.logger.buffer_db")

SYNC_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sync_watermark (
    table_name TEXT PRIMARY KEY,
    last_synced_epoch_ms INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
"""

TABLES_TO_PRUNE = [
    "packets",
    "telemetry_72v",
    "telemetry_12v",
    "telemetry_gps",
    "telemetry_charger",
    "telemetry_seatalkng",
    "telemetry_ais",
    "telemetry_fridge",
    "battery_capacity_history",
]

REDUNDANT_TOPIC_PREFIXES = (
    "rut955/gps/",
    "seatalkng/gps/",
    "charger/voltage",
    "charger/current",
    "charger/power",
    "charger/temperature",
    "charger/target_current",
    "charger/state",
    "72v/",
    "12v/",
)


class BufferTelemetryDatabase(TelemetryDatabase):
    """SQLite telemetry database with sliding-window retention and sync-aware pruning."""

    def __init__(
        self,
        db_path: str | Path,
        batch_size: int = 100,
        log_all_packets: bool = False,
    ):
        self.log_all_packets = log_all_packets
        super().__init__(db_path=db_path, batch_size=batch_size)

    def _init_db(self):
        conn = self._get_connection()
        # Enable incremental auto-vacuum before creating tables
        cur = conn.cursor()
        cur.execute("PRAGMA auto_vacuum;")
        res = cur.fetchone()
        if res and res[0] != 2:
            cur.execute("PRAGMA auto_vacuum = INCREMENTAL;")
        cur.execute("PRAGMA temp_store = MEMORY;")

        super()._init_db()

        with conn:
            conn.executescript(SYNC_SCHEMA_SQL)
        logger.info(
            "Initialized buffer telemetry database at %s (INCREMENTAL auto_vacuum enabled, log_all_packets=%s)",
            self.db_path,
            self.log_all_packets,
        )

    def record(self, topic: str, payload_str: str, timestamp_iso: str | None = None) -> None:
        """Records an incoming MQTT message into buffer with optional redundant scalar filtering."""
        if not timestamp_iso:
            now = datetime.now(timezone.utc)
            timestamp_iso = now.isoformat()
            epoch_ms = int(now.timestamp() * 1000)
        else:
            try:
                dt = datetime.fromisoformat(timestamp_iso)
                epoch_ms = int(dt.timestamp() * 1000)
            except Exception:
                now = datetime.now(timezone.utc)
                epoch_ms = int(now.timestamp() * 1000)

        # Parse JSON
        parsed_json: dict | None = None
        is_json = False
        try:
            val = json.loads(payload_str)
            if isinstance(val, dict):
                parsed_json = val
                is_json = True
            elif isinstance(val, (list, int, float, bool)):
                is_json = True
        except (ValueError, TypeError):
            pass

        # Check if this is a redundant scalar topic
        is_redundant = False
        if not self.log_all_packets:
            for prefix in REDUNDANT_TOPIC_PREFIXES:
                if topic.startswith(prefix):
                    is_redundant = True
                    break

        if not is_redundant:
            # Add to raw archive batch
            self._raw_batch.append((
                timestamp_iso,
                epoch_ms,
                topic,
                payload_str,
                1 if is_json else 0
            ))

        # Check structured payloads
        if topic == "paeraki/72v/state" and isinstance(parsed_json, dict):
            self._record_72v(parsed_json, timestamp_iso, epoch_ms)

        if topic == "paeraki/12v/state" and isinstance(parsed_json, dict):
            self._record_12v(parsed_json, timestamp_iso, epoch_ms)

        if (topic in ("paeraki/gps/state", "paeraki/rut955/gps/state")) and isinstance(parsed_json, dict):
            self._record_gps(parsed_json, timestamp_iso, epoch_ms, source="rut955")

        if (topic in ("paeraki/charger/state", "charger/telemetry")) and isinstance(parsed_json, dict):
            self._record_charger(parsed_json, timestamp_iso, epoch_ms)

        if (
            (topic in ("paeraki/battery/72v/capacity", "paeraki/battery/12v/capacity") or topic.startswith("paeraki/battery/"))
            and topic.endswith("/capacity")
            and isinstance(parsed_json, dict)
        ):
            self._record_capacity(parsed_json, timestamp_iso, epoch_ms, topic)

        if topic == "paeraki/seatalkng/state" and isinstance(parsed_json, dict):
            self._record_seatalkng(parsed_json, timestamp_iso, epoch_ms)

        if topic.startswith("paeraki/seatalkng/ais/target/") and isinstance(parsed_json, dict):
            self._record_ais(parsed_json, timestamp_iso, epoch_ms)
        elif topic == "paeraki/seatalkng/ais/targets" and isinstance(parsed_json, list):
            for t in parsed_json:
                if isinstance(t, dict):
                    self._record_ais(t, timestamp_iso, epoch_ms)

        if topic == "paeraki/fridge/state" and isinstance(parsed_json, dict):
            self._record_fridge(parsed_json, timestamp_iso, epoch_ms)

        # Check batch threshold across any accumulating batch
        if (
            len(self._raw_batch) >= self.batch_size
            or len(self._72v_batch) >= self.batch_size
            or len(self._12v_batch) >= self.batch_size
            or len(self._gps_batch) >= self.batch_size
            or len(self._charger_batch) >= self.batch_size
            or len(self._seatalkng_batch) >= self.batch_size
            or len(self._ais_batch) >= self.batch_size
            or len(self._fridge_batch) >= self.batch_size
        ):
            self.flush()

    def prune(self, retention_days: float = 3.0, disk_safety_gb: float = 15.0) -> dict[str, int]:
        """
        Prunes records older than retention_days.
        Sync-Aware: Only prunes records that have been confirmed synced (<= last_synced_epoch_ms),
        UNLESS free disk space falls below disk_safety_gb.
        Returns a mapping of table_name -> deleted_count.
        """
        now_ms = int(time.time() * 1000)
        retention_ms = int(retention_days * 86400 * 1000)
        cutoff_ms = now_ms - retention_ms

        try:
            free_bytes = shutil.disk_usage(self.db_path.parent).free
            free_gb = free_bytes / (1024 ** 3)
        except Exception:
            free_gb = 999.0

        force_prune_for_disk = (free_gb < disk_safety_gb)
        if force_prune_for_disk:
            logger.warning(
                "Disk space critical (%.2f GB free < %.2f GB threshold). Forcing prune regardless of sync state!",
                free_gb, disk_safety_gb
            )

        conn = self._get_connection()
        watermarks = self.get_sync_watermarks()
        deleted_counts: dict[str, int] = {}

        for table in TABLES_TO_PRUNE:
            last_synced = watermarks.get(table)
            if force_prune_for_disk:
                barrier_ms = cutoff_ms
            elif last_synced is not None:
                barrier_ms = min(cutoff_ms, last_synced)
            else:
                # Never synced yet, and disk is healthy -> retain all records!
                barrier_ms = None

            if barrier_ms is not None:
                try:
                    with conn:
                        cur = conn.execute(
                            f"DELETE FROM {table} WHERE epoch_ms <= ?", (barrier_ms,)
                        )
                        deleted_counts[table] = cur.rowcount
                except Exception as e:
                    logger.error("Error pruning table %s: %s", table, e)
                    deleted_counts[table] = 0
            else:
                deleted_counts[table] = 0

        total_deleted = sum(deleted_counts.values())
        if total_deleted > 0:
            try:
                conn.execute("PRAGMA incremental_vacuum(500);")
                logger.info(
                    "Pruned %d records total across tables (retention_days=%.1f). Incremental vacuum executed.",
                    total_deleted, retention_days
                )
            except Exception as e:
                logger.warning("Error running incremental vacuum: %s", e)

        return deleted_counts

    def get_sync_watermarks(self) -> dict[str, int]:
        """Returns dict of table_name -> last_synced_epoch_ms."""
        conn = self._get_connection()
        try:
            cur = conn.execute("SELECT table_name, last_synced_epoch_ms FROM sync_watermark")
            return {row[0]: row[1] for row in cur.fetchall()}
        except Exception:
            return {}

    def update_sync_watermark(self, table_name: str, epoch_ms: int) -> None:
        """Updates or advances last_synced_epoch_ms for the given table."""
        conn = self._get_connection()
        now_iso = datetime.now(timezone.utc).isoformat()
        with conn:
            conn.execute(
                """INSERT INTO sync_watermark (table_name, last_synced_epoch_ms, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(table_name) DO UPDATE SET
                       last_synced_epoch_ms = MAX(sync_watermark.last_synced_epoch_ms, excluded.last_synced_epoch_ms),
                       updated_at = excluded.updated_at""",
                (table_name, epoch_ms, now_iso),
            )
