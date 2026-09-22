"""Marketplace limits that belong to the contract, not to one module (spec §5.2, §5.4). Dependency-free.

These are **pilot defaults**, not legal classifications: a listing above a limit is refused with a clear reason,
so raising one is an explicit product decision instead of a silent truncation. The prohibited-items list itself
is a business decision (§5.2 "admin sozlamasida beriladi") and is deliberately not invented here - this module
provides the enforcement point and the size limits the pilot agreed on.
"""

from __future__ import annotations

# --- §5.2 parcel pilot limits ----------------------------------------------------------------------------------
PARCEL_PILOT_MAX_WEIGHT_G = 50_000  # 50 kg: what one driver can reasonably load without help
PARCEL_PILOT_MAX_DIMENSION_CM = 150  # any single side
PARCEL_PILOT_MAX_VOLUME_ML = 500_000  # 0.5 m3

# --- §5.4 "Yangi e'lon uchun miqdoriy rate-limit ishlaydi" -------------------------------------------------------
# Publishes per author per window. Re-publishing the same post cannot be used to look fresh or to push the feed.
LISTING_PUBLISH_RATE_LIMIT = 10
LISTING_PUBLISH_RATE_WINDOW_S = 3600
