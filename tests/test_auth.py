"""Authentication service and route tests."""

from datetime import datetime

import pytest

from app.auth.services import authenticate, register_user
from app.common.clock import clock
from app.common.errors import BusinessError
from app.enums import Role
from app.extensions import db
from app.models import User


def test_register_and_authenticate(app):
    user = register_user("alice", "Alice", "password123", "wx:alice", ["buyer", "seller"])
    assert user.id is not None
    assert user.has_role(Role.BUYER)
    assert user.has_role(Role.SELLER)

    logged_in = authenticate("alice", "password123")
    assert logged_in.id == user.id


def test_wrong_password_is_rejected(app):
    register_user("bob", "Bob", "password123")
    with pytest.raises(BusinessError):
        authenticate("bob", "wrong-password")


def test_account_locks_after_five_failures(app, monkeypatch):
    register_user("carol", "Carol", "password123")
    fixed = datetime(2026, 11, 15, 12, 0, 0)
    monkeypatch.setattr(clock, "now", lambda: fixed)

    for _ in range(4):
        with pytest.raises(BusinessError):
            authenticate("carol", "wrong-password")

    with pytest.raises(BusinessError) as excinfo:
        authenticate("carol", "wrong-password")
    assert "锁定" in str(excinfo.value)

    user = User.query.filter_by(account="carol").first()
    assert user.locked_until is not None

    with pytest.raises(BusinessError) as locked:
        authenticate("carol", "password123")
    assert "锁定" in str(locked.value)


def test_register_and_login_route(client):
    response = client.post(
        "/auth/register",
        data={
            "account": "dave",
            "nickname": "Dave",
            "password": "password123",
            "confirm": "password123",
            "contact": "wx:dave",
            "roles": ["buyer"],
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "退出" in response.get_data(as_text=True)

    client.get("/auth/logout")
    response = client.post(
        "/auth/login",
        data={"account": "dave", "password": "password123"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Dave" in response.get_data(as_text=True)
