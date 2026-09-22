# Running Elchi

Quickstart for all four surfaces. Every command here was run and verified on this Mac.

| Surface | Path | Runs on |
|---|---|---|
| Backend API | `app/` | `https://api.elchigo.uz` (prod) · `localhost:8000` (local) |
| Web app + admin | `frontend/` | Vercel · `localhost:5173` |
| Android app | `android-app/` | Expo dev build on an emulator |
| Mobile web (optional) | `mobile-app/` | not deployed |

For the deeper local-Postgres and release-APK detail, see [START.md](START.md).

---

## 0. One-time setup

```bash
# Node — any recent LTS
node -v

# Python 3.11+ and the backend venv
cd ~/Desktop/Elchi/elchi
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt   # runtime + test tools (pytest)

# JS deps
cd frontend     && npm install
cd ../android-app && npm install
```

**Java for Android builds.** You do *not* need to install a JDK — Android Studio bundles
one. Point at it rather than installing a second:

```bash
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
export ANDROID_HOME="$HOME/Library/Android/sdk"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"
```

Add those four lines to `~/.zshrc` so they persist. Verify with `java -version` → 21.x.

---

## 1. Backend

### Against production (nothing to start)

The API is already live and is what the deployed apps talk to:

```bash
curl https://api.elchigo.uz/api/v1/health     # {"success":true,"message":"OK"}
open https://api.elchigo.uz/docs              # Swagger
```

### Locally

**The database first.** Stage 2 needs PostGIS from migration `0030` onwards, and a plain local PostgreSQL
install usually has none - the stage-2 schema then simply cannot be created. The repo ships a persistent
stack with the same engine as production (decision 34):

```bash
docker compose -f docker-compose.dev.yml up -d --wait     # PostgreSQL 16 + PostGIS :45433, Redis :36380
```

Its data lives in a named volume, so it survives container and machine restarts. `docker-compose.test.yml`
(`:45432`) is a *different* stack: tmpfs, wiped on every restart, and only meant for `tests/pg`. Pointing the
dev server at the test stack is the usual reason accounts and catalogues "disappear".

`.env` then reads:

```env
ELCHI_DATABASE_URL=postgresql+psycopg://elchi:elchi_dev@127.0.0.1:45433/elchi
ELCHI_REDIS_URL=redis://127.0.0.1:36380/0
```

An `ELCHI_DATABASE_URL` exported in the shell **overrides `.env`**, so start the server from a shell that does
not set it (`echo $ELCHI_DATABASE_URL` should be empty).

```bash
cd ~/Desktop/Elchi/elchi
.venv/bin/alembic upgrade head                # ALWAYS run after pulling
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0`, not `127.0.0.1` — otherwise emulators and phones can't reach it.

First time only, seed reference data:

```bash
.venv/bin/python -m app.modules.platform.environment set development --by "dev:<you>"
.venv/bin/python scripts/seed_admin_required_data.py          # v1 catalogue: 14 regions, 176 districts, super_admin
.venv/bin/python scripts/import_legacy_districts.py --create-regions --apply   # v2 catalogue: 14 regions, 164 districts
.venv/bin/python scripts/seed_geo_fixtures.py --actor-user-id 1                # DEV ONLY: corridor, stops, routes + service flags
```

### Routing: our own OSRM

The map draws whatever geometry the configured router returns. `fake` returns straight lines between
stops - fine for a unit test, wrong on a map. `geoapify` is a real router but a third party outside the
country, which Q24 keeps off. **OSRM run by us** is the third option and the only one with neither problem:
it serves an OpenStreetMap extract from a container beside the database, so no coordinate leaves the machine
and there is no external data flow to review.

```bash
scripts/osrm-prepare.sh                                              # one-time: ~120 MB extract + graph
docker compose -f docker-compose.dev.yml --profile routing up -d osrm
# .env:
ELCHI_GEO_ROUTING_PROVIDER=osrm
```

Preparing the graph takes a few minutes and about 1 GB of RAM; the result lives in `docker/osrm/data`
(gitignored) and is rebuilt with `scripts/osrm-prepare.sh --refresh` when a newer extract is wanted. The
container is behind the `routing` compose profile, so a plain `up -d` does not try to start a router whose
graph may not exist yet.

What it buys, measured against the road:

| | `fake` | `osrm` | real |
|---|---|---|---|
| Toshkent - Namangan | 281 km / 4s40m | **292 km / 4s08m** | ~290 km |
| Samarqand - Buxoro | 291 km / 4s50m | **271 km / 4s19m** | ~270 km |
| Toshkent - Kasbi | 530 km | **510 km** | ~480 km |

`fake` also assumes one speed everywhere, which is why its durations are consistently long.

Then, for testing the flow anywhere in the country rather than only on the fixture corridor:

```bash
.venv/bin/python scripts/geocode_missing_district_centres.py --apply   # district centres with no source
.venv/bin/python scripts/seed_dev_nationwide.py                        # country flags + corridors on the axes
```

`geocode_missing_district_centres.py` is what makes "choose a district, the map opens there" true. The
rule it keeps is wave 17.1's: a district centre is a coordinate somebody checked or it is NULL, never a
guess. 66 districts are filled from the hand-checked list in `seed_districts.py::DISTRICT_CENTERS` - those
are town centres and are the best source there is. The rest have no source in the repository, so the script
asks the geocoder by name and accepts an answer only if it lands inside Uzbekistan, near its own region, and
still carries the district's name. 96 pass that; 2 stay NULL, which the picker already handles by opening on
the province and asking the person to mark their place.

A geocoder answer is the district **polygon centroid**, not its town, so it can sit tens of kilometres from
where people actually are - Konimex differs by 98 km. That is why the hand-checked list wins wherever it has
an entry, and why these two sources are not interchangeable.

`seed_dev_nationwide.py` turns the stage-2 services on at **country** scope and seeds four synthetic
corridors along the axes that actually carry traffic - M39 south, M37 west, the Fergana valley, and
Qashqadaryo - Buxoro - each with a confirmed route in both directions. With
`ELCHI_GEO_DEV_POINT_OFFSET_M=250000` in `.env`, places away from an axis still project onto one.

It was one corridor through all 14 region centres at first, and that is worth knowing because of how it
failed: everything resolved, but Toshkent - Kasbi came back as **1 008 km**, since the only path between
them ran down through Surxondaryo. A leg is measured *along the line it is projected onto*, so the line has
to resemble the road or the distance above the price field is nonsense. With the per-axis corridors the same
pair is 530 km against a real ~480, Toshkent - Namangan 281 against ~290, Samarqand - Buxoro 291 against
~270.

Still a **fixture, not geography**: straight hops between region centres from the fake router, region centres
instead of verified stops, and a radius no real corridor would have. A pair that shares no axis (Kasbi -
Namangan) resolves onto whichever line both reach and then *understates* the trip, because the drive to the
road is not part of a leg - the client says so on screen whenever an end sits more than 5 km off the route.
Both scripts refuse to run against a production marker, and the override is ignored outside development.
`--drop` retires the corridors by closing them: a DB trigger protects the stops of a confirmed route
version, and closing is the real retirement path anyway.

Note what the fixture costs while it is on: `qa_probe_ui_journey.py` then reports three failures on purpose -
`passenger stays off until the legal review`, `two places no route serves get the no-route answer` and
`a direction that runs backwards along the road is refused`. Those checks assert the closed configuration, and
the fixture is the open one. Drop it to see them pass again.

That last script also switches the corridor's stage-2 services on: passenger, parcel, **driver listings** and
matching. `driver_listing_enabled` is the one that bites - it defaults to `false` like every other service
flag, and a corridor with no row for it falls back to that default, so a driver gets `FEATURE_DISABLED` when
they try to publish a trip offer and the supply side of the marketplace looks broken. Re-running the script is
safe: a flag already on is left completely alone (no version bump, no audit row). Production defaults are not
touched, and the script refuses to run at all under a production marker.

The environment marker is what makes the catalogue scripts run at all (they fail closed without it). Without
the last line the direction picker shows regions and districts but no stops, and the feed stays empty: offers
are matched on verified stops and confirmed routes, never on district names (spec §6.1).

### A cast you can log in as

The catalogue makes the map work; it does not give you anybody to *be*. The QA probes and the v1 seeders
leave hundreds of accounts behind, but every phone number is random, so the first screen of the app has no
answer to "which number do I type?". `seed_demo_v2.py` seeds five fixed accounts and puts the stage-2 world
around them into a known state:

```bash
.venv/Scripts/python.exe scripts/seed_demo_v2.py            # --dry-run builds it all, then rolls back
```

| Phone | Role | What it is for |
|---|---|---|
| `+998900001001` | client | Two published requests (parcel + passenger), two live negotiations, an inbox |
| `+998900001002` | client | Answers the driver's trip offer, so the other direction has a thread too |
| `+998900001010` | driver | Approved, one vehicle, one planned trip advertised **twice** - taxi and parcel |
| `+998900001011` | driver | Approved, bids against driver 1 on the same request (the Q40 board needs two) |
| `+998900001012` | driver | Unapproved on purpose: this is what the verification gate looks like |

The OTP is the dev mock (`ELCHI_DEV_MOCK_OTP`, `12345` by default) and works for any phone while
`ELCHI_ENVIRONMENT` is a development one. Both approved drivers get one approved top-up (50 000 so'm) and
one still pending (20 000 so'm), so the wallet screen is not a row of zeros; the listings carry real view
counts because the script opens them as the other accounts.

Everything is written through the **domain services**, never into tables, so the seeded world is one a real
user could have reached: the unapproved driver really cannot publish, a proposal really carries its frozen
fee quote. If the script cannot build a state it prints the refusal and carries on - that refusal is the
product saying no for a reason, and it is worth reading rather than working around.

Idempotent: accounts match on phone and the rows it owns carry `[demo-v2]` in their comment, so a second run
tops the world up instead of doubling it. It refuses to run against a production marker.

Two things that look like bugs and are not: `request-otp` has a 60-second resend cooldown
(`OTP_RESEND_TOO_SOON`) so logging the same phone in twice in a row makes you wait, and notifications only
exist once the outbox has been dispatched - the seeder does that at the end, and the worker does it on a
timer otherwise.

### Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

> Known: ~12 tests in `test_auth.py` / `test_files.py` / `test_stage20_final_qa.py` fail
> because they read your personal `.env` and hardcode a 5-digit `dev_otp`. Pre-existing and
> unrelated to any recent change — compare against `git stash` before blaming your work.

---

## 2. Web app and admin panel

### Stage 2: the `mobile-app` client

**Stage-2 work lives in `mobile-app/`, not in `frontend/`.** `frontend/` is the v1 admin web app: it is frozen,
talks only to `/api/v1`, and knows nothing about listings, trips, bookings or the commission wallet. Opening it
and concluding "the backend work is not in the UI" is the usual confusion - the stage-2 screens are served by
`mobile-app`: the stage-2 marketplace is a **section inside the client app**, and the staff screens are under
`/admin`.

```bash
cd mobile-app
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1 npm run dev
```

| Yo'l | Nima | Kim uchun |
|---|---|---|
| <http://localhost:5173/> | Mijoz va haydovchi ilovasi — **v1 pochta oqimi va 2-bosqich bozori bir ilovada** | Foydalanuvchilar |
| <http://localhost:5173/admin> | Admin/operator paneli (v1 bo'limlari + v2 bo'limlari) | Xodimlar |
| <http://localhost:5173/e/{token}> | Ommaviy e'lon/kuzatuv sahifasi | Havola olgan odam |

**Alohida `/v2` ilovasi yo'q va alohida «bozor» bo'limi ham yo'q.** v1 ekranlarining o'zi 2-bosqich
dvigatelida ishlaydi (wave 12): dizayn, yorliqlar va navigatsiya o'zgarmagan, faqat ular ortidagi katalog va
buyruqlar `/api/v2` ga ulangan.

### Qaysi backend ishi qaysi ekranda

| Backend imkoniyati | Ekran (v1 nomi bilan) | Yo'l |
|---|---|---|
| Hudud → tuman → **xaritada joy belgilash** (Q88) | `client-location-selector` → `client-district-selector` → `client-point-picker` (`MapPointPicker`) | Bosh sahifa → «Qayerdan?» yoki «Qayerga?» qatori |
| **Yo'lovchi / Yuk** rejimi (Q89) | `client-home` dagi ikki tugma | Flag o'chiq bo'lsa tugma umuman ko'rinmaydi |
| Yo'nalish preview: koridor, masofa, yo'ldagi tumanlar | `GET /directions/preview` | Ikkala nuqta belgilanishi bilan avtomatik |
| «Bu ikki nuqta hozircha ELCHI yo'nalishiga mos kelmaydi» | `client-home` dagi rad holati | `409 ROUTE_MISMATCH` javobida |
| Yo'nalishdagi tumanlar (G17) va **tasdiqlangan marshrut xaritasi** (G18) | `client-home` va `client-route-summary` | «Yo'nalishni ko'rish» |
| Jo'nash oynasi (dan/gacha) va narx | `client-route-summary` | O'sha ekranda |
| Posilka turi, og'irligi, o'lchamlari (Q68) | `client-order-parcel` | «Davom etish» |
| E'lon yaratish va e'lon qilish (L1 + L4) | `client-order-review` | «Buyurtmani e'lon qilish» |
| Maskalangan aloqa ma'lumotlari ogohlantirishi (Q43) | `client-success` | E'lon qilingandan keyin |
| E'lonlar, bronlar va eski v1 buyurtmalar | `client-orders` | Pastki navigatsiya → «Buyurtmalar» |
| Takliflar, anonim «Haydovchi #N» (Q40), qabul qilish | `client-listing-bids` | Buyurtma → «Takliflarni ko'rish» |
| Topshirish/yetkazish **kodlari** (B5) va «Yetkazilganini tasdiqlash» | `client-booking-detail` | Buyurtmalar → bronni oching |
| Avtomobil ro'yxatdan o'tkazish (tekshiruv holati bilan, §17.1) | `driver-profile-form` | Haydovchi bosh sahifasi → «Profilni to'ldirish» |
| Safar rejalashtirish (tasdiqlangan marshrut, o'rin va yuk sig'imi) | `driver-add-route` | «Yo'nalishlar» → `+` |
| Safarni boshlash / yo'lga chiqish / yakunlash (T9) | `driver-routes` | «Yo'nalishlar» kartasidagi tugma |
| Mijoz so'rovlari lentasi, **yo'lingizdagi tumanlar** bo'yicha (M1) | `driver-feed` | «Moslar» |
| Taklif yuborish; olib ketish oynasi safar jadvalidan olinadi | `driver-bid` | «Moslar» → «Taklif yuborish» |
| Bron amallari: yetib keldim → olib ketildi (kod) → yo'lda → yetkazildi (kod) | `driver-order-detail` | «Buyurtmalar» → bronni oching |
| **Komissiya balansi**: mavjud / ushlab qolingan / qaytarilgan / to'ldirishlar | `driver-income` | Haydovchi bosh sahifasi → o'ng yuqoridagi karta |
| Posilka rasmi (imzolangan havola, Q6) | `ParcelPhoto` — mijoz e'loni, mijoz va haydovchi broni | Buyurtma tafsilotlari |
| Qarshi taklif (P6): narx, `price_revisions_left`, konflikt | `client-listing-bids` va `driver-proposals` | «Takliflarni ko'rish» / Profil → «Takliflarim» |
| Chat (N6/N7): maskalangan matn, sahifalash, qayta urinish | `booking-chat` | Bron → «Xabarlar» |
| Kuzatuv: **holat kuzatuvi** va **jonli joylashuv** alohida | `booking-tracking` | Bron → «Kuzatuv» |
| Naqd to'lov qaydi (B10): qayd → tasdiq/e'tiroz | `CashAcknowledgement` | Bron ekranida, xizmat boshlangach |
| Operator navbatlari, nizolar, KPI/SLO, legacy arxiv | `AdminOpsPanel` | `/admin` → tegishli bo'lim |
| Staff MFA (omil ulash, tasdiqlash, bekor qilish) | `AdminSecurityPanel` | `/admin` → **Xavfsizlik (MFA)** |

Xizmat flag'i o'chiq bo'lsa e'lon qilish `403 FEATURE_DISABLED` beradi — bu Q5 bo'yicha to'g'ri xulq. Lokal
tekshiruv uchun koridorga flag yoqiladi:

```bash
curl -X PUT "http://127.0.0.1:8000/api/v2/admin/feature-flags/parcel_enabled/scopes/corridor/<corridor_id>" \
  -H "Authorization: Bearer <staff_token>" -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" -d '{"enabled":true,"reason":"local dev"}'
```

Butun yo'lni bir buyruq bilan tekshirish (ekranlar chaqiradigan aynan shu ketma-ketlik):

```bash
QA_BASE=http://127.0.0.1:8000 py scripts/qa_probe_ui_journey.py
```

Ko'rinmaydigan narsalar odatda **ma'lumot yo'qligidan**: bo'sh katalogda viloyat/tuman/koridor bo'lmaydi va
lentalar bo'sh chiqadi. Katalogni yuklash 1-bo'limda.

⚠️ **API calls from `localhost:5173` are blocked by CORS.** Production allows only
`elchi.uz`, `www.elchi.uz`, and `admin.elchigo.uz`. The UI renders but login fails. Either:

- use the deployed panel at <https://admin.elchigo.uz/admin>, or
- run the backend locally (section 1) and drop the `VITE_API_BASE_URL` override, or
- add `http://localhost:5173` to `ELCHI_CORS_ORIGINS` on the server.

### Admin login

Username + password — **staff cannot use SMS OTP**; the API rejects staff roles on the OTP
endpoints. To create or reset a login, on the server:

```bash
cd /opt/elchi
docker compose --env-file .env.production -f docker-compose.prod.yml \
  run --rm api python scripts/set_staff_password.py --username admin --phone +998900000001
```

It prompts twice, hidden. Nothing is echoed or stored in shell history.

### Build / typecheck

```bash
npm run typecheck
npm run build
```

---

## 3. Android app on the emulators

### Start the emulators

```bash
$ANDROID_HOME/emulator/emulator -list-avds        # Pixel_9_Pro, Pixel_10_Pro, Medium_Phone
$ANDROID_HOME/emulator/emulator -avd Pixel_9_Pro  -no-snapshot-save &
$ANDROID_HOME/emulator/emulator -avd Pixel_10_Pro -no-snapshot-save &

adb devices                                       # wait for two "device" lines
```

> **Serial numbers are not stable.** `emulator-5554` is whichever booted first, and it
> changes between runs. Never assume — resolve it every time:
>
> ```bash
> for s in $(adb devices | tail -n +2 | awk '{print $1}'); do
>   printf "%s = " $s; adb -s $s emu avd name | head -1 | tr -d '\r'
> done
> ```

Wait until each reports `1`:

```bash
adb -s emulator-5554 shell getprop sys.boot_completed
```

### First run — build and install (~2–3 min)

```bash
cd ~/Desktop/Elchi/elchi/android-app
EXPO_PUBLIC_API_BASE_URL=https://api.elchigo.uz/api/v1 \
  npx expo run:android --device Pixel_9_Pro
```

`--device` takes the **AVD name**, not the adb serial. Passing a serial fails with
`Could not find device with name: emulator-5554`.

### Install the same APK on the second emulator

Don't rebuild — reuse the artifact:

```bash
adb -s emulator-5556 install -r \
  android/app/build/outputs/apk/debug/app-debug.apk
```

If you get `INSTALL_FAILED_UPDATE_INCOMPATIBLE: signatures do not match`, an older build
signed with a different debug key is installed. On an emulator just remove it:

```bash
adb -s emulator-5556 uninstall uz.elchi.app
```

⚠️ Never do this blindly on a **real device with a release build** — it wipes app data.

### Subsequent runs — just Metro

The APK stays installed; you only need the JS server:

```bash
cd ~/Desktop/Elchi/elchi/android-app
EXPO_PUBLIC_API_BASE_URL=https://api.elchigo.uz/api/v1 \
  npx expo start --dev-client --port 8081
```

Then wire each emulator to it and launch:

```bash
for s in emulator-5554 emulator-5556; do
  adb -s $s reverse tcp:8081 tcp:8081
  adb -s $s shell monkey -p uz.elchi.app -c android.intent.category.LAUNCHER 1
done
```

### Screenshots

```bash
adb -s emulator-5554 exec-out screencap -p > /tmp/shot.png
```

---

## 4. Environment variables

`.env` files are gitignored — copy from the `.example` next to each and fill in.

| File | Key variables |
|---|---|
| `.env` | `ELCHI_DATABASE_URL`, `ELCHI_SECRET_KEY`, `ELCHI_ESKIZ_*`, `ELCHI_OTP_LENGTH` |
| `frontend/.env` | `VITE_API_BASE_URL`, `VITE_GOOGLE_MAPS_API_KEY`, `VITE_OTP_LENGTH` |
| `android-app/.env` | `EXPO_PUBLIC_API_BASE_URL`, `EXPO_PUBLIC_GOOGLE_MAPS_API_KEY`, `EXPO_PUBLIC_OTP_LENGTH` |

**OTP length must match everywhere.** Backend `ELCHI_OTP_LENGTH`, web `VITE_OTP_LENGTH`,
and Android `EXPO_PUBLIC_OTP_LENGTH` are currently **4** (the Eskiz-approved Elchi
template). A mismatch means a delivered code can never be entered.

**`EXPO_PUBLIC_*` and `VITE_*` are baked in at bundle time.** Changing a `.env` requires a
rebundle — restart Metro or rerun `npm run build`. An override on the command line wins
over the `.env` file, which is handy for pointing a local build at production without
editing anything:

```bash
EXPO_PUBLIC_API_BASE_URL=https://api.elchigo.uz/api/v1 npx expo start --dev-client
```

---

## 5. Deploying

**Backend** — SSH to the VPS:

```bash
cd /opt/elchi && git pull && ./scripts/deploy.sh
```

Builds the image, runs migrations *before* any new container serves traffic, then starts
the API and Caddy. On a first deploy the health check retries for 60s while Caddy obtains
its TLS certificate — a `502` on the first attempt is normal.

**Frontend** — pushing to `main` should trigger Vercel.

> ⚠️ Vercel Hobby blocks deploys whose commit author isn't the project owner. Commits must
> be authored by **`elchiuzb-star`**:
>
> ```bash
> git config user.name  "elchiuzb-star"
> git config user.email "304070600+elchiuzb-star@users.noreply.github.com"
> ```
>
> Escape hatch that skips the author check entirely: `cd frontend && npx vercel --prod`

---

## 6. Troubleshooting

| Symptom | Cause |
|---|---|
| `ERR_CONNECTION_REFUSED` to `127.0.0.1:8000` in a browser | Stale cached bundle built before `VITE_API_BASE_URL` was set. Hard-refresh `Cmd+Shift+R` |
| App loads but every API call 400s with no `allow-origin` | CORS. The origin isn't in `ELCHI_CORS_ORIGINS` |
| `PASSWORD_LOGIN_REQUIRED` on `/auth/request-otp` | Working as intended — staff use `/auth/staff-login` |
| `ModuleNotFoundError: No module named 'app'` in a script | `PYTHONPATH` unset. The Docker image sets `PYTHONPATH=/app`; locally run from the repo root |
| Red box: `Cannot find native module …` | Another project's Metro owns port 8081. `lsof -ti:8081 \| xargs kill` |
| `Could not find device with name: emulator-5554` | `--device` wants the AVD name, not the serial |
| Frontend deployed but behaviour is old | Vercel didn't rebuild. Check the bundle: `curl -s https://admin.elchigo.uz \| grep -oE '/assets/index-[^"]+\.js'` — the hash should change between deploys |
