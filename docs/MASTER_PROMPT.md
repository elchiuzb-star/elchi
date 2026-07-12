You are working on the backend for an Intercity Parcel Delivery Marketplace MVP.

Do not build everything at once. Work strictly stage by stage.

First inspect the repository structure, detect the backend stack, and summarize what exists. If there is no backend yet, create a clean FastAPI backend with PostgreSQL, SQLAlchemy, Alembic, Pydantic, JWT auth, and modular app structure.

Important MVP restrictions:
- No time matching.
- No driver departure time.
- No capacity check.
- No driver capacity.
- No cargo type.
- No weight.
- No size/volume.
- No OTP/QR proof.
- No pickup proof.
- No delivery proof.
- No online payment.
- No P2P payment.
- No real-time GPS tracking.
- No chat.

Main MVP flow:
Client creates order → order is published → matched approved drivers see it by route → drivers bid → client selects one driver → driver updates statuses → client/operator confirms → payment is cash only.

Use these main modules:
- auth
- users
- cities
- route_tariffs
- driver_profiles
- driver_documents
- driver_routes
- orders
- bids
- order_offers
- status_history
- disputes
- ratings
- notifications
- audit_logs
- admin

Rules:
- Keep code modular.
- Add migrations for every DB change.
- Add automated tests for every stage.
- Do not add features not listed in the MVP.
- Do not make destructive changes without explaining them first.
- After each stage, stop and report:
  1. What was implemented
  2. Files changed
  3. How to run migrations
  4. How to run tests
  5. Manual API test examples
  6. Known limitations