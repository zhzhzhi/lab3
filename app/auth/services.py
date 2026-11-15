"""Registration and login rules."""

from datetime import timedelta

from flask import current_app

from ..common.clock import clock
from ..common.errors import BusinessError
from ..enums import Role, UserStatus
from ..extensions import db
from ..models import User

SELF_SERVICE_ROLES = {Role.BUYER.value, Role.SELLER.value}


def register_user(
    account: str,
    nickname: str,
    password: str,
    contact: str = "",
    roles: list[str] | None = None,
) -> User:
    """Create a buyer/seller account. Admin accounts are provisioned separately."""
    account = (account or "").strip()
    nickname = (nickname or "").strip()
    if not account or not nickname:
        raise BusinessError("账号和昵称不能为空。", next_step="填写账号和昵称后重试。")
    if len(password or "") < 8:
        raise BusinessError("密码至少需要 8 位。", next_step="换一个更长的密码。")
    if User.query.filter_by(account=account).first():
        raise BusinessError("账号已存在。", next_step="换一个账号，或直接登录。")

    selected = [role for role in (roles or []) if role in SELF_SERVICE_ROLES]
    if not selected:
        selected = [Role.BUYER.value]

    user = User(
        account=account,
        nickname=nickname,
        contact=(contact or "").strip(),
        roles=selected,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def authenticate(account: str, password: str) -> User:
    """Check credentials, lockout state, and account status."""
    user = User.query.filter_by(account=(account or "").strip()).first()
    now = clock.now()
    if user is None:
        raise BusinessError("账号或密码错误。", next_step="检查账号密码后重试。")

    if user.locked_until and user.locked_until > now:
        raise BusinessError(
            "账号已锁定。",
            current_state="锁定中",
            next_step=f"{current_app.config['LOGIN_LOCK_MINUTES']} 分钟后再试。",
        )
    if user.status != UserStatus.ACTIVE.value:
        raise BusinessError(
            "账号已被禁用。",
            current_state=user.status_label,
            next_step="联系管理员处理。",
        )

    if user.check_password(password):
        user.failed_attempts = 0
        user.locked_until = None
        db.session.commit()
        return user

    user.failed_attempts += 1
    maximum = current_app.config["LOGIN_MAX_ATTEMPTS"]
    if user.failed_attempts >= maximum:
        user.locked_until = now + timedelta(
            minutes=current_app.config["LOGIN_LOCK_MINUTES"]
        )
        user.failed_attempts = 0
        db.session.commit()
        raise BusinessError(
            "连续失败次数过多，账号已锁定。",
            current_state="锁定中",
            next_step=f"{current_app.config['LOGIN_LOCK_MINUTES']} 分钟后再试。",
        )

    db.session.commit()
    raise BusinessError("账号或密码错误。", next_step="检查账号密码后重试。")
