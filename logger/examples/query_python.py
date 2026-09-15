#!/usr/bin/env python3
"""
Example: Querying Paeraki telemetry database in Python.
Works with standard library sqlite3 or pandas.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "paeraki.db"


def main():
    if not DB_PATH.exists():
        print(f"Database file not found at {DB_PATH}. Start the logger service first.")
        return

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    print(f"Connected to Paeraki database: {DB_PATH}")

    # 1. Total counts
    p_count = conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
    t72_count = conn.execute("SELECT COUNT(*) FROM telemetry_72v").fetchone()[0]
    t12_count = conn.execute("SELECT COUNT(*) FROM telemetry_12v").fetchone()[0]
    stng_count = conn.execute("SELECT COUNT(*) FROM telemetry_seatalkng").fetchone()[0]
    ais_count = conn.execute("SELECT COUNT(*) FROM telemetry_ais").fetchone()[0]
    print(f"Total packets: {p_count} | 72V: {t72_count} | 12V: {t12_count} | SeaTalkNG: {stng_count} | AIS: {ais_count}\n")

    # 2. Latest 72V telemetry
    print("=== Latest 72V Propulsion Telemetry ===")
    cursor = conn.execute("""
        SELECT timestamp, total_voltage, current, power, rsoc, cell_delta_mv
        FROM telemetry_72v
        ORDER BY epoch_ms DESC
        LIMIT 5
    """)
    for row in cursor.fetchall():
        print(f"[{row['timestamp'][:19]}] {row['total_voltage']:.2f}V | {row['current']:+.2f}A | {row['power']:+.1f}W | SoC: {row['rsoc']}% | Delta: {row['cell_delta_mv']}mV")

    # 3. Latest 12V Solar telemetry
    print("\n=== Latest 12V Solar Telemetry ===")
    cursor = conn.execute("""
        SELECT timestamp, battery_voltage, solar_power, solar_voltage, solar_current, charging_status
        FROM telemetry_12v
        ORDER BY epoch_ms DESC
        LIMIT 5
    """)
    for row in cursor.fetchall():
        print(f"[{row['timestamp'][:19]}] Batt: {row['battery_voltage']:.2f}V | Solar: {row['solar_power']}W ({row['solar_voltage']}V / {row['solar_current']}A) | {row['charging_status']}")

    # 4. Latest SeaTalkNG Navigation & Attitude
    print("\n=== Latest SeaTalkNG Vessel Telemetry ===")
    cursor = conn.execute("""
        SELECT timestamp, heading_deg, heading_ref, pitch_deg, roll_deg, latitude, longitude, sog_knots, satellites, pilot_mode
        FROM telemetry_seatalkng
        ORDER BY epoch_ms DESC
        LIMIT 5
    """)
    for row in cursor.fetchall():
        print(f"[{row['timestamp'][:19]}] Hdg: {row['heading_deg']:.1f}° ({row['heading_ref']}) | Pitch: {row['pitch_deg']:+.2f}° | Roll: {row['roll_deg']:+.2f}° | Lat: {row['latitude']:.5f} | Lon: {row['longitude']:.5f} | Sats: {row['satellites']} | Pilot: {row['pilot_mode']}")

    # 5. Latest AIS Targets
    print("\n=== Latest AIS Targets in Range ===")
    cursor = conn.execute("""
        SELECT timestamp, mmsi, vessel_name, ais_class, range_nm, bearing_deg, sog_knots, cog_true
        FROM telemetry_ais
        ORDER BY epoch_ms DESC
        LIMIT 5
    """)
    for row in cursor.fetchall():
        print(f"[{row['timestamp'][:19]}] MMSI {row['mmsi']} ({row['vessel_name'] or 'Unknown'}) | Cls {row['ais_class']} | Range: {row['range_nm']} NM | Brg: {row['bearing_deg']}° | SOG: {row['sog_knots']} kt")

    conn.close()


if __name__ == "__main__":
    main()
