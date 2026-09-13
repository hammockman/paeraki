#!/usr/bin/env python3
"""
Lightweight, robust NMEA 0183 GNSS Sentence Parser for yacht Paeraki.
Decodes $GPRMC, $GPGGA, $GPVTG, $GPGSA sentences from Teltonika RUT955 router.
"""

from datetime import datetime, timezone
import logging
from typing import Any

logger = logging.getLogger("paeraki.gps.nmea")


def verify_checksum(sentence: str) -> bool:
    """Verifies standard NMEA 0183 XOR checksum (*XX)."""
    if "*" not in sentence:
        return True  # no checksum present to verify
    try:
        content, csum_str = sentence.strip().lstrip("$").split("*", 1)
        expected_csum = int(csum_str[:2], 16)
        calc_csum = 0
        for char in content:
            calc_csum ^= ord(char)
        return calc_csum == expected_csum
    except Exception:
        return False


def parse_lat_nmea(raw: str, hemi: str) -> float | None:
    """Converts NMEA latitude ddmm.mmmm to decimal degrees."""
    if not raw or not hemi or len(raw) < 4:
        return None
    try:
        degrees = float(raw[:2])
        minutes = float(raw[2:])
        dec = degrees + (minutes / 60.0)
        if hemi.upper() == "S":
            dec = -dec
        return round(dec, 6)
    except (ValueError, TypeError):
        return None


def parse_lon_nmea(raw: str, hemi: str) -> float | None:
    """Converts NMEA longitude dddmm.mmmm to decimal degrees."""
    if not raw or not hemi or len(raw) < 5:
        return None
    try:
        degrees = float(raw[:3])
        minutes = float(raw[3:])
        dec = degrees + (minutes / 60.0)
        if hemi.upper() == "W":
            dec = -dec
        return round(dec, 6)
    except (ValueError, TypeError):
        return None


def format_lat_nautical(lat: float | None) -> str:
    """Formats decimal latitude into nautical degrees and minutes (e.g. 36° 50.910' S)."""
    if lat is None:
        return "--° --.---' -"
    hemi = "S" if lat < 0 else "N"
    abs_lat = abs(lat)
    deg = int(abs_lat)
    minutes = (abs_lat - deg) * 60.0
    return f"{deg}° {minutes:06.3f}' {hemi}"


def format_lon_nautical(lon: float | None) -> str:
    """Formats decimal longitude into nautical degrees and minutes (e.g. 174° 45.798' E)."""
    if lon is None:
        return "---° --.---' -"
    hemi = "W" if lon < 0 else "E"
    abs_lon = abs(lon)
    deg = int(abs_lon)
    minutes = (abs_lon - deg) * 60.0
    return f"{deg}° {minutes:06.3f}' {hemi}"


class NmeaState:
    """Maintains current GNSS receiver fix, position, and velocity state."""

    def __init__(self):
        self.timestamp: str | None = None
        self.fix: bool = False
        self.fix_status: str = "V"  # A = Active/Valid, V = Void/Invalid
        self.fix_quality: int = 0   # 0 = invalid, 1 = GPS SPS, 2 = DGPS
        self.latitude: float | None = None
        self.longitude: float | None = None
        self.latitude_nautical: str = "--° --.---' -"
        self.longitude_nautical: str = "---° --.---' -"
        self.sog_knots: float = 0.0
        self.sog_kmh: float = 0.0
        self.sog_ms: float = 0.0
        self.cog_true: float | None = None
        self.altitude_m: float | None = None
        self.satellites: int = 0
        self.hdop: float | None = None
        self.last_sentence_type: str | None = None
        self.raw_sentence: str = ""

    def parse_line(self, line: str) -> bool:
        """Parses a single NMEA sentence. Returns True if successfully parsed."""
        if not line:
            return False
        clean = line.strip()
        if not clean.startswith("$"):
            # Some Teltonika prefixes prepend device ID e.g. "RUT955 $GPRMC,..."
            idx = clean.find("$")
            if idx != -1:
                clean = clean[idx:]
            else:
                return False

        if not verify_checksum(clean):
            logger.warning("NMEA checksum mismatch: %s", clean)
            return False

        self.raw_sentence = clean
        parts = clean.split("*")[0].split(",")
        cmd = parts[0].upper()
        # Sentence identifier: strip talker ($GP, $GN, $GL, $GA)
        sentence_type = cmd[3:] if len(cmd) >= 5 else cmd[1:]
        self.last_sentence_type = sentence_type

        try:
            if sentence_type == "RMC":
                return self._parse_rmc(parts)
            elif sentence_type == "GGA":
                return self._parse_gga(parts)
            elif sentence_type == "VTG":
                return self._parse_vtg(parts)
            elif sentence_type == "GSA":
                return self._parse_gsa(parts)
            return False
        except Exception as e:
            logger.debug("Error parsing %s: %s", cmd, e)
            return False

    def _parse_rmc(self, parts: list[str]) -> bool:
        # $--RMC,hhmmss.ss,A,llll.ll,a,yyyyy.yy,a,x.x,x.x,ddmmyy,x.x,a,m*hh
        # 1: UTC Time
        # 2: Status (A = active/valid, V = void)
        # 3: Latitude
        # 4: N/S
        # 5: Longitude
        # 6: E/W
        # 7: Speed over ground in knots
        # 8: Track made good (degrees true)
        # 9: Date (ddmmyy)
        if len(parts) < 10:
            return False

        status = parts[2].upper() if len(parts) > 2 else "V"
        self.fix_status = status
        self.fix = (status == "A")

        lat = parse_lat_nmea(parts[3], parts[4]) if len(parts) > 4 else None
        lon = parse_lon_nmea(parts[5], parts[6]) if len(parts) > 6 else None
        if lat is not None and lon is not None:
            self.latitude = lat
            self.longitude = lon
            self.latitude_nautical = format_lat_nautical(lat)
            self.longitude_nautical = format_lon_nautical(lon)

        # Speed over ground (knots)
        try:
            if parts[7]:
                self.sog_knots = round(float(parts[7]), 2)
                self.sog_kmh = round(self.sog_knots * 1.852, 2)
                self.sog_ms = round(self.sog_knots * 0.514444, 2)
        except (ValueError, IndexError):
            pass

        # Course over ground (degrees True)
        try:
            if parts[8]:
                self.cog_true = round(float(parts[8]), 1)
        except (ValueError, IndexError):
            pass

        # Construct UTC timestamp
        try:
            time_str = parts[1]
            date_str = parts[9]
            if time_str and date_str and len(time_str) >= 6 and len(date_str) == 6:
                d = int(date_str[:2])
                m = int(date_str[2:4])
                y = 2000 + int(date_str[4:6])
                hh = int(time_str[:2])
                mm = int(time_str[2:4])
                ss = int(time_str[4:6])
                self.timestamp = datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc).isoformat()
            else:
                self.timestamp = datetime.now(timezone.utc).isoformat()
        except Exception:
            self.timestamp = datetime.now(timezone.utc).isoformat()

        return True

    def _parse_gga(self, parts: list[str]) -> bool:
        # $--GGA,hhmmss.ss,llll.ll,a,yyyyy.yy,a,x,xx,x.x,x.x,M,x.x,M,x.x,xxxx*hh
        # 2: Latitude, 3: N/S, 4: Longitude, 5: E/W
        # 6: Fix quality (0=inv, 1=GPS, 2=DGPS)
        # 7: Number of satellites
        # 8: HDOP
        # 9: Altitude, 10: M (meters)
        if len(parts) < 10:
            return False

        try:
            q = int(parts[6]) if parts[6] else 0
            self.fix_quality = q
            if q > 0:
                self.fix = True
        except (ValueError, IndexError):
            pass

        lat = parse_lat_nmea(parts[2], parts[3]) if len(parts) > 3 else None
        lon = parse_lon_nmea(parts[4], parts[5]) if len(parts) > 5 else None
        if lat is not None and lon is not None:
            self.latitude = lat
            self.longitude = lon
            self.latitude_nautical = format_lat_nautical(lat)
            self.longitude_nautical = format_lon_nautical(lon)

        try:
            if parts[7]:
                self.satellites = int(parts[7])
        except (ValueError, IndexError):
            pass

        try:
            if parts[8]:
                self.hdop = round(float(parts[8]), 2)
        except (ValueError, IndexError):
            pass

        try:
            if parts[9]:
                self.altitude_m = round(float(parts[9]), 1)
        except (ValueError, IndexError):
            pass

        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

        return True

    def _parse_vtg(self, parts: list[str]) -> bool:
        # $--VTG,x.x,T,x.x,M,x.x,N,x.x,K,m*hh
        # 1: Track degrees True, 2: T
        # 5: Speed knots, 6: N
        # 7: Speed km/h, 8: K
        if len(parts) < 8:
            return False

        try:
            if parts[1]:
                self.cog_true = round(float(parts[1]), 1)
        except (ValueError, IndexError):
            pass

        try:
            if parts[5]:
                self.sog_knots = round(float(parts[5]), 2)
                self.sog_kmh = round(self.sog_knots * 1.852, 2)
                self.sog_ms = round(self.sog_knots * 0.514444, 2)
        except (ValueError, IndexError):
            pass

        return True

    def _parse_gsa(self, parts: list[str]) -> bool:
        # $--GSA,a,x,xx,xx,...,x.x,x.x,x.x*hh
        # 2: Fix mode (1=No fix, 2=2D, 3=3D)
        # 15: PDOP, 16: HDOP, 17: VDOP
        if len(parts) < 17:
            return False

        try:
            mode = int(parts[2]) if parts[2] else 1
            if mode >= 2:
                self.fix = True
            elif mode == 1:
                self.fix = False
        except (ValueError, IndexError):
            pass

        try:
            if parts[16]:
                self.hdop = round(float(parts[16]), 2)
        except (ValueError, IndexError):
            pass

        return True

    def to_dict(self) -> dict[str, Any]:
        """Returns consolidated dictionary for JSON publishing and state updates."""
        return {
            "timestamp": self.timestamp or datetime.now(timezone.utc).isoformat(),
            "fix": self.fix,
            "fix_status": self.fix_status,
            "fix_quality": self.fix_quality,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "latitude_nautical": self.latitude_nautical,
            "longitude_nautical": self.longitude_nautical,
            "sog_knots": self.sog_knots,
            "sog_kmh": self.sog_kmh,
            "sog_ms": self.sog_ms,
            "cog_true": self.cog_true,
            "altitude_m": self.altitude_m,
            "satellites": self.satellites,
            "hdop": self.hdop,
            "last_sentence": self.last_sentence_type,
        }
