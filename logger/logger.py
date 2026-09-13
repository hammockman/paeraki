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

    total_logged = 0
    logger.info("Paeraki Logger initialized (Broker: %s:%d, DB: %s)", broker, port, db.db_path)

    while not shutdown_event.is_set():
        try:
            logger.info("Connecting to Paeraki broker at %s:%d...", broker, port)
            async with aiomqtt.Client(broker, port=port) as client:
                logger.info("Connected! Subscribing to wildcard topic '#'...")
                await client.subscribe("#")

                async for msg in client.messages:
                    if shutdown_event.is_set():
                        break

                    topic = str(msg.topic)
                    try:
                        payload_str = msg.payload.decode("utf-8")
                    except UnicodeDecodeError:
                        payload_str = f"<binary {len(msg.payload)} bytes>"

                    db.record(topic, payload_str)
                    total_logged += 1

                    if total_logged % 200 == 0:
                        db_size_kb = round(db.db_path.stat().st_size / 1024, 1) if db.db_path.exists() else 0
                        logger.info("Telemetry logger heartbeat: %d packets recorded (DB size: %s KB)", total_logged, db_size_kb)

        except (aiomqtt.MqttError, OSError) as err:
            if not shutdown_event.is_set():
                logger.warning("Broker connection error: %s. Retrying in %.1fs...", err, retry_delay)
                db.flush()
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=retry_delay)
                except asyncio.TimeoutError:
                    pass
        except Exception as e:
            logger.exception("Unexpected error in logger loop: %s", e)
            await asyncio.sleep(retry_delay)

    # Cleanup & final flush
    flush_task.cancel()
    try:
        await flush_task
    except asyncio.CancelledError:
        pass

    db.close()
    logger.info("Logger service stopped cleanly. Total packets captured: %d", total_logged)


def main():
    parser = argparse.ArgumentParser(description="Paeraki Vessel Telemetry Logger (hammer)")
    parser.add_argument("--broker", default="192.168.1.1", help="Paeraki MQTT Broker IP (default: 192.168.1.1)")
    parser.add_argument("--port", type=int, default=1883, help="MQTT Broker port (default: 1883)")
    parser.add_argument("--db-path", default="/home/jh/paeraki/data/paeraki.db", help="Path to SQLite database file")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch size for SQLite transactions (default: 50)")
    parser.add_argument("--flush-interval", type=float, default=2.0, help="Flush interval in seconds (default: 2.0s)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Log level")
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
        flush_interval=args.flush_interval
    ))


if __name__ == "__main__":
    main()
