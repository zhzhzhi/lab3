"""Item reports: submit, review and take-down rules."""

from __future__ import annotations

from sqlalchemy import func

from ..common.audit import record_log
from ..common.clock import clock
from ..common.errors import BusinessError
from ..enums import ItemStatus, ReportStatus, Role
from ..extensions import db
from ..models import Item, Report

REPORTABLE_STATUSES = (
    ItemStatus.PUBLISHED.value,
    ItemStatus.RESERVED.value,
    ItemStatus.CONFIRMED.value,
    ItemStatus.COMPLETED.value,
)

MIN_REASON_LENGTH = 5
MAX_REASON_LENGTH = 500


def submit_report(reporter, item_id: int, reason: str) -> Report:
    reason = (reason or "").strip()
    if not MIN_REASON_LENGTH <= len(reason) <= MAX_REASON_LENGTH:
        raise BusinessError(
            f"举报原因需要 {MIN_REASON_LENGTH}–{MAX_REASON_LENGTH} 个字符。",
            current_state="表单校验未通过",
            next_step="补充具体问题后重新提交。",
        )

    item = db.session.get(Item, item_id)
    if item is None:
        raise BusinessError("商品不存在。", status_code=404, next_step="返回商品广场。")
    if item.seller_id == reporter.id:
        raise BusinessError("不能举报自己发布的商品。")
    if item.status not in REPORTABLE_STATUSES:
        raise BusinessError(
            "该商品当前不可举报。",
            current_state=item.status_label,
            next_step="刷新页面后重试。",
        )

    duplicated = Report.query.filter_by(
        reporter_id=reporter.id,
        item_id=item.id,
        status=ReportStatus.PENDING.value,
    ).first()
    if duplicated is not None:
        raise BusinessError(
            "你已提交过该商品的举报，请等待管理员处理。",
            current_state="待处理",
            next_step="在管理员处理前无需重复提交。",
        )

    report = Report(
        reporter_id=reporter.id,
        item_id=item.id,
        reason=reason,
        status=ReportStatus.PENDING.value,
    )
    db.session.add(report)
    db.session.flush()
    record_log(reporter.id, "submit_report", "report", report.id, detail=item.name)
    db.session.commit()
    return report


def list_reports(status: str | None = None):
    query = Report.query
    if status:
        query = query.filter(Report.status == status)
    return query.order_by(Report.created_at.desc(), Report.id.desc())


def pending_report_count() -> int:
    return Report.query.filter_by(status=ReportStatus.PENDING.value).count()


def report_counts() -> dict[str, int]:
    counts = {status.value: 0 for status in ReportStatus}
    rows = (
        db.session.query(Report.status, func.count(Report.id))
        .group_by(Report.status)
        .all()
    )
    for status, count in rows:
        counts[status] = count
    return counts


def handle_report(admin, report_id: int, accepted: bool, note: str = "") -> Report:
    """Accept or reject a report; an accepted report takes the item off shelf."""
    if not admin.has_role(Role.ADMIN):
        raise BusinessError("只有管理员可以处理举报。", status_code=403)

    report = db.session.get(Report, report_id)
    if report is None:
        raise BusinessError("举报记录不存在。", status_code=404)
    if report.status != ReportStatus.PENDING.value:
        raise BusinessError(
            "该举报已经处理过。",
            current_state=report.status_label,
            next_step="刷新页面查看最新状态。",
        )

    note = (note or "").strip()[:500]
    report.status = (
        ReportStatus.RESOLVED.value if accepted else ReportStatus.REJECTED.value
    )
    report.handled_by = admin.id
    report.handled_at = clock.now()
    report.result = note or ("举报成立" if accepted else "举报不成立")

    if accepted:
        _take_down(report.item, f"举报成立：{report.result}")

    record_log(
        admin.id,
        "handle_report",
        "report",
        report.id,
        detail=f"{report.status_label}：{report.result}",
    )
    db.session.commit()
    return report


def _take_down(item: Item, reason: str) -> None:
    """Force a reported item off the shelf (active reservations stay for arbitration)."""
    if item.status == ItemStatus.OFF_SHELF.value:
        item.off_shelf_reason = reason[:200]
        return
    if item.status == ItemStatus.COMPLETED.value:
        return
    item.status = ItemStatus.OFF_SHELF.value
    item.off_shelf_reason = reason[:200]
    item.version += 1
