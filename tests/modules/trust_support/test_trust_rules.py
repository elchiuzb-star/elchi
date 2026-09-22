"""Pure trust & support rules, config and migration literals (A12, wave 3). No database."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.contracts import trust
from app.contracts.enums import (
    DisputeResolutionCode,
    DisputeStatus,
    DisputeType,
    SupportTicketKind,
    SupportTicketStatus,
    TrustReviewDecision,
    TrustReviewStatus,
    TrustSignalType,
)
from app.contracts.errors import DomainError, ErrorCode
from app.modules.trust_support import config, rules

REPO = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


def _migration():  # noqa: ANN202
    path = REPO / "alembic" / "versions" / "20260916_0060_trust_support_disputes_strikes.py"
    spec = importlib.util.spec_from_file_location("a12_0060", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_literals_match_contract_enums() -> None:
    m = _migration()
    assert set(m.DISPUTE_TYPES) == {item.value for item in DisputeType}
    assert set(m.DISPUTE_STATUSES) == {item.value for item in DisputeStatus}
    assert set(m.DISPUTE_RESOLUTION_CODES) == {item.value for item in DisputeResolutionCode}
    assert set(m.TRUST_SIGNAL_TYPES) == {item.value for item in TrustSignalType}
    assert set(m.TRUST_REVIEW_STATUSES) == {item.value for item in TrustReviewStatus}
    assert set(m.TRUST_REVIEW_DECISIONS) == {item.value for item in TrustReviewDecision}
    assert set(m.TRUST_REVIEW_EVIDENCE_KEYS) == set(trust.TRUST_REVIEW_EVIDENCE_KEYS)
    assert set(m.SUPPORT_TICKET_KINDS) == {item.value for item in SupportTicketKind}
    assert set(m.SUPPORT_TICKET_STATUSES) == {item.value for item in SupportTicketStatus}
    assert m.DISPUTE_DESCRIPTION_MAX_LENGTH == trust.DISPUTE_DESCRIPTION_MAX_LENGTH
    assert m.SUPPORT_MESSAGE_MAX_LENGTH == trust.SUPPORT_MESSAGE_MAX_LENGTH
    assert m.RATING_COMMENT_MAX_LENGTH == rules.RATING_COMMENT_MAX_LENGTH
    assert (m.revision, m.down_revision) == ("20260916_0060", "20260916_0059")


def test_blocking_and_visibility_rules() -> None:
    for dtype in DisputeType:
        blocks = rules.dispute_blocks_capture(dtype.value, "open")
        assert blocks is (dtype in trust.BLOCKING_DISPUTE_TYPES)
        assert not rules.dispute_blocks_capture(dtype.value, "resolved")
    assert not rules.dispute_visible_to_side("commission", "client")
    assert rules.dispute_visible_to_side("commission", "driver")
    assert rules.dispute_escalate_at(NOW) == NOW + timedelta(hours=48)


def test_rating_window_is_seven_days() -> None:
    assert rules.rating_window_open(NOW, NOW + timedelta(days=6, hours=23))
    assert not rules.rating_window_open(NOW, NOW + timedelta(days=7))
    assert not rules.rating_window_open(None, NOW)
    assert rules.rating_publish_due(NOW, NOW + timedelta(days=7))
    assert rules.counterpart_side("client") == "driver"
    with pytest.raises(ValueError):
        rules.counterpart_side("operator")


def test_review_decisions() -> None:
    assert rules.review_decision_for("start_review", None) is None
    assert rules.review_decision_for("dismiss", None) == "no_violation"
    assert rules.review_decision_for("action", "warning_issued") == "warning_issued"
    for command, decision in (("action", None), ("action", "no_violation"), ("dismiss", "warning_issued"), ("start_review", "no_violation")):
        with pytest.raises(DomainError) as info:
            rules.review_decision_for(command, decision)
        assert info.value.code is ErrorCode.VALIDATION_ERROR


def test_evidence_merge_keeps_ids_and_counters_only() -> None:
    merged = rules.merge_evidence({"booking_ids": ["bkg_a"]}, {"booking_ids": ["bkg_a", "bkg_b"], "cancel_count": 2})
    assert merged == {"booking_ids": ["bkg_a", "bkg_b"], "cancel_count": 2}
    with pytest.raises(ValueError):
        rules.merge_evidence({}, {"phone": ["+998901234567"]})
    with pytest.raises(ValueError):
        rules.merge_evidence({}, {"hit_count": "3"})
    assert rules.strikes_in_window([NOW - timedelta(days=31), NOW - timedelta(days=2), NOW], NOW) == 2


@pytest.mark.parametrize("hours", ["24/7", "Har kuni 24 soat", "kun-u tun", "Круглосуточно", "javob 15 daqiqada"])
def test_support_contacts_never_promise_response_time(hours: str) -> None:
    available, phone, shown = config.support_contacts(config.SupportSettings(phone="+998711234567", hours_text=hours))
    assert (available, phone, shown) == (True, "+998711234567", None)


def test_support_contacts_unconfigured_is_unavailable() -> None:
    assert config.support_contacts(config.SupportSettings(phone=None, hours_text="Du-Ju 09:00-18:00")) == (False, None, None)
    assert config.support_contacts(config.SupportSettings(phone="+998711234567", hours_text="Du-Ju 09:00-18:00")) == (
        True, "+998711234567", "Du-Ju 09:00-18:00")


def test_consumers_shape() -> None:
    from app.contracts.enums import EventType
    from app.modules.trust_support.consumers import CONSUMERS, RELEVANCE_CHECKS

    assert {c.name: c.event_types for c in CONSUMERS} == {
        "contact_filter_strikes": frozenset({EventType.CONTACT_FILTER_HIT}),
        "cancellation_signals": frozenset({EventType.BOOKING_CANCELLED}),
    }
    assert RELEVANCE_CHECKS == {}
