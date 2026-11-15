"""Shared pytest fixtures."""

import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db


@pytest.fixture
def app(tmp_path):
    class LocalTestConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
        UPLOAD_FOLDER = str(tmp_path / "uploads")

    application = create_app(LocalTestConfig)
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()
