# Elchi Mobile App — Google Maps Route Selection Flow Integration

You are working on the **Elchi mobile frontend** project.

The frontend is a separate Vite + React + TypeScript mobile web app.

Backend is a separate FastAPI project.

Your task is to implement a real Google Maps based pickup/dropoff selection flow for the **client order creation** experience.

The UX must follow a modern taxi-style map flow, similar to apps where the user opens the app, sees a map, selects pickup point, selects destination point, confirms route, then continues order creation.

Important: keep the approved MVP logic unchanged.

---

# 1. Current product context

Elchi is an MVP marketplace app for intercity parcel/small cargo delivery in Uzbekistan.

Main MVP flow:

```text
Client creates order
Drivers with matching city route see order
Drivers send price offers
Client selects one driver
Selected driver updates order status
Client confirms delivery
Client rates driver
Payment is cash only
```

Google Maps is used only for:

```text
pickup point selection
dropoff point selection
address search
reverse geocoding / automatic address detection
read-only map preview for assigned order
```

Do not use maps for matching or pricing.

---

# 2. Features that must NOT be added

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

The map is only for selecting pickup and dropoff coordinates.

---

# 3. UX goal

Implement this client flow:

```text
1. Client opens app
2. Map Home screen opens
3. Bottom sheet shows pickup and destination fields
4. Client taps pickup field
5. Location selector opens
6. Client can select from city/region list or tap "Xarita"
7. If "Xarita" is tapped, Google Map picker opens
8. Client selects exact pickup point on map
9. App automatically detects address with reverse geocoding
10. Client confirms pickup point
11. Client taps destination field
12. Client repeats the same flow for dropoff point
13. Route summary screen opens
14. Client taps "Saqlash"
15. App continues existing order creation flow:
    phone numbers
    parcel photo
    comment
    review
    publish order
```

All visible UI text must be in **Uzbek language**.

---

# 4. Environment variables

Add/update:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
VITE_GOOGLE_MAPS_API_KEY=your-google-maps-api-key
```

Create/update:

```text
.env.example
```

Do not hardcode Google API key in source code.

Do not commit real API key.

---

# 5. Package

Install Google Maps package:

```bash
npm install @react-google-maps/api
```

If the project already has another Google Maps package, use the existing package and do not install duplicates.

Do not add Yandex, Leaflet, Mapbox, or MapLibre in this task.

---

# 6. Backend coordinate support

If backend code is available in the workspace, update backend order model, schema, migration and API payload to support optional coordinates.

Add nullable fields to `orders`:

```text
pickup_lat
pickup_lng
dropoff_lat
dropoff_lng
```

Recommended DB type:

```text
DECIMAL(10, 7)
```

or current project’s numeric/float style.

Validation:

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

Coordinates must be optional.

Order creation must still work without map-selected points.

Do not add:

```text
distance
duration
route_polyline
driver_location
tracking_status
price_by_distance
```

If backend is not available in this workspace, create:

```text
docs/backend_required_changes_for_google_maps.md
```

and document exact backend changes needed.

---

# 7. Order create payload update

Frontend order creation payload must support optional coordinates:

```ts
{
  from_city_id: string
  to_city_id: string
  pickup_address: string
  dropoff_address: string
  pickup_lat?: number
  pickup_lng?: number
  dropoff_lat?: number
  dropoff_lng?: number
  sender_phone: string
  receiver_phone: string
  cargo_photo_url: string
  comment?: string
}
```

Do not send undefined fields if backend validation is strict.

Prefer omitting optional coordinates when not selected.

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

# 8. Main Map Home screen

Create or update the client home screen to behave like a map-first home.

Screen name recommendation:

```text
ClientMapHome
```

UI:

```text
Full-screen Google Map
Top safe area respected
Floating menu button
Floating current location button, optional
Bottom sheet with pickup and destination fields
```

Bottom sheet text:

```text
Olib ketish joyi
Qayerga?
```

If pickup is already selected:

```text
Olib ketish joyi
<selected pickup address>
```

If destination is already selected:

```text
Qayerga?
<selected dropoff address>
```

Primary action after both points selected:

```text
Yo‘nalishni ko‘rish
```

Rules:

```text
Do not show bottom navigation on full-screen map picker.
Do not overlap bottom sheet with map controls.
Do not make location permission mandatory.
If location permission is denied, default to Tashkent.
```

Default center:

```ts
{
  lat: 41.2995,
  lng: 69.2401
}
```

Default zoom:

```text
13
```

---

# 9. Location selector screen

When user taps pickup or destination field, open location selector.

Screen title depends on mode:

Pickup:

```text
Qayerdan?
```

Dropoff:

```text
Qayerga?
```

Search placeholder:

```text
Qidirish
```

Right-side button:

```text
Xarita
```

List should show backend cities/regions.

Use existing backend cities API:

```http
GET /api/v1/cities
```

City rows:

```text
location icon
city/region name
"Yangi" tag if needed only if already in design
chevron
```

Do not hardcode cities after backend integration, except temporary fallback if API fails.

If user taps a city row:

```text
Set from_city_id or to_city_id
Use city name as city context
Then open map picker so user can choose exact address/pin within that city
```

If user taps "Xarita":

```text
Open Google Map Picker directly
```

Important:

```text
City selection is still required for matching.
Map pin is for exact address.
```

---

# 10. Google Map Picker component

Create reusable component:

```text
src/components/maps/GoogleMapPicker.tsx
```

Props:

```ts
type MapSelectionMode = "pickup" | "dropoff"

type GoogleMapPickerProps = {
  mode: MapSelectionMode
  title: string
  cityName?: string
  initialLat?: number | null
  initialLng?: number | null
  initialAddress?: string
  onConfirm: (location: {
    lat: number
    lng: number
    address: string
  }) => void
  onCancel: () => void
}
```

UI texts:

```text
Qidirish
Xaritadan belgilang
Tanlangan manzil
Tasdiqlash
Bekor qilish
Joriy joylashuv
Manzil topilmadi
Nuqtani tanlang
```

Behavior:

```text
Show full-screen Google Map
Show search input at top
Show back button
Show center marker or draggable marker
Allow tapping on map to move marker
Show selected address in bottom sheet
Show confirm button
```

Minimum required behavior:

```text
Map opens
User taps map
Marker moves
Coordinates are saved
Reverse geocoding tries to detect address
User can confirm
```

Places autocomplete is preferred but map tap + reverse geocoding is enough for MVP.

---

# 11. Google services

Use:

```text
Maps JavaScript API
Places Autocomplete if implemented
Geocoder for reverse geocoding
```

Do not use:

```text
Directions API
Distance Matrix API
Routes API
Navigation SDK
```

Search behavior:

```text
User types address/place
Show Google suggestions if autocomplete implemented
User selects suggestion
Map moves to selected location
Marker is set
Address is saved
```

Reverse geocoding behavior:

```text
User taps map or moves marker
Use geocoder to get formatted address
If address found, fill selected address
If not found, use manually typed address if available
If nothing available, use coordinates as fallback display text
```

---

# 12. Address sync rules

Pickup selection:

```text
Save pickup_lat
Save pickup_lng
Update pickup_address if Google returns address
Keep from_city_id from selected city
```

Dropoff selection:

```text
Save dropoff_lat
Save dropoff_lng
Update dropoff_address if Google returns address
Keep to_city_id from selected city
```

User must be able to edit address manually later.

Address and coordinate are separate:

```text
pickup_address = human-readable address
pickup_lat/lng = exact pin
```

---

# 13. Route summary screen

After pickup and dropoff are selected, show route summary screen like the uploaded screenshot, but in Uzbek.

Screen title:

```text
Yo‘nalish
```

Section 1:

```text
Olib ketish
<pickup address>
<pickup city/region>
```

Small button:

```text
O‘zgartirish
```

Section 2:

```text
Yetkazish
<dropoff address>
<dropoff city/region>
```

Button:

```text
Saqlash
```

On save:

```text
Continue to next order creation step
```

Do not show route line.

Do not show distance.

Do not show duration.

---

# 14. Existing order creation flow update

After route summary save, continue existing flow:

```text
phone numbers
parcel photo
comment
review
publish
```

The review screen must show:

```text
Yo‘nalish
Olib ketish manzili
Yetkazish manzili
Xaritada belgilangan / Xaritada belgilanmagan
Telefon raqamlar
Posilka rasmi
Tavsiya etilgan narx
Izoh
```

If pickup coordinates exist:

```text
Olib ketish joyi xaritada belgilangan
```

If dropoff coordinates exist:

```text
Yetkazish joyi xaritada belgilangan
```

Map selection must not be mandatory.

---

# 15. City and map relationship

City selection is still required for backend matching:

```text
from_city_id
to_city_id
```

Map pin is only for exact address:

```text
pickup_lat/lng
dropoff_lat/lng
```

Matching must still use:

```text
from_city_id + to_city_id
```

Do not implement coordinate-based matching.

Do not implement distance-based matching.

---

# 16. Suggested price behavior

After both city IDs are selected, call:

```http
GET /api/v1/route-tariffs/suggested-price?from_city_id=...&to_city_id=...
```

If suggested_price exists:

```text
60 000 so‘m
```

If null:

```text
Narx haydovchi bilan kelishiladi
```

Do not calculate price by distance.

Do not use Google distance to calculate price.

---

# 17. Driver privacy rule

Before driver is selected, driver feed must not show exact coordinates.

Driver feed must not show:

```text
pickup_lat
pickup_lng
dropoff_lat
dropoff_lng
sender_phone
receiver_phone
full pickup address
full dropoff address
```

Driver feed may show:

```text
from_city
to_city
short pickup area
short dropoff area
suggested price
cargo photo
```

After client selects driver, only the assigned driver may see:

```text
full pickup address
full dropoff address
pickup coordinates
dropoff coordinates
sender_phone
receiver_phone
```

If frontend receives private fields in feed accidentally, do not render them before selection.

---

# 18. Assigned order read-only map

For assigned driver order detail, if coordinates exist, show:

```text
Xaritada ko‘rish
```

Open read-only map with:

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

Optional external button:

```text
Google Maps’da ochish
```

This may open external Google Maps app/browser with destination coordinates.

It must not become in-app navigation.

---

# 19. Utility functions

Create:

```text
src/utils/maps.ts
```

Functions:

```ts
export function createGoogleMapsSearchUrl(lat: number, lng: number): string

export function createGoogleMapsDirectionsUrl(destinationLat: number, destinationLng: number): string

export function hasCoordinates(lat?: number | null, lng?: number | null): boolean
```

Create:

```text
src/utils/address.ts
```

Functions:

```ts
export function formatShortAddress(address: string): string

export function formatMapSelectionStatus(lat?: number | null, lng?: number | null): string
```

---

# 20. Types update

Update order types:

```ts
export type OrderDraft = {
  from_city_id?: string
  to_city_id?: string
  from_city_name?: string
  to_city_name?: string

  pickup_address?: string
  dropoff_address?: string

  pickup_lat?: number | null
  pickup_lng?: number | null
  dropoff_lat?: number | null
  dropoff_lng?: number | null

  sender_phone?: string
  receiver_phone?: string
  cargo_photo_url?: string
  comment?: string
}
```

Do not add cargo type/weight/size.

---

# 21. Error states

Use Uzbek messages:

```text
Xarita yuklanmadi
Google Maps API kaliti topilmadi
Manzil topilmadi
Nuqtani tanlang
Internet aloqasi yo‘q
Qayta urinib ko‘ring
Tanlangan shahar faol emas
Bu yo‘nalish uchun narx topilmadi
```

If Google Maps fails:

```text
Show manual address input fallback.
Do not block order creation.
```

If user does not select coordinates:

```text
Allow manual address flow.
```

---

# 22. UI quality requirements

Map screens must be clean and mobile-friendly.

Rules:

```text
Respect safe area
No overlapping UI
Bottom sheet must not hide confirm button
Search input must be readable
Back button must be visible
Map controls must not cover bottom sheet
No tiny labels
No mixed Russian UI text
No unnecessary buttons
```

All app UI text must be Uzbek.

Uploaded screenshots are examples of layout style, but final app must use Uzbek text.

---

# 23. Manual QA checklist

## Pickup point selection

```text
1. Login as client.
2. Open app.
3. Map Home appears.
4. Tap "Olib ketish joyi".
5. Location selector opens.
6. Select a city or tap "Xarita".
7. Google Map picker opens.
8. Tap map or search address.
9. Address is detected automatically.
10. Confirm.
11. Pickup address and coordinates are saved.
```

## Dropoff point selection

```text
1. Tap "Qayerga?"
2. Select city or tap "Xarita".
3. Pick destination point.
4. Confirm.
5. Dropoff address and coordinates are saved.
```

## Route summary

```text
1. After both points selected, route summary opens.
2. Pickup address is visible.
3. Dropoff address is visible.
4. Tap "Saqlash".
5. App continues order creation.
```

## Order publish

```text
1. Fill phone numbers.
2. Upload cargo photo.
3. Review order.
4. Publish order.
5. Backend receives city IDs, addresses, and optional coordinates.
```

## Optional map fallback

```text
1. Create order with manual address only.
2. Do not select map point.
3. Order must still publish.
```

## Privacy

```text
1. Login as driver before being selected.
2. Open feed.
3. Exact coordinates must not be visible.
4. Sender/receiver phone must not be visible.
5. Full address must not be visible.
6. Select driver as client.
7. Assigned driver can see full address and map points.
```

---

# 24. Files likely to create/update

Frontend:

```text
src/components/maps/GoogleMapPicker.tsx
src/components/maps/ReadOnlyOrderMap.tsx
src/utils/maps.ts
src/utils/address.ts
src/types/order.ts
src/api/client-orders.api.ts
src/api/cities.api.ts
src/app/App.tsx
.env.example
README.md
```

If project has different structure, adapt to existing structure.

Backend if available:

```text
app/models/order.py
app/schemas/order.py
app/api/v1/client/orders.py
app/services/orders.py
alembic/versions/<timestamp>_add_order_coordinates.py
tests/
```

If backend is not available, create documentation file:

```text
docs/backend_required_changes_for_google_maps.md
```

---

# 25. Final report

After implementation, stop and report:

```text
1. Files changed
2. Google Maps package added or reused
3. Environment variables added
4. Map Home implemented
5. Location selector implemented
6. Google Map picker implemented
7. Pickup/dropoff coordinate state implemented
8. Route summary implemented
9. Order create payload updated
10. Backend coordinate fields added or documented
11. Privacy rules checked
12. Manual QA result
13. Known TODOs
```

Do not add extra features beyond this task.
