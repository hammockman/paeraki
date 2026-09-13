#!/usr/bin/env python3
"""
BF Tech (Hexapower) 72V Battery Charger Telemetry Collector for yacht Paeraki.
Polls charger HTTP interface at 192.168.4.1 (via dedicated wlan1 interface)
and publishes metrics to MQTT broker at 192.168.1.1:1883.
"""

import argparse
import asyncio
import json
import logging
import math
import random
import re
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import aiomqtt
except ImportError:
    aiomqtt = None

logger = logging.getLogger("paeraki.charger")

DEFAULT_CHARGER_URL = "http://192.168.4.1"
DEFAULT_BROKER = "192.168.1.1"
DEFAULT_PORT = 1883


class ChargerPoller:
    """HTTP client to query and extract metrics from BF Tech charger."""

    def __init__(self, base_url: str = DEFAULT_CHARGER_URL, timeout: float = 2.5):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.status_endpoint = "/status"  # will auto-adapt if needed
        self.is_connected = False
        self.consecutive_failures = 0

    def query(self) -> dict:
        """Fetch and parse charger metrics."""
        # Try candidate endpoints in priority order
        endpoints_to_try = [self.status_endpoint, "/status.json", "/data", "/api/status", "/"]

        for ep in endpoints_to_try:
            url = f"{self.base_url}{ep}"
            req = Request(url, headers={"User-Agent": "Paeraki-Charger-Watch/1.0"})
            try:
                with urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                    parsed = self._parse_response(raw)
                    if parsed:
                        self.status_endpoint = ep
                        self.is_connected = True
                        self.consecutive_failures = 0
                        return parsed
            except (HTTPError, URLError, TimeoutError, OSError):
                continue

        self.consecutive_failures += 1
        self.is_connected = False
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "epoch_ms": int(time.time() * 1000),
            "state": "OFFLINE",
            "output_voltage": 0.0,
            "output_current": 0.0,
            "output_power": 0.0,
            "target_current": 20.0,
            "temperature": 0.0,
            "error_code": "CONNECTION_TIMEOUT",
        }

    def _parse_response(self, raw: str) -> dict | None:
        """Parse JSON response or scrape HTML."""
        now = datetime.now(timezone.utc)
        epoch_ms = int(now.timestamp() * 1000)

        # 1. Try direct JSON parse
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                v = float(data.get("voltage") or data.get("output_voltage") or data.get("v") or 0.0)
                i = float(data.get("current") or data.get("output_current") or data.get("a") or 0.0)
                p = float(data.get("power") or data.get("w") or round(v * i, 1))
                state = str(data.get("state") or data.get("status") or ("CHARGING" if i > 0.5 else "IDLE")).upper()
                temp = float(data.get("temp") or data.get("temperature") or 0.0)
                target_i = float(data.get("target_current") or data.get("max_current") or 20.0)
                error = str(data.get("error") or data.get("fault") or "NONE")

                return {
                    "timestamp": now.isoformat(),
                    "epoch_ms": epoch_ms,
                    "state": state,
                    "output_voltage": round(v, 2),
                    "output_current": round(i, 2),
                    "output_power": round(p, 1),
                    "target_current": round(target_i, 1),
                    "temperature": round(temp, 1),
                    "error_code": error,
                }
        except Exception:
            pass

        # 2. Try regex extraction from HTML / JS
        v_match = re.search(r"(?:voltage|volt|v_out)\s*[:=]\s*([\d\.]+)", raw, re.I)
        i_match = re.search(r"(?:current|curr|i_out|amps?)\s*[:=]\s*([\d\.]+)", raw, re.I)
        temp_match = re.search(r"(?:temp(?:erature)?)\s*[:=]\s*([\d\.]+)", raw, re.I)

        if v_match or i_match:
            v = float(v_match.group(1)) if v_match else 0.0
            i = float(i_match.group(1)) if i_match else 0.0
            p = round(v * i, 1)
            temp = float(temp_match.group(1)) if temp_match else 0.0
            state = "CHARGING" if i > 0.5 else "IDLE"

            return {
                "timestamp": now.isoformat(),
                "epoch_ms": epoch_ms,
                "state": state,
                "output_voltage": round(v, 2),
                "output_current": round(i, 2),
                "output_power": p,
                "target_current": 20.0,
                "temperature": round(temp, 1),
                "error_code": "NONE",
            }

        return None


class MockCharger:
    """Simulates realistic BF Tech 72V 20A charging and current-hunting behavior."""

    def __init__(self):
        self.base_v = 79.5
        self.step = 0
        self.state = "CHARGING"

    def query(self) -> dict:
        self.step += 1
        now = datetime.now(timezone.utc)
        t = self.step * 0.1

        # Simulate 20A hunting / oscillation cycle between 11A and 19.8A
        oscillation = math.sin(t * 0.5) * 4.0 + math.cos(t * 1.2) * 1.5
        curr = max(0.0, min(20.0, 15.5 + oscillation + random.uniform(-0.4, 0.4)))
        volt = round(self.base_v + (curr * 0.04) + (self.step * 0.002), 2)
        power = round(volt * curr, 1)
        temp = round(32.0 + (curr * 0.5) + math.sin(t * 0.1) * 2.0, 1)

        return {
            "timestamp": now.isoformat(),
            "epoch_ms": int(now.timestamp() * 1000),
            "state": "CHARGING" if curr > 0.8 else "IDLE",
            "output_voltage": volt,
            "output_current": round(curr, 2),
            "output_power": power,
            "target_current": 20.0,
            "temperature": temp,
            "error_code": "NONE",
        }


async def publish_telemetry(client: aiomqtt.Client, data: dict):
    """Publish charger metrics to standard MQTT topics."""
    await client.publish("charger/state", data["state"], qos=0)
    await client.publish("charger/voltage", str(data["output_voltage"]), qos=0)
    await client.publish("charger/current", str(data["output_current"]), qos=0)
    await client.publish("charger/power", str(data["output_power"]), qos=0)
    await client.publish("charger/temperature", str(data["temperature"]), qos=0)
    await client.publish("charger/target_current", str(data["target_current"]), qos=0)

    # Full structured payload
    payload_json = json.dumps(data)
    await client.publish("charger/telemetry", payload_json, qos=1)
    await client.publish("paeraki/charger/state", payload_json, qos=1)


async def main_loop(args):
    shutdown_event = asyncio.Event()

    def _handle_signal():
        logger.info("Shutdown signal received. Exiting...")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    poller = MockCharger() if args.mock else ChargerPoller(args.url, timeout=args.timeout)

    logger.info(
        "Starting BF Tech Charger Poller (URL: %s, Broker: %s:%d, Mode: %s)",
        args.url,
        args.broker,
        args.port,
        "MOCK" if args.mock else "LIVE",
    )

    if not aiomqtt:
        logger.warning("aiomqtt not installed. Printing telemetry to stdout.")
        while not shutdown_event.is_set():
            data = poller.query()
            print(json.dumps(data, indent=2))
            if args.once:
                break
            await asyncio.sleep(args.interval)
        return

    while not shutdown_event.is_set():
        try:
            logger.info("Connecting to MQTT broker %s:%d...", args.broker, args.port)
            async with aiomqtt.Client(args.broker, port=args.port) as client:
                logger.info("Connected to MQTT broker successfully.")

                while not shutdown_event.is_set():
                    data = poller.query()

                    if data["state"] == "OFFLINE":
                        logger.warning("Charger unreachable at %s. Retrying...", args.url)
                        poll_interval = max(args.interval, 8.0)
                    else:
                        poll_interval = args.interval

                    await publish_telemetry(client, data)
                    logger.info(
                        "Charger [%s]: %.2f V | %.2f A | %.1f W | T: %.1f°C",
                        data["state"],
                        data["output_voltage"],
                        data["output_current"],
                        data["output_power"],
                        data["temperature"],
                    )

                    if args.once:
                        shutdown_event.set()
                        break

                    try:
                        await asyncio.wait_for(shutdown_event.wait(), timeout=poll_interval)
                    except asyncio.TimeoutError:
                        pass

        except (aiomqtt.MqttError, OSError) as err:
            if not shutdown_event.is_set():
                logger.warning("MQTT broker error: %s. Retrying in 5 seconds...", err)
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass


def main():
    parser = argparse.ArgumentParser(description="Paeraki BF Tech Charger Watcher")
    parser.add_argument("--url", default=DEFAULT_CHARGER_URL, help="Charger HTTP URL (default: http://192.168.4.1)")
    parser.add_argument("--broker", default=DEFAULT_BROKER, help="MQTT Broker IP (default: 192.168.1.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="MQTT Broker port (default: 1883)")
    parser.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds (default: 2.0)")
    parser.add_argument("--timeout", type=float, default=2.5, help="HTTP request timeout in seconds (default: 2.5)")
    parser.add_argument("--mock", action="store_true", help="Run in mock mode (simulates hunting 72V 20A charger)")
    parser.add_argument("--once", action="store_true", help="Poll once and exit")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Log level")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    asyncio.run(main_loop(args))


if __name__ == "__main__":
    main()
