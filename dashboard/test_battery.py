#!/usr/bin/env python3
"""
Unit tests for Battery OCV modeling, Coulomb integration, and Dashboard state.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard.battery import BatteryIntegrator, calculate_voltage_soc
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

        assert abs(res["integrated_ah"] - 134.80) < 0.01
        assert res["soc_bms"] == 3.0
        assert res["soc_discrepancy"] is True  # BMS reported 3%, real is ~67%

        # Crucial test: simulate under-voltage event where BMS suddenly drops to 0.0 Ah / 0% RSOC
        t2 = "2026-09-10T08:00:12+00:00"
        res_trip = integrator.update(current_a=0.0, timestamp_iso=t2, bms_rsoc=0.0, pack_voltage=77.9)
        assert abs(res_trip["integrated_ah"] - 134.80) < 0.01, "Integrator must ignore BMS under-voltage 0% trip!"

        # Test periodic alignment rule:
        # "reset to 100% whenever the BMS reported SOC hits 100% so the two measures periodically align"
        t3 = "2026-09-10T08:30:00+00:00"
        res_full = integrator.update(current_a=0.2, timestamp_iso=t3, bms_rsoc=100.0, pack_voltage=83.8)
        assert res_full["integrated_ah"] == 200.0
        assert res_full["soc_integrated"] == 100.0
        assert res_full["soc_discrepancy"] is False

    finally:
        if state_file.exists():
            state_file.unlink()


def test_battery_integrator_persistence():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        state_file = Path(tf.name)

    try:
        b1 = BatteryIntegrator(nominal_capacity_ah=200.0, seed_ah=155.5, state_file=state_file)
        b1.save_state(force=True)

        # Load in a new instance
        b2 = BatteryIntegrator(nominal_capacity_ah=200.0, state_file=state_file)
        assert b2.integrated_ah == 155.5
    finally:
        if state_file.exists():
            state_file.unlink()


def test_dashboard_server_snapshot_and_calibration():
    # Test record packet
    test_packet = {
        "total_voltage": 79.64,
        "current": 0.0,
        "power": 0.0,
        "rsoc": 3.0,
        "residual_capacity_ah": 4.6,
        "nominal_capacity_ah": 200.0,
        "number_of_cells": 20,
        "timestamp": "2026-09-10T08:00:00+00:00",
    }
    server.state.record_packet("paeraki/72v/state", json.dumps(test_packet))
    snap = server.state.get_snapshot()["subsystems"]["72v"]

    assert snap["soc_voltage"] > 79.0
    assert snap["soc_bms"] == 3.0
    assert snap["soc_discrepancy"] is True

    # Test calibrate to voltage
    server.state.battery.recalibrate(soc_pct=snap["soc_voltage"])
    snap2 = server.state.battery.update(current_a=0.0, pack_voltage=79.64, bms_rsoc=3.0)
    assert abs(snap2["soc_integrated"] - snap["soc_voltage"]) < 0.5


if __name__ == "__main__":
    test_calculate_voltage_soc_nominal()
    print("✓ test_calculate_voltage_soc_nominal passed")
    test_calculate_voltage_soc_ir_compensation()
    print("✓ test_calculate_voltage_soc_ir_compensation passed")
    test_battery_integrator_coulomb_counting()
    print("✓ test_battery_integrator_coulomb_counting passed")
    test_battery_integrator_persistence()
    print("✓ test_battery_integrator_persistence passed")
    test_dashboard_server_snapshot_and_calibration()
    print("✓ test_dashboard_server_snapshot_and_calibration passed")
    print("\nAll 5 battery unit tests PASSED successfully!")
