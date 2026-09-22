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
VITE_YANDEX_MAPS_API_KEY=your-yandex-js-api-key
```

### Maps

This client uses the **Yandex Maps JavaScript API**, loaded from `api-maps.yandex.ru`. "MapKit SDK" is the
native Android/iOS library and has no web build - the native app lives in `android-app/`, which is frozen.

* `VITE_YANDEX_MAPS_VERSION` picks the API version: `2.1` (default) or `v3`. Yandex issues a key for one
  version only, and the other answers `403 Invalid api key`. The key this account holds is a **v2.1** key, so
  `2.1` is the default; switching to `v3` is one env line, because `src/components/maps/yandex.ts` keeps one
  adapter per version behind a single interface and no component knows which is loaded.
* `VITE_YANDEX_MAPS_API_KEY` draws the map. Create it in the Yandex Cloud console ("JavaScript API and
  Geocoder API") and **restrict it to the domains this app is served from**: the key ships in the browser
  bundle, so the domain restriction is the only thing protecting it.
* There is **no geocoder key in the client.** Turning a pin into an address (`/geo/reverse-geocode`) and an
  address into a pin (`/geo/geocode`) goes through our own backend, which holds
  `ELCHI_YANDEX_GEOCODER_API_KEY`.
* Without the map key nothing breaks: every map degrades to the text it was drawn over - the ordered stop
  list, the address, or the coordinates. A place can still be marked and an order still placed.

## Connected Backend Modules

- Auth: request OTP, verify OTP, refresh, logout, current user.
- Cities and route tariffs.
- File upload.
- Client orders: create, list, detail, update, publish, bids, select driver, confirm, rating, cancel.
- Driver: profile, documents, availability, routes, feed, bids, assigned order detail, status updates.
- Notifications: list and mark as read.
- Yandex Maps: pickup/dropoff point selection and read-only assigned order maps; geocoding is proxied by our backend.

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

## API v2 types (ADR-0010)

The v2 schema is exported from the backend and committed, so a DTO change shows up as a diff here:

```bash
py scripts/export_openapi.py            # -> mobile-app/src/api/generated/openapi-v2.json
py scripts/export_openapi.py --check    # CI: fails (exit 3) when the committed file is stale
```

```bash
npm run gen:api                         # openapi-v2.json -> src/api/generated/v2.ts (types only)
```

`openapi-typescript` is pinned in `package-lock.json` (ADR-0010 §3, types-only devDependency, no runtime code).
Both generated files are committed, so a backend DTO change shows up in review and breaks the client build on
purpose. The v1 screens keep their hand-written types; no new hand-written DTO is added anywhere (ADR-0010 §5).

## Screens

| Path | What runs there |
|---|---|
| `/` | The frozen-scope v1 client and driver screens (unchanged) |
| `/v2` | The v2 client (A8): my requests, driver proposals, accept, booking, tracking, chat, support |
| `/e/<token>` | The public page of a shared listing (O3, §20.2) - no sign-in, no identity shown |
| `/admin` | The admin panel; the A9 operator sections (queues, v2 disputes, support/trust, KPI/SLO) live here |

`/v2` reuses the v1 OTP session: the same JWT is accepted by `/api/v2` (ADR-0006). `VITE_API_V2_BASE_URL` is
optional - by default `/api/v1` in `VITE_API_BASE_URL` is swapped for `/api/v2` on the same host.

Staff sign in with a username and password (`/api/v1/auth/staff-login`); OTP is only for clients and drivers.
The admin panel keeps its own session (`elchi_admin_*`), and the v2 calls from those screens travel with it.

## Languages

The client speaks Uzbek and Russian. Every word a person reads is chosen in the client: the server's `message`
field carries an English developer description of an error code (`app/contracts/errors.py`), so there is no
`Accept-Language` negotiation to do.

* `src/i18n/messages.ts` — one entry per key, both languages side by side. `messages.test.ts` fails when an
  entry has only one language, when the Russian slot still holds the Uzbek text, or when the two sides use
  different `{placeholders}`.
* `src/i18n/index.ts` — `translate(key)` for known keys, `translateDynamic(code)` for codes that only exist at
  runtime (a status, an error code, a match type). Uzbek is the fallback, so a missing translation renders a
  usable screen rather than a key name.
* `src/i18n/react.ts` — `useT()` and `useLocale()`; the locale is one module-level value read through
  `useSyncExternalStore`, persisted in `localStorage` under `elchi.lang`.

**State of the migration.** The *vocabulary* is done and tested: every error code, warning, booking/listing/trip
status, match type, proof code, dispute type/status/resolution and tracking state resolves through the
dictionary in both languages. **Screen copy is not** - headings, buttons and explanatory paragraphs in
`ConnectedApp.tsx` and the admin panels are still Uzbek literals.

There is deliberately **no language switch in the UI yet**. Shipping one now would show a screen that is part
Russian (the statuses and refusals) and part Uzbek (everything around them), which is worse than one honest
language. The switch goes in when the screen copy is migrated; until then the locale can be set from devtools
(`localStorage.setItem("elchi.lang", "ru")`) to review translations.

## Tests

```bash
npm run lint    # tsc --noEmit
npm test        # vitest: auction rules and design-system behaviour
npm run build   # tsc + vite build
```

`npm test` covers the rules that decide whether a conversation can become a booking (`src/app/auction.ts` -
AC05 among them) and the behaviour of the shared components (`src/app/ui/mobile.tsx`). Rendering and layout are
judged by eye; these tests exist for the things that can be silently *wrong*.
