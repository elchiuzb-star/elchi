"""S12 ``FraudSignalDTO.evidence`` matches what the detectors store (admin panel bug: a string booking id -> 500)."""

from datetime import datetime, timezone
from types import SimpleNamespace

from app.modules.trust_support import api as trust_api


def test_every_stored_evidence_shape_serialises(monkeypatch) -> None:
    monkeypatch.setattr(trust_api.identity_service, "user_public_id", lambda session, user_id: f"usr_{user_id}")
    monkeypatch.setattr(trust_api.service, "fraud_signal_public_id", lambda signal: "fsg_test")
    shapes = [
        {"booking_id": "bkg_b32mrfk36vh3vdloulbfblnhpa", "shared_device": 1},  # self_dealing_device
        {"window_days": 30, "completed_bookings": 7},  # repeated_pair_bookings
        {"other_accounts": ["usr_a", "usr_b"], "accounts_on_device": 3},  # shared_device_accounts
    ]
    for evidence in shapes:
        signal = SimpleNamespace(
            signal_type="self_dealing_device", subject_user_id=7, status="open", evidence=evidence,
            detected_at=datetime(2026, 10, 4, tzinfo=timezone.utc), reviewed_at=None, version=1,
        )
        dto = trust_api.fraud_signal_dto(None, signal)
        assert dto.evidence == evidence  # ints stay ints, ids stay strings
        assert dto.model_dump(mode="json")["evidence"] == evidence
