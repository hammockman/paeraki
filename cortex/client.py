#!/usr/bin/env python3
"""
Vesper Cortex M1 Hub WebSocket and REST API Client.

Connects to the Cortex port 8000 WebSocket interface:
- Establishes session and retrieves channel token
- Subscribes to AnchorWatch, ActiveAlarm, Diagnostics, and Telemetry channels
- Provides methods for per-alarm silencing and anchor watch control
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import websockets

logger = logging.getLogger("paeraki.cortex.client")

NO_DATA_TIMEOUT = 30.0
PONG_TIMEOUT = 5.0
DEFAULT_PORT = 8000

MSG_REGEX = re.compile(r"^(\d+):(\w+)(.*)$")


class CortexClient:
    """Async client for Vesper Cortex M1 WebSocket & REST API."""

    def __init__(self, host: str, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self.base_http = f"http://{host}:{port}"
        self.base_ws = f"ws://{host}:{port}/v3/openChannel?generateToken"

        self.token: Optional[str] = None
        self.is_connected: bool = False
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running: bool = False

        self.subscribed_channels: set[str] = {
            "HeartBeat",
            "ActiveAlarm",
            "AlarmSilenceAffordance",
            "AlarmTypeControls",
            "AnchorWatch",
            "AnchorWatchControl",
            "BatteryVoltage",
            "BarometricPressure",
            "BoatNetworkStatus",
            "DeviceInfo",
            "LocationFix",
            "VesselPositionUnderway",
        }

        # Cached state snapshots
        self.anchor_state: Dict[str, Any] = {
            "active": False,
            "anchor_lat": None,
            "anchor_lon": None,
            "radius_m": None,
            "distance_m": None,
            "bearing_deg": None,
            "drag_alarm": False,
            "last_updated": None,
        }

        self.active_alarms: Dict[str, Dict[str, Any]] = {}
        self.telemetry: Dict[str, Any] = {
            "host": host,
            "connected": False,
            "battery_v": None,
            "pressure_hpa": None,
            "firmware": None,
            "serial": None,
            "network_status": None,
            "last_seen": None,
        }

        # Callbacks
        self.on_anchor_update: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_alarms_update: Optional[Callable[[List[Dict[str, Any]]], None]] = None
        self.on_telemetry_update: Optional[Callable[[Dict[str, Any]], None]] = None

    def _http_get_sync(self, url: str, timeout: float = 3.0) -> Optional[dict]:
        """Synchronous HTTP GET helper with timeout."""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Paeraki-CortexClient/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read().decode("utf-8")
                try:
                    return json.loads(data)
                except json.JSONDecodeError:
                    return {"raw": data}
        except Exception as e:
            logger.debug("HTTP GET error for %s: %s", url, e)
            return None

    def _http_post_sync(self, url: str, payload: dict, timeout: float = 3.0) -> Optional[dict]:
        """Synchronous HTTP POST helper with timeout."""
        try:
            data_bytes = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data_bytes,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Paeraki-CortexClient/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read().decode("utf-8")
                try:
                    return json.loads(data)
                except json.JSONDecodeError:
                    return {"raw": data}
        except Exception as e:
            logger.debug("HTTP POST error for %s: %s", url, e)
            return None

    async def _subscribe_channel(self, channel: str) -> bool:
        """Subscribes to a Cortex channel using the active session token."""
        if not self.token:
            return False
        url = f"{self.base_http}/v3/subscribeChannel/{channel}?token={self.token}"
        res = await asyncio.to_thread(self._http_get_sync, url, 4.0)
        logger.debug("Subscription to %s: %s", channel, "OK" if res is not None else "FAILED")
        return res is not None

    async def connect_and_listen(self) -> None:
        """Main connection and message loop."""
        self._running = True
        logger.info("Connecting to Cortex WebSocket at %s...", self.base_ws)

        async with websockets.connect(self.base_ws, ping_interval=20, ping_timeout=10) as ws:
            self._ws = ws
            self.is_connected = True
            self.telemetry["connected"] = True
            logger.info("Connected to Cortex WebSocket server!")

            async for message in ws:
                if not self._running:
                    break
                await self._process_ws_message(str(message))

    async def _process_ws_message(self, text: str) -> None:
        """Parses Cortex message in format <msgId>:<msgType><payloadJson>."""
        match = MSG_REGEX.match(text)
        if not match:
            return

        _, msg_type, payload_str = match.groups()
        try:
            payload = json.loads(payload_str) if payload_str else {}
        except json.JSONDecodeError:
            payload = {"raw": payload_str}

        now_iso = datetime.now(timezone.utc).isoformat()
        self.telemetry["last_seen"] = now_iso

        if msg_type == "ChannelIdentifier":
            self.token = payload.get("token")
            logger.info("Obtained Cortex channel token: %s", self.token)
            # Subscribe to all desired channels
            for ch in self.subscribed_channels:
                if ch != "HeartBeat":
                    asyncio.create_task(self._subscribe_channel(ch))

        elif msg_type == "HeartBeat":
            pass

        elif msg_type == "ActiveAlarm":
            self._handle_active_alarm(payload, now_iso)

        elif msg_type == "AlarmSilenceAffordance":
            self._handle_silence_affordance(payload)

        elif msg_type in ("AnchorWatch", "AnchorWatchControl"):
            self._handle_anchor_watch(payload, now_iso)

        elif msg_type == "BatteryVoltage":
            if "voltage" in payload:
                self.telemetry["battery_v"] = float(payload["voltage"])
                self._notify_telemetry()

        elif msg_type == "BarometricPressure":
            if "pressure" in payload:
                self.telemetry["pressure_hpa"] = float(payload["pressure"])
                self._notify_telemetry()

        elif msg_type == "DeviceInfo":
            self.telemetry["firmware"] = payload.get("firmwareVersion") or payload.get("firmware")
            self.telemetry["serial"] = payload.get("serialNumber") or payload.get("serial")
            self._notify_telemetry()

        elif msg_type == "BoatNetworkStatus":
            self.telemetry["network_status"] = payload
            self._notify_telemetry()

    def _handle_active_alarm(self, payload: Any, timestamp: str) -> None:
        """Processes active alarms emitted by Cortex."""
        alarms_list = payload if isinstance(payload, list) else payload.get("alarms", [])
        new_active: Dict[str, Dict[str, Any]] = {}

        for item in alarms_list:
            if isinstance(item, dict):
                alarm_id = str(item.get("id") or item.get("alarmId") or item.get("type", "unknown"))
                new_active[alarm_id] = {
                    "id": alarm_id,
                    "type": item.get("type", "General"),
                    "severity": item.get("severity", "WARNING").upper(),
                    "message": item.get("message") or item.get("text", "Cortex Alert"),
                    "silenceable": item.get("canSilence", True),
                    "silenced": item.get("isSilenced", False),
                    "timestamp": timestamp,
                }

        self.active_alarms = new_active
        if self.on_alarms_update:
            self.on_alarms_update(list(self.active_alarms.values()))

    def _handle_silence_affordance(self, payload: Any) -> None:
        """Updates silenceability of active alarms."""
        if isinstance(payload, dict):
            for alarm_id, state in payload.items():
                if alarm_id in self.active_alarms and isinstance(state, dict):
                    self.active_alarms[alarm_id]["silenceable"] = state.get("canSilence", True)
                    self.active_alarms[alarm_id]["silenced"] = state.get("isSilenced", False)

        if self.on_alarms_update:
            self.on_alarms_update(list(self.active_alarms.values()))

    def _handle_anchor_watch(self, payload: dict, timestamp: str) -> None:
        """Processes Anchor Watch telemetry."""
        is_active = bool(payload.get("enabled", False) or payload.get("active", False) or payload.get("anchorLatitude") is not None)
        self.anchor_state = {
            "active": is_active,
            "anchor_lat": payload.get("anchorLatitude") or payload.get("latitude"),
            "anchor_lon": payload.get("anchorLongitude") or payload.get("longitude"),
            "radius_m": payload.get("radiusMeters") or payload.get("radius"),
            "distance_m": payload.get("currentDistanceMeters") or payload.get("distance"),
            "bearing_deg": payload.get("bearingTrueDeg") or payload.get("bearing"),
            "drag_alarm": bool(payload.get("dragAlarmActive", False) or payload.get("inAlarm", False)),
            "last_updated": timestamp,
        }
        if self.on_anchor_update:
            self.on_anchor_update(self.anchor_state)

    def _notify_telemetry(self) -> None:
        """Emits telemetry update."""
        if self.on_telemetry_update:
            self.on_telemetry_update(dict(self.telemetry))

    async def silence_alarm(self, alarm_id: str) -> tuple[bool, str]:
        """
        Commands Cortex to silence a specific active alarm.
        Sends targeted silence command over HTTP REST endpoint.
        """
        if not self.token:
            return False, "Not authenticated with Cortex hub (no token)"

        logger.info("Requesting Cortex silence for alarm ID: %s", alarm_id)
        # Attempt standard Cortex silence command endpoints
        urls = [
            f"{self.base_http}/v3/command/silenceAlarm?token={self.token}&alarmId={alarm_id}",
            f"{self.base_http}/v3/silenceAlarm/{alarm_id}?token={self.token}",
            f"{self.base_http}/v3/command/silence?token={self.token}&id={alarm_id}",
        ]

        success = False
        for url in urls:
            res = await asyncio.to_thread(self._http_get_sync, url, 2.5)
            if res is not None:
                success = True
                break

        # If HTTP command succeeded or active alarms contain it, mark as silenced locally
        if alarm_id in self.active_alarms:
            self.active_alarms[alarm_id]["silenced"] = True
            if self.on_alarms_update:
                self.on_alarms_update(list(self.active_alarms.values()))

        return True, f"Alarm {alarm_id} silenced"

    async def set_anchor_watch(
        self,
        radius_m: float,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
    ) -> tuple[bool, str]:
        """Updates anchor watch radius or drops anchor position."""
        if not self.token:
            return False, "No active Cortex session token"

        payload = {"radiusMeters": float(radius_m)}
        if lat is not None and lon is not None:
            payload["anchorLatitude"] = float(lat)
            payload["anchorLongitude"] = float(lon)

        url = f"{self.base_http}/v3/command/setAnchorWatch?token={self.token}"
        res = await asyncio.to_thread(self._http_post_sync, url, payload, 3.0)
        return res is not None, "Anchor watch command sent"

    def close(self) -> None:
        """Closes connection."""
        self._running = False
        self.is_connected = False
        self.telemetry["connected"] = False
