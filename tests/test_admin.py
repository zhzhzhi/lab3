"""Admin governance, audit log and statistics tests."""

import pytest

from app.admin.services import (
    dashboard_stats,
    search_logs,
    search_users,
    set_user_status,
    unlock_user,
)
from app.auth.services import authenticate
from app.common.audit import record_log
from app.common.clock import utcnow
from app.common.errors import BusinessError
from app.enums import ItemStatus, Role, UserStatus
from app.extensions import db
from app.models import User
from tests.helpers import make_category, make_item, make_user


def _accounts():
    admin = make_user("admin", roles=[Role.ADMIN.value])
    buyer = make_user("buyer")
    seller = make_user("seller", roles=[Role.SELLER.value, Role.BUYER.value])
    db.session.commit()
    return admin, buyer, seller


def _login(client, account, password="password123"):
    return client.post("/auth/login", data={"account": account, "password": password})


def test_search_users_by_keyword_role_and_status(app):
    admin, buyer, seller = _accounts()
    set_user_status(admin, seller.id, disabled=True, reason="测试")

    assert [u.account for u in search_users(keyword="buy")] == ["buyer"]
    assert {u.account for u in search_users(role="seller")} == {"seller"}
    disabled = search_users(status="disabled")
    assert [u.account for u in disabled] == ["seller"]
    assert len(search_users()) == 3


def test_disabled_user_cannot_login(app):
    admin, buyer, _ = _accounts()

    set_user_status(admin, buyer.id, disabled=True)

    assert buyer.status == UserStatus.DISABLED.value
    with pytest.raises(BusinessError) as excinfo:
        authenticate("buyer", "password123")
    assert "禁用" in str(excinfo.value)


def test_admin_cannot_disable_self_or_other_admins(app):
    admin, _, _ = _accounts()
    another = make_user("admin2", roles=[Role.ADMIN.value])
    db.session.commit()

    with pytest.raises(BusinessError) as self_error:
        set_user_status(admin, admin.id, disabled=True)
    assert "自己" in str(self_error.value)

    with pytest.raises(BusinessError) as peer_error:
        set_user_status(admin, another.id, disabled=True)
    assert "管理员" in str(peer_error.value)


def test_enable_user_clears_lock_state(app):
    admin, buyer, _ = _accounts()
    buyer.failed_attempts = 5
    buyer.locked_until = utcnow()
    db.session.commit()
    set_user_status(admin, buyer.id, disabled=True)

    set_user_status(admin, buyer.id, disabled=False)

    saved = db.session.get(User, buyer.id)
    assert saved.status == UserStatus.ACTIVE.value
    assert saved.failed_attempts == 0
    assert saved.locked_until is None


def test_unlock_user_clears_failures(app):
    admin, buyer, _ = _accounts()
    buyer.failed_attempts = 3
    db.session.commit()

    unlock_user(admin, buyer.id)

    assert db.session.get(User, buyer.id).failed_attempts == 0


def test_log_search_filters(app):
    admin, buyer, _ = _accounts()
    record_log(buyer.id, "create_item", "item", 1, detail="商品A")
    record_log(buyer.id, "create_reservation", "reservation", 1, detail="预约A")
    db.session.commit()

    pagination = search_logs({"action_type": "create_item"})
    assert pagination.total == 1
    assert pagination.items[0].action_type == "create_item"

    by_operator = search_logs({"operator": "buyer"})
    assert by_operator.total == 2

    assert search_logs({"target_type": "reservation"}).total == 1


def test_log_search_rejects_bad_date_range(app):
    _accounts()

    with pytest.raises(BusinessError):
        search_logs({"date_from": "2026-13-01"})
    with pytest.raises(BusinessError):
        search_logs({"date_from": "2026-11-20", "date_to": "2026-11-10"})


def test_dashboard_stats_shape(app):
    _, buyer, seller = _accounts()
    category = make_category()
    make_item(seller, category, status=ItemStatus.PUBLISHED.value)
    make_item(seller, category, status=ItemStatus.PENDING.value)

    stats = dashboard_stats()

    assert stats["items"]["total"] == 2
    assert stats["items"]["by_status"]["published"] == 1
    assert stats["items"]["by_status"]["draft"] == 0
    assert stats["users"]["total"] == 3
    assert stats["pending_review"] == 1
    assert len(stats["recent"]) == 7
    assert set(stats["recent"][0]) == {"date", "items", "reservations", "completed"}
    assert buyer.id is not None


def test_admin_pages_require_admin(client, app):
    _accounts()

    _login(client, "buyer")
    for path in ("/admin/", "/admin/users/", "/admin/logs/", "/admin/stats/"):
        assert client.get(path).status_code == 403

    client.get("/auth/logout")
    _login(client, "admin")
    for path in ("/admin/", "/admin/users/", "/admin/logs/", "/admin/stats/"):
        assert client.get(path).status_code == 200


def test_disable_user_route(client, app):
    admin, buyer, _ = _accounts()

    _login(client, "admin")
    response = client.post(f"/admin/users/{buyer.id}/disable", data={"reason": "违规"})
    assert response.status_code == 302
    assert db.session.get(User, buyer.id).status == UserStatus.DISABLED.value

    client.post(f"/admin/users/{buyer.id}/enable")
    assert db.session.get(User, buyer.id).status == UserStatus.ACTIVE.value
