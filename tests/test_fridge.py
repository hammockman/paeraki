"""
Unit tests for Brass Monkey / Alpicool BLE fridge monitoring subsystem.
"""

from unittest.mock import AsyncMock
import pytest

from fridge.protocol import (
    FridgeCommand,
    FridgeRunMode,
    FridgeBatterySaver,
    create_packet,
    decode_fridge_packet,
    encode_query_packet,
    encode_set_left_target,
    encode_set_right_target,
    verify_packet,
)
from fridge.watch import get_mock_telemetry, publish_fridge_telemetry


# Live notification frame captured on board Paeraki
LIVE_PACKET_HEX = "fefe2101000101010514ec020000fdfdfd0003640d0204000002fdfdfd00040000000996"


def test_verify_and_decode_live_packet():
    raw = bytes.fromhex(LIVE_PACKET_HEX)
    assert verify_packet(raw) is True

    telemetry = decode_fridge_packet(raw)
    assert telemetry is not None
    assert telemetry.powered_on is True
    assert telemetry.controls_locked is False
    assert telemetry.run_mode == "Eco"
    assert telemetry.battery_saver == "Mid"
    assert telemetry.battery_voltage == 13.2
    assert telemetry.battery_percent == 100
    assert telemetry.temperature_unit == "Celsius"
    assert telemetry.compressor_running is False
    assert telemetry.running_status_code == 0

    # Left Zone (Unit 1)
    assert telemetry.left_zone.current_temperature == 3
    assert telemetry.left_zone.target_temperature == 5
    assert telemetry.left_zone.hysteresis == 2

    # Right Zone (Unit 2)
    assert telemetry.right_zone is not None
    assert telemetry.right_zone.current_temperature == 4
    assert telemetry.right_zone.target_temperature == 4
    assert telemetry.right_zone.hysteresis == 2


def test_packet_creation_and_verification():
    query_pkt = encode_query_packet()
    assert query_pkt[:2] == b"\xFE\xFE"
    assert query_pkt[2] == 3  # length byte
    assert query_pkt[3] == FridgeCommand.QUERY
    assert verify_packet(query_pkt) is True

    left_set = encode_set_left_target(-18)
    assert verify_packet(left_set) is True
    assert left_set[3] == FridgeCommand.SET_LEFT_TARGET
    assert left_set[4] == 0xEE  # -18 signed byte (256 - 18 = 238 = 0xEE)

    right_set = encode_set_right_target(4)
    assert verify_packet(right_set) is True
    assert right_set[3] == FridgeCommand.SET_RIGHT_TARGET
    assert right_set[4] == 4


def test_decode_negative_temperatures():
    # Construct a packet with sub-zero freezer temperature (-18°C)
    # Payload: locked=0, on=1, mode=0(Max), saver=2(High)
    # Left: target=-18, max=20, min=-20, hyst=2, delay=0, unit=0, corr=(-3,-3,-3,0), current=-17
    # Batt: 100%, 12V, 8 (12.8V)
    # Right: target=-20, padding(0,0), hyst=2, corr=(-3,-3,-3,0), current=-19
    # status: 0, running_status: 1 (Compressor Running)
    import struct
    payload = struct.pack(
        ">BBBB bbbbbb bbbb b BBB b bb b bbbb b BBB",
        0, 1, 0, 2,  # locked, on, mode, saver (4)
        -18, 20, -20, 2, 0, 0,  # target, max, min, hyst, delay, unit (6)
        -3, -3, -3, 0,  # corrections (4)
        -17,  # current (1)
        100, 12, 8,  # battery % (1), V int (1), V frac (1) -> (3)
        -20,  # right target (1)
        0, 0,  # padding (2)
        2,  # right hyst (1)
        -3, -3, -3, 0,  # right corrections (4)
        -19,  # right current (1)
        0, 1, 0  # status (1), running_status=1 (1), error_code=0 (1) -> (3)
    )
    assert len(payload) == 30
    pkt = create_packet(bytes([FridgeCommand.QUERY]) + payload)
    assert verify_packet(pkt) is True

    telemetry = decode_fridge_packet(pkt)
    assert telemetry is not None
    assert telemetry.run_mode == "Max"
    assert telemetry.battery_saver == "High"
    assert telemetry.battery_voltage == 12.8
    assert telemetry.compressor_running is True
    assert telemetry.left_zone.current_temperature == -17
    assert telemetry.left_zone.target_temperature == -18
    assert telemetry.right_zone.current_temperature == -19
    assert telemetry.right_zone.target_temperature == -20


def test_invalid_packets():
    assert verify_packet(b"") is False
    assert verify_packet(b"\x00\x00\x03\x01\x00\x00") is False  # bad magic
    assert verify_packet(b"\xFE\xFE\x05\x01\x00") is False  # too short
    # Corrupt checksum
    corrupt = bytearray(bytes.fromhex(LIVE_PACKET_HEX))
    corrupt[-1] ^= 0xFF
    assert verify_packet(bytes(corrupt)) is False
    assert decode_fridge_packet(bytes(corrupt)) is None


def test_dry_run_telemetry_structure():
    mock_data = get_mock_telemetry()
    assert "timestamp" in mock_data
    assert mock_data["battery_voltage"] == 13.2
    assert "left_zone" in mock_data
    assert "right_zone" in mock_data
    assert mock_data["left_zone"]["current_temperature"] == 3
    assert mock_data["right_zone"]["current_temperature"] == 4


def test_publish_fridge_telemetry():
    import asyncio
    mock_client = AsyncMock()
    telemetry = get_mock_telemetry()
    asyncio.run(publish_fridge_telemetry(mock_client, telemetry))

    # Check published topics
    published_topics = [call.args[0] for call in mock_client.publish.call_args_list]
    assert "paeraki/fridge/state" in published_topics
    assert "paeraki/fridge/left/temperature" in published_topics
    assert "paeraki/fridge/left/target" in published_topics
    assert "paeraki/fridge/right/temperature" in published_topics
    assert "paeraki/fridge/voltage" in published_topics
    assert "paeraki/fridge/compressor" in published_topics
    assert "paeraki/fridge/mode" in published_topics
