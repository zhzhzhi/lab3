"""Report submission and admin handling tests."""

import pytest

from app.common.errors import BusinessError
from app.enums import ItemStatus, ReportStatus, Role
from app.extensions import db
from app.models import Item, Report
from app.reports.services import handle_report, submit_report
from tests.helpers import make_category, make_item, make_user


def _setup():
    seller = make_user("seller", roles=[Role.SELLER.value, Role.BUYER.value])
    reporter = make_user("reporter")
    admin = make_user("admin", roles=[Role.ADMIN.value])
    category = make_category()
    item = make_item(seller, category)
    db.session.commit()
    return seller, reporter, admin, item


def _login(client, account, password="password123"):
    return client.post("/auth/login", data={"account": account, "password": password})


def test_submit_report_creates_pending_record(app):
    _, reporter, _, item = _setup()

    report = submit_report(reporter, item.id, "商品实物与描述严重不符")

    assert report.status == ReportStatus.PENDING.value
    assert report.reporter_id == reporter.id
    assert db.session.get(Item, item.id).status == ItemStatus.PUBLISHED.value


def test_cannot_report_own_item(app):
    seller, _, _, item = _setup()

    with pytest.raises(BusinessError) as excinfo:
        submit_report(seller, item.id, "商品实物与描述严重不符")
    assert "自己" in excinfo.value.message


def test_report_reason_length_is_validated(app):
    _, reporter, _, item = _setup()

    with pytest.raises(BusinessError) as excinfo:
        submit_report(reporter, item.id, "太短")
    assert "5–500" in excinfo.value.message


def test_duplicate_pending_report_is_rejected(app):
    _, reporter, _, item = _setup()
    submit_report(reporter, item.id, "商品实物与描述严重不符")

    with pytest.raises(BusinessError) as excinfo:
        submit_report(reporter, item.id, "同一商品再举报一次")
    assert "已提交过" in excinfo.value.message


def test_report_only_visible_items(app):
    seller, reporter, _, item = _setup()
    draft = make_item(seller, item.category, status=ItemStatus.DRAFT.value)

    with pytest.raises(BusinessError):
        submit_report(reporter, draft.id, "商品实物与描述严重不符")


def test_accepted_report_takes_item_down(app):
    _, reporter, admin, item = _setup()
    report = submit_report(reporter, item.id, "商品实物与描述严重不符")

    handle_report(admin, report.id, accepted=True, note="核实属实")

    assert report.status == ReportStatus.RESOLVED.value
    assert report.handled_by == admin.id
    assert report.handled_at is not None
    saved = db.session.get(Item, item.id)
    assert saved.status == ItemStatus.OFF_SHELF.value
    assert "举报成立" in saved.off_shelf_reason


def test_rejected_report_keeps_item_online(app):
    _, reporter, admin, item = _setup()
    report = submit_report(reporter, item.id, "商品实物与描述严重不符")

    handle_report(admin, report.id, accepted=False, note="核实后不成立")

    assert report.status == ReportStatus.REJECTED.value
    assert db.session.get(Item, item.id).status == ItemStatus.PUBLISHED.value


def test_only_admin_can_handle_reports(app):
    _, reporter, _, item = _setup()
    report = submit_report(reporter, item.id, "商品实物与描述严重不符")

    with pytest.raises(BusinessError) as excinfo:
        handle_report(reporter, report.id, accepted=True)
    assert excinfo.value.status_code == 403


def test_report_cannot_be_handled_twice(app):
    _, reporter, admin, item = _setup()
    report = submit_report(reporter, item.id, "商品实物与描述严重不符")
    handle_report(admin, report.id, accepted=False)

    with pytest.raises(BusinessError) as excinfo:
        handle_report(admin, report.id, accepted=True)
    assert "已经处理" in str(excinfo.value)


def test_report_routes(client, app):
    _, reporter, admin, item = _setup()

    _login(client, "reporter")
    assert client.get(f"/reports/item/{item.id}").status_code == 200
    response = client.post(
        f"/reports/item/{item.id}", data={"reason": "商品实物与描述严重不符"}
    )
    assert response.status_code == 302
    assert Report.query.count() == 1

    assert client.get("/reports/").status_code == 200
    assert client.get("/admin/reports/").status_code == 403

    client.get("/auth/logout")
    _login(client, "admin")
    body = client.get("/admin/reports/").get_data(as_text=True)
    assert item.name in body
    assert client.get("/reports/").status_code == 403

    report = Report.query.one()
    client.post(
        f"/admin/reports/{report.id}/handle",
        data={"decision": "accept", "note": "核实属实"},
    )
    assert report.status == ReportStatus.RESOLVED.value
