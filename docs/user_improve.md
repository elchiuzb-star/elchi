# Elchi Mobile App — Client UX Hardening and Order Flow Completion

You are working on the **Elchi mobile frontend** project.

Frontend stack:

```text
Vite
React
TypeScript
Google Maps
```

This task focuses only on the **client/user side** of the mobile app.

Do not redesign the whole app.

Do not add admin panel.

Do not add driver-only features except where needed for displaying client order data.

Do not add features outside the approved MVP.

All visible UI text must be in **Uzbek language**.

---

# 1. Goal

Improve and complete the client-side UX for:

```text
auth role routing
city/district/map pickup selection
city/district/map dropoff selection
manual address fallback
order creation validation
suggested price explanation
order publish empty state
bids comparison
select driver confirmation
order status timeline
cancel/dispute UX
delivery confirmation
rating flow
notifications click behavior
loading/error/empty states
```

The app must feel production-ready for MVP.

---

# 2. MVP restrictions

Do not implement:

```text
online payment
Click
Payme
card payment
wallet
balance
escrow
P2P
chat
live GPS tracking
driver live location
route calculation
distance calculation
distance-based pricing
Distance Matrix API
Directions API
Routes API
Navigation SDK
delivery OTP
QR code
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
```

Google Maps is allowed only for:

```text
pickup pin selection
dropoff pin selection
reverse geocoding
read-only map preview after driver is assigned
```

Matching remains based on:

```text
from_city_id
from_district_id
to_city_id
to_district_id
```

Do not implement coordinate-based matching.

---

# 3. Auth startup and role routing

Implement or fix app startup logic.

Startup behavior:

```text
If access_token exists:
  call GET /api/v1/auth/me
  if valid and role=client:
    show Client Map Home
  if valid and role=driver:
    show Driver Home
  if token invalid:
    try refresh token once
  if refresh fails:
    clear tokens and show auth flow

If no token:
  show Splash / Onboarding / Role Select / Login flow
```

Mobile app roles:

```text
client
driver
```

Do not allow mobile app to create or access:

```text
operator
admin
super_admin
```

If backend returns admin/operator/super_admin role, show:

```text
Bu rol mobile ilova uchun mavjud emas
```

and logout.

---

# 4. Client location selection flow

Both pickup and dropoff must use the same logic.

## Pickup

When user taps:

```text
Olib ketish joyi
```

or:

```text
Qayerdan?
```

Flow:

```text
1. Open city selector.
2. User searches city/region.
3. User selects city.
4. If selected city requires district, open district selector.
5. User searches district.
6. User selects district.
7. Open Google Map picker.
8. User searches address or taps map.
9. Reverse geocoding detects address.
10. User confirms.
11. Save pickup data to order draft.
```

Saved pickup fields:

```ts
from_city_id
from_city_name
from_city_requires_district

from_district_id
from_district_name

pickup_address
pickup_lat
pickup_lng
```

## Dropoff

When user taps:

```text
Qayerga?
```

Flow:

```text
1. Open city selector.
2. User searches city/region.
3. User selects city.
4. If selected city requires district, open district selector.
5. User searches district.
6. User selects district.
7. Open Google Map picker.
8. User searches address or taps map.
9. Reverse geocoding detects address.
10. User confirms.
11. Save dropoff data to order draft.
```

Saved dropoff fields:

```ts
to_city_id
to_city_name
to_city_requires_district

to_district_id
to_district_name

dropoff_address
dropoff_lat
dropoff_lng
```

---

# 5. Toshkent shahri district rule

If selected city has:

```ts
requires_district === false
```

then skip district selector.

Example:

```text
Toshkent shahri → directly open Google Map picker
```

For all other cities/regions where:

```ts
requires_district === true
```

district is required before map picker.

If user tries to continue without district, show:

```text
Tumanni tanlang
```

---

# 6. City selector

Create or update:

```text
src/components/location/CitySelector.tsx
```

UI text:

```text
Qayerdan?
Qayerga?
Qidirish
Xarita
Avval shaharni tanlang, keyin xaritada aniq manzilni belgilang.
Shahar topilmadi
Shaharlar yuklanmoqda...
Shaharlarni yuklab bo‘lmadi
```

Rules:

```text
Use backend GET /api/v1/cities.
Support search.
Search by name_uz, name_ru, region.
Case-insensitive.
Trim query.
Partial match.
Debounce search 250–400 ms.
```

If user taps `Xarita` before selecting city, show:

```text
Avval shaharni tanlang
```

Do not open map without city.

City row must show:

```text
city name
region/type description
chevron
```

---

# 7. District selector

Create or update:

```text
src/components/location/DistrictSelector.tsx
```

UI text:

```text
Tumanni tanlang
Tuman qidirish
Keyin xaritada aniq manzilni belgilang.
Tuman topilmadi
Tumanlar yuklanmoqda...
Tumanlarni yuklab bo‘lmadi
```

Rules:

```text
Use backend GET /api/v1/cities/{city_id}/districts.
Support search.
Search by name_uz and name_ru.
Case-insensitive.
Trim query.
Partial match.
Debounce search 250–400 ms.
```

If selected city does not require district, do not show this screen.

---

# 8. Google Map picker and reverse geocoding

Create or update:

```text
src/components/maps/GoogleMapPicker.tsx
```

Map picker must work for both:

```text
pickup
dropoff
```

UI text:

```text
Olib ketish joyini belgilang
Yetkazish joyini belgilang
Manzil qidirish
Xaritadan belgilang
Tanlangan manzil
Nuqtani tanlang
Tasdiqlash
Bekor qilish
Manzil topilmadi
Xarita yuklanmadi
Google Maps API kaliti topilmadi
```

Required behavior:

```text
Show full-screen Google Map.
Show search input.
Show back button.
Allow user to tap map.
Move marker to selected point.
Run reverse geocoding after marker changes.
Show detected address in bottom sheet.
Allow user to confirm once coordinates are selected.
```

If reverse geocoding fails:

```text
Keep selected coordinates.
Show fallback:
Tanlangan nuqta: <lat>, <lng>
Allow confirmation.
```

Do not block order creation because of reverse geocoding failure.

---

# 9. Manual address fallback

Map selection is preferred, but order creation must still work if Google Maps fails.

If map fails to load, show:

```text
Xarita yuklanmadi
Manzilni qo‘lda kiriting
```

Allow user to manually enter:

```text
pickup_address
dropoff_address
```

Coordinates can stay null.

Order creation should still work if backend allows optional coordinates.

Do not make Google Maps mandatory.

---

# 10. Address editing after map selection

After reverse geocoding fills address, user must be able to edit address manually later.

Important rule:

```text
district_id comes from DB selection
address text comes from Google or manual input
coordinates come from Google Map picker
```

Do not auto-create districts from Google.

Do not auto-change selected district based on Google.

Optional soft warning:

```text
Tanlangan nuqta tanlangan tumanga mos kelmasligi mumkin
```

Buttons:

```text
Baribir davom etish
Qayta tanlash
```

---

# 11. Order draft type

Update client order draft type/state:

```ts
type OrderDraft = {
  from_city_id?: string
  from_city_name?: string
  from_city_requires_district?: boolean

  from_district_id?: string | null
  from_district_name?: string | null

  to_city_id?: string
  to_city_name?: string
  to_city_requires_district?: boolean

  to_district_id?: string | null
  to_district_name?: string | null

  pickup_address?: string
  pickup_lat?: number | null
  pickup_lng?: number | null

  dropoff_address?: string
  dropoff_lat?: number | null
  dropoff_lng?: number | null

  sender_phone?: string
  receiver_phone?: string
  cargo_photo_url?: string
  comment?: string
}
```

Do not add:

```text
cargo_type
weight
size
distance
duration
route_polyline
```

---

# 12. Route summary screen

Create or update the route summary screen.

Title:

```text
Yo‘nalish
```

Pickup section:

```text
Olib ketish
<pickup_address>
<from_city_name>
<from_district_name if exists>
Xaritada belgilangan / Xaritada belgilanmagan
```

Dropoff section:

```text
Yetkazish
<dropoff_address>
<to_city_name>
<to_district_name if exists>
Xaritada belgilangan / Xaritada belgilanmagan
```

Buttons:

```text
O‘zgartirish
Saqlash
```

Do not show:

```text
distance
duration
route line
price by distance
```

On `Saqlash`, continue to order details form.

---

# 13. Order details form

After route summary, ask for:

```text
Yuboruvchi telefon raqami
Qabul qiluvchi telefon raqami
Posilka rasmi
Izoh
```

UX improvement:

```text
Default sender_phone should be current logged-in user phone.
User can edit it.
receiver_phone is required.
cargo_photo_url is required for MVP.
comment is optional.
```

If cargo photo not uploaded, disable publish/review continuation and show:

```text
Posilka rasmini yuklang
```

Do not ask for:

```text
Yuk turi
Og‘irligi
Hajmi
O‘lchami
```

---

# 14. Suggested price UX

After both cities are selected, call:

```http
GET /api/v1/route-tariffs/suggested-price?from_city_id=...&to_city_id=...
```

If price exists, show:

```text
Tavsiya etilgan narx: 60 000 so‘m
Bu tavsiya narx. Haydovchilar o‘z taklifini yuboradi.
```

If price is null, show:

```text
Narx haydovchi bilan kelishiladi
Haydovchilar o‘z taklifini yuboradi.
```

Do not calculate price using map distance.

Do not use district for tariff in this task.

---

# 15. Order review screen

Review screen must show:

```text
Yo‘nalish
Olib ketish manzili
Yetkazish manzili
Telefon raqamlar
Posilka rasmi
Tavsiya etilgan narx
Izoh
```

Show map status:

```text
Olib ketish joyi xaritada belgilangan
Yetkazish joyi xaritada belgilangan
```

or:

```text
Xaritada belgilanmagan
```

Button:

```text
Buyurtmani e’lon qilish
```

Secondary:

```text
Tahrirlash
```

---

# 16. Order create payload

When publishing order, send only MVP fields:

```ts
{
  from_city_id,
  from_district_id,
  to_city_id,
  to_district_id,

  pickup_address,
  pickup_lat,
  pickup_lng,

  dropoff_address,
  dropoff_lat,
  dropoff_lng,

  sender_phone,
  receiver_phone,
  cargo_photo_url,
  comment
}
```

Do not send undefined values if backend rejects them.

If district is not required, send null or omit according to current backend contract.

---

# 17. Publish success and waiting state

After successful publish, show success state:

```text
Buyurtma e’lon qilindi
Haydovchilardan takliflar kutilmoqda
Taklif kelganda sizga xabar beramiz
```

Button:

```text
Buyurtmalarimga o‘tish
```

Order detail empty state when no bids:

```text
Hozircha takliflar yo‘q
Haydovchilar taklif yuborishi bilan shu yerda ko‘rasiz
```

Add simple timeline:

```text
E’lon qilindi
Takliflar kutilmoqda
Haydovchi tanlanadi
Yetkaziladi
Tasdiqlanadi
```

---

# 18. Bids comparison UX

When bids exist, show bid cards with:

```text
Haydovchi ismi
Avtomobil modeli
Avtomobil raqami
Reyting
Taklif narxi
Izoh
```

Button:

```text
Shu haydovchini tanlash
```

Do not show chat.

Do not show online payment.

If driver phone is not allowed before selection, do not show it.

---

# 19. Select driver confirmation

Before selecting driver, show confirmation modal:

```text
Haydovchini tanlaysizmi?
Tanlaganingizdan keyin boshqa takliflar yopiladi.
```

Buttons:

```text
Tanlash
Bekor qilish
```

On confirm:

```text
Call select-driver endpoint.
Refresh order detail.
Show accepted/selected driver state.
```

---

# 20. Selected driver order detail

After driver selected, client sees:

```text
Haydovchi ismi
Avtomobil modeli
Avtomobil raqami
Reyting
Yakuniy narx
Status
```

If backend provides selected driver phone, show it only after accepted status:

```text
Haydovchi telefoni
```

Optional call button is allowed only after driver is selected:

```text
Qo‘ng‘iroq qilish
```

Do not show chat.

---

# 21. Order status timeline

Show client-friendly status timeline:

```text
E’lon qilindi
Takliflar bor
Haydovchi tanlandi
Olib ketildi
Yo‘lda
Yetkazildi
Tasdiqlandi
```

Backend status labels:

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

Use Uzbek labels everywhere.

Do not show raw backend statuses to user.

---

# 22. Delivery confirmation UX

If order.status is:

```text
delivered
```

show button:

```text
Yetkazilganini tasdiqlash
```

Before confirm, show modal:

```text
Posilka yetib keldimi?
Tasdiqlaganingizdan keyin buyurtma yakunlanadi.
```

Buttons:

```text
Tasdiqlash
Bekor qilish
```

On confirm success, show rating flow.

No OTP.

No QR.

No proof photo.

---

# 23. Rating flow

After client confirms delivery, show rating screen/modal:

```text
Haydovchini baholang
1 dan 5 gacha baho bering
Izoh qoldiring
Bahoni yuborish
Keyinroq
```

Rules:

```text
rating must be 1 to 5 if submitted
comment optional
rating can be skipped with "Keyinroq" if backend allows
```

If backend requires rating endpoint separately, call it only when user submits.

Do not block confirmed order if rating is skipped unless backend requires rating.

---

# 24. Cancel order UX

Show cancel button only when allowed.

Client can cancel in:

```text
draft
published
bidding
accepted
```

For `accepted`, show stronger confirmation:

```text
Haydovchi tanlangan. Buyurtmani bekor qilmoqchimisiz?
```

Do not allow normal cancel button after:

```text
picked_up
in_transit
delivered
confirmed
```

After picked_up or later, show:

```text
Muammo haqida xabar berish
```

instead of cancel.

Cancel modal:

```text
Buyurtmani bekor qilasizmi?
Bu amalni ortga qaytarib bo‘lmaydi.
```

Buttons:

```text
Bekor qilish
Ortga
```

---

# 25. Dispute UX

Since dispute exists in MVP, implement minimal client dispute UI.

Show dispute option for active/problematic orders:

```text
Muammo haqida xabar berish
```

Dispute screen/modal:

```text
Muammo turi
Izoh
Yuborish
```

Reason options:

```text
Haydovchi kelmadi
Posilka kechikdi
Narx bo‘yicha kelishmovchilik
Boshqa muammo
```

Do not add chat.

Do not add complex support center.

After submit:

```text
Nizo ochildi
Operatorlar muammoni ko‘rib chiqadi
```

If dispute endpoint is not connected yet, create API adapter placeholder and TODO, but keep UI ready.

---

# 26. Notifications click behavior

Notifications screen must not be passive only.

Notification card should open related order detail if it has:

```text
order_id
```

Behavior:

```text
Tap notification.
Mark as read if endpoint exists.
Navigate to related order detail.
```

Notification empty state:

```text
Hozircha bildirishnomalar yo‘q
```

Client notification examples:

```text
Yangi taklif keldi
Haydovchi tanlandi
Posilka olib ketildi
Posilka yo‘lda
Posilka yetkazildi
Buyurtma tasdiqlandi
Nizo ochildi
```

---

# 27. Loading, error, empty states

Every API screen must have:

```text
loading state
error state
empty state
retry button
```

Uzbek texts:

```text
Yuklanmoqda...
Xatolik yuz berdi
Qayta urinib ko‘ring
Ma’lumot topilmadi
Internet aloqasi yo‘q
Ruxsat yo‘q
```

Known backend errors map to Uzbek:

```ts
ROLE_MISMATCH: "Bu telefon raqam boshqa rolda ro‘yxatdan o‘tgan"
OTP_INVALID: "Kod noto‘g‘ri"
OTP_EXPIRED: "Kod muddati tugagan"
DISTRICT_REQUIRED: "Tumanni tanlang"
DISTRICT_CITY_MISMATCH: "Tuman tanlangan shaharga tegishli emas"
CITY_INACTIVE: "Tanlangan shahar faol emas"
DISTRICT_INACTIVE: "Tanlangan tuman faol emas"
DRIVER_NOT_APPROVED: "Haydovchi tasdiqlanmagan"
FORBIDDEN: "Ruxsat yo‘q"
UNAUTHORIZED: "Qayta tizimga kiring"
```

Do not show raw English backend errors unless there is no known mapping.

---

# 28. API modules to update

Create/update:

```text
src/api/client-orders.api.ts
src/api/cities.api.ts
src/api/districts.api.ts
src/api/notifications.api.ts
src/api/files.api.ts
```

Required client order functions:

```ts
createOrder(payload)
publishOrder(orderId)
getClientOrders(params)
getClientOrderDetail(orderId)
getOrderBids(orderId)
selectDriver(orderId, bidId)
cancelOrder(orderId)
confirmOrder(orderId)
rateOrder(orderId, payload)
openDispute(orderId, payload)
```

If backend endpoint names differ, update only API adapter.

Do not spread endpoint URLs across UI components.

---

# 29. UI quality rules

Do not break the current design.

Important:

```text
No overlapping text
No broken safe area
No huge bottom navigation covering content
No Russian UI text
No English UI text
No raw backend status text
No unnecessary screens
No extra payment/chat/tracking features
```

Keep UI clean, mobile-friendly, and similar to the current Figma-made style.

---

# 30. Manual QA checklist

## Auth

```text
Client login works.
Existing token routes to client home.
Expired token refresh works.
Refresh failure logs out.
Driver role does not enter client screens.
```

## Location

```text
Qayerdan? opens city selector.
City search works.
District selector opens if required.
Toshkent skips district selector.
Google map picker opens.
Reverse geocoding fills address.
Manual address fallback works if map fails.
Qayerga? works the same.
```

## Order creation

```text
Suggested price displays correctly.
Sender phone defaults to user phone.
Receiver phone required.
Cargo photo required.
Review screen shows correct route, district, address, and map status.
Order publish works.
```

## Bids

```text
No bids empty state works.
Bids list works.
Select driver modal appears.
Selecting driver refreshes order detail.
```

## Status

```text
Timeline displays correct Uzbek labels.
Delivered order shows confirm button.
Confirm modal works.
Rating flow appears after confirm.
```

## Cancel/dispute

```text
Cancel button appears only in allowed statuses.
After picked_up, dispute button appears instead.
Dispute form submits or shows TODO if endpoint missing.
```

## Notifications

```text
Notifications list loads.
Empty state works.
Tap notification opens related order detail.
```

---

# 31. Final report

After implementation, stop and report:

```text
1. Files changed
2. Auth role routing status
3. Location flow status
4. City/district search status
5. Map/reverse geocoding status
6. Order creation validation status
7. Suggested price UX status
8. Bids/select driver UX status
9. Cancel/dispute UX status
10. Notification click behavior status
11. Manual QA result
12. Known TODOs
```

Do not continue to unrelated features.
