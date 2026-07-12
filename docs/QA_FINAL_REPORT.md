# Final QA Report

## Summary

Stage 20 final QA is complete. The automated backend regression suite passes with the new final MVP happy-path and consistency checks included.

## Test Summary

- Full test suite: passed
- Total tests: 260 passed
- Warnings: 180 FastAPI/Python deprecation warnings from `asyncio.iscoroutinefunction`
- Coverage command: unavailable because `pytest-cov` is not installed
- Ruff commands: unavailable because `ruff` is not installed

## Full Flow Status

The Stage 20 integration test covers the complete MVP path:

1. Client registers with OTP and receives tokens.
2. Driver registers with OTP and receives tokens.
3. Admin creates cities and route tariff.
4. Driver updates profile and submits all required documents.
5. Operator approval is rejected.
6. Admin approves driver.
7. Driver manually sets availability to true.
8. Driver creates a route from City A to City B.
9. Client uploads a cargo photo.
10. Client creates and publishes an order.
11. Matching creates one offer for the eligible route-matched driver.
12. Driver sees limited feed/detail before assignment.
13. Driver creates a bid and order moves to bidding.
14. Client selects the active bid.
15. Assigned driver sees full contact/address detail.
16. Driver marks picked_up, in_transit, and delivered.
17. Client confirms the delivered order.
18. Payment remains cash and payment_status becomes paid_manual.
19. Client rates the driver.
20. Database consistency is verified for order, bid, offer, rating, status history, audit logs, and notifications.

Expected lifecycle verified:

```text
draft -> published -> bidding -> accepted -> picked_up -> in_transit -> delivered -> confirmed
```

## Regression Status

Covered by the full suite:

- Auth and public role registration restrictions
- File upload validation
- Cities and route tariffs
- Driver profile, documents, verification, availability, and routes
- Client order creation, publishing, cancellation, confirmation, and rating
- Matching and order offers
- Driver feed, limited/full visibility, bids, bid updates, and rejects
- Select-driver transaction consistency
- Driver order status transitions
- Disputes
- Admin orders and manual intervention
- Admin driver verification
- Notifications
- Audit log access and filters
- Security and ownership hardening
- API docs and Postman collection checks

## Security And Permission Status

Verified:

- Anonymous users cannot access protected endpoints.
- Blocked and inactive users cannot act.
- Clients cannot access driver/admin endpoints.
- Drivers cannot access admin endpoints.
- Operators cannot approve drivers and cannot access audit logs.
- Admin and super_admin can access audit logs.
- Ownership and private contact visibility rules are covered by existing tests.

## Status Transition Status

Verified by integration and module tests:

- Valid normal transitions create status_history.
- Invalid driver skips are rejected.
- Client confirm is allowed only from delivered.
- Driver cancellation is allowed only before pickup.
- Admin/operator manual updates require reasons and write audit logs where implemented.

## Data Consistency Status

Verified after the full happy path:

- Order has one client and one assigned driver.
- accepted_bid_id points to the selected bid.
- final_price equals accepted bid price.
- Exactly one accepted bid exists for the order.
- Rating exists once per order.
- Status history is chronological by id and contains all expected statuses.
- Notifications belong to the relevant users.
- Critical audit actions exist.

## Removed Feature Scan

Automated model/OpenAPI checks confirm removed features are not active model columns or request fields:

```text
cargo_type, weight, size, capacity, departure_time, pickup_time, delivery_time,
pickup_proof, delivery_proof, receiver_confirmation_code, delivery_photo,
gps, tracking, online_payment, payme, click, escrow, p2p, chat
```

Source text scan found occurrences only in expected contexts:

- Documentation describing MVP exclusions
- Negative regression tests asserting fields do not exist
- Auth OTP flow naming, which is part of the existing login mechanism, not delivery proof
- File upload `size_bytes` metadata and size-limit validation
- Cash payment fields `payment_method` and `payment_status`

No active removed MVP business feature was found.

## OpenAPI And Documentation Check

Verified:

- `/openapi.json` loads in tests.
- README exists.
- `.env.example` exists.
- Postman collection and local environment exist.
- MVP restrictions, cash-only payment, lifecycle, driver visibility, and file upload types are documented.
- OpenAPI request schemas do not expose removed order/route/proof/payment fields.

## Manual QA Steps

1. Run migrations:

```bash
alembic upgrade head
```

2. Start backend:

```bash
uvicorn app.main:app --reload --port 8000
```

3. Open Swagger:

```text
http://127.0.0.1:8000/docs
```

4. Create staff users directly in the database, because public registration supports only client and driver.

5. Register client and driver through:

```text
POST /api/v1/auth/request-otp
POST /api/v1/auth/verify-otp
```

6. Admin creates City A, City B, and a route tariff.
7. Driver updates profile, submits required documents, and admin approves driver.
8. Driver sets availability true and creates route City A -> City B.
9. Client uploads cargo photo, creates draft order, and publishes it.
10. Driver sees the order in feed, sees limited detail, and creates a bid.
11. Client selects bid.
12. Driver sees full detail and marks picked_up, in_transit, delivered.
13. Client confirms and rates.
14. Admin checks order detail, status_history, bids, notifications, and audit logs.

Expected final state:

```text
orders.status = confirmed
orders.payment_method = cash
orders.payment_status = paid_manual
selected bid status = accepted
other bids status = closed
ratings has one row for the order
status_history has draft -> confirmed lifecycle
audit_logs contain critical actions
```

## Known Limitations

- SMS/FCM/external notification delivery is not implemented by MVP decision.
- Online payment, gateway, escrow, card, and P2P payment are not implemented by MVP decision.
- GPS/map tracking, proof uploads, QR/receiver confirmation code, capacity, cargo weight/size/type, and chat are not implemented by MVP decision.
- Rate limiting is documented as a production TODO.
- CORS origin restrictions should be configured for production.
- There is no dedicated client endpoint for listing bid details; clients can select a bid by id, while staff can inspect bids in admin order detail.

## Remaining TODOs

- Add production rate limiting for auth, file upload, bids, and disputes.
- Configure production CORS origins.
- Consider adding a client-owned bid listing endpoint after product review if mobile/frontend needs it.
- Add `pytest-cov` and `ruff` to the development toolchain if coverage and lint checks should be mandatory.

## Commands Run

```bash
.venv\Scripts\python.exe -m pytest tests/test_stage20_final_qa.py
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m pytest --cov=app
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
```

Results:

- Stage 20 tests: passed
- Full pytest: 260 passed
- Coverage: failed because `pytest-cov` is not installed
- Ruff: failed because `ruff` is not installed

## Release Readiness

Backend MVP is ready for frontend/mobile integration from the tested API-contract perspective, with the known limitations above. Product review is recommended before adding any feature beyond the approved MVP.
