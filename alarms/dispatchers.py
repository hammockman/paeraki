#!/usr/bin/env python3
"""
Multi-Channel Alert Dispatchers for Paeraki Vessel Alarms.
Routes alarms to MQTT, Teltonika Router SMS (gsmctl), and system logs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
from typing import Any

from alarms.rules import AlarmEvent, AlarmSeverity

logger = logging.getLogger("paeraki.alarms.dispatchers")


class BaseDispatcher:
    """Base interface for alarm notification channels."""

    async def dispatch(self, event: AlarmEvent, consolidated_status: dict[str, Any]) -> bool:
        raise NotImplementedError


class ConsoleDispatcher(BaseDispatcher):
    """Outputs alert events to standard log."""

    async def dispatch(self, event: AlarmEvent, consolidated_status: dict[str, Any]) -> bool:
        prefix = "🚨 [ALARM]" if event.state != "OK" else "✅ [CLEARED]"
        logger.warning("%s %s (%s): %s", prefix, event.rule_name, event.severity, event.message)
        return True


class MqttDispatcher(BaseDispatcher):
    """Publishes individual alarm events and consolidated alarm status to MQTT."""

    def __init__(self, mqtt_client: Any):
        self.mqtt_client = mqtt_client

    async def dispatch(self, event: AlarmEvent, consolidated_status: dict[str, Any]) -> bool:
        if not self.mqtt_client:
            return False

        try:
            # 1. Publish individual event
            event_topic = f"paeraki/alarms/{event.rule_name}"
            event_payload = json.dumps(event.to_dict())
            await self.mqtt_client.publish(event_topic, payload=event_payload, retain=True)

            # 2. Publish consolidated state snapshot
            state_topic = "paeraki/alarms/state"
            state_payload = json.dumps(consolidated_status)
            await self.mqtt_client.publish(state_topic, payload=state_payload, retain=True)
            logger.debug("Published alarm event to MQTT (%s)", event_topic)
            return True
        except Exception as e:
            logger.error("Failed to publish alarm to MQTT: %s", e)
            return False

    async def publish_status(self, consolidated_status: dict[str, Any]) -> bool:
        if not self.mqtt_client:
            return False
        try:
            state_topic = "paeraki/alarms/state"
            state_payload = json.dumps(consolidated_status)
            await self.mqtt_client.publish(state_topic, payload=state_payload, retain=True)
            return True
        except Exception as e:
            logger.error("Failed to publish alarm status to MQTT: %s", e)
            return False


class SmsDispatcher(BaseDispatcher):
    """
    Dispatches SMS notifications via Teltonika RUT955 router GSM daemon (gsmctl).
    Executes: ssh root@<router-ip> "gsmctl -S -s '<phone>' '<message>'"
    """

    def __init__(
        self,
        phone_number: str | None,
        router_ip: str = "192.168.1.1",
        router_user: str = "root",
        dry_run: bool = False,
    ):
        self.phone_number = phone_number
        self.router_ip = router_ip
        self.router_user = router_user
        self.dry_run = dry_run

    async def dispatch(self, event: AlarmEvent, consolidated_status: dict[str, Any]) -> bool:
        # Only send SMS for active ALARM states (not for informational clears unless critical)
        if event.state == "OK" and event.severity != AlarmSeverity.CRITICAL.value:
            return True

        if not self.phone_number:
            logger.debug("No phone number configured; skipping SMS dispatch.")
            return False

        # Format concise nautical SMS
        prefix = "PAERAKI ALERT" if event.state != "OK" else "PAERAKI RESOLVED"
        sms_body = f"{prefix}: {event.message} [{event.timestamp[:19]}]"

        if self.dry_run:
            logger.info("[DRY-RUN SMS] Would send to %s: '%s'", self.phone_number, sms_body)
            return True

        # Run SSH gsmctl asynchronously (RutOS requires number and text in one quoted argument)
        sms_content = f"{self.phone_number} {sms_body}"
        safe_arg = shlex.quote(sms_content)
        cmd = f"ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=5 {self.router_user}@{self.router_ip} 'gsmctl -S -s {safe_arg}'"

        logger.info("Sending SMS via Teltonika router to %s...", self.phone_number)
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                logger.error("Timeout connecting to router for SMS dispatch")
                return False

            if proc.returncode == 0:
                logger.info("SMS dispatched successfully via router: %s", stdout.decode().strip())
                return True
            else:
                logger.warning("Router gsmctl failed (code %d): %s", proc.returncode, stderr.decode().strip())
                return False
        except Exception as e:
            logger.error("Failed to execute SMS dispatch via router: %s", e)
            return False


class EmailDispatcher(BaseDispatcher):
    """
    Dispatches email notifications via Teltonika router SMTP relay or direct SMTP.
    Also supports fallback to Teltonika router sendmail command via SSH.
    """

    def __init__(
        self,
        recipient_email: str | None,
        smtp_host: str = "192.168.1.1",
        smtp_port: int = 25,
        sender_email: str = "paeraki@paeraki.local",
        router_ip: str = "192.168.1.1",
        router_user: str = "root",
        dry_run: bool = False,
    ):
        self.recipient_email = recipient_email
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.sender_email = sender_email
        self.router_ip = router_ip
        self.router_user = router_user
        self.dry_run = dry_run

    async def dispatch(self, event: AlarmEvent, consolidated_status: dict[str, Any]) -> bool:
        # Only send email for active ALARM states (not for informational clears unless critical)
        if event.state == "OK" and event.severity != AlarmSeverity.CRITICAL.value:
            return True

        if not self.recipient_email:
            logger.debug("No recipient email configured; skipping email dispatch.")
            return False

        subject = f"[{event.severity.upper()}] Paeraki Vessel Alarm: {event.rule_name}"
        body = (
            f"Paeraki Telemetry Alarm Notification\n"
            f"------------------------------------\n"
            f"Rule: {event.rule_name}\n"
            f"Status: {event.state}\n"
            f"Severity: {event.severity}\n"
            f"Timestamp: {event.timestamp}\n\n"
            f"Message:\n{event.message}\n\n"
            f"Active Alarms Count: {consolidated_status.get('active_count', 1)}\n"
        )
        if event.metrics:
            body += f"\nMetrics:\n{json.dumps(event.metrics, indent=2)}\n"

        if self.dry_run:
            logger.info(
                "[DRY-RUN EMAIL] Would send to %s via %s:%d: '%s'",
                self.recipient_email,
                self.smtp_host,
                self.smtp_port,
                subject,
            )
            return True

        # First attempt: Try standard SMTP relay to router or configured SMTP server
        try:
            loop = asyncio.get_running_loop()
            sent = await loop.run_in_executor(None, self._send_smtp_sync, subject, body)
            if sent:
                logger.info(
                    "Email dispatched successfully via SMTP relay (%s:%d) to %s",
                    self.smtp_host,
                    self.smtp_port,
                    self.recipient_email,
                )
                return True
        except Exception as e:
            logger.debug(
                "SMTP relay to %s:%d failed (%s); trying router SSH sendmail fallback...",
                self.smtp_host,
                self.smtp_port,
                e,
            )

        # Second attempt: Teltonika router sendmail via SSH
        return await self._send_router_sendmail(subject, body)

    def _send_smtp_sync(self, subject: str, body: str) -> bool:
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.sender_email
        msg["To"] = self.recipient_email
        msg.set_content(body)

        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=8.0) as server:
            server.send_message(msg)
        return True

    async def _send_router_sendmail(self, subject: str, body: str) -> bool:
        safe_to = shlex.quote(self.recipient_email)
        mail_text = f"Subject: {subject}\\nFrom: {self.sender_email}\\nTo: {self.recipient_email}\\n\\n{body}"
        safe_mail_text = shlex.quote(mail_text)
        cmd = (
            f"ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=5 "
            f"{self.router_user}@{self.router_ip} "
            f"'echo -e {safe_mail_text} | sendmail {safe_to}'"
        )
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                logger.error("Timeout connecting to router for email dispatch")
                return False

            if proc.returncode == 0:
                logger.info("Email dispatched successfully via router SSH sendmail to %s", self.recipient_email)
                return True
            else:
                logger.warning("Router sendmail failed (code %d): %s", proc.returncode, stderr.decode().strip())
                return False
        except Exception as e:
            logger.error("Failed to execute email dispatch via router: %s", e)
            return False

