"""
Database layer for Paeraki telemetry logging on hammer.
Uses SQLite in WAL mode for zero-overhead, highly concurrent time-series analytics.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("paeraki.logger.db")

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;

-- 1. Raw packets archive
CREATE TABLE IF NOT EXISTS packets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    epoch_ms INTEGER NOT NULL,
    topic TEXT NOT NULL,
    payload TEXT NOT NULL,
    is_json BOOLEAN NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_packets_epoch ON packets(epoch_ms);
CREATE INDEX IF NOT EXISTS idx_packets_topic ON packets(topic, epoch_ms);

-- 2. Structured 72V Propulsion Pack Telemetry
CREATE TABLE IF NOT EXISTS telemetry_72v (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    epoch_ms INTEGER NOT NULL,
    total_voltage REAL,
    current REAL,
    power REAL,
    rsoc REAL,
    residual_capacity_ah REAL,
    nominal_capacity_ah REAL,
    cycle_times INTEGER,
    charge_status BOOLEAN,
    discharge_status BOOLEAN,
    temp_1 REAL,
    temp_2 REAL,
    cell_min_v REAL,
    cell_max_v REAL,
    cell_delta_mv INTEGER,
    cell_voltages_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_72v_epoch ON telemetry_72v(epoch_ms);

-- 3. Structured 12V House & Solar Telemetry (SRNE MPPT Controller)
CREATE TABLE IF NOT EXISTS telemetry_12v (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    epoch_ms INTEGER NOT NULL,
    battery_voltage REAL,
    battery_soc REAL,
    battery_charge_current REAL,
    solar_voltage REAL,
    solar_current REAL,
    solar_power REAL,
    load_voltage REAL,
    load_current REAL,
    load_power REAL,
    daily_yield_kwh REAL,
    daily_load_kwh REAL,
    controller_temp REAL,
    battery_temp REAL,
    charging_status TEXT
);

CREATE INDEX IF NOT EXISTS idx_12v_epoch ON telemetry_12v(epoch_ms);

-- 4. Structured GPS Navigation Telemetry
CREATE TABLE IF NOT EXISTS telemetry_gps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    epoch_ms INTEGER NOT NULL,
    fix BOOLEAN NOT NULL DEFAULT 0,
    fix_status TEXT,
    fix_quality INTEGER,
    latitude REAL,
    longitude REAL,
    latitude_nautical TEXT,
    longitude_nautical TEXT,
    sog_knots REAL,
    sog_kmh REAL,
    sog_ms REAL,
    cog_true REAL,
    altitude_m REAL,
    satellites INTEGER,
    hdop REAL,
    last_sentence TEXT
);

CREATE INDEX IF NOT EXISTS idx_gps_epoch ON telemetry_gps(epoch_ms);

-- 5. Structured 72V Battery Charger Telemetry
CREATE TABLE IF NOT EXISTS telemetry_charger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    epoch_ms INTEGER NOT NULL,
    state TEXT,
    output_voltage REAL,
    output_current REAL,
    output_power REAL,
    target_current REAL,
    temp REAL,
    error_code TEXT,
    raw_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_charger_epoch ON telemetry_charger(epoch_ms);

-- Convenient views for data analysis
CREATE VIEW IF NOT EXISTS v_recent_72v AS
    SELECT * FROM telemetry_72v ORDER BY epoch_ms DESC LIMIT 500;

CREATE VIEW IF NOT EXISTS v_recent_12v AS
    SELECT * FROM telemetry_12v ORDER BY epoch_ms DESC LIMIT 500;

CREATE VIEW IF NOT EXISTS v_recent_gps AS
    SELECT * FROM telemetry_gps ORDER BY epoch_ms DESC LIMIT 500;

CREATE VIEW IF NOT EXISTS v_recent_charger AS
    SELECT * FROM telemetry_charger ORDER BY epoch_ms DESC LIMIT 500;

CREATE VIEW IF NOT EXISTS v_recent_packets AS
    SELECT * FROM packets ORDER BY epoch_ms DESC LIMIT 500;
"""


class TelemetryDatabase:
    def __init__(self, db_path: str | Path, batch_size: int = 50):
        self.db_path = Path(db_path).resolve()
        self.batch_size = batch_size

        # Create parent directory if needed
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._raw_batch: list[tuple] = []
        self._72v_batch: list[tuple] = []
        self._12v_batch: list[tuple] = []
        self._gps_batch: list[tuple] = []
        self._charger_batch: list[tuple] = []

        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                timeout=10.0,
                check_same_thread=False
            )
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self):
        conn = self._get_connection()
        with conn:
            conn.executescript(SCHEMA_SQL)
        logger.info("Initialized telemetry database at %s (WAL mode enabled)", self.db_path)

    def record(self, topic: str, payload_str: str, timestamp_iso: str | None = None) -> None:
        """Records an incoming MQTT message into buffer for batch insertion."""
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

        # Add to raw archive batch
        self._raw_batch.append((
            timestamp_iso,
            epoch_ms,
            topic,
            payload_str,
            1 if is_json else 0
        ))

        # Check for 72V structured payload
        if topic == "paeraki/72v/state" and isinstance(parsed_json, dict):
            self._record_72v(parsed_json, timestamp_iso, epoch_ms)
        elif topic.startswith("72v/"):
            # If discrete topic, we can also record into 72v table if appropriate
            pass

        # Check for 12V structured payload (record on state topic to avoid double-logging)
        if topic == "paeraki/12v/state" and isinstance(parsed_json, dict):
            self._record_12v(parsed_json, timestamp_iso, epoch_ms)

        # Check for GPS structured payload
        if topic == "paeraki/gps/state" and isinstance(parsed_json, dict):
            self._record_gps(parsed_json, timestamp_iso, epoch_ms)

        # Check for Charger structured payload
        if (topic in ("paeraki/charger/state", "charger/telemetry")) and isinstance(parsed_json, dict):
            self._record_charger(parsed_json, timestamp_iso, epoch_ms)

        # Check batch threshold
        if len(self._raw_batch) >= self.batch_size:
            self.flush()

    def _record_72v(self, data: dict, timestamp_iso: str, epoch_ms: int):
        cur = data.get("current", 0.0)
        v = data.get("total_voltage", 0.0)
        pwr = data.get("power")
        if pwr is None and cur is not None and v is not None:
            pwr = round(float(cur) * float(v), 1)

        temps = data.get("temperatures", [])
        t1 = temps[0] if len(temps) > 0 else None
        t2 = temps[1] if len(temps) > 1 else None

        cells = data.get("cell_voltages", [])
        min_c = min(cells) if cells else None
        max_c = max(cells) if cells else None
        delta_mv = round((max_c - min_c) * 1000, 1) if (min_c is not None and max_c is not None) else None

        row = (
            timestamp_iso,
            epoch_ms,
            v,
            cur,
            pwr,
            data.get("rsoc"),
            data.get("residual_capacity_ah"),
            data.get("nominal_capacity_ah"),
            data.get("cycle_times"),
            1 if data.get("charge_status") else 0,
            1 if data.get("discharge_status") else 0,
            t1,
            t2,
            min_c,
            max_c,
            delta_mv,
            json.dumps(cells) if cells else None
        )
        self._72v_batch.append(row)

    def _record_12v(self, data: dict, timestamp_iso: str, epoch_ms: int):
        row = (
            timestamp_iso,
            epoch_ms,
            data.get("battery_voltage"),
            data.get("battery_soc"),
            data.get("battery_charge_current"),
            data.get("solar_voltage"),
            data.get("solar_current"),
            data.get("solar_power"),
            data.get("load_voltage"),
            data.get("load_current"),
            data.get("load_power"),
            data.get("daily_yield_kwh"),
            data.get("daily_load_kwh"),
            data.get("controller_temperature"),
            data.get("battery_temperature"),
            str(data.get("charging_status", "")),
        )
        self._12v_batch.append(row)

    def _record_gps(self, data: dict, timestamp_iso: str, epoch_ms: int):
        row = (
            timestamp_iso,
            epoch_ms,
            1 if data.get("fix") else 0,
            str(data.get("fix_status", "")),
            data.get("fix_quality"),
            data.get("latitude"),
            data.get("longitude"),
            data.get("latitude_nautical"),
            data.get("longitude_nautical"),
            data.get("sog_knots"),
            data.get("sog_kmh"),
            data.get("sog_ms"),
            data.get("cog_true"),
            data.get("altitude_m"),
            data.get("satellites"),
            data.get("hdop"),
            str(data.get("last_sentence", ""))
        )
        self._gps_batch.append(row)

    def _record_charger(self, data: dict, timestamp_iso: str, epoch_ms: int):
        v = data.get("output_voltage") or data.get("voltage")
        i = data.get("output_current") or data.get("current")
        p = data.get("output_power") or data.get("power")
        if p is None and v is not None and i is not None:
            p = round(float(v) * float(i), 1)

        row = (
            timestamp_iso,
            epoch_ms,
            str(data.get("state") or data.get("status") or "UNKNOWN"),
            float(v) if v is not None else None,
            float(i) if i is not None else None,
            float(p) if p is not None else None,
            float(data.get("target_current", 20.0)) if data.get("target_current") is not None else 20.0,
            float(data.get("temperature") or data.get("temp", 0.0)),
            str(data.get("error_code") or data.get("error") or "NONE"),
            json.dumps(data)
        )
        self._charger_batch.append(row)

    def flush(self) -> int:
        """Flushes all pending buffered records to SQLite in a single transaction."""
        if not self._raw_batch and not self._72v_batch and not self._12v_batch and not self._gps_batch and not self._charger_batch:
            return 0

        conn = self._get_connection()
        total_flushed = len(self._raw_batch)

        try:
            with conn:
                if self._raw_batch:
                    conn.executemany(
                        "INSERT INTO packets (timestamp, epoch_ms, topic, payload, is_json) VALUES (?, ?, ?, ?, ?)",
                        self._raw_batch
                    )
                    self._raw_batch.clear()

                if self._72v_batch:
                    conn.executemany(
                        """INSERT INTO telemetry_72v (
                            timestamp, epoch_ms, total_voltage, current, power, rsoc,
                            residual_capacity_ah, nominal_capacity_ah, cycle_times,
                            charge_status, discharge_status, temp_1, temp_2,
                            cell_min_v, cell_max_v, cell_delta_mv, cell_voltages_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        self._72v_batch
                    )
                    self._72v_batch.clear()

                if self._12v_batch:
                    conn.executemany(
                        """INSERT INTO telemetry_12v (
                            timestamp, epoch_ms, battery_voltage, battery_soc, battery_charge_current,
                            solar_voltage, solar_current, solar_power,
                            load_voltage, load_current, load_power,
                            daily_yield_kwh, daily_load_kwh,
                            controller_temp, battery_temp, charging_status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        self._12v_batch
                    )
                    self._12v_batch.clear()

                if self._gps_batch:
                    conn.executemany(
                        """INSERT INTO telemetry_gps (
                            timestamp, epoch_ms, fix, fix_status, fix_quality,
                            latitude, longitude, latitude_nautical, longitude_nautical,
                            sog_knots, sog_kmh, sog_ms, cog_true, altitude_m,
                            satellites, hdop, last_sentence
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        self._gps_batch
                    )
                    self._gps_batch.clear()

                if self._charger_batch:
                    conn.executemany(
                        """INSERT INTO telemetry_charger (
                            timestamp, epoch_ms, state, output_voltage, output_current,
                            output_power, target_current, temp, error_code, raw_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        self._charger_batch
                    )
                    self._charger_batch.clear()

            logger.debug("Flushed %d packets to SQLite", total_flushed)
            return total_flushed
        except Exception as e:
            logger.error("Failed to flush records to SQLite: %s", e)
            return 0

    def close(self):
        self.flush()
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.info("Closed telemetry database connection.")
