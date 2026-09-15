#!/usr/bin/env python3
"""
SeaTalkNG / NMEA 2000 Telemetry Service for yacht Paeraki.
Listens for PUSR USR-CAN115 CAN-over-Ethernet stream on TCP port 8234,
decodes all PGNs (GPS, Heading, Attitude, AIS, Autopilot, Environmental),
falls back to raw payloads for novel PGNs, and publishes live telemetry to MQTT.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import struct
import sys
from typing import Any, Dict, List, Optional

# Ensure package import works
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seatalkng.decoder import (
    CanFrame,
    PGN_CATALOG,
    UniversalDecoder,
    calculate_range_bearing,
    parse_can_id,
)

try:
    import aiomqtt
except ImportError:
    aiomqtt = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("paeraki.seatalkng")


class VesselState:
    """Maintains recent consolidated telemetry for Paeraki."""

    def __init__(self):
        self.latitude: Optional[float] = None
        self.longitude: Optional[float] = None
        self.sog_knots: Optional[float] = None
        self.cog_true: Optional[float] = None
        self.heading_deg: Optional[float] = None
        self.heading_ref: Optional[str] = None
        self.variation_deg: Optional[float] = None
        self.pitch_deg: Optional[float] = None
        self.roll_deg: Optional[float] = None
        self.yaw_deg: Optional[float] = None
        self.rate_of_turn_dps: Optional[float] = None
        self.rudder_deg: Optional[float] = None
        self.satellites: Optional[int] = None
        self.hdop: Optional[float] = None
        self.altitude_m: Optional[float] = None
        self.pressure_hpa: Optional[float] = None
        self.pilot_mode: Optional[str] = None
        self.last_updated: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        iso_time = (
            datetime.fromtimestamp(self.last_updated, tz=timezone.utc).isoformat()
            if self.last_updated > 0
            else datetime.now(timezone.utc).isoformat()
        )
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "sog_knots": self.sog_knots,
            "cog_true": self.cog_true,
            "heading_deg": self.heading_deg,
            "heading_reference": self.heading_ref,
            "variation_deg": self.variation_deg,
            "pitch_deg": self.pitch_deg,
            "roll_deg": self.roll_deg,
            "yaw_deg": self.yaw_deg,
            "rate_of_turn_dps": self.rate_of_turn_dps,
            "rudder_deg": self.rudder_deg,
            "satellites": self.satellites,
            "hdop": self.hdop,
            "altitude_m": self.altitude_m,
            "pressure_hpa": self.pressure_hpa,
            "pilot_mode": self.pilot_mode,
            "timestamp": iso_time,
        }


class AisDirectory:
    """Maintains active AIS targets within VHF reception range."""

    def __init__(self, timeout_sec: float = 900.0):  # 15 minutes
        self.timeout_sec = timeout_sec
        # MMSI -> dict
        self.targets: Dict[int, Dict[str, Any]] = {}

    def update_position(self, mmsi: int, pos_data: Dict[str, Any], own_lat: Optional[float], own_lon: Optional[float]):
        now = datetime.now(timezone.utc).timestamp()
        if mmsi not in self.targets:
            self.targets[mmsi] = {
                "mmsi": mmsi,
                "vessel_name": "",
                "call_sign": "",
                "ship_type": None,
                "ais_class": pos_data.get("ais_class", "B"),
                "first_seen": now,
            }
        t = self.targets[mmsi]
        t["last_seen"] = now
        t["latitude"] = pos_data.get("latitude")
        t["longitude"] = pos_data.get("longitude")
        t["sog_knots"] = pos_data.get("sog_knots")
        t["cog_true"] = pos_data.get("cog_true")
        t["true_heading"] = pos_data.get("true_heading")
        if "nav_status" in pos_data:
            t["nav_status"] = pos_data["nav_status"]

        # Compute range and bearing if own vessel coordinates are known
        if own_lat is not None and own_lon is not None and t["latitude"] is not None and t["longitude"] is not None:
            dist_nm, bearing = calculate_range_bearing(own_lat, own_lon, t["latitude"], t["longitude"])
            t["range_nm"] = dist_nm
            t["bearing_deg"] = bearing

    def update_static(self, mmsi: int, static_data: Dict[str, Any]):
        now = datetime.now(timezone.utc).timestamp()
        if mmsi not in self.targets:
            self.targets[mmsi] = {
                "mmsi": mmsi,
                "vessel_name": "",
                "call_sign": "",
                "ship_type": None,
                "ais_class": "B",
                "first_seen": now,
            }
        t = self.targets[mmsi]
        t["last_seen"] = now
        if "vessel_name" in static_data and static_data["vessel_name"]:
            t["vessel_name"] = static_data["vessel_name"]
        if "call_sign" in static_data and static_data["call_sign"]:
            t["call_sign"] = static_data["call_sign"]
        if "ship_type" in static_data and static_data["ship_type"] is not None:
            t["ship_type"] = static_data["ship_type"]

    def cleanup(self):
        now = datetime.now(timezone.utc).timestamp()
        stale = [mmsi for mmsi, t in self.targets.items() if now - t.get("last_seen", 0) > self.timeout_sec]
        for mmsi in stale:
            del self.targets[mmsi]

    def get_active_list(self) -> List[Dict[str, Any]]:
        self.cleanup()
        now = datetime.now(timezone.utc).timestamp()
        out = []
        for t in self.targets.values():
            rec = dict(t)
            rec["age_sec"] = round(now - t.get("last_seen", now), 1)
            out.append(rec)
        # Sort by range if available, else by age
        out.sort(key=lambda x: (x.get("range_nm") is None, x.get("range_nm", 9999)))
        return out


class PgnCatalogTracker:
    """Maintains live statistics for all PGNs detected on the SeaTalkNG bus."""

    def __init__(self):
        # PGN -> dict
        self.stats: Dict[int, Dict[str, Any]] = {}

    def record_frame(self, pgn: int, source: int, priority: int, payload: bytes):
        now = datetime.now(timezone.utc).timestamp()
        if pgn not in self.stats:
            self.stats[pgn] = {
                "pgn": pgn,
                "name": PGN_CATALOG.get(pgn, "Proprietary / Unknown"),
                "count": 0,
                "first_seen": now,
                "last_seen": now,
                "sources": set(),
                "last_sample_hex": "",
                "rate_hz": 0.0,
                "_window_count": 0,
                "_window_start": now,
            }
        entry = self.stats[pgn]
        entry["count"] += 1
        entry["last_seen"] = now
        entry["sources"].add(source)
        entry["last_sample_hex"] = payload.hex(" ")
        entry["_window_count"] += 1

    def update_rates(self):
        now = datetime.now(timezone.utc).timestamp()
        for entry in self.stats.values():
            dt = now - entry["_window_start"]
            if dt >= 1.0:
                entry["rate_hz"] = round(entry["_window_count"] / dt, 1)
                entry["_window_count"] = 0
                entry["_window_start"] = now

    def to_list(self) -> List[Dict[str, Any]]:
        self.update_rates()
        res = []
        for pgn, entry in sorted(self.stats.items()):
            res.append({
                "pgn": pgn,
                "name": entry["name"],
                "count": entry["count"],
                "rate_hz": entry["rate_hz"],
                "sources": sorted(list(entry["sources"])),
                "last_sample_hex": entry["last_sample_hex"],
                "last_seen_iso": datetime.fromtimestamp(entry["last_seen"], tz=timezone.utc).isoformat(),
            })
        return res


class SeaTalkNgService:
    """Central daemon running on look to capture, decode, and publish SeaTalkNG data."""

    def __init__(
        self,
        listen_host: str = "0.0.0.0",
        listen_port: int = 8234,
        broker_host: str = "192.168.1.1",
        broker_port: int = 1883,
        use_mqtt: bool = True,
    ):
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.use_mqtt = use_mqtt and (aiomqtt is not None)

        self.decoder = UniversalDecoder()
        self.vessel_state = VesselState()
        self.ais_dir = AisDirectory()
        self.catalog_tracker = PgnCatalogTracker()

        self.mqtt_client: Optional[Any] = None
        self.mqtt_connected = asyncio.Event()
        self.total_frames_received = 0
        self.total_packets_decoded = 0

    async def run(self):
        logger.info(
            "Starting SeaTalkNG Service (Listening on %s:%d | MQTT broker: %s:%d)",
            self.listen_host,
            self.listen_port,
            self.broker_host,
            self.broker_port,
        )

        tasks = [
            asyncio.create_task(self._tcp_server_loop()),
            asyncio.create_task(self._periodic_state_publisher()),
            asyncio.create_task(self._periodic_ais_publisher()),
            asyncio.create_task(self._periodic_catalog_publisher()),
        ]

        if self.use_mqtt:
            tasks.append(asyncio.create_task(self._mqtt_connection_loop()))
        else:
            logger.warning("Running without MQTT publishing (aiomqtt not installed or --no-mqtt passed)")

        await asyncio.gather(*tasks)

    async def _mqtt_connection_loop(self):
        """Maintains persistent connection to Mosquitto broker."""
        while True:
            try:
                logger.info("Connecting to MQTT broker at %s:%d...", self.broker_host, self.broker_port)
                async with aiomqtt.Client(hostname=self.broker_host, port=self.broker_port, identifier="paeraki_seatalkng") as client:
                    self.mqtt_client = client
                    self.mqtt_connected.set()
                    logger.info("Connected to MQTT broker.")
                    # Keep connection alive until disconnection
                    while True:
                        await asyncio.sleep(1.0)
            except Exception as e:
                logger.warning("MQTT connection lost: %s. Reconnecting in 3s...", e)
                self.mqtt_connected.clear()
                self.mqtt_client = None
                await asyncio.sleep(3.0)

    async def _publish(self, topic: str, payload: str):
        """Safe publication helper."""
        if not self.use_mqtt or not self.mqtt_connected.is_set() or self.mqtt_client is None:
            return
        try:
            await self.mqtt_client.publish(topic, payload)
        except Exception as e:
            logger.debug("Failed publishing to %s: %s", topic, e)

    async def _tcp_server_loop(self):
        """Runs the TCP server accepting connections from USR-CAN115."""
        server = await asyncio.start_server(self._handle_client, self.listen_host, self.listen_port)
        async with server:
            await server.serve_forever()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info("peername")
        logger.info("USR-CAN115 connected from %s", addr)
        buffer = bytearray()

        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    logger.warning("USR-CAN115 disconnected from %s", addr)
                    break

                buffer.extend(data)
                while len(buffer) >= 13:
                    if buffer[0] == 0x88:
                        can_id = struct.unpack(">I", buffer[1:5])[0]
                        payload = bytes(buffer[5:13])
                        buffer = buffer[13:]

                        self.total_frames_received += 1
                        prio, dp, pf, ps, sa, dst, pgn = parse_can_id(can_id)
                        self.catalog_tracker.record_frame(pgn, sa, prio, payload)

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

                        record = self.decoder.process_frame(frame)
                        if record is not None:
                            self.total_packets_decoded += 1
                            await self._handle_packet(record, frame)
                    else:
                        buffer.pop(0)
        except Exception as e:
            logger.error("Error in client handler: %s", e, exc_info=True)
        finally:
            writer.close()
            await writer.wait_closed()

    async def _handle_packet(self, record: Dict[str, Any], frame: CanFrame):
        pgn = record["pgn"]
        payload_json = json.dumps(record)

        # 1. Universal PGN publication (all PGNs, decoded or raw fallback)
        await self._publish(f"paeraki/seatalkng/pgn/{pgn}", payload_json)

        # 2. Update state and dispatch specific topics
        now = datetime.now(timezone.utc).timestamp()

        if pgn in (129025, 129029):
            lat = record.get("latitude")
            lon = record.get("longitude")
            if lat is not None and lon is not None:
                self.vessel_state.latitude = lat
                self.vessel_state.longitude = lon
                self.vessel_state.last_updated = now
            if "satellites" in record and record["satellites"] is not None:
                self.vessel_state.satellites = record["satellites"]
            if "hdop" in record and record["hdop"] is not None:
                self.vessel_state.hdop = record["hdop"]
            if "altitude_m" in record and record["altitude_m"] is not None:
                self.vessel_state.altitude_m = record["altitude_m"]

        elif pgn == 129026:
            if "sog_knots" in record and record["sog_knots"] is not None:
                self.vessel_state.sog_knots = record["sog_knots"]
            if "cog_true" in record and record["cog_true"] is not None:
                self.vessel_state.cog_true = record["cog_true"]
            self.vessel_state.last_updated = now

        elif pgn == 127250:
            if "heading_deg" in record and record["heading_deg"] is not None:
                self.vessel_state.heading_deg = record["heading_deg"]
                self.vessel_state.heading_ref = record.get("reference", "Magnetic")
                self.vessel_state.last_updated = now
            if "variation_deg" in record and record["variation_deg"] is not None:
                self.vessel_state.variation_deg = record["variation_deg"]

        elif pgn == 127257:
            if "pitch_deg" in record and record["pitch_deg"] is not None:
                self.vessel_state.pitch_deg = record["pitch_deg"]
            if "roll_deg" in record and record["roll_deg"] is not None:
                self.vessel_state.roll_deg = record["roll_deg"]
            if "yaw_deg" in record and record["yaw_deg"] is not None:
                self.vessel_state.yaw_deg = record["yaw_deg"]
            self.vessel_state.last_updated = now

        elif pgn == 127251:
            if "rate_of_turn_dps" in record and record["rate_of_turn_dps"] is not None:
                self.vessel_state.rate_of_turn_dps = record["rate_of_turn_dps"]

        elif pgn == 127245:
            if "rudder_deg" in record and record["rudder_deg"] is not None:
                self.vessel_state.rudder_deg = record["rudder_deg"]

        elif pgn == 130314:
            if "pressure_hpa" in record and record["pressure_hpa"] is not None:
                self.vessel_state.pressure_hpa = record["pressure_hpa"]

        elif pgn == 65379:
            if "pilot_mode" in record:
                self.vessel_state.pilot_mode = record["pilot_mode"]

        # AIS target processing
        elif pgn in (129038, 129039):
            mmsi = record.get("mmsi")
            if mmsi:
                self.ais_dir.update_position(
                    mmsi, record, self.vessel_state.latitude, self.vessel_state.longitude
                )
                target = self.ais_dir.targets.get(mmsi)
                if target:
                    await self._publish(f"paeraki/seatalkng/ais/target/{mmsi}", json.dumps(target))

        elif pgn in (129809, 129810):
            mmsi = record.get("mmsi")
            if mmsi:
                self.ais_dir.update_static(mmsi, record)
                target = self.ais_dir.targets.get(mmsi)
                if target:
                    await self._publish(f"paeraki/seatalkng/ais/target/{mmsi}", json.dumps(target))

    async def _periodic_state_publisher(self):
        """Publishes consolidated vessel state and individual navigation topics at 1 Hz."""
        while True:
            await asyncio.sleep(1.0)
            state = self.vessel_state.to_dict()
            state["ais_target_count"] = len(self.ais_dir.targets)
            state["frames_received"] = self.total_frames_received
            state["packets_decoded"] = self.total_packets_decoded

            payload = json.dumps(state)
            await self._publish("paeraki/seatalkng/state", payload)

            # Sub-topics
            if state["heading_deg"] is not None:
                await self._publish(
                    "paeraki/seatalkng/heading",
                    json.dumps({
                        "heading_deg": state["heading_deg"],
                        "reference": state["heading_reference"],
                        "variation_deg": state["variation_deg"],
                    }),
                )
            if state["pitch_deg"] is not None or state["roll_deg"] is not None:
                await self._publish(
                    "paeraki/seatalkng/attitude",
                    json.dumps({
                        "pitch_deg": state["pitch_deg"],
                        "roll_deg": state["roll_deg"],
                        "yaw_deg": state["yaw_deg"],
                        "rate_of_turn_dps": state["rate_of_turn_dps"],
                    }),
                )

            # GPS compatibility bridge
            if state["latitude"] is not None and state["longitude"] is not None:
                await self._publish(
                    "paeraki/seatalkng/gps",
                    json.dumps({
                        "latitude": state["latitude"],
                        "longitude": state["longitude"],
                        "sog_knots": state["sog_knots"] or 0.0,
                        "cog_true": state["cog_true"],
                        "satellites": state["satellites"],
                        "hdop": state["hdop"],
                        "altitude_m": state["altitude_m"],
                    }),
                )
                # Bridge to primary vessel GPS topics
                await self._publish("gps/latitude", str(state["latitude"]))
                await self._publish("gps/longitude", str(state["longitude"]))
                if state["sog_knots"] is not None:
                    await self._publish("gps/sog_knots", str(state["sog_knots"]))
                    await self._publish("gps/sog_kmh", str(round(state["sog_knots"] * 1.852, 2)))
                if state["cog_true"] is not None:
                    await self._publish("gps/cog_true", str(state["cog_true"]))
                if state["satellites"] is not None:
                    await self._publish("gps/satellites", str(state["satellites"]))
                if state["hdop"] is not None:
                    await self._publish("gps/hdop", str(state["hdop"]))
                await self._publish("gps/fix", "true")
                await self._publish("gps/fix_status", "GNSS 3D")
                await self._publish("gps/timestamp", state["timestamp"])

    async def _periodic_ais_publisher(self):
        """Publishes the full array of nearby AIS targets every 2 seconds."""
        while True:
            await asyncio.sleep(2.0)
            targets = self.ais_dir.get_active_list()
            await self._publish("paeraki/seatalkng/ais/targets", json.dumps(targets))

    async def _periodic_catalog_publisher(self):
        """Publishes the full PGN bus catalog every 5 seconds."""
        while True:
            await asyncio.sleep(5.0)
            catalog = self.catalog_tracker.to_list()
            await self._publish("paeraki/seatalkng/catalog", json.dumps(catalog))


def main():
    parser = argparse.ArgumentParser(description="Paeraki SeaTalkNG / NMEA 2000 Service")
    parser.add_argument("--listen-host", default="0.0.0.0", help="TCP listen host for USR-CAN115 (default: 0.0.0.0)")
    parser.add_argument("--listen-port", type=int, default=8234, help="TCP listen port for USR-CAN115 (default: 8234)")
    parser.add_argument("--broker-host", default="192.168.1.1", help="MQTT broker host (default: 192.168.1.1)")
    parser.add_argument("--broker-port", type=int, default=1883, help="MQTT broker port (default: 1883)")
    parser.add_argument("--no-mqtt", action="store_true", help="Disable MQTT publishing")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")

    args = parser.parse_args()
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    service = SeaTalkNgService(
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        broker_host=args.broker_host,
        broker_port=args.broker_port,
        use_mqtt=not args.no_mqtt,
    )

    try:
        asyncio.run(service.run())
    except KeyboardInterrupt:
        logger.info("Service stopped by user.")


if __name__ == "__main__":
    main()
