"""Injectable clock so time-dependent rules can be tested."""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return naive UTC time, matching the values stored in SQLite."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Clock:
    """Small wrapper that tests can monkeypatch."""

    def now(self) -> datetime:
        return utcnow()


clock = Clock()
