"""Item lifecycle and permission tests."""

import pytest

from app.common.errors import BusinessError
from app.enums import ItemStatus, Role
from app.items.services import (
    approve_item,
    create_item,
    off_shelf,
    reject_item,
    seller_items,
    submit_for_review,
    to_draft,
    update_item,
    withdraw_review,
)
from tests.helpers import item_data, make_category, make_item, make_user


def test_create_submit_and_approve(app):
    seller = make_user("seller", [Role.SELLER.value])
    admin = make_user("admin", [Role.ADMIN.value])
    category = make_category()

    item = create_item(seller, item_data(category), ["/uploads/a.png"])
    assert item.status == ItemStatus.DRAFT.value

    submit_for_review(seller, item.id)
    assert item.status == ItemStatus.PENDING.value

    approve_item(admin, item.id)
    assert item.status == ItemStatus.PUBLISHED.value
    assert item.published_at is not None


def test_invalid_fields_report_all_errors(app):
    seller = make_user("seller", [Role.SELLER.value])
    category = make_category()

    with pytest.raises(BusinessError) as excinfo:
        create_item(
            seller,
            {
                "name": "短",
                "description": "太短",
                "price": "0",
                "contact": "",
                "category_id": "999",
            },
            [],
        )
    message = str(excinfo.value)
    assert "名称" in message
    assert "描述" in message
    assert "价格" in message
    assert "分类" in message
    assert "图片" in message


def test_reject_then_edit_and_resubmit(app):
    seller = make_user("seller", [Role.SELLER.value])
    admin = make_user("admin", [Role.ADMIN.value])
    category = make_category()
    item = create_item(seller, item_data(category), ["/uploads/a.png"])
    submit_for_review(seller, item.id)

    reject_item(admin, item.id, "图片不清晰")
    assert item.status == ItemStatus.REJECTED.value
    assert item.reject_reason == "图片不清晰"

    update_item(
        seller, item.id, item_data(category, name="修改后的名称"), ["/uploads/b.png"]
    )
    assert item.status == ItemStatus.DRAFT.value
    assert item.reject_reason is None

    submit_for_review(seller, item.id)
    assert item.status == ItemStatus.PENDING.value


def test_only_owner_can_edit(app):
    seller = make_user("seller", [Role.SELLER.value])
    other = make_user("other", [Role.SELLER.value])
    category = make_category()
    item = create_item(seller, item_data(category), ["/uploads/a.png"])

    with pytest.raises(BusinessError) as excinfo:
        update_item(other, item.id, item_data(category), ["/uploads/a.png"])
    assert excinfo.value.status_code == 403


def test_withdraw_and_shelf_lifecycle(app):
    seller = make_user("seller", [Role.SELLER.value])
    admin = make_user("admin", [Role.ADMIN.value])
    category = make_category()
    item = create_item(seller, item_data(category), ["/uploads/a.png"])

    submit_for_review(seller, item.id)
    withdraw_review(seller, item.id)
    assert item.status == ItemStatus.DRAFT.value

    submit_for_review(seller, item.id)
    approve_item(admin, item.id)
    off_shelf(seller, item.id, "卖掉了")
    assert item.status == ItemStatus.OFF_SHELF.value

    to_draft(seller, item.id)
    assert item.status == ItemStatus.DRAFT.value


def test_seller_list_and_counts(app):
    seller = make_user("seller", [Role.SELLER.value])
    category = make_category()
    make_item(seller, category, ItemStatus.PUBLISHED.value)
    make_item(seller, category, ItemStatus.DRAFT.value, name="草稿商品")

    assert seller_items(seller.id).count() == 2
    assert seller_items(seller.id, ItemStatus.DRAFT.value).count() == 1


def test_create_item_route_with_upload(client, app):
    import io
    from app.extensions import db
    from app.models import Item

    seller = make_user("seller", [Role.SELLER.value])
    category = make_category()
    db.session.commit()

    client.post("/auth/login", data={"account": "seller", "password": "password123"})
    data = item_data(category)
    data["images"] = (io.BytesIO(b"fake-image-bytes"), "book.png")
    response = client.post(
        "/seller/items/new",
        data=data,
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert Item.query.count() == 1
