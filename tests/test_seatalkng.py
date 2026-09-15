"""
Unit tests for SeaTalkNG / NMEA 2000 decoder engine.
Tests live captured packet frames, Fast Packet reassembly, and novel PGN fallback.
"""

import struct
import pytest
from seatalkng.decoder import (
    CanFrame,
    FastPacketReassembler,
    UniversalDecoder,
    calculate_range_bearing,
    parse_can_id,
    decode_pgn_129025,
    decode_pgn_129026,
    decode_pgn_127250,
    decode_pgn_127257,
    decode_pgn_127251,
    decode_pgn_129038,
    decode_pgn_129039,
    decode_pgn_129809,
    decode_pgn_130314,
)


def test_parse_can_id():
    # Test PGN 129025 (0x01F801) from source 0x16, prio 2 -> CAN ID: 0x09F80116
    can_id = 0x09F80116
    prio, dp, pf, ps, sa, dst, pgn = parse_can_id(can_id)
    assert prio == 2
    assert dp == 1
    assert pf == 0xF8
    assert sa == 0x16
    assert pgn == 129025
    assert dst == 0xFF  # Broadcast (pf >= 240)

    # Test PDU1 Addressable (e.g. ISO Request PF=0xEA, dest=0xCC, src=0x85, prio=6)
    # CAN ID: (6 << 26) | (0 << 24) | (0xEA << 16) | (0xCC << 8) | 0x85
    can_id_req = (6 << 26) | (0xEA << 16) | (0xCC << 8) | 0x85
    prio, dp, pf, ps, sa, dst, pgn = parse_can_id(can_id_req)
    assert prio == 6
    assert pf == 0xEA
    assert sa == 0x85
    assert dst == 0xCC
    assert pgn == 59904


def test_decode_pgn_129025_rapid_position():
    # Live sample: 24 70 02 e6 67 36 f2 66
    payload = bytes.fromhex("24 70 02 e6 67 36 f2 66")
    res = decode_pgn_129025(payload)
    assert res["latitude"] == pytest.approx(-43.6047836, abs=1e-5)
    assert res["longitude"] == pytest.approx(172.7149671, abs=1e-5)


def test_decode_pgn_129026_cog_sog():
    # Live sample: 9c fc c1 44 00 00 ff ff
    payload = bytes.fromhex("9c fc c1 44 00 00 ff ff")
    res = decode_pgn_129026(payload)
    assert res["sid"] == 0x9C
    assert res["cog_reference"] == "True"
    assert res["cog_true"] == pytest.approx(100.8, abs=0.2)
    assert res["sog_knots"] == 0.0


def test_decode_pgn_127250_heading():
    # Live sample: ff a0 66 ff 7f ff 7f fd
    payload = bytes.fromhex("ff a0 66 ff 7f ff 7f fd")
    res = decode_pgn_127250(payload)
    assert res["heading_deg"] == pytest.approx(150.5, abs=0.2)
    assert res["reference"] == "Magnetic"


def test_decode_pgn_127257_attitude():
    # Live sample: ff a0 66 5d 01 99 fe ff
    payload = bytes.fromhex("ff a0 66 5d 01 99 fe ff")
    res = decode_pgn_127257(payload)
    assert res["pitch_deg"] == pytest.approx(2.00, abs=0.1)
    assert res["roll_deg"] == pytest.approx(-2.06, abs=0.1)


def test_decode_pgn_127251_rate_of_turn():
    # Live sample: raw rot = 54400 -> ~3.11 deg/s
    payload = struct.pack("<Bi", 0xFF, 54400)
    res = decode_pgn_127251(payload)
    assert res["rate_of_turn_dps"] == pytest.approx(3.12, abs=0.1)


def test_decode_pgn_130314_pressure():
    # Live sample: bf 00 00 70 7b 0f 00 ff
    payload = bytes.fromhex("bf 00 00 70 7b 0f 00 ff")
    res = decode_pgn_130314(payload)
    assert res["pressure_hpa"] == pytest.approx(1014.6, abs=0.5)


def test_fast_packet_reassembly_and_ais_class_a():
    # Live PGN 129038 captured in dump_ais:
    # 01 41 9f 84 1e 6a 50 f3 66 4c 4e 02 e6 35 ff ff 00 00 12 12 00 7e 16 00 00 cf f8 ff
    full_payload = bytes.fromhex("01 41 9f 84 1e 6a 50 f3 66 4c 4e 02 e6 35 ff ff 00 00 12 12 00 7e 16 00 00 cf f8 ff")
    assert len(full_payload) == 28

    # Frame 0: header (seq 0 | frame 0) = 0x00, total = 28, 6 data bytes
    f0 = bytes([0x00, 28]) + full_payload[:6]
    # Frame 1: header (seq 0 | frame 1) = 0x01, 7 data bytes
    f1 = bytes([0x01]) + full_payload[6:13]
    # Frame 2: header (seq 0 | frame 2) = 0x02, 7 data bytes
    f2 = bytes([0x02]) + full_payload[13:20]
    # Frame 3: header (seq 0 | frame 3) = 0x03, 7 data bytes
    f3 = bytes([0x03]) + full_payload[20:27]
    # Frame 4: header (seq 0 | frame 4) = 0x04, 1 data byte + 6 padding
    f4 = bytes([0x04]) + full_payload[27:28] + b"\xFF" * 6

    reassembler = FastPacketReassembler()
    assert reassembler.push_frame(129038, 0x16, f0) is None
    assert reassembler.push_frame(129038, 0x16, f1) is None
    assert reassembler.push_frame(129038, 0x16, f2) is None
    assert reassembler.push_frame(129038, 0x16, f3) is None
    assembled = reassembler.push_frame(129038, 0x16, f4)
    assert assembled == full_payload

    # Decode assembled AIS Class A
    ais = decode_pgn_129038(assembled)
    assert ais["ais_class"] == "A"
    assert ais["mmsi"] == 512008001
    assert ais["latitude"] == pytest.approx(-43.60565, abs=1e-4)
    assert ais["longitude"] == pytest.approx(172.72218, abs=1e-4)
    assert ais["sog_knots"] == 0.0


def test_decode_pgn_129809_vessel_name():
    # MMSI 512010966, Name: 'KOKAHA' padded with 0xFF
    mmsi_bytes = struct.pack("<I", 512010966)
    name_bytes = b"KOKAHA" + b"\xFF" * 14
    payload = bytes([0x18]) + mmsi_bytes + name_bytes
    res = decode_pgn_129809(payload)
    assert res["mmsi"] == 512010966
    assert res["vessel_name"] == "KOKAHA"


def test_universal_decoder_novel_pgn_fallback():
    decoder = UniversalDecoder()
    novel_payload = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88])
    frame = CanFrame(
        can_id=0x19FFFF00,
        priority=6,
        data_page=1,
        pdu_format=0xFF,
        pdu_specific=0xFF,
        source=0x00,
        destination=0xFF,
        pgn=131071,
        payload=novel_payload,
    )
    record = decoder.process_frame(frame)
    assert record is not None
    assert record["pgn"] == 131071
    assert record["decoded"] is False
    assert record["hex"] == "1122334455667788"
    assert record["bytes"] == [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]


def test_range_bearing_calculation():
    # Paeraki at (-43.60478, 172.71496)
    # Target 0.5 NM due North
    dist, bearing = calculate_range_bearing(-43.60478, 172.71496, -43.59645, 172.71496)
    assert dist == pytest.approx(0.5, abs=0.05)
    assert bearing == pytest.approx(0.0, abs=1.0)
