#!/usr/bin/env python3
"""
Unit tests for Battery OCV modeling, Coulomb integration, 12V AGM modeling, and Dashboard state.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard.battery import BatteryIntegrator, calculate_voltage_soc
from dashboard.battery_12v import HouseBatteryIntegrator, calculate_agm_voltage_soc
import dashboard.server as server


def test_calculate_voltage_soc_nominal():
    # 20S Pack: 79.64 V -> 3.982 V/cell -> ~80%
    soc = calculate_voltage_soc(79.64)
    assert 79.0 <= soc <= 81.0, f"Expected ~80% SoC at 79.64V, got {soc}"

    # Full charge (84.0 V = 4.20 V/cell)
    assert calculate_voltage_soc(84.0) == 100.0
    assert calculate_voltage_soc(85.0) == 100.0

    # Dead pack (60.0 V = 3.00 V/cell)
    assert calculate_voltage_soc(60.0) == 0.0
    assert calculate_voltage_soc(55.0) == 0.0

    # Nominal 50% (74.2 V = 3.71 V/cell)
    soc_50 = calculate_voltage_soc(74.2)
    assert 49.0 <= soc_50 <= 51.0, f"Expected ~50% at 74.2V, got {soc_50}"


def test_calculate_voltage_soc_ir_compensation():
    # At 79.64V resting: ~80.1%
    resting_soc = calculate_voltage_soc(79.64, current=0.0)

    # Under -50A discharge, terminal voltage sags by ~1.5V (78.14V):
    # With IR compensation, calculated OCV should recover ~79.64V and match resting SoC
    loaded_soc = calculate_voltage_soc(78.14, current=-50.0)
    assert abs(resting_soc - loaded_soc) < 0.5, f"Loaded SoC {loaded_soc} should match resting {resting_soc}"


def test_battery_integrator_coulomb_counting():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        state_file = Path(tf.name)

    try:
        integrator = BatteryIntegrator(nominal_capacity_ah=200.0, seed_ah=134.90, state_file=state_file)
        assert integrator.integrated_ah == 134.90

        # Simulate 10 seconds of 36A discharge:
        # delta_Ah = -36 * 10 / 3600 = -0.10 Ah
        t0 = "2026-09-10T08:00:00+00:00"
        t1 = "2026-09-10T08:00:10+00:00"

        integrator.update(current_a=0.0, timestamp_iso=t0, bms_rsoc=3.0, pack_voltage=79.64)
        res = integrator.update(current_a=-36.0, timestamp_iso=t1, bms_rsoc=3.0, pack_voltage=77.5)

        assert abs(integrator.integrated_ah - 134.80) < 0.01, f"Expected 134.80 Ah, got {integrator.integrated_ah}"
        assert res["soc_integrated"] == round((134.80 / 200.0) * 100.0, 1)

        # Test BMS reset: when bms_rsoc reaches 100%, reset integration to 100% capacity
        integrator.update(current_a=5.0, timestamp_iso="2026-09-10T08:00:20+00:00", bms_rsoc=100.0, pack_voltage=83.5)
        assert integrator.integrated_ah == 200.0
    finally:
        if state_file.exists():
            state_file.unlink()


def test_battery_integrator_persistence():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        state_file = Path(tf.name)

    try:
        b1 = BatteryIntegrator(nominal_capacity_ah=200.0, seed_ah=155.5, state_file=state_file)
        b1.save_state(force=True)

        # Verify file written
        assert state_file.exists()
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data["integrated_ah"] == 155.5
        assert data["nominal_capacity_ah"] == 200.0

        # Load in a new instance
        b2 = BatteryIntegrator(nominal_capacity_ah=200.0, state_file=state_file)
        assert b2.integrated_ah == 155.5
    finally:
        if state_file.exists():
            state_file.unlink()


def test_12v_agm_soc_nominal():
    # 12.85V -> 100%
    assert calculate_agm_voltage_soc(12.85) == 100.0
    assert calculate_agm_voltage_soc(13.20) == 100.0

    # 12.15V -> 50%
    assert calculate_agm_voltage_soc(12.15) == 50.0

    # 10.80V -> 0%
    assert calculate_agm_voltage_soc(10.80) == 0.0
    assert calculate_agm_voltage_soc(10.50) == 0.0

    # 12.60V -> 80%
    assert calculate_agm_voltage_soc(12.60) == 80.0

    # IR compensation under 10A solar charge:
    # V_terminal = 12.90V, I = 10A, R_int = 0.015 -> V_ocv = 12.90 - 0.15 = 12.75V (90%)
    soc_chg = calculate_agm_voltage_soc(12.90, current=10.0, r_int=0.015)
    assert abs(soc_chg - 90.0) < 0.5


def test_house_battery_integrator():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        state_file = Path(tf.name)

    try:
        integrator = HouseBatteryIntegrator(nominal_capacity_ah=100.0, seed_ah=60.0, state_file=state_file)
        assert integrator.integrated_ah == 60.0

        # Solar charging at 10A, load 2A -> Net current = +8A for 1 hour (3600s)
        # Efficiency = 0.90 -> delta_Ah = 8 * 1 * 0.90 = +7.2 Ah
        t0 = "2026-09-14T08:00:00+00:00"
        t1 = "2026-09-14T09:00:00+00:00"

        integrator.update(charge_current_a=10.0, load_current_a=2.0, batt_voltage=13.2, timestamp_iso=t0)
        res = integrator.update(charge_current_a=10.0, load_current_a=2.0, batt_voltage=13.4, timestamp_iso=t1)

        assert abs(integrator.integrated_ah - 67.2) < 0.05
        assert res["soc_12v_integrated"] == 67.2

        # Test Float Mode calibration: transitions to Float mode -> sync to 100%
        res_float = integrator.update(
            charge_current_a=0.8,
            load_current_a=0.0,
            batt_voltage=13.7,
            timestamp_iso="2026-09-14T10:00:00+00:00",
            charging_status="Float",
        )
        assert integrator.integrated_ah == 100.0
        assert res_float["soc_12v_integrated"] == 100.0
        assert res_float["is_12v_calibrated"] is True
    finally:
        if state_file.exists():
            state_file.unlink()


def test_dashboard_server_snapshot_and_calibration():
    # Test record 72V packet
    test_72v = {
        "total_voltage": 79.64,
        "current": 0.0,
        "power": 0.0,
        "rsoc": 3.0,
        "residual_capacity_ah": 4.6,
        "nominal_capacity_ah": 200.0,
        "number_of_cells": 20,
        "timestamp": "2026-09-10T08:00:00+00:00",
    }
    server.state.record_packet("paeraki/72v/state", json.dumps(test_72v))
    snap = server.state.get_snapshot()["subsystems"]["72v"]

    assert snap["soc_voltage"] > 79.0
    assert snap["soc_bms"] == 3.0
    assert snap["soc_discrepancy"] is True

    # Test record 12V packet
    test_12v = {
        "battery_voltage": 12.75,
        "battery_soc": 100,
        "battery_charge_current": 4.0,
        "load_current": 1.0,
        "solar_power": 55.0,
        "daily_yield_kwh": 1.25,
        "charging_status": "Boost MPPT",
        "controller_temperature": 19,
        "battery_temperature": 23,
        "timestamp": "2026-09-14T08:00:00+00:00",
    }
    server.state.record_packet("paeraki/12v/state", json.dumps(test_12v))
    snap_12v = server.state.get_snapshot()["subsystems"]["12v"]

    assert snap_12v["battery_voltage"] == 12.75
    assert snap_12v["charging_status"] == "Boost MPPT"
    assert 86.0 <= snap_12v["soc_12v_voltage"] <= 91.0
    assert snap_12v["controller_temperature"] == 19
    assert snap_12v["battery_temperature"] == 23


def test_dynamic_capacity_and_soh_mqtt():
    # 72V capacity retained message
    cap_72v_msg = {
        "pack_name": "72v_propulsion",
        "estimated_capacity_ah": 178.4,
        "nameplate_capacity_ah": 200.0,
        "soh_percentage": 89.2,
        "confidence_score": 0.95,
        "source": "cycle_analyzer",
    }
    server.state.record_packet("paeraki/battery/72v/capacity", json.dumps(cap_72v_msg))
    snap_72v = server.state.get_snapshot()["subsystems"]["72v"]
    assert snap_72v["nominal_capacity_ah"] == 178.4
    assert snap_72v["soh_percentage"] == 89.2
    assert server.state.battery.nominal_capacity_ah == 178.4
    assert server.state.battery.soh_percentage == 89.2

    # 12V capacity retained message
    cap_12v_msg = {
        "pack_name": "12v_house",
        "estimated_capacity_ah": 91.5,
        "nameplate_capacity_ah": 100.0,
        "soh_percentage": 91.5,
        "confidence_score": 0.90,
        "source": "cycle_analyzer",
    }
    server.state.record_packet("paeraki/battery/12v/capacity", json.dumps(cap_12v_msg))
    snap_12v = server.state.get_snapshot()["subsystems"]["12v"]
    assert snap_12v["nominal_capacity_ah"] == 91.5
    assert snap_12v["soh_percentage"] == 91.5
    assert server.state.battery_12v.nominal_capacity_ah == 91.5
    assert server.state.battery_12v.soh_percentage == 91.5


def test_alarm_engine_and_low_12v_rule():
    from alarms.rules import AlarmEngine, Low12VCapacityRule, AlarmState

    rule = Low12VCapacityRule(debounce_sec=0.0)
    engine = AlarmEngine([rule])

    # 1. Normal state (80% SoC)
    engine.update_telemetry("12v", {"battery_voltage": 12.65, "soc_12v_active": 80.0})
    events = engine.evaluate()
    assert len(events) == 0
    assert rule.state == AlarmState.OK
    assert engine.get_status()["overall_status"] == "OK"

    # 2. Low 12V state (48% SoC -> below 50% threshold)
    engine.update_telemetry("12v", {"battery_voltage": 12.10, "soc_12v_active": 48.0})
    events = engine.evaluate()
    assert len(events) == 1
    assert events[0].rule_name == "low_12v_house_battery"
    assert events[0].severity == "WARNING"
    assert rule.state == AlarmState.ALARM
    assert engine.get_status()["overall_status"] == "WARNING"

    # 3. Critical drop (36% SoC -> below 40% threshold)
    engine.update_telemetry("12v", {"battery_voltage": 11.90, "soc_12v_active": 36.0})
    events = engine.evaluate()
    assert len(events) == 1
    assert events[0].severity == "CRITICAL"
    assert engine.get_status()["overall_status"] == "CRITICAL"

    # 4. Partial recovery (52% SoC -> not yet at 55% hysteresis recovery threshold)
    engine.update_telemetry("12v", {"battery_voltage": 12.30, "soc_12v_active": 52.0})
    events = engine.evaluate()
    assert len(events) == 0
    assert rule.state == AlarmState.ALARM

    # 5. Full recovery (58% SoC -> >= 55% recovery threshold)
    engine.update_telemetry("12v", {"battery_voltage": 13.20, "soc_12v_active": 58.0})
    events = engine.evaluate()
    assert len(events) == 1
    assert events[0].state == "OK"
    assert "recovered" in events[0].message.lower()
    assert rule.state == AlarmState.OK
    assert engine.get_status()["overall_status"] == "OK"


if __name__ == "__main__":
    test_calculate_voltage_soc_nominal()
    print("✓ test_calculate_voltage_soc_nominal passed")
    test_calculate_voltage_soc_ir_compensation()
    print("✓ test_calculate_voltage_soc_ir_compensation passed")
    test_battery_integrator_coulomb_counting()
    print("✓ test_battery_integrator_coulomb_counting passed")
    test_battery_integrator_persistence()
    print("✓ test_battery_integrator_persistence passed")
    test_12v_agm_soc_nominal()
    print("✓ test_12v_agm_soc_nominal passed")
    test_house_battery_integrator()
    print("✓ test_house_battery_integrator passed")
    test_dashboard_server_snapshot_and_calibration()
    print("✓ test_dashboard_server_snapshot_and_calibration passed")
    test_dynamic_capacity_and_soh_mqtt()
    print("✓ test_dynamic_capacity_and_soh_mqtt passed")
    test_alarm_engine_and_low_12v_rule()
    print("✓ test_alarm_engine_and_low_12v_rule passed")
    print("\nAll 9 battery, capacity, dashboard, and alarm unit tests PASSED successfully!")
