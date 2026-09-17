"""
Vesper Cortex M1 Hub Integration for Paeraki.
Provides network discovery, WebSocket/HTTP telemetry ingestion,
anchor watch tracking, alarm monitoring, per-alarm silencing, and MoB triggering.
"""

from .discovery import discover_cortex_host
from .client import CortexClient

__all__ = ["discover_cortex_host", "CortexClient"]
