import asyncio
import json
import pytest
from unittest.mock import patch, MagicMock

from cortex.client import CortexClient
from cortex.discovery import discover_cortex_host


def test_cortex_client_message_parsing():
    async def _run():
        client = CortexClient(host="127.0.0.1", port=8000)

        # 1. Token Handshake
        msg_token = '1:ChannelIdentifier{"token":"secret-token-123"}'
        await client._process_ws_message(msg_token)
        assert client.token == "secret-token-123"

        # 2. Active Alarms
        alarms_received = []
        client.on_alarms_update = lambda al: alarms_received.append(al)

        msg_alarm = '2:ActiveAlarm[{"id":"anchor_01","type":"AnchorDrag","severity":"critical","message":"Anchor dragging 45m"}]'
        await client._process_ws_message(msg_alarm)
        assert len(client.active_alarms) == 1
        assert "anchor_01" in client.active_alarms
        assert client.active_alarms["anchor_01"]["severity"] == "CRITICAL"
        assert client.active_alarms["anchor_01"]["silenced"] is False
        assert len(alarms_received) == 1

        # 3. Silence Affordance
        msg_affordance = '3:AlarmSilenceAffordance{"anchor_01":{"canSilence":true,"isSilenced":true}}'
        await client._process_ws_message(msg_affordance)
        assert client.active_alarms["anchor_01"]["silenced"] is True

        # 4. Anchor Watch Telemetry
        anchor_received = []
        client.on_anchor_update = lambda a: anchor_received.append(a)

        msg_anchor = '4:AnchorWatch{"enabled":true,"anchorLatitude":-36.8485,"anchorLongitude":174.7633,"radiusMeters":30.0,"currentDistanceMeters":12.5,"dragAlarmActive":false}'
        await client._process_ws_message(msg_anchor)
        assert client.anchor_state["active"] is True
        assert client.anchor_state["anchor_lat"] == -36.8485
        assert client.anchor_state["radius_m"] == 30.0
        assert client.anchor_state["distance_m"] == 12.5
        assert len(anchor_received) == 1

        # 5. Telemetry: Pressure & Voltage
        telemetry_received = []
        client.on_telemetry_update = lambda t: telemetry_received.append(t)

        await client._process_ws_message('5:BatteryVoltage{"voltage":13.1}')
        assert client.telemetry["battery_v"] == 13.1

        await client._process_ws_message('6:BarometricPressure{"pressure":1015.3}')
        assert client.telemetry["pressure_hpa"] == 1015.3
        assert len(telemetry_received) == 2

    asyncio.run(_run())


def test_cortex_client_silence_alarm():
    async def _run():
        client = CortexClient(host="127.0.0.1", port=8000)
        client.token = "test-token"
        client.active_alarms["test_alarm_99"] = {
            "id": "test_alarm_99",
            "type": "CPA",
            "silenced": False,
        }

        with patch.object(client, "_http_get_sync", return_value={"status": "ok"}):
            ok, msg = await client.silence_alarm("test_alarm_99")
            assert ok is True
            assert client.active_alarms["test_alarm_99"]["silenced"] is True

    asyncio.run(_run())


def test_cortex_discovery_fallback():
    async def _run():
        # If probe fails, it should fall back to default static IP 192.168.1.50
        with patch("cortex.discovery.probe_tcp_port_async", return_value=False):
            host = await discover_cortex_host()
            assert host == "192.168.1.50"

        # If preferred host is given and probe succeeds, return it
        with patch("cortex.discovery.probe_tcp_port_async", return_value=True):
            host = await discover_cortex_host(preferred_host="192.168.1.99")
            assert host == "192.168.1.99"

    asyncio.run(_run())

