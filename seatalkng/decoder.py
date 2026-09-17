"""
Universal SeaTalkNG / NMEA 2000 framing, Fast-Packet reassembly, and message decoder.
Handles all CAN frames arriving via PUSR USR-CAN115 Ethernet-to-CAN converter.
Decodes known PGNs into structured dictionaries and provides universal raw fallback
for novel or unmapped PGNs.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import struct
from typing import Any, Callable, Dict, List, Optional, Tuple


# Known NMEA 2000 PGN descriptions
PGN_CATALOG: Dict[int, str] = {
    59392: "ISO Acknowledgment",
    59904: "ISO Request",
    60160: "ISO Transport Protocol - Data Transfer",
    60416: "ISO Transport Protocol - Connection Management",
    60928: "ISO Address Claim",
    65240: "ISO Commanded Address",
    65359: "Seatalk: Pilot Heading (Proprietary)",
    65379: "Seatalk: Pilot Mode (Proprietary)",
    65384: "Seatalk: Pilot Target / Wind Datum (Proprietary)",
    126208: "NMEA Request / Command / Acknowledge Group Function",
    126720: "Seatalk: Autopilot Control / Command (Proprietary)",
    126983: "Alert",
    126984: "Alert Response / Silence",
    126985: "Alert Text",
    126992: "System Time",
    126996: "Product Information",
    126998: "Configuration Information",
    127233: "Man Overboard Notification",
    127245: "Rudder",
    127250: "Vessel Heading",
    127251: "Rate of Turn",
    127257: "Attitude (Pitch / Roll / Yaw)",
    127258: "Magnetic Variation",
    127488: "Engine Parameters, Rapid Update",
    127489: "Engine Parameters, Dynamic",
    127505: "Fluid Level",
    127506: "DC Detailed Status",
    127508: "Battery Status",
    128259: "Speed, Water Referenced",
    128267: "Water Depth",
    128275: "Distance Log",
    129025: "Position, Rapid Update (Lat/Lon)",
    129026: "COG & SOG, Rapid Update",
    129029: "GNSS Position Data",
    129038: "AIS Class A Position Report",
    129039: "AIS Class B Position Report",
    129040: "AIS Extended Position Report",
    129041: "AIS Aids to Navigation (AtoN) Report",
    129539: "GNSS DOPs",
    129540: "GNSS Satellites in View",
    129794: "AIS Class A Static and Voyage Related Data",
    129809: "AIS Class B CS Static Report, Part A",
    129810: "AIS Class B CS Static Report, Part B",
    130306: "Wind Data",
    130310: "Environmental Parameters",
    130311: "Environmental Parameters (Old)",
    130314: "Actual Pressure",
    130916: "EV-1 Calibration / Diagnostics (Proprietary)",
}

# Multi-frame Fast Packet PGN list
FAST_PACKET_PGNS = {
    126983, 126985, 126996, 126998, 127233, 129029, 129038, 129039, 129040, 129041,
    129540, 129794, 129809, 129810, 126720
}

# Navigational Status labels for AIS
AIS_NAV_STATUS = {
    0: "Under way using engine",
    1: "At anchor",
    2: "Not under command",
    3: "Restricted manoeuvrability",
    4: "Constrained by her draught",
    5: "Moored",
    6: "Aground",
    7: "Engaged in fishing",
    8: "Under way sailing",
    9: "Reserved for HSC",
    10: "Reserved for WIG",
    11: "Power-driven vessel towing astern",
    12: "Power-driven vessel pushing ahead or towing alongside",
    13: "Reserved for future use",
    14: "AIS-SART (active)",
    15: "Undefined / Default",
}


@dataclass
class CanFrame:
    """Represents a single raw CAN frame."""
    can_id: int
    priority: int
    data_page: int
    pdu_format: int
    pdu_specific: int
    source: int
    destination: int
    pgn: int
    payload: bytes
    timestamp: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())


def parse_can_id(can_id: int) -> Tuple[int, int, int, int, int, int, int]:
    """
    Decodes 29-bit CAN ID into NMEA 2000 components:
    (priority, data_page, pdu_format, pdu_specific, source, destination, pgn)
    """
    priority = (can_id >> 26) & 0x07
    data_page = (can_id >> 24) & 0x01
    pdu_format = (can_id >> 16) & 0xFF
    pdu_specific = (can_id >> 8) & 0xFF
    source = can_id & 0xFF

    if pdu_format < 240:
        # PDU1: Addressable (PDU Specific is Destination Address)
        destination = pdu_specific
        pgn = (data_page << 16) | (pdu_format << 8)
    else:
        # PDU2: Broadcast (PDU Specific is Group Extension)
        destination = 0xFF
        pgn = (data_page << 16) | (pdu_format << 8) | pdu_specific

    return priority, data_page, pdu_format, pdu_specific, source, destination, pgn


class FastPacketReassembler:
    """Reassembles multi-frame NMEA 2000 Fast Packets."""

    def __init__(self, timeout_sec: float = 0.8):
        self.timeout_sec = timeout_sec
        # Key: (pgn, source, sequence) -> {'total': int, 'data': bytearray, 'updated': float}
        self.assemblies: Dict[Tuple[int, int, int], Dict[str, Any]] = {}

    def push_frame(self, pgn: int, source: int, payload: bytes) -> Optional[bytes]:
        """
        Processes a frame payload. Returns complete assembled bytes if finished,
        or None if more frames are required.
        """
        now = datetime.now(timezone.utc).timestamp()
        self._cleanup(now)

        if len(payload) < 2:
            return None

        header = payload[0]
        sequence = (header >> 5) & 0x07
        frame_idx = header & 0x1F
        key = (pgn, source, sequence)

        if frame_idx == 0:
            total_bytes = payload[1]
            data_bytes = payload[2:]
            self.assemblies[key] = {
                "total": total_bytes,
                "data": bytearray(data_bytes),
                "updated": now,
            }
            if len(data_bytes) >= total_bytes:
                res = self.assemblies.pop(key)["data"][:total_bytes]
                return bytes(res)
            return None

        if key in self.assemblies:
            entry = self.assemblies[key]
            entry["data"].extend(payload[1:])
            entry["updated"] = now
            if len(entry["data"]) >= entry["total"]:
                res = self.assemblies.pop(key)["data"][:entry["total"]]
                return bytes(res)

        return None

    def _cleanup(self, now: float):
        """Drops abandoned multi-frame assemblies older than timeout."""
        stale = [k for k, v in self.assemblies.items() if now - v["updated"] > self.timeout_sec]
        for k in stale:
            del self.assemblies[k]


def calculate_range_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> Tuple[float, float]:
    """
    Calculates great-circle distance in nautical miles and initial True bearing in degrees
    between vessel (lat1, lon1) and target (lat2, lon2).
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    # Haversine distance
    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    distance_nm = (6371000.0 * c) / 1852.0  # Nautical miles

    # Initial bearing
    y = math.sin(delta_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
    bearing_deg = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0

    return round(distance_nm, 2), round(bearing_deg, 1)


# ============================================================================
# Specific PGN Field Decoders
# ============================================================================

def decode_pgn_129025(payload: bytes) -> Dict[str, Any]:
    """PGN 129025: Position, Rapid Update (Lat/Lon)."""
    if len(payload) < 8:
        raise ValueError("PGN 129025 payload under 8 bytes")
    raw_lat, raw_lon = struct.unpack("<ii", payload[:8])
    lat = raw_lat * 1e-7 if raw_lat != 0x7FFFFFFF else None
    lon = raw_lon * 1e-7 if raw_lon != 0x7FFFFFFF else None
    return {
        "latitude": round(lat, 7) if lat is not None else None,
        "longitude": round(lon, 7) if lon is not None else None,
    }


def decode_pgn_129026(payload: bytes) -> Dict[str, Any]:
    """PGN 129026: COG & SOG, Rapid Update."""
    if len(payload) < 6:
        raise ValueError("PGN 129026 payload under 6 bytes")
    sid, cog_ref_byte, raw_cog, raw_sog = struct.unpack("<BBHH", payload[:6])
    cog_ref_code = cog_ref_byte & 0x03
    cog_ref = "True" if cog_ref_code == 0 else "Magnetic" if cog_ref_code == 1 else "Unknown"

    cog_deg = (raw_cog * 1e-4 * 180.0 / math.pi) if raw_cog != 0xFFFF else None
    sog_ms = (raw_sog * 0.01) if raw_sog != 0xFFFF else None
    sog_kts = (sog_ms * 1.943844) if sog_ms is not None else None

    return {
        "sid": sid,
        "cog_reference": cog_ref,
        "cog_true": round(cog_deg, 1) if cog_deg is not None else None,
        "sog_knots": round(sog_kts, 2) if sog_kts is not None else None,
        "sog_ms": round(sog_ms, 2) if sog_ms is not None else None,
    }


def decode_pgn_129029(payload: bytes) -> Dict[str, Any]:
    """PGN 129029: GNSS Position Data (Fast-Packet)."""
    if len(payload) < 36:
        raise ValueError(f"PGN 129029 payload too short ({len(payload)} < 36)")
    sid = payload[0]
    days_since_1970 = struct.unpack("<H", payload[1:3])[0]
    time_units = struct.unpack("<I", payload[3:7])[0]
    raw_lat, raw_lon, raw_alt = struct.unpack("<qqq", payload[7:31])

    lat = raw_lat * 1e-16 if raw_lat != 0x7FFFFFFFFFFFFFFF else None
    lon = raw_lon * 1e-16 if raw_lon != 0x7FFFFFFFFFFFFFFF else None
    alt_m = raw_alt * 1e-6 if raw_alt != 0x7FFFFFFFFFFFFFFF else None

    method_system = payload[31]
    gnss_type = method_system & 0x0F
    method = (method_system >> 4) & 0x0F
    integrity = payload[32] & 0x03
    n_sats = payload[33] if payload[33] != 0xFF else None
    hdop = struct.unpack("<h", payload[34:36])[0] * 0.01 if len(payload) >= 36 else None

    return {
        "sid": sid,
        "days": days_since_1970,
        "latitude": round(lat, 7) if lat is not None else None,
        "longitude": round(lon, 7) if lon is not None else None,
        "altitude_m": round(alt_m, 1) if alt_m is not None else None,
        "gnss_type": gnss_type,
        "method": method,
        "satellites": n_sats,
        "hdop": round(hdop, 2) if hdop is not None and hdop != 327.67 else None,
    }


def decode_pgn_129539(payload: bytes) -> Dict[str, Any]:
    """PGN 129539: GNSS DOPs."""
    if len(payload) < 7:
        raise ValueError("PGN 129539 payload too short")
    sid, des_mode = payload[0], payload[1] & 0x07
    hdop = struct.unpack("<h", payload[2:4])[0] * 0.01
    vdop = struct.unpack("<h", payload[4:6])[0] * 0.01
    return {
        "sid": sid,
        "hdop": round(hdop, 2) if hdop < 327.0 else None,
        "vdop": round(vdop, 2) if vdop < 327.0 else None,
    }


def decode_pgn_127250(payload: bytes) -> Dict[str, Any]:
    """PGN 127250: Vessel Heading."""
    if len(payload) < 8:
        raise ValueError("PGN 127250 payload under 8 bytes")
    sid, raw_hdg, raw_dev, raw_var, ref_byte = struct.unpack("<Bhhhb", payload[:8])
    hdg_rad = (raw_hdg & 0xFFFF) * 1e-4
    hdg_deg = (hdg_rad * 180.0 / math.pi) if (raw_hdg & 0xFFFF) != 0xFFFF else None
    ref = "Magnetic" if (ref_byte & 0x03) == 1 else "True" if (ref_byte & 0x03) == 0 else "Unknown"

    var_deg = (raw_var * 1e-4 * 180.0 / math.pi) if raw_var != 0x7FFF else None
    dev_deg = (raw_dev * 1e-4 * 180.0 / math.pi) if raw_dev != 0x7FFF else None

    return {
        "sid": sid,
        "heading_deg": round(hdg_deg, 1) if hdg_deg is not None else None,
        "reference": ref,
        "variation_deg": round(var_deg, 2) if var_deg is not None else None,
        "deviation_deg": round(dev_deg, 2) if dev_deg is not None else None,
    }


def decode_pgn_127251(payload: bytes) -> Dict[str, Any]:
    """PGN 127251: Rate of Turn."""
    if len(payload) < 5:
        raise ValueError("PGN 127251 payload under 5 bytes")
    sid, raw_rot = struct.unpack("<Bi", payload[:5])
    rot_rad_s = raw_rot * 1e-6 if raw_rot != 0x7FFFFFFF else None
    rot_deg_s = (rot_rad_s * 180.0 / math.pi) if rot_rad_s is not None else None
    return {
        "sid": sid,
        "rate_of_turn_dps": round(rot_deg_s, 2) if rot_deg_s is not None else None,
    }


def decode_pgn_127257(payload: bytes) -> Dict[str, Any]:
    """PGN 127257: Attitude (Yaw, Pitch, Roll)."""
    if len(payload) < 7:
        raise ValueError("PGN 127257 payload under 7 bytes")
    sid, raw_yaw, raw_pitch, raw_roll = struct.unpack("<Bhhh", payload[:7])
    yaw = (raw_yaw * 1e-4 * 180.0 / math.pi) if raw_yaw != 0x7FFF else None
    pitch = (raw_pitch * 1e-4 * 180.0 / math.pi) if raw_pitch != 0x7FFF else None
    roll = (raw_roll * 1e-4 * 180.0 / math.pi) if raw_roll != 0x7FFF else None
    return {
        "sid": sid,
        "yaw_deg": round(yaw, 2) if yaw is not None else None,
        "pitch_deg": round(pitch, 2) if pitch is not None else None,
        "roll_deg": round(roll, 2) if roll is not None else None,
    }


def decode_pgn_127258(payload: bytes) -> Dict[str, Any]:
    """PGN 127258: Magnetic Variation."""
    if len(payload) < 6:
        raise ValueError("PGN 127258 payload under 6 bytes")
    sid, source_code, age, raw_var = struct.unpack("<BBHh", payload[:6])
    var_deg = (raw_var * 1e-4 * 180.0 / math.pi) if raw_var != 0x7FFF else None
    return {
        "sid": sid,
        "source": source_code,
        "variation_deg": round(var_deg, 2) if var_deg is not None else None,
    }


def decode_pgn_127245(payload: bytes) -> Dict[str, Any]:
    """PGN 127245: Rudder Position."""
    if len(payload) < 6:
        raise ValueError("PGN 127245 payload under 6 bytes")
    instance = payload[0]
    direction_order = payload[1] & 0x07
    raw_angle_order = struct.unpack("<h", payload[2:4])[0]
    raw_position = struct.unpack("<h", payload[4:6])[0]

    pos_deg = (raw_position * 1e-4 * 180.0 / math.pi) if raw_position != 0x7FFF else None
    return {
        "instance": instance,
        "rudder_deg": round(pos_deg, 1) if pos_deg is not None else None,
    }


def decode_pgn_129038(payload: bytes) -> Dict[str, Any]:
    """PGN 129038: AIS Class A Position Report (Fast-Packet, 28 bytes)."""
    if len(payload) < 25:
        raise ValueError(f"PGN 129038 payload too short ({len(payload)} < 25)")
    msg_id = payload[0] & 0x3F
    mmsi = struct.unpack("<I", payload[1:5])[0]
    raw_lon, raw_lat = struct.unpack("<ii", payload[5:13])
    lon = raw_lon * 1e-7 if raw_lon != 0x7FFFFFFF else None
    lat = raw_lat * 1e-7 if raw_lat != 0x7FFFFFFF else None

    flags_ts = payload[13]
    accuracy = flags_ts & 0x01
    timestamp_sec = (flags_ts >> 2) & 0x3F

    raw_cog, raw_sog = struct.unpack("<HH", payload[14:18])
    cog = (raw_cog * 1e-4 * 180.0 / math.pi) if raw_cog != 0xFFFF else None
    sog_ms = (raw_sog * 0.01) if raw_sog != 0xFFFF else None
    sog_kts = (sog_ms * 1.943844) if sog_ms is not None else None

    raw_hdg = struct.unpack("<H", payload[21:23])[0] if len(payload) >= 23 else 0xFFFF
    hdg = (raw_hdg * 1e-4 * 180.0 / math.pi) if raw_hdg != 0xFFFF else None

    nav_status_code = payload[25] & 0x0F if len(payload) >= 26 else 15
    nav_status = AIS_NAV_STATUS.get(nav_status_code, "Unknown")

    return {
        "ais_class": "A",
        "mmsi": mmsi,
        "latitude": round(lat, 6) if lat is not None else None,
        "longitude": round(lon, 6) if lon is not None else None,
        "sog_knots": round(sog_kts, 1) if sog_kts is not None else None,
        "cog_true": round(cog, 1) if cog is not None else None,
        "true_heading": round(hdg, 1) if hdg is not None else None,
        "nav_status_code": nav_status_code,
        "nav_status": nav_status,
        "timestamp_sec": timestamp_sec,
    }


def decode_pgn_129039(payload: bytes) -> Dict[str, Any]:
    """PGN 129039: AIS Class B Position Report (Fast-Packet, 26 bytes)."""
    if len(payload) < 23:
        raise ValueError(f"PGN 129039 payload too short ({len(payload)} < 23)")
    msg_id = payload[0] & 0x3F
    mmsi = struct.unpack("<I", payload[1:5])[0]
    raw_lon, raw_lat = struct.unpack("<ii", payload[5:13])
    lon = raw_lon * 1e-7 if raw_lon != 0x7FFFFFFF else None
    lat = raw_lat * 1e-7 if raw_lat != 0x7FFFFFFF else None

    flags_ts = payload[13]
    timestamp_sec = (flags_ts >> 2) & 0x3F

    raw_cog, raw_sog = struct.unpack("<HH", payload[14:18])
    cog = (raw_cog * 1e-4 * 180.0 / math.pi) if raw_cog != 0xFFFF else None
    sog_ms = (raw_sog * 0.01) if raw_sog != 0xFFFF else None
    sog_kts = (sog_ms * 1.943844) if sog_ms is not None else None

    raw_hdg = struct.unpack("<H", payload[21:23])[0] if len(payload) >= 23 else 0xFFFF
    hdg = (raw_hdg * 1e-4 * 180.0 / math.pi) if raw_hdg != 0xFFFF else None

    return {
        "ais_class": "B",
        "mmsi": mmsi,
        "latitude": round(lat, 6) if lat is not None else None,
        "longitude": round(lon, 6) if lon is not None else None,
        "sog_knots": round(sog_kts, 1) if sog_kts is not None else None,
        "cog_true": round(cog, 1) if cog is not None else None,
        "true_heading": round(hdg, 1) if hdg is not None else None,
        "timestamp_sec": timestamp_sec,
    }


def decode_pgn_129809(payload: bytes) -> Dict[str, Any]:
    """PGN 129809: AIS Class B CS Static Report Part A (Vessel Name)."""
    if len(payload) < 5:
        raise ValueError("PGN 129809 payload too short")
    mmsi = struct.unpack("<I", payload[1:5])[0]
    name_raw = payload[5:25] if len(payload) >= 25 else payload[5:]
    name = name_raw.decode("latin1", errors="replace").rstrip("@ \x00\xff")
    return {
        "mmsi": mmsi,
        "vessel_name": name,
    }


def decode_pgn_129810(payload: bytes) -> Dict[str, Any]:
    """PGN 129810: AIS Class B CS Static Report Part B (Type, Call Sign, Dimensions)."""
    if len(payload) < 6:
        raise ValueError("PGN 129810 payload too short")
    mmsi = struct.unpack("<I", payload[1:5])[0]
    ship_type = payload[5]
    call_sign = payload[13:20].decode("latin1", errors="replace").rstrip("@ \x00\xff") if len(payload) >= 20 else ""
    return {
        "mmsi": mmsi,
        "ship_type": ship_type,
        "call_sign": call_sign,
    }


def decode_pgn_130314(payload: bytes) -> Dict[str, Any]:
    """PGN 130314: Actual Pressure (Barometer)."""
    if len(payload) < 7:
        raise ValueError("PGN 130314 payload under 7 bytes")
    sid, instance, source = payload[0], payload[1], payload[2]
    raw_press = struct.unpack("<I", payload[3:7])[0]
    # Resolution is 0.1 Pa (or 1 Pa depending on spec) -> ~1014.6 hPa
    press_hpa = (raw_press * 0.001) if raw_press != 0xFFFFFFFF else None
    return {
        "sid": sid,
        "source": source,
        "pressure_hpa": round(press_hpa, 1) if press_hpa is not None else None,
    }


def decode_raymarine_proprietary(pgn: int, payload: bytes) -> Dict[str, Any]:
    """Decodes known Raymarine autopilot proprietary PGNs."""
    mfg_code = 1851  # Raymarine
    res: Dict[str, Any] = {"manufacturer": "Raymarine", "mfg_code": mfg_code}

    if pgn == 65379:  # Pilot Mode
        mode_code = payload[6] if len(payload) >= 7 else (payload[2] if len(payload) >= 3 else 0)
        mode_names = {
            0: "Standby",
            1: "Auto",
            2: "Wind",
            3: "Track",
            4: "Power Steer",
        }
        res["pilot_mode_code"] = mode_code
        res["pilot_mode"] = mode_names.get(mode_code, f"Mode {mode_code}")
    elif pgn == 65359:  # Pilot Heading
        if len(payload) >= 7:
            raw_hdg = struct.unpack("<H", payload[5:7])[0]
            hdg_deg = (raw_hdg * 1e-4 * 180.0 / math.pi) if raw_hdg != 0xFFFF else None
            res["pilot_heading_deg"] = round(hdg_deg, 1) if hdg_deg is not None else None
    elif pgn == 65384:  # Pilot Wind Datum / Heading 3
        res["description"] = "Seatalk Pilot Target / Wind Datum"

    return res


def decode_pgn_126983(payload: bytes) -> Dict[str, Any]:
    """PGN 126983: Alert definition and state."""
    if len(payload) < 6:
        raise ValueError("PGN 126983 payload under 6 bytes")
    alert_id = struct.unpack("<H", payload[0:2])[0]
    alert_type = payload[2]
    category = payload[3]
    system = payload[4]
    sub_system = payload[5]
    silenced = bool(payload[10] & 0x01) if len(payload) >= 11 else False
    acknowledged = bool(payload[11] & 0x01) if len(payload) >= 12 else False
    return {
        "alert_id": alert_id,
        "alert_type": alert_type,
        "category": category,
        "system": system,
        "sub_system": sub_system,
        "silenced": silenced,
        "acknowledged": acknowledged,
    }


def decode_pgn_126984(payload: bytes) -> Dict[str, Any]:
    """PGN 126984: Alert Response / Silence command."""
    if len(payload) < 8:
        raise ValueError("PGN 126984 payload under 8 bytes")
    alert_id = struct.unpack("<H", payload[0:2])[0]
    resp_cmd = payload[7] if len(payload) >= 8 else 0
    resp_names = {0: "Acknowledge", 1: "Temporary Silence", 2: "Cancel Silence"}
    return {
        "alert_id": alert_id,
        "response_command": resp_cmd,
        "response_action": resp_names.get(resp_cmd, f"Command {resp_cmd}"),
    }


def decode_pgn_126985(payload: bytes) -> Dict[str, Any]:
    """PGN 126985: Alert Text Description."""
    if len(payload) < 3:
        raise ValueError("PGN 126985 payload under 3 bytes")
    alert_id = struct.unpack("<H", payload[0:2])[0]
    language_id = payload[2]
    text = payload[3:].decode("latin1", errors="replace").rstrip("\x00\xff") if len(payload) > 3 else ""
    return {
        "alert_id": alert_id,
        "language_id": language_id,
        "alert_text": text,
    }


def decode_pgn_127233(payload: bytes) -> Dict[str, Any]:
    """PGN 127233: Man Overboard Notification."""
    if len(payload) < 21:
        raise ValueError("PGN 127233 payload under 21 bytes")
    mob_id = struct.unpack("<I", payload[0:4])[0]
    mob_status = payload[4]
    raw_lat = struct.unpack("<i", payload[13:17])[0]
    raw_lon = struct.unpack("<i", payload[17:21])[0]
    lat = (raw_lat * 1e-7) if raw_lat != 0x7FFFFFFF else None
    lon = (raw_lon * 1e-7) if raw_lon != 0x7FFFFFFF else None
    return {
        "mob_id": mob_id,
        "mob_active": (mob_status == 0),
        "latitude": round(lat, 6) if lat is not None else None,
        "longitude": round(lon, 6) if lon is not None else None,
    }


def encode_pgn_126984_silence(alert_id: int, response_cmd: int = 1) -> bytes:
    """Encodes PGN 126984 Alert Response (1 = Temporary Silence, 0 = Acknowledge)."""
    return struct.pack("<HBBBBBB", alert_id, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, response_cmd)


def encode_pgn_127233_mob(lat: float, lon: float, mob_id: int = 1, active: bool = True) -> bytes:
    """Encodes PGN 127233 Man Overboard Notification."""
    status = 0 if active else 1
    raw_lat = int(round(lat * 1e7))
    raw_lon = int(round(lon * 1e7))
    return struct.pack("<IBIIii", mob_id, status, 0xFFFFFFFF, 0xFFFFFFFF, raw_lat, raw_lon)


# Dispatch table for known PGN decoders
DECODERS: Dict[int, Callable[[bytes], Dict[str, Any]]] = {
    126983: decode_pgn_126983,
    126984: decode_pgn_126984,
    126985: decode_pgn_126985,
    127233: decode_pgn_127233,
    129025: decode_pgn_129025,
    129026: decode_pgn_129026,
    129029: decode_pgn_129029,
    129539: decode_pgn_129539,
    127250: decode_pgn_127250,
    127251: decode_pgn_127251,
    127257: decode_pgn_127257,
    127258: decode_pgn_127258,
    127245: decode_pgn_127245,
    129038: decode_pgn_129038,
    129039: decode_pgn_129039,
    129809: decode_pgn_129809,
    129810: decode_pgn_129810,
    130314: decode_pgn_130314,
}


class UniversalDecoder:
    """
    Main engine that accepts raw CAN frames, performs Fast-Packet reassembly,
    decodes recognized PGNs, and falls back to universal raw structure for novel PGNs.
    """

    def __init__(self):
        self.fast_packet_reassembler = FastPacketReassembler()

    def process_frame(self, frame: CanFrame) -> Optional[Dict[str, Any]]:
        """
        Ingests a single CAN frame.
        Returns a dictionary representing the decoded message or raw fallback record.
        Returns None if frame is part of an ongoing multi-frame Fast Packet.
        """
        pgn = frame.pgn
        payload = frame.payload

        # Fast Packet check
        if pgn in FAST_PACKET_PGNS:
            assembled = self.fast_packet_reassembler.push_frame(pgn, frame.source, payload)
            if assembled is None:
                return None  # Waiting for more frames
            payload = assembled

        # Try specific decoder
        pgn_name = PGN_CATALOG.get(pgn, "Proprietary / Unknown")
        iso_time = datetime.fromtimestamp(frame.timestamp, tz=timezone.utc).isoformat()

        record: Dict[str, Any] = {
            "pgn": pgn,
            "name": pgn_name,
            "src": frame.source,
            "prio": frame.priority,
            "len": len(payload),
            "timestamp": iso_time,
            "decoded": False,
        }

        # Check for Raymarine proprietary header 0x3B 0x9F
        is_raymarine = len(payload) >= 2 and payload[0] == 0x3B and payload[1] == 0x9F
        if is_raymarine or pgn in (65359, 65379, 65384, 130916):
            try:
                ray_fields = decode_raymarine_proprietary(pgn, payload)
                record.update(ray_fields)
                record["decoded"] = True
            except Exception as e:
                record["error"] = str(e)
        elif pgn in DECODERS:
            try:
                decoded_fields = DECODERS[pgn](payload)
                record.update(decoded_fields)
                record["decoded"] = True
            except Exception as e:
                record["error"] = f"Decoding failed: {e}"

        # If novel or decoding failed, ensure raw byte representations are present
        if not record.get("decoded", False):
            record["hex"] = payload.hex()
            record["bytes"] = list(payload)

        return record
