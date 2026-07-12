# Elchi Mobile App — Google Maps Pickup/Dropoff Integration Prompt

You are working on the **Elchi mobile frontend** project.

Frontend is a separate Vite + React + TypeScript mobile web app.

Backend is a separate FastAPI project.

Your task is to integrate **real Google Maps** into the client order creation flow so the client can select:

```text
pickup point
dropoff point
```

on the map.

Do not redesign the whole app.

Do not add extra product features.

Do not add live tracking.

Do not add distance-based pricing.

Do not add route calculation.

Do not add driver movement tracking.

Google Maps is used only for:

```text
address search
map pin selection
pickup/dropoff coordinates
```

---

# 1. MVP rules that must not change

Current MVP logic remains unchanged:

```text
Client creates order
Drivers with matching city route see the order
Drivers submit bids
Client selects one driver
Driver updates status
Client confirms delivery
Client rates driver
Payment is cash only
```

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
distance matrix
distance-based pricing
delivery OTP
QR code
pickup proof
delivery proof
delivery photo
cargo type
cargo weight
cargo size
driver departure time
driver capacity
free space
```

---

# 2. Google Maps usage

Use Google Maps only for client pickup/dropoff location selection.

Required Google features:

```text
Google Maps JavaScript API
Places Autocomplete / Places search
Geocoding or reverse geocoding if needed
```

Do not use:

```text
Directions API
Distance Matrix API
Routes API
Navigation SDK
real-time tracking
```

---

# 3. Environment variables

Add frontend env variable:

```env
VITE_GOOGLE_MAPS_API_KEY=YOUR_GOOGLE_MAPS_API_KEY
```

Keep existing backend API variable:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
```

Do not hardcode Google API key inside source code.

Do not commit real API key.

Update `.env.example`:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
VITE_GOOGLE_MAPS_API_KEY=your-google-maps-api-key
```

---

# 4. Recommended package

Install:

```bash
npm install @react-google-maps/api
```

If the project already has a Google Maps package, use the existing one.

Do not install multiple map libraries.

Do not use Leaflet, MapLibre, Yandex, or Mapbox in this task.

---

# 5. Backend required update

Update the backend order model and schemas to support optional coordinates.

Add nullable fields to `orders`:

```text
pickup_lat
pickup_lng
dropoff_lat
dropoff_lng
```

Recommended database type:

```text
DECIMAL(10, 7) or Float/Numeric according to current project style
```

Fields must be optional.

Order creation must still work without coordinates.

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

Do not add:

```text
distance
duration
route_polyline
driver_location
tracking_status
price_by_distance
```

---

# 6. Backend API payload update

Client order create payload should support:

```json
{
  "from_city_id": "uuid",
  "to_city_id": "uuid",
  "pickup_address": "Chilonzor, 12-mavze, 45-uy",
  "dropoff_address": "Samarqand shahar, Registon ko‘chasi",
  "pickup_lat": 41.2995000,
  "pickup_lng": 69.2401000,
  "dropoff_lat": 39.6542000,
  "dropoff_lng": 66.9597000,
  "sender_phone": "+998901234567",
  "receiver_phone": "+998909876543",
  "cargo_photo_url": "/storage/uploads/cargo_photo/example.jpg",
  "comment": "Ehtiyot bo‘lib olib boring"
}
```

Only these coordinates are added.

Do not add removed cargo fields.

Do not require coordinates.

---

# 7. Frontend order draft state update

Update client order draft state to include:

```ts
pickup_lat?: number | null
pickup_lng?: number | null
dropoff_lat?: number | null
dropoff_lng?: number | null
```

Keep existing fields:

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

```ts
cargo_type
weight
size
distance
duration
route_polyline
```

---

# 8. UX flow update

Current client order creation flow should become:

```text
Step 1: Select cities
Step 2: Enter pickup/dropoff addresses and optionally select points on map
Step 3: Upload parcel photo
Step 4: Review and publish
```

Do not add extra steps unless absolutely necessary.

In Step 2, add buttons:

```text
Olib ketish joyini xaritadan belgilash
Yetkazish joyini xaritadan belgilash
```

When user selects pickup point:

```text
Save pickup_lat
Save pickup_lng
Update pickup_address from selected place/address if available
```

When user selects dropoff point:

```text
Save dropoff_lat
Save dropoff_lng
Update dropoff_address from selected place/address if available
```

If user manually types address and does not select map point, order creation must still work.

---

# 9. Map picker component

Create reusable component:

```text
src/components/maps/GoogleMapPicker.tsx
```

Props:

```ts
type GoogleMapPickerProps = {
  title: string
  initialLat?: number | null
  initialLng?: number | null
  initialAddress?: string
  cityName?: string
  onConfirm: (location: {
    lat: number
    lng: number
    address: string
  }) => void
  onCancel: () => void
}
```

Behavior:

```text
Show full-screen mobile map
Show search input at top
Show selected address panel at bottom
Show draggable or tappable pin
Show confirm button
Show cancel/back button
```

UI text must be Uzbek.

Use:

```text
Qidirish
Xaritadan belgilang
Tanlangan manzil
Tasdiqlash
Bekor qilish
```

---

# 10. Map picker visual style

Design should feel like a real mobile app.

Use style similar to modern taxi/map apps:

```text
full-screen map
top search field
floating back button
center marker or draggable marker
bottom sheet with selected address
primary confirm button
```

Important UI quality rules:

```text
No overlapping text
No tiny unreadable labels
No map controls covering bottom sheet
No bottom nav inside map picker
No broken safe area
```

Map picker should not show the app bottom navigation.

It is a temporary full-screen selection screen/modal.

---

# 11. Search behavior

Use Google Places Autocomplete if available.

Search input behavior:

```text
User types address/place
Show suggestions
User selects suggestion
Move map to selected place
Set marker
Set address
```

If Places Autocomplete is not implemented immediately, support manual map click and reverse geocoding as fallback.

Do not block MVP because autocomplete is incomplete.

Minimum acceptable MVP:

```text
Map opens
User taps map
Marker moves
Selected coordinates are saved
Address is reverse-geocoded if possible
Confirm works
```

---

# 12. Default map center

Default map center should be Tashkent, Uzbekistan:

```ts
lat: 41.2995
lng: 69.2401
```

Default zoom:

```ts
13
```

If user already selected a point, open map at that point.

If cityName is available, optionally bias search to that city.

Do not request live user location by default.

Optional current location button is allowed only if simple and safe:

```text
Current location button can ask browser permission.
If denied, app must still work.
```

Do not make current location required.

---

# 13. Address sync rules

When selecting a point on map:

```text
If Google returns formatted address:
  fill pickup_address/dropoff_address with that address.

If Google cannot return address:
  keep manually typed address if it exists.
  otherwise show coordinates as fallback text.
```

User must be able to edit address manually after map selection.

Coordinates and address are separate:

```text
address = human-readable text
lat/lng = exact pin point
```

---

# 14. Review screen update

Order review screen must show map selection status.

For pickup:

```text
Olib ketish manzili
Chilonzor, 12-mavze, 45-uy
Xaritada belgilangan
```

For dropoff:

```text
Yetkazish manzili
Samarqand shahar, Registon ko‘chasi
Xaritada belgilangan
```

If no coordinate selected:

```text
Xaritada belgilanmagan
```

Do not block order publish if map is not selected.

---

# 15. Client order detail update

In client order detail, show map coordinate summary only if coordinates exist.

UI:

```text
Xarita nuqtalari
Olib ketish joyi belgilangan
Yetkazish joyi belgilangan
```

Optional button:

```text
Xaritada ko‘rish
```

This button can open read-only map with pickup and dropoff markers.

Do not draw route line.

Do not show distance.

---

# 16. Driver feed privacy rule

Before driver is selected, driver feed must not show full private contact data.

Map coordinates should also be protected.

Before selected driver:

```text
Do not expose full pickup_lat/lng
Do not expose full dropoff_lat/lng
Do not expose sender phone
Do not expose receiver phone
Do not expose full address
```

Driver feed may show:

```text
from_city
to_city
short pickup area/address
short dropoff area/address
suggested price
cargo photo
```

After driver is selected, only assigned driver can see:

```text
pickup_address
dropoff_address
pickup_lat/lng
dropoff_lat/lng
sender_phone
receiver_phone
```

Update frontend UI accordingly.

---

# 17. Assigned driver order detail map

For assigned driver order detail, if coordinates exist, show button:

```text
Xaritada ko‘rish
```

When opened, show read-only Google map with:

```text
pickup marker
dropoff marker
```

Do not show:

```text
route line
turn-by-turn navigation
distance calculation
live tracking
```

Optional external button:

```text
Google Maps’da ochish
```

This can open Google Maps URL with destination coordinates.

Do not implement in-app navigation.

---

# 18. Google Maps URL helper

Create utility:

```text
src/utils/maps.ts
```

Functions:

```ts
createGoogleMapsSearchUrl(lat: number, lng: number): string
createGoogleMapsDirectionsUrl(destinationLat: number, destinationLng: number): string
```

Use external Google Maps app/browser only for manual navigation.

This does not count as in-app navigation.

---

# 19. Frontend API update

Update client order API create function to send coordinates if they exist.

Example:

```ts
const payload = {
  from_city_id,
  to_city_id,
  pickup_address,
  dropoff_address,
  pickup_lat,
  pickup_lng,
  dropoff_lat,
  dropoff_lng,
  sender_phone,
  receiver_phone,
  cargo_photo_url,
  comment
}
```

Do not send undefined fields if backend has strict validation.

Send `null` only if backend accepts null.

Prefer omitting missing optional coordinates.

---

# 20. Error handling

Show Uzbek errors:

```text
Xarita yuklanmadi
Google Maps API kaliti topilmadi
Manzil topilmadi
Nuqtani tanlang
Internet aloqasi yo‘q
Qayta urinib ko‘ring
```

If Google Maps fails to load:

```text
User can still type address manually.
Order creation should still work.
```

Do not make map failure block order creation.

---

# 21. Security rules

Do not expose Google API key in backend.

Google API key is public frontend key, but must be restricted in Google Cloud Console by:

```text
HTTP referrer
allowed domains
enabled APIs only
```

Do not log:

```text
access_token
refresh_token
Google API key
full user phone numbers unnecessarily
```

---

# 22. Tests / QA

Add or update tests if test framework exists.

Manual QA is required.

## Manual QA: client pickup/dropoff

```text
1. Login as client.
2. Open Create Order.
3. Select from city and to city.
4. Enter pickup address.
5. Tap "Olib ketish joyini xaritadan belgilash".
6. Map opens.
7. Search or tap map.
8. Confirm point.
9. pickup_lat and pickup_lng are saved.
10. Enter dropoff address.
11. Tap "Yetkazish joyini xaritadan belgilash".
12. Confirm point.
13. dropoff_lat and dropoff_lng are saved.
14. Upload cargo photo.
15. Review order.
16. Confirm review shows map selection status.
17. Publish order.
18. Verify backend receives coordinates.
```

## Manual QA: optional map

```text
1. Create order without selecting map points.
2. Order should still publish successfully.
```

## Manual QA: privacy

```text
1. Login as driver before being selected.
2. Open feed.
3. Confirm full coordinates are not shown.
4. Select driver as client.
5. Login as assigned driver.
6. Open assigned order detail.
7. Confirm full map/address details are visible.
```

---

# 23. Files likely to create/update

Frontend:

```text
src/components/maps/GoogleMapPicker.tsx
src/components/maps/ReadOnlyOrderMap.tsx
src/utils/maps.ts
src/api/client-orders.api.ts
src/types/order.ts
src/app/App.tsx or current order flow files
.env.example
README.md
```

Backend if included:

```text
app/models/order.py
app/schemas/order.py
app/api/client/orders.py
app/services/orders.py
alembic/versions/<new_migration>_add_order_coordinates.py
tests/
```

Only update files that exist in current project structure.

---

# 24. Final report

After implementation, stop and report:

```text
1. Files changed
2. Google Maps package added
3. Env variables added
4. Backend coordinate fields added or required backend changes documented
5. Pickup/dropoff map picker implemented
6. Order create payload updated
7. Read-only map implemented or TODO
8. Privacy rule checked
9. Manual QA result
10. Known TODOs
```

Do not continue with extra map features.
