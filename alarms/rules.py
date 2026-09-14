#!/usr/bin/env python3
"""
Vessel Alarm Rules Engine for Paeraki.
Implements state transitions, debouncing, hysteresis recovery, and rate-limiting
for multi-channel vessel telemetry alerting.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.battery import calculate_voltage_soc
from dashboard.battery_12v import calculate_agm_voltage_soc

logger = logging.getLogger("paeraki.alarms.rules")


class AlarmSeverity(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlarmState(str, enum.Enum):
    OK = "OK"
    ALARM = "ALARM"
    ACKNOWLEDGED = "ACKNOWLEDGED"


@dataclass
class AlarmEvent:
    rule_name: str
    severity: str
    state: str
    message: str
    timestamp: str
    epoch_ms: int
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AlarmRule:
    """Base class for all Paeraki vessel telemetry alarm rules."""

    def __init__(
        self,
        name: str,
        description: str,
        severity: AlarmSeverity = AlarmSeverity.WARNING,
        debounce_sec: float = 10.0,
        cooldown_sec: float = 21600.0,  # 6 hours default cooldown for repeat alerts
    ):
        self.name = name
        self.description = description
        self.default_severity = severity
        self.current_severity = severity
        self.debounce_sec = debounce_sec
        self.cooldown_sec = cooldown_sec

        self.state: AlarmState = AlarmState.OK
        self.condition_start_time: float | None = None
        self.last_notification_time: float = 0.0
        self.last_event: AlarmEvent | None = None

    def evaluate_condition(self, snapshot: dict[str, Any]) -> tuple[bool, AlarmSeverity, str, dict[str, Any]]:
        """
        Returns (is_active, severity, message, metrics).
        Must be implemented by subclasses.
        """
        raise NotImplementedError

    def evaluate_recovery(self, snapshot: dict[str, Any]) -> tuple[bool, str]:
        """
        Returns (is_recovered, message).
        Must be implemented by subclasses to provide hysteresis.
        """
        raise NotImplementedError

    def update(self, snapshot: dict[str, Any], now_epoch: float | None = None) -> AlarmEvent | None:
        """
        Processes snapshot against rule logic, handles debouncing & hysteresis,
        and returns an AlarmEvent on state transition or notification trigger.
        """
        now = now_epoch if now_epoch is not None else datetime.now(timezone.utc).timestamp()
        iso_now = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
        epoch_ms = int(now * 1000)

        is_active, severity, msg, metrics = self.evaluate_condition(snapshot)

        if self.state == AlarmState.OK:
            if is_active:
                if self.condition_start_time is None:
                    self.condition_start_time = now

                # Check if debounce window has elapsed
                if (now - self.condition_start_time) >= self.debounce_sec:
                    self.state = AlarmState.ALARM
                    self.current_severity = severity
                    self.last_notification_time = now

                    event = AlarmEvent(
                        rule_name=self.name,
                        severity=severity.value,
                        state=self.state.value,
                        message=msg,
                        timestamp=iso_now,
                        epoch_ms=epoch_ms,
                        metrics=metrics,
                    )
                    self.last_event = event
                    logger.warning("ALARM TRIGGERED [%s]: %s (Severity: %s)", self.name, msg, severity.value)
                    return event
            else:
                self.condition_start_time = None

        elif self.state in (AlarmState.ALARM, AlarmState.ACKNOWLEDGED):
            is_recovered, recovery_msg = self.evaluate_recovery(snapshot)

            if is_recovered:
                self.state = AlarmState.OK
                self.condition_start_time = None
                self.current_severity = self.default_severity

                event = AlarmEvent(
                    rule_name=self.name,
                    severity=AlarmSeverity.INFO.value,
                    state=self.state.value,
                    message=f"CLEARED: {recovery_msg}",
                    timestamp=iso_now,
                    epoch_ms=epoch_ms,
                    metrics=metrics,
                )
                self.last_event = event
                logger.info("ALARM CLEARED [%s]: %s", self.name, recovery_msg)
                return event

            # If severity escalated from WARNING to CRITICAL, notify immediately
            if severity == AlarmSeverity.CRITICAL and self.current_severity != AlarmSeverity.CRITICAL:
                self.current_severity = AlarmSeverity.CRITICAL
                self.last_notification_time = now

                event = AlarmEvent(
                    rule_name=self.name,
                    severity=severity.value,
                    state=self.state.value,
                    message=f"ESCALATED: {msg}",
                    timestamp=iso_now,
                    epoch_ms=epoch_ms,
                    metrics=metrics,
                )
                self.last_event = event
                logger.warning("ALARM ESCALATED [%s]: %s", self.name, msg)
                return event

            # Check repeat notification cooldown
            if (now - self.last_notification_time) >= self.cooldown_sec:
                self.last_notification_time = now
                event = AlarmEvent(
                    rule_name=self.name,
                    severity=self.current_severity.value,
                    state=self.state.value,
                    message=f"REMINDER: {msg}",
                    timestamp=iso_now,
                    epoch_ms=epoch_ms,
                    metrics=metrics,
                )
                self.last_event = event
                return event

        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "state": self.state.value,
            "severity": self.current_severity.value,
            "last_notification_time": self.last_notification_time,
            "last_event": self.last_event.to_dict() if self.last_event else None,
        }


class Low12VCapacityRule(AlarmRule):
    """
    Alerts when 12V House AGM battery capacity drops to or below 50.0% DoD limit.
    Clears with hysteresis when SoC recovers to >= 55.0%.
    """

    def __init__(
        self,
        soc_threshold: float = 50.0,
        recovery_threshold: float = 55.0,
        critical_threshold: float = 40.0,
        debounce_sec: float = 10.0,
        cooldown_sec: float = 21600.0,  # 6 hours
    ):
        super().__init__(
            name="low_12v_house_battery",
            description="12V AGM House Battery reached 50% Depth of Discharge limit",
            severity=AlarmSeverity.WARNING,
            debounce_sec=debounce_sec,
            cooldown_sec=cooldown_sec,
        )
        self.soc_threshold = soc_threshold
        self.recovery_threshold = recovery_threshold
        self.critical_threshold = critical_threshold

    def _extract_12v_metrics(self, snapshot: dict[str, Any]) -> tuple[float | None, float | None]:
        sys_12v = snapshot.get("12v", {})
        v = sys_12v.get("battery_voltage")
        try:
            v_f = float(v) if v is not None else None
        except (ValueError, TypeError):
            v_f = None

        soc = sys_12v.get("soc_12v_active")
        if soc is None:
            soc = sys_12v.get("soc_12v_integrated")
        if soc is None:
            soc = sys_12v.get("soc_12v_voltage")
        if soc is None and v_f is not None:
            soc = calculate_agm_voltage_soc(v_f)
        if soc is None:
            soc = sys_12v.get("battery_soc")

        try:
            soc_f = float(soc) if soc is not None else None
        except (ValueError, TypeError):
            soc_f = None

        # Cross-validation with voltage: 12.30V on AGM is ~65-70% SoC.
        if v_f is not None and v_f >= 12.30 and (soc_f is None or soc_f <= self.soc_threshold):
            v_soc = calculate_agm_voltage_soc(v_f)
            if v_soc is not None:
                soc_f = v_soc

        return soc_f, v_f

    def evaluate_condition(self, snapshot: dict[str, Any]) -> tuple[bool, AlarmSeverity, str, dict[str, Any]]:
        soc, v = self._extract_12v_metrics(snapshot)
        if soc is None and v is None:
            return False, AlarmSeverity.WARNING, "", {}

        # Voltage guard: 12.30V AGM is healthy. Do not alarm if voltage >= 12.30V.
        if v is not None and v >= 12.30:
            return False, AlarmSeverity.WARNING, "", {"soc": soc, "voltage": v}

        # 50% AGM resting OCV is ~12.15V
        is_low_soc = soc is not None and soc <= self.soc_threshold
        is_low_v = v is not None and v <= 12.15

        if is_low_soc or is_low_v:
            severity = AlarmSeverity.CRITICAL if (soc is not None and soc <= self.critical_threshold) else AlarmSeverity.WARNING
            v_str = f"{v:.2f}V" if v is not None else "--.-V"
            soc_str = f"{soc:.1f}%" if soc is not None else "--.-%"
            msg = f"12V House Battery capacity at {soc_str} ({v_str}) - below 50% limit"
            return True, severity, msg, {"soc": soc, "voltage": v}

        return False, AlarmSeverity.WARNING, "", {"soc": soc, "voltage": v}

    def evaluate_recovery(self, snapshot: dict[str, Any]) -> tuple[bool, str]:
        soc, v = self._extract_12v_metrics(snapshot)
        if soc is None and v is None:
            return False, ""

        # Recovers when SoC >= 55% or voltage >= 12.40V
        recovered_soc = soc is not None and soc >= self.recovery_threshold
        recovered_v = v is not None and v >= 12.40

        if recovered_soc or recovered_v:
            soc_str = f"{soc:.1f}%" if soc is not None else "--.-%"
            v_str = f"{v:.2f}V" if v is not None else "--.-V"
            return True, f"12V House Battery recovered to {soc_str} ({v_str})"

        return False, ""


class Low72VBatteryRule(AlarmRule):
    """Alerts when 72V Propulsion battery drops to or below 20.0%."""

    def __init__(
        self,
        soc_threshold: float = 20.0,
        recovery_threshold: float = 25.0,
        critical_threshold: float = 10.0,
        debounce_sec: float = 10.0,
        cooldown_sec: float = 14400.0,  # 4 hours
    ):
        super().__init__(
            name="low_72v_propulsion_battery",
            description="72V Propulsion NMC Battery low capacity warning",
            severity=AlarmSeverity.WARNING,
            debounce_sec=debounce_sec,
            cooldown_sec=cooldown_sec,
        )
        self.soc_threshold = soc_threshold
        self.recovery_threshold = recovery_threshold
        self.critical_threshold = critical_threshold

    def _extract_72v_metrics(self, snapshot: dict[str, Any]) -> tuple[float | None, float | None]:
        sys_72v = snapshot.get("72v", {})
        v = sys_72v.get("total_voltage")
        try:
            v_f = float(v) if v is not None else None
        except (ValueError, TypeError):
            v_f = None

        soc = sys_72v.get("soc_integrated")
        if soc is None:
            soc = sys_72v.get("soc_voltage")
        if soc is None and v_f is not None:
            soc = calculate_voltage_soc(v_f)
        if soc is None:
            soc = sys_72v.get("rsoc")

        try:
            soc_f = float(soc) if soc is not None else None
        except (ValueError, TypeError):
            soc_f = None

        # Cross-validation with pack voltage:
        # If terminal voltage is healthy (>= 72.0V, ~3.60V/cell on 20S NMC),
        # an uncalibrated JBD BMS RSOC reporting <= 20% is spurious.
        if v_f is not None and v_f >= 72.0 and (soc_f is None or soc_f <= self.soc_threshold):
            v_soc = calculate_voltage_soc(v_f)
            if v_soc is not None:
                soc_f = v_soc

        return soc_f, v_f

    def evaluate_condition(self, snapshot: dict[str, Any]) -> tuple[bool, AlarmSeverity, str, dict[str, Any]]:
        soc, v = self._extract_72v_metrics(snapshot)
        if soc is None:
            return False, AlarmSeverity.WARNING, "", {}

        # Voltage guard: 72.0V on a 20S NMC pack corresponds to ~3.60V/cell (healthy reserve).
        # Never trigger low battery alarm if pack voltage is >= 72.0V.
        if v is not None and v >= 72.0:
            return False, AlarmSeverity.WARNING, "", {"soc": soc, "voltage": v}

        if soc <= self.soc_threshold:
            severity = AlarmSeverity.CRITICAL if soc <= self.critical_threshold else AlarmSeverity.WARNING
            v_str = f"{v:.1f}V" if v is not None else "--.-V"
            msg = f"72V Propulsion Battery at {soc:.1f}% ({v_str}) - low battery reserve"
            return True, severity, msg, {"soc": soc, "voltage": v}

        return False, AlarmSeverity.WARNING, "", {"soc": soc, "voltage": v}

    def evaluate_recovery(self, snapshot: dict[str, Any]) -> tuple[bool, str]:
        soc, v = self._extract_72v_metrics(snapshot)
        recovered_soc = soc is not None and soc >= self.recovery_threshold
        recovered_v = v is not None and v >= 73.5  # ~3.68V/cell
        if recovered_soc or recovered_v:
            v_str = f"{v:.1f}V" if v is not None else "--.-V"
            soc_str = f"{soc:.1f}%" if soc is not None else "--.-%"
            return True, f"72V Propulsion Battery recovered to {soc_str} ({v_str})"
        return False, ""


class BatteryOverheatRule(AlarmRule):
    """Alerts when battery temperatures exceed safety limits (> 45°C)."""

    def __init__(
        self,
        temp_threshold: float = 45.0,
        recovery_temp: float = 40.0,
        debounce_sec: float = 5.0,
        cooldown_sec: float = 3600.0,
    ):
        super().__init__(
            name="battery_overheat",
            description="Battery temperature exceeded 45°C safety threshold",
            severity=AlarmSeverity.CRITICAL,
            debounce_sec=debounce_sec,
            cooldown_sec=cooldown_sec,
        )
        self.temp_threshold = temp_threshold
        self.recovery_temp = recovery_temp

    def evaluate_condition(self, snapshot: dict[str, Any]) -> tuple[bool, AlarmSeverity, str, dict[str, Any]]:
        t_72v_1 = snapshot.get("72v", {}).get("temp_1")
        t_72v_2 = snapshot.get("72v", {}).get("temp_2")
        t_12v_batt = snapshot.get("12v", {}).get("battery_temperature")

        temps = [t for t in (t_72v_1, t_72v_2, t_12v_batt) if t is not None]
        if not temps:
            return False, AlarmSeverity.CRITICAL, "", {}

        max_t = max(float(t) for t in temps)
        if max_t >= self.temp_threshold:
            msg = f"Battery Overheat Warning: peak temperature reached {max_t:.1f}°C"
            return True, AlarmSeverity.CRITICAL, msg, {"peak_temp": max_t}

        return False, AlarmSeverity.CRITICAL, "", {"peak_temp": max_t}

    def evaluate_recovery(self, snapshot: dict[str, Any]) -> tuple[bool, str]:
        t_72v_1 = snapshot.get("72v", {}).get("temp_1")
        t_72v_2 = snapshot.get("72v", {}).get("temp_2")
        t_12v_batt = snapshot.get("12v", {}).get("battery_temperature")

        temps = [float(t) for t in (t_72v_1, t_72v_2, t_12v_batt) if t is not None]
        if temps and max(temps) < self.recovery_temp:
            return True, f"Battery temperatures returned to normal ({max(temps):.1f}°C)"
        return False, ""


class AlarmEngine:
    """Orchestrates all alarm rules and tracks vessel-wide alert status."""

    def __init__(self, rules: list[AlarmRule] | None = None):
        self.rules: list[AlarmRule] = rules if rules is not None else [
            Low12VCapacityRule(),
            Low72VBatteryRule(),
            BatteryOverheatRule(),
        ]
        self.snapshot: dict[str, Any] = {
            "72v": {},
            "12v": {},
            "gps": {},
            "charger": {},
        }

    def update_telemetry(self, subsystem: str, data: dict[str, Any]):
        """Updates internal state snapshot with incoming subsystem packet."""
        if subsystem in self.snapshot:
            self.snapshot[subsystem].update(data)
        else:
            self.snapshot[subsystem] = data

    def evaluate(self, now_epoch: float | None = None) -> list[AlarmEvent]:
        """Evaluates all rules against current snapshot and returns new events."""
        events: list[AlarmEvent] = []
        for rule in self.rules:
            event = rule.update(self.snapshot, now_epoch=now_epoch)
            if event:
                events.append(event)
        return events

    def get_status(self) -> dict[str, Any]:
        """Consolidated vessel alarms snapshot."""
        active_alarms = [r.to_dict() for r in self.rules if r.state != AlarmState.OK]
        has_critical = any(r.current_severity == AlarmSeverity.CRITICAL for r in self.rules if r.state != AlarmState.OK)
        has_warning = any(r.current_severity == AlarmSeverity.WARNING for r in self.rules if r.state != AlarmState.OK)

        overall = "OK"
        if has_critical:
            overall = "CRITICAL"
        elif has_warning:
            overall = "WARNING"

        return {
            "overall_status": overall,
            "active_count": len(active_alarms),
            "active_alarms": active_alarms,
            "all_rules": [r.to_dict() for r in self.rules],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
