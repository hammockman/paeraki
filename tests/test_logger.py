"""
Unit tests for Paeraki telemetry database logging (SeaTalkNG and AIS).
"""

import json
import sqlite3
import pytest
from logger.db import TelemetryDatabase


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_paeraki.db"
    db = TelemetryDatabase(db_path=db_file, batch_size=2)
    yield db
    db.close()


def test_seatalkng_and_ais_logging(temp_db):
    # 1. Record SeaTalkNG consolidated state
    seatalkng_state = {
        "latitude": -43.604784,
        "longitude": 172.7149718,
        "sog_knots": 0.0,
        "cog_true": 100.8,
        "heading_deg": 150.0,
        "heading_reference": "Magnetic",
        "variation_deg": 24.87,
        "pitch_deg": 2.05,
        "roll_deg": -1.72,
        "yaw_deg": 149.97,
        "rate_of_turn_dps": 0.97,
        "rudder_deg": 0.5,
        "satellites": 15,
        "hdop": 0.49,
        "altitude_m": 8.3,
        "pressure_hpa": 1014.0,
        "pilot_mode": "Wind",
        "ais_target_count": 2,
    }

    temp_db.record("paeraki/seatalkng/state", json.dumps(seatalkng_state))

    # 2. Record individual AIS target
    ais_target = {
        "mmsi": 512008001,
        "vessel_name": "KOKAHA",
        "call_sign": "ZM1234",
        "ship_type": 36,
        "ais_class": "A",
        "latitude": -43.605638,
        "longitude": 172.72217,
        "sog_knots": 1.2,
        "cog_true": 90.0,
        "true_heading": 92.0,
        "nav_status": "Under way using engine",
        "range_nm": 0.32,
        "bearing_deg": 99.3,
    }

    temp_db.record("paeraki/seatalkng/ais/target/512008001", json.dumps(ais_target))
    temp_db.flush()

    # Query helper tests
    stng_rows = temp_db.query_recent_seatalkng(10)
    assert len(stng_rows) == 1
    row = stng_rows[0]
    assert row["heading_deg"] == 150.0
    assert row["heading_ref"] == "Magnetic"
    assert row["pitch_deg"] == 2.05
    assert row["roll_deg"] == -1.72
    assert row["latitude"] == pytest.approx(-43.604784)
    assert row["satellites"] == 15
    assert row["pilot_mode"] == "Wind"

    # AIS helper test
    ais_rows = temp_db.query_recent_ais(10)
    assert len(ais_rows) == 1
    ais = ais_rows[0]
    assert ais["mmsi"] == 512008001
    assert ais["vessel_name"] == "KOKAHA"
    assert ais["range_nm"] == 0.32
    assert ais["bearing_deg"] == 99.3

    # Verify SeaTalkNG does not pollute telemetry_gps
    conn = sqlite3.connect(temp_db.db_path)
    conn.row_factory = sqlite3.Row
    gps_count = conn.execute("SELECT count(*) as cnt FROM telemetry_gps").fetchone()["cnt"]
    assert gps_count == 0

    # Record router GPS telemetry
    router_state = {
        "fix": True,
        "fix_status": "A",
        "fix_quality": 1,
        "latitude": -36.8485,
        "longitude": 174.7633,
        "latitude_nautical": "36° 50.910' S",
        "longitude_nautical": "174° 45.798' E",
        "sog_knots": 5.2,
        "sog_kmh": 9.6,
        "sog_ms": 2.7,
        "cog_true": 54.0,
        "altitude_m": 3.2,
        "satellites": 9,
        "hdop": 1.1,
        "last_sentence": "$GPRMC",
    }
    temp_db.record("paeraki/rut955/gps/state", json.dumps(router_state))
    temp_db.flush()

    # Verify telemetry_gps is populated with source='rut955'
    gps_row = conn.execute("SELECT * FROM telemetry_gps ORDER BY epoch_ms DESC LIMIT 1").fetchone()
    assert gps_row is not None
    assert gps_row["latitude"] == pytest.approx(-36.8485)
    assert gps_row["longitude"] == pytest.approx(174.7633)
    assert gps_row["source"] == "rut955"
    assert gps_row["fix"] == 1
    assert gps_row["satellites"] == 9

    # Check views
    v_stng = conn.execute("SELECT * FROM v_recent_seatalkng LIMIT 1").fetchone()
    assert v_stng["heading_deg"] == 150.0

    v_ais = conn.execute("SELECT * FROM v_recent_ais LIMIT 1").fetchone()
    assert v_ais["mmsi"] == 512008001
    conn.close()


def test_fridge_logging(temp_db):
    fridge_state = {
        "timestamp": "2026-09-18T09:00:00Z",
        "powered_on": True,
        "controls_locked": False,
        "run_mode": "Eco",
        "battery_saver": "Mid",
        "battery_voltage": 13.2,
        "battery_percent": 100,
        "temperature_unit": "Celsius",
        "compressor_running": False,
        "running_status_code": 0,
        "left_zone": {
            "current_temperature": 3,
            "target_temperature": 5,
            "hysteresis": 2,
            "temp_correction_hot": -3,
            "temp_correction_mid": -3,
            "temp_correction_cold": -3,
            "temp_correction_halt": 0,
        },
        "right_zone": {
            "current_temperature": 4,
            "target_temperature": 4,
            "hysteresis": 2,
            "temp_correction_hot": -3,
            "temp_correction_mid": -3,
            "temp_correction_cold": -3,
            "temp_correction_halt": 0,
        },
    }

    temp_db.record("paeraki/fridge/state", json.dumps(fridge_state))
    temp_db.flush()

    recent = temp_db.query_recent_fridge()
    assert len(recent) == 1
    row = recent[0]
    assert row["left_temp"] == 3
    assert row["left_target"] == 5
    assert row["right_temp"] == 4
    assert row["right_target"] == 4
    assert row["voltage"] == 13.2
    assert row["compressor_running"] == 0
    assert row["run_mode"] == "Eco"
    assert row["battery_saver"] == "Mid"
    assert row["powered_on"] == 1

    # Verify view v_recent_fridge
    conn = temp_db._get_connection()
    view_rows = conn.execute("SELECT * FROM v_recent_fridge").fetchall()
    assert len(view_rows) == 1
    assert view_rows[0]["left_temp"] == 3

