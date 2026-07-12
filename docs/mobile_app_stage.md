# Elchi Mobile Frontend Backend Integration — Professional Codex Prompt

You are working on the **Elchi mobile frontend** project.

This is a separate frontend project exported from Figma Make.

Current frontend stack:

```text
Vite
React
TypeScript
Tailwind / CSS
lucide-react icons
shadcn-style UI components
```

Backend is a separate FastAPI project.

Do not move frontend code into backend.

Do not merge backend and frontend into one project.

Expected folder structure:

```text
elchi-platform/
├── backend/
└── mobile-app/
```

Your task is to connect the existing mobile frontend UI to the Elchi backend API.

Do not redesign the app.

Do not add new product features.

Do not add admin panel to the mobile app.

Do not add removed MVP features.

Keep all visible app text in **Uzbek language**.

---

# 1. Important MVP restrictions

Do not implement or add UI for:

```text
admin panel inside mobile app
online payment
Click
Payme
card payment
wallet
balance
escrow
P2P payment
chat
GPS tracking
live map tracking
map picker
coordinates
QR code
delivery OTP
pickup proof
delivery proof
delivery photo
receiver confirmation code
cargo type
cargo weight
cargo size
cargo volume
driver departure time
driver capacity
free space
weight limit
AI pricing
dynamic pricing
earnings dashboard
complex analytics
```

The mobile app must only support:

```text
client auth
driver auth
client order flow
driver profile/documents/routes/feed/bids/orders
notifications
profile/logout
```

---

# 2. First inspect the project

Before changing code, inspect:

```text
package.json
src/app/App.tsx
src/main.tsx
src/styles/
src/app/components/
```

Understand the current screen state machine.

The current app likely uses one large `App.tsx` with local screen state.

Do not break the current UI.

Do not remove existing screens.

Do not remove Uzbek texts.

Do not change visual design unless required for backend integration.

---

# 3. Integration goal

Replace mock/static behavior with real API calls.

The final app must be able to:

```text
request OTP
verify OTP
store access_token and refresh_token
load current user with /auth/me
route user to client or driver UI
load cities from backend
load suggested price from backend
upload cargo photo
create client order
publish client order
list client orders
view order bids
select driver
confirm delivery
rate driver
load driver profile
update driver profile
upload driver documents
set driver availability
create driver routes
load driver feed
send driver bid
list driver orders
update assigned order status
load notifications
logout
```

---

# 4. Environment variables

Create:

```text
.env.example
.env.local
```

`.env.example`:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
VITE_APP_ENV=development
```

`.env.local` should be ignored by git if needed.

The frontend must read API base URL from:

```ts
import.meta.env.VITE_API_BASE_URL
```

Do not hardcode backend URL inside components.

---

# 5. Backend CORS note

The backend must allow the Vite dev origin.

Frontend dev URL is usually:

```text
http://localhost:5173
```

If CORS error appears, do not hack the frontend.

Backend `.env` should include something like:

```env
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

Only update backend CORS if backend code is available and user approves.

Otherwise document this requirement.

---

# 6. API response format

Backend uses standard response format.

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

The frontend API client must handle this format consistently.

Create one central API client.

Do not parse API responses separately in every screen.

---

# 7. Recommended frontend folder structure

Create or refactor into this structure:

```text
src/
├── api/
│   ├── http.ts
│   ├── auth.api.ts
│   ├── cities.api.ts
│   ├── files.api.ts
│   ├── client-orders.api.ts
│   ├── driver.api.ts
│   ├── notifications.api.ts
│   └── index.ts
├── auth/
│   ├── AuthContext.tsx
│   ├── tokenStorage.ts
│   └── roleGuard.ts
├── types/
│   ├── api.ts
│   ├── auth.ts
│   ├── city.ts
│   ├── order.ts
│   ├── driver.ts
│   ├── bid.ts
│   └── notification.ts
├── utils/
│   ├── phone.ts
│   ├── money.ts
│   ├── statusLabels.ts
│   └── errors.ts
└── app/
    └── existing UI files
```

Keep existing UI components.

Only move code if it improves maintainability and does not break design.

---

# 8. HTTP client

Create:

```text
src/api/http.ts
```

Requirements:

```text
Use fetch or axios.
Prefer fetch if no extra dependency is needed.
Automatically attach Authorization header if access_token exists.
Support JSON requests.
Support multipart/form-data file uploads.
Handle backend success/error wrapper.
On 401, try refresh token once.
If refresh fails, logout user and return to login.
Do not log tokens to console.
```

Important token rules:

```text
access_token goes to Authorization: Bearer <token>
refresh_token is used only for /auth/refresh
do not send refresh_token to normal endpoints
```

Recommended local storage keys:

```text
elchi_access_token
elchi_refresh_token
elchi_user
```

For MVP web/mobile prototype, localStorage is acceptable.

Do not store OTP.

Do not store password.

There is no password login.

---

# 9. Token refresh behavior

Implement:

```text
If API returns 401:
  1. call POST /auth/refresh with refresh_token
  2. save new tokens
  3. retry original request once
  4. if still fails, logout
```

Avoid infinite retry loops.

If refresh token is missing, logout immediately.

---

# 10. Auth API

Implement:

```ts
requestOtp(payload)
verifyOtp(payload)
refreshToken(refreshToken)
logout(refreshToken)
getMe()
```

Expected endpoints:

```http
POST /api/v1/auth/request-otp
POST /api/v1/auth/verify-otp
POST /api/v1/auth/refresh
POST /api/v1/auth/logout
GET  /api/v1/auth/me
```

Request OTP body:

```json
{
  "phone": "+998901234567",
  "role": "client"
}
```

or:

```json
{
  "phone": "+998901234567",
  "role": "driver"
}
```

Verify OTP body:

```json
{
  "phone": "+998901234567",
  "role": "client",
  "otp": "12345"
}
```

Roles used in frontend:

```text
client
driver
```

Do not allow mobile app to create:

```text
operator
admin
super_admin
```

These are not mobile app roles.

---

# 11. Auth UX integration

Connect existing auth screens.

Flow:

```text
Splash
Onboarding
Role select
Phone login
OTP verification
```

Behavior:

```text
User selects role: client or driver.
User enters phone.
Frontend calls /auth/request-otp.
OTP screen opens.
User enters 5-digit OTP.
Frontend calls /auth/verify-otp.
Save access_token and refresh_token.
Save user.
Call /auth/me or use returned user.
If role=client, open Client Home.
If role=driver, open Driver Home.
```

OTP requirements in UI:

```text
OTP length = 5 digits
Timer shows 01:59
Resend button disabled until timer ends
```

Use Uzbek error messages:

```text
Kod noto‘g‘ri
Kod muddati tugagan
Juda ko‘p urinish bo‘ldi
Telefon raqam noto‘g‘ri
Bu raqam boshqa rolda ro‘yxatdan o‘tgan
```

---

# 12. Phone formatting helper

Create:

```text
src/utils/phone.ts
```

Frontend should help user enter Uzbek phone numbers.

Rules:

```text
Input visual format: +998 __ ___ __ __
Send normalized format to backend: +998901234567
Do not send spaces or hyphens.
```

If phone is invalid, show:

```text
Telefon raqam noto‘g‘ri
```

Backend still performs final validation.

---

# 13. AuthContext

Create:

```text
src/auth/AuthContext.tsx
```

AuthContext must provide:

```ts
user
role
isAuthenticated
isLoading
loginWithOtp
requestOtp
logout
refreshMe
accessToken
```

App startup behavior:

```text
If access_token exists:
  call /auth/me.
  If valid: show correct role home.
  If invalid: try refresh.
  If refresh fails: clear tokens and show auth.
If no token: show splash/onboarding/auth flow.
```

---

# 14. Cities API

Implement:

```ts
getCities(params)
getSuggestedPrice(fromCityId, toCityId)
```

Endpoints:

```http
GET /api/v1/cities
GET /api/v1/route-tariffs/suggested-price?from_city_id=...&to_city_id=...
```

Cities response may be:

```json
{
  "success": true,
  "data": {
    "items": []
  }
}
```

or simple array depending on backend implementation.

Frontend must support both safely, but prefer `data.items`.

City selector must use real backend cities.

Do not hardcode city list after integration, except as a fallback empty state during development.

Suggested price behavior:

```text
If suggested_price is number, show: 60 000 so‘m
If suggested_price is null, show: Narx haydovchi bilan kelishiladi
```

---

# 15. Files API

Implement file upload helper.

Endpoint:

```http
POST /api/v1/files/upload
```

Use multipart/form-data.

Expected form fields, depending on backend:

```text
file
file_type
```

Supported file_type values for mobile:

```text
cargo_photo
passport
selfie
license
car_document
car_photo
```

Do not use:

```text
pickup_proof
delivery_proof
delivery_photo
```

Create:

```ts
uploadFile(file, fileType)
```

Return expected:

```ts
file_url
```

If backend returns different key, map it in the API adapter only.

Do not spread backend differences into screen components.

---

# 16. Client order API

Create:

```text
src/api/client-orders.api.ts
```

Implement functions based on actual backend endpoints.

Expected endpoint pattern:

```http
POST /api/v1/client/orders
GET  /api/v1/client/orders
GET  /api/v1/client/orders/{order_id}
PATCH /api/v1/client/orders/{order_id}
POST /api/v1/client/orders/{order_id}/publish
GET  /api/v1/client/orders/{order_id}/bids
POST /api/v1/client/orders/{order_id}/select-driver
POST /api/v1/client/orders/{order_id}/confirm
POST /api/v1/client/orders/{order_id}/rating
POST /api/v1/client/orders/{order_id}/cancel
```

If the backend uses slightly different paths, inspect Swagger/OpenAPI or backend code and update only this API file.

Do not change UI logic everywhere.

---

# 17. Client order creation integration

Connect these screens:

```text
Client Home
Create Order Step 1
Create Order Step 2
Create Order Step 3
Order Review
Publish Success
```

Frontend order draft state must include only MVP fields:

```ts
from_city_id
to_city_id
pickup_address
dropoff_address
sender_phone
receiver_phone
cargo_photo_url
comment
```

Do not add:

```text
cargo_type
weight
size
pickup_time
delivery_time
coordinates
map location
```

Flow:

```text
Step 1:
  select from_city
  select to_city
  fetch suggested price

Step 2:
  enter pickup_address
  enter dropoff_address
  enter sender_phone
  enter receiver_phone
  enter comment

Step 3:
  upload cargo photo through /files/upload
  save cargo_photo_url

Review:
  show all data
  create order using POST /client/orders
  then publish order using POST /client/orders/{id}/publish
```

If backend create endpoint automatically creates draft and publish endpoint is separate, follow that.

If backend create endpoint supports direct publish, still keep UI flow the same and use backend properly.

---

# 18. Client orders integration

Connect:

```text
Client Orders screen
Client Order Detail — no bids
Client Order Detail — bids
Client Order Detail — selected driver
Client Confirm
Client Rating
```

Use real data from:

```text
GET /client/orders
GET /client/orders/{order_id}
GET /client/orders/{order_id}/bids
```

Order status mapping in Uzbek:

```ts
draft: "Qoralama"
published: "E’lon qilingan"
bidding: "Takliflar bor"
accepted: "Haydovchi tanlangan"
picked_up: "Olib ketildi"
in_transit: "Yo‘lda"
delivered: "Yetkazildi"
confirmed: "Tasdiqlandi"
cancelled: "Bekor qilingan"
disputed: "Nizo ochilgan"
```

Client selects driver:

```text
User taps "Shu haydovchini tanlash"
Show confirm modal
Call select-driver endpoint with bid_id
Refresh order detail
Show selected driver detail
```

Confirm delivery:

```text
If order.status = delivered:
  show "Yetkazilganini tasdiqlash"
  call confirm endpoint
  then show rating screen
```

Rating:

```text
rating 1 to 5
optional comment
POST rating endpoint
```

No OTP.

No QR.

No delivery proof.

---

# 19. Driver API

Create:

```text
src/api/driver.api.ts
```

Expected functions:

```ts
getDriverProfile()
updateDriverProfile(payload)
uploadDriverDocument(documentType, file)
setDriverAvailability(isAvailable)
getDriverRoutes()
createDriverRoute(payload)
updateDriverRoute(routeId, payload)
getDriverFeed()
sendBid(orderId, payload)
rejectOrder(orderId)
getDriverOrders()
getDriverOrderDetail(orderId)
updateDriverOrderStatus(orderId, status)
```

Expected endpoint pattern:

```http
GET   /api/v1/driver/profile
PATCH /api/v1/driver/profile
PATCH /api/v1/driver/availability

GET   /api/v1/driver/routes
POST  /api/v1/driver/routes
PATCH /api/v1/driver/routes/{route_id}

GET   /api/v1/driver/feed
POST  /api/v1/driver/orders/{order_id}/bids
POST  /api/v1/driver/orders/{order_id}/reject

GET   /api/v1/driver/orders
GET   /api/v1/driver/orders/{order_id}
POST  /api/v1/driver/orders/{order_id}/status
```

If backend paths differ, update only `driver.api.ts`.

---

# 20. Driver profile integration

Connect screens:

```text
Driver Home
Driver Profile Form
Driver Documents
Driver Profile
```

Driver profile editable fields only:

```ts
full_name
car_model
car_color
plate_number
```

Do not let frontend send:

```text
verification_status
rating
total_orders
completed_orders
cancelled_orders
dispute_count
role
user status
```

Documents:

```text
passport
selfie
license
car_document
car_photo
```

Do not send:

```text
pickup_proof
delivery_proof
delivery_photo
```

Driver verification states:

```text
new
pending
approved
rejected
blocked
```

Use Uzbek labels:

```ts
new: "Profil va hujjatlarni to‘ldiring"
pending: "Hujjatlar ko‘rib chiqilmoqda"
approved: "Profil tasdiqlangan"
rejected: "Hujjatlar rad etildi"
blocked: "Profil bloklangan"
```

---

# 21. Driver availability integration

Availability UI rule:

```text
If verification_status !== approved:
  disable toggle
  show "Tasdiqlanmaguncha faol bo‘la olmaysiz"

If verification_status === approved:
  allow toggle
```

API:

```text
PATCH /driver/availability
```

Payload:

```json
{
  "is_available": true
}
```

If backend returns DRIVER_NOT_APPROVED, show:

```text
Tasdiqlanmaguncha faol bo‘la olmaysiz
```

---

# 22. Driver routes integration

Connect:

```text
Driver Routes
Add Route
```

Route fields:

```ts
from_city_id
to_city_id
```

Do not add:

```text
departure_time
capacity
free_space
weight_limit
```

Load cities from real `/cities`.

After creating route, return to routes list and refresh.

Route status labels:

```ts
available: "Faol"
unavailable: "Faol emas"
busy: "Band"
```

---

# 23. Driver feed and bids integration

Feed visible only when backend returns data.

Frontend should show helpful states:

```text
Profil tasdiqlanmagan
Faol holatni yoqing
Hozircha mos buyurtmalar yo‘q
```

Before driver is selected, do not show private client data.

Do not render fields if backend accidentally includes them in feed:

```text
sender_phone
receiver_phone
full pickup_address
full dropoff_address
```

Use only limited fields:

```text
from_city
to_city
pickup_area or shortened pickup_address
dropoff_area or shortened dropoff_address
suggested_price
cargo_photo_url
```

Send bid:

```json
{
  "price": 70000,
  "comment": "Bugun olib ketaman"
}
```

Validation:

```text
Taklif narxi 0 dan katta bo‘lishi kerak
```

---

# 24. Driver assigned orders integration

Connect:

```text
Driver Orders
Assigned Order Detail
Status update buttons
```

Driver can update statuses:

```text
accepted → picked_up
picked_up → in_transit
in_transit → delivered
```

Button labels:

```text
Olib ketildi deb belgilash
Yo‘lga chiqdi deb belgilash
Yetkazildi deb belgilash
```

Do not implement:

```text
delivery proof upload
delivery photo
OTP
QR
```

After status update, refresh order detail.

---

# 25. Notifications API

Create:

```text
src/api/notifications.api.ts
```

Expected endpoints:

```http
GET  /api/v1/notifications
POST /api/v1/notifications/{notification_id}/read
```

If backend differs, update API adapter only.

Show notifications in Uzbek.

Empty state:

```text
Hozircha bildirishnomalar yo‘q
```

---

# 26. Loading, error, and empty states

Every API screen must have:

```text
loading state
error state
empty state
retry action
```

Use Uzbek UI text:

```text
Yuklanmoqda...
Xatolik yuz berdi
Qayta urinib ko‘ring
Ma’lumot topilmadi
Internet aloqasi yo‘q
Ruxsat yo‘q
```

Do not leave raw English backend errors on screen.

Map known backend error codes to Uzbek messages.

Example:

```ts
ROLE_MISMATCH: "Bu telefon raqam boshqa rolda ro‘yxatdan o‘tgan"
OTP_INVALID: "Kod noto‘g‘ri"
OTP_EXPIRED: "Kod muddati tugagan"
DRIVER_NOT_APPROVED: "Profil tasdiqlanmagan"
CITY_INACTIVE: "Tanlangan shahar faol emas"
ROUTE_TARIFF_NOT_FOUND: "Bu yo‘nalish uchun narx topilmadi"
```

---

# 27. Money formatting

Create:

```text
src/utils/money.ts
```

Format UZS prices:

```text
60000 → 60 000 so‘m
```

If value is null:

```text
Narx haydovchi bilan kelishiladi
```

Do not show decimals.

---

# 28. Status label helper

Create:

```text
src/utils/statusLabels.ts
```

Map backend statuses to Uzbek labels.

Order statuses:

```text
draft
published
bidding
accepted
picked_up
in_transit
delivered
confirmed
cancelled
disputed
```

Driver verification statuses:

```text
new
pending
approved
rejected
blocked
```

Route statuses:

```text
available
unavailable
busy
```

Bid statuses:

```text
active
accepted
closed
rejected
expired
```

---

# 29. Route protection

If using React Router, add route guards.

If keeping the existing screen-state approach, add equivalent guards.

Rules:

```text
Unauthenticated user cannot access client/driver screens.
Client cannot access driver screens.
Driver cannot access client screens.
If token expires and refresh fails, return to auth flow.
```

Mobile app roles:

```text
client
driver
```

No admin screens.

---

# 30. Do not break UI/UX

Important:

```text
Keep the current visual design.
Keep Uzbek text.
Keep mobile layout.
Keep bottom navigation compact.
Do not introduce overlapping text.
Do not introduce new tabs.
Do not create admin screens.
Do not add payment/wallet/chat/map features.
```

Only change UI where required for real backend data:

```text
loading state
error state
empty state
real list rendering
real form state
real submit handlers
```

---

# 31. Development commands

Update README with:

```bash
npm install
npm run dev
```

or if pnpm is used:

```bash
pnpm install
pnpm dev
```

Add `.env.example` instructions:

```bash
cp .env.example .env.local
```

Example:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
```

---

# 32. Manual QA checklist

After implementation, verify manually.

## Auth

```text
Client can request OTP.
Client can verify OTP.
Client reaches Client Home.
Driver can request OTP.
Driver can verify OTP.
Driver reaches Driver Home.
Wrong OTP shows Uzbek error.
Logout clears token.
Refresh token works after access token expires.
```

## Cities

```text
City list loads from backend.
Suggested price loads after from/to selected.
No tariff shows "Narx haydovchi bilan kelishiladi".
```

## Client flow

```text
Client creates order.
Client uploads cargo photo.
Client publishes order.
Client sees order in list.
Client sees bids.
Client selects driver.
Client confirms delivered order.
Client rates driver.
```

## Driver flow

```text
Driver loads profile.
Driver updates profile.
Driver uploads documents.
Driver sees pending state.
Approved driver can enable availability.
Driver creates route.
Driver sees matching feed.
Driver sends bid.
Driver sees assigned order.
Driver updates status accepted → picked_up → in_transit → delivered.
```

## Security UX

```text
Driver before selected does not see sender phone.
Driver before selected does not see receiver phone.
Driver before selected does not see full pickup address.
Driver before selected does not see full dropoff address.
Client cannot see driver screens.
Driver cannot see client screens.
```

---

# 33. Final report

After finishing, stop and report:

```text
1. Files changed
2. API modules created
3. Auth/token flow implemented
4. Which backend endpoints are connected
5. Which endpoints were missing or had different paths
6. How to configure VITE_API_BASE_URL
7. How to run frontend
8. Manual QA result
9. Known TODOs
10. Any backend CORS requirement
```

Do not continue adding new features after backend integration is complete.
