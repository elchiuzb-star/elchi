# Elchi Frontend (Modern Driver App UI)

The Figma "Modern Driver App UI" export, wired end-to-end to the FastAPI backend
in `../app`. It contains three role-based apps behind a single SPA:

| Route      | App           | Auth store (localStorage)      |
|------------|---------------|--------------------------------|
| `/`        | Auth flow     | —                              |
| `/driver`  | Driver mobile | `elchi_access_token` …         |
| `/client`  | Client mobile | `elchi_access_token` …         |
| `/admin`   | Admin desktop | `elchi_admin_access_token` …   |

Driver/client and admin keep **separate** token stores so an operator and a
driver can be logged in side by side.

## Setup

```bash
npm install
cp .env.example .env   # already present; adjust VITE_API_BASE_URL if needed
npm run dev            # http://127.0.0.1:5173
```

The backend must be running on the URL in `.env`:

```bash
# from the repo root
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`VITE_API_BASE_URL` defaults to `http://127.0.0.1:8000/api/v1`. The backend's
CORS config already allows `localhost`/`127.0.0.1` dev origins.

## Google Maps

`VITE_GOOGLE_MAPS_API_KEY` (+ optional `VITE_GOOGLE_MAPS_MAP_ID`) enables real
maps. They appear in:
- **Location picker** (`src/components/maps/LocationPicker.tsx`) — client order
  flow: drag the map under the centre pin → address is reverse-geocoded and the
  lat/lng is saved on the order.
- **Read-only route map** (`src/components/maps/MapView.tsx`) — client home and
  the client/driver order-detail screens (pickup **A** / dropoff **B** markers).

Without a key, these fall back to manual address entry / a placeholder, so the
app still works.

The **backend** also talks to Google Maps (server-side) via
`app/services/google_maps_service.py`, exposed at `POST /api/v1/geo/reverse-geocode`
and `POST /api/v1/geo/geocode`. Set `ELCHI_GOOGLE_MAPS_API_KEY` (a key with the
**Geocoding API** enabled) in the repo-root `.env`; it degrades to the local
nearest-district heuristic when absent.

## Auth / OTP

Login is phone + OTP. In development the backend returns the OTP in the
`request-otp` response, and the OTP screen shows a tappable **Demo OTP** chip
(`123456789` by default). Admin login auto-detects the staff role
(`super_admin` → `admin` → `operator`) for the entered phone; staff users must
be seeded in the backend (e.g. the super admin phone `+998900000001`).

## Architecture

- `src/app/App.tsx` — all screens (Figma export), wired to the data layer.
- `src/api/*` — typed API clients + envelope handling + token refresh (reused
  from the original `mobile-app`).
- `src/auth/*` — token storage (mobile + admin).
- `src/types/*` — backend DTO types.
- `src/data/*` — hooks and mappers that adapt backend payloads to the screens:
  - `session.ts` — OTP login/logout for all roles.
  - `useApi.ts` — `useAsync` loader hook.
  - `cities.ts`, `driver.ts`, `admin.ts`, `format.ts` — domain data + mappers.

## Scripts

- `npm run dev` — Vite dev server.
- `npm run build` — production build (`vite build`).
- `npm run typecheck` — `tsc --noEmit`.
