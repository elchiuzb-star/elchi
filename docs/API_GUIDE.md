# Elchi MVP API Guide

This guide summarizes how frontend, mobile, QA, and backend developers should use the MVP API.

## Base URLs

```text
Local API: http://127.0.0.1:8000
Swagger UI: http://127.0.0.1:8000/docs
OpenAPI JSON: http://127.0.0.1:8000/openapi.json
API prefix: /api/v1
```

## Authentication

1. `POST /api/v1/auth/request-otp` with `phone` and `role`.
2. `POST /api/v1/auth/verify-otp` with `phone`, `role`, and `otp`.
3. Store `access_token` and `refresh_token`.
4. Send `Authorization: Bearer ACCESS_TOKEN` for protected endpoints.
5. Use `POST /api/v1/auth/refresh` with a refresh token.

Public registration supports only `client` and `driver`. Existing staff users can log in with OTP, but staff users must be created by `super_admin` or by the initial local seed/manual database process.

Development OTP is 5 digits:

```text
12345
```

Create the first super admin locally:

```bash
python scripts/create_super_admin.py
```

Then create admin/operator users:

```text
POST /api/v1/admin/users
```

## Roles

| Role | Access |
|---|---|
| client | Own orders, selection, confirmation, rating, disputes, notifications |
| driver | Own profile, documents, routes, matched feed, own bids, assigned order status |
| operator | Admin order/dispute review and allowed manual order/dispute actions |
| admin | Operator access plus cities, tariffs, driver verification, audit logs |
| super_admin | Admin access |

Inactive, blocked, and deleted users cannot use protected endpoints.

## Core MVP Flow

```text
client creates draft order
client publishes order
system matches approved available drivers by exact route
drivers bid
client selects one bid
order becomes accepted
assigned driver marks picked_up, in_transit, delivered
client confirms
client rates driver
```

Payment is cash only.

## Driver Visibility

Before selection, a matched driver receives limited order detail only:

```text
from city
to city
pickup area
dropoff area
cargo photo
suggested price
own bid
status
created_at
```

Only the assigned driver receives full pickup/dropoff addresses and sender/receiver phone numbers.

## Important Endpoints

| Module | Endpoint |
|---|---|
| Health | `GET /api/v1/health` |
| Auth | `POST /api/v1/auth/request-otp`, `POST /api/v1/auth/verify-otp`, `POST /api/v1/auth/refresh` |
| Files | `POST /api/v1/files/upload` |
| Cities | `GET /api/v1/cities` |
| Tariffs | `GET /api/v1/route-tariffs/suggested-price` |
| Client orders | `POST /api/v1/client/orders`, `POST /api/v1/client/orders/{id}/publish` |
| Select driver | `POST /api/v1/client/orders/{id}/select-driver` |
| Driver feed | `GET /api/v1/driver/orders/feed` |
| Driver bids | `POST /api/v1/driver/orders/{id}/bids`, `PATCH /api/v1/driver/bids/{id}` |
| Driver status | `POST /api/v1/driver/orders/{id}/picked-up`, `/in-transit`, `/delivered` |
| Confirm/rating | `POST /api/v1/client/orders/{id}/confirm`, `/rating` |
| Disputes | `POST /api/v1/orders/{id}/disputes`, `GET /api/v1/disputes` |
| Notifications | `GET /api/v1/notifications`, `PATCH /api/v1/notifications/{id}/read` |
| Admin orders | `GET /api/v1/admin/orders` |
| Admin drivers | `GET /api/v1/admin/drivers`, `POST /api/v1/admin/drivers/{id}/approve` |
| Audit logs | `GET /api/v1/admin/audit-logs` |

### Driver block and stage-2 obligations (Q15, additive, 15.09.2026)

`POST /api/v1/admin/drivers/{id}/block` accepts `{"reason": "...", "emergency": false}`. The response shape is unchanged
(`{success, data, message}`); `data` gains `block_type` (`new_business_only` | `full`), `v2_eligibility_blocked`,
`v2_active_trip_count` and `v2_active_booking_count`.

- Driver with active v2 trips or bookings: by default only new business is blocked (v2 eligibility block); the
  account, active trips, tracking, proofs and support keep working (`block_type = new_business_only`).
- `emergency: true` fully suspends the account (`block_type = full`) and is allowed only for `super_admin`; other
  roles get `403 FORBIDDEN`.
- Driver without v2 business: the previous full block behaviour is unchanged.

## Cities And Tariffs

Public city lists return active cities only by default:

```text
GET /api/v1/cities?page=1&limit=20&search=tosh
```

List responses use:

```json
{"success": true, "data": {"items": [], "pagination": {"page": 1, "limit": 20, "total": 0, "total_pages": 0}}, "message": "OK"}
```

Admin and operator users may read `GET /api/v1/admin/cities` and `GET /api/v1/admin/route-tariffs`. Only admin and super admin users may create or patch cities and tariffs. City names are trimmed, repeated whitespace is collapsed, and `name_uz` is unique case-insensitively.

Route tariffs are direction-based. A tariff from Toshkent to Samarqand does not create the reverse route. Prices are integer UZS values, and suggested-price responses include `currency: "UZS"`. Client order creation copies the currently active route tariff `suggested_price` into the order at creation time. Driver route matching uses exact active city IDs; inactive cities must not be used by Stage 6 driver routes, Stage 7 orders, or Stage 8 matching.

## File Uploads

Allowed upload types:

```text
cargo_photo
passport
selfie
license
car_document
car_photo
```

MVP does not support proof, tracking, chat, audio, or video uploads.

## Collections

Postman collection:

```text
docs/postman/intercity_mvp_api.postman_collection.json
```

Postman environment:

```text
docs/postman/intercity_mvp_local.postman_environment.json
```

Import both files, select the local environment, run auth requests, set token variables, then follow folders in order.

## Removed MVP Features

Do not add or document active usage for:

```text
online payment
P2P payment
Payme
Click
escrow
payment gateway
OTP/QR proof
pickup proof
delivery proof
receiver confirmation code
delivery photo
real-time GPS tracking
maps route tracking
coordinates/distance calculation
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
