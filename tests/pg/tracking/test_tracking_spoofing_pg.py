"""Q149 on PostgreSQL: spoofing-like points are stored with their flags, never move the live marker when untrusted,
and a session that keeps sending them opens exactly one `suspicious_location` signal for an operator - no block,
no penalty (§10.4, §17.3). An honest session opens nothing. SYNTHETIC data."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.contracts.dto import TrackingPointIn
from app.contracts.enums import FraudSignalType
from app.modules.tracking import service as tracking_service
from app.modules.trust_support import service as trust_service
from app.modules.trust_support.models import FraudSignal
from tests.pg.tracking.conftest import BW, LAT, LNG, passenger_booking, point, rows, send, start_session

pytestmark = pytest.mark.pg


def _p(seq: int, at, *, lat: float = LAT, acc: int = 10, speed: int | None = None, mock: bool = False) -> TrackingPointIn:  # noqa: ANN001
    return TrackingPointIn(seq=seq, captured_at=at, lat=lat, lng=LNG, accuracy_m=acc, speed_mps=speed, is_mock=mock, battery_pct=70)


def _flags(bw: BW, session_public: str) -> dict[int, list[str]]:
    with bw.db.session() as s:
        sid = tracking_service._session_by_public_id(s, session_public).id
    return dict(rows(bw.db, "SELECT seq, quality_flags FROM tracking_points WHERE session_id = :s", s=sid))


def _signals(bw: BW) -> list[FraudSignal]:
    with bw.db.session() as s:
        return s.execute(
            select(FraudSignal).where(FraudSignal.signal_type == FraudSignalType.SUSPICIOUS_LOCATION.value)
        ).scalars().all()


def test_q149_spoofing_points_are_flagged_and_zero_accuracy_never_moves_the_marker(tw: BW) -> None:
    trip_id, trip_public, _ = passenger_booking(tw, "01T149AA")
    now = tw.base - timedelta(minutes=10)
    sid = start_session(tw, trip_public)
    send(tw, sid, [_p(0, now, speed=0)], now=now)
    ack = send(
        tw, sid,
        [
            _p(1, now + timedelta(seconds=10), lat=LAT + 0.0027, speed=0),   # ~300 m in 10 s, device says standing
            _p(2, now + timedelta(seconds=20), lat=LAT + 0.0100, acc=0),     # 0 m accuracy
        ],
        now=now + timedelta(seconds=21),
    )
    assert ack.accepted_seqs == [1, 2]
    flags = _flags(tw, sid)
    assert flags[0] == [] and flags[1] == ["speed_mismatch"] and "zero_accuracy" in flags[2]
    with tw.db.session() as s:
        live = tracking_service._trip_live_point(s, trip_id)
    # speed_mismatch is a signal only (the marker follows it); the 0 m point is not trusted and does not move it
    assert live.captured_at == now + timedelta(seconds=10)


def test_q149_repeated_spoofing_opens_one_signal_with_counts_only(tw: BW) -> None:
    _, trip_public, _ = passenger_booking(tw, "01T149AB")
    now = tw.base - timedelta(minutes=10)
    sid = start_session(tw, trip_public)
    send(
        tw, sid,
        [
            point(0, now),
            point(1, now + timedelta(seconds=10), mock=True),
            _p(2, now + timedelta(seconds=20), acc=0),
            point(3, now + timedelta(seconds=30), lat=LAT + 1.0),  # ~111 km in 30 s
        ],
        now=now + timedelta(seconds=31),
    )
    with tw.db.session() as s:
        opened = trust_service.scan_fraud_signals(s, now=now + timedelta(minutes=1))
        s.commit()
    assert opened >= 1
    [signal] = _signals(tw)
    assert signal.subject_user_id == tw.w.driver_id and signal.status == "open"
    assert signal.evidence["trip_id"] == [trip_public] and signal.evidence["tracking_session_id"] == [sid]
    assert signal.evidence["suspicious_points"] == 3 and signal.evidence["total_points"] == 4
    assert signal.evidence["flag_mock_location"] == 1 and signal.evidence["flag_zero_accuracy"] == 1
    assert signal.evidence["flag_implausible_speed"] == 1
    assert not any(key in signal.evidence for key in ("lat", "lng", "point", "coordinates"))  # §15: counts only

    with tw.db.session() as s:
        again = trust_service.scan_fraud_signals(s, now=now + timedelta(minutes=2))
        s.commit()
    assert again == 0 and len(_signals(tw)) == 1
    # a signal is a question: the driver keeps publishing and the session stays active
    with tw.db.session() as s:
        assert tracking_service._session_by_public_id(s, sid).status == "active"


def test_q149_honest_session_opens_no_signal(tw: BW) -> None:
    _, trip_public, _ = passenger_booking(tw, "01T149AC")
    now = tw.base - timedelta(minutes=10)
    sid = start_session(tw, trip_public)
    send(
        tw, sid,
        [_p(i, now + timedelta(seconds=10 * i), lat=LAT + 0.0027 * i, speed=29, acc=12) for i in range(6)]
        + [_p(6, now + timedelta(seconds=60), lat=LAT + 0.0027 * 5 + 0.00135, acc=150, speed=0)],  # 150 m jitter at ±150 m
        now=now + timedelta(seconds=61),
    )
    assert all(flags in ([], ["low_accuracy"]) for flags in _flags(tw, sid).values())
    with tw.db.session() as s:
        trust_service.scan_fraud_signals(s, now=now + timedelta(minutes=2))
        s.commit()
    assert _signals(tw) == []
