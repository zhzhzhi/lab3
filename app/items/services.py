"""Item lifecycle rules: draft, review, publishing and shelving."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from sqlalchemy import func

from ..common.audit import record_log
from ..common.clock import clock
from ..common.errors import BusinessError
from ..enums import ItemStatus, Role
from ..extensions import db
from ..models import Category, Item, ItemImage, User

MAX_PRICE = Decimal("1000000.00")


def _parse_price(raw) -> Decimal:
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError, AttributeError) as exc:
        raise BusinessError("价格格式不正确。", next_step="填写数字价格。") from exc
    if value <= 0:
        raise BusinessError("价格必须大于 0 元。", next_step="填写大于 0 的价格。")
    if value > MAX_PRICE:
        raise BusinessError(
            "价格不能超过 1000000 元。", next_step="填写不超过上限的价格。"
        )
    if value.as_tuple().exponent < -2:
        raise BusinessError(
            "价格最多保留两位小数。", next_step="把价格改为两位小数以内。"
        )
    return value.quantize(Decimal("0.01"))


def validate_item_fields(
    name: str,
    description: str,
    price,
    contact: str,
    category_id,
    image_urls: list[str],
) -> dict:
    """Validate all item fields and return normalized values or raise all errors."""
    errors: list[str] = []
    name = (name or "").strip()
    description = (description or "").strip()
    contact = (contact or "").strip()

    if not 2 <= len(name) <= 100:
        errors.append("商品名称需要 2–100 个字符。")
    if not 10 <= len(description) <= 2000:
        errors.append("商品描述需要 10–2000 个字符。")
    if not contact or len(contact) > 100:
        errors.append("联系方式不能为空，且不超过 100 个字符。")

    try:
        price_value = _parse_price(price)
    except BusinessError as exc:
        errors.append(exc.message)
        price_value = None

    category = None
    try:
        category = db.session.get(Category, int(category_id))
    except (TypeError, ValueError):
        category = None
    if category is None or not category.enabled:
        errors.append("请选择一个可用的商品分类。")

    urls = [url for url in (image_urls or []) if url]
    if not 1 <= len(urls) <= 9:
        errors.append("商品图片需要 1–9 张。")

    if errors:
        raise BusinessError(
            "；".join(errors),
            current_state="表单校验未通过",
            next_step="按提示修改后重新保存。",
        )

    return {
        "name": name,
        "description": description,
        "price": price_value,
        "contact": contact,
        "category": category,
        "image_urls": urls,
    }


def _owned_item(seller: User, item_id: int) -> Item:
    item = db.session.get(Item, item_id)
    if item is None:
        raise BusinessError("商品不存在。", status_code=404, next_step="返回商品列表。")
    if item.seller_id != seller.id:
        raise BusinessError("只能操作自己的商品。", status_code=403)
    return item


def _require_status(item: Item, allowed: tuple[str, ...], action: str) -> None:
    if item.status not in allowed:
        raise BusinessError(
            f"当前状态不能{action}。",
            current_state=item.status_label,
            next_step="刷新页面，按当前状态选择可用操作。",
        )


def _replace_images(item: Item, image_urls: list[str]) -> None:
    for image in list(item.images):
        db.session.delete(image)
    for index, url in enumerate(image_urls):
        db.session.add(ItemImage(item_id=item.id, url=url, sort_order=index))


def create_item(seller: User, data: dict, image_urls: list[str]) -> Item:
    values = validate_item_fields(
        data.get("name", ""),
        data.get("description", ""),
        data.get("price", ""),
        data.get("contact", ""),
        data.get("category_id"),
        image_urls,
    )
    item = Item(
        seller_id=seller.id,
        category_id=values["category"].id,
        name=values["name"],
        description=values["description"],
        price=values["price"],
        contact=values["contact"],
        status=ItemStatus.DRAFT.value,
    )
    db.session.add(item)
    db.session.flush()
    _replace_images(item, values["image_urls"])
    record_log(seller.id, "create_item", "item", item.id, detail=item.name)
    db.session.commit()
    return item


def update_item(seller: User, item_id: int, data: dict, image_urls: list[str]) -> Item:
    item = _owned_item(seller, item_id)
    _require_status(item, (ItemStatus.DRAFT.value, ItemStatus.REJECTED.value), "编辑")
    values = validate_item_fields(
        data.get("name", ""),
        data.get("description", ""),
        data.get("price", ""),
        data.get("contact", ""),
        data.get("category_id"),
        image_urls,
    )
    item.category_id = values["category"].id
    item.name = values["name"]
    item.description = values["description"]
    item.price = values["price"]
    item.contact = values["contact"]
    item.status = ItemStatus.DRAFT.value
    item.reject_reason = None
    item.version += 1
    _replace_images(item, values["image_urls"])
    record_log(seller.id, "update_item", "item", item.id, detail=item.name)
    db.session.commit()
    return item


def submit_for_review(seller: User, item_id: int) -> Item:
    item = _owned_item(seller, item_id)
    _require_status(
        item, (ItemStatus.DRAFT.value, ItemStatus.REJECTED.value), "提交审核"
    )
    validate_item_fields(
        item.name,
        item.description,
        item.price,
        item.contact,
        item.category_id,
        [image.url for image in item.images],
    )
    item.status = ItemStatus.PENDING.value
    item.reject_reason = None
    item.version += 1
    record_log(seller.id, "submit_review", "item", item.id, detail=item.name)
    db.session.commit()
    return item


def withdraw_review(seller: User, item_id: int) -> Item:
    item = _owned_item(seller, item_id)
    _require_status(item, (ItemStatus.PENDING.value,), "撤回审核")
    item.status = ItemStatus.DRAFT.value
    item.version += 1
    record_log(seller.id, "withdraw_review", "item", item.id, detail=item.name)
    db.session.commit()
    return item


def approve_item(admin: User, item_id: int) -> Item:
    if not admin.has_role(Role.ADMIN):
        raise BusinessError("只有管理员可以审核商品。", status_code=403)
    item = db.session.get(Item, item_id)
    if item is None:
        raise BusinessError("商品不存在。", status_code=404)
    _require_status(item, (ItemStatus.PENDING.value,), "审核通过")
    item.status = ItemStatus.PUBLISHED.value
    item.published_at = clock.now()
    item.reject_reason = None
    item.version += 1
    record_log(admin.id, "approve_item", "item", item.id, detail=item.name)
    db.session.commit()
    return item


def reject_item(admin: User, item_id: int, reason: str) -> Item:
    if not admin.has_role(Role.ADMIN):
        raise BusinessError("只有管理员可以审核商品。", status_code=403)
    reason = (reason or "").strip()
    if not reason:
        raise BusinessError("驳回原因不能为空。", next_step="填写驳回原因。")
    if len(reason) > 200:
        raise BusinessError("驳回原因不能超过 200 个字符。")
    item = db.session.get(Item, item_id)
    if item is None:
        raise BusinessError("商品不存在。", status_code=404)
    _require_status(item, (ItemStatus.PENDING.value,), "驳回")
    item.status = ItemStatus.REJECTED.value
    item.reject_reason = reason
    item.version += 1
    record_log(admin.id, "reject_item", "item", item.id, detail=reason)
    db.session.commit()
    return item


def off_shelf(actor: User, item_id: int, reason: str = "") -> Item:
    item = db.session.get(Item, item_id)
    if item is None:
        raise BusinessError("商品不存在。", status_code=404)
    is_admin = actor.has_role(Role.ADMIN)
    if not is_admin and item.seller_id != actor.id:
        raise BusinessError("只能下架自己的商品。", status_code=403)
    if item.status == ItemStatus.COMPLETED.value:
        raise BusinessError("已完成的交易不能下架。", current_state=item.status_label)
    if item.status in (ItemStatus.RESERVED.value, ItemStatus.CONFIRMED.value):
        raise BusinessError(
            "商品存在有效预约，需先处理预约。",
            current_state=item.status_label,
            next_step="在预约处理中确认或取消预约。",
        )
    _require_status(item, (ItemStatus.PUBLISHED.value,), "下架")
    item.status = ItemStatus.OFF_SHELF.value
    item.off_shelf_reason = (reason or "未填写原因").strip()[:200]
    item.version += 1
    record_log(actor.id, "off_shelf", "item", item.id, detail=item.off_shelf_reason)
    db.session.commit()
    return item


def to_draft(seller: User, item_id: int) -> Item:
    item = _owned_item(seller, item_id)
    _require_status(item, (ItemStatus.OFF_SHELF.value,), "转回草稿")
    item.status = ItemStatus.DRAFT.value
    item.off_shelf_reason = None
    item.version += 1
    record_log(seller.id, "to_draft", "item", item.id, detail=item.name)
    db.session.commit()
    return item


def seller_items(seller_id: int, status: str | None = None):
    query = Item.query.filter_by(seller_id=seller_id)
    if status:
        query = query.filter_by(status=status)
    return query.order_by(Item.created_at.desc())


def seller_status_counts(seller_id: int) -> dict[str, int]:
    counts = {status.value: 0 for status in ItemStatus}
    rows = (
        db.session.query(Item.status, func.count(Item.id))
        .filter(Item.seller_id == seller_id)
        .group_by(Item.status)
        .all()
    )
    for status, count in rows:
        counts[status] = count
    return counts


def pending_items():
    return (
        Item.query.filter_by(status=ItemStatus.PENDING.value)
        .order_by(Item.created_at.asc())
        .all()
    )
