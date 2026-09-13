#!/usr/bin/env python3
"""
Continuous GPS & Navigation Telemetry Collector for yacht Paeraki.
Receives NMEA 0183 sentences from Teltonika RUT955 router over UDP (port 8500),
parses position, velocity, and fix metrics, and publishes to Paeraki MQTT broker.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
import random
import signal
import sys
from typing import Any

# Support running directly or as module
sys.path.insert(0, str(Path(__file__).parent))
from nmea import NmeaState, format_lat_nautical, format_lon_nautical, verify_checksum

try:
    import aiomqtt
except ImportError:
    aiomqtt = None

logger = logging.getLogger("paeraki.gps")


def make_nmea_sentence(body: str) -> str:
    """Calculates XOR checksum and returns formatted NMEA sentence."""
    csum = 0
    for char in body:
        csum ^= ord(char)
    return f"${body}*{csum:02X}\r\n"


class NmeaUdpProtocol(asyncio.DatagramProtocol):
    """Asyncio UDP datagram handler for incoming NMEA sentences."""

    def __init__(self, callback):
        self.callback = callback
        self.buffer = ""

    def datagram_received(self, data: bytes, addr: tuple[str, int]):
        try:
            text = data.decode("ascii", errors="replace")
            self.buffer += text
            while "\n" in self.buffer:
                line, self.buffer = self.buffer.split("\n", 1)
                line = line.strip("\r").strip()
                if line:
                    self.callback(line, addr)
        except Exception as e:
            logger.error("Error processing UDP datagram from %s: %s", addr, e)

    def error_received(self, exc: Exception):
        logger.warning("UDP socket error: %s", exc)


class GpsWatcher:
    """Manages NMEA reception, state tracking, and MQTT publishing."""

    def __init__(
        self,
        broker_host: str = "192.168.1.1",
        broker_port: int = 1883,
        listen_host: str = "0.0.0.0",
        listen_port: int = 8500,
        publish_interval: float = 1.0,
        dry_run: bool = False,
    ):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.publish_interval = publish_interval
        self.dry_run = dry_run

        self.nmea_state = NmeaState()
        self.last_published_epoch = 0.0
        self.last_packet_received_epoch = 0.0
        self.mqtt_client: Any = None
        self.mqtt_connected = asyncio.Event()
        self.sentences_received = 0
        self.sentences_parsed = 0

        # Dry run simulation coordinates (Westhaven Marina towards Rangitoto Channel)
        self.sim_lat = -36.83912
        self.sim_lon = 174.75521
        self.sim_sog = 5.2  # knots
        self.sim_cog = 54.0  # degrees True

    def handle_nmea_line(self, line: str, addr: tuple[str, int] | None = None):
        """Called whenever an NMEA sentence string is received."""
        self.sentences_received += 1
        self.last_packet_received_epoch = asyncio.get_running_loop().time()
        parsed = self.nmea_state.parse_line(line)
        if parsed:
            self.sentences_parsed += 1
            logger.debug("Parsed NMEA (%s): %s", self.nmea_state.last_sentence_type, line)
            asyncio.create_task(self.maybe_publish(line))
        else:
            logger.debug("Unparsed or ignored NMEA: %s", line)

    async def maybe_publish(self, raw_line: str = ""):
        """Publishes telemetry if interval has elapsed or on key sentence epoch."""
        now = asyncio.get_running_loop().time()
        # Publish at most once per publish_interval (or if last sentence was RMC/GGA)
        if now - self.last_published_epoch < self.publish_interval:
            return
        self.last_published_epoch = now

        if not self.mqtt_client:
            return

        state = self.nmea_state.to_dict()
        try:
            # 1. Consolidated state JSON
            payload = json.dumps(state)
            await self.mqtt_client.publish("paeraki/gps/state", payload)

            # 2. Discrete metrics under gps/*
            await self.mqtt_client.publish("gps/fix", str(state["fix"]).lower())
            await self.mqtt_client.publish("gps/fix_status", str(state["fix_status"]))
            if state["latitude"] is not None:
                await self.mqtt_client.publish("gps/latitude", str(state["latitude"]))
                await self.mqtt_client.publish("gps/longitude", str(state["longitude"]))
                await self.mqtt_client.publish("gps/latitude_nautical", state["latitude_nautical"])
                await self.mqtt_client.publish("gps/longitude_nautical", state["longitude_nautical"])
            await self.mqtt_client.publish("gps/sog_knots", str(state["sog_knots"]))
            await self.mqtt_client.publish("gps/sog_kmh", str(state["sog_kmh"]))
            if state["cog_true"] is not None:
                await self.mqtt_client.publish("gps/cog_true", str(state["cog_true"]))
            if state["altitude_m"] is not None:
                await self.mqtt_client.publish("gps/altitude_m", str(state["altitude_m"]))
            await self.mqtt_client.publish("gps/satellites", str(state["satellites"]))
            if state["hdop"] is not None:
                await self.mqtt_client.publish("gps/hdop", str(state["hdop"]))
            await self.mqtt_client.publish("gps/timestamp", state["timestamp"])

            fix_label = "FIX 3D" if state["fix"] else "NO FIX"
            logger.info(
                "GPS published [%s]: %s, %s | SOG: %.1f kts | COG: %s° | Sats: %d",
                fix_label,
                state["latitude_nautical"],
                state["longitude_nautical"],
                state["sog_knots"],
                f"{state['cog_true']:.1f}" if state["cog_true"] is not None else "--",
                state["satellites"],
            )
        except Exception as e:
            logger.error("Failed to publish GPS telemetry to MQTT: %s", e)
            self.mqtt_connected.clear()

    async def run_simulation_step(self):
        """Simulates vessel movement and emits standard NMEA sentences."""
        now_dt = datetime.now(timezone.utc)
        utc_time = now_dt.strftime("%H%M%S.00")
        utc_date = now_dt.strftime("%d%m%y")

        # Slight speed and heading variations for realistic simulation
        self.sim_sog += (random.random() - 0.5) * 0.1
        self.sim_sog = max(3.5, min(7.5, self.sim_sog))
        self.sim_cog += (random.random() - 0.5) * 1.5
        self.sim_cog = (self.sim_cog + 360.0) % 360.0

        # Advance position along cog at sog
        dist_nm = (self.sim_sog / 3600.0)
        d_lat_deg = (dist_nm / 60.0) * math.cos(math.radians(self.sim_cog))
        d_lon_deg = (dist_nm / (60.0 * math.cos(math.radians(self.sim_lat)))) * math.sin(math.radians(self.sim_cog))
        self.sim_lat += d_lat_deg
        self.sim_lon += d_lon_deg

        # Format coordinates for NMEA: ddmm.mmmm and dddmm.mmmm
        lat_abs = abs(self.sim_lat)
        lat_deg = int(lat_abs)
        lat_min = (lat_abs - lat_deg) * 60.0
        lat_nmea = f"{lat_deg:02d}{lat_min:07.4f}"
        lat_hemi = "S" if self.sim_lat < 0 else "N"

        lon_abs = abs(self.sim_lon)
        lon_deg = int(lon_abs)
        lon_min = (lon_abs - lon_deg) * 60.0
        lon_nmea = f"{lon_deg:03d}{lon_min:07.4f}"
        lon_hemi = "W" if self.sim_lon < 0 else "E"

        # 1. $GPRMC
        rmc_body = f"GPRMC,{utc_time},A,{lat_nmea},{lat_hemi},{lon_nmea},{lon_hemi},{self.sim_sog:.2f},{self.sim_cog:.1f},{utc_date},,,A"
        # 2. $GPGGA
        gga_body = f"GPGGA,{utc_time},{lat_nmea},{lat_hemi},{lon_nmea},{lon_hemi},1,09,1.1,2.4,M,0.0,M,,"
        # 3. $GPVTG
        vtg_body = f"GPVTG,{self.sim_cog:.1f},T,,M,{self.sim_sog:.2f},N,{self.sim_sog * 1.852:.2f},K,A"
        # 4. $GPGSA
        gsa_body = "GPGSA,A,3,02,06,12,14,19,24,25,29,31,,,,1.8,1.1,1.4"

        for body in (rmc_body, gga_body, vtg_body, gsa_body):
            sentence = make_nmea_sentence(body)
            self.handle_nmea_line(sentence.strip())

    async def run(self, shutdown_event: asyncio.Event):
        """Main service loop."""
        loop = asyncio.get_running_loop()

        # Register signal handlers
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: shutdown_event.set())
            except (NotImplementedError, RuntimeError):
                pass

        # Start UDP and TCP listeners if not in dry-run
        transport = None
        tcp_server = None
        if not self.dry_run:
            try:
                transport, _ = await loop.create_datagram_endpoint(
                    lambda: NmeaUdpProtocol(self.handle_nmea_line),
                    local_addr=(self.listen_host, self.listen_port),
                )
                logger.info("Listening for NMEA UDP datagrams on %s:%d", self.listen_host, self.listen_port)
            except Exception as e:
                logger.error("Failed to bind UDP port %s:%d: %s", self.listen_host, self.listen_port, e)

            # Start TCP listener so standard BusyBox nc (TCP-only) works seamlessly
            async def handle_tcp_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
                client_addr = writer.get_extra_info("peername")
                logger.info("TCP NMEA client connected from %s", client_addr)
                try:
                    while not shutdown_event.is_set():
                        line = await reader.readline()
                        if not line:
                            break
                        text = line.decode("ascii", errors="replace").strip()
                        if text:
                            self.handle_nmea_line(text, client_addr)
                except Exception as err:
                    logger.debug("TCP client %s error/disconnect: %s", client_addr, err)
                finally:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception:
                        pass
                    logger.info("TCP NMEA client disconnected from %s", client_addr)

            try:
                tcp_server = await asyncio.start_server(
                    handle_tcp_client,
                    self.listen_host,
                    self.listen_port,
                )
                logger.info("Listening for NMEA TCP streams on %s:%d", self.listen_host, self.listen_port)
            except Exception as e:
                logger.warning("Could not bind TCP port %s:%d: %s", self.listen_host, self.listen_port, e)

        while not shutdown_event.is_set():
            try:
                logger.info("Connecting to MQTT broker at %s:%d...", self.broker_host, self.broker_port)
                async with aiomqtt.Client(self.broker_host, port=self.broker_port) as client:
                    self.mqtt_client = client
                    self.mqtt_connected.set()
                    logger.info("Connected to MQTT broker successfully.")

                    # If dry-run simulation mode is active
                    if self.dry_run:
                        logger.info("Dry-run voyage simulation active (Hauraki Gulf route).")
                        while not shutdown_event.is_set() and self.mqtt_connected.is_set():
                            await self.run_simulation_step()
                            try:
                                await asyncio.wait_for(shutdown_event.wait(), timeout=self.publish_interval)
                            except asyncio.TimeoutError:
                                pass
                    else:
                        # Real hardware mode: wait while UDP protocol receives packets
                        while not shutdown_event.is_set() and self.mqtt_connected.is_set():
                            # Heartbeat log every 30 seconds
                            try:
                                await asyncio.wait_for(shutdown_event.wait(), timeout=5.0)
                            except asyncio.TimeoutError:
                                fix_str = "FIX" if self.nmea_state.fix else "WAITING FOR FIX"
                                logger.info(
                                    "GPS watcher status: %s | Sentences received: %d, parsed: %d | Lat: %s, Lon: %s",
                                    fix_str,
                                    self.sentences_received,
                                    self.sentences_parsed,
                                    self.nmea_state.latitude_nautical,
                                    self.nmea_state.longitude_nautical,
                                )

            except Exception as e:
                self.mqtt_client = None
                if not shutdown_event.is_set():
                    logger.warning("MQTT connection error: %s. Retrying in 5 seconds...", e)
                    try:
                        await asyncio.wait_for(shutdown_event.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        pass

        if transport:
            transport.close()
            logger.info("UDP transport closed.")
        if tcp_server:
            tcp_server.close()
            await tcp_server.wait_closed()
            logger.info("TCP server closed.")


def main():
    parser = argparse.ArgumentParser(description="Continuous GPS Navigation Telemetry Collector for yacht Paeraki")
    parser.add_argument("--broker", default="192.168.1.1", help="MQTT broker hostname or IP (default: 192.168.1.1)")
    parser.add_argument("--broker-port", type=int, default=1883, help="MQTT broker port (default: 1883)")
    parser.add_argument("--bind", default="0.0.0.0", help="UDP listen address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8500, help="UDP listen port (default: 8500)")
    parser.add_argument("--interval", type=float, default=1.0, help="Publication interval in seconds (default: 1.0)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate realistic Hauraki Gulf voyage telemetry")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Log level")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    shutdown_event = asyncio.Event()

    watcher = GpsWatcher(
        broker_host=args.broker,
        broker_port=args.broker_port,
        listen_host=args.bind,
        listen_port=args.port,
        publish_interval=args.interval,
        dry_run=args.dry_run,
    )

    try:
        asyncio.run(watcher.run(shutdown_event))
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
