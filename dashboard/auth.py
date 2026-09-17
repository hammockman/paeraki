#!/usr/bin/env python3
"""
Device Authorization Module for Paeraki Dashboard.

Provides role-based access control for vessel operations (alarms, MoB, calibrations).
- Unauthenticated devices have read-only access to live telemetry and charts.
- Authorized devices (CONTROLLER role) can execute commands and silence alarms.
- Authorization can be granted via Skipper PIN or pairing approval from an authorized console.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger("paeraki.dashboard.auth")

DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"
DEFAULT_AUTH_FILE = DEFAULT_DATA_DIR / "authorized_devices.json"
DEFAULT_SALT = "paeraki_salt_2026"
DEFAULT_PIN = os.getenv("PAERAKI_SKIPPER_PIN", "1234")

security_bearer = HTTPBearer(auto_error=False)


def hash_pin(pin: str, salt: str = DEFAULT_SALT) -> str:
    """Computes SHA-256 hash of the PIN with salt."""
    return hashlib.sha256(f"{salt}:{pin}".encode("utf-8")).hexdigest()


class DeviceAuthManager:
    """Manages persistent device tokens and authorization states."""

    def __init__(self, auth_file: Path | str = DEFAULT_AUTH_FILE, default_pin: str = DEFAULT_PIN):
        self.auth_file = Path(auth_file)
        self.default_pin = str(default_pin)
        self._data: dict[str, Any] = {
            "pin_hash": hash_pin(self.default_pin),
            "devices": {},          # uuid -> {name, token, role, created_at, last_seen, ip}
            "tokens": {},           # token -> uuid
            "pending_requests": {}, # uuid -> {name, ip, requested_at}
        }
        self.load()

    def load(self) -> None:
        """Loads authorized devices from storage or initializes with defaults."""
        if not self.auth_file.exists():
            self.save()
            return

        try:
            with open(self.auth_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
                self._data["pin_hash"] = saved.get("pin_hash", hash_pin(self.default_pin))
                self._data["devices"] = saved.get("devices", {})
                self._data["pending_requests"] = saved.get("pending_requests", {})
                # Rebuild token lookup index
                self._data["tokens"] = {
                    dev["token"]: uuid
                    for uuid, dev in self._data["devices"].items()
                    if "token" in dev
                }
        except Exception as e:
            logger.error("Failed to read %s: %s. Using in-memory fallback.", self.auth_file, e)

    def save(self) -> None:
        """Persists authorization state to file safely."""
        try:
            self.auth_file.parent.mkdir(parents=True, exist_ok=True)
            export_data = {
                "pin_hash": self._data["pin_hash"],
                "devices": self._data["devices"],
                "pending_requests": self._data["pending_requests"],
            }
            temp_file = self.auth_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2)
            temp_file.replace(self.auth_file)
        except Exception as e:
            logger.error("Failed to write %s: %s", self.auth_file, e)

    def verify_pin(self, pin: str) -> bool:
        """Verifies provided PIN against stored hash."""
        expected = self._data.get("pin_hash", hash_pin(self.default_pin))
        provided = hash_pin(str(pin).strip())
        return hmac.compare_digest(expected, provided)

    def set_pin(self, old_pin: str, new_pin: str) -> bool:
        """Updates skipper PIN if old PIN is valid."""
        if not self.verify_pin(old_pin):
            return False
        self._data["pin_hash"] = hash_pin(str(new_pin).strip())
        self.save()
        logger.info("Skipper PIN updated successfully.")
        return True

    def authorize_with_pin(
        self, uuid: str, pin: str, name: str = "", ip: str = ""
    ) -> tuple[bool, str, str | None]:
        """Validates PIN and elevates device to CONTROLLER role with a bearer token."""
        if not self.verify_pin(pin):
            return False, "Invalid Skipper PIN", None

        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc).isoformat()
        device_name = name.strip() or f"Device-{uuid[:6]}"

        self._data["devices"][uuid] = {
            "uuid": uuid,
            "name": device_name,
            "role": "CONTROLLER",
            "token": token,
            "created_at": now,
            "last_seen": now,
            "ip": ip,
        }
        self._data["tokens"][token] = uuid
        # Clear from pending if it was waiting
        self._data["pending_requests"].pop(uuid, None)
        self.save()
        logger.info("Device '%s' (%s) authorized as CONTROLLER via PIN", device_name, uuid)
        return True, "Authorization granted", token

    def request_pairing(self, uuid: str, name: str = "", ip: str = "") -> dict[str, Any]:
        """Registers a device pairing request for approval by helm display."""
        now = datetime.now(timezone.utc).isoformat()
        req = {
            "uuid": uuid,
            "name": name.strip() or f"Device-{uuid[:6]}",
            "ip": ip,
            "requested_at": now,
        }
        self._data["pending_requests"][uuid] = req
        self.save()
        logger.info("Pairing request registered for device '%s' (%s)", req["name"], uuid)
        return req

    def approve_pairing(self, uuid: str) -> tuple[bool, str, str | None]:
        """Approves a pending pairing request and returns a token."""
        req = self._data["pending_requests"].pop(uuid, None)
        if not req:
            return False, "No pending pairing request found for device", None

        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc).isoformat()
        self._data["devices"][uuid] = {
            "uuid": uuid,
            "name": req["name"],
            "role": "CONTROLLER",
            "token": token,
            "created_at": now,
            "last_seen": now,
            "ip": req.get("ip", ""),
        }
        self._data["tokens"][token] = uuid
        self.save()
        logger.info("Pairing approved for device '%s' (%s)", req["name"], uuid)
        return True, "Pairing approved", token

    def validate_token(self, token: str, ip: str = "") -> dict[str, Any] | None:
        """Validates token and updates last_seen timestamp."""
        uuid = self._data["tokens"].get(token)
        if not uuid:
            return None

        dev = self._data["devices"].get(uuid)
        if not dev:
            return None

        # Update last seen
        dev["last_seen"] = datetime.now(timezone.utc).isoformat()
        if ip:
            dev["ip"] = ip
        return dev

    def revoke_device(self, uuid: str) -> bool:
        """Revokes authorization for a device."""
        dev = self._data["devices"].pop(uuid, None)
        if dev and "token" in dev:
            self._data["tokens"].pop(dev["token"], None)
            self.save()
            logger.info("Revoked authorization for device '%s' (%s)", dev.get("name"), uuid)
            return True
        return False

    def list_devices(self) -> list[dict[str, Any]]:
        """Returns list of authorized devices (excluding secret tokens)."""
        return [
            {k: v for k, v in dev.items() if k != "token"}
            for dev in self._data["devices"].values()
        ]

    def list_pending(self) -> list[dict[str, Any]]:
        """Returns list of pending pairing requests."""
        return list(self._data["pending_requests"].values())


# Global singleton instance
auth_manager = DeviceAuthManager()


async def get_current_device_auth(
    request: Request,
) -> dict[str, Any] | None:
    """
    Extracts and validates device authentication from Bearer token,
    custom header, or cookie. Returns None if unauthenticated.
    """
    token: str | None = None

    auth_header = request.headers.get("authorization", "")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    elif "x-device-token" in request.headers:
        token = request.headers["x-device-token"]
    elif "paeraki_token" in request.cookies:
        token = request.cookies["paeraki_token"]

    if not token:
        return None

    client_ip = request.client.host if request.client else ""
    return auth_manager.validate_token(token, ip=client_ip)



async def require_control_auth(
    auth_ctx: dict[str, Any] | None = Depends(get_current_device_auth),
) -> dict[str, Any]:
    """
    FastAPI dependency that enforces CONTROLLER role for protected endpoints.
    Raises 403 Forbidden if unauthenticated.
    """
    if not auth_ctx or auth_ctx.get("role") != "CONTROLLER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device not authorized for vessel control. Please enter the Skipper PIN.",
        )
    return auth_ctx
