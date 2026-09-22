"""Decision 29: the read-only legacy-rate check matches migration 0036's rule exactly."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.modules.wallet.checks import LegacyRateError, parse_legacy_rate

REPO_ROOT = Path(__file__).resolve().parents[3]


def _migration_0036():
    path = REPO_ROOT / "alembic" / "versions" / "20260913_0036_wallet_commission_policies.py"
    spec = importlib.util.spec_from_file_location("a3_migration_0036", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALID = [(None, 1500), ("0.15", 1500), ("0.1500", 1500), ("0.125", 1250), (" 0.2 ", 2000), ("1", 10000)]
INVALID = ["0", "0.0000", "0.00001", "abc", "1.5", "-0.1", "NaN", "Infinity"]


@pytest.mark.parametrize(("raw", "bps"), VALID)
def test_valid_rates_match_migration(raw, bps):
    assert parse_legacy_rate(raw) == bps
    assert _migration_0036()._parse_legacy_rate(raw)[0] == bps


@pytest.mark.parametrize("raw", INVALID)
def test_invalid_rates_are_refused_by_both(raw):
    with pytest.raises(LegacyRateError):
        parse_legacy_rate(raw)
    with pytest.raises(Exception):
        _migration_0036()._parse_legacy_rate(raw)
