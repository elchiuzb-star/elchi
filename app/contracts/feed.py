"""Feed, ranking and saved-search contract (wave 3, A5; spec §6.4, §6.6, §8.2-§8.4; AC18, AC35, AC36).

Pure constants/helpers. Ranking weights are the spec §8.2/§8.4 starting values; a change bumps ``RANKING_VERSION``.
Values marked "(pilot)" are integrator defaults awaiting user confirmation.
"""

from __future__ import annotations

from app.contracts.enums import MatchType

RANKING_VERSION = "2026-09-16.1"  # returned as meta.ranking_version (M1, M2)

# §8.2 client score: 100 * (0.30M + 0.20T + 0.20R + 0.20P + 0.10E)
CLIENT_SCORE_WEIGHTS: dict[str, float] = {"M": 0.30, "T": 0.20, "R": 0.20, "P": 0.20, "E": 0.10}
# §8.4 driver score: 100 * (0.35M + 0.20T + 0.20Y + 0.15C + 0.10F)
DRIVER_SCORE_WEIGHTS: dict[str, float] = {"M": 0.35, "T": 0.20, "Y": 0.20, "C": 0.15, "F": 0.10}
# §8.2 M; alternatives are a separate group (MatchGroup.ALTERNATIVE), not scored against primaries.
MATCH_TYPE_SCORE: dict[MatchType, float] = {MatchType.EXACT: 1.00, MatchType.ON_ROUTE: 0.90, MatchType.DETOUR: 0.65}
NEUTRAL_PRICE_SCORE = 0.5  # §8.2 P without a trusted L/U band (or U == L); §8.4 Y without a reference
NEUTRAL_FIT_SCORE = 0.5  # §8.4 F with unknown data
# R = 0.60*(adjusted_rating/5) + 0.25*C + 0.15*O (§8.2); priors live in app.contracts.trust.
RELIABILITY_WEIGHTS: dict[str, float] = {"rating": 0.60, "completion": 0.25, "on_time": 0.15}
EXPERIENCE_LOG_BASE_TRIPS = 100  # E = min(1, ln(1 + completed_trips) / ln(101))

SAVED_SEARCH_MAX_PER_USER = 10  # (pilot) -> 409 SAVED_SEARCH_LIMIT_REACHED details {limit}
SAVED_SEARCH_MAX_WINDOW_DAYS = 60  # (pilot) time_window_end - time_window_start
# FeedPageMeta.match_scope: production matches confirmed corridor stops only (Q46, no detour measurement).
MATCH_SCOPE_CONFIRMED_STOPS = "confirmed_stops"
FEED_DEFAULT_LIMIT = 20
FEED_MAX_LIMIT = 50


def score_weights_are_normalized(weights: dict[str, float]) -> bool:
    return abs(sum(weights.values()) - 1.0) < 1e-9

