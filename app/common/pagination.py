"""Pagination helpers."""

from __future__ import annotations


def normalize_page(value: str | int | None, default: int = 1) -> int:
    try:
        page = int(value or default)
    except (TypeError, ValueError):
        return default
    return max(page, 1)


def normalize_per_page(value: str | int | None, default: int = 20) -> int:
    try:
        per_page = int(value or default)
    except (TypeError, ValueError):
        return default
    if per_page not in (20, 50, 100):
        return default
    return per_page
