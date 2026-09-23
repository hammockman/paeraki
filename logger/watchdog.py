#!/usr/bin/env python3
"""
Paeraki Logger Connection Watchdog.
Monitors link health between the logger service, the RUT955 router, and the Look SBC.
Triggers multi-channel alarms (SMS via router gsmctl, Email via SMTP/sendmail)
when connection to either device is lost for more than 1 hour.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from alarms.dispatchers import EmailDispatcher, SmsDispatcher
from alarms.rules import AlarmEvent, AlarmSeverity, AlarmState

logger = logging.getLogger("paeraki.logger.watchdog")

# Topic prefixes known to originate from look
LOOK_TOPIC_PREFIXES = (
    "paeraki/gps",
    "paeraki/seatalkng",
    "paeraki/12v",
    "paeraki/72v",
    "paeraki/fridge",
    "paeraki/alarms",
)


def format_duration(seconds: float) -> str:
    """Format duration in seconds to human-readable string (e.g. '1h 24m' or '45m')."""
    total_minutes = int(seconds // 60)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


class LinkWatchdog:
    """
    Watches MQTT connection to RUT955 router and sensor packet arrivals from Look.
    Dispatches alerts when an outage exceeds the configured threshold (default 1 hour).
    """

    def __init__(
        self,
        timeout_sec: float = 3600.0,
        repeat_interval_sec: float = 7200.0,
        check_interval_sec: float = 30.0,
        phone_number: str | None = "+64274461297",
        recipient_email: str | None = "jjharrington@gmail.com",
        smtp_host: str | None = None,
        smtp_port: int | None = None,
        smtp_user: str | None = None,
        smtp_password: str | None = None,
        sender_email: str | None = None,
        router_ip: str = "192.168.1.1",
        router_user: str = "root",
        db_path: Path | str | None = None,
        dry_run: bool = False,
    ):
        self.timeout_sec = timeout_sec
        self.repeat_interval_sec = repeat_interval_sec
        self.check_interval_sec = check_interval_sec
        self.phone_number = phone_number
        self.recipient_email = recipient_email
        self.router_ip = router_ip
        self.router_user = router_user
        self.db_path = Path(db_path) if db_path else None
        self.dry_run = dry_run

        # Dispatchers
        self.sms_dispatcher = SmsDispatcher(
            phone_number=phone_number,
            router_ip=router_ip,
            router_user=router_user,
            dry_run=dry_run,
        ) if phone_number else None

        self.email_dispatcher = EmailDispatcher(
            recipient_email=recipient_email,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            sender_email=sender_email,
            router_ip=router_ip,
            router_user=router_user,
            dry_run=dry_run,
        ) if recipient_email else None

        # Tracking states
        now = time.time()
        self.broker_connected: bool = False
        self.broker_last_seen: float = now
        self.broker_alarm_state: AlarmState = AlarmState.OK
        self.broker_last_alert_time: float = 0.0

        self.look_last_seen: float = now
        self.look_alarm_state: AlarmState = AlarmState.OK
        self.look_last_alert_time: float = 0.0
        self.look_sms_sent_for_current_alarm: bool = False

        # Seed initial state from DB if available
        if self.db_path:
            self.seed_from_db(self.db_path)

    def seed_from_db(self, db_path: Path) -> None:
        """Seeds the look_last_seen timestamp from the latest packet in the database."""
        if not db_path.exists():
            return

        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cursor = conn.cursor()
            query = """
                SELECT epoch_ms FROM packets
                WHERE topic LIKE 'paeraki/gps%'
                   OR topic LIKE 'paeraki/12v%'
                   OR topic LIKE 'paeraki/72v%'
                   OR topic LIKE 'paeraki/seatalkng%'
                   OR topic LIKE 'paeraki/fridge%'
                ORDER BY epoch_ms DESC LIMIT 1;
            """
            cursor.execute(query)
            row = cursor.fetchone()
            conn.close()

            if row and row[0]:
                self.look_last_seen = row[0] / 1000.0
                dt_str = datetime.fromtimestamp(self.look_last_seen, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                downtime_str = format_duration(time.time() - self.look_last_seen)
                logger.info("Watchdog seeded look last seen from DB: %s (%s ago)", dt_str, downtime_str)
        except Exception as e:
            logger.warning("Could not seed watchdog last seen from DB: %s", e)

    def on_broker_connected(self) -> None:
        """Called when MQTT broker connection is established."""
        now = time.time()
        was_alarm = (self.broker_alarm_state == AlarmState.ALARM)
        outage_duration = now - self.broker_last_seen
        self.broker_connected = True
        self.broker_last_seen = now

        if was_alarm:
            self.broker_alarm_state = AlarmState.OK
            asyncio.create_task(self._dispatch_recovery("RUT955 Router", outage_duration))

        # If look is currently in alarm and SMS hasn't been sent yet, trigger it now via the connected router
        look_downtime = now - self.look_last_seen
        if look_downtime >= self.timeout_sec and not self.look_sms_sent_for_current_alarm:
            self.look_alarm_state = AlarmState.ALARM
            self.look_sms_sent_for_current_alarm = True
            self.look_last_alert_time = now
            asyncio.create_task(
                self._dispatch_alarm(
                    target="look telemetry computer",
                    rule_name="connection_look_lost",
                    downtime=look_downtime,
                    last_seen=self.look_last_seen,
                    can_sms=True,
                    send_email=False,
                )
            )

    def on_broker_disconnected(self) -> None:
        """Called when MQTT broker connection is lost."""
        self.broker_connected = False

    def on_packet(self, topic: str, retain: bool = False) -> None:
        """Called for every incoming MQTT packet. Retained messages are ignored as live packets."""
        if retain:
            return

        now = time.time()
        if any(topic.startswith(prefix) for prefix in LOOK_TOPIC_PREFIXES):
            was_alarm = (self.look_alarm_state == AlarmState.ALARM)
            outage_duration = now - self.look_last_seen
            self.look_last_seen = now
            self.look_sms_sent_for_current_alarm = False

            if was_alarm:
                self.look_alarm_state = AlarmState.OK
                asyncio.create_task(self._dispatch_recovery("look telemetry computer", outage_duration))

    async def check(self) -> None:
        """Evaluates outage timers for RUT955 and Look."""
        now = time.time()

        # 1. Check RUT955 Broker Connection
        if not self.broker_connected:
            downtime = now - self.broker_last_seen
            if downtime >= self.timeout_sec:
                if (
                    self.broker_alarm_state != AlarmState.ALARM
                    or (now - self.broker_last_alert_time) >= self.repeat_interval_sec
                ):
                    self.broker_alarm_state = AlarmState.ALARM
                    self.broker_last_alert_time = now
                    await self._dispatch_alarm(
                        target="RUT955 Router",
                        rule_name="connection_rut955_lost",
                        downtime=downtime,
                        last_seen=self.broker_last_seen,
                        can_sms=False,  # Router is down, so gsmctl won't work
                    )
        else:
            self.broker_last_seen = now

        # 2. Check Look Telemetry Computer
        look_downtime = now - self.look_last_seen
        if look_downtime >= self.timeout_sec:
            if (
                self.look_alarm_state != AlarmState.ALARM
                or (now - self.look_last_alert_time) >= self.repeat_interval_sec
            ):
                self.look_alarm_state = AlarmState.ALARM
                self.look_last_alert_time = now
                # If router is connected, we can send SMS via router gsmctl!
                can_sms = self.broker_connected
                if can_sms:
                    self.look_sms_sent_for_current_alarm = True
                await self._dispatch_alarm(
                    target="look telemetry computer",
                    rule_name="connection_look_lost",
                    downtime=look_downtime,
                    last_seen=self.look_last_seen,
                    can_sms=can_sms,
                )

    async def _dispatch_alarm(
        self,
        target: str,
        rule_name: str,
        downtime: float,
        last_seen: float,
        can_sms: bool = True,
        send_email: bool = True,
    ) -> None:
        duration_str = format_duration(downtime)
        last_seen_dt = datetime.fromtimestamp(last_seen, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        msg = (
            f"Connection to {target} lost for {duration_str}. "
            f"No telemetry received since {last_seen_dt}."
        )
        logger.warning("🚨 [LINK ALARM] %s: %s", rule_name, msg)

        event = AlarmEvent(
            rule_name=rule_name,
            severity=AlarmSeverity.CRITICAL.value,
            state=AlarmState.ALARM.value,
            message=msg,
            timestamp=datetime.now(timezone.utc).isoformat(),
            epoch_ms=int(time.time() * 1000),
            metrics={
                "target": target,
                "downtime_seconds": round(downtime, 1),
                "downtime_formatted": duration_str,
                "last_seen_utc": last_seen_dt,
            },
        )
        status_dict = {"active_count": 1, "alarm": rule_name}

        # 1. SMS Dispatch (if enabled and router is available)
        if can_sms and self.sms_dispatcher:
            try:
                await self.sms_dispatcher.dispatch(event, status_dict)
            except Exception as e:
                logger.error("Failed to dispatch SMS for %s: %s", rule_name, e)

        # 2. Email Dispatch (if enabled and requested)
        if send_email and self.email_dispatcher:
            try:
                await self.email_dispatcher.dispatch(event, status_dict)
            except Exception as e:
                logger.error("Failed to dispatch Email for %s: %s", rule_name, e)

    async def _dispatch_recovery(self, target: str, outage_duration: float) -> None:
        duration_str = format_duration(outage_duration)
        msg = f"Connection to {target} restored after {duration_str} outage."
        logger.info("✅ [LINK RECOVERED] %s", msg)

        event = AlarmEvent(
            rule_name=f"connection_{target.lower().replace(' ', '_')}_recovered",
            severity=AlarmSeverity.INFO.value,
            state=AlarmState.OK.value,
            message=msg,
            timestamp=datetime.now(timezone.utc).isoformat(),
            epoch_ms=int(time.time() * 1000),
            metrics={"target": target, "outage_duration_seconds": round(outage_duration, 1)},
        )
        status_dict = {"active_count": 0}

        if self.sms_dispatcher and self.broker_connected:
            try:
                await self.sms_dispatcher.dispatch(event, status_dict)
            except Exception as e:
                logger.debug("Failed to dispatch recovery SMS: %s", e)

        if self.email_dispatcher:
            try:
                await self.email_dispatcher.dispatch(event, status_dict)
            except Exception as e:
                logger.debug("Failed to dispatch recovery Email: %s", e)

    async def run_loop(self, shutdown_event: asyncio.Event) -> None:
        """Periodic background checking loop."""
        logger.info(
            "LinkWatchdog started (Timeout: %.0fs, Repeat: %.0fs, Check interval: %.0fs)",
            self.timeout_sec,
            self.repeat_interval_sec,
            self.check_interval_sec,
        )
        # Brief grace period on startup allowing MQTT client to establish initial connection
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pass

        while not shutdown_event.is_set():
            try:
                await self.check()
            except Exception as e:
                logger.exception("Error in LinkWatchdog check loop: %s", e)

            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=self.check_interval_sec)
            except asyncio.TimeoutError:
                pass
        logger.info("LinkWatchdog loop stopped.")
