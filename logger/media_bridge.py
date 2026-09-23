#!/usr/bin/env python3
"""
Paeraki Vessel Media Bridge Daemon (runs on sing).
Bridges MPD (Music Player Daemon) and moOde OS state with Paeraki's MQTT bus:
- Publishes 'paeraki/media/state' (retained) with current track metadata and playback status.
- Subscribes to 'paeraki/media/command' to execute playback control (play, pause, next, prev, outputs).
- Monitors /var/local/www/currentsong.txt for active external renderers (Spotify Connect / AirPlay).
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import signal
import sys
from typing import Any

try:
    import aiomqtt
except ImportError:
    aiomqtt = None

try:
    import mpd
except ImportError:
    mpd = None

logger = logging.getLogger("paeraki.media_bridge")

CURRENTSONG_TXT = Path("/var/local/www/currentsong.txt")


def parse_moode_currentsong(path: Path = CURRENTSONG_TXT) -> dict[str, str]:
    """Reads and parses moOde's /var/local/www/currentsong.txt key=value file."""
    meta: dict[str, str] = {}
    if not path.is_file():
        return meta
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        for line in content.splitlines():
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                meta[k.strip().lower()] = v.strip()
    except Exception as exc:
        logger.debug("Error reading %s: %s", path, exc)
    return meta


class MediaBridge:
    def __init__(
        self,
        broker_host: str = "192.168.1.1",
        broker_port: int = 1883,
        mpd_host: str = "localhost",
        mpd_port: int = 6600,
        publish_topic: str = "paeraki/media/state",
        command_topic: str = "paeraki/media/command",
        poll_interval: float = 1.0,
    ):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.mpd_host = mpd_host
        self.mpd_port = mpd_port
        self.publish_topic = publish_topic
        self.command_topic = command_topic
        self.poll_interval = poll_interval

        self.mpd_client: Any = None
        self.mqtt_client: Any = None
        self._lock = asyncio.Lock()
        self._last_state: dict[str, Any] = {}
        self._last_published_time: float = 0.0
        self.running = True

    def get_mpd_client(self) -> Any:
        """Returns a connected MPD client instance, reconnecting if needed."""
        if self.mpd_client:
            try:
                self.mpd_client.ping()
                return self.mpd_client
            except Exception:
                try:
                    self.mpd_client.disconnect()
                except Exception:
                    pass
                self.mpd_client = None

        if not mpd:
            logger.error("python-mpd2 is not installed!")
            return None

        try:
            client = mpd.MPDClient()
            client.timeout = 3.0
            client.idletimeout = None
            client.connect(self.mpd_host, self.mpd_port)
            self.mpd_client = client
            logger.info("Connected to MPD at %s:%d", self.mpd_host, self.mpd_port)
            return client
        except Exception as exc:
            logger.debug("Failed connecting to MPD at %s:%d: %s", self.mpd_host, self.mpd_port, exc)
            self.mpd_client = None
            return None

    def read_playback_state(self) -> dict[str, Any]:
        """Queries MPD and moOde status to construct a consolidated media state dict."""
        state = {
            "state": "stop",
            "source": "mpd",
            "title": "",
            "artist": "",
            "album": "",
            "elapsed": 0.0,
            "duration": 0.0,
            "volume": 0,
            "outputs": {
                "inside": False,
                "outside": False,
                "both": False,
            },
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        # 1. Check moOde currentsong.txt (for Spotify Connect / AirPlay renderers)
        moode_meta = parse_moode_currentsong()
        moode_state = moode_meta.get("state", "").lower()
        moode_file = moode_meta.get("file", "").lower()

        is_renderer = any(r in moode_file for r in ("spotify", "airplay", "shairport", "renderer", "bluez"))
        if is_renderer and moode_state in ("play", "pause"):
            state["source"] = "spotify" if "spotify" in moode_file else ("airplay" if "airplay" in moode_file or "shairport" in moode_file else "renderer")
            state["state"] = moode_state
            state["title"] = moode_meta.get("title", "")
            state["artist"] = moode_meta.get("artist", "")
            state["album"] = moode_meta.get("album", "")
            try:
                state["elapsed"] = float(moode_meta.get("elapsed", 0.0))
            except ValueError:
                state["elapsed"] = 0.0
            try:
                state["duration"] = float(moode_meta.get("duration", 0.0))
            except ValueError:
                state["duration"] = 0.0

        # 2. Query MPD directly
        client = self.get_mpd_client()
        if client:
            try:
                mpd_status = client.status()
                mpd_state = mpd_status.get("state", "stop")

                # If moOde was not actively reporting an external renderer, use MPD state
                if not is_renderer or mpd_state in ("play", "pause"):
                    state["state"] = mpd_state
                    state["source"] = "mpd"

                    # Parse elapsed / duration
                    if "elapsed" in mpd_status:
                        try:
                            state["elapsed"] = round(float(mpd_status["elapsed"]), 1)
                        except ValueError:
                            pass
                    if "duration" in mpd_status:
                        try:
                            state["duration"] = round(float(mpd_status["duration"]), 1)
                        except ValueError:
                            pass

                    # Parse track details
                    current_song = client.currentsong()
                    if current_song:
                        song_file = current_song.get("file", "")
                        is_radio_stream = ("http://" in song_file.lower() or "https://" in song_file.lower())

                        raw_title = current_song.get("title")
                        raw_name = current_song.get("name")
                        raw_artist = current_song.get("artist") or current_song.get("albumartist") or ""

                        if is_radio_stream:
                            state["source"] = "radio"
                            station_name = raw_name or Path(song_file).stem
                            elapsed = state.get("elapsed", 0.0)

                            # If elapsed > 0 and live song title is distinct from station name, show song & station
                            if raw_title and raw_name and raw_title != raw_name and elapsed > 0:
                                state["title"] = raw_title
                                state["artist"] = station_name
                            elif raw_title and not raw_name and elapsed > 0:
                                state["title"] = raw_title
                                state["artist"] = "Live Radio"
                            else:
                                # Station connecting, buffering, or station without per-track ICY metadata
                                state["title"] = station_name
                                state["artist"] = "Live Radio"
                            state["album"] = ""
                        else:
                            state["title"] = raw_title or raw_name or Path(song_file).stem
                            state["artist"] = raw_artist
                            state["album"] = current_song.get("album") or ""

                if "volume" in mpd_status and mpd_status["volume"] != "-1":
                    try:
                        state["volume"] = int(mpd_status["volume"])
                    except ValueError:
                        pass

                # Parse output device states
                for out in client.outputs():
                    out_name = out.get("outputname", "").lower()
                    enabled = (out.get("outputenabled") == "1")
                    if "inside" in out_name:
                        state["outputs"]["inside"] = enabled
                    elif "outside" in out_name:
                        state["outputs"]["outside"] = enabled
                    elif "whole boat" in out_name or "both" in out_name:
                        state["outputs"]["both"] = enabled

            except Exception as exc:
                logger.debug("Error querying MPD status: %s", exc)

        return state

    def handle_command(self, cmd_data: dict[str, Any]) -> None:
        """Executes transport or output commands on MPD."""
        client = self.get_mpd_client()
        if not client:
            logger.warning("Cannot execute command: MPD client not connected")
            return

        command = str(cmd_data.get("command", "")).lower()
        logger.info("Executing media command: %s", command)

        try:
            song = client.currentsong() or {}
            song_file = song.get("file", "").lower()
            is_stream = ("http://" in song_file or "https://" in song_file)

            if command == "play":
                client.play()
            elif command == "pause":
                if is_stream:
                    client.stop()
                else:
                    client.pause(1)
            elif command in ("play_pause", "toggle"):
                status = client.status()
                if status.get("state") == "play":
                    if is_stream:
                        client.stop()
                    else:
                        client.pause(1)
                else:
                    client.play()
            elif command == "stop":
                client.stop()
            elif command in ("next", "skip"):
                client.next()
            elif command in ("prev", "previous"):
                client.previous()
            elif command in ("toggle_output", "set_output"):
                zone = str(cmd_data.get("zone", "")).lower()
                target_enabled = cmd_data.get("enabled")
                outputs = client.outputs()
                for out in outputs:
                    out_name = out.get("outputname", "").lower()
                    out_id = out.get("outputid")
                    matches = False
                    if zone == "inside" and "inside" in out_name:
                        matches = True
                    elif zone == "outside" and "outside" in out_name:
                        matches = True
                    elif zone in ("both", "whole boat") and ("whole boat" in out_name or "both" in out_name):
                        matches = True

                    if matches and out_id is not None:
                        is_enabled = (out.get("outputenabled") == "1")
                        new_state = (not is_enabled) if target_enabled is None else bool(target_enabled)
                        if new_state:
                            client.enableoutput(int(out_id))
                            logger.info("Enabled MPD output %s (%s)", out_id, out_name)
                        else:
                            client.disableoutput(int(out_id))
                            logger.info("Disabled MPD output %s (%s)", out_id, out_name)
            elif command in ("restart_audio", "restart", "heal_audio"):
                logger.info("Received '%s' command; executing restart_audio_system", command)
                try:
                    import sys
                    from pathlib import Path
                    sys.path.insert(0, str(Path(__file__).parent.parent / "dashboard"))
                    from audio import restart_audio_system
                    restart_audio_system(restore_playback=True)
                except Exception as exc:
                    logger.warning("restart_audio_system failed: %s", exc)
                try:
                    if self.mpd_client:
                        self.mpd_client.disconnect()
                except Exception:
                    pass
                self.mpd_client = None
            else:
                logger.warning("Unrecognized media command: %s", command)
        except Exception as exc:
            logger.error("Error executing media command '%s': %s", command, exc)
            try:
                if self.mpd_client:
                    self.mpd_client.disconnect()
            except Exception:
                pass
            self.mpd_client = None

    async def run(self):
        """Main async loop subscribing to commands and publishing state."""
        if not aiomqtt:
            logger.critical("aiomqtt is not installed!")
            sys.exit(1)

        while self.running:
            try:
                logger.info("Connecting to MQTT broker at %s:%d...", self.broker_host, self.broker_port)
                async with aiomqtt.Client(hostname=self.broker_host, port=self.broker_port) as client:
                    self.mqtt_client = client
                    logger.info("Connected to MQTT broker. Subscribing to %s...", self.command_topic)
                    await client.subscribe(self.command_topic)

                    # Initial publication immediately on connect
                    current = self.read_playback_state()
                    self._last_state = current
                    await client.publish(
                        self.publish_topic,
                        payload=json.dumps(current),
                        retain=True,
                    )
                    self._last_published_time = asyncio.get_running_loop().time()

                    # Start consumer task for commands
                    command_task = asyncio.create_task(self._command_consumer(client))
                    poll_task = asyncio.create_task(self._poll_loop(client))

                    done, pending = await asyncio.wait(
                        [command_task, poll_task],
                        return_when=asyncio.FIRST_EXCEPTION,
                    )
                    for task in pending:
                        task.cancel()
                    for task in done:
                        if task.exception():
                            raise task.exception()

            except (aiomqtt.MqttError, OSError) as exc:
                logger.warning("MQTT connection error: %s. Reconnecting in 3s...", exc)
                await asyncio.sleep(3.0)
            except Exception as exc:
                logger.error("Unexpected error in media bridge: %s. Retrying in 5s...", exc, exc_info=True)
                await asyncio.sleep(5.0)

    async def _command_consumer(self, client: aiomqtt.Client):
        async for message in client.messages:
            if message.topic.matches(self.command_topic):
                try:
                    payload_str = message.payload.decode("utf-8")
                    data = json.loads(payload_str)
                    if isinstance(data, dict):
                        async with self._lock:
                            self.handle_command(data)
                            cmd = str(data.get("command", "")).lower()
                            if cmd in ("next", "prev", "previous", "skip"):
                                await asyncio.sleep(0.25)
                            else:
                                await asyncio.sleep(0.05)
                            new_state = self.read_playback_state()
                            self._last_state = new_state

                        await client.publish(
                            self.publish_topic,
                            payload=json.dumps(new_state),
                            retain=True,
                        )
                        self._last_published_time = asyncio.get_running_loop().time()
                except Exception as exc:
                    logger.error("Failed processing command payload: %s", exc)

    async def _poll_loop(self, client: aiomqtt.Client):
        while self.running:
            try:
                await asyncio.sleep(self.poll_interval)
                async with self._lock:
                    current = self.read_playback_state()
                now = asyncio.get_running_loop().time()

                # Check if meaningful state changed
                state_changed = (
                    current.get("state") != self._last_state.get("state")
                    or current.get("title") != self._last_state.get("title")
                    or current.get("artist") != self._last_state.get("artist")
                    or current.get("outputs") != self._last_state.get("outputs")
                    or current.get("source") != self._last_state.get("source")
                )

                # Heartbeat every 5s during playback to keep elapsed position synchronized
                heartbeat_due = (
                    current.get("state") == "play"
                    and (now - self._last_published_time) >= 5.0
                )

                if state_changed or heartbeat_due:
                    self._last_state = current
                    self._last_published_time = now
                    try:
                        await client.publish(
                            self.publish_topic,
                            payload=json.dumps(current),
                            retain=True,
                        )
                    except Exception as exc:
                        logger.warning("Failed publishing media state: %s", exc)
            except Exception as exc:
                logger.debug("Transient error in media poll loop: %s", exc)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Paeraki Vessel Media Bridge")
    parser.add_argument("--broker", default="192.168.1.1", help="MQTT Broker host (default: 192.168.1.1)")
    parser.add_argument("--port", type=int, default=1883, help="MQTT Broker port (default: 1883)")
    parser.add_argument("--mpd-host", default="localhost", help="MPD host (default: localhost)")
    parser.add_argument("--mpd-port", type=int, default=6600, help="MPD port (default: 6600)")
    parser.add_argument("--poll", type=float, default=1.0, help="Status polling interval in seconds")
    args = parser.parse_args()

    bridge = MediaBridge(
        broker_host=args.broker,
        broker_port=args.port,
        mpd_host=args.mpd_host,
        mpd_port=args.mpd_port,
        poll_interval=args.poll,
    )

    def _stop(*_):
        bridge.running = False
        sys.exit(0)

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _stop)

    asyncio.run(bridge.run())


if __name__ == "__main__":
    main()
