#!/usr/bin/env python3
"""
Vesper Cortex Telemetry & Control Daemon for Paeraki.

Maintains an active WebSocket session with Cortex M1 Hub:
- Ingests Anchor Watch status, active alarms, and system telemetry.
- Publishes real-time state to Mosquitto MQTT.
- Subscribes to command topic to execute per-alarm silencing and MoB triggers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import aiomqtt
except ImportError:
    aiomqtt = None

from cortex.client import CortexClient
from cortex.discovery import discover_cortex_host

logger = logging.getLogger("paeraki.cortex.watch")

TOPIC_ANCHOR = "paeraki/cortex/anchor"
TOPIC_ALARMS = "paeraki/cortex/alarms"
TOPIC_TELEMETRY = "paeraki/cortex/telemetry"
TOPIC_COMMAND = "paeraki/cortex/command"
TOPIC_MOB = "paeraki/cortex/mob/alert"


def get_mock_cortex_telemetry() -> tuple[dict, list[dict], dict]:
    """Generates synthetic Cortex data for dry-run testing."""
    now_iso = datetime.now(timezone.utc).isoformat()
    anchor = {
        "active": True,
        "anchor_lat": -36.8485,
        "anchor_lon": 174.7633,
        "radius_m": 35.0,
        "distance_m": 14.2,
        "bearing_deg": 125.0,
        "drag_alarm": False,
        "last_updated": now_iso,
    }
    alarms = [
        {
            "id": "cpa_target_512004210",
            "type": "CollisionRisk",
            "severity": "WARNING",
            "message": "CPA 0.2 NM with TE AWA in 6 mins",
            "silenceable": True,
            "silenced": False,
            "timestamp": now_iso,
        }
    ]
    telemetry = {
        "host": "cortex.local",
        "connected": True,
        "battery_v": 13.4,
        "pressure_hpa": 1014.6,
        "firmware": "2.1.0",
        "serial": "VSP-M1-88412",
        "network_status": {"mode": "BoatNetwork", "ip": "192.168.1.50", "ssid": "Paeraki-WiFi"},
        "last_seen": now_iso,
    }
    return anchor, alarms, telemetry


class CortexDaemon:
    """Manages Cortex connection, MQTT streaming, and remote commands."""

    def __init__(
        self,
        broker_host: str = "192.168.1.1",
        broker_port: int = 1883,
        cortex_host: Optional[str] = None,
        cortex_port: int = 8000,
        enable_mock: bool = False,
    ):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.preferred_cortex_host = cortex_host
        self.cortex_port = cortex_port
        self.enable_mock = enable_mock

        self.client: Optional[CortexClient] = None
        self._mqtt_client: Optional[Any] = None
        self._running = False

    async def start(self) -> None:
        """Starts daemon main loop."""
        self._running = True
        logger.info(
            "Starting Cortex Daemon (MQTT: %s:%d, Mock: %s)",
            self.broker_host,
            self.broker_port,
            self.enable_mock,
        )

        if self.enable_mock:
            await self._run_mock_loop()
            return

        while self._running:
            try:
                # Discover active Cortex host
                target_host = await discover_cortex_host(
                    preferred_host=self.preferred_cortex_host,
                    port=self.cortex_port,
                )
                self.client = CortexClient(host=target_host, port=self.cortex_port)
                self.client.on_anchor_update = self._on_anchor_update
                self.client.on_alarms_update = self._on_alarms_update
                self.client.on_telemetry_update = self._on_telemetry_update

                # Run MQTT bridge and WebSocket listener concurrently
                await asyncio.gather(
                    self._run_mqtt_bridge(),
                    self.client.connect_and_listen(),
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Cortex loop error: %s. Reconnecting in 5s...", e)
                if self.client:
                    self.client.close()
                await asyncio.sleep(5.0)

    async def _run_mqtt_bridge(self) -> None:
        """Connects to MQTT and listens for command payloads."""
        if aiomqtt is None:
            logger.error("aiomqtt library not installed. MQTT publishing disabled.")
            return

        async with aiomqtt.Client(self.broker_host, self.broker_port) as mqtt_client:
            self._mqtt_client = mqtt_client
            logger.info("Connected to Paeraki MQTT broker! Subscribing to %s...", TOPIC_COMMAND)
            await mqtt_client.subscribe(TOPIC_COMMAND)

            async for message in mqtt_client.messages:
                if not self._running:
                    break
                await self._handle_mqtt_command(str(message.payload.decode("utf-8")))

    async def _handle_mqtt_command(self, payload_str: str) -> None:
        """Executes commands received over MQTT."""
        try:
            cmd = json.loads(payload_str)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON command: %s", payload_str)
            return

        action = cmd.get("command")
        logger.info("Received Cortex command: %s", action)

        if action == "silence":
            alarm_id = cmd.get("alarm_id")
            if alarm_id and self.client:
                ok, msg = await self.client.silence_alarm(alarm_id)
                logger.info("Silence result for %s: %s (%s)", alarm_id, ok, msg)
            elif not alarm_id:
                logger.warning("Silence command missing 'alarm_id'")

        elif action == "mob":
            now_iso = datetime.now(timezone.utc).isoformat()
            mob_payload = {
                "active": True,
                "timestamp": now_iso,
                "source": cmd.get("source", "dashboard"),
                "note": "Man Overboard event triggered from Paeraki console",
            }
            logger.critical("MAN OVERBOARD TRIGGERED: %s", mob_payload)
            if self._mqtt_client:
                await self._mqtt_client.publish(TOPIC_MOB, json.dumps(mob_payload), retain=True)

        elif action == "set_anchor_watch":
            radius = float(cmd.get("radius", 30.0))
            lat = cmd.get("lat")
            lon = cmd.get("lon")
            if self.client:
                ok, msg = await self.client.set_anchor_watch(radius, lat=lat, lon=lon)
                logger.info("Set anchor watch result: %s (%s)", ok, msg)

    def _on_anchor_update(self, state: dict) -> None:
        """Callback when Cortex anchor watch state updates."""
        if self._mqtt_client:
            asyncio.create_task(
                self._mqtt_client.publish(TOPIC_ANCHOR, json.dumps(state), retain=True)
            )

    def _on_alarms_update(self, alarms: list[dict]) -> None:
        """Callback when Cortex active alarms update."""
        if self._mqtt_client:
            asyncio.create_task(
                self._mqtt_client.publish(TOPIC_ALARMS, json.dumps(alarms), retain=True)
            )

    def _on_telemetry_update(self, telemetry: dict) -> None:
        """Callback when Cortex telemetry updates."""
        if self._mqtt_client:
            asyncio.create_task(
                self._mqtt_client.publish(TOPIC_TELEMETRY, json.dumps(telemetry), retain=True)
            )

    async def _run_mock_loop(self) -> None:
        """Runs mock loop for dry-run testing."""
        logger.info("Running in MOCK mode. Generating simulated Cortex telemetry...")
        while self._running:
            anchor, alarms, telemetry = get_mock_cortex_telemetry()
            logger.debug("Mock Cortex: Anchor distance=%.1fm, Active alarms=%d",
                         anchor["distance_m"], len(alarms))
            if self._mqtt_client:
                await self._mqtt_client.publish(TOPIC_ANCHOR, json.dumps(anchor), retain=True)
                await self._mqtt_client.publish(TOPIC_ALARMS, json.dumps(alarms), retain=True)
                await self._mqtt_client.publish(TOPIC_TELEMETRY, json.dumps(telemetry), retain=True)
            await asyncio.sleep(5.0)

    def stop(self) -> None:
        """Stops the daemon."""
        self._running = False
        if self.client:
            self.client.close()


def main():
    parser = argparse.ArgumentParser(description="Paeraki Vesper Cortex Telemetry Daemon")
    parser.add_argument("--broker", default="192.168.1.1", help="MQTT Broker host (default: 192.168.1.1)")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT Broker port (default: 1883)")
    parser.add_argument("--cortex-host", default=None, help="Explicit Cortex M1 IP/host")
    parser.add_argument("--cortex-port", type=int, default=8000, help="Cortex port (default: 8000)")
    parser.add_argument("--mock", action="store_true", help="Run with synthetic mock data")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    daemon = CortexDaemon(
        broker_host=args.broker,
        broker_port=args.mqtt_port,
        cortex_host=args.cortex_host,
        cortex_port=args.cortex_port,
        enable_mock=args.mock,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def shutdown():
        logger.info("Shutting down Cortex daemon...")
        daemon.stop()
        for task in asyncio.all_tasks(loop):
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown)
        except NotImplementedError:
            pass

    try:
        loop.run_until_complete(daemon.start())
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
