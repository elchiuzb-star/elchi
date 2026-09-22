"""Operations and growth constants (A13, wave 4; spec §19.3, §20.2, §20.4). Dependency-free (AGENTS §4).

Share links (§20.2) are a growth tool, not an identity leak: the public page shows the route, the window and the
price, never a name, phone or exact address. The token is a secret (ADR-0018) and only its SHA-256 is stored.

KPI (§20.4) are *targets to agree on*, not industry norms, and every ratio is reported with its numerator and
denominator so a small n is visible instead of a flattering percentage.
"""

from __future__ import annotations

from datetime import timedelta

# --- share links (O1-O3) ---------------------------------------------------------------------------------------
SHARE_LINK_TOKEN_BYTES = 32
SHARE_LINK_MIN_TTL_HOURS = 1
SHARE_LINK_MAX_TTL_HOURS = 24 * 14
SHARE_LINK_DEFAULT_TTL_HOURS = 48
SHARE_LINK_MAX_ACTIVE_PER_LISTING = 5
# Path of the public page; the deployment may put a web page in front of it (ELCHI_SHARE_PUBLIC_URL_TEMPLATE).
SHARE_LINK_PUBLIC_PATH = "/api/v2/public/listings/{token}"

# --- ops queues (O4) -------------------------------------------------------------------------------------------
OPS_QUEUE_DEFAULT_LIMIT = 20
OPS_QUEUE_MAX_LIMIT = 100

# --- KPI (O5, §20.4) -------------------------------------------------------------------------------------------
# "at least one valid offer within 30 minutes for >= 70 % of matching requests"
OFFER_TARGET = timedelta(minutes=30)
# Targets agreed for the pilot; shown next to the measured value, never used to round one up.
KPI_TARGETS: dict[str, float] = {
    "offer_within_target": 0.70,
    "booking_completion": 0.90,
    "driver_fault_cancel": 0.05,  # upper bound
}
# Below this denominator a ratio is reported but marked small_sample: the count is what matters (§20.4).
KPI_SMALL_SAMPLE_BELOW = 30
KPI_MAX_RANGE_DAYS = 92

# --- map / routing quota (§10.8) --------------------------------------------------------------------------------
# Geoapify's published credit rules (§10.8): a map tile costs 0.25 credits, a plain geocode 1, a route 1 per
# request as a *pilot estimate* - routing cost varies with waypoints and length, so the operator answer calls the
# number an estimate and never a bill.
PROVIDER_CREDIT_COST: dict[str, float] = {"route": 1.0, "geocode": 1.0, "tile": 0.25}
# Free tier of the provider we would start with; configurable per deployment once a plan is bought.
PROVIDER_DAILY_CREDIT_LIMIT = 3000
# §10.8: warn the operator at 70 %, restrict optional calls at 85 %. Ingesting GPS is never restricted.
PROVIDER_QUOTA_WARN_RATIO = 0.70
PROVIDER_QUOTA_RESTRICT_RATIO = 0.85

# --- SLO (O6, §19.3) -------------------------------------------------------------------------------------------
# "95 % of active tracking points on a good network are fresher than 30 seconds"
TRACKING_FRESH_SECONDS = 30
TRACKING_FRESHNESS_TARGET = 0.95
# Feed p95 < 1 s and accept p95 < 2 s are spec targets; this application does not measure request latency itself
# (no metrics store), so those fields are reported as null with measured=false instead of an invented number.
LATENCY_TARGETS_SECONDS: dict[str, float] = {"feed_p95": 1.0, "booking_accept_p95": 2.0}
SLO_MAX_RANGE_DAYS = 31
