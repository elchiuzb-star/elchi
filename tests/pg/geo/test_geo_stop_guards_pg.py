"""Q47 continuous stop guards for pilot/active corridors and N2 stop photo validation (wave 1.6)."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.errors import DomainError, ErrorCode
from app.core.config import settings
from app.modules.geo import service
from app.modules.geo.types import LatLng
from tests.fixtures.geo.loader import load_geo_fixture
from tests.pg.conftest import PgDatabase
from tests.pg.geo.geo_pg_helpers import create_user
from tests.pg.harness import run_concurrently

pytestmark = pytest.mark.pg


@pytest.fixture
def pilot(pg_db: PgDatabase):  # noqa: ANN201
    """Fixture corridor in `pilot`, reduced to exactly 3 active stops (all with meeting notes)."""
    admin = create_user(pg_db, "admin")
    with pg_db.session() as db:
        fx = load_geo_fixture(db, actor_user_id=admin, with_routes=False)
        for key in ("kattaqorgon", "kitob", "chiroqchi"):
            stop = fx.stops[key]
            fx.stops[key] = service.patch_stop(db, actor_user_id=admin, stop_api_id=stop.api_id, expected_version=stop.version, changes={"is_active": False})
            db.commit()
    return pg_db, fx, admin


def reason_of(fn) -> str:  # noqa: ANN001
    with pytest.raises(DomainError) as info:
        fn()
    assert info.value.code is ErrorCode.INVALID_STATE_TRANSITION, info.value.code
    return info.value.details["reason"]


def active_count(pg_db: PgDatabase, corridor_id: int) -> int:
    with pg_db.engine.connect() as conn:
        return conn.scalar(text("SELECT count(*) FROM corridor_stops WHERE corridor_id = :c AND is_active"), {"c": corridor_id})


def test_service_enforces_guards_on_every_stop_change(pilot) -> None:  # noqa: ANN001
    pg_db, fx, admin = pilot
    toshkent, samarqand, qarshi = fx.stops["toshkent"], fx.stops["samarqand"], fx.stops["qarshi"]
    with pg_db.session() as db:
        # 3 -> 2 active is fine; 2 -> 1 is not.
        service.patch_stop(db, actor_user_id=admin, stop_api_id=samarqand.api_id, expected_version=samarqand.version, changes={"is_active": False})
        db.commit()
        assert reason_of(lambda: service.patch_stop(db, actor_user_id=admin, stop_api_id=qarshi.api_id, expected_version=qarshi.version, changes={"is_active": False})) == "needs_two_active_stops"
        db.rollback()
        # Removing the only evidence of an active stop is refused.
        assert reason_of(lambda: service.patch_stop(db, actor_user_id=admin, stop_api_id=toshkent.api_id, expected_version=toshkent.version, changes={"meeting_note": "  "})) == "stops_missing_meeting_evidence"
        db.rollback()
        # A new active stop without evidence is refused; with a note it is accepted.
        new_stop = dict(
            corridor_api_id=fx.corridor.api_id, name_ru=None, district_api_id=fx.district_api_ids["kitob"],
            point=LatLng(39.12, 66.88), sequence_hint=26, is_active=True,
        )
        assert reason_of(lambda: service.create_stop(db, actor_user_id=admin, name_uz="Yangi bekat", meeting_note=None, **new_stop)) == "stops_missing_meeting_evidence"
        db.rollback()
        created = service.create_stop(db, actor_user_id=admin, name_uz="Yangi bekat", meeting_note="Choyxona oldida", **new_stop)
        db.commit()
        # Re-activating a stop without evidence is refused too.
        kitob = fx.stops["kitob"]
        service.patch_stop(db, actor_user_id=admin, stop_api_id=kitob.api_id, expected_version=kitob.version, changes={"meeting_note": None})
        db.commit()  # inactive stops need no evidence
        assert reason_of(lambda: service.patch_stop(db, actor_user_id=admin, stop_api_id=kitob.api_id, expected_version=kitob.version + 1, changes={"is_active": True})) == "stops_missing_meeting_evidence"
        db.rollback()
    assert created.is_active and active_count(pg_db, fx.corridor.id) == 3


def test_draft_and_internal_corridors_are_not_restricted(pg_db: PgDatabase) -> None:
    admin = create_user(pg_db, "admin")
    with pg_db.session() as db:
        fx = load_geo_fixture(db, actor_user_id=admin, with_routes=False)
        corridor = service.patch_corridor(db, actor_user_id=admin, corridor_api_id=fx.corridor.api_id, expected_version=fx.corridor.version, reason="back", changes={"rollout_state": "internal"})
        db.commit()
        for key in ("toshkent", "samarqand", "kattaqorgon", "kitob", "chiroqchi"):
            stop = fx.stops[key]
            service.patch_stop(db, actor_user_id=admin, stop_api_id=stop.api_id, expected_version=stop.version, changes={"is_active": False, "meeting_note": None})
        db.commit()
    assert corridor.rollout_state.value == "internal" and active_count(pg_db, fx.corridor.id) == 1


def test_concurrent_service_deactivations_cannot_drop_below_two(pilot) -> None:  # noqa: ANN001
    pg_db, fx, admin = pilot
    targets = [fx.stops["toshkent"], fx.stops["samarqand"]]

    def deactivate(worker: int, session) -> str:  # noqa: ANN001
        stop = targets[worker]
        service.patch_stop(session, actor_user_id=admin, stop_api_id=stop.api_id, expected_version=stop.version, changes={"is_active": False})
        session.commit()
        return stop.api_id

    report = run_concurrently(2, deactivate, engine=pg_db.engine)
    assert len(report.successes) == 1
    failures = report.errors_of(DomainError)
    assert len(failures) == 1 and failures[0].error.details["reason"] == "needs_two_active_stops"
    assert active_count(pg_db, fx.corridor.id) == 2


def test_concurrent_raw_sql_deactivations_are_stopped_by_the_deferred_db_guard(pilot) -> None:  # noqa: ANN001
    pg_db, fx, _ = pilot
    ids = [fx.stops["toshkent"].id, fx.stops["samarqand"].id]

    def deactivate(worker: int, session) -> int:  # noqa: ANN001
        session.execute(text("UPDATE corridor_stops SET is_active = false, version = version + 1 WHERE id = :id"), {"id": ids[worker]})
        session.commit()  # the constraint trigger runs here, after locking the corridor row
        return ids[worker]

    report = run_concurrently(2, deactivate, engine=pg_db.engine)
    assert len(report.successes) == 1
    failures = report.errors_of(DBAPIError)
    assert len(failures) == 1 and "at least 2 active stops" in str(failures[0].error)
    assert active_count(pg_db, fx.corridor.id) == 2


def test_db_guard_on_evidence_and_rollout_without_service(pilot) -> None:  # noqa: ANN001
    pg_db, fx, admin = pilot
    with pytest.raises(DBAPIError, match="meeting note or photo"):
        with pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE corridor_stops SET meeting_note = NULL, version = version + 1 WHERE id = :id"), {"id": fx.stops["qarshi"].id})
    # Deferred: a transaction may add a stop before retiring another.
    with pg_db.engine.begin() as conn:
        conn.execute(text("UPDATE corridor_stops SET is_active = false, version = version + 1 WHERE id IN (:a, :b)"), {"a": fx.stops["toshkent"].id, "b": fx.stops["samarqand"].id})
        conn.execute(text("UPDATE corridor_stops SET is_active = true, version = version + 1 WHERE id IN (:a, :b)"), {"a": fx.stops["kitob"].id, "b": fx.stops["chiroqchi"].id})
    assert active_count(pg_db, fx.corridor.id) == 3
    # A corridor cannot be pushed to pilot by SQL while its stops break the rules.
    with pg_db.session() as db:
        corridor = service.create_corridor(
            db, actor_user_id=admin, name="SQL rollout", origin_region_api_id=fx.regions["toshkent"].api_id,
            destination_region_api_id=fx.regions["samarqand"].api_id, search_radius_m=3000, default_max_detour_minutes=10, default_max_detour_m=1000,
        )
        service.create_stop(
            db, actor_user_id=admin, corridor_api_id=corridor.api_id, name_uz="Yolg'iz bekat", name_ru=None,
            district_api_id=fx.district_api_ids["samarqand"], point=LatLng(39.6, 66.9), meeting_note=None, sequence_hint=0, is_active=True,
        )
        db.commit()
    with pytest.raises(DBAPIError, match="at least 2 active stops"):
        with pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE service_corridors SET rollout_state = 'pilot', version = version + 1 WHERE id = :id"), {"id": corridor.id})


# --- N2: meeting photo references --------------------------------------------------------------------


def test_meeting_photo_requires_an_existing_stop_photo_upload(pilot) -> None:  # noqa: ANN001
    """`stop_photo` is a real upload type now (wave 1.6 integration); a reference to a missing file is refused."""
    pg_db, fx, admin = pilot
    stop = fx.stops["qarshi"]
    with pg_db.session() as db:
        with pytest.raises(DomainError) as info:
            service.patch_stop(db, actor_user_id=admin, stop_api_id=stop.api_id, expected_version=stop.version, changes={"meeting_photo_file_id": f"stop_photo/2026/09/u{admin}/abc.jpg"})
    assert info.value.code is ErrorCode.VALIDATION_ERROR
    assert info.value.details == {"field": "meeting_photo_file_id", "reason": "invalid_file_reference"}


def test_meeting_photo_must_be_own_existing_image_upload(pilot, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    """Exercises H0's resolve_attachment with an existing image-only upload type standing in for `stop_photo`."""
    pg_db, fx, admin = pilot
    monkeypatch.setattr(service, "STOP_PHOTO_UPLOAD_TYPE", "car_photo")
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    other = create_user(pg_db, "admin")
    folder = tmp_path / "car_photo" / "2026" / "09"
    for owner, name in ((admin, "meet1.jpg"), (other, "meet2.jpg"), (admin, "meet3.pdf")):
        (folder / f"u{owner}").mkdir(parents=True, exist_ok=True)
        (folder / f"u{owner}" / name).write_bytes(b"\xff\xd8\xff" + b"0" * 32)
    stop = fx.stops["qarshi"]

    def attempt(value: str, version: int):  # noqa: ANN202
        with pg_db.session() as db:
            result = service.patch_stop(db, actor_user_id=admin, stop_api_id=stop.api_id, expected_version=version, changes={"meeting_photo_file_id": value})
            db.commit()
            return result

    for bad in (
        f"car_photo/2026/09/u{other}/meet2.jpg",  # someone else's upload
        f"car_photo/2026/09/u{admin}/missing.jpg",  # not on disk
        f"car_photo/2026/09/u{admin}/meet3.pdf",  # not an image
        f"selfie/2026/09/u{admin}/meet1.jpg",  # wrong upload type
        "../../etc/passwd",
    ):
        with pytest.raises(DomainError) as info:
            attempt(bad, stop.version)
        assert info.value.details["reason"] == "invalid_file_reference", bad

    saved = attempt(f"/api/v1/files/car_photo/2026/09/u{admin}/meet1.jpg?exp=1&sig=x", stop.version)
    assert saved.meeting_photo_file_id == f"/uploads/car_photo/2026/09/u{admin}/meet1.jpg"
    # Photo alone is evidence: the note can go.
    cleared = attempt(saved.meeting_photo_file_id, saved.version)  # same value is kept as is
    with pg_db.session() as db:
        final = service.patch_stop(db, actor_user_id=admin, stop_api_id=stop.api_id, expected_version=cleared.version, changes={"meeting_note": None})
        db.commit()
    assert final.meeting_note is None and final.meeting_photo_file_id == saved.meeting_photo_file_id
