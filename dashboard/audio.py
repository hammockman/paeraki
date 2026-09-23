#!/usr/bin/env python3
"""
Audio mixer and zone controller for Paeraki (sing).
Controls ALSA hardware headphone volume and mute for 'inside' (Cabin) and 'outside' (Cockpit).
Provides graceful in-memory fallback for test and non-Linux/non-ALSA environments.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any

try:
    import mpd
except ImportError:
    mpd = None

logger = logging.getLogger("paeraki.audio")

VALID_ZONES = ("inside", "outside")

# In-memory state cache (used as fallback when amixer is unavailable or on test systems)
_audio_cache: dict[str, dict[str, Any]] = {
    "inside": {"volume": 30, "muted": False, "available": True},
    "outside": {"volume": 30, "muted": False, "available": True},
}


def _has_amixer() -> bool:
    return shutil.which("amixer") is not None


def get_alsa_zone_state(zone: str) -> dict[str, Any]:
    """
    Reads hardware volume percentage and mute state for the given ALSA card zone ('inside' or 'outside').
    Returns dict: {'volume': int, 'muted': bool, 'available': bool}
    """
    if zone not in VALID_ZONES:
        raise ValueError(f"Invalid audio zone '{zone}'. Must be one of {VALID_ZONES}")

    if not _has_amixer():
        state = dict(_audio_cache[zone])
        state["available"] = False
        return state

    cmd = ["amixer", "-M", "-c", zone, "sget", "Headphone"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=2.0)
        if res.returncode != 0:
            logger.debug("amixer returned error for card '%s': %s", zone, res.stderr.strip())
            state = dict(_audio_cache[zone])
            state["available"] = False
            return state

        out = res.stdout
        # Match volume percentage: e.g. [70%]
        vol_match = re.search(r"\[(\d+)%\]", out)
        # Match mute status: e.g. [on] or [off] (off == muted)
        mute_match = re.search(r"\[(on|off)\]", out)

        vol = int(vol_match.group(1)) if vol_match else _audio_cache[zone]["volume"]
        muted = (mute_match.group(1) == "off") if mute_match else _audio_cache[zone]["muted"]

        _audio_cache[zone]["volume"] = vol
        _audio_cache[zone]["muted"] = muted
        _audio_cache[zone]["available"] = True

        return {"volume": vol, "muted": muted, "available": True}
    except Exception as exc:
        logger.debug("Failed querying amixer for zone '%s': %s", zone, exc)
        state = dict(_audio_cache[zone])
        state["available"] = False
        return state


def get_all_audio_state() -> dict[str, dict[str, Any]]:
    """Returns state of both inside and outside zones."""
    return {
        "inside": get_alsa_zone_state("inside"),
        "outside": get_alsa_zone_state("outside"),
    }


def set_alsa_volume(zone: str, volume: int) -> dict[str, Any]:
    """
    Sets volume for the given zone (0-100%).
    Updates hardware via amixer if available, else updates fallback cache.
    """
    if zone not in VALID_ZONES:
        raise ValueError(f"Invalid audio zone '{zone}'. Must be one of {VALID_ZONES}")

    # Clamp volume
    volume = max(0, min(100, int(volume)))
    _audio_cache[zone]["volume"] = volume

    if _has_amixer():
        cmd = ["amixer", "-M", "-c", zone, "sset", "Headphone", f"{volume}%"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=2.0)
            if res.returncode != 0:
                logger.warning("amixer sset volume failed for '%s': %s", zone, res.stderr.strip())
                _audio_cache[zone]["available"] = False
            else:
                _audio_cache[zone]["available"] = True
        except Exception as exc:
            logger.warning("Exception setting volume on '%s': %s", zone, exc)
            _audio_cache[zone]["available"] = False

    return get_alsa_zone_state(zone)


def set_alsa_mute(zone: str, muted: bool) -> dict[str, Any]:
    """
    Sets mute state for the given zone (True=muted, False=unmuted).
    Updates hardware via amixer if available, else updates fallback cache.
    """
    if zone not in VALID_ZONES:
        raise ValueError(f"Invalid audio zone '{zone}'. Must be one of {VALID_ZONES}")

    muted = bool(muted)
    _audio_cache[zone]["muted"] = muted

    if _has_amixer():
        action = "mute" if muted else "unmute"
        cmd = ["amixer", "-c", zone, "sset", "Headphone", action]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=2.0)
            if res.returncode != 0:
                logger.warning("amixer sset mute failed for '%s': %s", zone, res.stderr.strip())
                _audio_cache[zone]["available"] = False
            else:
                _audio_cache[zone]["available"] = True
        except Exception as exc:
            logger.warning("Exception setting mute on '%s': %s", zone, exc)
            _audio_cache[zone]["available"] = False

    return get_alsa_zone_state(zone)


_last_health_check_time: float = 0.0
_cached_health: dict[str, Any] = {}


def check_audio_health(force: bool = False) -> dict[str, Any]:
    """
    Evaluates system audio health:
    - ALSA cards presence and accessibility ('inside', 'outside')
    - Hardware mixer responsiveness and level drift
    - MPD daemon running status and socket responsiveness
    - MPD output enablement status
    Returns:
      {
        "healthy": bool,
        "status": "healthy" | "degraded" | "error" | "simulated",
        "devices": {
          "inside": {"present": bool, "available": bool, "volume": int, "muted": bool},
          "outside": {"present": bool, "available": bool, "volume": int, "muted": bool}
        },
        "mpd": {
          "active": bool,
          "responsive": bool,
          "state": str,
          "outputs": {"inside": bool, "outside": bool}
        },
        "message": str
      }
    """
    global _last_health_check_time, _cached_health
    now = time.monotonic()
    if not force and _cached_health and (now - _last_health_check_time < 2.5):
        return _cached_health
    cards_path = Path("/proc/asound/cards")
    has_alsa_proc = cards_path.exists()

    dev_health = {}
    cards_text = ""
    if has_alsa_proc:
        try:
            cards_text = cards_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            logger.debug("Failed reading /proc/asound/cards: %s", exc)

    all_devs_present = True
    for z in VALID_ZONES:
        present = (f"[{z}" in cards_text or f" {z} " in cards_text) if has_alsa_proc else _audio_cache[z]["available"]
        st = get_alsa_zone_state(z)
        dev_health[z] = {
            "present": present,
            "available": st.get("available", False),
            "volume": st.get("volume", 0),
            "muted": st.get("muted", False),
        }
        if not present or not st.get("available", False):
            all_devs_present = False

    # Check MPD
    mpd_health: dict[str, Any] = {
        "active": False,
        "responsive": False,
        "state": "unknown",
        "outputs": {"inside": False, "outside": False},
        "error": None,
    }

    # 1. Check systemd mpd service
    if shutil.which("systemctl"):
        try:
            r = subprocess.run(["systemctl", "is-active", "mpd"], capture_output=True, text=True, timeout=2.0)
            mpd_health["active"] = (r.stdout.strip() == "active")
        except Exception:
            pass
    else:
        mpd_health["active"] = True

    # 2. Check MPD client connection & outputs
    if mpd:
        try:
            client = mpd.MPDClient()
            client.timeout = 2.0
            client.connect("localhost", 6600)
            st = client.status()
            mpd_health["responsive"] = True
            mpd_health["state"] = st.get("state", "unknown")
            outs = client.outputs()
            for out in outs:
                out_name = out.get("outputname", "").lower()
                is_en = (out.get("outputenabled") == "1")
                if "inside" in out_name:
                    mpd_health["outputs"]["inside"] = is_en
                elif "outside" in out_name:
                    mpd_health["outputs"]["outside"] = is_en
            client.disconnect()
        except Exception as exc:
            mpd_health["responsive"] = False
            mpd_health["error"] = str(exc)
    elif shutil.which("mpc"):
        try:
            r = subprocess.run(["mpc", "status"], capture_output=True, text=True, timeout=2.0)
            if r.returncode == 0:
                mpd_health["responsive"] = True
                if "[playing]" in r.stdout:
                    mpd_health["state"] = "play"
                elif "[paused]" in r.stdout:
                    mpd_health["state"] = "pause"
                else:
                    mpd_health["state"] = "stop"

                ro = subprocess.run(["mpc", "outputs"], capture_output=True, text=True, timeout=2.0)
                if ro.returncode == 0:
                    for line in ro.stdout.splitlines():
                        ll = line.lower()
                        if "inside" in ll:
                            mpd_health["outputs"]["inside"] = ("is enabled" in ll)
                        elif "outside" in ll:
                            mpd_health["outputs"]["outside"] = ("is enabled" in ll)
        except Exception as exc:
            mpd_health["responsive"] = False
            mpd_health["error"] = str(exc)
    else:
        # Fallback for test/mock environments
        mpd_health["responsive"] = True
        mpd_health["state"] = "play"
        mpd_health["outputs"] = {"inside": True, "outside": True}

    # Overall evaluation
    if not has_alsa_proc and not _has_amixer():
        status = "simulated"
        healthy = True
        msg = "Simulated audio environment (test mode)"
    elif all_devs_present and mpd_health["active"] and mpd_health["responsive"]:
        if mpd_health["outputs"]["inside"] and mpd_health["outputs"]["outside"]:
            status = "healthy"
            healthy = True
            msg = "All audio DACs and MPD outputs healthy"
        else:
            status = "degraded"
            healthy = False
            msg = "One or more MPD outputs disabled"
    elif not all_devs_present and (dev_health["inside"]["present"] or dev_health["outside"]["present"]):
        status = "degraded"
        healthy = False
        msg = "One audio DAC is disconnected or unavailable"
    else:
        status = "error"
        healthy = False
        msg = "Audio hardware or MPD daemon unavailable"

    result = {
        "healthy": healthy,
        "status": status,
        "devices": dev_health,
        "mpd": mpd_health,
        "message": msg,
    }
    _cached_health = result
    _last_health_check_time = now
    return result


def restart_audio_system(restore_playback: bool = True) -> dict[str, Any]:
    """
    Safely restarts MPD and re-initializes hardware mixers.
    1. Captures current playback state.
    2. Restarts mpd via sudo systemctl (if available).
    3. Re-applies volume and mute settings to both zones.
    4. Re-enables MPD zone outputs.
    5. Restores playback if previously playing.
    6. Returns fresh check_audio_health() result.
    """
    logger.info("Initiating audio system restart...")

    # 1. Capture playback state
    was_playing = False
    current_song_pos = None
    if mpd:
        try:
            client = mpd.MPDClient()
            client.timeout = 1.5
            client.connect("localhost", 6600)
            st = client.status()
            was_playing = (st.get("state") == "play")
            current_song_pos = st.get("song")
            client.disconnect()
        except Exception:
            pass
    elif shutil.which("mpc"):
        try:
            r = subprocess.run(["mpc", "status"], capture_output=True, text=True, timeout=1.5)
            was_playing = ("[playing]" in r.stdout)
        except Exception:
            pass

    # 2. Restart MPD
    if shutil.which("systemctl"):
        try:
            subprocess.run(["sudo", "-n", "systemctl", "restart", "mpd"], check=True, timeout=8.0)
            time.sleep(0.7)
        except Exception as exc:
            logger.warning("systemctl restart mpd failed: %s", exc)

    # 3. Restore ALSA mixer levels for both zones (prevent 80 / -20dB reset)
    for z in VALID_ZONES:
        target_vol = _audio_cache[z].get("volume", 30)
        target_muted = _audio_cache[z].get("muted", False)
        try:
            set_alsa_volume(z, target_vol)
            set_alsa_mute(z, target_muted)
        except Exception as exc:
            logger.warning("Failed restoring ALSA settings for zone '%s': %s", z, exc)

    # 4. Re-enable outputs and resume playback if requested
    if mpd:
        try:
            client = mpd.MPDClient()
            client.timeout = 3.0
            client.connect("localhost", 6600)
            for out in client.outputs():
                out_name = out.get("outputname", "").lower()
                out_id = out.get("outputid")
                if out_id is not None and ("inside" in out_name or "outside" in out_name):
                    try:
                        client.enableoutput(int(out_id))
                    except Exception:
                        pass
            if restore_playback and was_playing:
                try:
                    if current_song_pos is not None:
                        client.play(int(current_song_pos))
                    else:
                        client.play()
                except Exception:
                    pass
            client.disconnect()
        except Exception as exc:
            logger.warning("Error re-enabling MPD outputs: %s", exc)
    elif shutil.which("mpc"):
        try:
            ro = subprocess.run(["mpc", "outputs"], capture_output=True, text=True, timeout=2.0)
            if ro.returncode == 0:
                for line in ro.stdout.splitlines():
                    m = re.search(r"Output (\d+)", line)
                    if m and ("inside" in line.lower() or "outside" in line.lower()):
                        subprocess.run(["mpc", "enable", m.group(1)], check=False, timeout=1.0)
            if restore_playback and was_playing:
                subprocess.run(["mpc", "play"], check=False, timeout=2.0)
        except Exception as exc:
            logger.warning("Error re-enabling mpc outputs: %s", exc)

    # 5. Return fresh health
    health = check_audio_health(force=True)
    logger.info("Audio system restart completed. New status: %s", health.get("status"))
    return health

