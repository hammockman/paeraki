#!/usr/bin/env python3
"""
Paeraki Yacht Rolling Buffer Telemetry Logger (runs on sing).
Lightweight, resilient daemon that subscribes to Paeraki MQTT messages,
maintains a configurable rolling buffer (default 3 days) in SQLite WAL mode,
filters redundant high-frequency scalar subtopics, and supports sync-aware
pruning for seamless catch-up replication to hammer.
"""

import argparse
import asyncio
import logging
from pathlib import Path
import signal
import sys

# Add logger directory to sys.path
sys.path.insert(0, str(Path(__file__).parent))
from buffer_db import BufferTelemetryDatabase

try:
    import aiomqtt
except ImportError:
    aiomqtt = None

logger = logging.getLogger("paeraki.buffer_logger")


async def run_buffer_logger(
    broker: str,
    port: int,
    db_path: str,
    retention_days: float = 3.0,
    prune_interval_hours: float = 1.0,
    batch_size: int = 100,
    flush_interval: float = 3.0,
    log_all_packets: bool = False,
    disk_safety_gb: float = 15.0,
    retry_delay: float = 3.0,
):
    if not aiomqtt:
        logger.critical("aiomqtt is not installed. Please install dependencies.")
        sys.exit(1)

    db = BufferTelemetryDatabase(
        db_path=db_path,
        batch_size=batch_size,
        log_all_packets=log_all_packets,
    )
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
        """Periodically flushes buffered records even if batch_size isn't reached."""
        while not shutdown_event.is_set():
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=flush_interval)
            except asyncio.TimeoutError:
                db.flush()

    async def prune_loop():
        """Periodically cleans up old records based on retention policy and sync state."""
        interval_seconds = max(60.0, prune_interval_hours * 3600.0)
        # Initial wait of 60 seconds before first prune
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=60.0)
        except asyncio.TimeoutError:
            pass

        while not shutdown_event.is_set():
            try:
                db.flush()
                pruned = db.prune(retention_days=retention_days, disk_safety_gb=disk_safety_gb)
                total_pruned = sum(pruned.values())
                if total_pruned > 0:
                    logger.info("Pruned %d records: %s", total_pruned, pruned)
            except Exception as e:
                logger.error("Unexpected error in prune loop: %s", e)

            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=interval_seconds)
            except asyncio.TimeoutError:
                pass

    flush_task = asyncio.create_task(flush_loop())
    prune_task = asyncio.create_task(prune_loop())

    total_logged = 0
    logger.info(
        "Paeraki Buffer Logger initialized (Broker: %s:%d, DB: %s, Retention: %.1f days, LogAll: %s)",
        broker, port, db.db_path, retention_days, log_all_packets
    )

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

                    if total_logged % 500 == 0:
                        db_size_kb = round(db.db_path.stat().st_size / 1024, 1) if db.db_path.exists() else 0
                        logger.info(
                            "Buffer logger heartbeat: %d messages handled (DB size: %s KB)",
                            total_logged, db_size_kb
                        )

        except (aiomqtt.MqttError, OSError) as err:
            if not shutdown_event.is_set():
                logger.warning("Broker connection error: %s. Retrying in %.1fs...", err, retry_delay)
                db.flush()
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=retry_delay)
                except asyncio.TimeoutError:
                    pass
        except Exception as e:
            logger.exception("Unexpected error in buffer logger loop: %s", e)
            await asyncio.sleep(retry_delay)

    # Cleanup & final flush
    flush_task.cancel()
    prune_task.cancel()
    try:
        await asyncio.gather(flush_task, prune_task, return_exceptions=True)
    except Exception:
        pass

    db.close()
    logger.info("Buffer logger stopped cleanly. Total messages handled: %d", total_logged)


def main():
    parser = argparse.ArgumentParser(description="Paeraki Vessel Telemetry Buffer Logger (sing)")
    parser.add_argument("--broker", default="192.168.1.1", help="Paeraki MQTT Broker IP (default: 192.168.1.1)")
    parser.add_argument("--port", type=int, default=1883, help="MQTT Broker port (default: 1883)")
    parser.add_argument("--db-path", default="/home/jh/paeraki/data/paeraki_buffer.db", help="Path to SQLite buffer file")
    parser.add_argument("--retention-days", type=float, default=3.0, help="Retention buffer duration in days (default: 3.0)")
    parser.add_argument("--prune-interval-hours", type=float, default=1.0, help="Interval between prune runs in hours (default: 1.0)")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size for SQLite transactions (default: 100)")
    parser.add_argument("--flush-interval", type=float, default=3.0, help="Flush interval in seconds (default: 3.0)")
    parser.add_argument("--log-all-packets", action="store_true", help="Log all raw packets verbatim without filtering redundant scalar subtopics")
    parser.add_argument("--disk-safety-gb", type=float, default=15.0, help="Minimum free disk space (GB) before forced pruning (default: 15.0)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Log level")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    asyncio.run(run_buffer_logger(
        broker=args.broker,
        port=args.port,
        db_path=args.db_path,
        retention_days=args.retention_days,
        prune_interval_hours=args.prune_interval_hours,
        batch_size=args.batch_size,
        flush_interval=args.flush_interval,
        log_all_packets=args.log_all_packets,
        disk_safety_gb=args.disk_safety_gb,
    ))


if __name__ == "__main__":
    main()
