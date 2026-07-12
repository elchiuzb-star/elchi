# Elchi Mobile App

This folder contains the mobile frontend integration layer for the Elchi MVP.

## Setup

```bash
npm install
cp .env.example .env.local
npm run dev
```

Local API configuration:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
VITE_APP_ENV=development
VITE_GOOGLE_MAPS_API_KEY=your-google-maps-api-key
```

`VITE_GOOGLE_MAPS_API_KEY` is used only by the frontend for pickup/dropoff map point selection. Restrict the key in Google Cloud Console by HTTP referrer and enabled APIs.

## Connected Backend Modules

- Auth: request OTP, verify OTP, refresh, logout, current user.
- Cities and route tariffs.
- File upload.
- Client orders: create, list, detail, update, publish, bids, select driver, confirm, rating, cancel.
- Driver: profile, documents, availability, routes, feed, bids, assigned order detail, status updates.
- Notifications: list and mark as read.
- Google Maps: optional pickup/dropoff point selection and read-only assigned order maps.

## CORS

When running Vite locally, backend CORS must allow:

```text
http://localhost:5173
http://127.0.0.1:5173
```

If the browser shows a CORS error, configure the backend allowed origins instead of bypassing CORS in the frontend.

## UI Integration Notes

The Figma Make screens were not present in this workspace when this integration was added. Existing or exported screens should import from:

```text
src/api/
src/auth/AuthContext.tsx
src/utils/
src/types/
```

Keep all user-facing text in Uzbek and avoid adding removed MVP features such as payment, chat, live GPS tracking, route calculation, QR, OTP delivery proof, cargo weight/size/type, or driver capacity. Google Maps is allowed only for client pickup/dropoff point selection and read-only order point display.
