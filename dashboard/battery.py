#!/usr/bin/env python3
"""
Battery State of Charge (SoC) Calculation and Coulomb Counting Integrator.
Designed for Paeraki's 72V Propulsion System (20S Nissan Leaf NMC Lithium-ion).
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("paeraki.battery")

# Standard Open Circuit Voltage (OCV) curve for Nissan Leaf AESC NMC pouch cells (20-25°C)
# Table of (cell_voltage, soc_percentage)
NISSAN_LEAF_NMC_OCV = [
    (4.20, 100.0),
    (4.15, 95.0),
    (4.10, 90.0),
    (4.05, 85.0),
    (3.98, 80.0),
    (3.92, 75.0),
    (3.87, 70.0),
    (3.82, 65.0),
    (3.78, 60.0),
    (3.74, 55.0),
    (3.71, 50.0),
    (3.68, 45.0),
    (3.65, 40.0),
    (3.62, 35.0),
    (3.59, 30.0),
    (3.54, 25.0),
    (3.48, 20.0),
    (3.40, 15.0),
    (3.30, 10.0),
    (3.15, 5.0),
    (3.00, 0.0),
]


def calculate_voltage_soc(
    pack_voltage: float,
    current: float = 0.0,
    cell_count: int = 20,
    r_pack: float = 0.030,
) -> float:
    """
    Computes State of Charge (SoC) % based on 20S Nissan Leaf NMC OCV curve.
    Applies IR compensation under load: V_ocv = V_terminal - (I * R_pack).
    """
    if pack_voltage <= 0 or cell_count <= 0:
        return 0.0

    # Compensate for internal resistance voltage drop under load/charge
    v_ocv = pack_voltage - (current * r_pack)
    v_cell = v_ocv / cell_count

    if v_cell >= NISSAN_LEAF_NMC_OCV[0][0]:
        return 100.0
    if v_cell <= NISSAN_LEAF_NMC_OCV[-1][0]:
        return 0.0

    for i in range(len(NISSAN_LEAF_NMC_OCV) - 1):
        v_high, soc_high = NISSAN_LEAF_NMC_OCV[i]
        v_low, soc_low = NISSAN_LEAF_NMC_OCV[i + 1]
        if v_low <= v_cell <= v_high:
            frac = (v_cell - v_low) / (v_high - v_low)
            soc = soc_low + frac * (soc_high - soc_low)
            return round(max(0.0, min(100.0, soc)), 1)

    return 0.0


class BatteryIntegrator:
    """
    Maintains continuous Coulomb integration (Ah) independent of BMS zero-drop faults.
    Resets to 100% capacity whenever BMS reported SoC reaches 100%.
    """

    def __init__(
        self,
        nominal_capacity_ah: float = 200.0,
        state_file: Path | str | None = None,
        seed_ah: float = 134.90,
    ):
        self.nominal_capacity_ah = nominal_capacity_ah
        self.integrated_ah = seed_ah
        self.state_file = Path(state_file) if state_file else None
        self.last_timestamp: float | None = None
        self.last_saved_time: float = 0.0
        self.cell_count = 20

        # Attempt to load persistent state
        self.load_state()

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
            last_ts_str = data.get("last_timestamp")
            if last_ts_str:
                self.last_timestamp = datetime.fromisoformat(last_ts_str).timestamp()
            logger.info("Loaded persisted battery integration: %.2f Ah / %.0f Ah", self.integrated_ah, self.nominal_capacity_ah)
        except Exception as e:
            logger.warning("Failed to load battery state from %s: %s", self.state_file, e)

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
                "last_timestamp": datetime.now(timezone.utc).isoformat(),
                "soc_integrated": round((self.integrated_ah / max(1.0, self.nominal_capacity_ah)) * 100.0, 1),
            }
            tmp_path = self.state_file.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp_path.replace(self.state_file)
            self.last_saved_time = now
        except Exception as e:
            logger.warning("Failed to save battery state to %s: %s", self.state_file, e)

    def update(
        self,
        current_a: float,
        timestamp_iso: str | None = None,
        bms_rsoc: float | None = None,
        pack_voltage: float | None = None,
        nominal_ah: float | None = None,
        cell_count: int | None = None,
    ) -> dict[str, Any]:
        """
        Integrates current over time.
        - current_a: amperes (positive for charging, negative for discharging).
        - bms_rsoc: raw BMS SoC (if >= 100, aligns integration to 100%).
        - pack_voltage: volts (used for voltage-based SoC calculation).
        """
        if nominal_ah and nominal_ah > 0:
            self.nominal_capacity_ah = nominal_ah
        if cell_count and cell_count > 0:
            self.cell_count = cell_count

        now_ts = (
            datetime.fromisoformat(timestamp_iso).timestamp()
            if timestamp_iso
            else datetime.now(timezone.utc).timestamp()
        )

        # Integrate Coulomb count
        if self.last_timestamp is not None:
            dt = now_ts - self.last_timestamp
            if 0 < dt < 60.0:  # ignore large gaps or backwards clock jumps
                delta_ah = current_a * (dt / 3600.0)
                self.integrated_ah += delta_ah
                self.integrated_ah = max(0.0, min(self.nominal_capacity_ah, self.integrated_ah))
        self.last_timestamp = now_ts

        # Periodic alignment rule:
        # "reset to 100% whenever the BMS reported SOC hits 100% so the two measures periodically align"
        if bms_rsoc is not None and float(bms_rsoc) >= 100.0:
            if self.integrated_ah < self.nominal_capacity_ah:
                logger.info("BMS reported 100%% SoC; aligning integrated capacity to %.1f Ah", self.nominal_capacity_ah)
            self.integrated_ah = self.nominal_capacity_ah

        # Calculate Voltage-based SoC
        soc_voltage = 0.0
        vcell_avg = 0.0
        if pack_voltage and pack_voltage > 0:
            vcell_avg = round(pack_voltage / self.cell_count, 3)
            soc_voltage = calculate_voltage_soc(
                pack_voltage=pack_voltage,
                current=current_a,
                cell_count=self.cell_count,
            )

        # Integrated SoC percentage
        soc_integrated = round(
            (self.integrated_ah / max(1.0, self.nominal_capacity_ah)) * 100.0, 1
        )
        soc_integrated = max(0.0, min(100.0, soc_integrated))

        # Check for discrepancy with BMS
        soc_bms = float(bms_rsoc) if bms_rsoc is not None else 0.0
        discrepancy = abs(soc_bms - soc_integrated) > 20.0 or abs(soc_bms - soc_voltage) > 20.0

        self.save_state()

        return {
            "soc_integrated": soc_integrated,
            "integrated_ah": round(self.integrated_ah, 2),
            "soc_voltage": soc_voltage,
            "vcell_avg": vcell_avg,
            "soc_bms": round(soc_bms, 1),
            "soc_discrepancy": discrepancy,
        }

    def recalibrate(self, ah: float | None = None, soc_pct: float | None = None):
        """Manually calibrate the integrated capacity to a given Ah or percentage."""
        if ah is not None:
            self.integrated_ah = max(0.0, min(self.nominal_capacity_ah, float(ah)))
        elif soc_pct is not None:
            self.integrated_ah = max(0.0, min(self.nominal_capacity_ah, (float(soc_pct) / 100.0) * self.nominal_capacity_ah))
        self.save_state(force=True)
        logger.info("Recalibrated battery integrator to %.2f Ah", self.integrated_ah)
