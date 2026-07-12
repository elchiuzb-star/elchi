# Elchi Mobile App — Client Pickup/Dropoff Location Selector Integration

You are working on the **Elchi mobile frontend** project.

Frontend stack:

```text
Vite
React
TypeScript
Google Maps
```

Your task is to improve the **client-side location selection flow** for order creation.

Focus only on the user/client side.

Do not redesign the whole app.

Do not add extra features.

Do not change the approved MVP logic.

---

# 1. Goal

Implement a clean and working location selection flow for both:

```text
Qayerdan?
Qayerga?
```

Both pickup and dropoff must support:

```text
city/region search
district search when required
Google Map pin selection
reverse geocoding
automatic address detection
saving coordinates into order draft
```

All visible UI text must be in Uzbek.

---

# 2. MVP rules that must not change

Do not implement:

```text
online payment
wallet
chat
driver live tracking
route calculation
distance-based pricing
Directions API
Distance Matrix API
cargo type
cargo weight
cargo size
driver departure time
driver capacity
pickup proof
delivery proof
OTP delivery confirmation
QR code
```

Google Maps must be used only for:

```text
selecting pickup coordinate
selecting dropoff coordinate
reverse geocoding selected point into address text
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

# 3. Required flow

## Pickup flow

When client taps:

```text
Olib ketish joyi
```

or:

```text
Qayerdan?
```

open location selector in pickup mode.

Flow:

```text
1. Show city/region list.
2. User searches and selects city/region.
3. If selected city requires district, show district list.
4. User searches and selects district.
5. Open Google Map picker.
6. User searches address or taps map.
7. Marker is placed.
8. Reverse geocoding detects address.
9. User confirms.
10. Save pickup data into order draft.
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

---

## Dropoff flow

When client taps:

```text
Qayerga?
```

open location selector in dropoff mode.

Flow:

```text
1. Show city/region list.
2. User searches and selects city/region.
3. If selected city requires district, show district list.
4. User searches and selects district.
5. Open Google Map picker.
6. User searches address or taps map.
7. Marker is placed.
8. Reverse geocoding detects address.
9. User confirms.
10. Save dropoff data into order draft.
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

# 4. Toshkent shahri rule

If selected city is:

```text
Toshkent shahri
```

and:

```text
requires_district = false
```

then district selector must be skipped.

Example:

```text
Qayerdan? → Toshkent shahri → Google Map picker
```

or:

```text
Qayerga? → Toshkent shahri → Google Map picker
```

For other cities/regions where:

```text
requires_district = true
```

district selection is required before opening map picker.

---

# 5. City selector UI

Create or update reusable component:

```text
src/components/location/CitySelector.tsx
```

Props:

```ts
type CitySelectorProps = {
  mode: "pickup" | "dropoff"
  title: string
  onSelectCity: (city: City) => void
  onBack: () => void
}
```

Screen title:

For pickup:

```text
Qayerdan?
```

For dropoff:

```text
Qayerga?
```

Search placeholder:

```text
Qidirish
```

Helper text:

```text
Avval shaharni tanlang, keyin xaritada aniq manzilni belgilang.
```

Right button:

```text
Xarita
```

But important rule:

```text
If no city is selected yet, tapping "Xarita" should show message:
"Avval shaharni tanlang"
```

City row design:

```text
location icon
city name
region/description
chevron
```

Example city rows:

```text
Toshkent
Toshkent shahri

Nurafshon
Toshkent viloyati

Samarqand
Samarqand viloyati

Andijon
Andijon viloyati

Farg‘ona
Farg‘ona viloyati
```

Load cities from backend:

```http
GET /api/v1/cities
```

Do not hardcode final city list.

Temporary fallback is allowed only if backend is not reachable during development.

---

# 6. City search behavior

City search must work.

Rules:

```text
search by name_uz
search by name_ru if exists
search by region if exists
case-insensitive
trim spaces
partial match
```

Example:

```text
tosh
Toshkent
samar
Самарканд
fargo
```

Implementation:

```text
Prefer backend search query if supported.
If backend returns all cities, filter locally.
Debounce input by 250–400 ms.
Show empty state when no city found.
```

Empty state text:

```text
Shahar topilmadi
```

---

# 7. District selector UI

Create:

```text
src/components/location/DistrictSelector.tsx
```

Props:

```ts
type DistrictSelectorProps = {
  mode: "pickup" | "dropoff"
  city: City
  onSelectDistrict: (district: District) => void
  onBack: () => void
}
```

Screen title:

```text
Tumanni tanlang
```

Search placeholder:

```text
Tuman qidirish
```

Helper text:

```text
Keyin xaritada aniq manzilni belgilang.
```

District rows:

```text
location icon
district name
city name
chevron
```

Load districts:

```http
GET /api/v1/cities/{city_id}/districts
```

---

# 8. District search behavior

District search must work.

Rules:

```text
search by name_uz
search by name_ru if exists
case-insensitive
trim spaces
partial match
```

Implementation:

```text
Prefer backend search if supported.
If backend returns all districts, filter locally.
Debounce input by 250–400 ms.
Show empty state when no district found.
```

Empty state text:

```text
Tuman topilmadi
```

If selected city does not require district:

```text
Do not show district selector.
Open map picker directly.
```

---

# 9. Google Map picker

Create or update:

```text
src/components/maps/GoogleMapPicker.tsx
```

Props:

```ts
type GoogleMapPickerProps = {
  mode: "pickup" | "dropoff"
  city: City
  district?: District | null
  initialLat?: number | null
  initialLng?: number | null
  initialAddress?: string
  onConfirm: (location: {
    lat: number
    lng: number
    address: string
  }) => void
  onBack: () => void
}
```

Screen title:

Pickup:

```text
Olib ketish joyini belgilang
```

Dropoff:

```text
Yetkazish joyini belgilang
```

Search placeholder:

```text
Manzil qidirish
```

Bottom sheet labels:

```text
Tanlangan manzil
Nuqtani tanlang
Tasdiqlash
```

---

# 10. Google Map picker behavior

The map picker must support:

```text
Google Maps rendering
address search
tap map to place marker
reverse geocoding
selected address preview
confirm button
back button
```

Minimum required behavior:

```text
User opens map.
User taps map.
Marker moves to tapped position.
Reverse geocoding runs.
Address text appears.
User taps "Tasdiqlash".
Selected location is saved.
```

Preferred behavior:

```text
User can search address with Google Places Autocomplete.
Selecting a suggestion moves marker.
Reverse geocoding confirms address.
```

Do not use:

```text
Directions API
Distance Matrix API
route line
distance calculation
duration calculation
```

---

# 11. Reverse geocoding

When marker position changes:

```text
1. Get lat/lng.
2. Use Google Geocoder reverse geocoding.
3. If formatted_address exists, show it.
4. If address is not found, show:
   "Manzil topilmadi"
5. Allow user to confirm only after a coordinate is selected.
```

If reverse geocoding fails:

```text
Keep coordinates.
Show fallback address:
"Tanlangan nuqta: <lat>, <lng>"
```

Do not block the user if Google cannot detect the exact address.

---

# 12. District mismatch warning

If possible, compare Google returned address text with selected district name.

If selected district name is not found in returned address, show soft warning:

```text
Tanlangan nuqta tanlangan tumanga mos kelmasligi mumkin
```

Buttons:

```text
Baribir davom etish
Qayta tanlash
```

This warning is optional.

Do not block MVP if Google address components are unreliable.

Important:

```text
The selected district_id from backend is the source of truth.
Google reverse geocoding only fills address text.
```

Do not create or change district based on Google result automatically.

---

# 13. Order draft state

Update order draft type/state.

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

# 14. Saving pickup selection

After pickup map confirmation:

```ts
setOrderDraft(prev => ({
  ...prev,
  from_city_id: selectedCity.id,
  from_city_name: selectedCity.name_uz,
  from_city_requires_district: selectedCity.requires_district,

  from_district_id: selectedDistrict?.id ?? null,
  from_district_name: selectedDistrict?.name_uz ?? null,

  pickup_address: location.address,
  pickup_lat: location.lat,
  pickup_lng: location.lng
}))
```

Then return to Map Home or order creation screen.

---

# 15. Saving dropoff selection

After dropoff map confirmation:

```ts
setOrderDraft(prev => ({
  ...prev,
  to_city_id: selectedCity.id,
  to_city_name: selectedCity.name_uz,
  to_city_requires_district: selectedCity.requires_district,

  to_district_id: selectedDistrict?.id ?? null,
  to_district_name: selectedDistrict?.name_uz ?? null,

  dropoff_address: location.address,
  dropoff_lat: location.lat,
  dropoff_lng: location.lng
}))
```

Then return to Map Home or route summary screen.

---

# 16. Map Home behavior

On client map home, bottom sheet should show:

If pickup not selected:

```text
Olib ketish joyi
```

If pickup selected:

```text
<pickup_address>
<from_city_name>, <from_district_name if exists>
```

If dropoff not selected:

```text
Qayerga?
```

If dropoff selected:

```text
<dropoff_address>
<to_city_name>, <to_district_name if exists>
```

When both pickup and dropoff are selected, show button:

```text
Yo‘nalishni ko‘rish
```

Button opens route summary screen.

---

# 17. Route summary screen

Create or update route summary.

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
```

Dropoff section:

```text
Yetkazish
<dropoff_address>
<to_city_name>
<to_district_name if exists>
```

Button:

```text
Saqlash
```

On save, continue to the next order creation step:

```text
sender/receiver phone
parcel photo
comment
review
publish
```

Do not show:

```text
distance
duration
route line
price by distance
```

---

# 18. Order create payload

When creating order, send:

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

If district is not required, send:

```ts
from_district_id: null
```

or omit it if backend prefers omitted optional fields.

Use the backend contract already implemented.

Do not send undefined values if backend strict validation fails.

---

# 19. Suggested price

After both cities are selected, call suggested price API:

```http
GET /api/v1/route-tariffs/suggested-price?from_city_id=...&to_city_id=...
```

Suggested price remains city-level.

Do not use district for tariff yet.

Show:

```text
Tavsiya etilgan narx: 60 000 so‘m
```

If null:

```text
Narx haydovchi bilan kelishiladi
```

Do not calculate price from Google Maps.

---

# 20. API modules

Create or update:

```text
src/api/cities.api.ts
src/api/districts.api.ts
```

Required functions:

```ts
getCities(params?: {
  search?: string
  page?: number
  limit?: number
})

getDistricts(cityId: string, params?: {
  search?: string
  page?: number
  limit?: number
})
```

Types:

```ts
type City = {
  id: string
  name_uz: string
  name_ru?: string | null
  region?: string | null
  type?: "city" | "region" | "republic"
  requires_district: boolean
  is_active: boolean
}

type District = {
  id: string
  city_id: string
  name_uz: string
  name_ru?: string | null
  is_active: boolean
}
```

Handle backend response safely if data is returned as:

```ts
data.items
```

or direct array.

---

# 21. Error and empty states

Use Uzbek texts.

City loading:

```text
Shaharlar yuklanmoqda...
```

City error:

```text
Shaharlarni yuklab bo‘lmadi
```

No city:

```text
Shahar topilmadi
```

District loading:

```text
Tumanlar yuklanmoqda...
```

District error:

```text
Tumanlarni yuklab bo‘lmadi
```

No district:

```text
Tuman topilmadi
```

Map loading:

```text
Xarita yuklanmoqda...
```

Map error:

```text
Xarita yuklanmadi
```

Google API key missing:

```text
Google Maps API kaliti topilmadi
```

Coordinate not selected:

```text
Nuqtani tanlang
```

Reverse geocoding failed:

```text
Manzil topilmadi
```

---

# 22. UI quality rules

The UI must match the clean style of the uploaded screenshot.

Important:

```text
No overlapping text
No broken spacing
No tiny labels
No Russian visible text
No bottom navigation inside selector/map picker
No unnecessary buttons
No route line
No distance/duration block
```

The city selector must look clean:

```text
top app bar
back button
title
Xarita button
search field
helper text
city list
```

The district selector must look similar.

The map picker must be full-screen and mobile friendly.

---

# 23. Manual QA

## Pickup selector

```text
1. Login as client.
2. Tap "Olib ketish joyi".
3. City selector opens.
4. Search "Samarqand".
5. Select Samarqand.
6. District selector opens.
7. Search "Urgut".
8. Select Urgut.
9. Google Map picker opens.
10. Tap map.
11. Address is detected.
12. Confirm.
13. Pickup data is saved.
```

## Dropoff selector

```text
1. Tap "Qayerga?"
2. Search "Toshkent".
3. Select Toshkent shahri.
4. District selector is skipped.
5. Google Map picker opens.
6. Tap map.
7. Address is detected.
8. Confirm.
9. Dropoff data is saved.
```

## Search checks

```text
City search works.
District search works.
Google map search works if Places autocomplete implemented.
```

## Order payload

```text
Order payload includes:
from_city_id
from_district_id
to_city_id
to_district_id
pickup_address
pickup_lat
pickup_lng
dropoff_address
dropoff_lat
dropoff_lng
```

## No extra features

```text
No distance calculation.
No route line.
No live tracking.
No price by distance.
```

---

# 24. Final report

After implementation, stop and report:

```text
1. Files changed
2. City selector implemented
3. District selector implemented
4. Pickup flow connected
5. Dropoff flow connected
6. Google Map picker connected
7. Reverse geocoding working status
8. Search working status
9. Order draft fields updated
10. Order create payload updated
11. Manual QA result
12. Known TODOs
```

Do not continue to unrelated features.
