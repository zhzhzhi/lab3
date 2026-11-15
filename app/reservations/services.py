"""Reservation lifecycle: create, confirm, cancel, complete, expire and arbitrate.

Business rules implemented here (see the Lab 2 class and state diagrams):

* One item can have at most one active reservation (pending or confirmed).
* A reservation expires 48 hours after creation if the seller does not respond.
  Expiry is applied lazily: every query path calls ``expire_overdue`` first, so
  the system does not need a background scheduler.
* Creating a reservation is idempotent for a given ``request_id``: a retry from
  the client returns the original reservation instead of creating a second one.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

from flask import current_app
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..common.audit import record_log
from ..common.clock import clock
from ..common.errors import BusinessError
from ..enums import (
    ACTIVE_RESERVATION_STATUSES,
    ItemStatus,
    ReservationStatus,
    Role,
)
from ..extensions import db
from ..models import IdempotencyRecord, Item, Reservation

CREATE_ACTION = "create_reservation"
REQUEST_ID_MIN = 8
REQUEST_ID_MAX = 64


def _expire_hours() -> int:
    return int(current_app.config["RESERVATION_EXPIRE_HOURS"])


def _load_reservation(reservation_id: int) -> Reservation:
    reservation = db.session.get(Reservation, reservation_id)
    if reservation is None:
        raise BusinessError("预约不存在。", status_code=404, next_step="返回预约列表。")
    return reservation


def _require_status(
    reservation: Reservation, allowed: tuple[str, ...], action: str
) -> None:
    if reservation.status not in allowed:
        raise BusinessError(
            f"当前状态不能{action}。",
            current_state=reservation.status_label,
            next_step="刷新页面，按当前状态选择可用操作。",
        )


def _release_item(item: Item) -> None:
    """Put the item back on the market after a reservation is no longer active."""
    if item.status in (ItemStatus.RESERVED.value, ItemStatus.CONFIRMED.value):
        item.status = ItemStatus.PUBLISHED.value
        item.version += 1


def _expire_single(reservation: Reservation) -> None:
    reservation.status = ReservationStatus.EXPIRED.value
    reservation.version += 1
    _release_item(reservation.item)
    record_log(
        None,
        "expire_reservation",
        "reservation",
        reservation.id,
        detail="超过 48 小时卖家未处理，预约自动失效",
    )


def expire_overdue(now=None) -> int:
    """Mark pending reservations whose deadline has passed as expired."""
    moment = now or clock.now()
    overdue = (
        Reservation.query.filter(
            Reservation.status == ReservationStatus.PENDING.value,
            Reservation.expires_at < moment,
        )
        .order_by(Reservation.id.asc())
        .all()
    )
    if not overdue:
        return 0
    for reservation in overdue:
        _expire_single(reservation)
    db.session.commit()
    return len(overdue)


def _normalize_request_id(raw: str | None) -> str:
    value = (raw or "").strip()
    if not value:
        return uuid.uuid4().hex
    if not REQUEST_ID_MIN <= len(value) <= REQUEST_ID_MAX:
        raise BusinessError(
            "请求编号不合法。",
            next_step="刷新页面后重新提交预约。",
        )
    return value


def _find_idempotent_record(
    buyer_id: int, item_id: int, request_id: str
) -> IdempotencyRecord | None:
    return IdempotencyRecord.query.filter_by(
        user_id=buyer_id,
        action=CREATE_ACTION,
        item_id=item_id,
        request_id=request_id,
    ).first()


def _replay(record: IdempotencyRecord) -> Reservation:
    try:
        reservation_id = int(json.loads(record.result_json)["reservation_id"])
    except (ValueError, KeyError, TypeError) as exc:  # pragma: no cover - 数据损坏
        raise BusinessError("重复请求的记录已损坏。", next_step="联系管理员。") from exc
    reservation = db.session.get(Reservation, reservation_id)
    if reservation is None:  # pragma: no cover - 记录与预约应同时存在
        raise BusinessError("原预约已不存在。", next_step="重新发起预约。")
    return reservation


def _purge_stale_records() -> None:
    """Drop request ids older than the idempotency window (default 24h)."""
    hours = int(current_app.config["IDEMPOTENCY_WINDOW_HOURS"])
    cutoff = clock.now() - timedelta(hours=hours)
    IdempotencyRecord.query.filter(IdempotencyRecord.created_at < cutoff).delete(
        synchronize_session=False
    )


def _lock_item(item_id: int) -> Item | None:
    """Fetch the item while taking a row lock (no-op on SQLite, honest on MySQL)."""
    statement = select(Item).where(Item.id == item_id).with_for_update()
    return db.session.execute(statement).scalar_one_or_none()


def create_reservation(buyer, item_id: int, request_id: str | None = None):
    """Create a pending reservation, returning ``(reservation, replayed)``."""
    if not buyer.is_buyer:
        raise BusinessError("只有买家可以预约商品。", status_code=403)

    request_id = _normalize_request_id(request_id)
    _purge_stale_records()
    record = _find_idempotent_record(buyer.id, item_id, request_id)
    if record is not None:
        return _replay(record), True

    expire_overdue()

    item = _lock_item(item_id)
    if item is None:
        raise BusinessError("商品不存在。", status_code=404, next_step="返回商品广场。")
    if item.seller_id == buyer.id:
        raise BusinessError(
            "不能预约自己发布的商品。", next_step="看看其他卖家的商品。"
        )
    if item.status != ItemStatus.PUBLISHED.value:
        raise BusinessError(
            "该商品当前不可预约。",
            current_state=item.status_label,
            next_step="挑选其他在售商品，或稍后再来。",
        )

    moment = clock.now()
    reservation = Reservation(
        item_id=item.id,
        buyer_id=buyer.id,
        request_id=request_id,
        status=ReservationStatus.PENDING.value,
        created_at=moment,
        expires_at=moment + timedelta(hours=_expire_hours()),
    )
    item.status = ItemStatus.RESERVED.value
    item.version += 1
    db.session.add(reservation)
    try:
        db.session.flush()
        db.session.add(
            IdempotencyRecord(
                user_id=buyer.id,
                action=CREATE_ACTION,
                item_id=item.id,
                request_id=request_id,
                result_json=json.dumps({"reservation_id": reservation.id}),
            )
        )
        record_log(
            buyer.id,
            CREATE_ACTION,
            "reservation",
            reservation.id,
            detail=item.name,
        )
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        # A concurrent request may have claimed the item, or the same request id
        # may have won the race: check the latter before reporting a conflict.
        replay_record = _find_idempotent_record(buyer.id, item_id, request_id)
        if replay_record is not None:
            return _replay(replay_record), True
        raise BusinessError(
            "该商品刚刚被其他买家预约了。",
            current_state="已预约",
            next_step="返回商品广场看看其他商品。",
        ) from exc

    return reservation, False


def seller_confirm(seller, reservation_id: int) -> Reservation:
    expire_overdue()
    reservation = _load_reservation(reservation_id)
    if reservation.item.seller_id != seller.id:
        raise BusinessError("只能处理自己商品的预约。", status_code=403)
    if (
        reservation.status == ReservationStatus.PENDING.value
        and reservation.expires_at < clock.now()
    ):
        _expire_single(reservation)
        db.session.commit()
        raise BusinessError(
            "预约已超过 48 小时，已自动失效。",
            current_state="已失效",
            next_step="让买家重新发起预约。",
        )
    _require_status(reservation, (ReservationStatus.PENDING.value,), "确认预约")
    reservation.status = ReservationStatus.CONFIRMED.value
    reservation.seller_handled_at = clock.now()
    reservation.version += 1
    reservation.item.status = ItemStatus.CONFIRMED.value
    reservation.item.version += 1
    record_log(
        seller.id,
        "confirm_reservation",
        "reservation",
        reservation.id,
        detail=reservation.item.name,
    )
    db.session.commit()
    return reservation


def seller_cancel(seller, reservation_id: int, reason: str = "") -> Reservation:
    reservation = _load_reservation(reservation_id)
    if reservation.item.seller_id != seller.id:
        raise BusinessError("只能处理自己商品的预约。", status_code=403)
    _require_status(
        reservation,
        (ReservationStatus.PENDING.value, ReservationStatus.CONFIRMED.value),
        "取消预约",
    )
    reason = (reason or "卖家取消").strip()[:200]
    reservation.status = ReservationStatus.CANCELLED.value
    reservation.cancel_reason = reason
    reservation.seller_handled_at = clock.now()
    reservation.version += 1
    _release_item(reservation.item)
    record_log(
        seller.id,
        "seller_cancel_reservation",
        "reservation",
        reservation.id,
        detail=reason,
    )
    db.session.commit()
    return reservation


def buyer_cancel(buyer, reservation_id: int, reason: str = "") -> Reservation:
    reservation = _load_reservation(reservation_id)
    if reservation.buyer_id != buyer.id:
        raise BusinessError("只能取消自己的预约。", status_code=403)
    _require_status(
        reservation,
        (ReservationStatus.PENDING.value, ReservationStatus.CONFIRMED.value),
        "取消预约",
    )
    reason = (reason or "买家取消").strip()[:200]
    reservation.status = ReservationStatus.CANCELLED.value
    reservation.cancel_reason = reason
    reservation.version += 1
    _release_item(reservation.item)
    record_log(
        buyer.id,
        "buyer_cancel_reservation",
        "reservation",
        reservation.id,
        detail=reason,
    )
    db.session.commit()
    return reservation


def buyer_complete(buyer, reservation_id: int) -> Reservation:
    reservation = _load_reservation(reservation_id)
    if reservation.buyer_id != buyer.id:
        raise BusinessError("只能确认自己的预约。", status_code=403)
    _require_status(reservation, (ReservationStatus.CONFIRMED.value,), "确认交易完成")
    reservation.status = ReservationStatus.COMPLETED.value
    reservation.completed_at = clock.now()
    reservation.version += 1
    reservation.item.status = ItemStatus.COMPLETED.value
    reservation.item.version += 1
    record_log(
        buyer.id,
        "complete_reservation",
        "reservation",
        reservation.id,
        detail=reservation.item.name,
    )
    db.session.commit()
    return reservation


ARBITRATION_OUTCOMES = {
    ReservationStatus.COMPLETED.value: "判定交易完成",
    ReservationStatus.CANCELLED.value: "判定取消并恢复在售",
}


def arbitrate(admin, reservation_id: int, outcome: str, note: str = "") -> Reservation:
    """Admin resolves a disputed (confirmed) reservation."""
    if not admin.has_role(Role.ADMIN):
        raise BusinessError("只有管理员可以仲裁。", status_code=403)
    if outcome not in ARBITRATION_OUTCOMES:
        raise BusinessError("仲裁结论不正确。", next_step="选择“完成”或“取消”。")
    note = (note or "").strip()[:200]

    reservation = _load_reservation(reservation_id)
    _require_status(
        reservation,
        (ReservationStatus.CONFIRMED.value,),
        "仲裁",
    )
    reservation.status = outcome
    reservation.version += 1
    if outcome == ReservationStatus.COMPLETED.value:
        reservation.completed_at = clock.now()
        reservation.item.status = ItemStatus.COMPLETED.value
    else:
        reservation.cancel_reason = note or "管理员仲裁取消"
        _release_item(reservation.item)
    reservation.item.version += 1
    record_log(
        admin.id,
        "arbitrate_reservation",
        "reservation",
        reservation.id,
        detail=note or ARBITRATION_OUTCOMES[outcome],
    )
    db.session.commit()
    return reservation


def reservation_counts(user_id: int, as_seller: bool = False) -> dict[str, int]:
    counts = {status.value: 0 for status in ReservationStatus}
    query = db.session.query(Reservation.status, func.count(Reservation.id))
    if as_seller:
        query = query.join(Item, Reservation.item_id == Item.id).filter(
            Item.seller_id == user_id
        )
    else:
        query = query.filter(Reservation.buyer_id == user_id)
    for status, count in query.group_by(Reservation.status).all():
        counts[status] = count
    return counts


def buyer_reservations(buyer_id: int, status: str | None = None):
    query = Reservation.query.filter_by(buyer_id=buyer_id)
    if status:
        query = query.filter_by(status=status)
    return query.order_by(Reservation.created_at.desc(), Reservation.id.desc())


def seller_reservations(seller_id: int, status: str | None = None):
    query = Reservation.query.join(Item, Reservation.item_id == Item.id).filter(
        Item.seller_id == seller_id
    )
    if status:
        query = query.filter(Reservation.status == status)
    return query.order_by(Reservation.created_at.desc(), Reservation.id.desc())


def disputed_reservations(status: str | None = None):
    """Reservations the admin may arbitrate, newest first."""
    query = Reservation.query.filter(
        Reservation.status.in_(
            (ReservationStatus.CONFIRMED.value, ReservationStatus.PENDING.value)
        )
    )
    if status:
        query = query.filter(Reservation.status == status)
    return query.order_by(Reservation.created_at.asc(), Reservation.id.asc())


def contact_visible_to(viewer, item: Item) -> bool:
    """Contact details are revealed once a reservation is confirmed."""
    if viewer is None or not getattr(viewer, "is_authenticated", False):
        return False
    if viewer.is_admin or item.seller_id == viewer.id:
        return True
    return (
        Reservation.query.filter(
            Reservation.item_id == item.id,
            Reservation.buyer_id == viewer.id,
            Reservation.status.in_(
                (
                    ReservationStatus.CONFIRMED.value,
                    ReservationStatus.COMPLETED.value,
                )
            ),
        ).first()
        is not None
    )


def active_reservation(item_id: int) -> Reservation | None:
    return Reservation.query.filter(
        Reservation.item_id == item_id,
        Reservation.status.in_(ACTIVE_RESERVATION_STATUSES),
    ).first()
