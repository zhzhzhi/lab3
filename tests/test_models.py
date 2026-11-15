"""Domain model tests."""

from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.common.clock import utcnow
from app.enums import ItemStatus, ReservationStatus, Role
from app.extensions import db
from app.models import Category, Item, Reservation, User


def make_user(account="u1", roles=None):
    user = User(account=account, nickname=account, roles=roles or [Role.BUYER.value])
    user.set_password("password123")
    db.session.add(user)
    db.session.flush()
    return user


def make_item(seller, category, status=ItemStatus.PUBLISHED.value):
    item = Item(
        seller_id=seller.id,
        category_id=category.id,
        name="测试商品",
        description="这是一个用于测试的商品描述。",
        price=10,
        contact="test",
        status=status,
        published_at=utcnow(),
    )
    db.session.add(item)
    db.session.flush()
    return item


def test_user_password_and_roles(app):
    user = make_user(roles=[Role.BUYER.value, Role.SELLER.value])
    db.session.commit()

    assert user.check_password("password123")
    assert not user.check_password("wrong")
    assert user.has_role(Role.BUYER)
    assert user.has_role(Role.SELLER)
    assert not user.has_role(Role.ADMIN)


def test_only_one_active_reservation_per_item(app):
    buyer1 = make_user("buyer1")
    buyer2 = make_user("buyer2")
    seller = make_user("seller", roles=[Role.SELLER.value])
    category = Category(name="测试分类")
    db.session.add(category)
    db.session.flush()
    item = make_item(seller, category)
    db.session.commit()

    first = Reservation(
        item_id=item.id,
        buyer_id=buyer1.id,
        request_id="11111111-1111-4111-8111-111111111111",
        status=ReservationStatus.PENDING.value,
        expires_at=utcnow() + timedelta(hours=48),
    )
    db.session.add(first)
    db.session.commit()

    second = Reservation(
        item_id=item.id,
        buyer_id=buyer2.id,
        request_id="22222222-2222-4222-8222-222222222222",
        status=ReservationStatus.PENDING.value,
        expires_at=utcnow() + timedelta(hours=48),
    )
    db.session.add(second)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
