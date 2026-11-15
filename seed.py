"""Seed demo data for local development."""

from datetime import timedelta

from app.common.clock import utcnow
from app.enums import ItemStatus, ReservationStatus, Role, UserStatus
from app.extensions import db
from app.models import Category, Item, ItemImage, Reservation, User


def _user(account, nickname, password, roles, status=UserStatus.ACTIVE.value):
    user = User(account=account, nickname=nickname, contact="微信：demo", roles=roles, status=status)
    user.set_password(password)
    return user


def seed_data() -> None:
    if User.query.first():
        return

    admin = _user("admin", "管理员", "admin12345", [Role.ADMIN.value])
    buyer = _user("buyer01", "小陈", "buyer12345", [Role.BUYER.value])
    seller = _user("seller01", "林同学", "seller12345", [Role.SELLER.value, Role.BUYER.value])
    disabled = _user(
        "disabled01", "被禁用用户", "disabled12345", [Role.BUYER.value], UserStatus.DISABLED.value
    )
    db.session.add_all([admin, buyer, seller, disabled])
    db.session.flush()

    categories = [
        Category(name="图书教材", sort_order=1),
        Category(name="生活电器", sort_order=2),
        Category(name="数码配件", sort_order=3),
        Category(name="交通工具", sort_order=4),
        Category(name="运动器材", sort_order=5),
    ]
    db.session.add_all(categories)
    db.session.flush()

    book = Category.query.filter_by(name="图书教材").first()
    appliance = Category.query.filter_by(name="生活电器").first()
    digital = Category.query.filter_by(name="数码配件").first()

    now = utcnow()
    items = [
        Item(
            seller_id=seller.id,
            category_id=book.id,
            name="高等数学（第七版）教材",
            description="上下册，书内有少量铅笔笔记，整体 9 成新，宿舍楼下自提。",
            price=28,
            contact="微信：seller01",
            status=ItemStatus.PUBLISHED.value,
            published_at=now,
        ),
        Item(
            seller_id=seller.id,
            category_id=digital.id,
            name="机械键盘 87 键 青轴",
            description="95 新，功能正常，带原装数据线，可当面验货。",
            price=150,
            contact="微信：seller01",
            status=ItemStatus.PENDING.value,
        ),
        Item(
            seller_id=seller.id,
            category_id=appliance.id,
            name="护眼台灯 三档调光",
            description="用了一学期，功能正常，灯罩有轻微划痕，不影响使用。",
            price=35,
            contact="微信：seller01",
            status=ItemStatus.DRAFT.value,
        ),
    ]
    db.session.add_all(items)
    db.session.flush()

    for item in items:
        db.session.add(ItemImage(item_id=item.id, url="/static/img/placeholder.png", sort_order=0))

    book_item = items[0]
    reservation = Reservation(
        item_id=book_item.id,
        buyer_id=buyer.id,
        request_id="11111111-1111-4111-8111-111111111111",
        status=ReservationStatus.PENDING.value,
        expires_at=now + timedelta(hours=48),
    )
    book_item.status = ItemStatus.RESERVED.value
    db.session.add(reservation)
    db.session.commit()
