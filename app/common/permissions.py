"""Role checks used by routes."""

from functools import wraps
from typing import Callable

from flask import abort, flash, redirect, request, url_for
from flask_login import current_user


def roles_required(*roles: str) -> Callable:
    """Allow only authenticated users with at least one of the given roles."""

    def decorator(view: Callable) -> Callable:
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login", next=request.path))
            if not any(current_user.has_role(role) for role in roles):
                flash("没有权限执行该操作。", "error")
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator
