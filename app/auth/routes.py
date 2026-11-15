"""Login, registration and logout routes."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user

from ..common.errors import BusinessError
from .services import authenticate, register_user

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    if request.method == "POST":
        account = request.form.get("account", "")
        password = request.form.get("password", "")
        try:
            user = authenticate(account, password)
        except BusinessError as exc:
            flash(str(exc), "error")
            return render_template("auth/login.html", account=account), 400

        login_user(user, remember=request.form.get("remember") == "on")
        next_url = request.args.get("next")
        return redirect(next_url or url_for("main.index"))

    return render_template("auth/login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if password != confirm:
            flash("两次输入的密码不一致。", "error")
            return render_template("auth/register.html"), 400

        try:
            user = register_user(
                account=request.form.get("account", ""),
                nickname=request.form.get("nickname", ""),
                password=password,
                contact=request.form.get("contact", ""),
                roles=request.form.getlist("roles"),
            )
        except BusinessError as exc:
            flash(str(exc), "error")
            return render_template("auth/register.html"), 400

        login_user(user)
        flash("注册成功。", "success")
        return redirect(url_for("main.index"))

    return render_template("auth/register.html")


@auth_bp.get("/logout")
def logout():
    logout_user()
    flash("已退出登录。", "success")
    return redirect(url_for("auth.login"))
