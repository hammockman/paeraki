#!/usr/bin/env python3
"""
72V JBD BMS Telemetry Collector for yacht Paeraki.
Connects to JBD BMS over BLE, polls metrics, and publishes to MQTT.
"""

import argparse
import asyncio
import json
import logging
import random
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

# Support running directly or as module
sys.path.insert(0, str(Path(__file__).parent))
from jbdbms import (
    BASIC_INFO_QUERY,
    CELL_VOLTAGES_QUERY,
    debug_query,
    parse_basic_info,
    parse_cell_voltages,
    validate_response,
)

try:
    import aiomqtt
except ImportError:
    aiomqtt = None

try:
    from bleak import BleakClient, BleakScanner
    from bleak.exc import BleakError
except ImportError:
    BleakClient = None
    BleakScanner = None
    BleakError = Exception

UUID_SERVICE = "0000ff00-0000-1000-8000-00805f9b34fb"
UUID_WRITE = "0000ff02-0000-1000-8000-00805f9b34fb"
UUID_NOTIFY = "0000ff01-0000-1000-8000-00805f9b34fb"

logger = logging.getLogger("paeraki.72v")


class JBDBleClient:
    def __init__(self, address: str):
        self.address = address
        self.client: BleakClient | None = None
        self._rx_buffer = bytearray()
        self._rx_event = asyncio.Event()
        self._lock = asyncio.Lock()

    def _notification_handler(self, sender, data: bytearray):
        logger.debug("RX chunk (%d bytes): %s", len(data), data.hex())
        self._rx_buffer.extend(data)

        # Look for start byte 0xDD
        start_idx = self._rx_buffer.find(b"\xdd")
        if start_idx == -1:
            self._rx_buffer.clear()
            return
        elif start_idx > 0:
            del self._rx_buffer[:start_idx]

        if len(self._rx_buffer) >= 4:
            payload_len = self._rx_buffer[3]
            expected_total_len = payload_len + 7
            if len(self._rx_buffer) >= expected_total_len:
                logger.debug("Frame complete (%d bytes)", expected_total_len)
                self._rx_event.set()

    async def connect(self, timeout: float = 15.0):
        logger.info("Connecting to JBD BMS at %s...", self.address)
        self.client = BleakClient(self.address, timeout=timeout)
        await self.client.connect()
        logger.info("Connected to JBD BMS (%s)", self.address)
        await self.client.start_notify(UUID_NOTIFY, self._notification_handler)
        await asyncio.sleep(0.2)

        # Send JBD BLE App Key handshake (required by JBD BMS firmware)
        logger.debug("Sending JBD BLE App Key handshake...")
        app_key_frame = bytes([0xFF, 0xAA, 0x15, 0x06, 0x30, 0x30, 0x30, 0x30, 0x30, 0x30, 0x3B])
        await self.client.write_gatt_char(UUID_WRITE, app_key_frame, response=False)
        await asyncio.sleep(0.3)

    async def disconnect(self):
        if self.client and self.client.is_connected:
            try:
                await self.client.stop_notify(UUID_NOTIFY)
            except Exception:
                pass
            try:
                await self.client.disconnect()
            except Exception:
                pass
            logger.info("Disconnected from JBD BMS")
        self.client = None

    async def query(self, query_cmd: bytes, timeout: float = 4.0) -> bytes:
        if not self.client or not self.client.is_connected:
            raise ConnectionError("BLE client not connected")

        async with self._lock:
            self._rx_buffer.clear()
            self._rx_event.clear()

            logger.debug("TX query: %s", query_cmd.hex())
            await self.client.write_gatt_char(UUID_WRITE, query_cmd, response=False)

            try:
                await asyncio.wait_for(self._rx_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                raise TimeoutError(
                    f"Timeout waiting for BMS response to query {query_cmd.hex()} (received {len(self._rx_buffer)} bytes)"
                )

            payload_len = self._rx_buffer[3]
            total_len = payload_len + 7
            response = bytes(self._rx_buffer[:total_len])
            del self._rx_buffer[:total_len]

            validate_response(query_cmd, response)
            return response

    async def read_telemetry(self) -> dict:
        basic_bytes = await self.query(BASIC_INFO_QUERY)
        basic_info = parse_basic_info(basic_bytes)

        # Apply deadband filter to eliminate idle ADC shunt noise (< 50mA)
        if abs(basic_info.get("current", 0.0)) < 0.05:
            basic_info["current"] = 0.0
            basic_info["power"] = 0.0

        await asyncio.sleep(0.1)

        cell_bytes = await self.query(CELL_VOLTAGES_QUERY)
        cell_voltages = parse_cell_voltages(cell_bytes)

        telemetry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **basic_info,
            "cell_voltages": cell_voltages,
        }
        return telemetry


def get_mock_telemetry() -> dict:
    """Generates synthetic telemetry matching Paeraki's actual 20S pack profile at rest."""
    mock_cells = [round(4.165 + random.uniform(-0.003, 0.003), 3) for _ in range(20)]
    mock_voltage = round(sum(mock_cells), 2)
    mock_current = 0.00
    mock_power = 0.00

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_voltage": mock_voltage,
        "current": mock_current,
        "power": mock_power,
        "residual_capacity_ah": 150.0,
        "nominal_capacity_ah": 200.0,
        "cycle_times": 2,
        "rsoc": 100,
        "charge_status": True,
        "discharge_status": True,
        "temperatures": [19.0, 12.2, 5.9],
        "active_protection_states": [],
        "balance_states": [False] * 20,
        "number_of_cells": 20,
        "manufacturing_date": "2024-04-18",
        "cell_voltages": mock_cells,
    }


async def publish_telemetry(mqtt_client, telemetry: dict):
    """Publishes both consolidated JSON payload and individual metrics."""
    # Consolidated topic
    await mqtt_client.publish("paeraki/72v/state", payload=json.dumps(telemetry))

    # Individual topics matching legacy/12v style
    for key, value in telemetry.items():
        if isinstance(value, (dict, list)):
            payload = json.dumps(value)
        else:
            payload = str(value)
        await mqtt_client.publish(f"72v/{key}", payload=payload)


async def main():
    parser = argparse.ArgumentParser(description="72V JBD BMS Telemetry Collector for yacht Paeraki")
    parser.add_argument("--address", default="A4:C1:37:14:70:77", help="Bluetooth MAC address of JBD BMS")
    parser.add_argument("--broker", default="192.168.1.1", help="MQTT broker hostname or IP")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--interval", type=float, default=2.0, help="Poll interval in seconds")
    parser.add_argument("--dry-run", action="store_true", help="Simulate telemetry data without connecting to BLE")
    parser.add_argument("--once", action="store_true", help="Collect and publish one reading, then exit")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Log level")
    parser.add_argument("--max-retries", type=int, default=8, help="Maximum consecutive BLE connection/read failures before exiting to let systemd restart (default: 8, 0 to disable)")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    shutdown_event = asyncio.Event()

    def _handle_signal(*_):
        logger.info("Termination signal received. Exiting...")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    logger.info("Starting 72V collector (Broker: %s:%d, Mode: %s)", args.broker, args.port, "DRY-RUN" if args.dry_run else args.address)

    # Dry-run loop
    if args.dry_run:
        if aiomqtt:
            try:
                async with aiomqtt.Client(args.broker, port=args.port) as mqtt_client:
                    logger.info("Connected to MQTT broker at %s:%d", args.broker, args.port)
                    while not shutdown_event.is_set():
                        data = get_mock_telemetry()
                        await publish_telemetry(mqtt_client, data)
                        logger.info("Published dry-run telemetry: %s V, %s A, SoC: %s%%", data["total_voltage"], data["current"], data["rsoc"])
                        if args.once:
                            break
                        try:
                            await asyncio.wait_for(shutdown_event.wait(), timeout=args.interval)
                        except asyncio.TimeoutError:
                            pass
            except Exception as e:
                logger.warning("Could not connect to MQTT broker (%s). Printing mock data to stdout.", e)
                data = get_mock_telemetry()
                print(json.dumps(data, indent=2))
        else:
            data = get_mock_telemetry()
            print(json.dumps(data, indent=2))
        return

    # Live BLE loop
    bms = JBDBleClient(args.address)
    consecutive_mqtt_failures = 0
    while not shutdown_event.is_set():
        try:
            logger.info("Connecting to MQTT broker %s:%d...", args.broker, args.port)
            async with aiomqtt.Client(args.broker, port=args.port) as mqtt_client:
                logger.info("Connected to MQTT broker")
                consecutive_mqtt_failures = 0
                consecutive_ble_failures = 0

                while not shutdown_event.is_set():
                    try:
                        await bms.connect(timeout=10.0)
                        while not shutdown_event.is_set():
                            telemetry = await bms.read_telemetry()
                            await publish_telemetry(mqtt_client, telemetry)
                            consecutive_ble_failures = 0
                            logger.info(
                                "Published: %s V, %s A, %s W, SoC %s%%, %d cells",
                                telemetry["total_voltage"],
                                telemetry["current"],
                                telemetry["power"],
                                telemetry["rsoc"],
                                len(telemetry.get("cell_voltages", [])),
                            )
                            if args.once:
                                shutdown_event.set()
                                break
                            try:
                                await asyncio.wait_for(shutdown_event.wait(), timeout=args.interval)
                            except asyncio.TimeoutError:
                                pass
                    except (BleakError, TimeoutError, ConnectionError, OSError, ValueError) as ble_err:
                        consecutive_ble_failures += 1
                        err_msg = str(ble_err) if str(ble_err) else type(ble_err).__name__
                        logger.warning(
                            "BLE communication error (%s) (%d/%d): %s. Retrying in 5 seconds...",
                            type(ble_err).__name__,
                            consecutive_ble_failures,
                            args.max_retries,
                            err_msg,
                        )
                        await bms.disconnect()
                        if args.max_retries > 0 and consecutive_ble_failures >= args.max_retries:
                            logger.critical(
                                "72V BMS BLE failed %d consecutive times. Exiting process to trigger systemd restart.",
                                consecutive_ble_failures,
                            )
                            sys.exit(1)
                        if args.once:
                            shutdown_event.set()
                            break
                        try:
                            await asyncio.wait_for(shutdown_event.wait(), timeout=5.0)
                        except asyncio.TimeoutError:
                            pass
                    finally:
                        await bms.disconnect()

        except Exception as mqtt_err:
            consecutive_mqtt_failures += 1
            logger.error("MQTT connection error (%d/10): %s. Retrying in 5 seconds...", consecutive_mqtt_failures, mqtt_err)
            if consecutive_mqtt_failures >= 10:
                logger.critical("MQTT broker connection failed %d consecutive times. Exiting to trigger systemd restart.", consecutive_mqtt_failures)
                sys.exit(1)
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass


if __name__ == "__main__":
    asyncio.run(main())
