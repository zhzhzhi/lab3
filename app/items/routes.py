"""Seller and admin item routes."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from ..common.errors import BusinessError
from ..common.permissions import roles_required
from ..enums import ItemStatus, Role
from ..market.services import category_options
from ..models import Item
from .services import (
    approve_item,
    create_item,
    off_shelf,
    pending_items,
    reject_item,
    seller_items,
    seller_status_counts,
    submit_for_review,
    to_draft,
    update_item,
    withdraw_review,
)

items_bp = Blueprint("items", __name__, url_prefix="/seller/items")
admin_items_bp = Blueprint("admin_items", __name__, url_prefix="/admin/items")

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _save_uploads(files) -> list[str]:
    urls: list[str] = []
    folder = Path(current_app.config["UPLOAD_FOLDER"])
    folder.mkdir(parents=True, exist_ok=True)
    for uploaded in files:
        if uploaded is None or not uploaded.filename:
            continue
        extension = Path(uploaded.filename).suffix.lower().lstrip(".")
        if extension not in ALLOWED_EXTENSIONS:
            raise BusinessError(
                "图片格式不支持。",
                next_step="只上传 JPG、JPEG、PNG 或 WebP。",
            )
        uploaded.stream.seek(0, os.SEEK_END)
        size = uploaded.stream.tell()
        uploaded.stream.seek(0)
        if size > MAX_IMAGE_BYTES:
            raise BusinessError(
                "单张图片不能超过 5 MB。",
                next_step="压缩图片或换一张更小的图片。",
            )
        filename = f"{uuid.uuid4().hex}.{extension}"
        uploaded.save(folder / filename)
        urls.append(f"/uploads/{filename}")
    return urls


def _existing_image_urls(item: Item) -> list[str]:
    keep_ids = set(request.form.getlist("keep_image"))
    return [image.url for image in item.images if str(image.id) in keep_ids]


def _form_context(item: Item | None = None) -> dict:
    return {
        "item": item,
        "categories": category_options(),
        "form": request.form,
    }


@items_bp.get("/")
@roles_required(Role.SELLER.value)
def list_items():
    selected_status = request.args.get("status") or None
    items = seller_items(current_user.id, selected_status).all()
    counts = seller_status_counts(current_user.id)
    return render_template(
        "items/list.html",
        items=items,
        counts=counts,
        selected_status=selected_status,
    )


@items_bp.route("/new", methods=["GET", "POST"])
@roles_required(Role.SELLER.value)
def new_item():
    if request.method == "POST":
        try:
            image_urls = _save_uploads(request.files.getlist("images"))
            item = create_item(current_user, request.form, image_urls)
            if request.form.get("action") == "submit":
                submit_for_review(current_user, item.id)
                flash("商品已提交审核。", "success")
            else:
                flash("商品已保存为草稿。", "success")
            return redirect(url_for("items.list_items"))
        except BusinessError as exc:
            flash(str(exc), "error")
            return render_template("items/form.html", **_form_context()), 400
    return render_template("items/form.html", **_form_context())


@items_bp.route("/<int:item_id>/edit", methods=["GET", "POST"])
@roles_required(Role.SELLER.value)
def edit_item(item_id: int):
    item = Item.query.filter_by(id=item_id, seller_id=current_user.id).first()
    if item is None:
        flash("商品不存在。", "error")
        return redirect(url_for("items.list_items"))
    if item.status not in (ItemStatus.DRAFT.value, ItemStatus.REJECTED.value):
        flash("当前状态不能编辑。", "error")
        return redirect(url_for("items.list_items"))

    if request.method == "POST":
        try:
            image_urls = _existing_image_urls(item) + _save_uploads(
                request.files.getlist("images")
            )
            update_item(current_user, item.id, request.form, image_urls)
            if request.form.get("action") == "submit":
                submit_for_review(current_user, item.id)
                flash("商品已提交审核。", "success")
            else:
                flash("商品已保存。", "success")
            return redirect(url_for("items.list_items"))
        except BusinessError as exc:
            flash(str(exc), "error")
            return render_template("items/form.html", **_form_context(item)), 400

    return render_template("items/form.html", **_form_context(item))


@items_bp.post("/<int:item_id>/submit")
@roles_required(Role.SELLER.value)
def submit_item(item_id: int):
    try:
        submit_for_review(current_user, item_id)
        flash("商品已提交审核。", "success")
    except BusinessError as exc:
        flash(str(exc), "error")
    return redirect(url_for("items.list_items"))


@items_bp.post("/<int:item_id>/withdraw")
@roles_required(Role.SELLER.value)
def withdraw_item(item_id: int):
    try:
        withdraw_review(current_user, item_id)
        flash("已撤回审核。", "success")
    except BusinessError as exc:
        flash(str(exc), "error")
    return redirect(url_for("items.list_items"))


@items_bp.post("/<int:item_id>/off-shelf")
@roles_required(Role.SELLER.value)
def off_shelf_item(item_id: int):
    try:
        off_shelf(current_user, item_id, request.form.get("reason", ""))
        flash("商品已下架。", "success")
    except BusinessError as exc:
        flash(str(exc), "error")
    return redirect(url_for("items.list_items"))


@items_bp.post("/<int:item_id>/to-draft")
@roles_required(Role.SELLER.value)
def to_draft_item(item_id: int):
    try:
        to_draft(current_user, item_id)
        flash("商品已转回草稿。", "success")
    except BusinessError as exc:
        flash(str(exc), "error")
    return redirect(url_for("items.list_items"))


@admin_items_bp.get("/")
@roles_required(Role.ADMIN.value)
def review_list():
    items = pending_items()
    return render_template(
        "items/admin_list.html",
        items=items,
        pending_count=len(items),
    )


@admin_items_bp.post("/<int:item_id>/approve")
@roles_required(Role.ADMIN.value)
def approve(item_id: int):
    try:
        approve_item(current_user, item_id)
        flash("审核通过，商品已自动发布。", "success")
    except BusinessError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin_items.review_list"))


@admin_items_bp.post("/<int:item_id>/reject")
@roles_required(Role.ADMIN.value)
def reject(item_id: int):
    try:
        reject_item(current_user, item_id, request.form.get("reason", ""))
        flash("商品已驳回。", "success")
    except BusinessError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin_items.review_list"))
