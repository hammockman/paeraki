#!/usr/bin/env python3
"""
12V Renogy / SRNE Solar Telemetry Collector for yacht Paeraki.
Connects to Renogy/SRNE BT-1/BT-2 module over BLE, polls Modbus registers,
and publishes structured telemetry to MQTT broker.
"""

import argparse
import asyncio
import json
import logging
import signal
import sys
from datetime import datetime, timezone

try:
    import aiomqtt
except ImportError:
    aiomqtt = None

try:
    from renogy_lib_python.modbus_comm import EnhancedModbusClient
except ImportError:
    EnhancedModbusClient = None

logger = logging.getLogger("paeraki.12v")


def get_mock_telemetry() -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "battery_voltage": 13.8,
        "battery_soc": 100,
        "battery_charge_current": 3.46,
        "solar_power": 50,
        "solar_voltage": 45.0,
        "solar_current": 1.11,
        "load_voltage": 13.8,
        "load_current": 0.0,
        "load_power": 0,
        "daily_yield_kwh": 2.083,
        "daily_load_kwh": 0.092,
        "charging_status": "Float",
        "controller_temperature": 18,
        "battery_temperature": 25,
        "product_model": "Shiner2440",
    }


CHARGING_MODES = {
    0: "Deactivated",
    1: "Activated",
    2: "MPPT Charge",
    3: "Equalize",
    4: "Boost MPPT",
    5: "Float",
    6: "Current Limiting",
}


async def read_controller_telemetry(client: EnhancedModbusClient) -> dict:
    """
    Read contiguous block of 34 holding registers from 0x0100 to 0x0121 in ONE Modbus frame.
    Accurately extracts all solar, battery, load, temperature, and status registers.
    """
    raw = await client.read_holding_registers(0x0100, 34)
    if not raw or len(raw) < 68:
        raise ValueError(f"Incomplete Modbus response from controller: {len(raw) if raw else 0} bytes")

    regs = {}
    for i in range(0, len(raw), 2):
        reg = 0x0100 + (i // 2)
        regs[reg] = (raw[i] << 8) | raw[i + 1]

    batt_soc = int(regs[0x0100])
    batt_v = round(regs[0x0101] * 0.1, 2)
    chg_i = round(regs[0x0102] * 0.01, 2)

    # 0x0103: Temperatures (High byte = Controller temp, Low byte = Battery temp)
    temp_raw = regs[0x0103]
    ctrl_temp = (temp_raw >> 8) & 0xFF
    if ctrl_temp > 127:
        ctrl_temp -= 256
    batt_temp = temp_raw & 0xFF
    if batt_temp > 127:
        batt_temp -= 256

    # 0x0104 - 0x0106: DC Load Output
    load_v = round(regs[0x0104] * 0.1, 2)
    load_i = round(regs[0x0105] * 0.01, 2)
    load_p = int(regs[0x0106])

    # 0x0107 - 0x0109: Solar PV Input
    pv_v = round(regs[0x0107] * 0.1, 2)
    pv_i = round(regs[0x0108] * 0.01, 2)
    pv_p = int(regs[0x0109])  # Accurate Solar Power from register 0x0109

    # Energy metrics
    daily_yield_kwh = round(regs[0x0113] * 0.001, 3)
    daily_load_kwh = round(regs[0x0114] * 0.001, 3)

    # Status / Charging Mode (0x0120)
    status_raw = regs[0x0120]
    charging_mode_code = status_raw & 0x00FF
    mode_str = CHARGING_MODES.get(charging_mode_code, f"Mode {charging_mode_code}")

    iso_now = datetime.now(timezone.utc).isoformat()

    telemetry = {
        "timestamp": iso_now,
        "battery_voltage": batt_v,
        "battery_soc": batt_soc,
        "battery_charge_current": chg_i,
        "solar_power": float(pv_p),
        "solar_voltage": pv_v,
        "solar_current": pv_i,
        "load_voltage": load_v,
        "load_current": load_i,
        "load_power": load_p,
        "daily_yield_kwh": daily_yield_kwh,
        "daily_load_kwh": daily_load_kwh,
        "charging_status": mode_str,
        "controller_temperature": ctrl_temp,
        "battery_temperature": batt_temp,
        "product_model": "Shiner2440",
        "raw_registers": {f"0x{r:04X}": v for r, v in regs.items()},
    }
    return telemetry


async def publish_12v_telemetry(mqtt_client, telemetry: dict):
    await mqtt_client.publish("paeraki/12v/state", payload=json.dumps(telemetry))


async def main():
    parser = argparse.ArgumentParser(description="12V Renogy / SRNE Solar Telemetry Collector for yacht Paeraki")
    parser.add_argument("--address", default="D8:B6:73:BE:8F:BF", help="Bluetooth MAC address of BT-1 dongle")
    parser.add_argument("--broker", default="192.168.1.1", help="MQTT broker hostname or IP")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--interval", type=float, default=2.0, help="Poll interval in seconds")
    parser.add_argument("--dry-run", action="store_true", help="Simulate data without connecting to BLE")
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

    logger.info("Starting 12V collector (Broker: %s:%d, Target: %s)", args.broker, args.port, "DRY-RUN" if args.dry_run else args.address)

    # Dry-run loop
    if args.dry_run:
        if aiomqtt:
            try:
                async with aiomqtt.Client(args.broker, port=args.port) as mqtt_client:
                    logger.info("Connected to MQTT broker at %s:%d", args.broker, args.port)
                    while not shutdown_event.is_set():
                        mock_data = get_mock_telemetry()
                        await publish_12v_telemetry(mqtt_client, mock_data)
                        logger.info("Published dry-run 12V telemetry: %s V, %s W", mock_data["battery_voltage"], mock_data["solar_power"])
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

    # Live BLE Loop
    consecutive_mqtt_failures = 0
    while not shutdown_event.is_set():
        try:
            logger.info("Connecting to MQTT broker %s:%d...", args.broker, args.port)
            async with aiomqtt.Client(args.broker, port=args.port) as mqtt_client:
                logger.info("Connected to MQTT broker")
                consecutive_mqtt_failures = 0
                consecutive_ble_failures = 0

                while not shutdown_event.is_set():
                    client = EnhancedModbusClient(slave_address=0xFF)
                    connected = False
                    try:
                        logger.info("Connecting to Renogy BT dongle at %s...", args.address)
                        connected = await client.connect(args.address)
                        if not connected:
                            raise ConnectionError(f"Failed to connect to {args.address}")
                        
                        logger.info("Connected to Renogy BT dongle (%s)", args.address)

                        while not shutdown_event.is_set():
                            telemetry = await read_controller_telemetry(client)
                            await publish_12v_telemetry(mqtt_client, telemetry)
                            consecutive_ble_failures = 0
                            logger.info(
                                "12V Live: Batt %sV (%s%%) | PV %sV, %sW | Load %sV, %sA (%sW) | Temp Ctrl %s°C, Batt %s°C | Status %s",
                                telemetry["battery_voltage"],
                                telemetry["battery_soc"],
                                telemetry["solar_voltage"],
                                telemetry["solar_power"],
                                telemetry["load_voltage"],
                                telemetry["load_current"],
                                telemetry["load_power"],
                                telemetry["controller_temperature"],
                                telemetry["battery_temperature"],
                                telemetry["charging_status"],
                            )

                            if args.once:
                                shutdown_event.set()
                                break

                            try:
                                await asyncio.wait_for(shutdown_event.wait(), timeout=args.interval)
                            except asyncio.TimeoutError:
                                pass

                    except (aiomqtt.MqttError, aiomqtt.MqttCodeError) if aiomqtt else ConnectionError as mqtt_publish_err:
                        logger.warning("MQTT error during 12V telemetry publish: %s. Reconnecting to MQTT broker...", mqtt_publish_err)
                        break
                    except Exception as ble_err:
                        consecutive_ble_failures += 1
                        logger.warning(
                            "Renogy BLE communication error (%d/%d): %s. Retrying in 5s...",
                            consecutive_ble_failures,
                            args.max_retries,
                            ble_err,
                        )
                        if args.max_retries > 0 and consecutive_ble_failures >= args.max_retries:
                            logger.critical(
                                "Renogy BLE failed %d consecutive times. Exiting process to trigger systemd restart.",
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
                        if connected:
                            try:
                                await client.disconnect()
                            except Exception:
                                pass

        except Exception as mqtt_err:
            consecutive_mqtt_failures += 1
            logger.error("MQTT connection error (%d/10): %s. Retrying in 5s...", consecutive_mqtt_failures, mqtt_err)
            if consecutive_mqtt_failures >= 10:
                logger.critical("MQTT broker connection failed %d consecutive times. Exiting to trigger systemd restart.", consecutive_mqtt_failures)
                sys.exit(1)
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass


if __name__ == "__main__":
    asyncio.run(main())
