#!/usr/bin/env python3
"""
Paeraki Yacht Telemetry Monitor Server (runs on hammer).
Subscribes to all MQTT messages from Paeraki broker (192.168.1.1),
maintains state, and streams live telemetry to web dashboards via WebSockets.
"""

import argparse
import asyncio
import json
import logging
import random
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import socket
import sys
from typing import Any

# Ensure dashboard directory is in path
sys.path.insert(0, str(Path(__file__).parent))
from battery import BatteryIntegrator, calculate_voltage_soc
from battery_12v import HouseBatteryIntegrator, calculate_agm_voltage_soc

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

try:
    import aiomqtt
except ImportError:
    aiomqtt = None

logger = logging.getLogger("paeraki.monitor")
STATIC_DIR = Path(__file__).parent / "static"
DATA_DIR = Path(__file__).parent.parent / "data"
DIST_DIR = Path(__file__).parent.parent / "dist"


class DashboardState:
    def __init__(self):
        self.broker_host = "192.168.1.1"
        self.broker_port = 1883
        self.is_connected = False
        self.last_packet_time: str | None = None
        self.total_packets_received = 0
        self.messages_per_second = 0.0
        self._packet_timestamps = deque(maxlen=60)

        # High-level subsystem states
        self.battery = BatteryIntegrator(
            nominal_capacity_ah=200.0,
            state_file=DATA_DIR / "dashboard_soc_state.json",
            seed_ah=134.90,
        )

        self.battery_12v = HouseBatteryIntegrator(
            nominal_capacity_ah=100.0,
            state_file=DATA_DIR / "dashboard_12v_soc_state.json",
        )

        self.system_72v: dict[str, Any] = {
            "total_voltage": 0.0,
            "current": 0.0,
            "power": 0.0,
            "rsoc": 0,
            "residual_capacity_ah": 0.0,
            "nominal_capacity_ah": 200.0,
            "soc_integrated": round((self.battery.integrated_ah / max(1.0, self.battery.nominal_capacity_ah)) * 100.0, 1),
            "integrated_ah": round(self.battery.integrated_ah, 2),
            "soc_voltage": 0.0,
            "soc_bms": 0,
            "vcell_avg": 0.0,
            "soc_discrepancy": False,
            "cycle_times": 0,
            "charge_status": False,
            "discharge_status": False,
            "temperatures": [],
            "cell_voltages": [],
            "number_of_cells": 20,
            "active_protection_states": [],
            "last_updated": None,
        }

        self.system_12v: dict[str, Any] = {
            "battery_voltage": 0.0,
            "solar_power": 0.0,
            "solar_voltage": 0.0,
            "solar_current": 0.0,
            "battery_charge_current": 0.0,
            "load_voltage": 0.0,
            "load_current": 0.0,
            "load_power": 0.0,
            "charging_status": "Idle",
            "battery_soc": 0,
            "soc_12v_integrated": round(((self.battery_12v.integrated_ah or 0.0) / max(1.0, self.battery_12v.nominal_capacity_ah)) * 100.0, 1),
            "soc_12v_voltage": 0.0,
            "soc_12v_active": round(((self.battery_12v.integrated_ah or 0.0) / max(1.0, self.battery_12v.nominal_capacity_ah)) * 100.0, 1),
            "integrated_12v_ah": round(self.battery_12v.integrated_ah or 0.0, 2),
            "nominal_12v_capacity_ah": round(self.battery_12v.nominal_capacity_ah, 1),
            "net_12v_current": 0.0,
            "is_12v_calibrated": self.battery_12v.is_calibrated,
            "daily_yield_kwh": 0.0,
            "daily_load_kwh": 0.0,
            "controller_temperature": None,
            "battery_temperature": None,
            "raw_keys": {},
            "last_updated": None,
        }

        self.system_gps: dict[str, Any] = {
            "fix": False,
            "fix_status": "V",
            "fix_quality": 0,
            "latitude": None,
            "longitude": None,
            "latitude_nautical": "--° --.---' -",
            "longitude_nautical": "---° --.---' -",
            "sog_knots": 0.0,
            "sog_kmh": 0.0,
            "sog_ms": 0.0,
            "cog_true": None,
            "altitude_m": None,
            "satellites": 0,
            "hdop": None,
            "last_sentence": None,
            "last_updated": None,
        }

        self.charger: dict[str, Any] = {
            "state": "OFFLINE",
            "output_voltage": 0.0,
            "output_current": 0.0,
            "output_power": 0.0,
            "target_current": 20.0,
            "temperature": 0.0,
            "error_code": "NONE",
            "last_updated": None,
        }

        self.raw_topics: dict[str, Any] = {}
        self.recent_packets = deque(maxlen=150)
        self.ws_clients: set[WebSocket] = set()
        self.alarms: dict[str, Any] = {
            "overall_status": "OK",
            "active_count": 0,
            "active_alarms": [],
        }

    def record_packet(self, topic: str, payload_str: str, source: str = "mqtt"):
        now = datetime.now(timezone.utc)
        iso_now = now.isoformat()
        self.last_packet_time = iso_now
        self.total_packets_received += 1
        self._packet_timestamps.append(now.timestamp())

        # Update rate
        now_ts = now.timestamp()
        recent = [t for t in self._packet_timestamps if now_ts - t <= 10.0]
        self.messages_per_second = round(len(recent) / 10.0, 1) if recent else 0.0

        parsed_json = None
        try:
            parsed_json = json.loads(payload_str)
        except (ValueError, TypeError):
            pass

        # Subsystem parser logic
        if topic == "paeraki/72v/state" and isinstance(parsed_json, dict):
            self.system_72v.update(parsed_json)
            self.system_72v["last_updated"] = iso_now

            curr = float(self.system_72v.get("current") or 0.0)
            volt = float(self.system_72v.get("total_voltage") or 0.0)
            bms_rsoc = float(self.system_72v.get("rsoc") or 0.0)
            nom_ah = float(self.system_72v.get("nominal_capacity_ah") or 200.0)
            n_cells = int(self.system_72v.get("number_of_cells") or 20) or 20
            ts = self.system_72v.get("timestamp") or iso_now

            soc_info = self.battery.update(
                current_a=curr,
                timestamp_iso=ts,
                bms_rsoc=bms_rsoc,
                pack_voltage=volt,
                nominal_ah=nom_ah,
                cell_count=n_cells,
            )
            self.system_72v.update(soc_info)
        elif topic == "paeraki/12v/state" and isinstance(parsed_json, dict):
            # Sanitize charging status to prevent boolean overwrites
            raw_status = parsed_json.get("charging_status")
            if isinstance(raw_status, bool) or str(raw_status).lower() in ("true", "false", ""):
                parsed_json["charging_status"] = self.system_12v.get("charging_status", "Idle")

            self.system_12v.update(parsed_json)
            self.system_12v["last_updated"] = iso_now

            # Run 12V AGM house battery model
            v_batt = float(self.system_12v.get("battery_voltage") or 0.0)
            chg_i = float(self.system_12v.get("battery_charge_current") or 0.0)
            load_i = float(self.system_12v.get("load_current") or 0.0)
            status_str = str(self.system_12v.get("charging_status") or "")
            ts = self.system_12v.get("timestamp") or iso_now

            soc_12v_info = self.battery_12v.update(
                charge_current_a=chg_i,
                load_current_a=load_i,
                batt_voltage=v_batt,
                timestamp_iso=ts,
                charging_status=status_str,
            )
            self.system_12v.update(soc_12v_info)

        elif topic == "paeraki/battery/72v/capacity" and isinstance(parsed_json, dict):
            new_cap = parsed_json.get("estimated_capacity_ah")
            if new_cap and float(new_cap) > 10.0:
                self.battery.update_capacity(float(new_cap), parsed_json.get("soh_percentage"))
                self.system_72v["nominal_capacity_ah"] = self.battery.nominal_capacity_ah
                self.system_72v["soh_percentage"] = self.battery.soh_percentage
                logger.info("Updated 72V capacity via MQTT to %.1f Ah (SoH: %.1f%%)", self.battery.nominal_capacity_ah, self.battery.soh_percentage)

        elif topic == "paeraki/battery/12v/capacity" and isinstance(parsed_json, dict):
            new_cap = parsed_json.get("estimated_capacity_ah")
            if new_cap and float(new_cap) > 10.0:
                self.battery_12v.set_capacity(float(new_cap), parsed_json.get("soh_percentage"))
                self.system_12v["nominal_capacity_ah"] = self.battery_12v.nominal_capacity_ah
                self.system_12v["soh_percentage"] = self.battery_12v.soh_percentage
                logger.info("Updated 12V capacity via MQTT to %.1f Ah (SoH: %.1f%%)", self.battery_12v.nominal_capacity_ah, self.battery_12v.soh_percentage)

        elif topic == "paeraki/alarms/state" and isinstance(parsed_json, dict):
            self.alarms = parsed_json

        elif topic.startswith("12v/"):
            field = topic.split("/", 1)[1]
            val = parsed_json if parsed_json is not None else payload_str
            # Prevent boolean subtopics from overwriting human-readable charging status
            if field.lower() in ("charging_status", "status") and str(val).lower() in ("true", "false"):
                pass
            else:
                try:
                    if isinstance(val, str) and "." in val:
                        val = float(val)
                    elif isinstance(val, str) and (val.lstrip("-").isdigit()):
                        val = int(val)
                except ValueError:
                    pass
                self.system_12v[field] = val
                self.system_12v["last_updated"] = iso_now

        elif topic == "paeraki/gps/state" and isinstance(parsed_json, dict):
            self.system_gps.update(parsed_json)
            self.system_gps["last_updated"] = iso_now
        elif topic.startswith("gps/"):
            field = topic.split("/", 1)[1]
            val = parsed_json if parsed_json is not None else payload_str
            try:
                if isinstance(val, str) and "." in val:
                    val = float(val)
                elif isinstance(val, str) and (val.lstrip("-").isdigit()):
                    val = int(val)
                elif isinstance(val, str) and val.lower() in ("true", "false"):
                    val = val.lower() == "true"
            except ValueError:
                pass
            self.system_gps[field] = val
            self.system_gps["last_updated"] = iso_now

        elif (topic in ("paeraki/charger/state", "charger/telemetry")) and isinstance(parsed_json, dict):
            self.charger.update(parsed_json)
            self.charger["last_updated"] = iso_now
        elif topic.startswith("charger/"):
            field = topic.split("/", 1)[1]
            val = parsed_json if parsed_json is not None else payload_str
            try:
                if isinstance(val, str) and "." in val:
                    val = float(val)
                elif isinstance(val, str) and (val.lstrip("-").isdigit()):
                    val = int(val)
            except ValueError:
                pass
            self.charger[field] = val
            self.charger["last_updated"] = iso_now

        else:
            self.raw_topics[topic] = {
                "value": parsed_json if parsed_json is not None else payload_str,
                "timestamp": iso_now,
            }

        packet_entry = {
            "id": self.total_packets_received,
            "topic": topic,
            "payload": parsed_json if parsed_json is not None else payload_str,
            "raw": payload_str[:300],
            "is_json": parsed_json is not None,
            "timestamp": iso_now,
            "source": source,
        }
        self.recent_packets.appendleft(packet_entry)
        return packet_entry

    def get_snapshot(self) -> dict:
        return {
            "server": {
                "hostname": socket.gethostname(),
            },
            "broker": {
                "host": self.broker_host,
                "port": self.broker_port,
                "connected": self.is_connected,
                "total_packets": self.total_packets_received,
                "msg_rate": self.messages_per_second,
                "last_packet_time": self.last_packet_time,
            },
            "subsystems": {
                "72v": self.system_72v,
                "12v": self.system_12v,
                "gps": self.system_gps,
                "charger": self.charger,
                "raw_topics": self.raw_topics,
            },
            "alarms": self.alarms,
            "recent_packets": list(self.recent_packets)[:50],
        }

    async def broadcast(self, message: dict):
        if not self.ws_clients:
            return
        payload = json.dumps(message)
        dead = []
        for ws in self.ws_clients:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.ws_clients.discard(ws)


state = DashboardState()


async def mqtt_worker(broker: str, port: int, retry_delay: float = 3.0):
    """Background task connecting to Paeraki broker and listening to #."""
    if not aiomqtt:
        logger.error("aiomqtt is not installed. Cannot run real MQTT listener.")
        return

    state.broker_host = broker
    state.broker_port = port

    while True:
        try:
            logger.info("Connecting to Paeraki MQTT broker at %s:%d...", broker, port)
            async with aiomqtt.Client(broker, port=port) as client:
                state.is_connected = True
                logger.info("Connected to Paeraki MQTT broker! Subscribing to '#'...")
                await client.subscribe("#")
                await state.broadcast({"type": "connection_status", "connected": True, "broker": f"{broker}:{port}"})

                async for msg in client.messages:
                    topic = str(msg.topic)
                    try:
                        payload_str = msg.payload.decode("utf-8")
                    except UnicodeDecodeError:
                        payload_str = f"<binary {len(msg.payload)} bytes>"

                    packet = state.record_packet(topic, payload_str, source="live")
                    await state.broadcast({
                        "type": "packet",
                        "packet": packet,
                        "snapshot": state.get_snapshot(),
                    })

        except Exception as err:
            state.is_connected = False
            logger.warning("MQTT connection lost (%s). Retrying in %ss...", err, retry_delay)
            await state.broadcast({"type": "connection_status", "connected": False, "error": str(err)})
            await asyncio.sleep(retry_delay)


async def mock_worker(interval: float = 2.0):
    """Generates synthetic telemetry for testing without live sensors."""
    logger.info("Starting mock telemetry generator (interval: %.1fs)...", interval)
    cell_count = 20
    soc = 88.0

    while True:
        try:
            # Fluctuate mock values
            soc = max(10.0, min(100.0, soc + random.uniform(-0.1, 0.05)))
            cell_base = 3.32 + (soc / 100.0) * 0.12
            cells = [round(cell_base + random.uniform(-0.015, 0.015), 3) for _ in range(cell_count)]
            v_total = round(sum(cells), 2)
            curr = round(random.uniform(-25.0, 5.0), 2)
            pwr = round(v_total * curr, 1)

            t72_data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_voltage": v_total,
                "current": curr,
                "power": pwr,
                "rsoc": round(soc, 1),
                "residual_capacity_ah": round(100.0 * (soc / 100.0), 2),
                "nominal_capacity_ah": 100.0,
                "cycle_times": 48,
                "charge_status": True,
                "discharge_status": True,
                "temperatures": [round(22.4 + random.uniform(-0.3, 0.3), 1), round(23.1 + random.uniform(-0.3, 0.3), 1)],
                "number_of_cells": cell_count,
                "cell_voltages": cells,
                "active_protection_states": [],
                "balance_states": [random.random() < 0.15 for _ in range(cell_count)],
            }

            # 12V House / Solar mock
            sol_v = round(random.uniform(32.0, 41.5), 1)
            sol_c = round(random.uniform(4.0, 18.2), 1)
            sol_p = round(sol_v * sol_c, 1)
            batt_12 = round(13.2 + random.uniform(-0.1, 0.2), 2)

            t12_data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "battery_voltage": batt_12,
                "battery_soc": round(92.0 + random.uniform(-1, 1), 0),
                "battery_charge_current": round(sol_p / max(1.0, batt_12), 2),
                "solar_power": sol_p,
                "solar_voltage": sol_v,
                "solar_current": sol_c,
                "load_voltage": batt_12,
                "load_current": 1.2,
                "load_power": round(batt_12 * 1.2, 1),
                "daily_yield_kwh": round(1.85 + random.uniform(0.01, 0.05), 2),
                "daily_load_kwh": round(0.42 + random.uniform(0.001, 0.005), 3),
                "charging_status": "MPPT Charge" if sol_p > 50 else "Float",
                "controller_temperature": round(21.0 + random.uniform(-0.5, 0.5), 1),
                "battery_temperature": round(24.0 + random.uniform(-0.3, 0.3), 1),
            }

            # Inject into state
            p1 = state.record_packet("paeraki/72v/state", json.dumps(t72_data), source="mock")
            p2 = state.record_packet("paeraki/12v/state", json.dumps(t12_data), source="mock")

            await state.broadcast({
                "type": "packet",
                "packet": p1,
                "snapshot": state.get_snapshot(),
            })

            await asyncio.sleep(interval)
        except Exception as e:
            logger.error("Error in mock generator: %s", e)
            await asyncio.sleep(interval)


def create_app(broker: str, port: int, enable_mock: bool = False) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Start background workers
        tasks = []
        if enable_mock:
            tasks.append(asyncio.create_task(mock_worker()))
        if broker:
            tasks.append(asyncio.create_task(mqtt_worker(broker, port)))

        yield

        # Shutdown workers
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="Paeraki Vessel Monitor", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    if DIST_DIR.exists():
        app.mount("/dist", StaticFiles(directory=str(DIST_DIR)), name="dist")

    @app.get("/sw.js")
    async def service_worker():
        sw_file = STATIC_DIR / "sw.js"
        if sw_file.exists():
            return FileResponse(
                sw_file,
                media_type="application/javascript",
                headers={"Service-Worker-Allowed": "/"},
            )
        return JSONResponse({"error": "Service worker not found"}, status_code=404)

    @app.get("/download")
    @app.get("/download/apk")
    async def download_apk():
        apk_file = DIST_DIR / "paeraki-monitor.apk"
        if apk_file.exists():
            return FileResponse(
                apk_file,
                media_type="application/vnd.android.package-archive",
                filename="paeraki-monitor.apk",
            )
        return JSONResponse({"error": "APK not found. Please run ./android/build_apk.sh first."}, status_code=404)

    @app.get("/")
    async def index():
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return JSONResponse({"status": "ok", "message": "Paeraki Monitor backend is running."})

    @app.get("/api/state")
    async def get_state():
        return JSONResponse(state.get_snapshot())

    @app.get("/api/health")
    async def health():
        return JSONResponse({
            "status": "healthy",
            "broker_connected": state.is_connected,
            "packets_received": state.total_packets_received,
            "active_ws_clients": len(state.ws_clients),
        })

    @app.post("/api/72v/calibrate_soc")
    async def calibrate_soc(request: Request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}

        if payload.get("sync_to_voltage"):
            soc_v = float(state.system_72v.get("soc_voltage", 0.0))
            state.battery.recalibrate(soc_pct=soc_v)
        elif "ah" in payload:
            state.battery.recalibrate(ah=float(payload["ah"]))
        elif "soc_pct" in payload:
            state.battery.recalibrate(soc_pct=float(payload["soc_pct"]))

        curr = float(state.system_72v.get("current") or 0.0)
        volt = float(state.system_72v.get("total_voltage") or 0.0)
        bms_rsoc = float(state.system_72v.get("rsoc") or 0.0)
        soc_info = state.battery.update(current_a=curr, bms_rsoc=bms_rsoc, pack_voltage=volt)
        state.system_72v.update(soc_info)
        await state.broadcast({"type": "snapshot", "snapshot": state.get_snapshot()})
        return JSONResponse({"status": "ok", "system_72v": state.system_72v})

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        state.ws_clients.add(websocket)
        logger.info("New WebSocket client connected (%d total)", len(state.ws_clients))
        try:
            # Send initial snapshot immediately upon connect
            await websocket.send_text(json.dumps({
                "type": "snapshot",
                "snapshot": state.get_snapshot(),
            }))
            # Keep alive
            while True:
                data = await websocket.receive_text()
                # Handle client ping or command
                if data == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
        except WebSocketDisconnect:
            pass
        finally:
            state.ws_clients.discard(websocket)
            logger.info("WebSocket client disconnected (%d remaining)", len(state.ws_clients))

    return app


def main():
    parser = argparse.ArgumentParser(description="Paeraki Yacht Telemetry Monitor (hammer)")
    parser.add_argument("--broker", default="192.168.1.1", help="Paeraki MQTT Broker host (default: 192.168.1.1)")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT Broker port (default: 1883)")
    parser.add_argument("--host", default="0.0.0.0", help="Web server bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Web server bind port (default: 8080)")
    parser.add_argument("--mock", action="store_true", help="Enable synthetic mock telemetry stream alongside MQTT")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Log level")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("Starting Paeraki Monitor on http://%s:%d (Broker: %s:%d, Mock: %s)",
                args.host, args.port, args.broker, args.mqtt_port, args.mock)

    app = create_app(broker=args.broker, port=args.mqtt_port, enable_mock=args.mock)
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level.lower())


if __name__ == "__main__":
    main()
