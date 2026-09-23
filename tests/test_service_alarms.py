import pytest
from alarms.rules import (
    AlarmEngine,
    AlarmSeverity,
    AlarmState,
    ServiceRestartLoopRule,
)


def test_service_restart_loop_rule_threshold():
    rule = ServiceRestartLoopRule(
        service_id="12v",
        service_unit="watch_12v.service",
        display_name="12V Solar Monitor",
        failure_threshold=5,
        recovery_uptime_sec=60.0,
        debounce_sec=0.0,
    )

    # Initial state
    assert rule.state == AlarmState.OK

    # Simulate 4 consecutive failures (below threshold of 5)
    for i in range(1, 5):
        snapshot = {
            "services": {
                "watch_12v.service": {
                    "exec_main_exit_timestamp": f"2026-09-16 08:00:{i:02d}",
                    "exec_main_status": 1,
                    "active_state": "activating",
                    "sub_state": "auto-restart",
                    "n_restarts": i,
                }
            }
        }
        event = rule.update(snapshot)
        assert event is None
        assert rule.state == AlarmState.OK
        assert rule.consecutive_failures == i

    # 5th failure trips the alarm
    snapshot = {
        "services": {
            "watch_12v.service": {
                "exec_main_exit_timestamp": "2026-09-16 08:00:05",
                "exec_main_status": 1,
                "active_state": "activating",
                "sub_state": "auto-restart",
                "n_restarts": 5,
            }
        }
    }
    event = rule.update(snapshot)
    assert event is not None
    assert event.state == "ALARM"
    assert event.severity == "CRITICAL"
    assert "12V Solar Monitor" in event.message
    assert "5 times in a row" in event.message
    assert "look is continuing automatic restart attempts" in event.message
    assert rule.state == AlarmState.ALARM

    # 6th failure keeps alarm active
    snapshot["services"]["watch_12v.service"]["exec_main_exit_timestamp"] = "2026-09-16 08:00:06"
    snapshot["services"]["watch_12v.service"]["n_restarts"] = 6
    event_6 = rule.update(snapshot)
    # Does not re-emit state transition event unless cooldown passes, but stays in ALARM
    assert rule.state == AlarmState.ALARM
    assert rule.consecutive_failures == 6


def test_service_restart_loop_recovery_via_stable_uptime():
    rule = ServiceRestartLoopRule(
        service_id="72v",
        service_unit="watch_72v.service",
        display_name="72V BMS Monitor",
        failure_threshold=5,
        recovery_uptime_sec=60.0,
        debounce_sec=0.0,
    )

    # Trip alarm directly via injected consecutive failures
    snapshot_fail = {
        "services": {
            "watch_72v.service": {
                "consecutive_failures": 5,
                "active_state": "failed",
                "sub_state": "failed",
            }
        }
    }
    event = rule.update(snapshot_fail)
    assert event is not None
    assert rule.state == AlarmState.ALARM

    # Service starts running, but has only been running for 10s (below recovery window)
    t0 = 1000.0
    snapshot_running = {
        "services": {
            "watch_72v.service": {
                "active_state": "active",
                "sub_state": "running",
            }
        }
    }
    assert rule.update(snapshot_running, now_epoch=t0) is None
    assert rule.state == AlarmState.ALARM

    # After 50s (total 50s < 60s), still in ALARM
    assert rule.update(snapshot_running, now_epoch=t0 + 50.0) is None
    assert rule.state == AlarmState.ALARM

    # After 65s (exceeds 60s stability window), recovers to OK
    clear_event = rule.update(snapshot_running, now_epoch=t0 + 65.0)
    assert clear_event is not None
    assert clear_event.state == "OK"
    assert "CLEARED" in clear_event.message
    assert "has recovered and is running stably" in clear_event.message
    assert rule.state == AlarmState.OK
    assert rule.consecutive_failures == 0


def test_service_restart_loop_recovery_via_live_telemetry():
    rule = ServiceRestartLoopRule(
        service_id="gps",
        service_unit="watch_gps.service",
        display_name="GPS Navigation Monitor",
        failure_threshold=5,
        recovery_uptime_sec=60.0,
        debounce_sec=0.0,
    )

    # Trip alarm
    snapshot = {
        "services": {
            "watch_gps.service": {
                "consecutive_failures": 5,
                "active_state": "failed",
                "sub_state": "failed",
            }
        }
    }
    rule.update(snapshot)
    assert rule.state == AlarmState.ALARM

    # Service starts running and immediately publishes live telemetry
    snapshot["services"]["watch_gps.service"]["active_state"] = "active"
    snapshot["services"]["watch_gps.service"]["sub_state"] = "running"
    snapshot["gps"] = {"latitude": -43.6, "longitude": 172.7}

    clear_event = rule.update(snapshot)
    assert clear_event is not None
    assert clear_event.state == "OK"
    assert rule.state == AlarmState.OK


def test_alarm_engine_integration_all_monitors():
    engine = AlarmEngine()

    rule_names = [r.name for r in engine.rules]
    assert "restart_loop_12v" in rule_names
    assert "restart_loop_72v" in rule_names
    assert "restart_loop_gps" in rule_names
    assert "restart_loop_seatalkng" in rule_names

    # Feed systemd status for seatalkng with 5 consecutive failures
    engine.update_systemd({
        "paeraki_seatalkng.service": {
            "consecutive_failures": 5,
            "exec_main_status": 1,
            "active_state": "failed",
            "sub_state": "failed",
        }
    })

    events = engine.evaluate()
    assert len(events) >= 1
    stng_event = next(e for e in events if e.rule_name == "restart_loop_seatalkng")
    assert stng_event.severity == "CRITICAL"
    assert "SeaTalkNG Bus Monitor" in stng_event.message

    status = engine.get_status()
    assert status["overall_status"] == "CRITICAL"
    assert status["active_count"] == 1


@pytest.mark.anyio
async def test_email_dispatcher():
    from alarms.dispatchers import EmailDispatcher
    from alarms.rules import AlarmEvent

    # 1. No recipient -> False
    disp_none = EmailDispatcher(recipient_email=None)
    event = AlarmEvent(
        rule_name="restart_loop_12v",
        severity="CRITICAL",
        state="ALARM",
        message="12V Solar Monitor failed 5 times in a row",
        timestamp="2026-09-16T12:00:00Z",
        epoch_ms=1789518000000,
    )
    assert await disp_none.dispatch(event, {"active_count": 1}) is False

    # 2. Configured recipient with dry_run -> True
    disp_dry = EmailDispatcher(
        recipient_email="jjharrington@gmail.com",
        smtp_host="192.168.1.1",
        smtp_port=25,
        dry_run=True,
    )
    assert await disp_dry.dispatch(event, {"active_count": 1}) is True

    # 3. Informational cleared event -> True (skips non-critical clear)
    clear_event = AlarmEvent(
        rule_name="restart_loop_12v",
        severity="INFO",
        state="OK",
        message="CLEARED: 12V Solar Monitor recovered",
        timestamp="2026-09-16T12:05:00Z",
        epoch_ms=1789518300000,
    )
    assert await disp_dry.dispatch(clear_event, {"active_count": 0}) is True


@pytest.mark.anyio
async def test_sms_dispatcher():
    from alarms.dispatchers import SmsDispatcher
    from alarms.rules import AlarmEvent

    disp_dry = SmsDispatcher(
        phone_number="+64274461297",
        router_ip="192.168.1.1",
        dry_run=True,
    )
    event = AlarmEvent(
        rule_name="restart_loop_gps",
        severity="CRITICAL",
        state="ALARM",
        message="GPS Navigation Monitor failed 5 times in a row",
        timestamp="2026-09-16T12:00:00Z",
        epoch_ms=1789518000000,
    )
    assert await disp_dry.dispatch(event, {"active_count": 1}) is True


@pytest.mark.anyio
async def test_sms_dispatcher_execution():
    from unittest.mock import AsyncMock, patch
    from alarms.dispatchers import SmsDispatcher
    from alarms.rules import AlarmEvent

    disp = SmsDispatcher(
        phone_number="+64274461297",
        router_ip="192.168.1.1",
        dry_run=False,
    )
    event = AlarmEvent(
        rule_name="connection_look_lost",
        severity="CRITICAL",
        state="ALARM",
        message="Connection to look lost for 1h",
        timestamp="2026-09-24T09:00:00Z",
        epoch_ms=1790200000000,
    )

    # 1. Success case: returncode 0 and 'SMS sent: 1'
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"SMS sent: 1\n", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        assert await disp.dispatch(event, {"active_count": 1}) is True
        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert args[0] == "ssh"
        assert "root@192.168.1.1" in args
        # Check remote command has gsmctl -S -s
        remote_cmd = args[-1]
        assert remote_cmd.startswith("gsmctl -S -s ")
        assert "+64274461297" in remote_cmd

    # 2. Failure case: modem error / wrong format
    mock_proc_fail = AsyncMock()
    mock_proc_fail.returncode = 0
    mock_proc_fail.communicate = AsyncMock(return_value=(b"Wrong input format\n", b""))
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc_fail):
        assert await disp.dispatch(event, {"active_count": 1}) is False


@pytest.mark.anyio
async def test_email_dispatcher_smtp_execution():
    from unittest.mock import MagicMock, patch
    from alarms.dispatchers import EmailDispatcher
    from alarms.rules import AlarmEvent

    disp = EmailDispatcher(
        recipient_email="jjharrington@gmail.com",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_user="jjharrington@gmail.com",
        smtp_password="test_password",
        sender_email="jjharrington@gmail.com",
        dry_run=False,
    )
    event = AlarmEvent(
        rule_name="connection_rut955_lost",
        severity="CRITICAL",
        state="ALARM",
        message="Connection to RUT955 lost for 1h",
        timestamp="2026-09-24T09:00:00Z",
        epoch_ms=1790200000000,
    )

    mock_server = MagicMock()
    mock_smtp_class = MagicMock(return_value=mock_server)
    mock_server.__enter__.return_value = mock_server

    with patch("smtplib.SMTP", mock_smtp_class):
        res = await disp.dispatch(event, {"active_count": 1})
        assert res is True
        mock_smtp_class.assert_called_once_with("smtp.gmail.com", 587, timeout=10.0)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("jjharrington@gmail.com", "test_password")
        mock_server.send_message.assert_called_once()


