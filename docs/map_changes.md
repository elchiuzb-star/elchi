# Elchi — Add Districts + Google Maps Reverse Geocoding + District-Based Matching

You are working on the Elchi project.

This update changes the route/location model from only city-level matching to:

```text
City / Region
↓
District
↓
Exact Google Maps pin + address
```

Important: keep the approved MVP logic unchanged.

This update affects:

```text
Backend:
- cities
- new districts
- client orders
- driver routes
- matching/order offers
- schemas/validation
- seed data
- tests

Frontend:
- location selection flow
- district selector
- Google Maps picker
- reverse geocoding
- order creation payload
- driver route creation payload
```

Do not add extra product features.

---

# 1. MVP rules that must remain unchanged

Main MVP flow remains:

```text
Client creates order
↓
Approved driver with matching route sees the order
↓
Driver sends bid
↓
Client selects one driver
↓
Selected driver updates statuses
↓
Client confirms delivery
↓
Client rates driver
```

Payment remains:

```text
Cash only
```

Do not implement:

```text
online payment
Click
Payme
card payment
wallet
escrow
P2P
chat
live GPS tracking
driver live location
route calculation
distance-based pricing
Distance Matrix API
Directions API
Routes API
Navigation SDK
delivery OTP
QR
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

Google Maps is only for:

```text
pickup pin selection
dropoff pin selection
reverse geocoding
human-readable address detection
read-only map preview
```

---

# 2. New location logic

Previously the system used only:

```text
from_city_id
to_city_id
```

Now it must support:

```text
from_city_id
from_district_id

to_city_id
to_district_id
```

Plus exact map fields:

```text
pickup_address
pickup_lat
pickup_lng

dropoff_address
dropoff_lat
dropoff_lng
```

Business decision:

```text
Every service city/region has districts, except Toshkent shahri.
Toshkent shahri does not require district selection.
```

Example:

```text
Samarqand viloyati → Toshkent shahri
from_district_id = Samarqand shahri or Urgut or Pastdarg‘om
to_district_id = null
```

Example:

```text
Farg‘ona viloyati → Andijon viloyati
from_district_id = Qo‘qon or Marg‘ilon or Farg‘ona shahri
to_district_id = Andijon shahri or Asaka
```

Important:

```text
District is used for matching.
Google Maps coordinates are used for exact pickup/dropoff address.
```

Do not use coordinates for matching in this update.

---

# 3. Backend city model update

Keep the existing `cities` table if it already exists.

Do not rename `cities` to another table unless absolutely necessary.

Add these fields to `cities` if missing:

```text
type
requires_district
display_order
created_at
updated_at
```

Recommended `type` values:

```text
city
region
republic
```

Rules:

```text
Toshkent shahri:
  type = city
  requires_district = false

All other regions/cities:
  requires_district = true
```

Examples:

```text
Toshkent shahri       type=city      requires_district=false
Samarqand viloyati    type=region    requires_district=true
Farg‘ona viloyati     type=region    requires_district=true
Qoraqalpog‘iston      type=republic  requires_district=true
```

---

# 4. Add districts table

Create new table:

```text
districts
```

Fields:

```text
id
city_id
name_uz
name_ru
is_active
display_order
created_at
updated_at
```

Rules:

```text
districts.city_id references cities.id
district name must be unique within the same city
district name comparison should be case-insensitive if possible
is_active defaults to true
hard delete is not allowed
admin should use is_active=false instead of delete
```

Recommended DB constraint:

```text
Unique city_id + normalized lower(name_uz)
```

If DB-level case-insensitive unique is difficult, enforce duplicate check at service level.

---

# 5. District seed data

Add seed script:

```text
scripts/seed_districts.py
```

If scripts folder does not exist, create it.

Seed must be idempotent.

Running seed twice must not create duplicates.

Add districts for all service regions/cities except Toshkent shahri.

For Toshkent shahri:

```text
No district seed is required.
requires_district=false.
```

For other regions, seed known districts.

At minimum, seed enough realistic data for MVP testing.

Example structure:

```python
DISTRICTS = {
    "Samarqand viloyati": [
        "Samarqand shahri",
        "Kattaqo‘rg‘on",
        "Urgut",
        "Pastdarg‘om",
        "Bulung‘ur",
        "Jomboy",
        "Ishtixon",
        "Narpay",
        "Payariq",
        "Qo‘shrabot",
        "Toyloq"
    ],
    "Farg‘ona viloyati": [
        "Farg‘ona shahri",
        "Qo‘qon",
        "Marg‘ilon",
        "Rishton",
        "Oltiariq",
        "Beshariq",
        "Dang‘ara",
        "Uchko‘prik",
        "Quva",
        "Yozyovon"
    ]
}
```

Use correct Uzbek names where possible.

Do not block implementation if full Uzbekistan district list is incomplete.

But make the seed system easy to extend.

---

# 6. District API endpoints

Add public/authenticated endpoint:

```http
GET /api/v1/cities/{city_id}/districts
```

Access:

```text
Public or authenticated
```

Query params:

```text
search optional
is_active optional default true
page optional
limit optional
```

Response:

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "uuid",
        "city_id": "uuid",
        "name_uz": "Urgut",
        "name_ru": "Ургут",
        "is_active": true
      }
    ],
    "pagination": {
      "page": 1,
      "limit": 20,
      "total": 1,
      "total_pages": 1
    }
  }
}
```

If city does not require district:

```json
{
  "success": true,
  "data": {
    "items": [],
    "pagination": {
      "page": 1,
      "limit": 20,
      "total": 0,
      "total_pages": 0
    }
  },
  "message": "District selection is not required for this city"
}
```

---

# 7. Admin district endpoints

Add admin endpoints:

```http
POST /api/v1/admin/districts
GET /api/v1/admin/districts
PATCH /api/v1/admin/districts/{district_id}
```

Permissions:

```text
operator:
  can view districts

admin:
  can create/update districts

super_admin:
  can create/update districts
```

Client and driver cannot access admin district endpoints.

Create district request:

```json
{
  "city_id": "uuid",
  "name_uz": "Urgut",
  "name_ru": "Ургут",
  "is_active": true
}
```

Validation:

```text
city_id required
city must exist
name_uz required
name_uz unique within city
Toshkent shahri can have districts but they are not required; recommended not to create them for MVP
```

Patch district request:

```json
{
  "name_uz": "Urgut",
  "name_ru": "Ургут",
  "is_active": true
}
```

Write audit logs if audit service exists:

```text
district_created
district_updated
```

---

# 8. Order model update

Update `orders` table.

Add nullable fields:

```text
from_district_id
to_district_id
pickup_lat
pickup_lng
dropoff_lat
dropoff_lng
```

Foreign keys:

```text
from_district_id references districts.id nullable
to_district_id references districts.id nullable
```

Keep existing fields:

```text
from_city_id
to_city_id
pickup_address
dropoff_address
sender_phone
receiver_phone
cargo_photo_url
comment
suggested_price
final_price
status
```

Do not add removed fields:

```text
cargo_type
weight
size
distance
duration
route_polyline
```

---

# 9. Order validation rules

When client creates an order:

```text
from_city_id required
to_city_id required
from_city_id != to_city_id
both cities must exist
both cities must be active
```

District validation:

```text
If from_city.requires_district = true:
  from_district_id is required
  from_district_id must belong to from_city_id
  from_district must be active

If from_city.requires_district = false:
  from_district_id may be null
  if provided, it must belong to from_city_id and be active

If to_city.requires_district = true:
  to_district_id is required
  to_district_id must belong to to_city_id
  to_district must be active

If to_city.requires_district = false:
  to_district_id may be null
  if provided, it must belong to to_city_id and be active
```

Coordinate validation:

```text
pickup_lat must be between -90 and 90
pickup_lng must be between -180 and 180
dropoff_lat must be between -90 and 90
dropoff_lng must be between -180 and 180

If pickup_lat is provided, pickup_lng is required.
If pickup_lng is provided, pickup_lat is required.

If dropoff_lat is provided, dropoff_lng is required.
If dropoff_lng is provided, dropoff_lat is required.
```

Coordinates are optional.

Order creation must still work with manual address only.

---

# 10. Order create payload

Update client order create payload:

```json
{
  "from_city_id": "uuid",
  "from_district_id": "uuid",
  "to_city_id": "uuid",
  "to_district_id": null,

  "pickup_address": "Urgut tumani, G‘ishtli mahallasi",
  "pickup_lat": 39.4020000,
  "pickup_lng": 67.2430000,

  "dropoff_address": "Toshkent shahri, Chilonzor 12-mavze",
  "dropoff_lat": 41.2850000,
  "dropoff_lng": 69.2030000,

  "sender_phone": "+998901234567",
  "receiver_phone": "+998909876543",
  "cargo_photo_url": "/storage/uploads/cargo_photo/example.jpg",
  "comment": "Ehtiyot bo‘lib olib boring"
}
```

If destination is Toshkent shahri:

```text
to_district_id can be null
```

If origin is Samarqand viloyati:

```text
from_district_id is required
```

---

# 11. Driver routes model update

Update `driver_routes` table.

Add nullable fields:

```text
from_district_id
to_district_id
```

Keep existing fields:

```text
driver_id
from_city_id
to_city_id
status
```

Do not add:

```text
departure_time
capacity
free_space
weight_limit
```

---

# 12. Driver route validation

When driver creates route:

```text
from_city_id required
to_city_id required
from_city_id != to_city_id
both cities must exist and be active
```

District validation:

```text
If from_city.requires_district = true:
  from_district_id is required
  from_district_id must belong to from_city_id
  from_district must be active

If from_city.requires_district = false:
  from_district_id may be null

If to_city.requires_district = true:
  to_district_id is required
  to_district_id must belong to to_city_id
  to_district must be active

If to_city.requires_district = false:
  to_district_id may be null
```

Only approved driver can create route.

Driver can create route while is_available=false, but it will not match orders until driver is available.

---

# 13. Matching logic update

Update matching/order offers.

Old matching:

```text
order.from_city_id = route.from_city_id
order.to_city_id = route.to_city_id
```

New matching:

```text
1. driver user.status = active
2. driver profile.verification_status = approved
3. driver profile.is_available = true
4. driver route.status = available
5. order.from_city_id = route.from_city_id
6. order.to_city_id = route.to_city_id
7. from district matches if city requires district
8. to district matches if city requires district
```

District matching rule:

```text
If order.from_district_id is not null:
  route.from_district_id must equal order.from_district_id

If order.to_district_id is not null:
  route.to_district_id must equal order.to_district_id

If city does not require district and both values are null:
  it is considered match
```

Example:

```text
Driver route:
Samarqand viloyati / Urgut → Toshkent shahri

Order:
Samarqand viloyati / Urgut → Toshkent shahri

Match = yes
```

Example:

```text
Driver route:
Samarqand viloyati / Samarqand shahri → Toshkent shahri

Order:
Samarqand viloyati / Urgut → Toshkent shahri

Match = no
```

This prevents all Samarqand region orders from appearing to every Samarqand → Toshkent driver.

Do not implement coordinate radius matching in this update.

Do not implement distance matching.

---

# 14. Route tariffs remain city-level for now

Keep route tariffs city-to-city only.

Do not add district-level pricing in this update.

Suggested price remains:

```text
from_city_id + to_city_id
```

Reason:

```text
District is for matching accuracy.
City-level tariff is enough for MVP suggested price.
Final price still comes from driver bid.
```

Do not calculate price from Google Maps distance.

---

# 15. Frontend location flow update

Update client order creation UX.

Flow:

```text
1. Client opens app
2. Map Home opens
3. User taps "Olib ketish joyi"
4. City list opens
5. User selects city/region
6. If selected city requires district:
   show district list
7. User selects district
8. User can tap "Xarita" to choose exact pickup pin
9. Google Maps picker opens
10. User selects pin
11. Reverse geocoding detects address
12. User confirms
13. Repeat same for "Qayerga?"
14. Route summary opens
15. Continue order creation
```

For Toshkent shahri:

```text
Skip district selection.
Go directly to map picker after city selection.
```

All UI text must be Uzbek.

---

# 16. Frontend city selector UI

When choosing pickup/dropoff city:

Screen title for pickup:

```text
Qayerdan?
```

Screen title for dropoff:

```text
Qayerga?
```

Search placeholder:

```text
Qidirish
```

Button:

```text
Xarita
```

City row examples:

```text
Toshkent shahri
Samarqand viloyati
Farg‘ona viloyati
Andijon viloyati
Qoraqalpog‘iston Respublikasi
```

Load from:

```http
GET /api/v1/cities
```

Do not hardcode city list after API integration, except fallback for dev.

---

# 17. Frontend district selector UI

After city selection, if `requires_district=true`, open district selector.

Screen title examples:

```text
Tumanni tanlang
```

Search placeholder:

```text
Tuman qidirish
```

District rows:

```text
Urgut
Samarqand shahri
Pastdarg‘om
Kattaqo‘rg‘on
```

Load from:

```http
GET /api/v1/cities/{city_id}/districts
```

If no districts found:

```text
Tumanlar topilmadi
```

If city does not require district:

```text
Skip this screen.
```

---

# 18. Google Maps picker + reverse geocoding

Create or update:

```text
src/components/maps/GoogleMapPicker.tsx
```

Map picker must support:

```text
pickup mode
dropoff mode
initial city
initial district
initial address
tap map to move marker
search address
reverse geocoding
confirm selection
cancel selection
```

UI texts:

```text
Qidirish
Xaritadan belgilang
Tanlangan manzil
Tasdiqlash
Bekor qilish
Manzil topilmadi
Nuqtani tanlang
```

Reverse geocoding logic:

```text
When user taps map:
  save lat/lng
  call Google Geocoder geocode({ location: { lat, lng } })
  if formatted_address exists:
    set selected address
  else:
    keep manually typed address or show coordinates fallback
```

Do not rely on Google reverse geocoding as the source of truth for district matching.

District source of truth is:

```text
selected district_id from DB
```

Google address is only for readable address text.

---

# 19. Reverse geocoding district mismatch warning

If possible, parse Google reverse geocoding components and detect district/locality.

If detected Google district does not look similar to selected DB district, show a soft warning:

```text
Tanlangan nuqta tanlangan tumanga mos kelmasligi mumkin
```

Buttons:

```text
Baribir davom etish
Qayta tanlash
```

This warning is optional.

Do not block MVP if district detection from Google is unreliable.

Do not auto-create districts from Google.

Do not auto-change selected district without user confirmation.

---

# 20. Route summary screen update

After pickup and dropoff are selected, show summary.

Title:

```text
Yo‘nalish
```

Pickup section:

```text
Olib ketish
<from city>
<from district if exists>
<pickup address>
Xaritada belgilangan / Xaritada belgilanmagan
```

Dropoff section:

```text
Yetkazish
<to city>
<to district if exists>
<dropoff address>
Xaritada belgilangan / Xaritada belgilanmagan
```

Button:

```text
Saqlash
```

Do not show route line.

Do not show distance.

Do not show duration.

---

# 21. Frontend order draft type update

Update order draft type:

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

Do not add cargo type, weight, size, distance, duration.

---

# 22. Frontend API modules

Create/update:

```text
src/api/cities.api.ts
src/api/districts.api.ts
src/api/client-orders.api.ts
src/api/driver.api.ts
```

Functions:

```ts
getCities(params)
getDistricts(cityId, params)
createClientOrder(payload)
createDriverRoute(payload)
```

Order payload must include district IDs.

Driver route payload must include district IDs.

---

# 23. Driver route frontend update

When driver creates route:

Flow:

```text
1. Select from city
2. If from city requires district, select from district
3. Select to city
4. If to city requires district, select to district
5. Save route
```

For Toshkent shahri:

```text
district selection skipped
district_id = null
```

Driver route payload:

```json
{
  "from_city_id": "uuid",
  "from_district_id": "uuid",
  "to_city_id": "uuid",
  "to_district_id": null
}
```

Do not add departure time.

Do not add capacity.

---

# 24. Driver feed UI update

Driver feed cards should show district names if available.

Before selected:

```text
Samarqand viloyati, Urgut → Toshkent shahri
Olib ketish hududi: Urgut
Yetkazish hududi: Toshkent shahri
Tavsiya narx: 60 000 so‘m
```

Do not show exact coordinates before driver is selected.

Do not show full private address before driver is selected.

---

# 25. Assigned order detail map

After driver is selected, assigned driver can see:

```text
pickup_address
dropoff_address
pickup_lat/lng
dropoff_lat/lng
sender_phone
receiver_phone
```

If coordinates exist, show:

```text
Xaritada ko‘rish
```

Read-only map shows:

```text
pickup marker
dropoff marker
```

Do not show:

```text
route line
distance
duration
live tracking
driver movement
```

---

# 26. Error codes

Add/use these error codes:

```text
DISTRICT_NOT_FOUND
DISTRICT_INACTIVE
DISTRICT_REQUIRED
DISTRICT_CITY_MISMATCH
CITY_REQUIRES_DISTRICT
CITY_DOES_NOT_REQUIRE_DISTRICT
VALIDATION_ERROR
FORBIDDEN
UNAUTHORIZED
NOT_FOUND
SERVER_ERROR
```

Example:

```json
{
  "success": false,
  "error": {
    "code": "DISTRICT_REQUIRED",
    "message": "District is required for selected city"
  }
}
```

---

# 27. Tests required

Add/update backend tests.

District tests:

```text
admin can create district
operator cannot create district
duplicate district within same city rejected
same district name in different city allowed
public can list active districts by city
inactive district not shown publicly
district belongs to selected city
```

Order validation tests:

```text
order requires from_district_id if from city requires district
order allows null from_district_id for Toshkent shahri
order rejects district from another city
order rejects inactive district
order accepts optional pickup/dropoff coordinates
order rejects invalid lat/lng
order still works without coordinates
```

Driver route tests:

```text
route requires district if city requires district
route allows null district for Toshkent shahri
route rejects district from another city
route rejects inactive district
route does not include departure_time
route does not include capacity
```

Matching tests:

```text
same city and same district matches
same city but different from district does not match
same city but different to district does not match
Toshkent shahri null district matches null district
unapproved driver does not match
unavailable driver does not match
blocked driver does not match
```

Frontend manual QA:

```text
city selector opens
district selector opens when required
Toshkent skips district selector
map picker opens
reverse geocoding fills address
order payload sends city_id + district_id + address + coordinates
driver route sends city_id + district_id
```

---

# 28. Manual QA checklist

## Client pickup

```text
1. Login as client.
2. Tap "Olib ketish joyi".
3. Select "Samarqand viloyati".
4. District selector opens.
5. Select "Urgut".
6. Tap "Xarita".
7. Pick point on Google Map.
8. Address is auto-detected through reverse geocoding.
9. Confirm.
10. Check draft has:
   from_city_id
   from_district_id
   pickup_address
   pickup_lat
   pickup_lng
```

## Client dropoff Toshkent

```text
1. Tap "Qayerga?"
2. Select "Toshkent shahri".
3. District selector is skipped.
4. Pick point on Google Map.
5. Confirm.
6. Check draft has:
   to_city_id
   to_district_id = null
   dropoff_address
   dropoff_lat
   dropoff_lng
```

## Matching

```text
1. Driver creates route:
   Samarqand viloyati / Urgut → Toshkent shahri
2. Client creates order:
   Samarqand viloyati / Urgut → Toshkent shahri
3. Driver sees order.
4. Client creates order:
   Samarqand viloyati / Samarqand shahri → Toshkent shahri
5. Same driver does not see this order.
```

---

# 29. Files likely to change

Backend:

```text
app/models/city.py
app/models/district.py
app/models/order.py
app/models/driver_route.py
app/schemas/city.py
app/schemas/district.py
app/schemas/order.py
app/schemas/driver_route.py
app/api/v1/cities.py
app/api/v1/admin/districts.py
app/api/v1/client/orders.py
app/api/v1/driver/routes.py
app/services/matching.py
app/services/orders.py
app/services/driver_routes.py
alembic/versions/<timestamp>_add_districts_and_order_route_districts.py
scripts/seed_districts.py
tests/
```

Frontend:

```text
src/api/cities.api.ts
src/api/districts.api.ts
src/api/client-orders.api.ts
src/api/driver.api.ts
src/components/maps/GoogleMapPicker.tsx
src/components/location/CitySelector.tsx
src/components/location/DistrictSelector.tsx
src/components/location/LocationSelector.tsx
src/types/order.ts
src/types/location.ts
src/app/App.tsx
.env.example
README.md
```

Adapt to the actual project structure.

---

# 30. Final report

After implementation, stop and report:

```text
1. Files changed
2. Migrations created
3. District table added
4. City requires_district added
5. Order district fields added
6. Driver route district fields added
7. Matching updated to district-level
8. Reverse geocoding implemented
9. Frontend location selector updated
10. Tests added/updated
11. Manual QA result
12. Seed data status
13. Known TODOs
```

Do not continue to unrelated features.
