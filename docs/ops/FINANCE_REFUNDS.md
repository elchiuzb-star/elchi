# Finance: refund on account deletion and staging wallet settings

Owner: A3 (wallet). Coordinated with A10a (docs/ops). Decisions 31 and BR #13 (wave 1.5).

## 1. Refund of a prepaid commission balance when a driver deletes the account

Account deletion (v1 `DELETE /api/v1/auth/me`, later v2 I4) is refused while
`wallet.blocking_state_for_user(...).blocks_deletion` is true: a non-zero posted balance,
active holds, pending top-ups or pending adjustment requests. The balance is never written off
silently and never zeroed by editing rows (the ledger is immutable).

Procedure:
1. **Wait for open money.** Active holds are resolved by their bookings (capture/release).
   Pending top-ups are approved or rejected (W6/W7). Pending adjustment requests are approved
   (W16) or rejected with a reason (W17).
2. **Pay out outside the app.** Finance transfers the remaining posted balance to the driver's
   verified bank account or pays it at the cash desk against a signed receipt. Keep the bank
   statement line or receipt as evidence.
3. **Post a debit adjustment** (W8, `finance.adjustment`):
   `direction=debit`, `amount_minor = posted_balance_minor`, `reason = "refund on account deletion"`,
   `evidence_file_ids = [bank statement / signed receipt]`. Above
   `TWO_PERSON_APPROVAL_THRESHOLD_MINOR` the request waits for a **different** staff member with
   `finance.adjustment_approve` (W16). The posting is Dr driver prepaid liability / Cr
   `manual_adjustments`; the accountant maps it to the bank/cash account in the ledger export.
4. **Verify** `GET /api/v2/wallet` for the driver (or reconciliation) shows posted 0, held 0.
5. The driver retries deletion; it now passes the wallet check. Ledger history stays (audit).

Never: delete ledger rows, set `posted_balance_minor` directly (the DB rejects both), or treat a
legacy `orders.system_fee` as a debt (§18.2).

## 2. Staging: `wallet_required=false` and `test_overdraft_allowed`

Only in non-production databases (the `platform_environment` marker is not `production`):

- `wallet_required=false` skips **only** the balance sufficiency check. The commission is still
  computed from the real policy, snapshotted and held (Q1).
- Because the hold still increases `held_minor`, a wallet without enough posted balance violates
  `posted - held >= 0` unless the seed sets `test_overdraft_allowed=true` for that wallet
  (`wallet.set_test_overdraft_allowed`). Without it the hold is refused with
  `INSUFFICIENT_COMMISSION_BALANCE` (`details.reason = overdraft_not_allowed`).
- Such wallets make the production marker impossible to set (trigger) and make
  `assert_production_invariants` fail if the database is ever treated as production. Remove the
  flag (`test_overdraft_allowed=false`) and settle the negative available amount before a staging
  database is promoted or restored into production.
