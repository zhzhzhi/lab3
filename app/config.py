"""Application configuration."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    """Default development configuration."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{(BASE_DIR / 'instance' / 'app.db').as_posix()}",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Uploads: at most 9 images, 5 MB each, plus form overhead.
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024
    UPLOAD_FOLDER = str(BASE_DIR / "uploads")

    ITEMS_PER_PAGE = 20
    IDEMPOTENCY_WINDOW_HOURS = 24
    RESERVATION_EXPIRE_HOURS = 48
    LOGIN_MAX_ATTEMPTS = 5
    LOGIN_LOCK_MINUTES = 15


class TestConfig(Config):
    """Configuration used by pytest."""

    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
