import pytest
from alarms.rules import (
    AlarmEngine,
    AlarmSeverity,
    AlarmState,
    CortexAnchorDragRule,
    CortexCollisionRiskRule,
)


def test_cortex_anchor_drag_rule():
    rule = CortexAnchorDragRule(debounce_sec=0.0)

    # 1. Normal state: vessel within radius (12m / 35m)
    snapshot = {
        "cortex": {
            "anchor": {
                "active": True,
                "radius_m": 35.0,
                "distance_m": 12.0,
                "drag_alarm": False,
            }
        }
    }
    event = rule.update(snapshot, now_epoch=100.0)
    assert event is None
    assert rule.state == AlarmState.OK

    # 2. Anchor drag: vessel drifted 42m (beyond 35m)
    snapshot["cortex"]["anchor"]["distance_m"] = 42.0
    event = rule.update(snapshot, now_epoch=105.0)
    assert event is not None
    assert event.severity == AlarmSeverity.CRITICAL.value
    assert "ANCHOR DRAG" in event.message
    assert rule.state == AlarmState.ALARM

    # 3. Recovery: vessel brought back within radius (< 31.5m, 90% of 35m)
    snapshot["cortex"]["anchor"]["distance_m"] = 28.0
    event = rule.update(snapshot, now_epoch=110.0)
    assert event is not None
    assert event.state == AlarmState.OK.value
    assert "recovered" in event.message.lower()
    assert rule.state == AlarmState.OK


def test_cortex_collision_risk_rule():
    rule = CortexCollisionRiskRule(debounce_sec=0.0)

    # 1. Normal: no alarms
    snapshot = {"cortex": {"alarms": []}}
    event = rule.update(snapshot, now_epoch=200.0)
    assert event is None
    assert rule.state == AlarmState.OK

    # 2. Active CPA Alert
    snapshot["cortex"]["alarms"] = [
        {
            "id": "cpa_target_999",
            "type": "CollisionRisk",
            "severity": "WARNING",
            "message": "CPA 0.15 NM with FERRY in 4 mins",
            "silenced": False,
        }
    ]
    event = rule.update(snapshot, now_epoch=205.0)
    assert event is not None
    assert event.severity == AlarmSeverity.WARNING.value
    assert "COLLISION ALERT" in event.message
    assert rule.state == AlarmState.ALARM

    # 3. Silenced alert: should recover / clear
    snapshot["cortex"]["alarms"][0]["silenced"] = True
    event = rule.update(snapshot, now_epoch=210.0)
    assert event is not None
    assert event.state == AlarmState.OK.value
    assert rule.state == AlarmState.OK
