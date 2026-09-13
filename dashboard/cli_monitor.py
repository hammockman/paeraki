#!/usr/bin/env python3
"""
Paeraki Yacht Terminal Telemetry Monitor (runs on hammer).
Lightweight, rich terminal dashboard displaying real-time telemetry from yacht Paeraki.
"""

import argparse
import asyncio
import json
import logging
from collections import deque
from datetime import datetime

try:
    import aiomqtt
except ImportError:
    aiomqtt = None

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from battery import BatteryIntegrator, calculate_voltage_soc

console = Console()


def create_layout() -> Layout:
    layout = Layout(name="root")
    layout.split(
        Layout(name="header", size=3),
        Layout(name="main", ratio=1),
        Layout(name="log", size=10),
    )
    layout["main"].split_row(
        Layout(name="propulsion", ratio=1),
        Layout(name="house", ratio=1),
        Layout(name="navigation", ratio=1),
    )
    return layout


def make_header(broker: str, packets: int, rate: float, connected: bool) -> Panel:
    title = Text("⚓ PAERAKI VESSEL MONITOR (HAMMER) ⚓", style="bold cyan")
    status = Text(" CONNECTED ", style="bold black on green") if connected else Text(" CONNECTING... ", style="bold white on red")
    meta = Text(f" Broker: {broker}  |  Packets: {packets}  |  Rate: {rate:.1f} msg/s", style="dim")

    grid = Table.grid(expand=True)
    grid.add_column(justify="left", ratio=1)
    grid.add_column(justify="center", ratio=2)
    grid.add_column(justify="right", ratio=1)
    grid.add_row(status, title, meta)

    return Panel(grid, style="cyan", border_style="cyan")


def make_72v_panel(data: dict) -> Panel:
    table = Table(box=None, expand=True, show_header=False)
    table.add_column("Metric", style="dim")
    table.add_column("Value", justify="right", style="bold")

    soc_integ = data.get("soc_integrated", 0.0)
    integ_ah = data.get("integrated_ah", 0.0)
    soc_volt = data.get("soc_voltage", 0.0)
    soc_bms = data.get("rsoc", 0)

    integ_style = "bold green" if soc_integ > 40 else "bold yellow" if soc_integ > 20 else "bold red"
    volt_style = "bold green" if soc_volt > 40 else "bold yellow" if soc_volt > 20 else "bold red"
    bms_style = "bold red" if data.get("soc_discrepancy") else ("bold green" if soc_bms > 40 else "bold yellow")

    voltage = data.get("total_voltage", 0.0)
    current = data.get("current", 0.0)
    power = data.get("power", 0.0)

    cur_style = "green" if current > 0 else "cyan" if current < 0 else "white"

    table.add_row("SoC (Integrated Ah)", Text(f"{soc_integ:.1f}% ({integ_ah:.1f} Ah)", style=integ_style))
    table.add_row("SoC (Voltage OCV)", Text(f"{soc_volt:.1f}% (20S Leaf)", style=volt_style))
    table.add_row("SoC (BMS Reported)", Text(f"{soc_bms}% {'[DESYNCED]' if data.get('soc_discrepancy') else ''}", style=bms_style))
    table.add_row("Pack Voltage", f"{voltage:.2f} V")
    table.add_row("Pack Current", Text(f"{current:+.2f} A", style=cur_style))
    table.add_row("Net Power", f"{power:+.1f} W")
    table.add_row("BMS Capacity", f"{data.get('residual_capacity_ah', 0):.1f} / {data.get('nominal_capacity_ah', 0):.0f} Ah")
    table.add_row("Cycle Count", str(data.get("cycle_times", "--")))

    temps = data.get("temperatures", [])
    t_str = ", ".join(f"{t}°C" for t in temps) if temps else "--"
    table.add_row("Temperatures", t_str)

    cells = data.get("cell_voltages", [])
    if cells:
        min_c = min(cells)
        max_c = max(cells)
        delta_mv = int((max_c - min_c) * 1000)
        table.add_row("Cell Delta", f"{delta_mv} mV (Min: {min_c:.3f}V, Max: {max_c:.3f}V)")

    return Panel(table, title="[bold cyan]72V Propulsion System (JBD BMS)[/]", border_style="cyan")


def make_12v_panel(data: dict) -> Panel:
    table = Table(box=None, expand=True, show_header=False)
    table.add_column("Metric", style="dim")
    table.add_column("Value", justify="right", style="bold")

    batt_v = data.get("battery_voltage", 0.0)
    sol_w = data.get("solar_power", 0.0)
    sol_v = data.get("solar_voltage", 0.0)
    sol_a = data.get("solar_current", 0.0)

    table.add_row("House Battery Voltage", f"{batt_v:.2f} V" if batt_v else "--.- V")
    table.add_row("House Battery SoC", f"{data.get('battery_soc', '--')}%")
    table.add_row("Solar PV Power", Text(f"{sol_w:.1f} W", style="bold yellow"))
    table.add_row("Solar Voltage / Current", f"{sol_v:.1f} V / {sol_a:.1f} A")
    table.add_row("Controller State", str(data.get("charging_status", "Active")))
    table.add_row("Daily Yield", f"{data.get('daily_yield_kwh', '--')} kWh")
    table.add_row("Subscribed Topics", f"{len(data.get('raw_keys', {}))} keys")

    return Panel(table, title="[bold yellow]12V House & Solar System (SRNE/Renogy)[/]", border_style="yellow")


def make_gps_panel(data: dict) -> Panel:
    table = Table(box=None, expand=True, show_header=False)
    table.add_column("Metric", style="dim")
    table.add_column("Value", justify="right", style="bold")

    fix = data.get("fix", False)
    fix_style = "bold green" if fix else "bold yellow"
    fix_label = "3D Fix" if fix else ("Searching" if data.get("fix_status") != "A" else "Valid Fix")

    sog = float(data.get("sog_knots") or 0.0)
    sog_kmh = float(data.get("sog_kmh") or (sog * 1.852))
    cog = data.get("cog_true")
    cog_str = f"{float(cog):05.1f}° True" if cog is not None else "---.-°"

    lat_naut = data.get("latitude_nautical", "--° --.---' -")
    lon_naut = data.get("longitude_nautical", "---° --.---' -")
    sats = data.get("satellites", 0)
    hdop = data.get("hdop")
    alt = data.get("altitude_m")

    table.add_row("Fix Status", Text(fix_label, style=fix_style))
    table.add_row("Speed (SOG)", Text(f"{sog:.1f} kts ({sog_kmh:.1f} km/h)", style="bold green" if sog > 0 else "white"))
    table.add_row("Course (COG)", cog_str)
    table.add_row("Latitude", lat_naut)
    table.add_row("Longitude", lon_naut)
    table.add_row("Satellites", f"{sats} locked")
    table.add_row("Precision (HDOP)", f"{float(hdop):.2f}" if hdop is not None else "--")
    table.add_row("Altitude", f"{float(alt):.1f} m" if alt is not None else "--")

    return Panel(table, title="[bold green]Navigation & GPS (RUT955)[/]", border_style="green")


def make_log_panel(messages: deque) -> Panel:
    table = Table(expand=True, box=None)
    table.add_column("Time", style="dim", width=10)
    table.add_column("Topic", style="bold magenta", width=26)
    table.add_column("Payload", style="white")

    for msg in list(messages)[-7:]:
        table.add_row(msg["time"], msg["topic"], msg["payload"][:80])

    return Panel(table, title="[bold purple]Live MQTT Stream (Topic: #)[/]", border_style="purple")


async def run_cli_monitor(broker: str, port: int, mock: bool = False):
    packets_count = 0
    connected = False
    rate = 0.0
    recent_messages = deque(maxlen=20)
    state_72v = {}
    state_12v = {}
    state_gps = {}
    battery = BatteryIntegrator(
        nominal_capacity_ah=200.0,
        state_file=Path(__file__).parent.parent / "data" / "dashboard_soc_state.json",
        seed_ah=134.90,
    )

    layout = create_layout()

    async def update_ui(live: Live):
        while True:
            layout["header"].update(make_header(f"{broker}:{port}", packets_count, rate, connected))
            layout["propulsion"].update(make_72v_panel(state_72v))
            layout["house"].update(make_12v_panel(state_12v))
            layout["navigation"].update(make_gps_panel(state_gps))
            layout["log"].update(make_log_panel(recent_messages))
            live.refresh()
            await asyncio.sleep(0.25)

    async def mqtt_loop():
        nonlocal packets_count, connected, rate
        while True:
            try:
                async with aiomqtt.Client(broker, port=port) as client:
                    connected = True
                    await client.subscribe("#")
                    async for msg in client.messages:
                        packets_count += 1
                        topic = str(msg.topic)
                        payload = msg.payload.decode("utf-8", errors="ignore")
                        now_str = datetime.now().strftime("%H:%M:%S")

                        recent_messages.append({"time": now_str, "topic": topic, "payload": payload})

                        try:
                            data = json.loads(payload)
                            if topic == "paeraki/72v/state" and isinstance(data, dict):
                                state_72v.update(data)
                            elif topic == "paeraki/12v/state" and isinstance(data, dict):
                                state_12v.update(data)
                            elif topic == "paeraki/gps/state" and isinstance(data, dict):
                                state_gps.update(data)
                        except Exception:
                            if topic.startswith("72v/"):
                                state_72v[topic.split("/")[1]] = payload
                            elif topic.startswith("gps/"):
                                state_gps[topic.split("/")[1]] = payload

                        if topic == "paeraki/72v/state" or topic.startswith("72v/"):
                            curr = float(state_72v.get("current") or 0.0)
                            volt = float(state_72v.get("total_voltage") or 0.0)
                            bms_rsoc = float(state_72v.get("rsoc") or 0.0)
                            nom_ah = float(state_72v.get("nominal_capacity_ah") or 200.0)
                            n_cells = int(state_72v.get("number_of_cells") or 20) or 20
                            soc_info = battery.update(
                                current_a=curr,
                                bms_rsoc=bms_rsoc,
                                pack_voltage=volt,
                                nominal_ah=nom_ah,
                                cell_count=n_cells,
                            )
                            state_72v.update(soc_info)

            except Exception:
                connected = False
                await asyncio.sleep(3.0)

    with Live(layout, refresh_per_second=4, screen=True) as live:
        t_ui = asyncio.create_task(update_ui(live))
        t_mqtt = asyncio.create_task(mqtt_loop())
        await asyncio.gather(t_ui, t_mqtt)


def main():
    parser = argparse.ArgumentParser(description="Paeraki Terminal Telemetry Monitor")
    parser.add_argument("--broker", default="192.168.1.1", help="Paeraki MQTT Broker host")
    parser.add_argument("--port", type=int, default=1883, help="Paeraki MQTT Broker port")
    args = parser.parse_args()

    asyncio.run(run_cli_monitor(args.broker, args.port))


if __name__ == "__main__":
    main()
