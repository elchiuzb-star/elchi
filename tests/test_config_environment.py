"""ELCHI_ENVIRONMENT allowlist (wave 1.5 BR): unknown values fail Settings() (app start-up and migrations)."""

import pytest
from pydantic import ValidationError

from app.core.config import ALLOWED_ENVIRONMENTS, Settings
from app.modules.platform.service import DeploymentEnvironment


@pytest.mark.parametrize("value", ["production", "staging", "development", "test", "local", " Production "])
def test_allowed_environments_are_accepted_and_normalised(value: str) -> None:
    assert Settings(environment=value).environment == value.strip().lower()


@pytest.mark.parametrize("value", ["prod", "dev", "stage", "", "production2", "PRODUCTION-EU"])
def test_unknown_environment_fails_settings(value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(environment=value)


def test_allowlist_covers_every_db_marker_value() -> None:
    assert {member.value for member in DeploymentEnvironment} <= ALLOWED_ENVIRONMENTS


# --- key rotation settings (N5, ADR-0018) ------------------------------------------------------

OLD = "old-master-secret-value-0001"
NEW = "new-master-secret-value-0002"
DEDICATED = "d" * 32


def test_previous_secret_keys_parse_from_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELCHI_PREVIOUS_SECRET_KEYS", f" {OLD} , ,second-old-master-value ")
    assert Settings().previous_secret_keys == [OLD, "second-old-master-value"]
    monkeypatch.setenv("ELCHI_PREVIOUS_SECRET_KEYS", "")
    assert Settings().previous_secret_keys == []


def test_blank_dedicated_keys_are_unset_and_short_keys_rejected() -> None:
    config = Settings(proof_code_key="  ", cursor_signing_key="")
    assert config.proof_code_key is None and config.cursor_signing_key is None
    with pytest.raises(ValidationError):
        Settings(proof_code_key="too-short")


def test_proof_code_keyring_accepts_previous_master() -> None:
    from app.contracts.crypto import PURPOSE_BOOKING_PROOF_CODE, derive_subkey
    from app.core.config import proof_code_keyring

    rotated = proof_code_keyring(Settings(secret_key=NEW, previous_secret_keys=[OLD]))
    assert rotated.current == derive_subkey(NEW, PURPOSE_BOOKING_PROOF_CODE)
    assert derive_subkey(OLD, PURPOSE_BOOKING_PROOF_CODE) in rotated.previous

    dedicated = proof_code_keyring(Settings(secret_key=NEW, proof_code_key=DEDICATED))
    assert dedicated.current == derive_subkey(DEDICATED, PURPOSE_BOOKING_PROOF_CODE)
    assert dedicated.current != rotated.current


def test_cursor_signing_secret_prefers_dedicated_key() -> None:
    from app.contracts.crypto import PURPOSE_CURSOR_SIGNING, derive_subkey
    from app.core.config import cursor_signing_secret

    assert cursor_signing_secret(Settings(secret_key=NEW)) == derive_subkey(NEW, PURPOSE_CURSOR_SIGNING)
    assert cursor_signing_secret(Settings(secret_key=NEW, cursor_signing_key=DEDICATED)) == derive_subkey(
        DEDICATED, PURPOSE_CURSOR_SIGNING
    )
