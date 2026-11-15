"""Domain enumerations and human-readable labels."""

from enum import Enum


class Role(str, Enum):
    BUYER = "buyer"
    SELLER = "seller"
    ADMIN = "admin"


class UserStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class ItemStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    PUBLISHED = "published"
    RESERVED = "reserved"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    OFF_SHELF = "off_shelf"
    REJECTED = "rejected"


class ReservationStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ReportStatus(str, Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    REJECTED = "rejected"


class ActionResult(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"


ROLE_LABELS = {
    Role.BUYER.value: "买家",
    Role.SELLER.value: "卖家",
    Role.ADMIN.value: "管理员",
}

USER_STATUS_LABELS = {
    UserStatus.ACTIVE.value: "正常",
    UserStatus.DISABLED.value: "已禁用",
}

ITEM_STATUS_LABELS = {
    ItemStatus.DRAFT.value: "草稿",
    ItemStatus.PENDING.value: "待审核",
    ItemStatus.PUBLISHED.value: "已发布",
    ItemStatus.RESERVED.value: "已预约",
    ItemStatus.CONFIRMED.value: "已确认",
    ItemStatus.COMPLETED.value: "已完成",
    ItemStatus.OFF_SHELF.value: "已下架",
    ItemStatus.REJECTED.value: "已驳回",
}

RESERVATION_STATUS_LABELS = {
    ReservationStatus.PENDING.value: "待确认",
    ReservationStatus.CONFIRMED.value: "已确认",
    ReservationStatus.COMPLETED.value: "已完成",
    ReservationStatus.CANCELLED.value: "已取消",
    ReservationStatus.EXPIRED.value: "已失效",
}

REPORT_STATUS_LABELS = {
    ReportStatus.PENDING.value: "待处理",
    ReportStatus.RESOLVED.value: "成立",
    ReportStatus.REJECTED.value: "不成立",
}

ACTIVE_RESERVATION_STATUSES = (
    ReservationStatus.PENDING.value,
    ReservationStatus.CONFIRMED.value,
)


def label(mapping: dict[str, str], value: str) -> str:
    """Return a display label, falling back to the raw value."""
    return mapping.get(value, value)
