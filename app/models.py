"""SQLAlchemy models for the campus second-hand marketplace."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from flask_login import UserMixin

from .common.clock import utcnow
from .enums import (
    ACTIVE_RESERVATION_STATUSES,
    ITEM_STATUS_LABELS,
    REPORT_STATUS_LABELS,
    RESERVATION_STATUS_LABELS,
    ROLE_LABELS,
    USER_STATUS_LABELS,
    ItemStatus,
    ReportStatus,
    ReservationStatus,
    Role,
    UserStatus,
)
from .extensions import db

password_hasher = PasswordHasher()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    account = db.Column(db.String(50), unique=True, nullable=False, index=True)
    nickname = db.Column(db.String(50), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    contact = db.Column(db.String(100), nullable=False, default="")
    roles = db.Column(db.JSON, nullable=False, default=lambda: [Role.BUYER.value])
    status = db.Column(db.String(20), nullable=False, default=UserStatus.ACTIVE.value)
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    items = db.relationship("Item", back_populates="seller", lazy="dynamic")
    reservations = db.relationship(
        "Reservation", back_populates="buyer", lazy="dynamic"
    )
    reports = db.relationship(
        "Report",
        foreign_keys="Report.reporter_id",
        back_populates="reporter",
        lazy="dynamic",
    )
    handled_reports = db.relationship(
        "Report",
        foreign_keys="Report.handled_by",
        back_populates="handler",
        lazy="dynamic",
    )
    logs = db.relationship("OperationLog", back_populates="operator", lazy="dynamic")

    def set_password(self, raw_password: str) -> None:
        self.password_hash = password_hasher.hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        try:
            return password_hasher.verify(self.password_hash, raw_password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def has_role(self, role: Role | str) -> bool:
        value = role.value if isinstance(role, Role) else role
        return value in (self.roles or [])

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE.value

    @property
    def is_admin(self) -> bool:
        return self.has_role(Role.ADMIN)

    @property
    def is_buyer(self) -> bool:
        return self.has_role(Role.BUYER)

    @property
    def is_seller(self) -> bool:
        return self.has_role(Role.SELLER)

    @property
    def role_labels(self) -> list[str]:
        return [ROLE_LABELS.get(role, role) for role in (self.roles or [])]

    @property
    def status_label(self) -> str:
        return USER_STATUS_LABELS.get(self.status, self.status)

    def __repr__(self) -> str:
        return f"<User {self.account}>"


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    items = db.relationship("Item", back_populates="category", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<Category {self.name}>"


class Item(db.Model):
    __tablename__ = "items"

    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    category_id = db.Column(
        db.Integer, db.ForeignKey("categories.id"), nullable=False, index=True
    )
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False, index=True)
    contact = db.Column(db.String(100), nullable=False)
    status = db.Column(
        db.String(20), nullable=False, default=ItemStatus.DRAFT.value, index=True
    )
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    published_at = db.Column(db.DateTime, nullable=True, index=True)
    off_shelf_reason = db.Column(db.String(200), nullable=True)
    reject_reason = db.Column(db.String(200), nullable=True)
    version = db.Column(db.Integer, nullable=False, default=0)

    seller = db.relationship("User", back_populates="items")
    category = db.relationship("Category", back_populates="items")
    images = db.relationship(
        "ItemImage",
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="ItemImage.sort_order",
    )
    reservations = db.relationship("Reservation", back_populates="item", lazy="dynamic")
    reports = db.relationship("Report", back_populates="item", lazy="dynamic")

    @property
    def status_label(self) -> str:
        return ITEM_STATUS_LABELS.get(self.status, self.status)

    def is_visible_to(self, user: User | None) -> bool:
        if user is not None and getattr(user, "is_authenticated", False):
            if user.is_admin or user.id == self.seller_id:
                return True
        return self.status in (ItemStatus.PUBLISHED.value, ItemStatus.RESERVED.value)

    def __repr__(self) -> str:
        return f"<Item {self.id} {self.name}>"


class ItemImage(db.Model):
    __tablename__ = "item_images"

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(
        db.Integer, db.ForeignKey("items.id"), nullable=False, index=True
    )
    url = db.Column(db.String(255), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    item = db.relationship("Item", back_populates="images")

    def __repr__(self) -> str:
        return f"<ItemImage {self.url}>"


class Reservation(db.Model):
    __tablename__ = "reservations"

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(
        db.Integer, db.ForeignKey("items.id"), nullable=False, index=True
    )
    buyer_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    request_id = db.Column(db.String(36), nullable=False, index=True)
    status = db.Column(
        db.String(20),
        nullable=False,
        default=ReservationStatus.PENDING.value,
        index=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    seller_handled_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    cancel_reason = db.Column(db.String(200), nullable=True)
    version = db.Column(db.Integer, nullable=False, default=0)

    item = db.relationship("Item", back_populates="reservations")
    buyer = db.relationship("User", back_populates="reservations")

    __table_args__ = (
        db.Index(
            "uq_active_reservation_per_item",
            "item_id",
            unique=True,
            sqlite_where=db.text("status IN ('pending', 'confirmed')"),
        ),
    )

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_RESERVATION_STATUSES

    @property
    def status_label(self) -> str:
        return RESERVATION_STATUS_LABELS.get(self.status, self.status)

    def __repr__(self) -> str:
        return f"<Reservation {self.id} item={self.item_id} status={self.status}>"


class Report(db.Model):
    __tablename__ = "reports"

    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    item_id = db.Column(
        db.Integer, db.ForeignKey("items.id"), nullable=False, index=True
    )
    reason = db.Column(db.String(500), nullable=False)
    status = db.Column(
        db.String(20), nullable=False, default=ReportStatus.PENDING.value, index=True
    )
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    handled_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    handled_at = db.Column(db.DateTime, nullable=True)
    result = db.Column(db.String(500), nullable=True)

    reporter = db.relationship(
        "User", foreign_keys=[reporter_id], back_populates="reports"
    )
    handler = db.relationship(
        "User", foreign_keys=[handled_by], back_populates="handled_reports"
    )
    item = db.relationship("Item", back_populates="reports")

    @property
    def status_label(self) -> str:
        return REPORT_STATUS_LABELS.get(self.status, self.status)

    def __repr__(self) -> str:
        return f"<Report {self.id} item={self.item_id}>"


class OperationLog(db.Model):
    """Append-only audit log: no update/delete helpers are provided."""

    __tablename__ = "operation_logs"

    id = db.Column(db.Integer, primary_key=True)
    operator_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=True, index=True
    )
    action_type = db.Column(db.String(50), nullable=False, index=True)
    target_type = db.Column(db.String(30), nullable=False)
    target_id = db.Column(db.Integer, nullable=True)
    result = db.Column(db.String(20), nullable=False)
    detail = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    operator = db.relationship("User", back_populates="logs")

    def __repr__(self) -> str:
        return f"<OperationLog {self.action_type} {self.result}>"


class IdempotencyRecord(db.Model):
    """One row per client request id, used for 24-hour request deduplication."""

    __tablename__ = "idempotency_records"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    action = db.Column(db.String(50), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=True)
    request_id = db.Column(db.String(36), nullable=False)
    result_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "action", "item_id", "request_id", name="uq_idempotency_key"
        ),
    )

    def __repr__(self) -> str:
        return f"<IdempotencyRecord {self.request_id}>"
