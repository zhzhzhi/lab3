"""Reservation lifecycle, idempotency and route tests."""

from datetime import timedelta

import pytest

from app.common.clock import utcnow
from app.common.errors import BusinessError
from app.enums import ItemStatus, ReservationStatus, Role
from app.extensions import db
from app.models import IdempotencyRecord, Item, Reservation
from app.reservations.services import (
    arbitrate,
    buyer_cancel,
    buyer_complete,
    create_reservation,
    expire_overdue,
    seller_cancel,
    seller_confirm,
)
from tests.helpers import make_category, make_item, make_user


def _marketplace():
    seller = make_user("seller", roles=[Role.SELLER.value, Role.BUYER.value])
    buyer = make_user("buyer")
    other = make_user("other")
    category = make_category()
    item = make_item(seller, category)
    return seller, buyer, other, item


def _login(client, account, password="password123"):
    return client.post("/auth/login", data={"account": account, "password": password})


def test_create_reservation_locks_item(app):
    seller, buyer, _, item = _marketplace()

    reservation, replayed = create_reservation(buyer, item.id, "req-000001")

    assert replayed is False
    assert reservation.status == ReservationStatus.PENDING.value
    assert reservation.expires_at - reservation.created_at == timedelta(hours=48)
    assert db.session.get(Item, item.id).status == ItemStatus.RESERVED.value


def test_create_reservation_requires_buyer_role(app):
    seller, _, _, item = _marketplace()
    admin = make_user("admin2", roles=[Role.ADMIN.value])
    db.session.commit()

    with pytest.raises(BusinessError):
        create_reservation(admin, item.id, "req-000002")
    assert db.session.get(Item, item.id).status == ItemStatus.PUBLISHED.value


def test_cannot_reserve_own_or_unpublished_item(app):
    seller, buyer, _, item = _marketplace()
    seller_roles = seller.roles
    assert Role.BUYER.value in seller_roles

    with pytest.raises(BusinessError) as own:
        create_reservation(seller, item.id, "req-000003")
    assert "自己" in own.value.message

    draft = make_item(seller, item.category, status=ItemStatus.DRAFT.value)
    with pytest.raises(BusinessError):
        create_reservation(buyer, draft.id, "req-000004")


def test_second_buyer_cannot_take_reserved_item(app):
    _, buyer, other, item = _marketplace()
    create_reservation(buyer, item.id, "req-000005")

    with pytest.raises(BusinessError) as excinfo:
        create_reservation(other, item.id, "req-000006")
    assert "不可预约" in excinfo.value.message
    assert Reservation.query.count() == 1


def test_duplicate_request_id_is_idempotent(app):
    _, buyer, _, item = _marketplace()

    first, _ = create_reservation(buyer, item.id, "req-000007")
    second, replayed = create_reservation(buyer, item.id, "req-000007")

    assert replayed is True
    assert second.id == first.id
    assert Reservation.query.count() == 1


def test_seller_confirm_moves_item_to_confirmed(app):
    seller, buyer, _, item = _marketplace()
    reservation, _ = create_reservation(buyer, item.id, "req-000008")

    seller_confirm(seller, reservation.id)

    assert reservation.status == ReservationStatus.CONFIRMED.value
    assert reservation.seller_handled_at is not None
    assert db.session.get(Item, item.id).status == ItemStatus.CONFIRMED.value


def test_concurrent_reservation_conflict_is_reported(app):
    seller, buyer, other, item = _marketplace()
    # Simulate another buyer winning the race: an active row exists while the
    # item row still reads as published for the request being served.
    db.session.add(
        Reservation(
            item_id=item.id,
            buyer_id=other.id,
            request_id="race-first",
            status=ReservationStatus.PENDING.value,
            expires_at=utcnow() + timedelta(hours=48),
        )
    )
    db.session.commit()

    with pytest.raises(BusinessError) as excinfo:
        create_reservation(buyer, item.id, "race-second")
    assert "其他买家" in excinfo.value.message


def test_idempotency_window_purges_old_records(app):
    _, buyer, _, item = _marketplace()
    first, _ = create_reservation(buyer, item.id, "req-stale")
    buyer_cancel(buyer, first.id)

    record = IdempotencyRecord.query.one()
    record.created_at = utcnow() - timedelta(hours=25)
    db.session.commit()

    second, replayed = create_reservation(buyer, item.id, "req-stale")

    assert replayed is False
    assert second.id != first.id
    assert IdempotencyRecord.query.count() == 1


def test_only_item_seller_can_confirm(app):
    seller, buyer, other, item = _marketplace()
    reservation, _ = create_reservation(buyer, item.id, "req-000009")

    with pytest.raises(BusinessError) as excinfo:
        seller_confirm(other, reservation.id)
    assert excinfo.value.status_code == 403


def test_seller_cancel_puts_item_back_on_sale(app):
    seller, buyer, _, item = _marketplace()
    reservation, _ = create_reservation(buyer, item.id, "req-000010")

    seller_cancel(seller, reservation.id, "商品已卖出")

    assert reservation.status == ReservationStatus.CANCELLED.value
    assert reservation.cancel_reason == "商品已卖出"
    assert db.session.get(Item, item.id).status == ItemStatus.PUBLISHED.value


def test_buyer_cancel_puts_item_back_on_sale(app):
    _, buyer, _, item = _marketplace()
    reservation, _ = create_reservation(buyer, item.id, "req-000011")

    buyer_cancel(buyer, reservation.id, "不想要了")

    assert reservation.status == ReservationStatus.CANCELLED.value
    assert db.session.get(Item, item.id).status == ItemStatus.PUBLISHED.value


def test_buyer_complete_requires_confirmation(app):
    seller, buyer, _, item = _marketplace()
    reservation, _ = create_reservation(buyer, item.id, "req-000012")

    with pytest.raises(BusinessError):
        buyer_complete(buyer, reservation.id)

    seller_confirm(seller, reservation.id)
    buyer_complete(buyer, reservation.id)

    assert reservation.status == ReservationStatus.COMPLETED.value
    assert reservation.completed_at is not None
    assert db.session.get(Item, item.id).status == ItemStatus.COMPLETED.value


def test_pending_reservation_expires_after_48_hours(app):
    _, buyer, _, item = _marketplace()
    reservation, _ = create_reservation(buyer, item.id, "req-000013")

    reservation.expires_at = utcnow() - timedelta(minutes=1)
    db.session.commit()

    assert expire_overdue() == 1
    assert reservation.status == ReservationStatus.EXPIRED.value
    assert db.session.get(Item, item.id).status == ItemStatus.PUBLISHED.value


def test_confirm_after_deadline_expires_instead(app):
    seller, buyer, _, item = _marketplace()
    reservation, _ = create_reservation(buyer, item.id, "req-000014")
    reservation.expires_at = utcnow() - timedelta(hours=1)
    db.session.commit()

    with pytest.raises(BusinessError) as excinfo:
        seller_confirm(seller, reservation.id)
    assert "失效" in str(excinfo.value)
    assert db.session.get(Item, item.id).status == ItemStatus.PUBLISHED.value


def test_admin_arbitration(app):
    seller, buyer, _, item = _marketplace()
    admin = make_user("admin", roles=[Role.ADMIN.value])
    db.session.commit()
    reservation, _ = create_reservation(buyer, item.id, "req-000015")
    seller_confirm(seller, reservation.id)

    arbitrate(admin, reservation.id, "completed", "双方确认已交付")

    assert reservation.status == ReservationStatus.COMPLETED.value
    assert db.session.get(Item, item.id).status == ItemStatus.COMPLETED.value


def test_non_admin_cannot_arbitrate(app):
    seller, buyer, _, item = _marketplace()
    reservation, _ = create_reservation(buyer, item.id, "req-000016")
    seller_confirm(seller, reservation.id)

    with pytest.raises(BusinessError) as excinfo:
        arbitrate(buyer, reservation.id, "cancelled")
    assert excinfo.value.status_code == 403


def test_reserve_route_creates_one_reservation(client, app):
    _, buyer, _, item = _marketplace()

    _login(client, "buyer")
    response = client.post(
        f"/reservations/item/{item.id}", data={"request_id": "req-route-1"}
    )
    assert response.status_code == 302

    reservation = Reservation.query.one()
    assert reservation.buyer_id == buyer.id
    assert db.session.get(Item, item.id).status == ItemStatus.RESERVED.value


def test_reserve_route_deduplicates_double_submit(client, app):
    _, _, _, item = _marketplace()
    _login(client, "buyer")

    for _ in range(2):
        client.post(f"/reservations/item/{item.id}", data={"request_id": "req-route-2"})

    assert Reservation.query.count() == 1


def test_reservation_pages_render(client, app):
    seller, buyer, _, item = _marketplace()
    admin = make_user("admin", roles=[Role.ADMIN.value])
    db.session.commit()
    reservation, _ = create_reservation(buyer, item.id, "req-000017")
    seller_confirm(seller, reservation.id)

    _login(client, "buyer")
    assert client.get("/reservations/").status_code == 200
    assert client.get(f"/reservations/{reservation.id}").status_code == 200
    assert client.get("/seller/reservations/").status_code == 403

    client.get("/auth/logout")
    _login(client, "seller")
    assert client.get("/seller/reservations/").status_code == 200

    client.get("/auth/logout")
    _login(client, "admin")
    assert client.get("/admin/reservations/").status_code == 200


def test_seller_page_lists_pending_reservation(client, app):
    seller, buyer, _, item = _marketplace()
    create_reservation(buyer, item.id, "req-000018")

    _login(client, "seller")
    body = client.get("/seller/reservations/").get_data(as_text=True)

    assert item.name in body
    assert buyer.nickname in body
    assert "确认预约" in body


def test_confirm_route_moves_state(client, app):
    seller, buyer, _, item = _marketplace()
    reservation, _ = create_reservation(buyer, item.id, "req-000019")

    _login(client, "seller")
    client.post(f"/seller/reservations/{reservation.id}/confirm")

    assert reservation.status == ReservationStatus.CONFIRMED.value


def test_contact_visible_only_after_confirmation(client, app):
    seller, buyer, _, item = _marketplace()
    item.contact = "微信：confirmed-only"
    db.session.commit()
    _login(client, "buyer")
    body = client.get(f"/market/{item.id}").get_data(as_text=True)
    assert "确认预约后可见" in body
    assert "confirmed-only" not in body

    reservation, _ = create_reservation(buyer, item.id, "req-000020")
    seller_confirm(seller, reservation.id)
    body = client.get(f"/market/{item.id}").get_data(as_text=True)
    assert item.contact in body
