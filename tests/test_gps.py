"""
Unit tests for NMEA 0183 GPS parsing and WGS-84 altitude reconciliation.
"""

import pytest
from gps.nmea import NmeaState


def test_nmea_state_gga_altitude_wgs84():
    state = NmeaState()
    # Live $GPGGA sample from RUT955 Quectel modem:
    # Altitude MSL = 2.1 m, Geoidal Separation = 11.0 m -> WGS-84 Altitude = 13.1 m
    sentence = "$GPGGA,200733.00,4336.288008,S,17242.897509,E,1,10,0.7,2.1,M,11.0,M,,*71"
    parsed = state.parse_line(sentence)
    assert parsed is True
    assert state.fix is True
    assert state.fix_quality == 1
    assert state.satellites == 10
    assert state.hdop == 0.7
    assert state.altitude_m == 2.1
    assert state.geoidal_sep_m == 11.0
    assert state.altitude_wgs84_m == 13.1

    d = state.to_dict()
    assert d["altitude_m"] == 2.1
    assert d["geoidal_sep_m"] == 11.0
    assert d["altitude_wgs84_m"] == 13.1
