"""Small factories for tests."""

from app.common.clock import utcnow
from app.enums import ItemStatus, Role, UserStatus
from app.extensions import db
from app.models import Category, Item, ItemImage, User


def make_user(
    account, roles=None, password="password123", status=UserStatus.ACTIVE.value
):
    user = User(
        account=account,
        nickname=account,
        roles=roles or [Role.BUYER.value],
        status=status,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    return user


def make_category(name="图书教材"):
    category = Category(name=name)
    db.session.add(category)
    db.session.flush()
    return category


def make_item(
    seller, category, status=ItemStatus.PUBLISHED.value, name="测试商品", price="10.00"
):
    item = Item(
        seller_id=seller.id,
        category_id=category.id,
        name=name,
        description="这是一个用于测试的商品描述。",
        price=price,
        contact="test",
        status=status,
        published_at=(
            utcnow()
            if status in (ItemStatus.PUBLISHED.value, ItemStatus.RESERVED.value)
            else None
        ),
    )
    db.session.add(item)
    db.session.flush()
    db.session.add(ItemImage(item_id=item.id, url="/uploads/test.png", sort_order=0))
    db.session.commit()
    return item


def item_data(category, **overrides):
    data = {
        "name": "高等数学教材",
        "description": "九成新，书内有少量笔记，宿舍楼下自提。",
        "price": "28.00",
        "contact": "微信：test",
        "category_id": str(category.id),
    }
    data.update(overrides)
    return data
