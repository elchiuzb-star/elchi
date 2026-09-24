"""Referral stage 6: a deterministic scenario simulator for the approved referral mechanism (ADR-0023 §20).

Pure Python - no database, no network, no settings, no clock: a scenario file and a seed fully determine the result.
Every money rule is the production contract (``app.contracts.promo``): quotes, the one-campaign-per-instrument choice,
combinations, rounding, lot buckets, the budget, fair restoration, qualification and milestones. The simulator adds
only *behaviour assumptions* (arrivals, repeat orders, cancels, disputes, delays), and every such assumption is a
labelled input. Results are estimates under those inputs - never proof that users will grow or that the platform
cannot lose money.
"""
