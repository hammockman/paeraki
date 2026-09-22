"""
Unit tests for the rolling buffer database and sync logic.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time
import pytest

from logger.buffer_db import BufferTelemetryDatabase, TABLES_TO_PRUNE


def test_buffer_database_initialization(tmp_path):
    db_file = tmp_path / "test_buffer.db"
    db = BufferTelemetryDatabase(db_file, batch_size=10)

    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()

    # Check auto_vacuum mode (2 == INCREMENTAL)
    cur.execute("PRAGMA auto_vacuum;")
    mode = cur.fetchone()[0]
    assert mode == 2

    # Check sync_watermark table exists
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sync_watermark';")
    assert cur.fetchone() is not None

    db.close()
    conn.close()


def test_redundant_scalar_topic_filtering(tmp_path):
    db_file = tmp_path / "test_filter.db"
    db = BufferTelemetryDatabase(db_file, batch_size=5, log_all_packets=False)

    # 1. Publish redundant scalar topics (should NOT be added to packets table)
    db.record("rut955/gps/latitude", "-36.8509")
    db.record("rut955/gps/longitude", "174.7645")
    db.record("72v/voltage", "74.5")
    db.record("charger/current", "15.0")

    # 2. Publish structured and unmodeled topics (should BE added)
    gps_json = json.dumps({
        "fix": True,
        "latitude": -36.8509,
        "longitude": 174.7645,
        "sog_knots": 5.2,
        "cog_true": 180.0,
    })
    db.record("paeraki/gps/state", gps_json)
    db.record("paeraki/alarms/state", json.dumps({"active_alarms": []}))
    db.record("paeraki/custom/event", "vessel_started")

    db.flush()

    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()

    # packets should only have 3 records (paeraki/gps/state, paeraki/alarms/state, paeraki/custom/event)
    cur.execute("SELECT topic FROM packets ORDER BY id ASC;")
    topics = [r[0] for r in cur.fetchall()]
    assert "rut955/gps/latitude" not in topics
    assert "72v/voltage" not in topics
    assert "paeraki/gps/state" in topics
    assert "paeraki/alarms/state" in topics
    assert "paeraki/custom/event" in topics

    # But telemetry_gps MUST have the structured record!
    cur.execute("SELECT latitude, longitude, sog_knots FROM telemetry_gps;")
    row = cur.fetchone()
    assert row is not None
    assert row[0] == -36.8509
    assert row[1] == 174.7645
    assert row[2] == 5.2

    db.close()
    conn.close()


def test_log_all_packets_override(tmp_path):
    db_file = tmp_path / "test_all.db"
    db = BufferTelemetryDatabase(db_file, batch_size=5, log_all_packets=True)

    db.record("rut955/gps/latitude", "-36.8509")
    db.flush()

    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("SELECT topic FROM packets WHERE topic = 'rut955/gps/latitude';")
    assert cur.fetchone() is not None

    db.close()
    conn.close()


def test_sync_aware_retention_pruning(tmp_path):
    db_file = tmp_path / "test_retention.db"
    db = BufferTelemetryDatabase(db_file, batch_size=50)

    now_ms = int(time.time() * 1000)
    day_ms = 86400 * 1000

    # Insert synthetic records spanning 5 days: Day 0 (now), Day -1, Day -2, Day -4, Day -5
    timestamps = [
        now_ms,
        now_ms - 1 * day_ms,
        now_ms - 2 * day_ms,
        now_ms - 4 * day_ms,  # older than 3-day retention
        now_ms - 5 * day_ms,  # older than 3-day retention
    ]

    for ms in timestamps:
        iso_str = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()
        db.record("paeraki/custom/event", f"event_{ms}", timestamp_iso=iso_str)

    db.flush()

    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM packets;")
    assert cur.fetchone()[0] == 5

    # Case 1: No sync has happened yet, and disk is healthy
    # Pruner should RETAIN all 5 records (protecting against data loss during offshore voyage)
    pruned = db.prune(retention_days=3.0, disk_safety_gb=0.1)
    assert pruned.get("packets", 0) == 0

    cur.execute("SELECT count(*) FROM packets;")
    assert cur.fetchone()[0] == 5

    # Case 2: Watermark synced up to Day -4 (epoch_ms = now_ms - 4 * day_ms)
    # Day -5 is older than 3 days AND <= watermark -> should be pruned!
    # Day -4 is older than 3 days, and <= watermark -> should be pruned!
    db.update_sync_watermark("packets", now_ms - 4 * day_ms)
    pruned = db.prune(retention_days=3.0, disk_safety_gb=0.1)
    assert pruned.get("packets", 0) == 2  # Day -4 and Day -5 pruned

    cur.execute("SELECT count(*) FROM packets;")
    assert cur.fetchone()[0] == 3  # Day 0, Day -1, Day -2 remain

    db.close()
    conn.close()


def test_emergency_disk_safety_pruning(tmp_path):
    db_file = tmp_path / "test_emergency.db"
    db = BufferTelemetryDatabase(db_file, batch_size=50)

    now_ms = int(time.time() * 1000)
    day_ms = 86400 * 1000

    # Records: Day 0 and Day -4 (older than 3 days)
    iso_old = datetime.fromtimestamp((now_ms - 4 * day_ms) / 1000.0, tz=timezone.utc).isoformat()
    iso_now = datetime.fromtimestamp(now_ms / 1000.0, tz=timezone.utc).isoformat()

    db.record("paeraki/custom/event", "old", timestamp_iso=iso_old)
    db.record("paeraki/custom/event", "now", timestamp_iso=iso_now)
    db.flush()

    # Never synced, but set disk_safety_gb impossibly high to simulate disk full
    pruned = db.prune(retention_days=3.0, disk_safety_gb=999999.0)
    assert pruned.get("packets", 0) == 1

    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM packets;")
    assert cur.fetchone()[0] == 1

    db.close()
    conn.close()


def test_historian_syncer_deduplication(tmp_path):
    from logger.sync_historian import HistorianSyncer

    sing_db_file = tmp_path / "sing_buffer.db"
    hammer_db_file = tmp_path / "hammer_archive.db"

    # Set up sing buffer
    sing_db = BufferTelemetryDatabase(sing_db_file, batch_size=10)
    now_ms = int(time.time() * 1000)

    # Sing has records at t=1000, 2000, 3000
    sing_db.record("paeraki/72v/state", json.dumps({"total_voltage": 74.0, "current": 10.0}), timestamp_iso="2026-09-22T00:00:01Z")
    sing_db.record("paeraki/72v/state", json.dumps({"total_voltage": 74.2, "current": 12.0}), timestamp_iso="2026-09-22T00:00:02Z")
    sing_db.record("paeraki/72v/state", json.dumps({"total_voltage": 74.4, "current": 14.0}), timestamp_iso="2026-09-22T00:00:03Z")
    sing_db.flush()

    # Set up hammer archive with record at t=1000 (already logged before outage)
    hammer_db = BufferTelemetryDatabase(hammer_db_file, batch_size=10)
    hammer_db.record("paeraki/72v/state", json.dumps({"total_voltage": 74.0, "current": 10.0}), timestamp_iso="2026-09-22T00:00:01Z")
    hammer_db.flush()

    syncer = HistorianSyncer(
        sing_host="localhost",
        sing_db_path=str(sing_db_file),
        hammer_db_path=str(hammer_db_file),
    )

    # Mock remote query and watermark update to operate on local sing_db_file
    def mock_remote_query(sql: str):
        conn = sqlite3.connect(str(sing_db_file))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql)
        res = [dict(r) for r in cur.fetchall()]
        conn.close()
        return res

    def mock_update_watermark(table: str, epoch_ms: int):
        sing_db.update_sync_watermark(table, epoch_ms)

    syncer.run_remote_query = mock_remote_query
    syncer.update_sing_watermark = mock_update_watermark

    # Run sync for telemetry_72v
    inserted = syncer.sync_table("telemetry_72v")
    # Record at t=1000 was already in hammer, so only 2 records (t=2000, 3000) should be inserted
    assert inserted == 2

    # Check hammer now has exactly 3 records
    h_conn = sqlite3.connect(str(hammer_db_file))
    cur = h_conn.cursor()
    cur.execute("SELECT count(*), count(distinct epoch_ms) FROM telemetry_72v;")
    total, distinct = cur.fetchone()
    assert total == 3
    assert distinct == 3

    # Running sync a second time should insert 0 records (watermark and deduplication)
    inserted_again = syncer.sync_table("telemetry_72v")
    assert inserted_again == 0

    h_conn.close()
    sing_db.close()
    hammer_db.close()
    syncer.close()
