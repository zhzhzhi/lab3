"""Report submission and admin handling routes."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..common.errors import BusinessError
from ..common.permissions import roles_required
from ..enums import ReportStatus, Role
from ..extensions import db
from ..models import Item, Report
from .services import (
    handle_report,
    list_reports,
    report_counts,
    submit_report,
)

reports_bp = Blueprint("reports", __name__, url_prefix="/reports")
admin_reports_bp = Blueprint("admin_reports", __name__, url_prefix="/admin/reports")

STATUS_VALUES = {status.value for status in ReportStatus}


@reports_bp.route("/item/<int:item_id>", methods=["GET", "POST"])
@roles_required(Role.BUYER.value, Role.SELLER.value)
def report_item(item_id: int):
    item = db.session.get(Item, item_id)
    if item is None or not item.is_visible_to(current_user):
        flash("商品不存在或不可见。", "error")
        return redirect(url_for("market.list_items"))

    if request.method == "POST":
        try:
            submit_report(current_user, item_id, request.form.get("reason", ""))
            flash("举报已提交，管理员会尽快处理。", "success")
            return redirect(url_for("market.detail", item_id=item_id))
        except BusinessError as exc:
            flash(str(exc), "error")
            return (
                render_template(
                    "reports/form.html",
                    item=item,
                    reason=request.form.get("reason", ""),
                ),
                400,
            )

    return render_template("reports/form.html", item=item, reason="")


@reports_bp.get("/")
@roles_required(Role.BUYER.value, Role.SELLER.value)
def my_reports():
    reports = (
        Report.query.filter_by(reporter_id=current_user.id)
        .order_by(Report.created_at.desc(), Report.id.desc())
        .all()
    )
    return render_template("reports/my.html", reports=reports)


@admin_reports_bp.get("/")
@roles_required(Role.ADMIN.value)
def review_list():
    selected_status = request.args.get("status") or None
    if selected_status not in STATUS_VALUES:
        selected_status = None
    reports = list_reports(selected_status).all()
    counts = report_counts()
    return render_template(
        "reports/admin_list.html",
        reports=reports,
        counts=counts,
        selected_status=selected_status,
    )


@admin_reports_bp.post("/<int:report_id>/handle")
@roles_required(Role.ADMIN.value)
def handle(report_id: int):
    decision = request.form.get("decision")
    try:
        handle_report(
            current_user,
            report_id,
            accepted=decision == "accept",
            note=request.form.get("note", ""),
        )
        flash("举报处理结果已记录。", "success")
    except BusinessError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin_reports.review_list"))
