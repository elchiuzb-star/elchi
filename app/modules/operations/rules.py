"""Pure operations rules (A13, wave 4): share text, public-page mapping, KPI and SLO arithmetic.

No session, no I/O - unit-testable. Business truthfulness (spec §9, §20.4):
* a ratio with a zero denominator is ``None``, never 0 % or 100 %;
* a small denominator is flagged, so a "100 %" over 3 bookings cannot be read as a result;
* a value this system does not measure is absent or ``measured=False``, never a filled-in number.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.contracts.enums import KpiMetric, ListingKind, ListingStatus, ServiceType, ShareLinkChannel
from app.contracts.operations import (
    KPI_SMALL_SAMPLE_BELOW,
    KPI_TARGETS,
    SHARE_LINK_PUBLIC_PATH,
    TRACKING_FRESHNESS_TARGET,
)

DISPLAY_TZ = ZoneInfo("Asia/Tashkent")
OPEN_LISTING_STATUSES = frozenset({ListingStatus.PUBLISHED.value})
# The listing may still be shared while it is paused, but the page says it is not taking offers.
SHAREABLE_LISTING_STATUSES = frozenset({ListingStatus.PUBLISHED.value, ListingStatus.PAUSED.value})


def money_text(amount_minor: int, currency: str) -> str:
    """``12 000 000`` minor UZS -> ``120 000 UZS``. Integer arithmetic only (AGENTS §6)."""
    major, minor = divmod(int(amount_minor), 100)
    grouped = f"{major:,}".replace(",", " ")
    return f"{grouped} {currency}" if minor == 0 else f"{grouped},{minor:02d} {currency}"


def local_date(moment: datetime) -> date:
    return moment.astimezone(DISPLAY_TZ).date()


def local_time_range(start: datetime, end: datetime) -> str:
    return f"{start.astimezone(DISPLAY_TZ):%H:%M}-{end.astimezone(DISPLAY_TZ):%H:%M}"


def share_text(
    *,
    channel: str,
    kind: str,
    service_type: str,
    origin: str,
    destination: str,
    departure_start: datetime,
    departure_end: datetime,
    total_minor: int,
    currency: str,
    url: str,
) -> str:
    """The text the owner copies into a chat (§20.2). Route, date/window, total price and the link - nothing else.

    No phone, no name and no promise about the platform; the reader opens the page and signs in to offer.
    """
    service = "Yo'lovchi" if service_type == ServiceType.PASSENGER.value else "Pochta"
    what = "qidiruv" if kind == ListingKind.REQUEST.value else "e'lon"
    when = f"{local_date(departure_start):%d.%m.%Y} {local_time_range(departure_start, departure_end)}"
    lines = [
        f"{service} {what}: {origin} - {destination}",
        f"Vaqt: {when}",
        f"Jami: {money_text(total_minor, currency)}",
        url,
    ]
    if channel == ShareLinkChannel.TELEGRAM.value:
        lines.append("Taklif berish uchun havolani oching va ilovaga kiring.")
    return "\n".join(lines)


def public_url(token: str, template: str | None = None) -> str:
    """``template`` comes from the deployment (``ELCHI_SHARE_PUBLIC_URL_TEMPLATE``); it must carry ``{token}``."""
    chosen = (template or "").strip()
    if "{token}" not in chosen:
        chosen = SHARE_LINK_PUBLIC_PATH
    return chosen.replace("{token}", token)


def page_cta(*, status: str, expired: bool) -> str:
    if expired or status not in OPEN_LISTING_STATUSES:
        return "closed"
    return "open_app_to_offer"


# --- KPI ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Ratio:
    """A measured count pair. ``value`` is ``None`` when nothing was measured (denominator 0)."""

    numerator: int
    denominator: int

    @property
    def value(self) -> float | None:
        if self.denominator <= 0:
            return None
        return round(self.numerator / self.denominator, 4)

    @property
    def small_sample(self) -> bool:
        return 0 < self.denominator < KPI_SMALL_SAMPLE_BELOW


def kpi_target(metric: str) -> float | None:
    return KPI_TARGETS.get(metric)


# Metrics whose "numerator" is a count or an amount rather than one side of a ratio: the reader shows the pair,
# never a percentage. ``net_commission_per_corridor`` is money (minor units) with the number of bookings behind it.
NON_RATIO_METRICS = frozenset(
    {KpiMetric.LISTINGS_PUBLISHED.value, KpiMetric.NET_COMMISSION_PER_CORRIDOR.value}
)


def metric_is_ratio(metric: str) -> bool:
    """A plain count or an amount is not shown as a ratio (§20.4: the count is what matters)."""
    return metric not in NON_RATIO_METRICS


def freshness_ratio(fresh_points: int, total_points: int) -> Ratio:
    """§19.3: share of stored points that were fresher than ``TRACKING_FRESH_SECONDS`` when the next one arrived."""
    return Ratio(fresh_points, total_points)


def freshness_target() -> float:
    return TRACKING_FRESHNESS_TARGET
