"""Route-level tests covering both happy paths and error branches."""

from io import BytesIO

import pytest

from app.common.errors import BusinessError
from app.common.pagination import normalize_page, normalize_per_page
from app.enums import ItemStatus, ReservationStatus, Role, UserStatus
from app.extensions import db, login_manager
from app.models import Item, Reservation, User
from tests.helpers import make_category, make_item, make_user

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _login(client, account, password="password123"):
    return client.post("/auth/login", data={"account": account, "password": password})


def _marketplace(status=ItemStatus.PUBLISHED.value):
    seller = make_user("seller", roles=[Role.SELLER.value, Role.BUYER.value])
    buyer = make_user("buyer")
    admin = make_user("admin", roles=[Role.ADMIN.value])
    category = make_category()
    item = make_item(seller, category, status=status, name="测试教材")
    db.session.commit()
    return seller, buyer, admin, category, item


def _form(category, action="draft", **overrides):
    data = {
        "name": "二手教材",
        "description": "九成新，宿舍楼下自提，可以当面验货。",
        "price": "25.00",
        "contact": "微信：seller",
        "category_id": str(category.id),
        "action": action,
        "images": (BytesIO(PNG), "a.png"),
    }
    data.update(overrides)
    return data


def _post_form(client, url, data):
    return client.post(url, data=data, content_type="multipart/form-data")


# --------------------------------------------------------------------------
# 商品：卖家与管理员路由
# --------------------------------------------------------------------------


def test_seller_item_pages_render(client, app):
    _, _, _, _, item = _marketplace()
    _login(client, "seller")

    assert client.get("/seller/items/").status_code == 200
    assert client.get("/seller/items/new").status_code == 200
    assert client.get(f"/seller/items/{item.id}/edit").status_code == 302
    assert client.get("/admin/items/").status_code == 403


def test_create_item_route_saves_draft_then_submit(client, app):
    _, _, _, category, _ = _marketplace()
    _login(client, "seller")

    response = _post_form(client, "/seller/items/new", _form(category))
    assert response.status_code == 302
    draft = Item.query.filter_by(name="二手教材").one()
    assert draft.status == ItemStatus.DRAFT.value
    assert draft.images[0].url.startswith("/uploads/")

    response = _post_form(client, "/seller/items/new", _form(category, "submit"))
    assert response.status_code == 302
    pending = Item.query.filter_by(status=ItemStatus.PENDING.value).one()
    assert pending.name == "二手教材"


def test_create_item_route_renders_validation_error(client, app):
    _, _, _, category, _ = _marketplace()
    _login(client, "seller")

    response = _post_form(client, "/seller/items/new", _form(category, price="-1"))
    assert response.status_code == 400
    assert "价格必须大于 0 元" in response.get_data(as_text=True)


def test_create_item_route_rejects_bad_image_type(client, app):
    _, _, _, category, _ = _marketplace()
    _login(client, "seller")

    data = _form(category)
    data["images"] = (BytesIO(b"not an image"), "a.exe")
    response = _post_form(client, "/seller/items/new", data)
    assert response.status_code == 400


def test_edit_item_route_updates_and_resubmits(client, app):
    seller, _, _, category, _ = _marketplace(ItemStatus.DRAFT.value)
    _login(client, "seller")
    keep_id = Item.query.one().images[0].id

    data = _form(category, name="二手教材（改）")
    data.pop("images")
    data["keep_image"] = str(keep_id)
    response = client.post(
        f"/seller/items/{Item.query.one().id}/edit",
        data=data,
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    assert Item.query.one().name == "二手教材（改）"


def test_edit_item_route_blocks_wrong_status_and_owner(client, app):
    seller, buyer, _, category, item = _marketplace()
    _login(client, "seller")
    assert client.get(f"/seller/items/{item.id}/edit").status_code == 302

    client.get("/auth/logout")
    _login(client, "buyer")
    assert client.get(f"/seller/items/{item.id}/edit").status_code == 403


def test_lifecycle_routes(client, app):
    seller, _, _, _, item = _marketplace(ItemStatus.DRAFT.value)
    _login(client, "seller")

    client.post(f"/seller/items/{item.id}/submit")
    assert db.session.get(Item, item.id).status == ItemStatus.PENDING.value

    client.post(f"/seller/items/{item.id}/withdraw")
    assert db.session.get(Item, item.id).status == ItemStatus.DRAFT.value

    db.session.get(Item, item.id).status = ItemStatus.PUBLISHED.value
    db.session.commit()
    client.post(f"/seller/items/{item.id}/off-shelf", data={"reason": "测试下架"})
    assert db.session.get(Item, item.id).status == ItemStatus.OFF_SHELF.value

    client.post(f"/seller/items/{item.id}/to-draft")
    assert db.session.get(Item, item.id).status == ItemStatus.DRAFT.value


def test_lifecycle_route_errors_are_flashed(client, app):
    _, _, _, _, item = _marketplace(ItemStatus.PUBLISHED.value)
    _login(client, "seller")

    response = client.post(f"/seller/items/{item.id}/withdraw", follow_redirects=True)
    assert response.status_code == 200
    assert "不能撤回审核" in response.get_data(as_text=True)


def test_admin_review_routes(client, app):
    _, _, _, _, item = _marketplace(ItemStatus.PENDING.value)
    _login(client, "admin")
    assert client.get("/admin/items/").status_code == 200

    client.post(f"/admin/items/{item.id}/approve")
    assert db.session.get(Item, item.id).status == ItemStatus.PUBLISHED.value

    second = make_item(
        item.seller, item.category, status=ItemStatus.PENDING.value, name="第二件"
    )
    db.session.commit()
    client.post(f"/admin/items/{second.id}/reject", data={"reason": "描述不完整"})
    saved = db.session.get(Item, second.id)
    assert saved.status == ItemStatus.REJECTED.value
    assert saved.reject_reason == "描述不完整"


def test_admin_review_route_error_branch(client, app):
    _, _, _, _, item = _marketplace(ItemStatus.PUBLISHED.value)
    _login(client, "admin")

    response = client.post(f"/admin/items/{item.id}/approve", follow_redirects=True)
    assert "不能审核通过" in response.get_data(as_text=True)


# --------------------------------------------------------------------------
# 商品广场：筛选与错误分支
# --------------------------------------------------------------------------


def test_market_detail_not_found_redirects(client, app):
    _marketplace()
    response = client.get("/market/999")
    assert response.status_code == 302


def test_market_json_error_response(client, app):
    _marketplace()
    response = client.get("/market/999", headers={"Accept": "application/json"})
    assert response.status_code == 404
    assert response.get_json()["message"] == "商品不存在或不可见。"


@pytest.mark.parametrize(
    "query",
    [
        "min_price=abc",
        "min_price=100&max_price=10",
        "category_id=abc",
        "status=unknown",
    ],
)
def test_market_filter_errors(client, app, query):
    _marketplace()
    response = client.get(f"/market/?{query}")
    assert response.status_code == 302


# --------------------------------------------------------------------------
# 预约：路由与错误分支
# --------------------------------------------------------------------------


def test_reservation_route_error_branches(client, app):
    _, buyer, _, _, item = _marketplace()
    _login(client, "buyer")

    draft = make_item(item.seller, item.category, status=ItemStatus.DRAFT.value)
    db.session.commit()
    response = client.post(
        f"/reservations/item/{draft.id}", data={"request_id": "req-bad"}
    )
    assert response.status_code == 302

    reservation, _ = _reserve(client, app, item)
    response = client.post(f"/reservations/{reservation.id}/complete")
    assert response.status_code == 302
    assert "不能确认交易完成" in client.get("/reservations/").get_data(as_text=True)


def _reserve(client, app, item):
    from app.reservations.services import create_reservation

    buyer = User.query.filter_by(account="buyer").one()
    return create_reservation(buyer, item.id, "req-route-a")


def test_reservation_cancel_and_complete_routes(client, app):
    seller, buyer, _, _, item = _marketplace()
    reservation, _ = _reserve(client, app, item)

    _login(client, "buyer")
    client.post(f"/reservations/{reservation.id}/cancel", data={"reason": "不需要了"})
    assert reservation.status == ReservationStatus.CANCELLED.value
    assert db.session.get(Item, item.id).status == ItemStatus.PUBLISHED.value


def test_seller_reservation_routes(client, app):
    seller, _, _, _, item = _marketplace()
    reservation, _ = _reserve(client, app, item)

    _login(client, "seller")
    client.post(f"/seller/reservations/{reservation.id}/confirm")
    assert reservation.status == ReservationStatus.CONFIRMED.value

    other = make_item(
        seller, item.category, status=ItemStatus.PUBLISHED.value, name="第二件"
    )
    db.session.commit()
    second, _ = _reserve_more(item.seller, other)
    client.post(f"/seller/reservations/{second.id}/cancel", data={"reason": "不卖了"})
    assert second.status == ReservationStatus.CANCELLED.value


def _reserve_more(seller, item):
    from app.reservations.services import create_reservation

    buyer = make_user("buyer2")
    db.session.commit()
    return create_reservation(buyer, item.id, "req-route-b")


def test_admin_arbitration_route(client, app):
    _, _, admin, _, item = _marketplace()
    reservation, _ = _reserve(client, app, item)
    seller = item.seller
    from app.reservations.services import seller_confirm

    seller_confirm(seller, reservation.id)

    _login(client, "admin")
    assert client.get("/admin/reservations/").status_code == 200
    client.post(
        f"/admin/reservations/{reservation.id}/arbitrate",
        data={"outcome": "completed", "note": "已当面交付"},
    )
    assert reservation.status == ReservationStatus.COMPLETED.value


def test_admin_arbitration_route_error(client, app):
    _, _, _, _, item = _marketplace()
    reservation, _ = _reserve(client, app, item)

    _login(client, "admin")
    response = client.post(
        f"/admin/reservations/{reservation.id}/arbitrate",
        data={"outcome": "bogus"},
    )
    assert response.status_code == 302
    assert reservation.status == ReservationStatus.PENDING.value


def test_reservation_detail_route(client, app):
    _, _, _, _, item = _marketplace()
    reservation, _ = _reserve(client, app, item)

    _login(client, "buyer")
    assert client.get(f"/reservations/{reservation.id}").status_code == 200
    assert client.get("/reservations/999").status_code == 302


# --------------------------------------------------------------------------
# 认证路由
# --------------------------------------------------------------------------


def test_logout_and_anonymous_redirect(client, app):
    _marketplace()
    assert client.get("/auth/logout").status_code == 302
    response = client.get("/seller/items/")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_login_with_next_parameter(client, app):
    _marketplace()
    response = client.post(
        "/auth/login?next=/market/",
        data={"account": "buyer", "password": "password123"},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/market/")


def test_register_route_errors(client, app):
    _marketplace()
    mismatch = client.post(
        "/auth/register",
        data={
            "account": "new1",
            "nickname": "新人",
            "password": "password123",
            "confirm": "other123",
            "roles": ["buyer"],
        },
    )
    assert mismatch.status_code == 400

    duplicate = client.post(
        "/auth/register",
        data={
            "account": "buyer",
            "nickname": "重复",
            "password": "password123",
            "confirm": "password123",
            "roles": ["buyer"],
        },
    )
    assert duplicate.status_code == 400


def test_disabled_user_login_route(client, app):
    _, buyer, _, _, _ = _marketplace()
    buyer.status = UserStatus.DISABLED.value
    db.session.commit()

    response = _login(client, "buyer")
    assert response.status_code == 400
    assert "禁用" in response.get_data(as_text=True)


# --------------------------------------------------------------------------
# 管理后台路由与杂项
# --------------------------------------------------------------------------


def test_admin_user_routes(client, app):
    _, buyer, admin, _, _ = _marketplace()
    _login(client, "admin")

    assert (
        client.get("/admin/users/?keyword=buy&role=buyer&status=active").status_code
        == 200
    )
    client.post(f"/admin/users/{buyer.id}/disable", data={"reason": "违规"})
    assert db.session.get(User, buyer.id).status == UserStatus.DISABLED.value

    client.post(f"/admin/users/{buyer.id}/enable")
    assert db.session.get(User, buyer.id).status == UserStatus.ACTIVE.value

    buyer.failed_attempts = 3
    db.session.commit()
    client.post(f"/admin/users/{buyer.id}/unlock")
    assert db.session.get(User, buyer.id).failed_attempts == 0


def test_admin_cannot_disable_self_route(client, app):
    _, _, admin, _, _ = _marketplace()
    _login(client, "admin")

    response = client.post(f"/admin/users/{admin.id}/disable", follow_redirects=True)
    assert "不能修改自己的账号状态" in response.get_data(as_text=True)


def test_admin_logs_and_stats_routes(client, app):
    _marketplace()
    _login(client, "admin")

    assert client.get("/admin/logs/?action_type=approve_item").status_code == 200
    assert (
        client.get("/admin/logs/?date_from=2026-01-01&date_to=2026-12-31").status_code
        == 200
    )
    response = client.get("/admin/logs/?date_from=bad-date")
    assert response.status_code == 302

    stats_page = client.get("/admin/stats/")
    assert stats_page.status_code == 200
    body = stats_page.get_data(as_text=True)
    # Regression: dict keys named ``items`` must not resolve to dict.items().
    assert "built-in method" not in body

    dashboard = client.get("/admin/")
    assert dashboard.status_code == 200
    assert "built-in method" not in dashboard.get_data(as_text=True)


def test_health_and_cli_commands(app, client):
    assert client.get("/health").get_json() == {"status": "ok"}

    runner = app.test_cli_runner()
    assert "数据库表已创建" in runner.invoke(args=["init-db"]).output
    assert "示例数据已写入" in runner.invoke(args=["seed"]).output
    assert "重置" in runner.invoke(args=["reset-db"]).output


def test_user_loader_handles_invalid_ids(app, client):
    seller, _, _, _, _ = _marketplace()
    assert login_manager._user_callback(str(seller.id)).id == seller.id
    assert login_manager._user_callback("not-a-number") is None


def test_pagination_helpers():
    assert normalize_page("3") == 3
    assert normalize_page("-1") == 1
    assert normalize_page("abc") == 1
    assert normalize_page(None, default=2) == 2
    assert normalize_per_page("50") == 50
    assert normalize_per_page("7") == 20
    assert normalize_per_page("abc") == 20


# --------------------------------------------------------------------------
# 服务层边界：审核、下架、上传大小
# --------------------------------------------------------------------------


def test_approve_and_reject_validation(app):
    from app.items.services import approve_item, reject_item

    seller, buyer, admin, _, item = _marketplace(ItemStatus.PENDING.value)

    with pytest.raises(BusinessError):
        approve_item(buyer, item.id)
    with pytest.raises(BusinessError):
        approve_item(admin, 999)
    with pytest.raises(BusinessError):
        reject_item(admin, item.id, "   ")
    with pytest.raises(BusinessError):
        reject_item(admin, item.id, "长" * 201)
    with pytest.raises(BusinessError):
        reject_item(admin, 999, "原因合理")


def test_off_shelf_rejects_completed_and_reserved_items(app):
    from app.items.services import off_shelf

    seller, _, _, _, item = _marketplace(ItemStatus.COMPLETED.value)
    with pytest.raises(BusinessError) as done:
        off_shelf(seller, item.id)
    assert "已完成" in done.value.message

    other = make_item(
        seller, item.category, status=ItemStatus.RESERVED.value, name="已预约商品"
    )
    db.session.commit()
    with pytest.raises(BusinessError) as reserved:
        off_shelf(seller, other.id)
    assert "有效预约" in reserved.value.message


def test_upload_size_limit(client, app):
    _, _, _, category, _ = _marketplace()
    _login(client, "seller")

    big = BytesIO(b"0" * (5 * 1024 * 1024 + 1))
    data = _form(category)
    data["images"] = (big, "big.png")
    response = _post_form(client, "/seller/items/new", data)
    assert response.status_code == 400
    assert "5 MB" in response.get_data(as_text=True)


def test_admin_user_route_handles_missing_user(client, app):
    _marketplace()
    _login(client, "admin")

    response = client.post("/admin/users/999/disable", follow_redirects=True)
    assert "用户不存在" in response.get_data(as_text=True)

    response = client.post("/admin/users/999/unlock", follow_redirects=True)
    assert "用户不存在" in response.get_data(as_text=True)


def test_edit_item_route_renders_validation_error(client, app):
    _, _, _, category, item = _marketplace(ItemStatus.DRAFT.value)
    _login(client, "seller")

    data = _form(category, description="太短")
    data.pop("images")
    data["keep_image"] = str(item.images[0].id)
    response = client.post(
        f"/seller/items/{item.id}/edit", data=data, content_type="multipart/form-data"
    )
    assert response.status_code == 400
    assert "描述需要 10–2000 个字符" in response.get_data(as_text=True)
