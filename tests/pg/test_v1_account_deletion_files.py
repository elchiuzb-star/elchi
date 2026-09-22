"""BR wave-3 L6: account deletion removes uploads only after the root transaction commits.

v1 commits itself; v2 ``DELETE /me`` reuses the v1 service through ``_DeferredCommitSession`` (commit = flush) and the
idempotent runner commits later. Files must survive any rollback of the deleting transaction, including a released
SAVEPOINT (``after_commit`` also fires there) followed by a root rollback.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.config import settings
from app.models import DriverDocument, DriverProfile, User
from app.modules.trust_support.service import _DeferredCommitSession
from app.services.account_deletion_service import delete_own_account
from tests.pg.conftest import PgDatabase

pytestmark = pytest.mark.pg


@pytest.fixture
def upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "uploads"
    root.mkdir()
    monkeypatch.setattr(settings, "upload_dir", str(root))
    return root


def driver_with_document(pg_db: PgDatabase, upload_dir: Path, phone: str) -> tuple[int, Path]:
    key = f"passport/2026/06/{uuid4().hex}.jpg"
    path = upload_dir / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"stored-bytes")
    with pg_db.session() as db:
        user = User(phone=phone, role="driver", status="active", is_phone_verified=True)
        db.add(user)
        db.flush()
        profile = DriverProfile(user_id=user.id, verification_status="new")
        db.add(profile)
        db.flush()
        db.add(DriverDocument(driver_id=profile.id, document_type="passport", file_url=f"/uploads/{key}", status="pending"))
        db.commit()
        return user.id, path


def state(pg_db: PgDatabase, user_id: int) -> tuple[str, int]:
    with pg_db.session() as db:
        documents = len(db.scalars(select(DriverDocument).join(DriverProfile).where(DriverProfile.user_id == user_id)).all())
        return db.get(User, user_id).status, documents


def test_v1_commit_removes_files(pg_db: PgDatabase, upload_dir: Path) -> None:
    user_id, path = driver_with_document(pg_db, upload_dir, "+998934000001")
    with pg_db.session() as db:
        assert delete_own_account(db, db.get(User, user_id))["deleted"] is True
    assert not path.exists()
    assert state(pg_db, user_id) == ("deleted", 0)


def test_v2_deferred_commit_then_rollback_keeps_files_and_rows(pg_db: PgDatabase, upload_dir: Path) -> None:
    user_id, path = driver_with_document(pg_db, upload_dir, "+998934000002")
    with pg_db.session() as db:
        result = delete_own_account(_DeferredCommitSession(db), db.get(User, user_id))  # type: ignore[arg-type]
        assert result["deleted"] is True
        assert path.is_file()  # flushed only: nothing removed before the real commit
        db.rollback()  # e.g. the runner's commit failed
        assert path.is_file()
        db.commit()  # a later commit on the same session must not replay the dropped removal
    assert path.is_file()
    assert state(pg_db, user_id) == ("active", 1)


def test_v2_deferred_commit_then_real_commit_removes_files(pg_db: PgDatabase, upload_dir: Path) -> None:
    user_id, path = driver_with_document(pg_db, upload_dir, "+998934000003")
    with pg_db.session() as db:
        delete_own_account(_DeferredCommitSession(db), db.get(User, user_id))  # type: ignore[arg-type]
        assert path.is_file()
        db.commit()
    assert not path.exists()
    assert state(pg_db, user_id) == ("deleted", 0)


def test_released_savepoint_then_root_rollback_keeps_files(pg_db: PgDatabase, upload_dir: Path) -> None:
    user_id, path = driver_with_document(pg_db, upload_dir, "+998934000004")
    with pg_db.session() as db:
        user = db.get(User, user_id)
        savepoint = db.begin_nested()
        delete_own_account(_DeferredCommitSession(db), user)  # type: ignore[arg-type]
        savepoint.commit()  # RELEASE SAVEPOINT fires after_commit: must not remove files
        assert path.is_file()
        db.rollback()
    assert path.is_file()
    assert state(pg_db, user_id) == ("active", 1)
