"""Buyer, seller and admin reservation pages."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..common.errors import BusinessError
from ..common.permissions import roles_required
from ..enums import ReservationStatus, Role
from ..models import Reservation
from .services import (
    arbitrate,
    buyer_cancel,
    buyer_complete,
    buyer_reservations,
    create_reservation,
    disputed_reservations,
    expire_overdue,
    reservation_counts,
    seller_cancel,
    seller_confirm,
    seller_reservations,
)

reservations_bp = Blueprint("reservations", __name__, url_prefix="/reservations")
seller_reservations_bp = Blueprint(
    "seller_reservations", __name__, url_prefix="/seller/reservations"
)
admin_reservations_bp = Blueprint(
    "admin_reservations", __name__, url_prefix="/admin/reservations"
)

STATUS_VALUES = {status.value for status in ReservationStatus}


def _status_filter() -> str | None:
    status = request.args.get("status") or None
    return status if status in STATUS_VALUES else None


@reservations_bp.get("/")
@roles_required(Role.BUYER.value)
def my_reservations():
    expire_overdue()
    selected_status = _status_filter()
    reservations = buyer_reservations(current_user.id, selected_status).all()
    return render_template(
        "reservations/my.html",
        reservations=reservations,
        counts=reservation_counts(current_user.id),
        selected_status=selected_status,
    )


@reservations_bp.post("/item/<int:item_id>")
@roles_required(Role.BUYER.value)
def create(item_id: int):
    try:
        _, replayed = create_reservation(
            current_user, item_id, request.form.get("request_id")
        )
    except BusinessError as exc:
        flash(str(exc), "error")
        return redirect(url_for("market.detail", item_id=item_id))
    if replayed:
        flash("该预约已经提交过，未重复创建。", "success")
    else:
        flash("预约已提交，等待卖家在 48 小时内确认。", "success")
    return redirect(url_for("reservations.my_reservations"))


@reservations_bp.post("/<int:reservation_id>/cancel")
@roles_required(Role.BUYER.value)
def cancel(reservation_id: int):
    try:
        buyer_cancel(current_user, reservation_id, request.form.get("reason", ""))
        flash("预约已取消，商品恢复在售。", "success")
    except BusinessError as exc:
        flash(str(exc), "error")
    return redirect(url_for("reservations.my_reservations"))


@reservations_bp.post("/<int:reservation_id>/complete")
@roles_required(Role.BUYER.value)
def complete(reservation_id: int):
    try:
        buyer_complete(current_user, reservation_id)
        flash("交易已确认完成。", "success")
    except BusinessError as exc:
        flash(str(exc), "error")
    return redirect(url_for("reservations.my_reservations"))


@seller_reservations_bp.get("/")
@roles_required(Role.SELLER.value)
def seller_list():
    expire_overdue()
    selected_status = _status_filter()
    reservations = seller_reservations(current_user.id, selected_status).all()
    return render_template(
        "reservations/seller.html",
        reservations=reservations,
        counts=reservation_counts(current_user.id, as_seller=True),
        selected_status=selected_status,
    )


@seller_reservations_bp.post("/<int:reservation_id>/confirm")
@roles_required(Role.SELLER.value)
def confirm(reservation_id: int):
    try:
        seller_confirm(current_user, reservation_id)
        flash("预约已确认，请与买家约定线下交付。", "success")
    except BusinessError as exc:
        flash(str(exc), "error")
    return redirect(url_for("seller_reservations.seller_list"))


@seller_reservations_bp.post("/<int:reservation_id>/cancel")
@roles_required(Role.SELLER.value)
def seller_cancel_view(reservation_id: int):
    try:
        seller_cancel(current_user, reservation_id, request.form.get("reason", ""))
        flash("预约已取消，商品恢复在售。", "success")
    except BusinessError as exc:
        flash(str(exc), "error")
    return redirect(url_for("seller_reservations.seller_list"))


@admin_reservations_bp.get("/")
@roles_required(Role.ADMIN.value)
def admin_list():
    expire_overdue()
    selected_status = _status_filter()
    reservations = disputed_reservations(selected_status).all()
    return render_template(
        "reservations/admin.html",
        reservations=reservations,
        selected_status=selected_status,
    )


@admin_reservations_bp.post("/<int:reservation_id>/arbitrate")
@roles_required(Role.ADMIN.value)
def arbitrate_view(reservation_id: int):
    outcome = request.form.get("outcome", "")
    try:
        arbitrate(current_user, reservation_id, outcome, request.form.get("note", ""))
        flash("仲裁结果已记录。", "success")
    except BusinessError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin_reservations.admin_list"))


@reservations_bp.get("/<int:reservation_id>")
@roles_required(Role.BUYER.value)
def detail(reservation_id: int):
    reservation = Reservation.query.filter_by(
        id=reservation_id, buyer_id=current_user.id
    ).first()
    if reservation is None:
        flash("预约不存在。", "error")
        return redirect(url_for("reservations.my_reservations"))
    return render_template("reservations/detail.html", reservation=reservation)
