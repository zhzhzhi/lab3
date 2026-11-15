"""Public marketplace routes."""

import uuid

from flask import Blueprint, render_template, request
from flask_login import current_user

from ..reservations.services import (
    active_reservation,
    contact_visible_to,
    expire_overdue,
)
from .services import category_options, get_item_detail, search_items

market_bp = Blueprint("market", __name__, url_prefix="/market")


@market_bp.get("/")
def list_items():
    expire_overdue()
    viewer = current_user if current_user.is_authenticated else None
    pagination = search_items(viewer, request.args)
    return render_template(
        "market/list.html",
        pagination=pagination,
        filters=request.args,
        categories=category_options(),
    )


@market_bp.get("/<int:item_id>")
def detail(item_id: int):
    viewer = current_user if current_user.is_authenticated else None
    item = get_item_detail(item_id, viewer)
    return render_template(
        "market/detail.html",
        item=item,
        request_id=uuid.uuid4().hex,
        contact_visible=contact_visible_to(viewer, item),
        active_reservation=active_reservation(item.id),
    )
