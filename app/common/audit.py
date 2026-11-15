"""Append-only audit logging helper."""

from __future__ import annotations

from ..enums import ActionResult
from ..extensions import db
from ..models import OperationLog


def record_log(
    operator_id: int | None,
    action_type: str,
    target_type: str,
    target_id: int | None,
    result: str = ActionResult.SUCCESS.value,
    detail: str | None = None,
) -> OperationLog:
    log = OperationLog(
        operator_id=operator_id,
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
        result=result,
        detail=detail,
    )
    db.session.add(log)
    return log
