#!/usr/bin/env python3
"""
Paeraki Vessel Alarms Monitor Daemon (runs on look).
Subscribes to live vessel telemetry over MQTT, monitors alarm rules (including
12V AGM 50% DoD limit, 72V low battery, and pack overtemperature), and dispatches
multi-channel notifications to MQTT and Teltonika Router SMS.
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

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import aiomqtt
except ImportError:
    aiomqtt = None

from alarms.dispatchers import ConsoleDispatcher, MqttDispatcher, SmsDispatcher, EmailDispatcher
from alarms.rules import (
    AlarmEngine,
    Low12VCapacityRule,
    Low72VBatteryRule,
    BatteryOverheatRule,
    ServiceRestartLoopRule,
)

logger = logging.getLogger("paeraki.alarms")

MONITORED_SERVICES = [
    ("12v", "watch_12v.service", "12V Solar Monitor"),
    ("72v", "watch_72v.service", "72V BMS Monitor"),
    ("gps", "watch_gps.service", "GPS Navigation Monitor"),
    ("seatalkng", "paeraki_seatalkng.service", "SeaTalkNG Bus Monitor"),
]


_systemd_query_lock = asyncio.Lock()


async def query_systemd_services(units: list[str]) -> dict[str, dict]:
    """Queries systemd process metrics for target service units via non-blocking systemctl."""
    if _systemd_query_lock.locked():
        return {}
    async with _systemd_query_lock:
        cmd = [
            "systemctl", "show", *units,
            "-p", "Id",
            "-p", "ActiveState",
            "-p", "SubState",
            "-p", "NRestarts",
            "-p", "ExecMainStatus",
            "-p", "ExecMainExitTimestamp",
            "-p", "ActiveEnterTimestamp",
        ]
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=4.0)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                logger.debug("Timeout querying systemctl show")
                return {}

            lines = stdout.decode("utf-8").splitlines()
            services = {}
            curr = {}
            for line in lines:
                line = line.strip()
                if not line:
                    if "id" in curr:
                        services[curr["id"]] = curr
                        curr = {}
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    k_norm = k.strip().lower()
                    v_norm = v.strip()
                    if k_norm in ("nrestarts", "execmainstatus"):
                        try:
                            curr[k_norm] = int(v_norm)
                        except ValueError:
                            curr[k_norm] = 0
                    else:
                        curr[k_norm] = v_norm
            if "id" in curr:
                services[curr["id"]] = curr
            return services
        except Exception as e:
            if proc:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
            logger.debug("Could not query systemd status: %s", e)
            return {}


async def run_alarm_monitor(
    broker: str,
    port: int,
    phone_number: str | None = None,
    email: str | None = None,
    smtp_host: str = "192.168.1.1",
    smtp_port: int = 25,
    router_ip: str = "192.168.1.1",
    eval_interval: float = 1.0,
    dry_run: bool = False,
    mock: bool = False,
    once: bool = False,
):
    if not aiomqtt and not mock:
        logger.critical("aiomqtt is required for live MQTT monitoring. Install dependencies or run with --mock.")
        sys.exit(1)

    shutdown_event = asyncio.Event()

    def _handle_signal(*_):
        logger.info("Shutdown signal received. Stopping alarm daemon...")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    engine = AlarmEngine([
        Low12VCapacityRule(debounce_sec=2.0 if mock else 10.0),
        Low72VBatteryRule(debounce_sec=2.0 if mock else 10.0),
        BatteryOverheatRule(debounce_sec=2.0 if mock else 5.0),
        ServiceRestartLoopRule("12v", "watch_12v.service", "12V Solar Monitor", failure_threshold=5),
        ServiceRestartLoopRule("72v", "watch_72v.service", "72V BMS Monitor", failure_threshold=5),
        ServiceRestartLoopRule("gps", "watch_gps.service", "GPS Navigation Monitor", failure_threshold=5),
        ServiceRestartLoopRule("seatalkng", "paeraki_seatalkng.service", "SeaTalkNG Bus Monitor", failure_threshold=5),
    ])

    console_disp = ConsoleDispatcher()
    sms_disp = SmsDispatcher(
        phone_number=phone_number,
        router_ip=router_ip,
        dry_run=dry_run,
    )
    email_disp = EmailDispatcher(
        recipient_email=email,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        router_ip=router_ip,
        dry_run=dry_run,
    )

    if mock:
        logger.info("Running in MOCK mode. Simulating telemetry scenarios...")
        await _run_mock_loop(engine, [console_disp, sms_disp, email_disp], shutdown_event, eval_interval, once)
        return

    while not shutdown_event.is_set():
        try:
            logger.info("Connecting to MQTT broker %s:%d...", broker, port)
            async with aiomqtt.Client(broker, port=port) as client:
                logger.info("Connected to MQTT broker. Subscribing to vessel telemetry...")
                await client.subscribe("paeraki/#")

                mqtt_disp = MqttDispatcher(client)
                dispatchers = [console_disp, mqtt_disp, sms_disp, email_disp]

                # Background evaluation task
                async def eval_loop():
                    last_status_publish = 0.0
                    last_systemd_poll = 0.0
                    unit_names = [u for _, u, _ in MONITORED_SERVICES]
                    while not shutdown_event.is_set():
                        try:
                            await asyncio.wait_for(shutdown_event.wait(), timeout=eval_interval)
                        except asyncio.TimeoutError:
                            now = asyncio.get_event_loop().time()

                            # Periodic systemd status query every 10.0s
                            if not mock and (now - last_systemd_poll) >= 10.0:
                                svc_data = await query_systemd_services(unit_names)
                                if svc_data:
                                    engine.update_systemd(svc_data)
                                last_systemd_poll = now

                            events = engine.evaluate()
                            status = engine.get_status()
                            for ev in events:
                                for d in dispatchers:
                                    await d.dispatch(ev, status)
                                last_status_publish = now

                            # Periodic status heartbeat every 5s even when no state transitions
                            if (now - last_status_publish) >= 5.0:
                                await mqtt_disp.publish_status(status)
                                last_status_publish = now

                eval_task = asyncio.create_task(eval_loop())

                try:
                    async for msg in client.messages:
                        if shutdown_event.is_set():
                            break

                        topic = str(msg.topic)
                        try:
                            payload_str = msg.payload.decode("utf-8")
                            data = json.loads(payload_str)
                            if not isinstance(data, dict):
                                continue
                        except Exception:
                            continue

                        # Route to subsystem
                        if topic == "paeraki/12v/state":
                            engine.update_telemetry("12v", data)
                        elif topic == "paeraki/72v/state":
                            engine.update_telemetry("72v", data)
                        elif topic == "paeraki/gps/state":
                            engine.update_telemetry("gps", data)
                        elif topic == "paeraki/charger/state":
                            engine.update_telemetry("charger", data)
                        elif topic.startswith("paeraki/battery/"):
                            if "72v" in topic:
                                engine.update_telemetry("72v", data)
                            elif "12v" in topic:
                                engine.update_telemetry("12v", data)

                        if once:
                            shutdown_event.set()
                            break

                finally:
                    eval_task.cancel()
                    try:
                        await eval_task
                    except asyncio.CancelledError:
                        pass

        except (aiomqtt.MqttError, OSError) as err:
            if not shutdown_event.is_set():
                logger.warning("Broker connection error: %s. Retrying in 5s...", err)
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
        except Exception as e:
            logger.exception("Unexpected error in alarm monitor: %s", e)
            await asyncio.sleep(5.0)

    logger.info("Alarm monitor daemon stopped cleanly.")


async def _run_mock_loop(
    engine: AlarmEngine,
    dispatchers: list,
    shutdown_event: asyncio.Event,
    interval: float,
    once: bool,
):
    """Generates synthetic telemetry scenarios to verify alarm triggering, notification, and recovery."""
    step = 0
    while not shutdown_event.is_set():
        step += 1
        now_iso = datetime.now(timezone.utc).isoformat()

        # Phase 1 (Steps 1-3): Normal operation (12V at 80%, 72V at 85%)
        if step <= 3:
            v_12v = 12.65
            soc_12v = 80.0
            v_72v = 80.0
            soc_72v = 85.0
            phase = "NORMAL"

        # Phase 2 (Steps 4-7): 12V battery drops to 48% (below 50% limit)
        elif step <= 7:
            v_12v = 12.10
            soc_12v = 48.0
            v_72v = 79.5
            soc_72v = 82.0
            phase = "12V DROP <= 50%"

        # Phase 3 (Steps 8-10): 12V battery drops to 38% (escalates to CRITICAL)
        elif step <= 10:
            v_12v = 11.95
            soc_12v = 38.0
            v_72v = 79.0
            soc_72v = 80.0
            phase = "12V CRITICAL <= 40%"

        # Phase 4 (Steps 11-14): Solar charges 12V back to 58% (hysteresis recovery >= 55%)
        else:
            v_12v = 13.20
            soc_12v = 58.0
            v_72v = 80.0
            soc_72v = 82.0
            phase = "RECOVERY >= 55%"

        engine.update_telemetry("12v", {
            "battery_voltage": v_12v,
            "soc_12v_active": soc_12v,
            "battery_temperature": 22.0,
            "timestamp": now_iso,
        })
        engine.update_telemetry("72v", {
            "total_voltage": v_72v,
            "soc_integrated": soc_72v,
            "temp_1": 24.0,
            "temp_2": 23.5,
            "timestamp": now_iso,
        })

        events = engine.evaluate()
        status = engine.get_status()

        logger.info(
            "[Mock Step %02d | %s] 12V: %.2fV (%.1f%%) | Active Alarms: %d | Status: %s",
            step, phase, v_12v, soc_12v, status["active_count"], status["overall_status"]
        )

        for ev in events:
            for d in dispatchers:
                await d.dispatch(ev, status)

        if once or step >= 15:
            logger.info("Mock simulation finished successfully.")
            shutdown_event.set()
            break

        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


def main():
    parser = argparse.ArgumentParser(description="Paeraki Vessel Alarms Monitor Daemon")
    parser.add_argument("--broker", default="192.168.1.1", help="Paeraki MQTT Broker IP (default: 192.168.1.1)")
    parser.add_argument("--port", type=int, default=1883, help="MQTT Broker port (default: 1883)")
    parser.add_argument("--phone", default=None, help="Recipient phone number for SMS alerts via Teltonika router")
    parser.add_argument("--email", default=None, help="Recipient email address for alarms via Teltonika relay")
    parser.add_argument("--smtp-host", default="192.168.1.1", help="SMTP relay host (default: 192.168.1.1)")
    parser.add_argument("--smtp-port", type=int, default=25, help="SMTP relay port (default: 25)")
    parser.add_argument("--router-ip", default="192.168.1.1", help="Teltonika router IP (default: 192.168.1.1)")
    parser.add_argument("--interval", type=float, default=1.0, help="Evaluation interval in seconds (default: 1.0s)")
    parser.add_argument("--dry-run", action="store_true", help="Log simulated SMS/email instead of sending")
    parser.add_argument("--mock", action="store_true", help="Run simulated telemetry scenario")
    parser.add_argument("--once", action="store_true", help="Run single evaluation cycle and exit")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Log level")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    asyncio.run(run_alarm_monitor(
        broker=args.broker,
        port=args.port,
        phone_number=args.phone,
        email=args.email,
        smtp_host=args.smtp_host,
        smtp_port=args.smtp_port,
        router_ip=args.router_ip,
        eval_interval=args.interval,
        dry_run=args.dry_run,
        mock=args.mock,
        once=args.once,
    ))


if __name__ == "__main__":
    main()
