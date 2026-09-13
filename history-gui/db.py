"""Database query engine and async background worker for Paeraki Telemetry History.

Opens paeraki.db in read-only URI mode to prevent any database contention or locking
with paeraki_logger.service's continuous WAL updates.
"""

from __future__ import annotations

import datetime
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot

DB_PATH = Path("/home/jh/paeraki/data/paeraki.db")


def get_db_connection() -> sqlite3.Connection:
    """Return a read-only URI connection to paeraki.db."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}")
    uri = f"file:{DB_PATH.resolve()}?mode=ro"
    con = sqlite3.connect(uri, uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def get_time_bounds() -> dict[str, Any]:
    """Retrieve global min/max timestamps and row counts across all tables."""
    con = get_db_connection()
    try:
        cur = con.cursor()
        bounds = {}
        tables = ["telemetry_72v", "telemetry_12v", "telemetry_gps", "telemetry_charger", "packets"]
        overall_min = None
        overall_max = None
        counts = {}

        for tbl in tables:
            cur.execute(f"SELECT COUNT(*), MIN(epoch_ms), MAX(epoch_ms) FROM {tbl}")
            cnt, mn, mx = cur.fetchone()
            counts[tbl] = cnt
            if mn is not None:
                overall_min = mn if overall_min is None else min(overall_min, mn)
            if mx is not None:
                overall_max = mx if overall_max is None else max(overall_max, mx)

        return {
            "min_ms": overall_min or int((time.time() - 86400) * 1000),
            "max_ms": overall_max or int(time.time() * 1000),
            "counts": counts,
        }
    finally:
        con.close()


def query_72v(start_ms: int, end_ms: int, max_points: int = 10000) -> list[dict[str, Any]]:
    """Fetch 72V telemetry within [start_ms, end_ms], downsampling if needed."""
    con = get_db_connection()
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM telemetry_72v WHERE epoch_ms BETWEEN ? AND ?",
            (start_ms, end_ms),
        )
        total_rows = cur.fetchone()[0]

        step = max(1, total_rows // max_points) if total_rows > max_points else 1

        if step > 1:
            sql = f"""
            SELECT * FROM (
                SELECT *, ROW_NUMBER() OVER (ORDER BY epoch_ms ASC) as rn
                FROM telemetry_72v
                WHERE epoch_ms BETWEEN ? AND ?
            ) WHERE (rn % ?) = 1
            ORDER BY epoch_ms ASC
            """
            cur.execute(sql, (start_ms, end_ms, step))
        else:
            cur.execute(
                "SELECT * FROM telemetry_72v WHERE epoch_ms BETWEEN ? AND ? ORDER BY epoch_ms ASC",
                (start_ms, end_ms),
            )

        rows = [dict(r) for r in cur.fetchall()]
        return rows
    finally:
        con.close()


def query_charger(start_ms: int, end_ms: int, max_points: int = 10000) -> list[dict[str, Any]]:
    """Fetch 72V BF Tech Charger telemetry within [start_ms, end_ms]."""
    con = get_db_connection()
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM telemetry_charger WHERE epoch_ms BETWEEN ? AND ?",
            (start_ms, end_ms),
        )
        total_rows = cur.fetchone()[0]

        step = max(1, total_rows // max_points) if total_rows > max_points else 1

        if step > 1:
            sql = f"""
            SELECT * FROM (
                SELECT *, ROW_NUMBER() OVER (ORDER BY epoch_ms ASC) as rn
                FROM telemetry_charger
                WHERE epoch_ms BETWEEN ? AND ?
            ) WHERE (rn % ?) = 1
            ORDER BY epoch_ms ASC
            """
            cur.execute(sql, (start_ms, end_ms, step))
        else:
            cur.execute(
                "SELECT * FROM telemetry_charger WHERE epoch_ms BETWEEN ? AND ? ORDER BY epoch_ms ASC",
                (start_ms, end_ms),
            )

        return [dict(r) for r in cur.fetchall()]
    finally:
        con.close()


def query_12v(start_ms: int, end_ms: int, max_points: int = 10000) -> list[dict[str, Any]]:
    """Fetch 12V House & Solar telemetry within [start_ms, end_ms]."""
    con = get_db_connection()
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM telemetry_12v WHERE epoch_ms BETWEEN ? AND ?",
            (start_ms, end_ms),
        )
        total_rows = cur.fetchone()[0]

        step = max(1, total_rows // max_points) if total_rows > max_points else 1

        if step > 1:
            sql = f"""
            SELECT * FROM (
                SELECT *, ROW_NUMBER() OVER (ORDER BY epoch_ms ASC) as rn
                FROM telemetry_12v
                WHERE epoch_ms BETWEEN ? AND ?
            ) WHERE (rn % ?) = 1
            ORDER BY epoch_ms ASC
            """
            cur.execute(sql, (start_ms, end_ms, step))
        else:
            cur.execute(
                "SELECT * FROM telemetry_12v WHERE epoch_ms BETWEEN ? AND ? ORDER BY epoch_ms ASC",
                (start_ms, end_ms),
            )

        return [dict(r) for r in cur.fetchall()]
    finally:
        con.close()


def query_gps(start_ms: int, end_ms: int, max_points: int = 10000) -> list[dict[str, Any]]:
    """Fetch GPS navigation telemetry within [start_ms, end_ms]."""
    con = get_db_connection()
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM telemetry_gps WHERE epoch_ms BETWEEN ? AND ?",
            (start_ms, end_ms),
        )
        total_rows = cur.fetchone()[0]

        step = max(1, total_rows // max_points) if total_rows > max_points else 1

        if step > 1:
            sql = f"""
            SELECT * FROM (
                SELECT *, ROW_NUMBER() OVER (ORDER BY epoch_ms ASC) as rn
                FROM telemetry_gps
                WHERE epoch_ms BETWEEN ? AND ?
            ) WHERE (rn % ?) = 1
            ORDER BY epoch_ms ASC
            """
            cur.execute(sql, (start_ms, end_ms, step))
        else:
            cur.execute(
                "SELECT * FROM telemetry_gps WHERE epoch_ms BETWEEN ? AND ? ORDER BY epoch_ms ASC",
                (start_ms, end_ms),
            )

        return [dict(r) for r in cur.fetchall()]
    finally:
        con.close()


def query_packets(
    start_ms: int,
    end_ms: int,
    topic_filter: str | None = None,
    payload_search: str | None = None,
    limit: int = 1000,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Query packets matching time range and filters, returning (rows, total_count)."""
    con = get_db_connection()
    try:
        cur = con.cursor()
        conditions = ["epoch_ms BETWEEN ? AND ?"]
        params: list[Any] = [start_ms, end_ms]

        if topic_filter and topic_filter != "all":
            if "#" in topic_filter:
                prefix = topic_filter.split("#")[0]
                conditions.append("topic LIKE ?")
                params.append(f"{prefix}%")
            else:
                conditions.append("topic = ?")
                params.append(topic_filter)

        if payload_search and payload_search.strip():
            conditions.append("payload LIKE ?")
            params.append(f"%{payload_search.strip()}%")

        where_clause = " AND ".join(conditions)

        # Count total matching
        count_sql = f"SELECT COUNT(*) FROM packets WHERE {where_clause}"
        cur.execute(count_sql, params)
        total_count = cur.fetchone()[0]

        # Fetch limited slice
        query_sql = f"""
        SELECT id, timestamp, epoch_ms, topic, payload, is_json
        FROM packets
        WHERE {where_clause}
        ORDER BY epoch_ms DESC
        LIMIT ? OFFSET ?
        """
        cur.execute(query_sql, params + [limit, offset])
        rows = [dict(r) for r in cur.fetchall()]
        return rows, total_count
    finally:
        con.close()


def execute_sql(query: str, limit: int = 5000) -> tuple[list[str], list[list[Any]], float]:
    """Execute raw user query safely in read-only mode, returning (columns, rows, elapsed_ms)."""
    start_time = time.perf_counter()
    con = get_db_connection()
    try:
        cur = con.cursor()
        # Enforce read-only constraint even on cursor
        cur.execute(query)
        columns = [col[0] for col in cur.description] if cur.description else []
        rows = cur.fetchmany(limit)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        return columns, [list(r) for r in rows], elapsed_ms
    finally:
        con.close()


class WorkerSignals(QObject):
    """Signals for background database query workers."""

    finished = pyqtSignal()
    error = pyqtSignal(str)
    result = pyqtSignal(object)


class DbQueryWorker(QRunnable):
    """Generic background QRunnable for off-thread DB queries."""

    def __init__(self, query_fn, *args, **kwargs):
        super().__init__()
        self.query_fn = query_fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self):
        try:
            res = self.query_fn(*self.args, **self.kwargs)
            self.signals.result.emit(res)
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()
