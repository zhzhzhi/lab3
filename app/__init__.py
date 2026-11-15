"""Application factory."""

from pathlib import Path

import click
from flask import Flask, flash, jsonify, redirect, request, url_for

from .common.errors import BusinessError
from .config import Config
from .extensions import db, login_manager


def create_app(config_object: type[Config] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object or Config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    from .models import User

    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    register_blueprints(app)
    register_error_handlers(app)
    register_cli(app)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    return app


def register_blueprints(app: Flask) -> None:
    from .admin.routes import admin_bp
    from .auth.routes import auth_bp
    from .items.routes import admin_items_bp, items_bp
    from .main.routes import main_bp
    from .market.routes import market_bp
    from .reports.routes import admin_reports_bp, reports_bp
    from .reservations.routes import (
        admin_reservations_bp,
        reservations_bp,
        seller_reservations_bp,
    )

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(market_bp)
    app.register_blueprint(items_bp)
    app.register_blueprint(admin_items_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(seller_reservations_bp)
    app.register_blueprint(admin_reservations_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(admin_reports_bp)
    app.register_blueprint(admin_bp)


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(BusinessError)
    def handle_business_error(exc: BusinessError):
        if request.accept_mimetypes.best == "application/json":
            return jsonify(exc.to_dict()), exc.status_code
        flash(str(exc), "error")
        return redirect(request.referrer or url_for("main.index"))


def register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db_command() -> None:
        """Create all database tables."""
        db.create_all()
        click.echo("数据库表已创建。")

    @app.cli.command("seed")
    def seed_command() -> None:
        """Insert demo users, categories and items."""
        from seed import seed_data

        seed_data()
        click.echo("示例数据已写入。")

    @app.cli.command("reset-db")
    def reset_db_command() -> None:
        """Drop, recreate and seed the database."""
        from seed import seed_data

        db.drop_all()
        db.create_all()
        seed_data()
        click.echo("数据库已重置并写入示例数据。")
