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

-- 6. Battery Capacity & Degradation History
CREATE TABLE IF NOT EXISTS battery_capacity_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    epoch_ms INTEGER NOT NULL,
    pack_name TEXT NOT NULL,
    estimated_capacity_ah REAL NOT NULL,
    nameplate_capacity_ah REAL NOT NULL,
    soh_percentage REAL NOT NULL,
    confidence_score REAL,
    cycle_delta_ah REAL,
    start_soc REAL,
    end_soc REAL,
    mean_temp REAL,
    source TEXT,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_cap_history_epoch ON battery_capacity_history(epoch_ms);
CREATE INDEX IF NOT EXISTS idx_cap_history_pack ON battery_capacity_history(pack_name, epoch_ms);

-- 7. Structured SeaTalkNG & NMEA 2000 Vessel Telemetry
CREATE TABLE IF NOT EXISTS telemetry_seatalkng (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    epoch_ms INTEGER NOT NULL,
    heading_deg REAL,
    heading_ref TEXT,
    variation_deg REAL,
    pitch_deg REAL,
    roll_deg REAL,
    yaw_deg REAL,
    rate_of_turn_dps REAL,
    rudder_deg REAL,
    pressure_hpa REAL,
    pilot_mode TEXT,
    latitude REAL,
    longitude REAL,
    sog_knots REAL,
    cog_true REAL,
    satellites INTEGER,
    hdop REAL,
    altitude_m REAL,
    ais_target_count INTEGER,
    raw_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_seatalkng_epoch ON telemetry_seatalkng(epoch_ms);

-- 8. Structured AIS Targets (Class A & B)
CREATE TABLE IF NOT EXISTS telemetry_ais (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    epoch_ms INTEGER NOT NULL,
    mmsi INTEGER NOT NULL,
    vessel_name TEXT,
    call_sign TEXT,
    ship_type INTEGER,
    ais_class TEXT,
    latitude REAL,
    longitude REAL,
    sog_knots REAL,
    cog_true REAL,
    true_heading REAL,
    nav_status TEXT,
    range_nm REAL,
    bearing_deg REAL,
    raw_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_ais_epoch ON telemetry_ais(epoch_ms);
CREATE INDEX IF NOT EXISTS idx_ais_mmsi ON telemetry_ais(mmsi, epoch_ms);

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

CREATE VIEW IF NOT EXISTS v_recent_capacity AS
    SELECT * FROM battery_capacity_history ORDER BY epoch_ms DESC LIMIT 100;

CREATE VIEW IF NOT EXISTS v_recent_seatalkng AS
    SELECT * FROM telemetry_seatalkng ORDER BY epoch_ms DESC LIMIT 500;

CREATE VIEW IF NOT EXISTS v_recent_ais AS
    SELECT * FROM telemetry_ais ORDER BY epoch_ms DESC LIMIT 500;
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
        self._capacity_batch: list[tuple] = []
        self._seatalkng_batch: list[tuple] = []
        self._ais_batch: list[tuple] = []

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

        # Check for Capacity update payload
        if (topic in ("paeraki/battery/72v/capacity", "paeraki/battery/12v/capacity") or topic.startswith("paeraki/battery/")) and topic.endswith("/capacity") and isinstance(parsed_json, dict):
            self._record_capacity(parsed_json, timestamp_iso, epoch_ms, topic)

        # Check for SeaTalkNG consolidated state payload
        if topic == "paeraki/seatalkng/state" and isinstance(parsed_json, dict):
            self._record_seatalkng(parsed_json, timestamp_iso, epoch_ms)

        # Check for AIS target payload
        if topic.startswith("paeraki/seatalkng/ais/target/") and isinstance(parsed_json, dict):
            self._record_ais(parsed_json, timestamp_iso, epoch_ms)
        elif topic == "paeraki/seatalkng/ais/targets" and isinstance(parsed_json, list):
            for t in parsed_json:
                if isinstance(t, dict):
                    self._record_ais(t, timestamp_iso, epoch_ms)

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

    def _record_capacity(self, data: dict, timestamp_iso: str, epoch_ms: int, topic: str):
        pack_name = data.get("pack_name")
        if not pack_name:
            if "72v" in topic:
                pack_name = "72v_propulsion"
            elif "12v" in topic:
                pack_name = "12v_house"
            else:
                pack_name = "unknown"

        est_cap = float(data.get("estimated_capacity_ah") or 0.0)
        nom_cap = float(data.get("nameplate_capacity_ah") or (200.0 if "72v" in pack_name else 100.0))
        soh = float(data.get("soh_percentage") or (round((est_cap / max(1.0, nom_cap)) * 100.0, 1) if est_cap else 100.0))
        conf = float(data.get("confidence_score")) if data.get("confidence_score") is not None else None
        delta_ah = float(data.get("cycle_delta_ah")) if data.get("cycle_delta_ah") is not None else None
        start_soc = float(data.get("start_soc")) if data.get("start_soc") is not None else None
        end_soc = float(data.get("end_soc")) if data.get("end_soc") is not None else None
        mean_t = float(data.get("mean_temp")) if data.get("mean_temp") is not None else None
        source = str(data.get("source") or "cycle_analyzer")
        notes = str(data.get("notes") or "")

        row = (
            timestamp_iso,
            epoch_ms,
            pack_name,
            est_cap,
            nom_cap,
            soh,
            conf,
            delta_ah,
            start_soc,
            end_soc,
            mean_t,
            source,
            notes,
        )
        self._capacity_batch.append(row)

    def record_capacity_event(self, data: dict, timestamp_iso: str | None = None) -> None:
        """Directly writes a capacity estimation event and flushes."""
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
        pack_name = data.get("pack_name", "72v_propulsion")
        topic = f"paeraki/battery/{pack_name}/capacity"
        self._record_capacity(data, timestamp_iso, epoch_ms, topic)
        self.flush()

    def _record_seatalkng(self, data: dict, timestamp_iso: str, epoch_ms: int):
        heading = data.get("heading_deg")
        ref = data.get("heading_reference")
        var = data.get("variation_deg")
        pitch = data.get("pitch_deg")
        roll = data.get("roll_deg")
        yaw = data.get("yaw_deg")
        rot = data.get("rate_of_turn_dps")
        rudder = data.get("rudder_deg")
        press = data.get("pressure_hpa")
        pilot = data.get("pilot_mode")
        lat = data.get("latitude")
        lon = data.get("longitude")
        sog = data.get("sog_knots")
        cog = data.get("cog_true")
        sats = data.get("satellites")
        hdop = data.get("hdop")
        alt = data.get("altitude_m")
        ais_count = data.get("ais_target_count")

        row = (
            timestamp_iso,
            epoch_ms,
            heading,
            ref,
            var,
            pitch,
            roll,
            yaw,
            rot,
            rudder,
            press,
            pilot,
            lat,
            lon,
            sog,
            cog,
            sats,
            hdop,
            alt,
            ais_count,
            json.dumps(data)
        )
        self._seatalkng_batch.append(row)

        # Also keep telemetry_gps table updated with high-precision SeaTalkNG coordinates
        if lat is not None and lon is not None:
            lat_hemi = "S" if lat < 0 else "N"
            lat_deg = int(abs(lat))
            lat_min = (abs(lat) - lat_deg) * 60.0
            lat_naut = f"{lat_deg}°{lat_min:06.3f}' {lat_hemi}"

            lon_hemi = "W" if lon < 0 else "E"
            lon_deg = int(abs(lon))
            lon_min = (abs(lon) - lon_deg) * 60.0
            lon_naut = f"{lon_deg}°{lon_min:06.3f}' {lon_hemi}"

            sog_k = sog or 0.0
            gps_row = (
                timestamp_iso,
                epoch_ms,
                1,
                "GNSS 3D (SeaTalkNG)",
                1,
                lat,
                lon,
                lat_naut,
                lon_naut,
                sog_k,
                round(sog_k * 1.852, 2),
                round(sog_k * 0.514444, 2),
                cog,
                alt,
                sats,
                hdop,
                "SeaTalkNG PGN 129029"
            )
            self._gps_batch.append(gps_row)

    def _record_ais(self, data: dict, timestamp_iso: str, epoch_ms: int):
        mmsi = data.get("mmsi")
        if not mmsi:
            return
        row = (
            timestamp_iso,
            epoch_ms,
            int(mmsi),
            data.get("vessel_name") or "",
            data.get("call_sign") or "",
            data.get("ship_type"),
            data.get("ais_class") or "B",
            data.get("latitude"),
            data.get("longitude"),
            data.get("sog_knots"),
            data.get("cog_true"),
            data.get("true_heading"),
            data.get("nav_status"),
            data.get("range_nm"),
            data.get("bearing_deg"),
            json.dumps(data)
        )
        self._ais_batch.append(row)

    def flush(self) -> int:
        """Flushes all pending buffered records to SQLite in a single transaction."""
        if (
            not self._raw_batch
            and not self._72v_batch
            and not self._12v_batch
            and not self._gps_batch
            and not self._charger_batch
            and not self._capacity_batch
            and not self._seatalkng_batch
            and not self._ais_batch
        ):
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

                if self._capacity_batch:
                    conn.executemany(
                        """INSERT INTO battery_capacity_history (
                            timestamp, epoch_ms, pack_name, estimated_capacity_ah,
                            nameplate_capacity_ah, soh_percentage, confidence_score,
                            cycle_delta_ah, start_soc, end_soc, mean_temp,
                            source, notes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        self._capacity_batch
                    )
                    self._capacity_batch.clear()

                if self._seatalkng_batch:
                    conn.executemany(
                        """INSERT INTO telemetry_seatalkng (
                            timestamp, epoch_ms, heading_deg, heading_ref, variation_deg,
                            pitch_deg, roll_deg, yaw_deg, rate_of_turn_dps, rudder_deg,
                            pressure_hpa, pilot_mode, latitude, longitude, sog_knots,
                            cog_true, satellites, hdop, altitude_m, ais_target_count, raw_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        self._seatalkng_batch
                    )
                    self._seatalkng_batch.clear()

                if self._ais_batch:
                    conn.executemany(
                        """INSERT INTO telemetry_ais (
                            timestamp, epoch_ms, mmsi, vessel_name, call_sign,
                            ship_type, ais_class, latitude, longitude, sog_knots,
                            cog_true, true_heading, nav_status, range_nm, bearing_deg, raw_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        self._ais_batch
                    )
                    self._ais_batch.clear()

            logger.debug("Flushed %d packets to SQLite", total_flushed)
            return total_flushed
        except Exception as e:
            logger.error("Failed to flush records to SQLite: %s", e)
            return 0

    def query_recent_seatalkng(self, limit: int = 100) -> list[dict]:
        """Returns recent SeaTalkNG vessel telemetry records."""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT * FROM telemetry_seatalkng ORDER BY epoch_ms DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def query_recent_ais(self, limit: int = 100) -> list[dict]:
        """Returns recent AIS vessel position and target records."""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT * FROM telemetry_ais ORDER BY epoch_ms DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def close(self):
        self.flush()
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.info("Closed telemetry database connection.")
