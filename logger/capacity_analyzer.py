#!/usr/bin/env python3
"""
Battery Actual Usable Capacity Estimation & Long-Term Degradation Analyzer.
Analyzes telemetry cycles in SQLite (paeraki.db) to measure true usable pack capacity (Ah),
compute State of Health (SoH %), and publish retained updates to MQTT.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.battery import calculate_voltage_soc
from dashboard.battery_12v import calculate_agm_voltage_soc

logger = logging.getLogger("paeraki.capacity_analyzer")


class CapacityAnalyzer:
    """
    Extracts qualified charge/discharge cycles from historical telemetry,
    calculates actual usable capacity C_actual = ΔQ / ΔSoC, and tracks degradation.
    """

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path).resolve()
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found at {self.db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def get_latest_capacity(self, pack_name: str) -> dict[str, Any] | None:
        """Fetches the latest recorded capacity estimation from battery_capacity_history."""
        with self._get_connection() as conn:
            row = conn.execute(
                """SELECT * FROM battery_capacity_history
                   WHERE pack_name = ?
                   ORDER BY epoch_ms DESC LIMIT 1""",
                (pack_name,),
            ).fetchone()
            if row:
                return dict(row)
        return None

    def analyze_72v(
        self,
        min_soc_swing: float = 0.30,
        min_rest_seconds: float = 900.0,
        alpha: float = 0.15,
        nameplate_ah: float = 200.0,
    ) -> list[dict[str, Any]]:
        """
        Analyzes 72V NMC telemetry from SQLite to identify valid charge/discharge cycles.
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                """SELECT epoch_ms, timestamp, total_voltage, current, temp_1, temp_2, rsoc
                   FROM telemetry_72v
                   WHERE total_voltage > 50.0
                   ORDER BY epoch_ms ASC"""
            ).fetchall()

        if len(rows) < 10:
            logger.info("Insufficient 72V data for capacity analysis (%d rows)", len(rows))
            return []

        # Previous learned capacity or default to nameplate
        latest = self.get_latest_capacity("72v_propulsion")
        c_learned = float(latest["estimated_capacity_ah"]) if latest else nameplate_ah

        results = []
        in_rest = False
        rest_samples: list[sqlite3.Row] = []
        anchor_1: dict[str, Any] | None = None
        flux_samples: list[sqlite3.Row] = []

        last_epoch = rows[0]["epoch_ms"] / 1000.0

        for r in rows:
            epoch = r["epoch_ms"] / 1000.0
            dt = epoch - last_epoch
            last_epoch = epoch
            if dt > 300.0:  # Data gap reset
                in_rest = False
                rest_samples.clear()
                anchor_1 = None
                flux_samples.clear()

            cur = float(r["current"] or 0.0)
            v = float(r["total_voltage"] or 0.0)

            # Condition 1: Low current resting
            if abs(cur) < 0.3:
                rest_samples.append(r)
                rest_duration = (r["epoch_ms"] - rest_samples[0]["epoch_ms"]) / 1000.0
                if rest_duration >= min_rest_seconds:
                    in_rest = True
                    avg_v = sum(float(x["total_voltage"]) for x in rest_samples) / len(rest_samples)
                    avg_t = sum(float(x["temp_1"] or 20.0) for x in rest_samples) / len(rest_samples)
                    soc_rest = calculate_voltage_soc(avg_v, current=0.0)
                    anchor = {
                        "epoch_ms": r["epoch_ms"],
                        "timestamp": r["timestamp"],
                        "avg_v": avg_v,
                        "soc": soc_rest / 100.0,
                        "avg_t": avg_t,
                    }

                    # If we had a previous anchor and accumulated flux, evaluate cycle
                    if anchor_1 is not None and flux_samples:
                        delta_soc = abs(anchor["soc"] - anchor_1["soc"])
                        delta_q = self._integrate_flux(flux_samples)
                        mean_temp = sum(float(x["temp_1"] or 20.0) for x in flux_samples) / len(flux_samples)

                        event = self._evaluate_cycle(
                            pack_name="72v_propulsion",
                            anchor_1=anchor_1,
                            anchor_2=anchor,
                            delta_q=delta_q,
                            delta_soc=delta_soc,
                            mean_temp=mean_temp,
                            min_soc_swing=min_soc_swing,
                            nameplate_ah=nameplate_ah,
                            c_learned_prev=c_learned,
                            alpha=alpha,
                        )
                        if event:
                            results.append(event)
                            c_learned = event["estimated_capacity_ah"]

                        flux_samples.clear()

                    anchor_1 = anchor
            else:
                # Dynamic active current
                in_rest = False
                rest_samples.clear()
                if anchor_1 is not None:
                    flux_samples.append(r)

        return results

    def analyze_12v(
        self,
        min_soc_swing: float = 0.25,
        min_rest_seconds: float = 900.0,
        alpha: float = 0.15,
        nameplate_ah: float = 100.0,
    ) -> list[dict[str, Any]]:
        """
        Analyzes 12V House AGM telemetry from SQLite to identify valid charge/discharge cycles.
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                """SELECT epoch_ms, timestamp, battery_voltage, battery_charge_current,
                          load_current, controller_temp, battery_temp, charging_status
                   FROM telemetry_12v
                   WHERE battery_voltage > 9.0
                   ORDER BY epoch_ms ASC"""
            ).fetchall()

        if len(rows) < 10:
            logger.info("Insufficient 12V data for capacity analysis (%d rows)", len(rows))
            return []

        latest = self.get_latest_capacity("12v_house")
        c_learned = float(latest["estimated_capacity_ah"]) if latest else nameplate_ah

        results = []
        rest_samples: list[sqlite3.Row] = []
        anchor_1: dict[str, Any] | None = None
        flux_samples: list[sqlite3.Row] = []
        last_epoch = rows[0]["epoch_ms"] / 1000.0

        for r in rows:
            epoch = r["epoch_ms"] / 1000.0
            dt = epoch - last_epoch
            last_epoch = epoch
            if dt > 300.0:
                rest_samples.clear()
                anchor_1 = None
                flux_samples.clear()

            chg_i = float(r["battery_charge_current"] or 0.0)
            load_i = float(r["load_current"] or 0.0)
            net_i = chg_i - load_i
            v = float(r["battery_voltage"] or 0.0)

            # Rest condition: |net_i| < 0.2A
            if abs(net_i) < 0.2:
                rest_samples.append(r)
                rest_duration = (r["epoch_ms"] - rest_samples[0]["epoch_ms"]) / 1000.0
                if rest_duration >= min_rest_seconds:
                    avg_v = sum(float(x["battery_voltage"]) for x in rest_samples) / len(rest_samples)
                    avg_t = sum(float(x["battery_temp"] or 20.0) for x in rest_samples) / len(rest_samples)
                    soc_rest = calculate_agm_voltage_soc(avg_v, net_current=0.0)
                    anchor = {
                        "epoch_ms": r["epoch_ms"],
                        "timestamp": r["timestamp"],
                        "avg_v": avg_v,
                        "soc": soc_rest / 100.0,
                        "avg_t": avg_t,
                    }

                    if anchor_1 is not None and flux_samples:
                        delta_soc = abs(anchor["soc"] - anchor_1["soc"])
                        delta_q = self._integrate_12v_flux(flux_samples)
                        mean_temp = sum(float(x["battery_temp"] or 20.0) for x in flux_samples) / len(flux_samples)

                        event = self._evaluate_cycle(
                            pack_name="12v_house",
                            anchor_1=anchor_1,
                            anchor_2=anchor,
                            delta_q=delta_q,
                            delta_soc=delta_soc,
                            mean_temp=mean_temp,
                            min_soc_swing=min_soc_swing,
                            nameplate_ah=nameplate_ah,
                            c_learned_prev=c_learned,
                            alpha=alpha,
                        )
                        if event:
                            results.append(event)
                            c_learned = event["estimated_capacity_ah"]

                        flux_samples.clear()

                    anchor_1 = anchor
            else:
                rest_samples.clear()
                if anchor_1 is not None:
                    flux_samples.append(r)

        return results

    def _integrate_flux(self, samples: list[sqlite3.Row]) -> float:
        """Trapezoidal / step integration of 72V current (Ah)."""
        delta_q = 0.0
        for i in range(1, len(samples)):
            dt = (samples[i]["epoch_ms"] - samples[i - 1]["epoch_ms"]) / 1000.0
            if 0 < dt <= 30.0:
                cur = float(samples[i]["current"] or 0.0)
                delta_q += cur * (dt / 3600.0)
        return delta_q

    def _integrate_12v_flux(self, samples: list[sqlite3.Row], eta_charge: float = 0.90) -> float:
        """Integration of 12V net current with charging coulombic efficiency."""
        delta_q = 0.0
        for i in range(1, len(samples)):
            dt = (samples[i]["epoch_ms"] - samples[i - 1]["epoch_ms"]) / 1000.0
            if 0 < dt <= 30.0:
                chg = float(samples[i]["battery_charge_current"] or 0.0)
                load = float(samples[i]["load_current"] or 0.0)
                net = (chg * eta_charge) - load
                delta_q += net * (dt / 3600.0)
        return delta_q

    def _evaluate_cycle(
        self,
        pack_name: str,
        anchor_1: dict[str, Any],
        anchor_2: dict[str, Any],
        delta_q: float,
        delta_soc: float,
        mean_temp: float,
        min_soc_swing: float,
        nameplate_ah: float,
        c_learned_prev: float,
        alpha: float,
    ) -> dict[str, Any] | None:
        """Filters cycle validity and computes learned capacity."""
        if delta_soc < min_soc_swing:
            return None

        # Absolute flux in Ah
        abs_q = abs(delta_q)
        if abs_q < (0.15 * nameplate_ah):
            return None

        c_raw = abs_q / delta_soc

        # Rejection bounds: 50% to 120% of nameplate
        if not (0.50 * nameplate_ah <= c_raw <= 1.20 * nameplate_ah):
            return None

        # Temperature filter (10°C to 38°C)
        if not (10.0 <= mean_temp <= 38.0):
            return None

        # Confidence calculation
        # Higher score for larger SoC delta and optimal temp (20-25°C)
        temp_factor = max(0.5, 1.0 - abs(mean_temp - 22.5) / 25.0)
        soc_factor = min(1.0, delta_soc / 0.70)
        confidence = round(float(temp_factor * soc_factor), 2)

        # Recursive filter
        c_learned = round((1.0 - alpha) * c_learned_prev + alpha * c_raw, 2)
        soh = round((c_learned / nameplate_ah) * 100.0, 1)

        return {
            "timestamp": anchor_2["timestamp"],
            "epoch_ms": anchor_2["epoch_ms"],
            "pack_name": pack_name,
            "estimated_capacity_ah": c_learned,
            "nameplate_capacity_ah": nameplate_ah,
            "soh_percentage": soh,
            "confidence_score": confidence,
            "cycle_delta_ah": round(abs_q, 2),
            "start_soc": round(anchor_1["soc"] * 100.0, 1),
            "end_soc": round(anchor_2["soc"] * 100.0, 1),
            "mean_temp": round(mean_temp, 1),
            "source": "cycle_analyzer",
            "notes": f"Cycle swing: {delta_soc * 100.0:.1f}%, C_raw: {c_raw:.1f} Ah",
        }

    def record_events(self, events: list[dict[str, Any]]) -> int:
        """Records identified capacity events into database."""
        if not events:
            return 0
        with self._get_connection() as conn:
            conn.executemany(
                """INSERT INTO battery_capacity_history (
                    timestamp, epoch_ms, pack_name, estimated_capacity_ah,
                    nameplate_capacity_ah, soh_percentage, confidence_score,
                    cycle_delta_ah, start_soc, end_soc, mean_temp,
                    source, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        e["timestamp"],
                        e["epoch_ms"],
                        e["pack_name"],
                        e["estimated_capacity_ah"],
                        e["nameplate_capacity_ah"],
                        e["soh_percentage"],
                        e.get("confidence_score"),
                        e.get("cycle_delta_ah"),
                        e.get("start_soc"),
                        e.get("end_soc"),
                        e.get("mean_temp"),
                        e.get("source", "cycle_analyzer"),
                        e.get("notes", ""),
                    )
                    for e in events
                ],
            )
            conn.commit()
        return len(events)


def publish_retained_mqtt(
    broker: str,
    port: int,
    pack_name: str,
    payload_dict: dict[str, Any],
) -> bool:
    """Publishes retained capacity JSON payload to MQTT."""
    try:
        import paho.mqtt.publish as publish
    except ImportError:
        logger.warning("paho-mqtt not available; cannot publish MQTT update")
        return False

    topic = f"paeraki/battery/{'72v' if '72v' in pack_name else '12v'}/capacity"
    payload_str = json.dumps(payload_dict)
    try:
        publish.single(
            topic,
            payload=payload_str,
            hostname=broker,
            port=port,
            retain=True,
            keepalive=10,
        )
        logger.info("Published retained capacity to %s: %s", topic, payload_str)
        return True
    except Exception as e:
        logger.error("Failed to publish retained capacity to MQTT: %s", e)
        return False


def main():
    parser = argparse.ArgumentParser(description="Paeraki Battery Usable Capacity & Degradation Analyzer")
    parser.add_argument("--db-path", default="/home/jh/paeraki/data/paeraki.db", help="Path to SQLite database")
    parser.add_argument("--pack", choices=["72v", "12v", "both"], default="both", help="Battery pack to analyze")
    parser.add_argument("--publish", action="store_true", help="Publish latest learned capacity to retained MQTT topic")
    parser.add_argument("--broker", default="192.168.1.1", help="MQTT Broker host for publishing")
    parser.add_argument("--port", type=int, default=1883, help="MQTT Broker port")
    parser.add_argument("--dry-run", action="store_true", help="Do not write events to DB or publish to MQTT")
    parser.add_argument("--status", action="store_true", help="Display current recorded capacity status and exit")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    analyzer = CapacityAnalyzer(args.db_path)

    if args.status:
        print("=== Paeraki Battery Capacity & Health Status ===")
        for pack in ("72v_propulsion", "12v_house"):
            rec = analyzer.get_latest_capacity(pack)
            if rec:
                print(f"Pack: {pack}")
                print(f"  Estimated Capacity: {rec['estimated_capacity_ah']:.1f} Ah / {rec['nameplate_capacity_ah']:.0f} Ah")
                print(f"  State of Health (SoH): {rec['soh_percentage']:.1f}%")
                print(f"  Last Calibration: {rec['timestamp']} (Source: {rec['source']})")
            else:
                nom = 200.0 if "72v" in pack else 100.0
                print(f"Pack: {pack} - No calibrated cycles recorded yet (Using nameplate: {nom:.0f} Ah, SoH: 100%)")
        sys.exit(0)

    all_events = []
    if args.pack in ("72v", "both"):
        logger.info("Analyzing 72V propulsion cycles...")
        events_72v = analyzer.analyze_72v()
        logger.info("Found %d qualified 72V capacity events", len(events_72v))
        all_events.extend(events_72v)

    if args.pack in ("12v", "both"):
        logger.info("Analyzing 12V house cycles...")
        events_12v = analyzer.analyze_12v()
        logger.info("Found %d qualified 12V capacity events", len(events_12v))
        all_events.extend(events_12v)

    if all_events:
        print(f"\nDiscovered {len(all_events)} qualified capacity calibration events:")
        for ev in all_events:
            print(
                f"[{ev['timestamp']}] {ev['pack_name']}: "
                f"{ev['estimated_capacity_ah']:.1f} Ah ({ev['soh_percentage']:.1f}% SoH), "
                f"Swing: {ev['start_soc']:.0f}%->{ev['end_soc']:.0f}%, "
                f"Conf: {ev['confidence_score']:.2f}"
            )

        if not args.dry_run:
            saved = analyzer.record_events(all_events)
            logger.info("Saved %d capacity events to %s", saved, args.db_path)

            if args.publish:
                # Publish latest for each pack
                latest_72 = [e for e in all_events if e["pack_name"] == "72v_propulsion"]
                if latest_72:
                    publish_retained_mqtt(args.broker, args.port, "72v_propulsion", latest_72[-1])
                latest_12 = [e for e in all_events if e["pack_name"] == "12v_house"]
                if latest_12:
                    publish_retained_mqtt(args.broker, args.port, "12v_house", latest_12[-1])
    else:
        logger.info("No new qualified capacity cycles found in current dataset (requires continuous charge/discharge swing >= 25-30%%).")


if __name__ == "__main__":
    main()
