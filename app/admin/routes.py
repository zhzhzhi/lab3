"""Admin dashboard, user governance, audit logs and statistics."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..common.errors import BusinessError
from ..common.permissions import roles_required
from ..enums import Role
from .services import (
    action_type_options,
    dashboard_stats,
    search_logs,
    search_users,
    set_user_status,
    target_type_options,
    unlock_user,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.get("/")
@roles_required(Role.ADMIN.value)
def dashboard():
    summary = dashboard_stats()
    return render_template("admin/index.html", stats=summary)


@admin_bp.get("/users/")
@roles_required(Role.ADMIN.value)
def users():
    return render_template(
        "admin/users.html",
        users=search_users(
            request.args.get("keyword", ""),
            request.args.get("role", ""),
            request.args.get("status", ""),
        ),
        filters=request.args,
    )


@admin_bp.post("/users/<int:user_id>/disable")
@roles_required(Role.ADMIN.value)
def disable_user(user_id: int):
    try:
        set_user_status(
            current_user, user_id, disabled=True, reason=request.form.get("reason", "")
        )
        flash("用户已禁用，无法继续登录。", "success")
    except BusinessError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.users"))


@admin_bp.post("/users/<int:user_id>/enable")
@roles_required(Role.ADMIN.value)
def enable_user(user_id: int):
    try:
        set_user_status(current_user, user_id, disabled=False)
        flash("用户已恢复为正常状态。", "success")
    except BusinessError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.users"))


@admin_bp.post("/users/<int:user_id>/unlock")
@roles_required(Role.ADMIN.value)
def unlock(user_id: int):
    try:
        unlock_user(current_user, user_id)
        flash("已解除登录锁定。", "success")
    except BusinessError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.users"))


@admin_bp.get("/logs/")
@roles_required(Role.ADMIN.value)
def logs():
    pagination = search_logs(request.args)
    return render_template(
        "admin/logs.html",
        pagination=pagination,
        filters=request.args,
        actions=action_type_options(),
        targets=target_type_options(),
    )


@admin_bp.get("/stats/")
@roles_required(Role.ADMIN.value)
def stats():
    return render_template("admin/stats.html", stats=dashboard_stats())
