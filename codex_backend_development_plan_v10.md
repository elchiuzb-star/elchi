# Codex uchun Backend Development Plan v1.0

Ushbu hujjat Intercity Parcel Delivery Marketplace MVP backendini Codex orqali professional, bosqichma-bosqich yozish uchun tayyorlandi.

Asosiy qoida: Codex birdan hamma narsani yozmasin. Har bir etap alohida bajariladi, tekshiriladi, test qilinadi va keyingi etapga o‘tiladi.

---

# 0. Muhim loyiha qoidalari

Backend quyidagi tasdiqlangan MVP logikasiga qat’iy amal qilishi kerak.

## MVPda bo‘lmaydigan funksiyalar

Quyidagilarni backendga qo‘shma:

```text
Time match yo‘q
Driver departure time yo‘q
Capacity check yo‘q
Driver capacity yo‘q
Cargo type yo‘q
Weight yo‘q
Size / hajm yo‘q
OTP yo‘q
QR yo‘q
Pickup proof yo‘q
Delivery proof yo‘q
Online payment yo‘q
P2P payment yo‘q
Real-time GPS tracking yo‘q
Chat yo‘q
```

## MVPda bo‘ladigan asosiy model

```text
Client order yaratadi
↓
Order published bo‘ladi
↓
Route bo‘yicha approved driverlarga ko‘rinadi
↓
Driverlar bid beradi
↓
Client bitta driverni tanlaydi
↓
Driver statuslarni yangilaydi
↓
Client yoki Operator confirmed qiladi
↓
Payment = cash
```

## Asosiy backend prinsiplar

```text
Har bir etap alohida bajarilsin
Har bir etapdan keyin test yozilsin
Har bir etapdan keyin migration tekshirilsin
Har bir muhim action audit_logs ga yozilsin
Har bir status o‘zgarishi status_history ga yozilsin
Role-based access qat’iy tekshirilsin
Operator barcha statuslarga aralasha oladi
Normal flowdan tashqari operator o‘zgartirsa reason majburiy
```

---

# 1. Codex uchun umumiy master prompt

Quyidagi promptni Codexga birinchi berish kerak.

```text
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
```

---

# 2. Etap 1 — Repository audit va project setup

## Maqsad

Project holatini aniqlash va backend uchun toza struktura tayyorlash.

## Codexga prompt

```text
Stage 1: Inspect the repository and prepare backend project setup.

Tasks:
1. Inspect the current repository structure.
2. Detect if a backend already exists.
3. If backend exists, summarize its framework, folder structure, dependencies, and database setup.
4. If backend does not exist, create a clean FastAPI backend structure:
   - app/main.py
   - app/core/config.py
   - app/core/security.py
   - app/db/session.py
   - app/db/base.py
   - app/models/
   - app/schemas/
   - app/api/v1/
   - app/services/
   - app/utils/
   - tests/
   - alembic/
5. Add environment configuration support.
6. Add health check endpoint: GET /api/v1/health.
7. Add README instructions for running locally.

Do not implement business logic yet.

After finishing, run basic tests and report files changed.
```

## Tekshiruv checklist

```text
Backend ishga tushadi
Health endpoint ishlaydi
.env.example bor
Database connection config bor
Test command ishlaydi
Project strukturasi tartibli
Hali order/bid logic yozilmagan
```

## Manual test

```http
GET /api/v1/health
```

Expected:

```json
{
  "success": true,
  "message": "OK"
}
```

---

# 3. Etap 2 — Database models va migrations

## Maqsad

Tasdiqlangan Database Schema v1.0 asosida models va migrations yozish.

## Codexga prompt

```text
Stage 2: Implement database models and Alembic migrations.

Use the approved Database Schema v1.0.

Create models:
- User
- ClientProfile
- DriverProfile
- DriverDocument
- City
- DriverRoute
- RouteTariff
- Order
- Bid
- OrderOffer
- StatusHistory
- Dispute
- Rating
- Notification
- AuditLog

Important:
Do not add these fields anywhere:
- departure_time
- capacity
- cargo_type
- weight
- size
- otp
- qr
- pickup_proof
- delivery_proof
- online_payment

Add indexes and constraints:
- users.phone unique
- client_profiles.user_id unique
- driver_profiles.user_id unique
- driver_profiles.plate_number unique where possible
- orders.order_number unique
- orders.from_city_id != orders.to_city_id
- bids unique(order_id, driver_id)
- order_offers unique(order_id, driver_id)
- ratings.order_id unique
- rating between 1 and 5

Generate Alembic migration.
Add basic model tests.
```

## Tekshiruv checklist

```text
Barcha models bor
Migration yaratilgan
Migration databasega muvaffaqiyatli apply bo‘ladi
Rollback ishlaydi
Taqiqlangan fieldlar yo‘q
Unique constraintlar bor
Check constraintlar bor
Indexlar bor
```

## Manual tekshiruv

```bash
alembic upgrade head
alembic downgrade -1
alembic upgrade head
pytest
```

---

# 4. Etap 3 — Auth API

## Maqsad

Telefon orqali login/register va JWT token tizimini yozish.

MVP uchun OTP real SMS bilan shart emas. Developmentda mock OTP ishlashi mumkin.

## Codexga prompt

```text
Stage 3: Implement Auth API.

Endpoints:
- POST /api/v1/auth/request-otp
- POST /api/v1/auth/verify-otp
- POST /api/v1/auth/refresh
- POST /api/v1/auth/logout
- GET /api/v1/auth/me

Rules:
- Public users can register only as client or driver.
- operator/admin/super_admin cannot register publicly.
- Use JWT access token and refresh token.
- Mark phone as verified after OTP verification.
- For development, use mock OTP or store OTP securely depending on current project setup.
- Add role-based dependency helpers.
- Add tests for client login and driver login.
```

## Tekshiruv checklist

```text
Client login ishlaydi
Driver login ishlaydi
Admin role public register bo‘lmaydi
JWT token qaytadi
/auth/me ishlaydi
Refresh token ishlaydi
Blocked user login qila olmaydi
Tests yozilgan
```

## Manual API test

```http
POST /api/v1/auth/request-otp
POST /api/v1/auth/verify-otp
GET /api/v1/auth/me
```

---

# 5. Etap 4 — Files API

## Maqsad

Cargo photo va driver documents uchun fayl upload endpointini yozish.

## Codexga prompt

```text
Stage 4: Implement Files API.

Endpoint:
- POST /api/v1/files/upload

Supported types:
- cargo_photo
- passport
- selfie
- license
- car_document
- car_photo

Rules:
- Endpoint must require authentication.
- Use multipart/form-data.
- Validate file type and file size.
- Store files locally in development if no object storage exists.
- Return file_url.
- Do not implement pickup proof or delivery proof.
```

## Tekshiruv checklist

```text
Authenticated user fayl upload qila oladi
Anonymous user upload qila olmaydi
Noto‘g‘ri file type rad etiladi
File size limit ishlaydi
cargo_photo type bor
pickup_proof/delivery_proof type yo‘q
```

---

# 6. Etap 5 — Cities va Route Tariffs API

## Maqsad

Shaharlar va route bo‘yicha suggested price APIlarini yozish.

## Codexga prompt

```text
Stage 5: Implement Cities and Route Tariffs API.

Endpoints:
- GET /api/v1/cities
- GET /api/v1/route-tariffs/suggested-price
- POST /api/v1/admin/cities
- POST /api/v1/admin/route-tariffs

Rules:
- Public or authenticated users can get cities.
- Authenticated users can get suggested price.
- Only admin/super_admin can create cities and route tariffs.
- from_city_id and to_city_id cannot be the same.
- suggested_price must be >= 0.
- Add seed data for initial cities if project supports seed scripts.
```

## Tekshiruv checklist

```text
Cities list ishlaydi
Suggested price route bo‘yicha qaytadi
Admin city qo‘sha oladi
Client city qo‘sha olmaydi
from_city = to_city bo‘lsa error beradi
Route tariff bo‘lmasa null yoki clear error qaytadi
```

---

# 7. Etap 6 — Driver Profile, Documents, Routes

## Maqsad

Driver o‘z profilini to‘ldiradi, hujjat yuklaydi, route yaratadi va availability boshqaradi.

## Codexga prompt

```text
Stage 6: Implement Driver Profile, Documents, and Routes APIs.

Endpoints:
- GET /api/v1/driver/profile
- PATCH /api/v1/driver/profile
- POST /api/v1/driver/documents
- PATCH /api/v1/driver/availability
- POST /api/v1/driver/routes
- GET /api/v1/driver/routes
- PATCH /api/v1/driver/routes/{route_id}/status
- DELETE /api/v1/driver/routes/{route_id}

Rules:
- Only driver role can access driver endpoints.
- Driver cannot become available unless verification_status = approved.
- Driver route must have only from_city_id and to_city_id.
- Do not add departure_time.
- Do not add capacity/free_space/weight_limit.
- Driver can manage only own routes.
```

## Tekshiruv checklist

```text
Driver profile ko‘ra oladi
Driver profile update qila oladi
Driver hujjat yuklay oladi
Driver route yaratadi
Route’da departure_time yo‘q
Route’da capacity yo‘q
Unapproved driver available bo‘la olmaydi
Approved driver available bo‘la oladi
Driver boshqa driver routeini o‘zgartira olmaydi
```

---

# 8. Etap 7 — Client Orders API

## Maqsad

Client order yaratadi, publish qiladi, orderlarini ko‘radi, cancel qiladi.

## Codexga prompt

```text
Stage 7: Implement Client Orders API.

Endpoints:
- POST /api/v1/client/orders
- POST /api/v1/client/orders/{order_id}/publish
- GET /api/v1/client/orders
- GET /api/v1/client/orders/{order_id}
- POST /api/v1/client/orders/{order_id}/cancel

Order fields:
- from_city_id
- to_city_id
- pickup_address
- dropoff_address
- sender_phone
- receiver_phone
- cargo_photo_url
- comment

Do not add:
- cargo_type
- weight
- size
- pickup_time
- delivery_time

Rules:
- Client can only manage own orders.
- Create order as draft.
- On publish, status becomes published.
- suggested_price comes from route_tariffs if available.
- payment_method = cash.
- payment_status = unpaid.
- status_history must be written on publish/cancel.
```

## Tekshiruv checklist

```text
Client draft order yaratadi
Orderda cargo_type yo‘q
Orderda weight yo‘q
Orderda size yo‘q
Orderda pickup_time yo‘q
Publish ishlaydi
Publish status_history yozadi
Client faqat o‘z orderini ko‘radi
Client boshqa orderni ko‘ra olmaydi
Cancel reason majburiy
```

---

# 9. Etap 8 — Matching va Order Offers

## Maqsad

Order published bo‘lganda route bo‘yicha mos driverlarni topish va order_offers yozish.

## Codexga prompt

```text
Stage 8: Implement route-based matching and order_offers creation.

Matching rules:
- order.from_city_id = driver_routes.from_city_id
- order.to_city_id = driver_routes.to_city_id
- driver_routes.status = available
- driver.verification_status = approved
- driver.is_available = true
- user.status != blocked

Do not use:
- departure_time
- capacity
- weight
- size
- cargo_type

When order is published:
- Find matched drivers.
- Create order_offers for matched drivers.
- Do not duplicate order_offers because unique(order_id, driver_id).
- Return matched_drivers_count.
```

## Tekshiruv checklist

```text
Approved available driver match bo‘ladi
Unapproved driver match bo‘lmaydi
Blocked driver match bo‘lmaydi
Wrong route driver match bo‘lmaydi
Time match ishlatilmaydi
Capacity check ishlatilmaydi
Duplicate order_offers yaratilmaydi
```

---

# 10. Etap 9 — Driver Feed va Bids

## Maqsad

Driver mos orderlarni ko‘radi va bid beradi.

## Codexga prompt

```text
Stage 9: Implement Driver Order Feed and Bids APIs.

Endpoints:
- GET /api/v1/driver/orders/feed
- GET /api/v1/driver/orders/{order_id}
- POST /api/v1/driver/orders/{order_id}/bids
- PATCH /api/v1/driver/bids/{bid_id}
- POST /api/v1/driver/orders/{order_id}/reject

Rules:
- Driver sees only orders matching own available routes.
- Before accepted, driver sees limited order data only.
- After accepted, assigned driver sees full order data.
- Driver can bid only if approved and available.
- Driver can bid only on published or bidding orders.
- One driver can have only one bid per order.
- If order status is published and first bid is created, order status becomes bidding.
- status_history must be written when status changes.
- order_offers result must update to bid_sent or rejected.
```

## Tekshiruv checklist

```text
Driver feed route bo‘yicha ishlaydi
Driver full contactni tanlanmaguncha ko‘rmaydi
Driver bid bera oladi
Unapproved driver bid bera olmaydi
Wrong route driver bid bera olmaydi
Duplicate bid bo‘lmaydi
Bid update ishlaydi
Reject qilsa order qayta chiqmaydi
published → bidding status_history yoziladi
```

---

# 11. Etap 10 — Select Driver Transaction

## Maqsad

Client bid tanlaydi va order accepted bo‘ladi.

## Codexga prompt

```text
Stage 10: Implement select driver logic as a safe transaction.

Endpoint:
- POST /api/v1/client/orders/{order_id}/select-driver

Rules:
- Client can select driver only for own order.
- Order status must be bidding.
- Bid must belong to order.
- Bid status must be active.
- Driver must be approved.
- Use database transaction:
  - orders.assigned_driver_id = bid.driver_id
  - orders.accepted_bid_id = bid.id
  - orders.final_price = bid.price
  - orders.status = accepted
  - orders.accepted_at = now()
  - selected bid status = accepted
  - other bids status = closed
  - status_history written
  - audit_logs written
```

## Tekshiruv checklist

```text
Client active bidni tanlaydi
Order accepted bo‘ladi
assigned_driver_id yoziladi
final_price yoziladi
Selected bid accepted bo‘ladi
Other bids closed bo‘ladi
Transaction xatosiz ishlaydi
Boshqa client tanlay olmaydi
Accepted orderga boshqa bid berilmaydi
```

---

# 12. Etap 11 — Driver Order Status API

## Maqsad

Driver assigned order statuslarini o‘zgartiradi.

## Codexga prompt

```text
Stage 11: Implement Driver Order Status API.

Endpoints:
- POST /api/v1/driver/orders/{order_id}/picked-up
- POST /api/v1/driver/orders/{order_id}/in-transit
- POST /api/v1/driver/orders/{order_id}/delivered
- POST /api/v1/driver/orders/{order_id}/cancel

Rules:
- Driver can update only assigned orders.
- accepted → picked_up
- picked_up → in_transit
- in_transit → delivered
- Driver can cancel only in accepted status.
- Driver cannot cancel after picked_up.
- Every status change writes status_history.
- Notifications should be created if notification module exists.
```

## Tekshiruv checklist

```text
Assigned driver picked_up qila oladi
Boshqa driver picked_up qila olmaydi
Status ketma-ketlikdan tashqari o‘tmaydi
picked_updan keyin driver cancel qila olmaydi
Har status historyga yoziladi
Client notification yoziladi
```

---

# 13. Etap 12 — Client Confirm va Rating

## Maqsad

Client delivered orderni confirmed qiladi va rating beradi.

## Codexga prompt

```text
Stage 12: Implement Client Confirm and Rating APIs.

Endpoints:
- POST /api/v1/client/orders/{order_id}/confirm
- POST /api/v1/client/orders/{order_id}/rating

Rules:
- Client can confirm only own order.
- Order status must be delivered.
- Confirm sets status = confirmed.
- confirmed_at = now().
- payment_method remains cash.
- payment_status can be set to paid_manual or remain unpaid depending on current service logic; use paid_manual for MVP confirmation.
- Rating only after confirmed.
- One rating per order.
- Rating must be 1 to 5.
```

## Tekshiruv checklist

```text
Delivered order confirmed bo‘ladi
Non-delivered order confirmed bo‘lmaydi
Client boshqa orderni confirm qila olmaydi
Rating confirmed orderga beriladi
Bitta orderga ikki marta rating bo‘lmaydi
Driver rating recalculation ishlaydi yoki keyingi TODO sifatida belgilanadi
```

---

# 14. Etap 13 — Dispute API

## Maqsad

Client/driver/operator/admin dispute ochadi va admin boshqaradi.

## Codexga prompt

```text
Stage 13: Implement Dispute APIs.

Endpoints:
- POST /api/v1/orders/{order_id}/disputes
- GET /api/v1/disputes
- GET /api/v1/admin/disputes
- PATCH /api/v1/admin/disputes/{dispute_id}

Rules:
- Client can open dispute only for own order.
- Driver can open dispute only for assigned order.
- Operator/Admin can open dispute for any order.
- reason is required.
- Create dispute with status = open.
- Store previous_order_status.
- Set order.status = disputed.
- Write status_history.
- Admin/operator can update dispute status:
  open, under_review, resolved, rejected.
```

## Tekshiruv checklist

```text
Client dispute ocha oladi
Driver assigned orderga dispute ocha oladi
Boshqa driver dispute ocha olmaydi
Operator hammasiga dispute ocha oladi
previous_order_status saqlanadi
Order disputed bo‘ladi
Admin dispute statusni yangilaydi
```

---

# 15. Etap 14 — Admin Orders API

## Maqsad

Operator/admin orderlarni ko‘radi, status o‘zgartiradi, driver assign qiladi, cancel qiladi.

## Codexga prompt

```text
Stage 14: Implement Admin Orders API.

Endpoints:
- GET /api/v1/admin/orders
- GET /api/v1/admin/orders/{order_id}
- PATCH /api/v1/admin/orders/{order_id}/status
- POST /api/v1/admin/orders/{order_id}/assign-driver
- POST /api/v1/admin/orders/{order_id}/cancel

Rules:
- operator/admin/super_admin can access admin orders.
- Operator can change any order status.
- If status change is outside normal flow, reason is required.
- Every admin/operator action writes audit_logs.
- Every status change writes status_history.
- Admin assign driver requires approved driver and final_price > 0.
- Confirmed order cancel is only admin/super_admin exceptional action.
```

## Tekshiruv checklist

```text
Operator orders list ko‘radi
Operator status o‘zgartira oladi
Normal flowdan tashqari reason majburiy
Audit log yoziladi
Status history yoziladi
Admin driver assign qila oladi
Unapproved driver assign bo‘lmaydi
```

---

# 16. Etap 15 — Admin Driver Verification API

## Maqsad

Admin driverlarni approve/reject/block qiladi.

## Codexga prompt

```text
Stage 15: Implement Admin Driver Verification APIs.

Endpoints:
- GET /api/v1/admin/drivers
- GET /api/v1/admin/drivers/{driver_id}
- POST /api/v1/admin/drivers/{driver_id}/approve
- POST /api/v1/admin/drivers/{driver_id}/reject
- POST /api/v1/admin/drivers/{driver_id}/block

Rules:
- operator can view drivers.
- admin/super_admin can approve/reject/block.
- reject requires reason.
- block requires reason.
- approve sets verification_status = approved.
- reject sets verification_status = rejected.
- block sets verification_status = blocked and optionally user.status = blocked.
- Every action writes audit_logs.
```

## Tekshiruv checklist

```text
Operator driverlarni ko‘ra oladi
Operator approve qila olmaydi
Admin approve qila oladi
Reject reason majburiy
Block reason majburiy
Blocked driver available bo‘la olmaydi
Audit log yoziladi
```

---

# 17. Etap 16 — Notifications API

## Maqsad

In-app notificationlarni yozish va o‘qilgan qilish.

## Codexga prompt

```text
Stage 16: Implement Notifications API.

Endpoints:
- GET /api/v1/notifications
- PATCH /api/v1/notifications/{notification_id}/read

Rules:
- User sees only own notifications.
- Notifications are created for important events:
  - order_published
  - new_bid
  - driver_selected
  - picked_up
  - in_transit
  - delivered
  - confirmed
  - cancelled
  - disputed
- Implement in_app notifications first.
- Do not integrate external SMS/FCM unless project already has it.
```

## Tekshiruv checklist

```text
User o‘z notificationlarini ko‘radi
Boshqa user notificationini ko‘rmaydi
Read qilish ishlaydi
Order events notification yaratadi
SMS/FCM majburan qo‘shilmagan
```

---

# 18. Etap 17 — Audit Logs API

## Maqsad

Admin/super_admin audit loglarni ko‘radi.

## Codexga prompt

```text
Stage 17: Implement Audit Logs API.

Endpoint:
- GET /api/v1/admin/audit-logs

Rules:
- Only admin and super_admin can access audit logs.
- Filters:
  - actor_id
  - entity_type
  - entity_id
  - action
  - page
  - limit
- Audit logs must exist for:
  - order created
  - order published
  - driver bid created
  - bid updated
  - driver selected
  - status changed
  - order cancelled
  - dispute opened
  - operator status changed
  - admin driver approved/rejected/blocked
```

## Tekshiruv checklist

```text
Admin audit log ko‘radi
Operator audit log ko‘ra olmaydi yoki read-only ruxsat siyosatiga qarab cheklanadi
Filterlar ishlaydi
Audit loglar muhim actionlarda yozilgan
```

---

# 19. Etap 18 — Security va permission hardening

## Maqsad

Role-based access va edge case’larni mustahkamlash.

## Codexga prompt

```text
Stage 18: Security and permission hardening.

Tasks:
1. Review all endpoints for role-based access.
2. Ensure client can access only own orders.
3. Ensure driver can access only matched or assigned orders.
4. Ensure driver does not see full contact data before accepted.
5. Ensure operator/admin endpoints are protected.
6. Ensure blocked users cannot act.
7. Ensure blocked drivers cannot bid or be assigned.
8. Add tests for forbidden access cases.
9. Add consistent error responses.
```

## Tekshiruv checklist

```text
Client boshqa client orderini ko‘rmaydi
Driver boshqa route orderini ko‘rmaydi
Driver tanlanmaguncha contact ko‘rmaydi
Blocked user API ishlata olmaydi
Admin endpoints protected
Error response bir xil formatda
Forbidden tests bor
```

---

# 20. Etap 19 — API docs va test collection

## Maqsad

Backend jamoa va frontend/mobile jamoa ishlatishi uchun API hujjat va test collection tayyorlash.

## Codexga prompt

```text
Stage 19: API documentation and test collection.

Tasks:
1. Ensure OpenAPI/Swagger docs work.
2. Add endpoint descriptions.
3. Add request/response examples.
4. Create Postman or HTTPie collection if possible.
5. Add README section:
   - how to run backend
   - how to run migrations
   - how to run tests
   - how to seed cities and tariffs
   - how to create admin user
6. Add developer notes about MVP restrictions.
```

## Tekshiruv checklist

```text
Swagger ochiladi
Endpointlar nomi tushunarli
README yangilangan
Seed instruction bor
Admin yaratish instruction bor
MVP restrictions yozilgan
Postman/HTTP collection bor yoki TODO yozilgan
```

---

# 21. Etap 20 — Final QA va regression test

## Maqsad

Butun backend flow boshidan oxirigacha ishlashini tekshirish.

## Codexga prompt

```text
Stage 20: Final QA and regression tests.

Create automated integration tests for the full MVP flow:

1. Client registers.
2. Driver registers.
3. Admin approves driver.
4. Admin creates cities and route tariff.
5. Driver creates route and sets available.
6. Client creates order draft.
7. Client publishes order.
8. Matching creates order_offers.
9. Driver sees order in feed.
10. Driver creates bid.
11. Client selects driver.
12. Driver marks picked_up.
13. Driver marks in_transit.
14. Driver marks delivered.
15. Client confirms order.
16. Client rates driver.

Also test:
- Wrong route driver does not see order.
- Unapproved driver cannot bid.
- Driver cannot update another driver's order.
- Client cannot confirm another client's order.
- Operator can manually change status with reason.
- Dispute can be opened.
- Audit logs are created.
```

## Tekshiruv checklist

```text
Full happy path ishlaydi
Permission testlar ishlaydi
Status transition testlar ishlaydi
Audit logs testlari ishlaydi
Dispute testlari ishlaydi
No removed features exist in code
All tests pass
```

---

# 22. Codex bilan ishlash qoidasi

Har bir etapdan keyin Codexdan quyidagilarni talab qilish kerak:

```text
Stop after this stage.
Do not continue to the next stage yet.

Report:
1. Summary of implemented changes
2. Files changed
3. Database migrations created
4. How to run migration
5. How to run tests
6. Manual API test examples
7. Any assumptions made
8. Any TODOs
```

Agar testlar o‘tmasa:

```text
Do not add new features.
Fix the failing tests first.
Explain the root cause.
Then rerun tests.
```

Agar Codex keraksiz feature qo‘shsa:

```text
Remove this feature because it is outside MVP scope.
Do not add time matching, capacity, weight, size, OTP/QR, proof, online payment, or tracking.
Keep the MVP simple according to Product Logic v0.2.
```

---

# 23. Tavsiya etilgan backend module structure

Agar project noldan boshlansa, shunday structure tavsiya qilinadi:

```text
app/
  main.py
  core/
    config.py
    security.py
    permissions.py
  db/
    session.py
    base.py
  models/
    user.py
    client_profile.py
    driver_profile.py
    driver_document.py
    city.py
    driver_route.py
    route_tariff.py
    order.py
    bid.py
    order_offer.py
    status_history.py
    dispute.py
    rating.py
    notification.py
    audit_log.py
  schemas/
    auth.py
    user.py
    driver.py
    order.py
    bid.py
    dispute.py
    admin.py
  services/
    auth_service.py
    order_service.py
    matching_service.py
    bid_service.py
    status_service.py
    audit_service.py
    notification_service.py
    driver_service.py
    dispute_service.py
  api/
    v1/
      auth.py
      files.py
      cities.py
      route_tariffs.py
      client_orders.py
      driver_profile.py
      driver_routes.py
      driver_orders.py
      driver_bids.py
      disputes.py
      notifications.py
      admin_orders.py
      admin_drivers.py
      admin_disputes.py
      audit_logs.py
  utils/
    order_number.py
    file_storage.py
tests/
  test_auth.py
  test_models.py
  test_client_orders.py
  test_driver_routes.py
  test_matching.py
  test_bids.py
  test_order_status.py
  test_disputes.py
  test_admin_orders.py
  test_permissions.py
```

---

# 24. Qisqa development ketma-ketligi

```text
Etap 1: Repository audit va setup
Etap 2: Database models va migrations
Etap 3: Auth API
Etap 4: Files API
Etap 5: Cities va Route Tariffs API
Etap 6: Driver Profile, Documents, Routes
Etap 7: Client Orders API
Etap 8: Matching va Order Offers
Etap 9: Driver Feed va Bids
Etap 10: Select Driver Transaction
Etap 11: Driver Order Status API
Etap 12: Client Confirm va Rating
Etap 13: Dispute API
Etap 14: Admin Orders API
Etap 15: Admin Driver Verification API
Etap 16: Notifications API
Etap 17: Audit Logs API
Etap 18: Security va permission hardening
Etap 19: API docs va test collection
Etap 20: Final QA va regression test
```

---

# 25. Yakuniy qoida

Codex har doim quyidagi prinsip bilan ishlasin:

```text
First make it correct.
Then make it clean.
Then make it tested.
Only then move to the next stage.
```
