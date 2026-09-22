"""Q56 GateReport shape (unit, SQLite): fail closed off PostgreSQL, JSON-serialisable, ``passed`` alias."""

from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.modules.platform.service import GateCheck, GateReport, q48_gate_status


def test_gate_fails_closed_off_postgresql():
    with Session(create_engine("sqlite://")) as session:
        report = q48_gate_status(session)
    assert report.ok is False and report.passed is False
    assert report.failed == ["postgresql"]
    assert json.loads(json.dumps(report.as_dict())) == {
        "ok": False, "checks": [{"name": "postgresql", "ok": False, "detail": "not_postgresql"}]}


def test_gate_report_failed_lists_only_failing_checks():
    report = GateReport(False, (GateCheck("app_role_not_superuser", True, "role=app"),
                                GateCheck("seed_rate_confirmed", False)))
    assert report.failed == ["seed_rate_confirmed"] and report.passed is False
