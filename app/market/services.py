"""Marketplace search and detail rules."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from sqlalchemy import or_

from ..common.errors import BusinessError
from ..common.pagination import normalize_page, normalize_per_page
from ..enums import ItemStatus
from ..extensions import db
from ..models import Category, Item, User

PUBLIC_STATUSES = (ItemStatus.PUBLISHED.value, ItemStatus.RESERVED.value)


def category_options():
    return (
        Category.query.filter_by(enabled=True)
        .order_by(Category.sort_order.asc(), Category.id.asc())
        .all()
    )


def _price(value, label: str):
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise BusinessError(f"{label}格式不正确。", next_step="填写数字价格。") from exc
    if parsed < 0:
        raise BusinessError(f"{label}不能为负数。", next_step="填写非负价格。")
    return parsed


def search_items(viewer, filters: dict):
    """Return a paginated query respecting the viewer's visibility."""
    query = Item.query.join(User, Item.seller_id == User.id)
    if not (viewer and viewer.is_admin):
        query = query.filter(Item.status.in_(PUBLIC_STATUSES))

    keyword = (filters.get("keyword") or "").strip()
    if keyword:
        query = query.filter(
            or_(
                Item.name.contains(keyword),
                Item.description.contains(keyword),
                User.nickname.contains(keyword),
            )
        )

    category_id = filters.get("category_id")
    if category_id:
        try:
            query = query.filter(Item.category_id == int(category_id))
        except (TypeError, ValueError) as exc:
            raise BusinessError("分类参数不正确。", next_step="重新选择分类。") from exc

    min_price = _price(filters.get("min_price"), "最低价")
    max_price = _price(filters.get("max_price"), "最高价")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise BusinessError("最低价不能高于最高价。", next_step="调整价格区间。")
    if min_price is not None:
        query = query.filter(Item.price >= min_price)
    if max_price is not None:
        query = query.filter(Item.price <= max_price)

    status = filters.get("status")
    if status:
        if status not in {item.value for item in ItemStatus}:
            raise BusinessError("状态参数不正确。", next_step="重新选择状态。")
        query = query.filter(Item.status == status)

    seller = (filters.get("seller") or "").strip()
    if seller:
        query = query.filter(User.nickname.contains(seller))

    sort = filters.get("sort") or "newest"
    if sort == "price_asc":
        query = query.order_by(Item.price.asc(), Item.id.desc())
    elif sort == "price_desc":
        query = query.order_by(Item.price.desc(), Item.id.desc())
    else:
        query = query.order_by(Item.published_at.desc(), Item.id.desc())

    page = normalize_page(filters.get("page"))
    per_page = normalize_per_page(filters.get("per_page"))
    return query.paginate(page=page, per_page=per_page, error_out=False)


def get_item_detail(item_id: int, viewer) -> Item:
    item = db.session.get(Item, item_id)
    if item is None or not item.is_visible_to(viewer):
        raise BusinessError(
            "商品不存在或不可见。",
            status_code=404,
            next_step="返回商品广场。",
        )
    return item
