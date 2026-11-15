"""Business exceptions carry the three-part failure message required by REQ-025."""

from __future__ import annotations


class BusinessError(Exception):
    """A controlled failure: current state, reason, and a suggested next step."""

    def __init__(
        self,
        message: str,
        *,
        current_state: str | None = None,
        reason: str | None = None,
        next_step: str | None = None,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.current_state = current_state
        self.reason = reason or message
        self.next_step = next_step
        self.status_code = status_code

    def __str__(self) -> str:
        parts = [self.message]
        if self.current_state:
            parts.append(f"当前状态：{self.current_state}")
        if self.next_step:
            parts.append(f"下一步：{self.next_step}")
        return "；".join(parts)

    def to_dict(self) -> dict[str, str | None]:
        return {
            "message": self.message,
            "current_state": self.current_state,
            "reason": self.reason,
            "next_step": self.next_step,
        }
