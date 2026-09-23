"""Database query engine and async background worker for Paeraki Telemetry History.

Opens paeraki.db in read-only URI mode to prevent any database contention or locking
with paeraki_logger.service's continuous WAL updates.
"""

from __future__ import annotations

import datetime
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot

DB_PATH = Path("/home/jh/paeraki/data/paeraki.db")


@dataclass(frozen=True)
class MetricDef:
    """Definition and display metadata for a telemetry metric."""
    id: str
    name: str
    table: str
    column: str
    unit: str
    category_id: str
    category_name: str
    color: str
    bipolar: bool = False
    is_default: bool = False
    description: str = ""


# Master catalog of available metrics in paeraki.db
METRIC_CATALOG: dict[str, MetricDef] = {
    # ⚡ 72V High-Voltage Battery (BMS)
    "72v_v": MetricDef(
        id="72v_v", name="Pack Voltage", table="telemetry_72v", column="total_voltage",
        unit="V", category_id="72v", category_name="⚡ 72V High-Voltage Battery",
        color="#00e5ff", is_default=True, description="Total 20S battery pack terminal voltage"
    ),
    "72v_i": MetricDef(
        id="72v_i", name="Pack Current", table="telemetry_72v", column="current",
        unit="A", category_id="72v", category_name="⚡ 72V High-Voltage Battery",
        color="#10b981", bipolar=True, is_default=True, description="Net battery current (-ve discharge, +ve charge)"
    ),
    "72v_p": MetricDef(
        id="72v_p", name="Propulsion Power", table="telemetry_72v", column="power",
        unit="W", category_id="72v", category_name="⚡ 72V High-Voltage Battery",
        color="#fbbf24", is_default=True, description="Net propulsion electrical power"
    ),
    "72v_soc": MetricDef(
        id="72v_soc", name="State of Charge (RSOC)", table="telemetry_72v", column="rsoc",
        unit="%", category_id="72v", category_name="⚡ 72V High-Voltage Battery",
        color="#06b6d4", description="BMS reported remaining state of charge percentage"
    ),
    "72v_delta": MetricDef(
        id="72v_delta", name="Cell Delta (Max - Min)", table="telemetry_72v", column="cell_delta_mv",
        unit="mV", category_id="72v", category_name="⚡ 72V High-Voltage Battery",
        color="#f43f5e", is_default=True, description="Imbalance delta between highest and lowest 20S cell"
    ),
    "72v_cell_min": MetricDef(
        id="72v_cell_min", name="Lowest Cell Voltage", table="telemetry_72v", column="cell_min_v",
        unit="V", category_id="72v", category_name="⚡ 72V High-Voltage Battery",
        color="#38bdf8", description="Voltage of lowest 20S cell"
    ),
    "72v_cell_max": MetricDef(
        id="72v_cell_max", name="Highest Cell Voltage", table="telemetry_72v", column="cell_max_v",
        unit="V", category_id="72v", category_name="⚡ 72V High-Voltage Battery",
        color="#00e5ff", description="Voltage of highest 20S cell"
    ),
    "72v_cap": MetricDef(
        id="72v_cap", name="Remaining Capacity", table="telemetry_72v", column="residual_capacity_ah",
        unit="Ah", category_id="72v", category_name="⚡ 72V High-Voltage Battery",
        color="#2563eb", description="BMS estimated residual capacity in ampere-hours"
    ),
    "72v_t1": MetricDef(
        id="72v_t1", name="Battery Temp Sensor 1", table="telemetry_72v", column="temp_1",
        unit="°C", category_id="72v", category_name="⚡ 72V High-Voltage Battery",
        color="#f97316", description="BMS internal temperature sensor 1"
    ),
    "72v_t2": MetricDef(
        id="72v_t2", name="Battery Temp Sensor 2", table="telemetry_72v", column="temp_2",
        unit="°C", category_id="72v", category_name="⚡ 72V High-Voltage Battery",
        color="#ef4444", description="BMS internal temperature sensor 2"
    ),
    "72v_cycles": MetricDef(
        id="72v_cycles", name="Cycle Count", table="telemetry_72v", column="cycle_times",
        unit="count", category_id="72v", category_name="⚡ 72V High-Voltage Battery",
        color="#94a3b8", description="Total recorded charge/discharge cycles"
    ),

    # ☀ 12V House & Solar MPPT
    "12v_v": MetricDef(
        id="12v_v", name="House Battery Voltage", table="telemetry_12v", column="battery_voltage",
        unit="V", category_id="12v", category_name="☀ 12V House & Solar MPPT",
        color="#38bdf8", is_default=True, description="House 12V battery terminal voltage"
    ),
    "12v_soc": MetricDef(
        id="12v_soc", name="House Battery SoC", table="telemetry_12v", column="battery_soc",
        unit="%", category_id="12v", category_name="☀ 12V House & Solar MPPT",
        color="#10b981", description="House 12V battery state of charge percentage"
    ),
    "12v_net_i": MetricDef(
        id="12v_net_i", name="House Battery Net Current", table="telemetry_12v", column="battery_charge_current",
        unit="A", category_id="12v", category_name="☀ 12V House & Solar MPPT",
        color="#10b981", bipolar=True, is_default=True, description="Current into house battery from MPPT controller"
    ),
    "12v_pv_v": MetricDef(
        id="12v_pv_v", name="Solar Array Voltage", table="telemetry_12v", column="solar_voltage",
        unit="V", category_id="12v", category_name="☀ 12V House & Solar MPPT",
        color="#f59e0b", description="Photovoltaic array DC input voltage"
    ),
    "12v_pv_i": MetricDef(
        id="12v_pv_i", name="Solar Generation Current", table="telemetry_12v", column="solar_current",
        unit="A", category_id="12v", category_name="☀ 12V House & Solar MPPT",
        color="#f59e0b", is_default=True, description="Photovoltaic array generation current"
    ),
    "12v_pv_p": MetricDef(
        id="12v_pv_p", name="Solar Generation Power", table="telemetry_12v", column="solar_power",
        unit="W", category_id="12v", category_name="☀ 12V House & Solar MPPT",
        color="#ec4899", is_default=True, description="Solar generation electrical power harvested"
    ),
    "12v_load_v": MetricDef(
        id="12v_load_v", name="DC Load Output Voltage", table="telemetry_12v", column="load_voltage",
        unit="V", category_id="12v", category_name="☀ 12V House & Solar MPPT",
        color="#c084fc", description="MPPT DC load terminal voltage"
    ),
    "12v_load_i": MetricDef(
        id="12v_load_i", name="DC Load Output Current", table="telemetry_12v", column="load_current",
        unit="A", category_id="12v", category_name="☀ 12V House & Solar MPPT",
        color="#a855f7", description="MPPT DC load output current"
    ),
    "12v_load_p": MetricDef(
        id="12v_load_p", name="DC Load Output Power", table="telemetry_12v", column="load_power",
        unit="W", category_id="12v", category_name="☀ 12V House & Solar MPPT",
        color="#a855f7", description="MPPT DC load consumption power"
    ),
    "12v_yield": MetricDef(
        id="12v_yield", name="Solar Daily Yield", table="telemetry_12v", column="daily_yield_kwh",
        unit="kWh", category_id="12v", category_name="☀ 12V House & Solar MPPT",
        color="#eab308", description="Total solar energy harvested today"
    ),
    "12v_ctrl_t": MetricDef(
        id="12v_ctrl_t", name="MPPT Controller Temp", table="telemetry_12v", column="controller_temp",
        unit="°C", category_id="12v", category_name="☀ 12V House & Solar MPPT",
        color="#f97316", description="SRNE Shiner2440 internal heatsink temperature"
    ),
    "12v_batt_t": MetricDef(
        id="12v_batt_t", name="12V Battery Temp", table="telemetry_12v", column="battery_temp",
        unit="°C", category_id="12v", category_name="☀ 12V House & Solar MPPT",
        color="#ef4444", description="House battery temperature sensor probe"
    ),

    # 🧭 SeaTalkNG / NMEA2000
    "stng_sog": MetricDef(
        id="stng_sog", name="Speed Over Ground (SOG)", table="telemetry_seatalkng", column="sog_knots",
        unit="kn", category_id="stng", category_name="🧭 SeaTalkNG / NMEA2000",
        color="#0ea5e9", description="Vessel speed over ground from high-precision GNSS"
    ),
    "stng_hdg": MetricDef(
        id="stng_hdg", name="Compass Heading (Magnetic)", table="telemetry_seatalkng", column="heading_deg",
        unit="°", category_id="stng", category_name="🧭 SeaTalkNG / NMEA2000",
        color="#3b82f6", description="Raymarine Evolution 9-axis compass heading"
    ),
    "stng_cog": MetricDef(
        id="stng_cog", name="Course Over Ground (COG)", table="telemetry_seatalkng", column="cog_true",
        unit="°", category_id="stng", category_name="🧭 SeaTalkNG / NMEA2000",
        color="#14b8a6", description="Vessel course over ground (True)"
    ),
    "stng_var": MetricDef(
        id="stng_var", name="Magnetic Variation", table="telemetry_seatalkng", column="variation_deg",
        unit="°", category_id="stng", category_name="🧭 SeaTalkNG / NMEA2000",
        color="#14b8a6", description="Local magnetic variation"
    ),
    "stng_pitch": MetricDef(
        id="stng_pitch", name="Vessel Pitch Attitude", table="telemetry_seatalkng", column="pitch_deg",
        unit="°", category_id="stng", category_name="🧭 SeaTalkNG / NMEA2000",
        color="#10b981", bipolar=True, description="Vessel pitch angle (+ bow up, - bow down)"
    ),
    "stng_roll": MetricDef(
        id="stng_roll", name="Vessel Roll Attitude (Heel)", table="telemetry_seatalkng", column="roll_deg",
        unit="°", category_id="stng", category_name="🧭 SeaTalkNG / NMEA2000",
        color="#f59e0b", bipolar=True, description="Vessel roll / heel angle (+ stbd, - port)"
    ),
    "stng_yaw": MetricDef(
        id="stng_yaw", name="Vessel Yaw Attitude", table="telemetry_seatalkng", column="yaw_deg",
        unit="°", category_id="stng", category_name="🧭 SeaTalkNG / NMEA2000",
        color="#8b5cf6", description="Vessel yaw angle"
    ),
    "stng_rot": MetricDef(
        id="stng_rot", name="Rate of Turn", table="telemetry_seatalkng", column="rate_of_turn_dps",
        unit="°/s", category_id="stng", category_name="🧭 SeaTalkNG / NMEA2000",
        color="#d946ef", bipolar=True, description="Vessel angular turning rate in degrees per second"
    ),
    "stng_rudder": MetricDef(
        id="stng_rudder", name="Rudder Angle", table="telemetry_seatalkng", column="rudder_deg",
        unit="°", category_id="stng", category_name="🧭 SeaTalkNG / NMEA2000",
        color="#ec4899", bipolar=True, description="Autopilot rudder position"
    ),
    "stng_press": MetricDef(
        id="stng_press", name="Barometric Pressure", table="telemetry_seatalkng", column="pressure_hpa",
        unit="hPa", category_id="stng", category_name="🧭 SeaTalkNG / NMEA2000",
        color="#a855f7", description="Atmospheric barometric pressure from Vesper Cortex (PGN 130314)"
    ),
    "stng_sats": MetricDef(
        id="stng_sats", name="GNSS Satellites Tracked", table="telemetry_seatalkng", column="satellites",
        unit="count", category_id="stng", category_name="🧭 SeaTalkNG / NMEA2000",
        color="#94a3b8", description="Number of GNSS satellites tracked by Cortex"
    ),
    "stng_hdop": MetricDef(
        id="stng_hdop", name="GNSS HDOP Precision", table="telemetry_seatalkng", column="hdop",
        unit="HDOP", category_id="stng", category_name="🧭 SeaTalkNG / NMEA2000",
        color="#34d399", description="Horizontal dilution of precision"
    ),
    "stng_alt": MetricDef(
        id="stng_alt", name="GNSS Altitude", table="telemetry_seatalkng", column="altitude_m",
        unit="m", category_id="stng", category_name="🧭 SeaTalkNG / NMEA2000",
        color="#64748b", description="SeaTalkNG GNSS elevation above mean sea level"
    ),
    "stng_ais": MetricDef(
        id="stng_ais", name="Active AIS Targets", table="telemetry_seatalkng", column="ais_target_count",
        unit="count", category_id="stng", category_name="🧭 SeaTalkNG / NMEA2000",
        color="#eab308", description="Number of tracked AIS vessels in VHF range"
    ),

    # 📡 Router GPS (RUT955)
    "gps_sog": MetricDef(
        id="gps_sog", name="Router GPS SOG", table="telemetry_gps", column="sog_knots",
        unit="kn", category_id="gps", category_name="📡 Router GPS (RUT955)",
        color="#0ea5e9", description="Teltonika RUT955 router GPS speed over ground"
    ),
    "gps_cog": MetricDef(
        id="gps_cog", name="Router GPS COG", table="telemetry_gps", column="cog_true",
        unit="°", category_id="gps", category_name="📡 Router GPS (RUT955)",
        color="#14b8a6", description="Teltonika RUT955 router GPS course over ground"
    ),
    "gps_alt": MetricDef(
        id="gps_alt", name="Altitude", table="telemetry_gps", column="altitude_m",
        unit="m", category_id="gps", category_name="📡 Router GPS (RUT955)",
        color="#64748b", description="Elevation above mean sea level"
    ),
    "gps_sats": MetricDef(
        id="gps_sats", name="Router Satellites Tracked", table="telemetry_gps", column="satellites",
        unit="count", category_id="gps", category_name="📡 Router GPS (RUT955)",
        color="#94a3b8", description="Satellites tracked by router GNSS"
    ),
    "gps_hdop": MetricDef(
        id="gps_hdop", name="Router GPS HDOP", table="telemetry_gps", column="hdop",
        unit="HDOP", category_id="gps", category_name="📡 Router GPS (RUT955)",
        color="#34d399", description="Router GPS dilution of precision"
    ),

    # 🔌 72V BF Tech Charger
    "chg_v": MetricDef(
        id="chg_v", name="Charger Output Voltage", table="telemetry_charger", column="output_voltage",
        unit="V", category_id="chg", category_name="🔌 72V BF Tech Charger",
        color="#c084fc", description="72V BF Tech charger terminal voltage"
    ),
    "chg_i": MetricDef(
        id="chg_i", name="Charger Output Current", table="telemetry_charger", column="output_current",
        unit="A", category_id="chg", category_name="🔌 72V BF Tech Charger",
        color="#38bdf8", description="72V BF Tech charger output current"
    ),
    "chg_p": MetricDef(
        id="chg_p", name="Charger Output Power", table="telemetry_charger", column="output_power",
        unit="W", category_id="chg", category_name="🔌 72V BF Tech Charger",
        color="#fbbf24", description="72V BF Tech charger power output"
    ),
    "chg_target_i": MetricDef(
        id="chg_target_i", name="Charger Target Current", table="telemetry_charger", column="target_current",
        unit="A", category_id="chg", category_name="🔌 72V BF Tech Charger",
        color="#06b6d4", description="Charger setpoint current target"
    ),
    "chg_temp": MetricDef(
        id="chg_temp", name="Charger Temperature", table="telemetry_charger", column="temp",
        unit="°C", category_id="chg", category_name="🔌 72V BF Tech Charger",
        color="#f97316", description="Charger internal heat sink temperature"
    ),

    # ❄ Brass Monkey Dual-Zone Fridge
    "fridge_left_t": MetricDef(
        id="fridge_left_t", name="Fridge Left Temp", table="telemetry_fridge", column="left_temp",
        unit="°C", category_id="fridge", category_name="❄ Brass Monkey Fridge",
        color="#38bdf8", description="Left zone current compartment temperature"
    ),
    "fridge_left_target": MetricDef(
        id="fridge_left_target", name="Fridge Left Target", table="telemetry_fridge", column="left_target",
        unit="°C", category_id="fridge", category_name="❄ Brass Monkey Fridge",
        color="#0284c7", description="Left zone target setpoint temperature"
    ),
    "fridge_right_t": MetricDef(
        id="fridge_right_t", name="Fridge Right Temp", table="telemetry_fridge", column="right_temp",
        unit="°C", category_id="fridge", category_name="❄ Brass Monkey Fridge",
        color="#818cf8", description="Right zone current compartment temperature"
    ),
    "fridge_right_target": MetricDef(
        id="fridge_right_target", name="Fridge Right Target", table="telemetry_fridge", column="right_target",
        unit="°C", category_id="fridge", category_name="❄ Brass Monkey Fridge",
        color="#4f46e5", description="Right zone target setpoint temperature"
    ),
    "fridge_v": MetricDef(
        id="fridge_v", name="Fridge Voltage", table="telemetry_fridge", column="voltage",
        unit="V", category_id="fridge", category_name="❄ Brass Monkey Fridge",
        color="#fbbf24", description="Terminal supply voltage measured at fridge"
    ),
    "fridge_comp": MetricDef(
        id="fridge_comp", name="Compressor State", table="telemetry_fridge", column="compressor_running",
        unit="", category_id="fridge", category_name="❄ Brass Monkey Fridge",
        color="#10b981", description="Compressor running status (1=Running, 0=Idle)"
    ),
}

# Categorized groups in display order
CATEGORIES = [
    ("72v", "⚡ 72V High-Voltage Battery"),
    ("12v", "☀ 12V House & Solar MPPT"),
    ("fridge", "❄ Brass Monkey Fridge"),
    ("stng", "🧭 SeaTalkNG / NMEA2000"),
    ("gps", "📡 Router GPS (RUT955)"),
    ("chg", "🔌 72V BF Tech Charger"),
]

# Quick 1-click presets
PRESETS: dict[str, list[str]] = {
    "72V": ["72v_v", "72v_i", "72v_p", "72v_delta"],
    "12V": ["12v_v", "12v_net_i", "12v_pv_i", "12v_pv_p"],
    "Fridge": ["fridge_left_t", "fridge_left_target", "fridge_right_t", "fridge_right_target", "fridge_v", "fridge_comp"],
    "Nav": ["stng_sog", "stng_hdg", "stng_pitch", "stng_roll", "stng_press"],
    "All V": ["72v_v", "72v_cell_min", "72v_cell_max", "12v_v", "12v_pv_v", "12v_load_v", "chg_v", "fridge_v"],
    "All A": ["72v_i", "12v_net_i", "12v_pv_i", "12v_load_i", "chg_i"],
    "All W": ["72v_p", "12v_pv_p", "12v_load_p", "chg_p"],
    "Temps": ["72v_t1", "72v_t2", "12v_ctrl_t", "12v_batt_t", "chg_temp", "fridge_left_t", "fridge_right_t"],
    "Clear": [],
}


def get_db_connection() -> sqlite3.Connection:
    """Return a read-only URI connection to paeraki.db."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}")
    uri = f"file:{DB_PATH.resolve()}?mode=ro"
    con = sqlite3.connect(uri, uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def get_time_bounds() -> dict[str, Any]:
    """Retrieve global min/max timestamps and row counts across all tables."""
    con = get_db_connection()
    try:
        cur = con.cursor()
        tables = [
            "telemetry_72v",
            "telemetry_12v",
            "telemetry_gps",
            "telemetry_charger",
            "telemetry_seatalkng",
            "packets",
        ]
        overall_min = None
        overall_max = None
        counts = {}

        for tbl in tables:
            cur.execute(f"SELECT COUNT(*), MIN(epoch_ms), MAX(epoch_ms) FROM {tbl}")
            cnt, mn, mx = cur.fetchone()
            counts[tbl] = cnt
            if mn is not None:
                overall_min = mn if overall_min is None else min(overall_min, mn)
            if mx is not None:
                overall_max = mx if overall_max is None else max(overall_max, mx)

        return {
            "min_ms": overall_min or int((time.time() - 86400) * 1000),
            "max_ms": overall_max or int(time.time() * 1000),
            "counts": counts,
        }
    finally:
        con.close()


def query_table(table_name: str, start_ms: int, end_ms: int, max_points: int = 10000) -> list[dict[str, Any]]:
    """Generic query for any telemetry table with downsampling."""
    con = get_db_connection()
    try:
        cur = con.cursor()
        cur.execute(
            f"SELECT COUNT(*) FROM {table_name} WHERE epoch_ms BETWEEN ? AND ?",
            (start_ms, end_ms),
        )
        total_rows = cur.fetchone()[0]
        step = max(1, total_rows // max_points) if total_rows > max_points else 1

        if step > 1:
            sql = f"""
            SELECT * FROM (
                SELECT *, ROW_NUMBER() OVER (ORDER BY epoch_ms ASC) as rn
                FROM {table_name}
                WHERE epoch_ms BETWEEN ? AND ?
            ) WHERE (rn % ?) = 1
            ORDER BY epoch_ms ASC
            """
            cur.execute(sql, (start_ms, end_ms, step))
        else:
            cur.execute(
                f"SELECT * FROM {table_name} WHERE epoch_ms BETWEEN ? AND ? ORDER BY epoch_ms ASC",
                (start_ms, end_ms),
            )

        return [dict(r) for r in cur.fetchall()]
    finally:
        con.close()


def query_72v(start_ms: int, end_ms: int, max_points: int = 10000) -> list[dict[str, Any]]:
    """Fetch 72V telemetry within [start_ms, end_ms]."""
    return query_table("telemetry_72v", start_ms, end_ms, max_points)


def query_charger(start_ms: int, end_ms: int, max_points: int = 10000) -> list[dict[str, Any]]:
    """Fetch 72V BF Tech Charger telemetry within [start_ms, end_ms]."""
    return query_table("telemetry_charger", start_ms, end_ms, max_points)


def query_12v(start_ms: int, end_ms: int, max_points: int = 10000) -> list[dict[str, Any]]:
    """Fetch 12V House & Solar telemetry within [start_ms, end_ms]."""
    return query_table("telemetry_12v", start_ms, end_ms, max_points)


def query_gps(start_ms: int, end_ms: int, max_points: int = 10000) -> list[dict[str, Any]]:
    """Fetch GPS navigation telemetry within [start_ms, end_ms]."""
    return query_table("telemetry_gps", start_ms, end_ms, max_points)


def query_seatalkng(start_ms: int, end_ms: int, max_points: int = 10000) -> list[dict[str, Any]]:
    """Fetch SeaTalkNG navigation & attitude telemetry within [start_ms, end_ms]."""
    return query_table("telemetry_seatalkng", start_ms, end_ms, max_points)


def query_tables_batch(tables: list[str], start_ms: int, end_ms: int, max_points: int = 10000) -> dict[str, list[dict[str, Any]]]:
    """Fetch multiple tables in a single connection session, returning {table_name: rows}."""
    result: dict[str, list[dict[str, Any]]] = {}
    con = get_db_connection()
    try:
        cur = con.cursor()
        for tbl in tables:
            cur.execute(f"SELECT COUNT(*) FROM {tbl} WHERE epoch_ms BETWEEN ? AND ?", (start_ms, end_ms))
            total_rows = cur.fetchone()[0]
            step = max(1, total_rows // max_points) if total_rows > max_points else 1
            if step > 1:
                sql = f"""
                SELECT * FROM (
                    SELECT *, ROW_NUMBER() OVER (ORDER BY epoch_ms ASC) as rn
                    FROM {tbl}
                    WHERE epoch_ms BETWEEN ? AND ?
                ) WHERE (rn % ?) = 1
                ORDER BY epoch_ms ASC
                """
                cur.execute(sql, (start_ms, end_ms, step))
            else:
                cur.execute(
                    f"SELECT * FROM {tbl} WHERE epoch_ms BETWEEN ? AND ? ORDER BY epoch_ms ASC",
                    (start_ms, end_ms),
                )
            result[tbl] = [dict(r) for r in cur.fetchall()]
        return result
    finally:
        con.close()


def query_packets(
    start_ms: int,
    end_ms: int,
    topic_filter: str | None = None,
    payload_search: str | None = None,
    limit: int = 1000,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Query packets matching time range and filters, returning (rows, total_count)."""
    con = get_db_connection()
    try:
        cur = con.cursor()
        conditions = ["epoch_ms BETWEEN ? AND ?"]
        params: list[Any] = [start_ms, end_ms]

        if topic_filter and topic_filter != "all":
            if "#" in topic_filter:
                prefix = topic_filter.split("#")[0]
                conditions.append("topic LIKE ?")
                params.append(f"{prefix}%")
            else:
                conditions.append("topic = ?")
                params.append(topic_filter)

        if payload_search and payload_search.strip():
            conditions.append("payload LIKE ?")
            params.append(f"%{payload_search.strip()}%")

        where_clause = " AND ".join(conditions)

        # Count total matching
        count_sql = f"SELECT COUNT(*) FROM packets WHERE {where_clause}"
        cur.execute(count_sql, params)
        total_count = cur.fetchone()[0]

        # Fetch limited slice
        query_sql = f"""
        SELECT id, timestamp, epoch_ms, topic, payload, is_json
        FROM packets
        WHERE {where_clause}
        ORDER BY epoch_ms DESC
        LIMIT ? OFFSET ?
        """
        cur.execute(query_sql, params + [limit, offset])
        rows = [dict(r) for r in cur.fetchall()]
        return rows, total_count
    finally:
        con.close()


def execute_sql(query: str, limit: int = 5000) -> tuple[list[str], list[list[Any]], float]:
    """Execute raw user query safely in read-only mode, returning (columns, rows, elapsed_ms)."""
    start_time = time.perf_counter()
    con = get_db_connection()
    try:
        cur = con.cursor()
        cur.execute(query)
        columns = [col[0] for col in cur.description] if cur.description else []
        rows = cur.fetchmany(limit)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        return columns, [list(r) for r in rows], elapsed_ms
    finally:
        con.close()


class WorkerSignals(QObject):
    """Signals for background database query workers."""
    finished = pyqtSignal()
    error = pyqtSignal(str)
    result = pyqtSignal(object)


class DbQueryWorker(QRunnable):
    """Generic background QRunnable for off-thread DB queries."""

    def __init__(self, query_fn, *args, **kwargs):
        super().__init__()
        self.query_fn = query_fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self):
        try:
            res = self.query_fn(*self.args, **self.kwargs)
            self.signals.result.emit(res)
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()


def compute_max_gap(t_arr: np.ndarray) -> float:
    """Computes dynamic max allowable gap in seconds for telemetry continuity.
    Defaults to max(600.0, 3.0 * median_dt) (minimum 10 minutes, or 3x the typical sample interval).
    """
    if len(t_arr) <= 1:
        return 600.0
    dt = np.diff(t_arr)
    valid_dt = dt[dt > 0]
    median_dt = float(np.median(valid_dt)) if len(valid_dt) > 0 else 1.0
    return max(600.0, 3.0 * median_dt)


def compute_connect_array(
    t_arr: np.ndarray,
    y_arr: np.ndarray,
    max_gap: float | None = None,
) -> np.ndarray:
    """Computes a boolean/ubyte array for PyQtGraph's connect parameter.

    Connects adjacent points i and i+1 if and only if:
    1. Both y_arr[i] and y_arr[i+1] are finite (not NaN, None, or Inf).
    2. The time interval (t_arr[i+1] - t_arr[i]) <= max_gap.

    If max_gap is None, defaults dynamically to:
    max(600.0, 3.0 * median_dt) (minimum 10 minutes, or 3x the typical sample interval).
    """
    n = min(len(t_arr), len(y_arr))
    if n <= 1:
        return np.ones(n, dtype=np.ubyte)

    t = t_arr[:n]
    y = y_arr[:n]
    dt = np.diff(t)
    if max_gap is None:
        max_gap = compute_max_gap(t)

    finite_mask = np.isfinite(y)
    connect = np.zeros(n, dtype=np.ubyte)
    connect[:-1] = (dt <= max_gap).astype(np.ubyte) & finite_mask[:-1] & finite_mask[1:]
    return connect


