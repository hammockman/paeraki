#!/usr/bin/env python3
"""
Brass Monkey Dual-Zone Fridge Telemetry Collector for yacht Paeraki.
Connects to Alpicool/Brass Monkey Bluetooth controller over BLE, polls status,
and publishes structured telemetry to MQTT broker.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from datetime import datetime, timezone
from typing import Optional

from pathlib import Path

# Support running directly or as module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import aiomqtt
except ImportError:
    aiomqtt = None

from bleak import BleakClient
from bleak.exc import BleakError

from fridge.protocol import (
    CHAR_NOTIFY_UUID,
    CHAR_WRITE_UUID,
    FridgeTelemetry,
    FridgeZoneData,
    decode_fridge_packet,
    encode_query_packet,
)

logger = logging.getLogger("paeraki.fridge")


def get_mock_telemetry() -> dict:
    """Generates realistic mock telemetry for dry-run testing."""
    iso_now = datetime.now(timezone.utc).isoformat()
    return {
        "timestamp": iso_now,
        "powered_on": True,
        "controls_locked": False,
        "run_mode": "Eco",
        "battery_saver": "Mid",
        "battery_voltage": 13.2,
        "battery_percent": 100,
        "temperature_unit": "Celsius",
        "compressor_running": False,
        "running_status_code": 0,
        "left_zone": {
            "current_temperature": 3,
            "target_temperature": 5,
            "hysteresis": 2,
            "temp_correction_hot": -3,
            "temp_correction_mid": -3,
            "temp_correction_cold": -3,
            "temp_correction_halt": 0,
        },
        "right_zone": {
            "current_temperature": 4,
            "target_temperature": 4,
            "hysteresis": 2,
            "temp_correction_hot": -3,
            "temp_correction_mid": -3,
            "temp_correction_cold": -3,
            "temp_correction_halt": 0,
        },
    }


async def publish_fridge_telemetry(mqtt_client, telemetry_dict: dict):
    """Publishes consolidated and discrete MQTT topics."""
    # 1. Consolidated state JSON
    await mqtt_client.publish("paeraki/fridge/state", payload=json.dumps(telemetry_dict))

    # 2. Discrete sensor topics for convenience
    left = telemetry_dict.get("left_zone", {})
    right = telemetry_dict.get("right_zone")

    if left and "current_temperature" in left:
        await mqtt_client.publish("paeraki/fridge/left/temperature", payload=str(left["current_temperature"]))
        await mqtt_client.publish("paeraki/fridge/left/target", payload=str(left.get("target_temperature", "")))

    if right and "current_temperature" in right:
        await mqtt_client.publish("paeraki/fridge/right/temperature", payload=str(right["current_temperature"]))
        await mqtt_client.publish("paeraki/fridge/right/target", payload=str(right.get("target_temperature", "")))

    if "battery_voltage" in telemetry_dict:
        await mqtt_client.publish("paeraki/fridge/voltage", payload=str(telemetry_dict["battery_voltage"]))

    if "compressor_running" in telemetry_dict:
        running_str = "1" if telemetry_dict["compressor_running"] else "0"
        await mqtt_client.publish("paeraki/fridge/compressor", payload=running_str)

    if "run_mode" in telemetry_dict:
        await mqtt_client.publish("paeraki/fridge/mode", payload=str(telemetry_dict["run_mode"]))


class FridgeBLEClient:
    """Encapsulates BLE GATT session with Alpicool/Brass Monkey fridge."""

    def __init__(self, address: str, timeout: float = 12.0):
        self.address = address
        self.timeout = timeout
        self.client: Optional[BleakClient] = None
        self._notify_future: Optional[asyncio.Future[bytes]] = None
        self._rx_buffer = bytearray()

    async def connect(self):
        self.client = BleakClient(self.address, timeout=self.timeout)
        await self.client.connect()
        await self.client.start_notify(CHAR_NOTIFY_UUID, self._on_notify)

    async def disconnect(self):
        if self.client:
            try:
                if self.client.is_connected:
                    await self.client.stop_notify(CHAR_NOTIFY_UUID)
                await self.client.disconnect()
            except Exception:
                pass
            finally:
                self.client = None

    def _on_notify(self, sender, data: bytearray):
        self._rx_buffer.extend(data)
        # Search for frame header 0xFE 0xFE
        idx = self._rx_buffer.find(b"\xFE\xFE")
        if idx > 0:
            del self._rx_buffer[:idx]
            idx = 0

        if idx == 0 and len(self._rx_buffer) >= 4:
            pkt_len = self._rx_buffer[2]
            expected_total = pkt_len + 3
            if len(self._rx_buffer) >= expected_total:
                frame = bytes(self._rx_buffer[:expected_total])
                del self._rx_buffer[:expected_total]
                if self._notify_future and not self._notify_future.done():
                    self._notify_future.set_result(frame)

    async def query_status(self, response_timeout: float = 3.5) -> Optional[FridgeTelemetry]:
        if not self.client or not self.client.is_connected:
            raise ConnectionError("BLE client is not connected")

        loop = asyncio.get_running_loop()
        self._notify_future = loop.create_future()
        self._rx_buffer.clear()

        query_pkt = encode_query_packet()
        await self.client.write_gatt_char(CHAR_WRITE_UUID, query_pkt, response=True)

        try:
            frame = await asyncio.wait_for(self._notify_future, timeout=response_timeout)
            return decode_fridge_packet(frame)
        finally:
            self._notify_future = None


async def main():
    parser = argparse.ArgumentParser(description="Brass Monkey Dual-Zone Fridge Telemetry Collector for yacht Paeraki")
    parser.add_argument("--address", default="FF:FF:11:73:D1:71", help="Bluetooth MAC address of Brass Monkey fridge")
    parser.add_argument("--broker", default="192.168.1.1", help="MQTT broker hostname or IP")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--interval", type=float, default=300.0, help="Poll interval in seconds (default: 300.0 / 5 min)")
    parser.add_argument("--persistent", action="store_true", help="Maintain persistent BLE connection instead of periodic disconnect")
    parser.add_argument("--dry-run", action="store_true", help="Simulate telemetry without connecting to BLE")
    parser.add_argument("--once", action="store_true", help="Collect and publish one reading, then exit")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Log level")
    parser.add_argument("--max-retries", type=int, default=8, help="Consecutive failure limit before exiting for restart")
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

    disconnect_after_poll = not args.persistent

    logger.info(
        "Starting Fridge collector (Broker: %s:%d, Target: %s, Interval: %.1fs, Mode: %s)",
        args.broker,
        args.port,
        "DRY-RUN" if args.dry_run else args.address,
        args.interval,
        "Persistent" if args.persistent else "Periodic Disconnect (5-min)",
    )

    # Dry-run execution
    if args.dry_run:
        if aiomqtt:
            try:
                async with aiomqtt.Client(args.broker, port=args.port) as mqtt_client:
                    logger.info("Connected to MQTT broker at %s:%d", args.broker, args.port)
                    while not shutdown_event.is_set():
                        mock_data = get_mock_telemetry()
                        await publish_fridge_telemetry(mqtt_client, mock_data)
                        logger.info(
                            "Fridge Dry-Run: Left %s°C | Right %s°C | %sV | Mode %s",
                            mock_data["left_zone"]["current_temperature"],
                            mock_data["right_zone"]["current_temperature"],
                            mock_data["battery_voltage"],
                            mock_data["run_mode"],
                        )
                        if args.once:
                            break
                        try:
                            await asyncio.wait_for(shutdown_event.wait(), timeout=args.interval)
                        except asyncio.TimeoutError:
                            pass
            except Exception as e:
                logger.warning("Could not connect to MQTT broker (%s). Printing to stdout.", e)
                print(json.dumps(get_mock_telemetry(), indent=2))
        else:
            print(json.dumps(get_mock_telemetry(), indent=2))
        return

    # Live BLE execution
    consecutive_mqtt_failures = 0
    while not shutdown_event.is_set():
        try:
            logger.info("Connecting to MQTT broker %s:%d...", args.broker, args.port)
            async with aiomqtt.Client(args.broker, port=args.port) as mqtt_client:
                logger.info("Connected to MQTT broker")
                consecutive_mqtt_failures = 0
                consecutive_ble_failures = 0

                ble_client = FridgeBLEClient(args.address)

                while not shutdown_event.is_set():
                    try:
                        if not ble_client.client or not ble_client.client.is_connected:
                            logger.info("Connecting to Brass Monkey fridge at %s...", args.address)
                            await ble_client.connect()
                            logger.info("Connected to Brass Monkey fridge (%s)", args.address)

                        while not shutdown_event.is_set():
                            telemetry = await ble_client.query_status()
                            if telemetry:
                                data_dict = telemetry.to_dict()
                                data_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
                                await publish_fridge_telemetry(mqtt_client, data_dict)
                                consecutive_ble_failures = 0

                                right_str = f" | Right {telemetry.right_zone.current_temperature}°C (set {telemetry.right_zone.target_temperature}°C)" if telemetry.right_zone else ""
                                logger.info(
                                    "Fridge Live: Left %s°C (set %s°C)%s | Compressor: %s | %sV (%s/%s)",
                                    telemetry.left_zone.current_temperature,
                                    telemetry.left_zone.target_temperature,
                                    right_str,
                                    "Running" if telemetry.compressor_running else "Idle",
                                    telemetry.battery_voltage,
                                    telemetry.run_mode,
                                    telemetry.battery_saver,
                                )

                            if args.once:
                                shutdown_event.set()
                                break

                            if disconnect_after_poll:
                                await ble_client.disconnect()

                            try:
                                await asyncio.wait_for(shutdown_event.wait(), timeout=args.interval)
                            except asyncio.TimeoutError:
                                pass

                            if disconnect_after_poll and not shutdown_event.is_set():
                                break

                    except (aiomqtt.MqttError, aiomqtt.MqttCodeError) if aiomqtt else ConnectionError as mqtt_err:
                        logger.warning("MQTT error during fridge publish: %s. Reconnecting...", mqtt_err)
                        await ble_client.disconnect()
                        break
                    except Exception as ble_err:
                        consecutive_ble_failures += 1
                        logger.warning(
                            "Fridge BLE error (%d/%d): %s. Retrying in 5s...",
                            consecutive_ble_failures,
                            args.max_retries,
                            ble_err,
                        )
                        await ble_client.disconnect()

                        if args.max_retries > 0 and consecutive_ble_failures >= args.max_retries:
                            logger.critical(
                                "Fridge BLE failed %d consecutive times. Exiting to trigger systemd restart.",
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
                        if args.once or shutdown_event.is_set():
                            await ble_client.disconnect()

        except Exception as mqtt_err:
            consecutive_mqtt_failures += 1
            logger.error("MQTT connection error (%d/10): %s. Retrying in 5s...", consecutive_mqtt_failures, mqtt_err)
            if consecutive_mqtt_failures >= 10:
                logger.critical("MQTT broker connection failed repeatedly. Exiting for systemd restart.")
                sys.exit(1)
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass


if __name__ == "__main__":
    asyncio.run(main())
