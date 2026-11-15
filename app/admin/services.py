"""Admin governance: user status, audit log search and statistics."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from sqlalchemy import func, or_

from ..common.audit import record_log
from ..common.clock import clock
from ..common.errors import BusinessError
from ..common.pagination import normalize_page, normalize_per_page
from ..enums import (
    ITEM_STATUS_LABELS,
    REPORT_STATUS_LABELS,
    RESERVATION_STATUS_LABELS,
    ItemStatus,
    ReportStatus,
    ReservationStatus,
    Role,
    UserStatus,
)
from ..extensions import db
from ..models import Item, OperationLog, Report, Reservation, User

ROLE_VALUES = {role.value for role in Role}
USER_STATUS_VALUES = {status.value for status in UserStatus}


def search_users(keyword: str = "", role: str = "", status: str = "") -> list[User]:
    """Return matching users, newest first. Role is filtered in Python because
    the roles column is JSON and SQLite cannot index it portably."""
    keyword = (keyword or "").strip()
    query = User.query
    if keyword:
        query = query.filter(
            or_(User.account.contains(keyword), User.nickname.contains(keyword))
        )
    if status in USER_STATUS_VALUES:
        query = query.filter(User.status == status)
    users = query.order_by(User.created_at.desc(), User.id.desc()).all()
    if role in ROLE_VALUES:
        users = [user for user in users if user.has_role(role)]
    return users


def _target_user(user_id: int) -> User:
    user = db.session.get(User, user_id)
    if user is None:
        raise BusinessError("用户不存在。", status_code=404, next_step="返回用户列表。")
    return user


def set_user_status(admin, user_id: int, disabled: bool, reason: str = "") -> User:
    if not admin.has_role(Role.ADMIN):
        raise BusinessError("只有管理员可以管理用户。", status_code=403)
    user = _target_user(user_id)
    if user.id == admin.id:
        raise BusinessError("不能修改自己的账号状态。")
    if disabled and user.is_admin:
        raise BusinessError("不能禁用管理员账号。", current_state=user.status_label)

    user.status = UserStatus.DISABLED.value if disabled else UserStatus.ACTIVE.value
    if not disabled:
        user.failed_attempts = 0
        user.locked_until = None
    reason = (reason or "").strip()[:200]
    record_log(
        admin.id,
        "disable_user" if disabled else "enable_user",
        "user",
        user.id,
        detail=reason or user.account,
    )
    db.session.commit()
    return user


def unlock_user(admin, user_id: int) -> User:
    if not admin.has_role(Role.ADMIN):
        raise BusinessError("只有管理员可以管理用户。", status_code=403)
    user = _target_user(user_id)
    user.failed_attempts = 0
    user.locked_until = None
    record_log(admin.id, "unlock_user", "user", user.id, detail=user.account)
    db.session.commit()
    return user


def _parse_date(value: str | None) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.combine(datetime.strptime(value, "%Y-%m-%d").date(), time.min)
    except ValueError as exc:
        raise BusinessError(
            "日期格式不正确。", next_step="使用 YYYY-MM-DD 格式，例如 2026-11-15。"
        ) from exc


def search_logs(filters: dict):
    """Paginated audit log search with operator, action and date filters."""
    query = OperationLog.query.outerjoin(User, OperationLog.operator_id == User.id)

    action_type = (filters.get("action_type") or "").strip()
    if action_type:
        query = query.filter(OperationLog.action_type == action_type)

    target_type = (filters.get("target_type") or "").strip()
    if target_type:
        query = query.filter(OperationLog.target_type == target_type)

    operator = (filters.get("operator") or "").strip()
    if operator:
        query = query.filter(
            or_(
                User.account.contains(operator),
                User.nickname.contains(operator),
            )
        )

    date_from = _parse_date(filters.get("date_from"))
    date_to = _parse_date(filters.get("date_to"))
    if date_from and date_to and date_from > date_to:
        raise BusinessError("开始日期不能晚于结束日期。", next_step="调整日期范围。")
    if date_from:
        query = query.filter(OperationLog.created_at >= date_from)
    if date_to:
        query = query.filter(OperationLog.created_at < date_to + timedelta(days=1))

    query = query.order_by(OperationLog.created_at.desc(), OperationLog.id.desc())
    page = normalize_page(filters.get("page"))
    per_page = normalize_per_page(filters.get("per_page"))
    return query.paginate(page=page, per_page=per_page, error_out=False)


def action_type_options() -> list[str]:
    rows = db.session.query(OperationLog.action_type).distinct().all()
    return sorted({row[0] for row in rows})


def target_type_options() -> list[str]:
    rows = db.session.query(OperationLog.target_type).distinct().all()
    return sorted({row[0] for row in rows})


def _status_counts(model, column) -> dict[str, int]:
    rows = db.session.query(column, func.count(model.id)).group_by(column).all()
    return dict(rows)


def _user_counts() -> dict[str, int]:
    return {
        "total": User.query.count(),
        "active": User.query.filter_by(status=UserStatus.ACTIVE.value).count(),
        "disabled": User.query.filter_by(status=UserStatus.DISABLED.value).count(),
        "admins": len([user for user in User.query.all() if user.has_role(Role.ADMIN)]),
    }


def _recent_days(days: int = 7) -> list[dict]:
    """Daily counts for items created, reservations created and deals completed."""
    today = clock.now().date()
    start = datetime.combine(today - timedelta(days=days - 1), time.min)

    item_rows = (
        db.session.query(func.date(Item.created_at), func.count(Item.id))
        .filter(Item.created_at >= start)
        .group_by(func.date(Item.created_at))
        .all()
    )
    reservation_rows = (
        db.session.query(func.date(Reservation.created_at), func.count(Reservation.id))
        .filter(Reservation.created_at >= start)
        .group_by(func.date(Reservation.created_at))
        .all()
    )
    completed_rows = (
        db.session.query(
            func.date(Reservation.completed_at), func.count(Reservation.id)
        )
        .filter(
            Reservation.completed_at.isnot(None),
            Reservation.completed_at >= start,
            Reservation.status == ReservationStatus.COMPLETED.value,
        )
        .group_by(func.date(Reservation.completed_at))
        .all()
    )

    items = {str(day): count for day, count in item_rows}
    reservations = {str(day): count for day, count in reservation_rows}
    completed = {str(day): count for day, count in completed_rows}

    result = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        key = day.isoformat()
        result.append(
            {
                "date": day.strftime("%m-%d"),
                "items": items.get(key, 0),
                "reservations": reservations.get(key, 0),
                "completed": completed.get(key, 0),
            }
        )
    return result


def dashboard_stats() -> dict:
    item_counts = _status_counts(Item, Item.status)
    reservation_counts = _status_counts(Reservation, Reservation.status)
    report_counts = _status_counts(Report, Report.status)
    return {
        "items": {
            "total": sum(item_counts.values()),
            "by_status": {
                status.value: item_counts.get(status.value, 0) for status in ItemStatus
            },
            "labels": ITEM_STATUS_LABELS,
        },
        "reservations": {
            "total": sum(reservation_counts.values()),
            "by_status": {
                status.value: reservation_counts.get(status.value, 0)
                for status in ReservationStatus
            },
            "labels": RESERVATION_STATUS_LABELS,
        },
        "reports": {
            "total": sum(report_counts.values()),
            "by_status": {
                status.value: report_counts.get(status.value, 0)
                for status in ReportStatus
            },
            "labels": REPORT_STATUS_LABELS,
        },
        "users": _user_counts(),
        "recent": _recent_days(),
        "pending_review": Item.query.filter_by(status=ItemStatus.PENDING.value).count(),
        "pending_reports": Report.query.filter_by(
            status=ReportStatus.PENDING.value
        ).count(),
    }
