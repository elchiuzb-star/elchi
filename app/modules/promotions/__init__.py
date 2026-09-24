"""Promotions & referral: campaigns, budget, immutable promo ledger, obligations, bonus lots, redemptions (ADR-0023).

Separate from the real-money wallet: nothing here posts to ``ledger_transactions`` or changes a driver's prepaid
balance. Pure money rules live in ``app.contracts.promo``.
"""
