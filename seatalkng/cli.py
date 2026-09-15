#!/usr/bin/env python3
"""
SeaTalkNG Command-Line Tool & Live Bus Monitor.
Connects directly to the USR-CAN115 TCP port or observes MQTT topics
to display real-time navigation, attitude, and AIS target tables in the console.
"""

import argparse
import asyncio
import os
from pathlib import Path
import struct
import sys
import time
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seatalkng.decoder import (
    CanFrame,
    PGN_CATALOG,
    UniversalDecoder,
    calculate_range_bearing,
    parse_can_id,
)


def render_monitor_ui(state: Dict[str, Any], ais_targets: Dict[int, Dict[str, Any]], pgn_counts: Dict[int, int]):
    """Renders a clean terminal display for vessel telemetry and AIS."""
    os.system("clear")
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")

    lat = state.get("latitude")
    lon = state.get("longitude")
    lat_str = f"{abs(lat):.5f}° {'S' if lat and lat < 0 else 'N'}" if lat is not None else "--"
    lon_str = f"{abs(lon):.5f}° {'W' if lon and lon < 0 else 'E'}" if lon is not None else "--"
    sog_str = f"{state.get('sog_knots', 0.0):.1f} kts" if state.get("sog_knots") is not None else "--"
    cog_str = f"{state.get('cog_true', 0.0):.1f}° T" if state.get("cog_true") is not None else "--"
    hdg_str = f"{state.get('heading_deg', 0.0):.1f}° {state.get('heading_ref', 'M')}" if state.get("heading_deg") is not None else "--"

    pitch = state.get("pitch_deg", 0.0)
    roll = state.get("roll_deg", 0.0)
    rot = state.get("rate_of_turn_dps", 0.0)
    alt = state.get("altitude_m", 0.0)
    sats = state.get("satellites", "--")
    hdop = state.get("hdop", "--")
    press = state.get("pressure_hpa", "--")
    pilot = state.get("pilot_mode", "Standby")

    print("================================================================================")
    print(f"  PAERAKI SEATALKNG / N2K MONITOR              {now_str}")
    print("================================================================================")
    print(" [NAVIGATION & GPS] (Source: Vesper Cortex)")
    print(f"   Position : {lat_str}, {lon_str} (Alt: {alt}m | Sats: {sats} | HDOP: {hdop})")
    print(f"   Speed    : {sog_str:<12} Course (COG) : {cog_str:<12} Barometer : {press} hPa")
    print("--------------------------------------------------------------------------------")
    print(" [ATTITUDE & DYNAMICS] (Source: Raymarine EV-1)")
    print(f"   Heading  : {hdg_str:<12} Rate of Turn: {rot:+.2f} °/s   Autopilot : {pilot}")
    print(f"   Pitch    : {pitch:+.2f}° (Bow {'Up' if pitch >= 0 else 'Down'})")
    print(f"   Roll     : {roll:+.2f}° (List {'Stbd' if roll >= 0 else 'Port'})")
    print("--------------------------------------------------------------------------------")
    print(f" [AIS TARGETS IN VHF RANGE] ({len(ais_targets)} active targets)")
    print(f"  {'MMSI':<10} {'Name':<18} {'Class':<6} {'SOG':<8} {'COG':<8} {'Range':<10} {'Bearing':<9} {'Status'}")
    print("  " + "-" * 76)

    now = time.time()
    sorted_targets = sorted(ais_targets.values(), key=lambda t: (t.get("range_nm") is None, t.get("range_nm", 9999)))

    for t in sorted_targets[:10]:
        mmsi = t.get("mmsi", "--")
        name = (t.get("vessel_name") or "--")[:17]
        cls = t.get("ais_class", "B")
        sog = f"{t.get('sog_knots', 0.0):.1f} kt" if t.get("sog_knots") is not None else "--"
        cog = f"{t.get('cog_true', 0.0):.0f}°" if t.get("cog_true") is not None else "--"
        rng = f"{t.get('range_nm', 0.0):.2f} NM" if t.get("range_nm") is not None else "--"
        brg = f"{t.get('bearing_deg', 0.0):.0f}° T" if t.get("bearing_deg") is not None else "--"
        stat = (t.get("nav_status") or "--")[:18]
        print(f"  {mmsi:<10} {name:<18} {cls:<6} {sog:<8} {cog:<8} {rng:<10} {brg:<9} {stat}")

    print("================================================================================")
    total_frames = sum(pgn_counts.values())
    print(f"  Bus Activity: {total_frames} frames across {len(pgn_counts)} PGNs. Press Ctrl+C to exit.")


async def run_live_monitor(listen_host: str, listen_port: int, raw_mode: bool = False):
    decoder = UniversalDecoder()
    state: Dict[str, Any] = {}
    ais_targets: Dict[int, Dict[str, Any]] = {}
    pgn_counts: Dict[int, int] = {}
    last_render = 0.0

    print(f"Connecting to USR-CAN115 on {listen_host}:{listen_port} (waiting for connection)...")

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        nonlocal last_render
        addr = writer.get_extra_info("peername")
        print(f"Connected from {addr}")
        buffer = bytearray()

        while True:
            data = await reader.read(4096)
            if not data:
                break
            buffer.extend(data)
            while len(buffer) >= 13:
                if buffer[0] == 0x88:
                    can_id = struct.unpack(">I", buffer[1:5])[0]
                    payload = bytes(buffer[5:13])
                    buffer = buffer[13:]

                    prio, dp, pf, ps, sa, dst, pgn = parse_can_id(can_id)
                    pgn_counts[pgn] = pgn_counts.get(pgn, 0) + 1

                    if raw_mode:
                        pgn_name = PGN_CATALOG.get(pgn, "Unknown")
                        print(f"CAN 0x{can_id:08X} PGN {pgn:6d} ({pgn_name:<28}) SA 0x{sa:02X} [{len(payload)}]: {payload.hex(' ')}")
                        continue

                    frame = CanFrame(
                        can_id=can_id,
                        priority=prio,
                        data_page=dp,
                        pdu_format=pf,
                        pdu_specific=ps,
                        source=sa,
                        destination=dst,
                        pgn=pgn,
                        payload=payload,
                    )
                    record = decoder.process_frame(frame)
                    if record:
                        # Update state
                        if pgn in (129025, 129029):
                            for k in ("latitude", "longitude", "satellites", "hdop", "altitude_m"):
                                if record.get(k) is not None:
                                    state[k] = record[k]
                        elif pgn == 129026:
                            for k in ("sog_knots", "cog_true"):
                                if record.get(k) is not None:
                                    state[k] = record[k]
                        elif pgn == 127250:
                            state["heading_deg"] = record.get("heading_deg")
                            state["heading_ref"] = record.get("reference")
                        elif pgn == 127257:
                            state["pitch_deg"] = record.get("pitch_deg")
                            state["roll_deg"] = record.get("roll_deg")
                        elif pgn == 127251:
                            state["rate_of_turn_dps"] = record.get("rate_of_turn_dps")
                        elif pgn == 130314:
                            state["pressure_hpa"] = record.get("pressure_hpa")
                        elif pgn == 65379:
                            state["pilot_mode"] = record.get("pilot_mode")
                        elif pgn in (129038, 129039):
                            mmsi = record.get("mmsi")
                            if mmsi:
                                if mmsi not in ais_targets:
                                    ais_targets[mmsi] = {"mmsi": mmsi, "vessel_name": ""}
                                t = ais_targets[mmsi]
                                t.update(record)
                                if state.get("latitude") and state.get("longitude") and t.get("latitude") and t.get("longitude"):
                                    dist, brg = calculate_range_bearing(state["latitude"], state["longitude"], t["latitude"], t["longitude"])
                                    t["range_nm"] = dist
                                    t["bearing_deg"] = brg
                        elif pgn in (129809, 129810):
                            mmsi = record.get("mmsi")
                            if mmsi:
                                if mmsi not in ais_targets:
                                    ais_targets[mmsi] = {"mmsi": mmsi}
                                if record.get("vessel_name"):
                                    ais_targets[mmsi]["vessel_name"] = record["vessel_name"]

                    now = time.time()
                    if not raw_mode and now - last_render >= 0.25:
                        render_monitor_ui(state, ais_targets, pgn_counts)
                        last_render = now
                else:
                    buffer.pop(0)

    server = await asyncio.start_server(handle_client, listen_host, listen_port)
    async with server:
        await server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="SeaTalkNG CLI & Terminal Monitor")
    parser.add_argument("--listen-host", default="0.0.0.0", help="TCP listen host (default: 0.0.0.0)")
    parser.add_argument("--listen-port", type=int, default=8234, help="TCP listen port (default: 8234)")
    parser.add_argument("--raw", action="store_true", help="Print raw CAN frames without full UI")

    args = parser.parse_args()
    try:
        asyncio.run(run_live_monitor(args.listen_host, args.listen_port, raw_mode=args.raw))
    except KeyboardInterrupt:
        print("\nExiting monitor.")


if __name__ == "__main__":
    main()
