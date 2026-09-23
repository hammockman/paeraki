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


def test_dashboard_state_cortex_and_mob():
    state = DashboardState()

    # 1. Ingest Cortex Anchor Watch
    anchor_data = {
        "active": True,
        "anchor_lat": -36.8485,
        "anchor_lon": 174.7633,
        "radius_m": 35.0,
        "distance_m": 12.4,
        "bearing_deg": 120.0,
        "drag_alarm": False,
    }
    state.record_packet("paeraki/cortex/anchor", json.dumps(anchor_data))
    assert state.cortex_anchor["active"] is True
    assert state.cortex_anchor["radius_m"] == 35.0
    assert state.cortex_anchor["distance_m"] == 12.4

    # 2. Ingest Cortex Active Alarms
    alarms_data = [
        {"id": "alarm_cpa_1", "type": "CollisionRisk", "message": "CPA risk with Target A", "silenced": False}
    ]
    state.record_packet("paeraki/cortex/alarms", json.dumps(alarms_data))
    assert len(state.cortex_alarms) == 1
    assert state.cortex_alarms[0]["id"] == "alarm_cpa_1"

    # 3. Ingest MoB Alert
    mob_data = {
        "active": True,
        "timestamp": "2026-09-18T10:00:00Z",
        "latitude": -36.8485,
        "longitude": 174.7633,
        "source": "dashboard",
    }
    state.record_packet("paeraki/cortex/mob/alert", json.dumps(mob_data))
    assert state.mob_alert["active"] is True
    assert state.mob_alert["latitude"] == -36.8485

    # 4. Verify in Snapshot
    snap = state.get_snapshot()
    sub = snap["subsystems"]
    assert "cortex" in sub
    assert sub["cortex"]["anchor"]["radius_m"] == 35.0
    assert len(sub["cortex"]["alarms"]) == 1
    assert "mob" in sub
    assert sub["mob"]["active"] is True


def test_dashboard_auth_protection():
    import asyncio
    from fastapi import HTTPException
    from dashboard.auth import require_control_auth

    # Unauthenticated context -> must raise 403
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(require_control_auth(None))
    assert exc_info.value.status_code == 403

    # Viewer context -> must raise 403
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(require_control_auth({"role": "VIEWER"}))
    assert exc_info.value.status_code == 403

    # Controller context -> allowed
    ctx = asyncio.run(require_control_auth({"role": "CONTROLLER", "name": "Skipper"}))
    assert ctx["name"] == "Skipper"


def test_cortex_control_flow():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    import dashboard.server as srv

    # Mock publish on server's state
    srv.state.publish = AsyncMock()

    # Pre-populate Cortex alarm
    srv.state.cortex_alarms = [
        {"id": "alarm_anchor_1", "type": "AnchorDrag", "message": "Dragging anchor", "silenced": False}
    ]
    srv.state.system_gps = {"latitude": -36.8485, "longitude": 174.7633}

    app = srv.create_app("", 0)

    # Find cortex_silence, cortex_mob, cortex_mob_cancel route endpoints
    silence_endpoint = None
    mob_endpoint = None
    mob_cancel_endpoint = None
    for route in app.routes:
        if getattr(route, "path", None) == "/api/cortex/silence":
            silence_endpoint = route.endpoint
        elif getattr(route, "path", None) == "/api/cortex/mob":
            mob_endpoint = route.endpoint
        elif getattr(route, "path", None) == "/api/cortex/mob/cancel":
            mob_cancel_endpoint = route.endpoint

    assert silence_endpoint is not None
    assert mob_endpoint is not None
    assert mob_cancel_endpoint is not None

    async def _run_tests():
        # 1. Test Silence Alarm
        req = MagicMock()
        req.json = AsyncMock(return_value={"alarm_id": "alarm_anchor_1"})
        auth_ctx = {"role": "CONTROLLER", "name": "Skipper"}
        res = await silence_endpoint(req, auth_ctx=auth_ctx)
        assert res.status_code == 200
        assert srv.state.cortex_alarms[0]["silenced"] is True
        assert srv.state.publish.called

        # 2. Test Trigger MoB
        req_mob = MagicMock()
        req_mob.json = AsyncMock(return_value={"confirm": True})
        res_mob = await mob_endpoint(req_mob, auth_ctx=auth_ctx)
        assert res_mob.status_code == 200
        assert srv.state.mob_alert["active"] is True
        assert srv.state.mob_alert["latitude"] == -36.8485

        # 3. Test Cancel MoB
        req_cancel = MagicMock()
        res_cancel = await mob_cancel_endpoint(req_cancel, auth_ctx=auth_ctx)
        assert res_cancel.status_code == 200
        assert srv.state.mob_alert["active"] is False

    asyncio.run(_run_tests())


def test_audio_mixer_and_endpoints():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    import dashboard.server as srv
    from dashboard.audio import get_all_audio_state, set_alsa_volume, set_alsa_mute

    # Test standalone audio module helpers
    st = get_all_audio_state()
    assert "inside" in st
    assert "outside" in st

    res_vol = set_alsa_volume("inside", 77)
    assert res_vol["volume"] == 77

    res_mute = set_alsa_mute("outside", True)
    assert res_mute["muted"] is True

    # Test server endpoints
    app = srv.create_app("", 0)
    srv.state.broadcast = AsyncMock()

    get_audio_endpoint = None
    post_vol_endpoint = None
    post_mute_endpoint = None
    get_health_endpoint = None
    post_restart_endpoint = None
    for route in app.routes:
        path = getattr(route, "path", None)
        if path == "/api/audio/state":
            get_audio_endpoint = route.endpoint
        elif path == "/api/audio/volume":
            post_vol_endpoint = route.endpoint
        elif path == "/api/audio/mute":
            post_mute_endpoint = route.endpoint
        elif path == "/api/audio/health":
            get_health_endpoint = route.endpoint
        elif path == "/api/audio/restart":
            post_restart_endpoint = route.endpoint

    assert get_audio_endpoint is not None
    assert post_vol_endpoint is not None
    assert post_mute_endpoint is not None
    assert get_health_endpoint is not None
    assert post_restart_endpoint is not None

    async def _test():
        # GET audio state
        res = await get_audio_endpoint()
        data = json.loads(res.body.decode())
        assert "inside" in data
        assert "outside" in data

        # GET audio health
        res_h = await get_health_endpoint()
        assert res_h.status_code == 200
        data_h = json.loads(res_h.body.decode())
        assert "status" in data_h
        assert "devices" in data_h
        assert "mpd" in data_h

        # POST volume
        req = MagicMock()
        req.json = AsyncMock(return_value={"zone": "inside", "volume": 42})
        res = await post_vol_endpoint(req)
        assert res.status_code == 200
        data = json.loads(res.body.decode())
        assert data["status"] == "ok"
        assert data["zone"] == "inside"
        assert data["state"]["volume"] == 42
        assert srv.state.broadcast.called

        # POST mute
        req2 = MagicMock()
        req2.json = AsyncMock(return_value={"zone": "outside", "muted": True})
        res2 = await post_mute_endpoint(req2)
        assert res2.status_code == 200
        data2 = json.loads(res2.body.decode())
        assert data2["status"] == "ok"
        assert data2["zone"] == "outside"
        assert data2["state"]["muted"] is True

        # POST restart
        req3 = MagicMock()
        req3.json = AsyncMock(return_value={"restore_playback": True})
        res3 = await post_restart_endpoint(req3)
        assert res3.status_code == 200
        data3 = json.loads(res3.body.decode())
        assert data3["status"] == "ok"
        assert "health" in data3
        assert "audio" in data3

    asyncio.run(_test())


def test_media_state_ingestion_and_control_endpoint():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    import dashboard.server as srv

    state = srv.DashboardState()

    # 1. Ingest media packet
    media_data = {
        "state": "play",
        "source": "mpd",
        "title": "Telegraph Road",
        "artist": "Dire Straits",
        "album": "Love over Gold",
        "elapsed": 124.0,
        "duration": 859.0,
        "outputs": {
            "inside": True,
            "outside": True,
            "both": True,
        }
    }
    state.record_packet("paeraki/media/state", json.dumps(media_data))
    assert state.media["state"] == "play"
    assert state.media["title"] == "Telegraph Road"
    assert state.media["artist"] == "Dire Straits"
    assert state.media["outputs"]["inside"] is True

    # 2. Check snapshot
    snap = state.get_snapshot()
    assert "media" in snap
    assert snap["media"]["title"] == "Telegraph Road"

    # 3. Test API endpoint
    app = srv.create_app("", 0)
    srv.state.publish = AsyncMock()

    control_endpoint = None
    for route in app.routes:
        if getattr(route, "path", None) == "/api/media/control":
            control_endpoint = route.endpoint

    assert control_endpoint is not None

    async def _test():
        req = MagicMock()
        req.json = AsyncMock(return_value={"command": "play_pause"})
        res = await control_endpoint(req)
        assert res.status_code == 200
        data = json.loads(res.body.decode())
        assert data["status"] == "ok"
        assert data["command"] == "play_pause"
        assert srv.state.publish.called

    asyncio.run(_test())


def test_barometer_stale_handling():
    import dashboard.server as srv
    state = srv.DashboardState()

    # Initial state should have last known value and be flagged stale
    assert state.seatalkng_environment["pressure_hpa"] == 998.6
    assert state.seatalkng_environment["is_stale"] is True
    assert state.seatalkng_environment["trend"] == "STale"

    # Ingest live packet with valid pressure
    live_pkt = {"pressure_hpa": 1013.2}
    state.record_packet("paeraki/seatalkng/state", json.dumps(live_pkt))
    assert state.seatalkng_environment["pressure_hpa"] == 1013.2
    assert state.seatalkng_environment["is_stale"] is False
    assert state.seatalkng_environment["trend"] == "Steady"

    # Ingest packet with null pressure (sensor offline/no frames)
    offline_pkt = {"pressure_hpa": None}
    state.record_packet("paeraki/seatalkng/state", json.dumps(offline_pkt))
    # Last known pressure preserved, flagged stale
    assert state.seatalkng_environment["pressure_hpa"] == 1013.2
    assert state.seatalkng_environment["is_stale"] is True
    assert state.seatalkng_environment["trend"] == "STale"
