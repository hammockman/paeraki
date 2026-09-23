#!/usr/bin/env python3
"""
Unit tests for Historian LinkWatchdog.
Tests timeout detection, recovery events, rate limiting, and database seeding.
"""

import asyncio
from pathlib import Path
import sqlite3
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alarms.rules import AlarmState
from logger.watchdog import LinkWatchdog, format_duration


def test_format_duration():
    assert format_duration(45) == "0m"
    assert format_duration(90) == "1m"
    assert format_duration(3600) == "1h 00m"
    assert format_duration(3665) == "1h 01m"
    assert format_duration(7200 + 15 * 60) == "2h 15m"


@pytest.fixture
def mock_watchdog():
    wd = LinkWatchdog(
        timeout_sec=10.0,
        repeat_interval_sec=60.0,
        check_interval_sec=1.0,
        phone_number="+64270000000",
        recipient_email="test@example.com",
        dry_run=True,
    )
    # Mock dispatchers
    wd.sms_dispatcher = MagicMock()
    wd.sms_dispatcher.dispatch = AsyncMock(return_value=True)
    wd.email_dispatcher = MagicMock()
    wd.email_dispatcher.dispatch = AsyncMock(return_value=True)
    return wd


def test_watchdog_broker_alarm(mock_watchdog):
    async def _test():
        wd = mock_watchdog
        now = time.time()
        wd.broker_connected = False
        wd.broker_last_seen = now - 15.0  # 15s ago, exceeds 10s timeout

        await wd.check()

        assert wd.broker_alarm_state == AlarmState.ALARM
        assert wd.email_dispatcher.dispatch.called
        event = wd.email_dispatcher.dispatch.call_args[0][0]
        assert event.rule_name == "connection_rut955_lost"
        assert "RUT955" in event.message
        # SMS should NOT be called because router is down
        assert not wd.sms_dispatcher.dispatch.called

    asyncio.run(_test())


def test_watchdog_look_alarm_with_router_sms(mock_watchdog):
    async def _test():
        wd = mock_watchdog
        now = time.time()
        wd.broker_connected = True
        wd.broker_last_seen = now
        wd.look_last_seen = now - 20.0  # 20s ago, exceeds 10s timeout

        await wd.check()

        assert wd.look_alarm_state == AlarmState.ALARM
        # Both SMS (via router) and Email should be dispatched
        assert wd.sms_dispatcher.dispatch.called
        assert wd.email_dispatcher.dispatch.called

        sms_event = wd.sms_dispatcher.dispatch.call_args[0][0]
        assert sms_event.rule_name == "connection_look_lost"
        assert "look telemetry computer" in sms_event.message

    asyncio.run(_test())


def test_watchdog_rate_limiting(mock_watchdog):
    async def _test():
        wd = mock_watchdog
        now = time.time()
        wd.broker_connected = True
        wd.look_last_seen = now - 20.0

        await wd.check()
        assert wd.look_alarm_state == AlarmState.ALARM
        assert wd.sms_dispatcher.dispatch.call_count == 1

        # Immediate second check should NOT re-alert
        await wd.check()
        assert wd.sms_dispatcher.dispatch.call_count == 1

        # Simulate repeat interval passing
        wd.look_last_alert_time = now - 70.0  # Exceeds repeat_interval_sec (60s)
        await wd.check()
        assert wd.sms_dispatcher.dispatch.call_count == 2

    asyncio.run(_test())


def test_watchdog_recovery_event(mock_watchdog):
    async def _test():
        wd = mock_watchdog
        now = time.time()
        wd.broker_connected = True
        wd.look_alarm_state = AlarmState.ALARM
        wd.look_last_seen = now - 50.0

        # Incoming packet from look resets alarm and triggers recovery
        wd.on_packet("paeraki/gps/state")
        assert wd.look_alarm_state == AlarmState.OK

        # Allow asyncio tasks to execute
        await asyncio.sleep(0.05)
        assert wd.sms_dispatcher.dispatch.called
        call_args = wd.sms_dispatcher.dispatch.call_args[0][0]
        assert "recovered" in call_args.rule_name.lower() or "restored" in call_args.message.lower()

    asyncio.run(_test())


def test_watchdog_packet_filtering(mock_watchdog):
    wd = mock_watchdog
    initial_time = 1000.0
    wd.look_last_seen = initial_time

    # Non-look topic (media from sing) should NOT update look_last_seen
    wd.on_packet("paeraki/media/state")
    assert wd.look_last_seen == initial_time

    # Look topics SHOULD update look_last_seen when retain=False
    with patch("time.time", return_value=2000.0):
        # Retained packet should be ignored
        wd.on_packet("paeraki/gps/state", retain=True)
        assert wd.look_last_seen == initial_time

        # Live packet updates look_last_seen
        wd.on_packet("paeraki/gps/state", retain=False)
        assert wd.look_last_seen == 2000.0

        wd.on_packet("paeraki/seatalkng/pgn/126720")
        assert wd.look_last_seen == 2000.0


def test_watchdog_seed_from_db(tmp_path):
    db_file = tmp_path / "test_paeraki.db"
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE packets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            epoch_ms INTEGER NOT NULL,
            topic TEXT NOT NULL
        )
    """)
    target_epoch_ms = 1790139761000  # 1790139761.0 seconds
    cursor.execute("INSERT INTO packets (epoch_ms, topic) VALUES (?, ?)", (target_epoch_ms, "paeraki/gps/state"))
    cursor.execute("INSERT INTO packets (epoch_ms, topic) VALUES (?, ?)", (target_epoch_ms + 5000, "paeraki/media/state"))
    conn.commit()
    conn.close()

    wd = LinkWatchdog(
        timeout_sec=10.0,
        db_path=db_file,
        dry_run=True,
    )
    assert wd.look_last_seen == target_epoch_ms / 1000.0
