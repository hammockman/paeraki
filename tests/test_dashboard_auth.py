import tempfile
from pathlib import Path
import pytest
from dashboard.auth import DeviceAuthManager, hash_pin


@pytest.fixture
def auth_mgr():
    with tempfile.TemporaryDirectory() as tmpdir:
        auth_file = Path(tmpdir) / "authorized_devices.json"
        mgr = DeviceAuthManager(auth_file=auth_file, default_pin="9876")
        yield mgr


def test_pin_verification_and_update(auth_mgr):
    assert auth_mgr.verify_pin("9876") is True
    assert auth_mgr.verify_pin("1234") is False
    assert auth_mgr.verify_pin("wrong") is False

    # Update PIN
    assert auth_mgr.set_pin("wrong", "5555") is False
    assert auth_mgr.set_pin("9876", "5555") is True
    assert auth_mgr.verify_pin("9876") is False
    assert auth_mgr.verify_pin("5555") is True


def test_authorize_with_pin(auth_mgr):
    dev_uuid = "uuid-12345"
    # Wrong PIN
    ok, msg, token = auth_mgr.authorize_with_pin(dev_uuid, "0000", name="Skipper Phone")
    assert ok is False
    assert token is None

    # Correct PIN
    ok, msg, token = auth_mgr.authorize_with_pin(dev_uuid, "9876", name="Skipper Phone", ip="192.168.1.105")
    assert ok is True
    assert token is not None
    assert len(token) > 20

    # Validate token
    dev = auth_mgr.validate_token(token)
    assert dev is not None
    assert dev["uuid"] == dev_uuid
    assert dev["name"] == "Skipper Phone"
    assert dev["role"] == "CONTROLLER"

    # Listing devices
    devices = auth_mgr.list_devices()
    assert len(devices) == 1
    assert devices[0]["uuid"] == dev_uuid
    assert "token" not in devices[0]  # token not exposed in list


def test_pairing_request_and_approval(auth_mgr):
    dev_uuid = "tablet-uuid-99"
    # Request pairing
    req = auth_mgr.request_pairing(dev_uuid, name="Helm Tablet", ip="192.168.1.110")
    assert req["uuid"] == dev_uuid
    assert req["name"] == "Helm Tablet"
    assert len(auth_mgr.list_pending()) == 1

    # Approve pairing
    ok, msg, token = auth_mgr.approve_pairing(dev_uuid)
    assert ok is True
    assert token is not None
    assert len(auth_mgr.list_pending()) == 0

    # Validate token
    dev = auth_mgr.validate_token(token)
    assert dev is not None
    assert dev["role"] == "CONTROLLER"
    assert dev["name"] == "Helm Tablet"


def test_revocation(auth_mgr):
    dev_uuid = "guest-uuid"
    ok, _, token = auth_mgr.authorize_with_pin(dev_uuid, "9876", name="Guest Phone")
    assert ok is True

    # Valid before revocation
    assert auth_mgr.validate_token(token) is not None

    # Revoke
    assert auth_mgr.revoke_device(dev_uuid) is True
    assert auth_mgr.validate_token(token) is None
    assert len(auth_mgr.list_devices()) == 0


def test_dashboard_auth_routes():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    import dashboard.server as srv
    from dashboard.auth import auth_manager

    app = srv.create_app("", 0)

    # Locate route endpoints
    verify_pin_ep = None
    status_ep = None
    for route in app.routes:
        if getattr(route, "path", None) == "/api/auth/verify_pin":
            verify_pin_ep = route.endpoint
        elif getattr(route, "path", None) == "/api/auth/status":
            status_ep = route.endpoint

    assert verify_pin_ep is not None
    assert status_ep is not None

    async def _run():
        # 1. Test verify_pin with wrong PIN
        req_bad = MagicMock()
        req_bad.json = AsyncMock(return_value={"uuid": "unit-test-dev", "pin": "000000", "name": "Phone"})
        req_bad.client.host = "127.0.0.1"
        res_bad = await verify_pin_ep(req_bad)
        assert res_bad.status_code == 401

        # 2. Test verify_pin with correct default PIN
        req_good = MagicMock()
        req_good.json = AsyncMock(return_value={"uuid": "unit-test-dev", "pin": auth_manager.default_pin, "name": "Phone"})
        req_good.client.host = "127.0.0.1"
        res_good = await verify_pin_ep(req_good)
        assert res_good.status_code == 200

        # 3. Test status endpoint with unauthenticated request
        req_unauth = MagicMock()
        req_unauth.headers = {}
        req_unauth.cookies = {}
        req_unauth.client.host = "127.0.0.1"
        res_unauth = await status_ep(req_unauth)
        assert res_unauth.status_code == 200

    asyncio.run(_run())

