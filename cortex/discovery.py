#!/usr/bin/env python3
"""
Network Discovery for Vesper Cortex M1 Hub.

Attempts resolution of 'cortex.local' via mDNS (system resolver),
with fallback to configured or default static IP (192.168.1.50).
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from typing import Optional

logger = logging.getLogger("paeraki.cortex.discovery")

DEFAULT_CORTEX_MDNS = "cortex.local"
DEFAULT_CORTEX_STATIC_IP = "192.168.1.50"
CORTEX_PORT = 8000


def probe_tcp_port(host: str, port: int = CORTEX_PORT, timeout: float = 1.5) -> bool:
    """Checks if Cortex port 8000 is reachable at the given host."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, OSError):
        return False


async def probe_tcp_port_async(host: str, port: int = CORTEX_PORT, timeout: float = 1.5) -> bool:
    """Async wrapper for TCP connection probe."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (asyncio.TimeoutError, OSError):
        return False


def resolve_mdns_host(hostname: str = DEFAULT_CORTEX_MDNS) -> Optional[str]:
    """Resolves mDNS hostname using the local resolver."""
    try:
        ip = socket.gethostbyname(hostname)
        logger.debug("Resolved %s to %s", hostname, ip)
        return ip
    except socket.gaierror:
        return None


async def discover_cortex_host(
    preferred_host: Optional[str] = None,
    port: int = CORTEX_PORT,
    timeout: float = 2.0,
) -> str:
    """
    Discovers the active IP or hostname of the Vesper Cortex M1 hub.

    Resolution order:
    1. Explicit environment variable PAERAKI_CORTEX_HOST or preferred_host argument.
    2. mDNS hostname 'cortex.local'.
    3. Default static reservation '192.168.1.50'.
    """
    env_host = os.getenv("PAERAKI_CORTEX_HOST", "").strip()
    candidates = []

    if preferred_host:
        candidates.append(preferred_host)
    if env_host and env_host not in candidates:
        candidates.append(env_host)

    candidates.append(DEFAULT_CORTEX_MDNS)
    candidates.append(DEFAULT_CORTEX_STATIC_IP)

    for host in candidates:
        # If hostname is mDNS, attempt resolution
        target_ip = host
        if host.endswith(".local"):
            resolved = resolve_mdns_host(host)
            if resolved:
                target_ip = resolved
            else:
                logger.debug("mDNS resolution for %s failed; skipping probe", host)
                continue

        logger.debug("Probing Cortex at %s:%d...", target_ip, port)
        is_reachable = await probe_tcp_port_async(target_ip, port=port, timeout=timeout)
        if is_reachable:
            logger.info("Discovered active Cortex M1 Hub at %s:%d", target_ip, port)
            return target_ip

    # If probe fails on all candidates, fallback to first configured or static candidate
    fallback = env_host or preferred_host or DEFAULT_CORTEX_STATIC_IP
    logger.warning("Could not actively reach Cortex on port %d. Falling back to %s", port, fallback)
    return fallback
