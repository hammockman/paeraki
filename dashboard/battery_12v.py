#!/usr/bin/env python3
"""
Battery State of Charge (SoC) Calculation and Charge Flux Integrator.
Designed for Paeraki's 12V House Battery System (AGM Lead-Acid).
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("paeraki.battery_12v")

# Standard Open Circuit Voltage (OCV) curve for 12V AGM lead-acid battery at rest (20-25°C)
# Table of (terminal_voltage, soc_percentage)
AGM_12V_OCV = [
    (12.85, 100.0),
    (12.75, 90.0),
    (12.60, 80.0),
    (12.45, 70.0),
    (12.30, 60.0),
    (12.15, 50.0),  # Recommended maximum depth of discharge for AGM
    (12.00, 40.0),
    (11.75, 20.0),
    (10.80, 0.0),
]


def calculate_agm_voltage_soc(
    batt_voltage: float,
    current: float = 0.0,
    r_int: float = 0.015,
    net_current: float | None = None,
) -> float:
    """
    Computes State of Charge (SoC) % based on standard 12V AGM OCV curve.
    Applies IR drop compensation under load/charge: V_ocv = V_terminal - (I * R_int).
    Positive current = charging (increases terminal V); Negative current = discharging.
    """
    if net_current is not None:
        current = net_current
    if batt_voltage <= 0:
        return 0.0

    # Compensate for internal resistance voltage shift
    v_ocv = batt_voltage - (current * r_int)

    if v_ocv >= AGM_12V_OCV[0][0]:
        return 100.0
    if v_ocv <= AGM_12V_OCV[-1][0]:
        return 0.0

    for i in range(len(AGM_12V_OCV) - 1):
        v_high, soc_high = AGM_12V_OCV[i]
        v_low, soc_low = AGM_12V_OCV[i + 1]
        if v_low <= v_ocv <= v_high:
            frac = (v_ocv - v_low) / (v_high - v_low)
            soc = soc_low + frac * (soc_high - soc_low)
            return round(max(0.0, min(100.0, soc)), 1)

    return 0.0


class HouseBatteryIntegrator:
    """
    Maintains continuous Coulomb integration (Ah) and SoC estimation for 12V AGM house battery.
    Accounts for solar charge flux and DC load consumption reported by SRNE controller.
    Calibrates to 100% when controller reaches Float mode.
    """

    def __init__(
        self,
        nominal_capacity_ah: float = 100.0,
        state_file: Path | str | None = None,
        seed_ah: float | None = None,
    ):
        self.nominal_capacity_ah = nominal_capacity_ah
        self.integrated_ah: float | None = seed_ah
        self.state_file = Path(state_file) if state_file else None
        self.last_timestamp: float | None = None
        self.last_saved_time: float = 0.0
        self.nameplate_capacity_ah = 100.0
        self.soh_percentage = round((self.nominal_capacity_ah / self.nameplate_capacity_ah) * 100.0, 1)
        self.r_int = 0.015
        self.charge_efficiency = 0.90  # Typical coulombic efficiency for AGM charging
        self.quiescent_start_time: float | None = None
        self.is_calibrated = False

        # Attempt to load persistent state
        self.load_state()

    def set_capacity(self, new_capacity_ah: float, soh_pct: float | None = None):
        """Updates nominal capacity dynamically (e.g. from learned degradation) preserving ratio."""
        if new_capacity_ah <= 10.0:
            return
        ratio = self.integrated_ah / max(1.0, self.nominal_capacity_ah)
        self.nominal_capacity_ah = float(new_capacity_ah)
        self.integrated_ah = min(self.nominal_capacity_ah, ratio * self.nominal_capacity_ah)
        if soh_pct is not None:
            self.soh_percentage = float(soh_pct)
        else:
            self.soh_percentage = round((self.nominal_capacity_ah / self.nameplate_capacity_ah) * 100.0, 1)
        self.save_state(force=True)
        logger.info("Updated 12V nominal capacity to %.1f Ah (SoH: %.1f%%)", self.nominal_capacity_ah, self.soh_percentage)

    def load_state(self):
        """Loads previously saved integration state from disk if available."""
        if not self.state_file or not self.state_file.exists():
            return
        try:
            if self.state_file.stat().st_size == 0:
                return
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            saved_ah = float(data.get("integrated_ah", self.integrated_ah))
            self.nominal_capacity_ah = float(data.get("nominal_capacity_ah", self.nominal_capacity_ah))
            self.integrated_ah = max(0.0, min(self.nominal_capacity_ah, saved_ah))
            if "soh_percentage" in data:
                self.soh_percentage = float(data["soh_percentage"])
            else:
                self.soh_percentage = round((self.nominal_capacity_ah / self.nameplate_capacity_ah) * 100.0, 1)
            self.is_calibrated = bool(data.get("is_calibrated", False))
            last_ts_str = data.get("last_timestamp")
            if last_ts_str:
                self.last_timestamp = datetime.fromisoformat(last_ts_str).timestamp()
            logger.info(
                "Loaded persisted 12V battery integration: %.2f Ah / %.0f Ah",
                self.integrated_ah,
                self.nominal_capacity_ah,
            )
        except Exception as e:
            logger.warning("Failed to load 12V battery state from %s: %s", self.state_file, e)

    def save_state(self, force: bool = False):
        """Saves integration state to disk at most every 15 seconds unless forced."""
        if not self.state_file:
            return
        now = datetime.now(timezone.utc).timestamp()
        if not force and (now - self.last_saved_time < 15.0):
            return

        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "integrated_ah": round(self.integrated_ah, 3),
                "nominal_capacity_ah": round(self.nominal_capacity_ah, 1),
                "nameplate_capacity_ah": round(self.nameplate_capacity_ah, 1),
                "soh_percentage": round(self.soh_percentage, 1),
                "last_timestamp": datetime.now(timezone.utc).isoformat(),
                "soc_integrated": round((self.integrated_ah / max(1.0, self.nominal_capacity_ah)) * 100.0, 1),
                "is_calibrated": self.is_calibrated,
            }
            tmp_path = self.state_file.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp_path.replace(self.state_file)
            self.last_saved_time = now
        except Exception as e:
            logger.warning("Failed to save 12V battery state to %s: %s", self.state_file, e)

    def update(
        self,
        charge_current_a: float,
        load_current_a: float,
        batt_voltage: float,
        timestamp_iso: str,
        charging_status: str = "",
    ) -> dict[str, Any]:
        """
        Processes a telemetry tick, performs flux integration, and returns SoC metrics.
        """
        # Net current into the battery (positive = net charging, negative = net discharging)
        net_current = charge_current_a - load_current_a

        try:
            current_time = datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            current_time = datetime.now(timezone.utc).timestamp()

        # Voltage-based SoC
        v_soc = calculate_agm_voltage_soc(batt_voltage, current=net_current, r_int=self.r_int)

        # First reading initialization
        if self.last_timestamp is None:
            self.last_timestamp = current_time
            if self.integrated_ah is None:
                self.integrated_ah = (v_soc / 100.0) * self.nominal_capacity_ah
            return self._build_result(v_soc, net_current)

        dt = current_time - self.last_timestamp
        self.last_timestamp = current_time

        # Ignore anomalous time steps (reboots, long pauses > 1 hour)
        if 0 < dt <= 3600:
            if net_current > 0:
                # Charging: apply coulombic efficiency
                ah_delta = (net_current * dt / 3600.0) * self.charge_efficiency
            else:
                # Discharging
                ah_delta = (net_current * dt / 3600.0)

            self.integrated_ah += ah_delta
            self.integrated_ah = max(0.0, min(self.nominal_capacity_ah, self.integrated_ah))

        # Check for Full-Charge Calibration Anchor (Float Mode)
        # SRNE enters Float mode when absorption phase is complete and current tapers
        status_clean = (charging_status or "").strip().lower()
        is_float_mode = "float" in status_clean
        is_full_voltage = (batt_voltage >= 13.6 and charge_current_a < 1.0 and net_current >= 0)

        if is_float_mode or is_full_voltage:
            if not self.is_calibrated or self.integrated_ah < self.nominal_capacity_ah * 0.98:
                logger.info("12V Battery reached Float/Full charge (%.2fV). Syncing to 100%%", batt_voltage)
            self.integrated_ah = self.nominal_capacity_ah
            self.is_calibrated = True

        # Check for Quiescent Resting State (Anchor 1)
        # If net current is near zero (|I| < 0.2A) continuously for >= 15 minutes,
        # terminal voltage accurately reflects resting OCV.
        if abs(net_current) < 0.2:
            if self.quiescent_start_time is None:
                self.quiescent_start_time = current_time
            elif (current_time - self.quiescent_start_time) >= 900.0:  # 15 mins
                target_ah = (v_soc / 100.0) * self.nominal_capacity_ah
                # Smoothly blend integrated Ah toward resting OCV Ah (10% step per minute)
                blend_factor = min(1.0, (dt / 60.0) * 0.10)
                self.integrated_ah = (1.0 - blend_factor) * self.integrated_ah + blend_factor * target_ah
                self.is_calibrated = True
        else:
            self.quiescent_start_time = None

        self.save_state(force=False)
        return self._build_result(v_soc, net_current)

    def _build_result(self, v_soc: float, net_current: float) -> dict[str, Any]:
        int_ah = self.integrated_ah if self.integrated_ah is not None else ((v_soc / 100.0) * self.nominal_capacity_ah)
        int_soc = round((int_ah / max(1.0, self.nominal_capacity_ah)) * 100.0, 1)
        int_soc = max(0.0, min(100.0, int_soc))

        return {
            "soc_12v_integrated": int_soc,
            "soc_12v_voltage": v_soc,
            "soc_12v_active": int_soc if self.is_calibrated else v_soc,
            "integrated_12v_ah": round(int_ah, 2),
            "nominal_12v_capacity_ah": round(self.nominal_capacity_ah, 1),
            "soh_12v_percentage": round(self.soh_percentage, 1),
            "net_12v_current": round(net_current, 2),
            "is_12v_calibrated": self.is_calibrated,
        }
