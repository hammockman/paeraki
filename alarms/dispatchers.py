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

        # Run SSH gsmctl asynchronously
        safe_body = shlex.quote(sms_body)
        cmd = f"ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=5 {self.router_user}@{self.router_ip} 'gsmctl -S -s \"{self.phone_number}\" {safe_body}'"

        logger.info("Sending SMS via Teltonika router to %s...", self.phone_number)
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            if proc.returncode == 0:
                logger.info("SMS dispatched successfully via router: %s", stdout.decode().strip())
                return True
            else:
                logger.warning("Router gsmctl failed (code %d): %s", proc.returncode, stderr.decode().strip())
                return False
        except asyncio.TimeoutError:
            logger.error("Timeout connecting to router for SMS dispatch")
            return False
        except Exception as e:
            logger.error("Failed to execute SMS dispatch via router: %s", e)
            return False
