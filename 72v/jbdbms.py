# JBD BMS Protocol Parser
# Supports both BLE GATT notifications and Serial RS485/UART communication

import struct
from datetime import datetime
from enum import Enum

## Constants
BASIC_INFO_QUERY = b'\xdd\xa5\x03\x00\xff\xfd\x77'
CELL_VOLTAGES_QUERY = b'\xdd\xa5\x04\x00\xff\xfc\x77'

# Static boilerplate part of basic info. For every available NTC temp sensor, a 'H' is appended.
_basic_info_boilerplate = ">HhHHHHIHcBBBB"


class ProtectionState(Enum):
    SINGLE_OVERVOLTAGE = 0
    SINGLE_UNDERVOLTAGE = 1
    PACK_OVERVOLTAGE = 2
    PACK_UNDERVOLTAGE = 3
    CHARGE_OVER_TEMPERATURE = 4
    CHARGE_UNDER_TEMPERATURE = 5
    DISCHARGE_OVER_TEMPERATURE = 6
    DISCHARGE_UNDER_TEMPERATURE = 7
    CHARGE_OVER_CURRENT = 8
    DISCHARGE_OVER_CURRENT = 9
    SHORT_CIRCUIT = 10
    FRONT_DETECTION_IC_ERROR = 11
    MOS_SOFTWARE_LOCK = 12


def calculate_checksum(length: int, data: bytes | bytearray) -> int:
    """Takes data bytes and calculates the 16-bit JBD checksum."""
    return ((sum(data) + length - 1) ^ 0xFFFF) & 0xFFFF


def check_checksum(data: bytes | bytearray) -> bool:
    """Compares the checksum extracted from response (-3:-1) with calculated checksum."""
    if len(data) < 7:
        return False
    length = data[3]
    received_checksum, = struct.unpack(">H", data[-3:-1])
    calculated_checksum = calculate_checksum(length, data[4:-3])
    return received_checksum == calculated_checksum


def validate_response(query: bytes | bytearray, response: bytes | bytearray) -> None:
    """Validates that the response header, status byte, register, and checksum are valid."""
    if len(response) < 7:
        raise ValueError(f"Response too short ({len(response)} bytes)")
    if response[0] != 0xDD or response[-1] != 0x77:
        raise ValueError("Invalid framing bytes (expected 0xDD start and 0x77 end)")
    if response[1] != query[2]:
        raise ValueError(f"Register mismatch: expected 0x{query[2]:02X}, got 0x{response[1]:02X}")
    if response[2] != 0:
        raise ValueError(f"BMS reported error code: 0x{response[2]:02X}")
    if not check_checksum(response):
        raise ValueError("Checksum mismatch")


def value_to_date(value: int) -> datetime:
    """Unpacks two bytes into date according to JBD documentation."""
    year = 2000 + (value >> 9)
    month = (value >> 5) & 0x0F
    day = value & 0x1F
    # Clamp month/day to valid range in case of uninitialized memory
    month = max(1, min(12, month))
    day = max(1, min(31, day))
    return datetime(year, month, day)


def value_to_protection_state(value: int) -> list[ProtectionState]:
    """Extracts active protection states from 16-bit bitmask."""
    active_states = []
    if value != 0:
        for bit in range(16):
            if value & (1 << bit):
                try:
                    active_states.append(ProtectionState(bit))
                except ValueError:
                    pass
    return active_states


def value_to_balance_state(value: int, number_of_cells: int) -> list[bool]:
    """Decodes balancing status for each cell from bitmask."""
    balance_states = []
    for cell in range(number_of_cells):
        balance_states.append(bool(value & (1 << cell)))
    return balance_states


def parse_basic_info(data: bytes | bytearray) -> dict:
    """Parses a verified basic info response packet (0x03) into a dictionary."""
    if len(data) < 27:
        raise ValueError(f"Basic info data packet too short: {len(data)} bytes")

    number_of_cells = data[25]
    number_of_ntcs = data[26]

    struct_format = _basic_info_boilerplate + (number_of_ntcs * "H")
    expected_payload_len = struct.calcsize(struct_format)
    actual_payload = data[4:-3]

    if len(actual_payload) < expected_payload_len:
        raise ValueError(f"Payload length {len(actual_payload)} less than expected {expected_payload_len}")

    unpacked = struct.unpack(struct_format, actual_payload[:expected_payload_len])

    total_voltage = round(unpacked[0] / 100.0, 2)       # 10mV units -> Volts
    current = round(unpacked[1] / 100.0, 2)             # 10mA units -> Amperes
    power = round(total_voltage * current, 2)           # Watts (positive = charge, negative = discharge)
    residual_capacity = round(unpacked[2] / 100.0, 2)   # 10mAh units -> Ah
    nominal_capacity = round(unpacked[3] / 100.0, 2)    # 10mAh units -> Ah
    cycle_times = unpacked[4]
    manufacturing_date = value_to_date(unpacked[5])
    balance_states = value_to_balance_state(unpacked[6], number_of_cells)
    protection_states = [s.name for s in value_to_protection_state(unpacked[7])]
    rsoc = unpacked[9]                                  # Remaining State of Charge %
    fet_status = unpacked[10]
    discharge_status = bool(fet_status & 0x02)          # Bit 1 = Discharge MOS
    charge_status = bool(fet_status & 0x01)             # Bit 0 = Charge MOS
    temperatures = [round((raw - 2731) / 10.0, 1) for raw in unpacked[13:13 + number_of_ntcs]]

    return {
        "total_voltage": total_voltage,
        "current": current,
        "power": power,
        "residual_capacity_ah": residual_capacity,
        "nominal_capacity_ah": nominal_capacity,
        "cycle_times": cycle_times,
        "rsoc": rsoc,
        "charge_status": charge_status,
        "discharge_status": discharge_status,
        "temperatures": temperatures,
        "active_protection_states": protection_states,
        "balance_states": balance_states,
        "number_of_cells": number_of_cells,
        "manufacturing_date": manufacturing_date.strftime("%Y-%m-%d"),
    }


def parse_cell_voltages(data: bytes | bytearray) -> list[float]:
    """Parses a verified cell voltages response packet (0x04) into a list of cell voltages (Volts)."""
    payload_len = data[3]
    num_cells = payload_len // 2
    actual_payload = data[4:-3]
    struct_format = ">" + (num_cells * "H")
    raw_voltages = struct.unpack(struct_format, actual_payload[:num_cells * 2])
    return [round(raw / 1000.0, 3) for raw in raw_voltages]


def debug_query(query: bytes) -> bytes:
    """Returns synthetic recorded query responses for offline testing."""
    if query == BASIC_INFO_QUERY:
        return b'\xdd\x03\x00\x1b\x05\x4c\x00\x00\x24\xf2\x2a\xf8\x00\x00\x28\xd2\x00\x00\x00\x00\x00\x00\x17\x56\x03\x04\x02\x09\x7f\x0b\xa9\xfa\xb0\x77'
    elif query == CELL_VOLTAGES_QUERY:
        return b'\xdd\x04\x00\x08\x0d\x42\x0d\x3c\x0d\x40\x0d\x3a\xfe\xcc\x77'
    else:
        raise ValueError(f"Invalid query: {query}")


# Backward-compatible Serial BMS class
class BMS:
    def __init__(self, serial_port: str = "", query_retries: int = 3, offline: bool = False):
        self.__debug = offline
        self.__query_retries = query_retries
        self.__connection = None
        if not offline:
            import serial
            self.__connection = serial.Serial(
                port=serial_port,
                timeout=1,
                baudrate=9600,
                parity=serial.PARITY_EVEN,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS
            )

        self.total_voltage = -1.0
        self.current = -1.0
        self.residual_capacity = -1.0
        self.nominal_capacity = -1.0
        self.cycle_times = -1
        self.manufacturing_date = datetime.now()
        self.rsoc = -1
        self.balance_states = []
        self.active_protection_states = []
        self.discharge_status = False
        self.charge_status = False
        self.cell_voltages = []
        self.temperatures = []
        self.number_of_cells = -1

        self.query_all()

    def __query_bms(self, query: bytes) -> bytes:
        if self.__debug:
            return debug_query(query)

        response = bytearray()
        retries = 0
        while len(response) < 4:
            self.__connection.write(query)
            response.extend(self.__connection.read(4))
            retries += 1
            if retries > self.__query_retries:
                raise ValueError("Could not get response from BMS")

        length = response[3]
        response.extend(self.__connection.read(length + 3))
        return bytes(response)

    def query_all(self):
        self.query_basic_info()
        self.query_cell_voltages()

    def query_basic_info(self):
        response = self.__query_bms(BASIC_INFO_QUERY)
        validate_response(BASIC_INFO_QUERY, response)
        info = parse_basic_info(response)
        self.total_voltage = info["total_voltage"]
        self.current = info["current"]
        self.residual_capacity = info["residual_capacity_ah"]
        self.nominal_capacity = info["nominal_capacity_ah"]
        self.cycle_times = info["cycle_times"]
        self.rsoc = info["rsoc"]
        self.charge_status = info["charge_status"]
        self.discharge_status = info["discharge_status"]
        self.temperatures = info["temperatures"]
        self.active_protection_states = info["active_protection_states"]
        self.balance_states = info["balance_states"]
        self.number_of_cells = info["number_of_cells"]

    def query_cell_voltages(self):
        response = self.__query_bms(CELL_VOLTAGES_QUERY)
        validate_response(CELL_VOLTAGES_QUERY, response)
        self.cell_voltages = parse_cell_voltages(response)
