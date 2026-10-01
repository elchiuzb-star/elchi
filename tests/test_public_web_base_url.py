"""ELCHI_PUBLIC_WEB_BASE_URL: one origin that absolutises the tracking, share and referral links (audit fix).

Priority is the same for all three: the specific setting (template / host) > the base > the old behaviour. With
nothing set, every link is byte-for-byte what it was before the base existed.
"""

from __future__ import annotations

import pytest

from app.core import config as config_module
from app.core.config import Settings, public_web_host
from app.modules.operations import rules
from app.modules.promotions import portal
from app.modules.tracking.config import public_tracking_url


@pytest.fixture
def base(monkeypatch: pytest.MonkeyPatch):
    def set_base(value: str | None) -> None:
        monkeypatch.setattr(config_module.settings, "public_web_base_url", value)

    monkeypatch.delenv("ELCHI_TRACKING_PUBLIC_URL_TEMPLATE", raising=False)
    monkeypatch.setattr(config_module.settings, "referral_link_host", None)
    set_base(None)
    return set_base


def test_the_base_is_normalised_and_validated() -> None:
    assert Settings(_env_file=None, public_web_base_url="https://www.elchigo.uz/").public_web_base_url == "https://www.elchigo.uz"
    assert Settings(_env_file=None, public_web_base_url="  ").public_web_base_url is None
    assert Settings(_env_file=None).public_web_base_url is None
    for bad in ("www.elchigo.uz", "ftp://elchigo.uz", "https://elchigo.uz/?x=1"):
        with pytest.raises(ValueError, match="ELCHI_PUBLIC_WEB_BASE_URL"):
            Settings(_env_file=None, public_web_base_url=bad)
    assert public_web_host(Settings(_env_file=None, public_web_base_url="https://www.elchigo.uz")) == "www.elchigo.uz"
    assert public_web_host(Settings(_env_file=None)) is None


def test_tracking_link(base, monkeypatch: pytest.MonkeyPatch) -> None:
    assert public_tracking_url("tok") == "/api/v2/public/tracking/tok", "nothing set: unchanged"
    base("https://www.elchigo.uz")
    assert public_tracking_url("tok") == "https://www.elchigo.uz/t/tok"
    monkeypatch.setenv("ELCHI_TRACKING_PUBLIC_URL_TEMPLATE", "https://track.example.uz/x/{token}")
    assert public_tracking_url("tok") == "https://track.example.uz/x/tok", "the template keeps priority"
    monkeypatch.setenv("ELCHI_TRACKING_PUBLIC_URL_TEMPLATE", "https://broken.example.uz/")
    assert public_tracking_url("tok") == "https://www.elchigo.uz/t/tok", "a template without {token} is ignored"


def test_share_link() -> None:
    assert rules.public_url("tok") == "/api/v2/public/listings/tok"
    assert rules.public_url("tok", None, "https://www.elchigo.uz") == "https://www.elchigo.uz/e/tok"
    assert rules.public_url("tok", "https://s.example.uz/{token}", "https://www.elchigo.uz") == "https://s.example.uz/tok"


def test_referral_link(base, monkeypatch: pytest.MonkeyPatch) -> None:
    assert portal.share_url("ABC123") is None, "nothing set: no share_url (manual code entry)"
    base("https://www.elchigo.uz")
    assert portal.share_url("ABC123") == "https://www.elchigo.uz/r/ABC123"
    monkeypatch.setattr(config_module.settings, "referral_link_host", "go.elchi.uz")
    assert portal.share_url("ABC123") == "https://go.elchi.uz/r/ABC123", "ELCHI_REFERRAL_LINK_HOST keeps priority"
