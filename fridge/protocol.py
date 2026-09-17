"""
Protocol parser and packet codec for Alpicool / Brass Monkey dual-zone fridges.
Reverse-engineered Bluetooth Low Energy (BLE) GATT framing:
  Service UUID:   00001234-0000-1000-8000-00805f9b34fb
  Command (Write): 00001235-0000-1000-8000-00805f9b34fb
  Notify (Read):  00001236-0000-1000-8000-00805f9b34fb
"""

from __future__ import annotations

import struct
from dataclasses import asdict, dataclass
from enum import IntEnum
from typing import Optional

SERVICE_UUID = "00001234-0000-1000-8000-00805f9b34fb"
CHAR_WRITE_UUID = "00001235-0000-1000-8000-00805f9b34fb"
CHAR_NOTIFY_UUID = "00001236-0000-1000-8000-00805f9b34fb"


class FridgeCommand(IntEnum):
    BIND = 0x00
    QUERY = 0x01
    SET = 0x02
    RESET = 0x04
    SET_LEFT_TARGET = 0x05
    SET_RIGHT_TARGET = 0x06


class FridgeRunMode(IntEnum):
    MAX = 0
    ECO = 1


class FridgeBatterySaver(IntEnum):
    LOW = 0
    MID = 1
    HIGH = 2


class FridgeTemperatureUnit(IntEnum):
    CELSIUS = 0
    FAHRENHEIT = 1


@dataclass
class FridgeZoneData:
    """Telemetry for a single temperature zone (Left or Right)."""
    current_temperature: int
    target_temperature: int
    hysteresis: int = 2
    temp_correction_hot: int = 0
    temp_correction_mid: int = 0
    temp_correction_cold: int = 0
    temp_correction_halt: int = 0


@dataclass
class FridgeTelemetry:
    """Consolidated telemetry frame from Brass Monkey fridge."""
    powered_on: bool
    controls_locked: bool
    run_mode: str
    battery_saver: str
    battery_voltage: float
    battery_percent: int
    temperature_unit: str
    compressor_running: bool
    running_status_code: int
    left_zone: FridgeZoneData
    right_zone: Optional[FridgeZoneData] = None

    def to_dict(self) -> dict:
        """Serializes telemetry into JSON-compatible dictionary."""
        d = {
            "powered_on": self.powered_on,
            "controls_locked": self.controls_locked,
            "run_mode": self.run_mode,
            "battery_saver": self.battery_saver,
            "battery_voltage": self.battery_voltage,
            "battery_percent": self.battery_percent,
            "temperature_unit": self.temperature_unit,
            "compressor_running": self.compressor_running,
            "running_status_code": self.running_status_code,
            "left_zone": asdict(self.left_zone),
        }
        if self.right_zone is not None:
            d["right_zone"] = asdict(self.right_zone)
        return d


def create_packet(payload: bytes) -> bytes:
    """
    Wraps command payload into Alpicool frame:
      [0xFE, 0xFE, length (len(payload)+2), payload..., checksum_high, checksum_low]
    Checksum is 16-bit big-endian sum of all preceding bytes.
    """
    frame = b"\xFE\xFE" + struct.pack("B", len(payload) + 2) + payload
    checksum = sum(frame) & 0xFFFF
    return frame + struct.pack(">H", checksum)


def verify_packet(packet: bytes) -> bool:
    """Verifies header, length, and 16-bit checksum."""
    if len(packet) < 6:
        return False
    if packet[:2] != b"\xFE\xFE":
        return False
    pkt_len = packet[2]
    if pkt_len != len(packet) - 3:
        return False
    expected_csum = struct.unpack_from(">H", packet, len(packet) - 2)[0]
    calc_csum = sum(packet[:-2]) & 0xFFFF
    return expected_csum in (calc_csum, (calc_csum * 2) & 0xFFFF)


def encode_query_packet() -> bytes:
    """Constructs the Query (0x01) status packet."""
    return create_packet(bytes([FridgeCommand.QUERY]))


def encode_set_left_target(temp_celsius: int) -> bytes:
    """Constructs command to set left zone target temperature."""
    return create_packet(struct.pack("Bb", FridgeCommand.SET_LEFT_TARGET, int(temp_celsius)))


def encode_set_right_target(temp_celsius: int) -> bytes:
    """Constructs command to set right zone target temperature."""
    return create_packet(struct.pack("Bb", FridgeCommand.SET_RIGHT_TARGET, int(temp_celsius)))


def decode_fridge_packet(packet: bytes) -> Optional[FridgeTelemetry]:
    """
    Parses a raw notification frame into a structured FridgeTelemetry object.
    Returns None if packet is invalid or not a status notification.
    """
    if not verify_packet(packet):
        return None

    cmd = packet[3]
    if cmd != FridgeCommand.QUERY and cmd != FridgeCommand.SET:
        return None

    data = packet[4:-2]
    if len(data) < 18:
        return None

    controls_locked = bool(data[0])
    powered_on = bool(data[1])
    mode_int = data[2]
    run_mode_str = "Eco" if mode_int == FridgeRunMode.ECO else "Max"

    saver_int = data[3]
    saver_map = {
        FridgeBatterySaver.LOW: "Low",
        FridgeBatterySaver.MID: "Mid",
        FridgeBatterySaver.HIGH: "High",
    }
    battery_saver_str = saver_map.get(saver_int, f"Level {saver_int}")

    # Left zone (Unit 1):
    left_target = struct.unpack_from("b", data, 4)[0]
    left_hysteresis = data[7]
    temp_unit_int = data[9]
    temp_unit_str = "Celsius" if temp_unit_int == FridgeTemperatureUnit.CELSIUS else "Fahrenheit"
    left_corr_hot, left_corr_mid, left_corr_cold, left_corr_halt = struct.unpack_from("bbbb", data, 10)
    left_current = struct.unpack_from("b", data, 14)[0]

    left_zone = FridgeZoneData(
        current_temperature=left_current,
        target_temperature=left_target,
        hysteresis=left_hysteresis,
        temp_correction_hot=left_corr_hot,
        temp_correction_mid=left_corr_mid,
        temp_correction_cold=left_corr_cold,
        temp_correction_halt=left_corr_halt,
    )

    # Battery voltage & charge:
    battery_percent = data[15]
    v_int = data[16]
    v_frac = data[17]
    battery_voltage = round(v_int + (v_frac / 10.0), 2)

    # Right zone (Unit 2, if present in packet >= 27 bytes):
    right_zone = None
    if len(data) >= 27:
        right_target = struct.unpack_from("b", data, 18)[0]
        right_hysteresis = data[21]
        right_corr_hot, right_corr_mid, right_corr_cold, right_corr_halt = struct.unpack_from("bbbb", data, 22)
        right_current = struct.unpack_from("b", data, 26)[0]
        right_zone = FridgeZoneData(
            current_temperature=right_current,
            target_temperature=right_target,
            hysteresis=right_hysteresis,
            temp_correction_hot=right_corr_hot,
            temp_correction_mid=right_corr_mid,
            temp_correction_cold=right_corr_cold,
            temp_correction_halt=right_corr_halt,
        )

    running_status = 0
    if len(data) >= 29:
        running_status = data[28]

    compressor_running = running_status > 0

    return FridgeTelemetry(
        powered_on=powered_on,
        controls_locked=controls_locked,
        run_mode=run_mode_str,
        battery_saver=battery_saver_str,
        battery_voltage=battery_voltage,
        battery_percent=battery_percent,
        temperature_unit=temp_unit_str,
        compressor_running=compressor_running,
        running_status_code=running_status,
        left_zone=left_zone,
        right_zone=right_zone,
    )
