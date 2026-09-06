# Elchi Backend

Backend API for the Elchi Intercity Parcel Delivery Marketplace MVP.

Two people work in this repo at once — read [CONTRIBUTING.md](CONTRIBUTING.md)
before your first commit. It covers who owns which folder, branch naming, and the
API contract.

## Frontend

The project ships two React + Vite + TypeScript frontends:

- `frontend/` — `elchi-frontend`, the main web app (client, driver, and admin/staff UI).
- `mobile-app/` — `elchi-mobile-app`, the mobile-optimized client/driver UI.

Web frontend:

```bash
cd frontend
npm install
npm run dev
```

Mobile app:

```bash
cd mobile-app
npm install
npm run dev
```

Default frontend URL:

```text
http://localhost:5173/
```

Admin/staff URL:

```text
http://localhost:5173/admin
```

Default backend API URL used by the frontends:

```text
http://127.0.0.1:8000/api/v1
```

Frontend environment variables (set in `frontend/.env.local` and `mobile-app/.env.local`):

```text
VITE_API_BASE_URL         Backend API base URL
VITE_GOOGLE_MAPS_API_KEY  Google Maps JS API key for the map picker
VITE_GOOGLE_MAPS_MAP_ID   Google Maps vector map style id
VITE_SUPPORT_PHONE        Support phone shown in the UI (web app)
```

Clients create parcel orders between cities, route-matched approved drivers bid, clients select one driver, assigned drivers update delivery status, and clients confirm delivery. MVP payment is cash only.

## MVP Scope

Approved MVP flow:

```text
Client creates order
Client publishes order
Route-matched approved drivers see order
Drivers submit bids
Client selects one driver
Order becomes accepted
Assigned driver updates accepted -> picked_up -> in_transit -> delivered
Client confirms delivered order
Payment is cash only
Client can rate driver after confirmed
Operator/admin can intervene with audit logs
```

## Tech Stack

Backend:

- Python 3.11+
- FastAPI
- SQLAlchemy
- Alembic
- PostgreSQL
- Pytest
- Google Maps Geocoding (address ↔ coordinates, optional)

Frontend:

- React + TypeScript
- Vite
- Google Maps JS API (location picker)

## API Documentation

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

OpenAPI JSON:

```text
http://127.0.0.1:8000/openapi.json
```

API title:

```text
Intercity Parcel Delivery Marketplace API
```

API version:

```text
1.0.0-mvp
```

## Authentication

Public authentication flow:

```text
1. POST /api/v1/auth/request-otp with phone and role
2. POST /api/v1/auth/verify-otp with phone, role, and otp
3. Store access_token and refresh_token
4. Send Authorization: Bearer ACCESS_TOKEN on protected endpoints
5. POST /api/v1/auth/refresh when the access token expires
```

Public registration is allowed only for:

```text
client
driver
```

These roles cannot register publicly:

```text
operator
admin
super_admin
```

Inactive, blocked, and deleted users cannot perform protected actions.

## Roles

```text
client       Own orders, disputes, ratings, notifications, file uploads
driver       Own profile/documents/routes, matched order feed, own bids, assigned order status
operator     Admin order/dispute views and allowed manual order/dispute actions
admin        Operator permissions plus driver verification, cities, tariffs, audit logs
super_admin  Admin permissions
```

## Standard Responses

Success:

```json
{
  "success": true,
  "data": {},
  "message": "OK"
}
```

Error:

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid input",
    "details": {}
  }
}
```

Common error codes:

```text
UNAUTHORIZED
FORBIDDEN
VALIDATION_ERROR
NOT_FOUND
ORDER_INVALID_STATUS
DRIVER_NOT_APPROVED
DRIVER_NOT_AVAILABLE
DRIVER_BLOCKED
ROUTE_NOT_MATCHED
BID_NOT_ACTIVE
ALREADY_EXISTS
FILE_TOO_LARGE
CITY_INACTIVE
ROUTE_TARIFF_NOT_FOUND
SERVER_ERROR
```

## Access Matrix

| Module | Client | Driver | Operator | Admin | Super Admin |
|---|---:|---:|---:|---:|---:|
| Own orders | Yes | No | View all via admin | View all via admin | View all via admin |
| Driver feed | No | Yes | No | No | No |
| Bids | View own order bids | Own bids | View via admin orders | View via admin orders | View via admin orders |
| Driver profile/routes | No | Own only | View drivers | View/manage verification | View/manage verification |
| Disputes | Own related | Assigned related | View/update | View/update | View/update |
| Notifications | Own only | Own only | Own only | Own only | Own only |
| Admin orders | No | No | Yes | Yes | Yes |
| Driver verification | No | No | View only | Manage | Manage |
| Audit logs | No | No | No | Yes | Yes |

## Order Lifecycle

Normal lifecycle:

```text
draft -> published -> bidding -> accepted -> picked_up -> in_transit -> delivered -> confirmed
```

Exception statuses:

```text
cancelled
disputed
```

Who changes status:

```text
draft -> published: client
published -> bidding: first driver bid
bidding -> accepted: client selects driver
accepted -> picked_up: assigned driver
picked_up -> in_transit: assigned driver
in_transit -> delivered: assigned driver
delivered -> confirmed: client
allowed statuses -> cancelled: client, assigned driver, operator/admin according to rules
allowed statuses -> disputed: client, assigned driver, operator/admin according to rules
```

Operator/admin manual order changes require a reason, write status history, and write audit logs.

## Driver Visibility

Before selected, a matched driver sees only limited order data:

```text
from city
to city
pickup area
dropoff area
cargo photo
suggested price
own bid
status
```

After selected, the assigned driver sees:

```text
full pickup address
full dropoff address
sender phone
receiver phone
comment
final price
cash payment info
```

Other drivers never see private contact data.

## Cash Payment

MVP supports cash only.

```text
payment_method = cash
payment_status starts as unpaid
confirmation can set payment_status = paid_manual
```

There is no online payment, gateway, escrow, or card token flow.

## File Upload Rules

Allowed upload types:

```text
cargo_photo
passport
selfie
license
car_document
car_photo
```

Not allowed:

```text
pickup_proof
delivery_proof
tracking_photo
chat_media
audio
video
```

Size limits:

```text
cargo_photo: 5 MB
selfie: 5 MB
car_photo: 5 MB
passport: 10 MB
license: 10 MB
car_document: 10 MB
```

## Environment Variables

The project reads variables with the `ELCHI_` prefix. See `.env.example`.

```text
ELCHI_APP_NAME=Elchi API
ELCHI_ENVIRONMENT=local
ELCHI_DEBUG=true
ELCHI_API_V1_PREFIX=/api/v1
ELCHI_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/elchi
ELCHI_SECRET_KEY=change-this-secret-key
ELCHI_ACCESS_TOKEN_EXPIRE_MINUTES=60
ELCHI_REFRESH_TOKEN_EXPIRE_DAYS=30
ELCHI_JWT_ALGORITHM=HS256
ELCHI_MOCK_OTP_CODE=00000
ELCHI_OTP_LENGTH=5
ELCHI_OTP_EXPIRE_SECONDS=120
ELCHI_OTP_MAX_SEND_REQUESTS=5
ELCHI_OTP_SEND_WINDOW_MINUTES=30
ELCHI_OTP_RESEND_COOLDOWN_SECONDS=60
ELCHI_OTP_MAX_VERIFY_ATTEMPTS=5
ELCHI_DEV_MOCK_OTP=12345
ELCHI_SUPER_ADMIN_PHONE=+998900000001
ELCHI_UPLOAD_DIR=storage/uploads
ELCHI_MAX_IMAGE_UPLOAD_MB=5
ELCHI_MAX_DOCUMENT_UPLOAD_MB=10
ELCHI_PUBLIC_UPLOAD_BASE_URL=/uploads
ELCHI_GOOGLE_MAPS_API_KEY=
ELCHI_GOOGLE_MAPS_COUNTRY=uz
```

`ELCHI_GOOGLE_MAPS_API_KEY` is optional. When it is empty, the geo endpoints fall back to the nearest known district instead of calling Google Maps. `ELCHI_GOOGLE_MAPS_COUNTRY` biases geocoding results to the given country (default `uz`).

## Requirements

- Python 3.11+
- PostgreSQL

## Local Setup

Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Update `.env` with your local PostgreSQL connection string. PostgreSQL must exist before running migrations.

## Run API

```bash
uvicorn app.main:app --reload --port 8000
```

The API will be available at:

```text
http://127.0.0.1:8000
```

Swagger docs:

```text
http://127.0.0.1:8000/docs
```

## Run Migrations

```bash
alembic upgrade head
```

Create a migration during development:

```bash
alembic revision --autogenerate -m "message"
```

Downgrade one migration:

```bash
alembic downgrade -1
```

## Run Tests

```bash
pytest
```

Run one test file:

```bash
pytest tests/test_auth.py
```

Test coverage includes auth, file upload, cities/tariffs, driver profile/routes, client orders, matching, driver feed/bids, select driver, driver order status, confirm/rating, disputes, admin orders, admin drivers, notifications, audit logs, security permissions, and documentation checks.

## Seed And Admin Setup

Seed and setup scripts live under `scripts/`:

```text
scripts/create_super_admin.py          Create the initial super_admin user
scripts/seed_cities.py                 Seed the standard Uzbekistan cities
scripts/seed_districts.py              Seed districts used by geo/location lookup
scripts/seed_admin_required_data.py    Minimum data an admin needs (cities, tariffs)
scripts/seed_bidding_demo.py           Demo data for the bidding flow
scripts/seed_demo_marketplace_data.py  Broader demo marketplace dataset
```

Run a script after migrations, for example:

```bash
python scripts/seed_cities.py
python scripts/seed_districts.py
```

You can also create initial data through the API, direct SQL, or a short local script using the SQLAlchemy models.

Recommended cities for seed:

```text
Toshkent
Samarqand
Buxoro
Andijon
Namangan
Farg'ona
Qo'qon
Qarshi
Navoiy
Jizzax
Termiz
Urganch
Nukus
Guliston
```

Create at least:

```text
active cities
active route tariffs
operator/admin/super_admin users
```

Public registration only creates `client` and `driver` users. Existing staff users can log in through OTP, but public OTP cannot create `operator`, `admin`, or `super_admin`.

Create the initial super admin after migrations:

```bash
python scripts/create_super_admin.py
```

Then log in as `super_admin` and create admin/operator users:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/admin/users" \
  -H "Authorization: Bearer SUPER_ADMIN_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"phone":"+998900000002","role":"admin","full_name":"Admin User"}'
```

Example SQL for a local admin:

```sql
INSERT INTO users (phone, role, status, is_phone_verified)
VALUES ('+998900000001', 'super_admin', 'active', true);
```

## Postman Collection

Collections and environments (under `docs/postman/`):

```text
intercity_mvp_api.postman_collection.json            Full API collection
intercity_mvp_local.postman_environment.json         Local environment
elchi_client_side_automated.postman_collection.json  Automated client-side flow
elchi_client_side_automated.postman_environment.json
elchi_driver_side_automated.postman_collection.json  Automated driver-side flow
elchi_driver_side_automated.postman_environment.json
elchi_client_user_to_order.postman_collection.json   Client register -> order flow
elchi_client_user_to_order.postman_environment.json
```

Import a collection with its matching environment into Postman, set access tokens after login, then run requests folder by folder. The automated collections chain requests and set variables from responses. The collections use variables such as:

```text
{{base_url}}
{{client_access_token}}
{{driver_access_token}}
{{operator_access_token}}
{{admin_access_token}}
{{order_id}}
{{bid_id}}
```

## Manual Health Check

```bash
curl http://127.0.0.1:8000/api/v1/health
```

Expected response:

```json
{
  "success": true,
  "message": "OK"
}
```

## Manual File Upload

Create or reuse an access token from the auth API, then upload a file:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/files/upload" \
  -H "Authorization: Bearer ACCESS_TOKEN" \
  -F "type=cargo_photo" \
  -F "file=@test.jpg"
```

Local development uploads are stored under `storage/uploads` and exposed as `/uploads/...`.

## Manual Cities And Tariffs

Create a city with an admin token:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/admin/cities" \
  -H "Authorization: Bearer ADMIN_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name_uz":"Toshkent","name_ru":"Tashkent","region":"Toshkent"}'
```

List public active cities:

```bash
curl "http://127.0.0.1:8000/api/v1/cities?search=Toshkent"
```

Create a route tariff with an admin token:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/admin/route-tariffs" \
  -H "Authorization: Bearer ADMIN_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"from_city_id":1,"to_city_id":2,"suggested_price":60000,"min_price":50000,"max_price":80000}'
```

Get suggested price with any authenticated token:

```bash
curl "http://127.0.0.1:8000/api/v1/route-tariffs/suggested-price?from_city_id=1&to_city_id=2" \
  -H "Authorization: Bearer ACCESS_TOKEN"
```

## Geo And Location

The frontend map picker uses geo endpoints to turn a map marker or typed address into pickup/dropoff location data. These support address selection only; there is no real-time GPS trip tracking.

Reverse-geocode a map marker to an address (falls back to the nearest district when Google Maps is not configured):

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/geo/reverse-geocode" \
  -H "Content-Type: application/json" \
  -d '{"lat":41.311081,"lng":69.240562,"language":"uz"}'
```

Geocode a typed address to coordinates:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/geo/geocode" \
  -H "Content-Type: application/json" \
  -d '{"address":"Toshkent, Chilonzor","language":"uz"}'
```

Validate that a marker falls inside a selected region/district:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/geo/validate-location" \
  -H "Content-Type: application/json" \
  -d '{"lat":41.311081,"lng":69.240562,"region_id":1,"district_id":10}'
```

Each response reports a `provider` field: `google` when Google Maps answered, or `local` when the nearest-district fallback was used.

## Manual Driver Profile And Routes

Get current driver profile:

```bash
curl "http://127.0.0.1:8000/api/v1/driver/profile" \
  -H "Authorization: Bearer DRIVER_ACCESS_TOKEN"
```

Update driver profile:

```bash
curl -X PATCH "http://127.0.0.1:8000/api/v1/driver/profile" \
  -H "Authorization: Bearer DRIVER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"full_name":"Ali Valiyev","car_model":"Cobalt","plate_number":"01A123BC","car_color":"Oq"}'
```

Submit a previously uploaded document URL:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/driver/documents" \
  -H "Authorization: Bearer DRIVER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"document_type":"passport","file_url":"/uploads/passport/2026/06/example.jpg"}'
```

Set availability:

```bash
curl -X PATCH "http://127.0.0.1:8000/api/v1/driver/availability" \
  -H "Authorization: Bearer DRIVER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"is_available":true}'
```

Create a driver route:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/driver/routes" \
  -H "Authorization: Bearer DRIVER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"from_city_id":1,"to_city_id":2}'
```

## Manual Client Orders

Create an order draft:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/client/orders" \
  -H "Authorization: Bearer CLIENT_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"from_city_id":1,"to_city_id":2,"pickup_address":"Toshkent, Chilonzor","dropoff_address":"Samarqand center","sender_phone":"+998901234567","receiver_phone":"+998911112233","cargo_type":"parcel","cargo_photo_url":"/uploads/cargo_photo/2026/06/example.jpg","comment":"Ehtiyot qilib olib boring"}'
```

Publish a draft order:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/client/orders/ORDER_ID/publish" \
  -H "Authorization: Bearer CLIENT_ACCESS_TOKEN"
```

Publishing runs route-based matching and creates `order_offers` for approved, available drivers whose available route exactly matches the order route.

Verify offers in PostgreSQL:

```sql
SELECT *
FROM order_offers
WHERE order_id = ORDER_ID;
```

List own orders:

```bash
curl "http://127.0.0.1:8000/api/v1/client/orders?page=1&limit=20" \
  -H "Authorization: Bearer CLIENT_ACCESS_TOKEN"
```

Cancel an allowed order:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/client/orders/ORDER_ID/cancel" \
  -H "Authorization: Bearer CLIENT_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason":"Client fikridan qaytdi"}'
```

## Manual Driver Feed And Bids

Get matched published or bidding orders for an approved, available driver:

```bash
curl "http://127.0.0.1:8000/api/v1/driver/orders/feed?page=1&limit=20" \
  -H "Authorization: Bearer DRIVER_ACCESS_TOKEN"
```

Get limited order detail before assignment:

```bash
curl "http://127.0.0.1:8000/api/v1/driver/orders/ORDER_ID" \
  -H "Authorization: Bearer DRIVER_ACCESS_TOKEN"
```

Create a bid for a matched order:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/driver/orders/ORDER_ID/bids" \
  -H "Authorization: Bearer DRIVER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"price":55000}'
```

Update your own active bid. Stage 9 keeps `bid.status` as `active` and uses `updated_at` to show the price changed:

```bash
curl -X PATCH "http://127.0.0.1:8000/api/v1/driver/bids/BID_ID" \
  -H "Authorization: Bearer DRIVER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"price":60000}'
```

Reject a visible matched order:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/driver/orders/ORDER_ID/reject" \
  -H "Authorization: Bearer DRIVER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason":"Narx mos emas"}'
```

## Manual Select Driver

Select one active bid for your own bidding order:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/client/orders/ORDER_ID/select-driver" \
  -H "Authorization: Bearer CLIENT_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"bid_id":BID_ID}'
```

After selection:

```sql
SELECT status, assigned_driver_id, accepted_bid_id, final_price, accepted_at
FROM orders
WHERE id = ORDER_ID;

SELECT id, status
FROM bids
WHERE order_id = ORDER_ID;
```

Expected result: the order is `accepted`, the selected bid is `accepted`, other bids for that order are `closed`, and payment remains `cash` / `unpaid`.

## Manual Driver Order Status

Assigned drivers can move an accepted order through the delivery lifecycle:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/driver/orders/ORDER_ID/picked-up" \
  -H "Authorization: Bearer DRIVER_ACCESS_TOKEN"

curl -X POST "http://127.0.0.1:8000/api/v1/driver/orders/ORDER_ID/in-transit" \
  -H "Authorization: Bearer DRIVER_ACCESS_TOKEN"

curl -X POST "http://127.0.0.1:8000/api/v1/driver/orders/ORDER_ID/delivered" \
  -H "Authorization: Bearer DRIVER_ACCESS_TOKEN"
```

Assigned drivers can cancel only before pickup:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/driver/orders/ORDER_ID/cancel" \
  -H "Authorization: Bearer DRIVER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason":"Mashina buzilib qoldi"}'
```

Verify status history:

```sql
SELECT old_status, new_status, changed_by_role, reason
FROM status_history
WHERE order_id = ORDER_ID
ORDER BY created_at ASC;
```

## Manual Client Confirm And Rating

Confirm a delivered order:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/client/orders/ORDER_ID/confirm" \
  -H "Authorization: Bearer CLIENT_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Create one rating after the order is confirmed:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/client/orders/ORDER_ID/rating" \
  -H "Authorization: Bearer CLIENT_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"rating":5,"comment":"Yaxshi yetkazib berdi"}'
```

Verify confirmation and rating:

```sql
SELECT status, payment_method, payment_status, confirmed_at
FROM orders
WHERE id = ORDER_ID;

SELECT order_id, client_id, driver_id, rating, comment
FROM ratings
WHERE order_id = ORDER_ID;
```

## Manual Disputes

Open a dispute:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/orders/ORDER_ID/disputes" \
  -H "Authorization: Bearer ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason":"delayed","comment":"Haydovchi kechikyapti"}'
```

List disputes visible to the current user:

```bash
curl "http://127.0.0.1:8000/api/v1/disputes?status=open" \
  -H "Authorization: Bearer ACCESS_TOKEN"
```

Operator/admin dispute review:

```bash
curl "http://127.0.0.1:8000/api/v1/admin/disputes?status=open" \
  -H "Authorization: Bearer OPERATOR_ACCESS_TOKEN"

curl "http://127.0.0.1:8000/api/v1/admin/disputes/DISPUTE_ID" \
  -H "Authorization: Bearer OPERATOR_ACCESS_TOKEN"

curl -X PATCH "http://127.0.0.1:8000/api/v1/admin/disputes/DISPUTE_ID" \
  -H "Authorization: Bearer OPERATOR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"resolved","resolution":"Muammo hal qilindi"}'
```

## Manual Admin Orders

List and inspect orders:

```bash
curl "http://127.0.0.1:8000/api/v1/admin/orders?status=accepted&page=1&limit=20" \
  -H "Authorization: Bearer OPERATOR_ACCESS_TOKEN"

curl "http://127.0.0.1:8000/api/v1/admin/orders/ORDER_ID" \
  -H "Authorization: Bearer OPERATOR_ACCESS_TOKEN"
```

Manually update status:

```bash
curl -X PATCH "http://127.0.0.1:8000/api/v1/admin/orders/ORDER_ID/status" \
  -H "Authorization: Bearer OPERATOR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"in_transit","reason":"Driver called operator and confirmed parcel is on the way"}'
```

Manually assign a driver:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/admin/orders/ORDER_ID/assign-driver" \
  -H "Authorization: Bearer OPERATOR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"driver_id":DRIVER_ID,"final_price":55000,"reason":"Client requested operator assistance"}'
```

Cancel an order:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/admin/orders/ORDER_ID/cancel" \
  -H "Authorization: Bearer OPERATOR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason":"Client unreachable"}'
```

## Manual Admin Driver Verification

List and inspect drivers as operator/admin/super_admin:

```bash
curl "http://127.0.0.1:8000/api/v1/admin/drivers?verification_status=pending&page=1&limit=20" \
  -H "Authorization: Bearer OPERATOR_ACCESS_TOKEN"

curl "http://127.0.0.1:8000/api/v1/admin/drivers/DRIVER_ID" \
  -H "Authorization: Bearer OPERATOR_ACCESS_TOKEN"
```

Approve a driver as admin/super_admin:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/admin/drivers/DRIVER_ID/approve" \
  -H "Authorization: Bearer ADMIN_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"comment":"Documents checked"}'
```

Reject or block a driver with a required reason:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/admin/drivers/DRIVER_ID/reject" \
  -H "Authorization: Bearer ADMIN_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason":"License document is not clear"}'

curl -X POST "http://127.0.0.1:8000/api/v1/admin/drivers/DRIVER_ID/block" \
  -H "Authorization: Bearer ADMIN_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason":"Fraud suspicion"}'
```

Verify audit and state:

```sql
SELECT verification_status, is_available
FROM driver_profiles
WHERE id = DRIVER_ID;

SELECT status
FROM users
WHERE id = DRIVER_USER_ID;

SELECT action, details
FROM audit_logs
WHERE entity_id = DRIVER_ID
ORDER BY created_at DESC;
```

## Manual Notifications

List your own notifications:

```bash
curl "http://127.0.0.1:8000/api/v1/notifications?page=1&limit=20" \
  -H "Authorization: Bearer ACCESS_TOKEN"
```

Filter unread notifications or a specific type:

```bash
curl "http://127.0.0.1:8000/api/v1/notifications?is_read=false&type=new_bid" \
  -H "Authorization: Bearer ACCESS_TOKEN"
```

Mark one notification as read:

```bash
curl -X PATCH "http://127.0.0.1:8000/api/v1/notifications/NOTIFICATION_ID/read" \
  -H "Authorization: Bearer ACCESS_TOKEN"
```

Mark all own notifications as read:

```bash
curl -X PATCH "http://127.0.0.1:8000/api/v1/notifications/read-all" \
  -H "Authorization: Bearer ACCESS_TOKEN"
```

Verify notification storage:

```sql
SELECT user_id, type, title, message, order_id, channel, is_read, sent_at, created_at
FROM notifications
WHERE id = NOTIFICATION_ID;
```

## Manual Audit Logs

List audit logs as admin or super admin:

```bash
curl "http://127.0.0.1:8000/api/v1/admin/audit-logs?page=1&limit=20" \
  -H "Authorization: Bearer ADMIN_ACCESS_TOKEN"
```

Filter by entity, actor role, or action:

```bash
curl "http://127.0.0.1:8000/api/v1/admin/audit-logs?entity_type=orders&entity_id=ORDER_ID" \
  -H "Authorization: Bearer ADMIN_ACCESS_TOKEN"

curl "http://127.0.0.1:8000/api/v1/admin/audit-logs?actor_role=operator" \
  -H "Authorization: Bearer ADMIN_ACCESS_TOKEN"

curl "http://127.0.0.1:8000/api/v1/admin/audit-logs?action=admin_order_cancelled" \
  -H "Authorization: Bearer ADMIN_ACCESS_TOKEN"
```

Get one audit log:

```bash
curl "http://127.0.0.1:8000/api/v1/admin/audit-logs/AUDIT_LOG_ID" \
  -H "Authorization: Bearer ADMIN_ACCESS_TOKEN"
```

Audit log API is read-only. There are no POST, PATCH, or DELETE audit log endpoints.

## Manual Security Checks

Anonymous protected endpoint:

```bash
curl "http://127.0.0.1:8000/api/v1/client/orders"
```

Client trying an admin endpoint:

```bash
curl "http://127.0.0.1:8000/api/v1/admin/orders" \
  -H "Authorization: Bearer CLIENT_ACCESS_TOKEN"
```

Driver trying to update another driver's bid:

```bash
curl -X PATCH "http://127.0.0.1:8000/api/v1/driver/bids/OTHER_DRIVER_BID_ID" \
  -H "Authorization: Bearer DRIVER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"price":60000}'
```

Driver detail before assignment must not include full addresses or contact phones:

```bash
curl "http://127.0.0.1:8000/api/v1/driver/orders/ORDER_ID" \
  -H "Authorization: Bearer DRIVER_ACCESS_TOKEN"
```

Security hardening notes:

```text
Rate limiting is a future production TODO for auth, file upload, bids, and disputes.
CORS should be restricted to configured frontend origins before production deployment.
Security headers are enabled: X-Content-Type-Options, X-Frame-Options, and Referrer-Policy.
```

## Error Examples

Unauthorized:

```json
{
  "success": false,
  "error": {
    "code": "UNAUTHORIZED",
    "message": "Authentication required"
  }
}
```

Forbidden:

```json
{
  "success": false,
  "error": {
    "code": "FORBIDDEN",
    "message": "User account is not active"
  }
}
```

Invalid status:

```json
{
  "success": false,
  "error": {
    "code": "ORDER_INVALID_STATUS",
    "message": "Only bidding orders can accept a driver"
  }
}
```

Driver not approved:

```json
{
  "success": false,
  "error": {
    "code": "DRIVER_NOT_APPROVED",
    "message": "Driver must be approved"
  }
}
```

Route mismatch:

```json
{
  "success": false,
  "error": {
    "code": "ROUTE_NOT_MATCHED",
    "message": "Order does not match driver's route"
  }
}
```

Already exists:

```json
{
  "success": false,
  "error": {
    "code": "ALREADY_EXISTS",
    "message": "Driver already has a bid for this order"
  }
}
```

## Troubleshooting

- `alembic upgrade head` fails: confirm PostgreSQL is running and `ELCHI_DATABASE_URL` points to an existing database.
- Protected endpoint returns `UNAUTHORIZED`: use an access token, not a refresh token.
- Protected endpoint returns `FORBIDDEN`: confirm the user's role and that `users.status = active`.
- Driver feed is empty: driver must be approved, available, and have an available route matching order cities.
- Upload fails: confirm the file type, extension, MIME type, and size limit.
- Postman request fails with missing variables: select the local environment and fill token/id variables.

## Developer Notes

- Do not add removed MVP features without product approval.
- Keep route matching simple: `from_city_id` + `to_city_id`.
- Payment is cash only.
- Driver route has no `departure_time` and no `capacity`.
- Order has no `weight` or `size` (parcel `cargo_type` is supported: document, parcel, food, fragile, electronics, clothes, other).
- Proof flow is intentionally removed from MVP.
- Geo endpoints are for pickup/dropoff address selection only, not live trip tracking. Google Maps is optional; without a key they fall back to nearest-district lookup.
- Driver pre-selection order detail must not expose full addresses or phone numbers.
- Audit log output redacts sensitive fields.

## MVP Restrictions

Do not add:

```text
online payment
P2P payment
Payme
Click
escrow
payment gateway
OTP
QR
pickup proof
delivery proof
receiver confirmation code
delivery photo
real-time GPS tracking
maps route tracking
distance-based automatic pricing
driver departure time
trip departure time
capacity check
driver capacity
free space
weight limit
cargo weight
cargo size
chat
```
