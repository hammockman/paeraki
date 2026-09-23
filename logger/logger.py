#!/usr/bin/env python3
"""
Paeraki Yacht Telemetry Logger Service (runs on hammer).
Lightweight, resilient daemon that subscribes to all MQTT messages from Paeraki
and logs them into SQLite (WAL mode) for fast querying in Python, R, and Julia.
"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

# Add logger directory to sys.path
sys.path.insert(0, str(Path(__file__).parent))
from db import TelemetryDatabase
from watchdog import LinkWatchdog

try:
    import aiomqtt
except ImportError:
    aiomqtt = None

logger = logging.getLogger("paeraki.logger")


async def run_logger(
    broker: str,
    port: int,
    db_path: str,
    batch_size: int = 50,
    flush_interval: float = 2.0,
    retry_delay: float = 3.0,
    enable_alarms: bool = True,
    alarm_timeout: float = 3600.0,
    alarm_repeat: float = 7200.0,
    phone: str | None = "+64274461297",
    email: str | None = "jjharrington@gmail.com",
    dry_run: bool = False,
):
    if not aiomqtt:
        logger.critical("aiomqtt is not installed. Please install dependencies.")
        sys.exit(1)

    db = TelemetryDatabase(db_path=db_path, batch_size=batch_size)
    shutdown_event = asyncio.Event()

    def _handle_signal(*_):
        logger.info("Shutdown signal received. Initiating graceful stop...")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    async def flush_loop():
        """Periodically flushes buffered records even if batch_size threshold isn't reached."""
        while not shutdown_event.is_set():
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=flush_interval)
            except asyncio.TimeoutError:
                db.flush()

    flush_task = asyncio.create_task(flush_loop())

    # Initialize Watchdog if alarms are enabled
    watchdog: LinkWatchdog | None = None
    watchdog_task: asyncio.Task | None = None
    if enable_alarms:
        watchdog = LinkWatchdog(
            timeout_sec=alarm_timeout,
            repeat_interval_sec=alarm_repeat,
            phone_number=phone,
            recipient_email=email,
            router_ip=broker,
            db_path=db_path,
            dry_run=dry_run,
        )
        watchdog_task = asyncio.create_task(watchdog.run_loop(shutdown_event))

    total_logged = 0
    logger.info("Paeraki Logger initialized (Broker: %s:%d, DB: %s, Alarms: %s)", broker, port, db.db_path, enable_alarms)

    while not shutdown_event.is_set():
        try:
            logger.info("Connecting to Paeraki broker at %s:%d...", broker, port)
            async with aiomqtt.Client(broker, port=port) as client:
                logger.info("Connected! Subscribing to wildcard topic '#'...")
                await client.subscribe("#")
                if watchdog:
                    watchdog.on_broker_connected()

                async def _consume():
                    nonlocal total_logged
                    async for msg in client.messages:
                        topic = str(msg.topic)
                        try:
                            payload_str = msg.payload.decode("utf-8")
                        except UnicodeDecodeError:
                            payload_str = f"<binary {len(msg.payload)} bytes>"

                        db.record(topic, payload_str)
                        total_logged += 1

                        if watchdog:
                            watchdog.on_packet(topic, retain=msg.retain)

                        if total_logged % 200 == 0:
                            db_size_kb = round(db.db_path.stat().st_size / 1024, 1) if db.db_path.exists() else 0
                            logger.info("Telemetry logger heartbeat: %d packets recorded (DB size: %s KB)", total_logged, db_size_kb)

                consume_task = asyncio.create_task(_consume())
                shutdown_waiter = asyncio.create_task(shutdown_event.wait())

                done, pending = await asyncio.wait(
                    [consume_task, shutdown_waiter],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if shutdown_event.is_set():
                    consume_task.cancel()
                    try:
                        await consume_task
                    except asyncio.CancelledError:
                        pass
                    break
                else:
                    shutdown_waiter.cancel()
                    consume_task.result()

        except (aiomqtt.MqttError, OSError) as err:
            if watchdog:
                watchdog.on_broker_disconnected()
            if not shutdown_event.is_set():
                logger.warning("Broker connection error: %s. Retrying in %.1fs...", err, retry_delay)
                db.flush()
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=retry_delay)
                except asyncio.TimeoutError:
                    pass
        except Exception as e:
            if watchdog:
                watchdog.on_broker_disconnected()
            logger.exception("Unexpected error in logger loop: %s", e)
            await asyncio.sleep(retry_delay)

    # Cleanup & final flush
    flush_task.cancel()
    if watchdog_task:
        watchdog_task.cancel()
        try:
            await watchdog_task
        except asyncio.CancelledError:
            pass

    try:
        await flush_task
    except asyncio.CancelledError:
        pass

    db.close()
    logger.info("Logger service stopped cleanly. Total packets captured: %d", total_logged)


def main():
    parser = argparse.ArgumentParser(description="Paeraki Vessel Telemetry Logger")
    parser.add_argument("--broker", default="192.168.1.1", help="Paeraki MQTT Broker IP (default: 192.168.1.1)")
    parser.add_argument("--port", type=int, default=1883, help="MQTT Broker port (default: 1883)")
    parser.add_argument("--db-path", default="/home/jh/paeraki/data/paeraki.db", help="Path to SQLite database file")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch size for SQLite transactions (default: 50)")
    parser.add_argument("--flush-interval", type=float, default=2.0, help="Flush interval in seconds (default: 2.0s)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Log level")
    parser.add_argument("--alarm-timeout", type=float, default=3600.0, help="Timeout in seconds before triggering link alarm (default: 3600.0 / 1 hr)")
    parser.add_argument("--alarm-repeat", type=float, default=7200.0, help="Interval in seconds for repeating active alarms (default: 7200.0 / 2 hr)")
    parser.add_argument("--phone", default="+64274461297", help="Mobile phone number for router SMS dispatch")
    parser.add_argument("--email", default="jjharrington@gmail.com", help="Email address for alarm notifications")
    parser.add_argument("--disable-alarms", action="store_true", help="Disable connection watchdog and alarm dispatching")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode for dispatchers (logs instead of sending)")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    asyncio.run(run_logger(
        broker=args.broker,
        port=args.port,
        db_path=args.db_path,
        batch_size=args.batch_size,
        flush_interval=args.flush_interval,
        enable_alarms=not args.disable_alarms,
        alarm_timeout=args.alarm_timeout,
        alarm_repeat=args.alarm_repeat,
        phone=args.phone if args.phone else None,
        email=args.email if args.email else None,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
