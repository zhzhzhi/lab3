"""Marketplace query and visibility tests."""

import pytest

from app.common.errors import BusinessError
from app.enums import ItemStatus, Role
from app.market.services import get_item_detail, search_items
from tests.helpers import make_category, make_item, make_user


def test_buyer_only_sees_published_and_reserved(app):
    seller = make_user("seller", [Role.SELLER.value])
    buyer = make_user("buyer", [Role.BUYER.value])
    category = make_category()
    published = make_item(seller, category, ItemStatus.PUBLISHED.value, name="在售商品")
    reserved = make_item(seller, category, ItemStatus.RESERVED.value, name="已预约商品")
    make_item(seller, category, ItemStatus.DRAFT.value, name="草稿商品")
    make_item(seller, category, ItemStatus.COMPLETED.value, name="已完成商品")

    page = search_items(buyer, {})
    ids = {item.id for item in page.items}
    assert ids == {published.id, reserved.id}


def test_admin_sees_all_statuses(app):
    seller = make_user("seller", [Role.SELLER.value])
    admin = make_user("admin", [Role.ADMIN.value])
    category = make_category()
    for status in (ItemStatus.PUBLISHED, ItemStatus.DRAFT, ItemStatus.COMPLETED):
        make_item(seller, category, status.value, name=status.value)

    page = search_items(admin, {})
    assert page.total == 3


def test_keyword_category_and_price_filters(app):
    seller = make_user("seller", [Role.SELLER.value])
    buyer = make_user("buyer", [Role.BUYER.value])
    books = make_category("图书教材")
    digital = make_category("数码配件")
    make_item(seller, books, name="高等数学教材", price="28.00")
    make_item(seller, books, name="考研英语真题", price="45.00")
    make_item(seller, digital, name="机械键盘", price="150.00")

    page = search_items(buyer, {"keyword": "数学"})
    assert page.total == 1
    assert page.items[0].name == "高等数学教材"

    page = search_items(
        buyer, {"category_id": books.id, "min_price": "30", "max_price": "50"}
    )
    assert page.total == 1
    assert page.items[0].name == "考研英语真题"


def test_sort_and_pagination(app):
    seller = make_user("seller", [Role.SELLER.value])
    buyer = make_user("buyer", [Role.BUYER.value])
    category = make_category()
    for index in range(25):
        make_item(seller, category, name=f"商品{index}", price=f"{index + 1}.00")

    page = search_items(buyer, {"per_page": 20, "page": 1})
    assert page.total == 25
    assert len(page.items) == 20
    page2 = search_items(buyer, {"per_page": 20, "page": 2})
    assert len(page2.items) == 5

    page = search_items(buyer, {"sort": "price_asc", "per_page": 20})
    assert page.items[0].price == 1


def test_detail_visibility(app):
    seller = make_user("seller", [Role.SELLER.value])
    buyer = make_user("buyer", [Role.BUYER.value])
    admin = make_user("admin", [Role.ADMIN.value])
    category = make_category()
    draft = make_item(seller, category, ItemStatus.DRAFT.value)

    assert get_item_detail(draft.id, seller).id == draft.id
    assert get_item_detail(draft.id, admin).id == draft.id
    with pytest.raises(BusinessError):
        get_item_detail(draft.id, buyer)
