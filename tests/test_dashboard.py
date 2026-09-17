import json
import pytest
from dashboard.server import (
    DashboardState,
    format_lat_nautical,
    format_lon_nautical,
    haversine_nm,
    calculate_bearing_deg,
)


def test_geodetic_and_nautical_helpers():
    # Lat / Lon nautical formatting
    assert format_lat_nautical(-36.8485) == "36° 50.910' S"
    assert format_lon_nautical(174.7633) == "174° 45.798' E"
    assert format_lat_nautical(None) == "--° --.---' -"
    assert format_lon_nautical(None) == "---° --.---' -"

    # Distance between two points in Hauraki Gulf
    # -36.8485, 174.7633 to -36.8385, 174.7733 (~0.77 NM)
    dist = haversine_nm(-36.8485, 174.7633, -36.8385, 174.7733)
    assert dist is not None
    assert 0.70 <= dist <= 0.85

    # Bearing from point 1 to point 2
    brg = calculate_bearing_deg(-36.8485, 174.7633, -36.8385, 174.7733)
    assert brg is not None
    assert 0.0 <= brg <= 90.0  # North-East quadrant


def test_dashboard_state_seatalkng_and_router_gps():
    state = DashboardState()

    # Ingest SeaTalkNG State
    seatalk_payload = {
        "latitude": -36.8485,
        "longitude": 174.7633,
        "sog_knots": 5.2,
        "cog_true": 48.0,
        "heading_deg": 46.5,
        "heading_reference": "Magnetic",
        "variation_deg": 24.87,
        "pitch_deg": -0.8,
        "roll_deg": 2.4,
        "yaw_deg": 46.5,
        "rate_of_turn_dps": 0.3,
        "rudder_deg": 1.2,
        "satellites": 15,
        "hdop": 0.49,
        "altitude_m": 2.5,
        "pressure_hpa": 1014.5,
        "pilot_mode": "Auto Track",
    }
    state.record_packet("paeraki/seatalkng/state", json.dumps(seatalk_payload))

    # Verify SeaTalkNG GNSS
    assert state.system_gps_seatalkng["fix"] is True
    assert state.system_gps_seatalkng["latitude"] == -36.8485
    assert state.system_gps_seatalkng["longitude"] == 174.7633
    assert state.system_gps_seatalkng["sog_knots"] == 5.2
    assert "S" in state.system_gps_seatalkng["latitude_nautical"]
    assert "E" in state.system_gps_seatalkng["longitude_nautical"]

    # Verify Heading & Dynamics
    assert state.seatalkng_heading["heading_deg"] == 46.5
    assert state.seatalkng_heading["reference"] == "Magnetic"
    assert state.seatalkng_attitude["pitch_deg"] == -0.8
    assert state.seatalkng_attitude["roll_deg"] == 2.4
    assert state.seatalkng_attitude["rudder_deg"] == 1.2
    assert state.seatalkng_attitude["pilot_mode"] == "Auto Track"

    # Verify Barometer
    assert state.seatalkng_environment["pressure_hpa"] == 1014.5

    # Ingest Router GPS
    router_payload = {
        "latitude": -36.84852,
        "longitude": 174.76335,
        "sog_knots": 5.1,
        "cog_true": 47.0,
        "satellites": 9,
        "hdop": 1.1,
        "altitude_m": 4.0,
        "fix": True,
        "fix_status": "3D FIX",
    }
    state.record_packet("paeraki/rut955/gps/state", json.dumps(router_payload))

    assert state.system_gps_router["fix"] is True
    assert state.system_gps_router["latitude"] == -36.84852
    assert state.system_gps_router["source"] == "router"

    # Test discrete packet routing without crosstalk
    state.record_packet("rut955/gps/satellites", "8")
    state.record_packet("seatalkng/gps/satellites", "17")
    assert state.system_gps_router["satellites"] == 8
    assert state.system_gps_seatalkng["satellites"] == 17

    state.record_packet("rut955/gps/latitude", "-36.84855")
    state.record_packet("seatalkng/gps/latitude", "-43.60478")
    assert state.system_gps_router["latitude"] == -36.84855
    assert state.system_gps_seatalkng["latitude"] == -43.60478

    # Test WGS-84 altitude calculation from router altitude_m and geoidal_sep_m
    state.record_packet("rut955/gps/altitude_m", "2.1")
    state.record_packet("rut955/gps/geoidal_sep_m", "11.0")
    assert state.system_gps_router["altitude_m"] == 2.1
    assert state.system_gps_router["geoidal_sep_m"] == 11.0
    assert state.system_gps_router["altitude_wgs84_m"] == 13.1


def test_dashboard_state_ais_sorting_and_unknown_identification():
    state = DashboardState()

    # Own position
    state.system_gps_seatalkng["latitude"] = -36.8485
    state.system_gps_seatalkng["longitude"] = 174.7633

    # Ingest AIS targets (mix of named and unknown, different distances)
    targets = [
        {
            "mmsi": 512009988,
            "vessel_name": "",  # Unknown vessel (further away)
            "call_sign": "",
            "ais_class": "B",
            "latitude": -36.8185,
            "longitude": 174.7933,
            "sog_knots": 0.0,
            "cog_true": 0.0,
            "nav_status": "At Anchor",
        },
        {
            "mmsi": 512003891,
            "vessel_name": "",  # Unknown vessel (closest!)
            "call_sign": "",
            "ais_class": "B",
            "latitude": -36.8400,
            "longitude": 174.7680,
            "sog_knots": 4.8,
            "cog_true": 142.0,
            "nav_status": "Underway Using Engine",
        },
        {
            "mmsi": 512004210,
            "vessel_name": "TE AWA",  # Named vessel (medium distance)
            "call_sign": "ZMA3021",
            "ais_class": "A",
            "latitude": -36.8300,
            "longitude": 174.7750,
            "sog_knots": 11.2,
            "cog_true": 220.0,
            "nav_status": "Underway",
        },
    ]

    state.record_packet("paeraki/seatalkng/ais/targets", json.dumps(targets))

    sorted_targets = state.get_sorted_ais_targets()
    assert len(sorted_targets) == 3

    # Closest target must be first
    first = sorted_targets[0]
    assert first["mmsi"] == 512003891
    assert first["is_unknown"] is True
    assert first["range_nm"] is not None
    assert first["bearing_deg"] is not None

    # Te Awa must be second
    second = sorted_targets[1]
    assert second["mmsi"] == 512004210
    assert second["is_unknown"] is False
    assert second["vessel_name"] == "TE AWA"
    assert second["range_nm"] > first["range_nm"]

    # Furthest unknown must be third
    third = sorted_targets[2]
    assert third["mmsi"] == 512009988
    assert third["is_unknown"] is True
    assert third["range_nm"] > second["range_nm"]

    # Verify AIS status summary
    status = state.get_ais_status()
    assert status["online"] is True
    assert status["target_count"] == 3
    assert status["unknown_count"] == 2
    assert status["named_count"] == 1
    assert status["closest_range_nm"] == first["range_nm"]


def test_dashboard_snapshot_structure():
    state = DashboardState()
    snap = state.get_snapshot()

    assert "subsystems" in snap
    sub = snap["subsystems"]
    assert "gps" in sub
    assert "gps_router" in sub
    assert "gps_seatalkng" in sub
    assert "seatalkng" in sub

    st = sub["seatalkng"]
    assert "attitude" in st
    assert "heading" in st
    assert "environment" in st
    assert "ais_status" in st
    assert "ais_targets" in st
    assert "fridge" in sub


def test_dashboard_state_fridge():
    state = DashboardState()
    payload = {
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
        },
        "right_zone": {
            "current_temperature": 4,
            "target_temperature": 4,
        },
    }
    state.record_packet("paeraki/fridge/state", json.dumps(payload))
    assert state.fridge["battery_voltage"] == 13.2
    assert state.fridge["left_zone"]["current_temperature"] == 3
    assert state.fridge["right_zone"]["current_temperature"] == 4
    assert state.fridge["compressor_running"] is False
    assert state.fridge["run_mode"] == "Eco"

