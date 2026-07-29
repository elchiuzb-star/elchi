# Elchi — How to start the project (backend + Android app)

Full runbook to bring up the **FastAPI backend** and the **Android app** (`android-app/`)
from a cold machine, plus how they were configured on this Mac and the gotchas we hit.

Two parts, run in this order:

1. **Backend** — PostgreSQL + FastAPI (`app/`), serves `http://…:8000/api/v1`
2. **Android app** — Expo/React Native dev build **or** standalone release APK

---

## 0. Prerequisites (one-time install)

```bash
# Homebrew packages
brew install openjdk@17 postgresql@18     # JDK for Android builds, Postgres for the API
# Node (for the app) — any recent LTS; this repo used Node 24
node -v && npm -v
# Android SDK: install Android Studio, then note the SDK path (~/Library/Android/sdk)
# Python 3.11–3.14 for the backend
python3 --version
```

Environment variables the Android build needs (add to `~/.zshrc` so they persist):

```bash
export JAVA_HOME="$(brew --prefix openjdk@17)/libexec/openjdk.jdk/Contents/Home"
export ANDROID_HOME="$HOME/Library/Android/sdk"
export ANDROID_SDK_ROOT="$HOME/Library/Android/sdk"
export PATH="$PATH:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator"
```

---

## 1. Backend (FastAPI)

### 1a. PostgreSQL

This machine runs a Homebrew Postgres on **port 5433**, superuser **`a1234`**, trust auth,
with a database named **`elchi`** (already created and migrated).

```bash
# start Postgres (Homebrew)
brew services start postgresql@18        # or: pg_ctl -D <datadir> start

# sanity check + create the DB if it doesn't exist yet
PSQL=/Library/PostgreSQL/18/bin/psql      # or just `psql` if on PATH
$PSQL -h 127.0.0.1 -p 5433 -U a1234 -d postgres -c "\l" | grep elchi \
  || $PSQL -h 127.0.0.1 -p 5433 -U a1234 -d postgres -c "CREATE DATABASE elchi;"
```

### 1b. Python venv + deps

```bash
cd ~/Desktop/Elchi/elchi
python3 -m venv .venv                     # already exists on this machine
.venv/bin/python -m pip install -r requirements.txt
```

### 1c. Backend config (`.env` at repo root — already present)

Key values (see `elchi/.env`):

```env
ELCHI_ENVIRONMENT=local
ELCHI_DEBUG=true                          # dev mode → OTP is returned in the response
ELCHI_DATABASE_URL=postgresql+psycopg://a1234@127.0.0.1:5433/elchi
ELCHI_DEV_MOCK_OTP=12345                  # the OTP for every login in dev mode
ELCHI_GOOGLE_MAPS_API_KEY=…               # server-side geocoding (optional)
```

### 1d. Migrate + seed (first time, or after pulling new migrations)

```bash
cd ~/Desktop/Elchi/elchi
.venv/bin/alembic upgrade head                       # apply DB migrations (IMPORTANT)
.venv/bin/python scripts/seed_admin_required_data.py # cities, districts, tariffs, super admin
.venv/bin/python scripts/seed_bidding_demo.py        # optional: demo orders + driver bids
```

> **Always run `alembic upgrade head` after pulling.** A schema that's behind the code
> causes 500s like `column orders.cargo_type does not exist` (which looks like a generic
> "Xatolik yuz berdi" in the app).

### 1e. Run the backend

```bash
cd ~/Desktop/Elchi/elchi
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- Must be **`--host 0.0.0.0`** (not 127.0.0.1) so emulators/devices can reach it.
- Verify: open `http://127.0.0.1:8000/docs` (Swagger). Leave this terminal running.

---

## 2. Android app (`android-app/`)

The app uses native modules (maps, secure-store, image-picker), so it runs as a
**development build or a release APK — NOT Expo Go.**

### 2a. Install JS deps

```bash
cd ~/Desktop/Elchi/elchi/android-app
npm install
```

### 2b. Point the app at the backend (`android-app/.env`)

`EXPO_PUBLIC_API_BASE_URL` is **baked into the app at build/bundle time.**

| Target | Value |
|--------|-------|
| **Android emulator** (recommended for dev) | `http://10.0.2.2:8000/api/v1` — stable host alias, survives Wi-Fi/DHCP changes |
| **Physical device** (same Wi-Fi) | `http://<Mac-LAN-IP>:8000/api/v1` — find it with `ipconfig getifaddr en0` (or `en1`) |
| **Shareable / production** | `https://<your-deployed-backend>/api/v1` |

```env
# android-app/.env
EXPO_PUBLIC_API_BASE_URL=http://10.0.2.2:8000/api/v1
EXPO_PUBLIC_GOOGLE_MAPS_API_KEY=AIza…      # Android Maps SDK key
```

> After changing `.env`, you MUST rebundle/rebuild (see 2e for the release-cache caveat).

### 2c. Start an emulator

```bash
$ANDROID_HOME/emulator/emulator -list-avds
$ANDROID_HOME/emulator/emulator -avd <AvdName> &     # e.g. Medium_Phone or Pixel_10_Pro
adb devices                                          # confirm "emulator-5554  device"
```

### 2d. Option A — Development build (fast iteration, loads JS from Metro)

```bash
cd ~/Desktop/Elchi/elchi/android-app
npx expo run:android        # first run: prebuild + Gradle (~7 min). Installs + launches.
# subsequent runs — just serve JS; edits hot-reload:
npx expo start              # Metro on port 8081
```

- **Metro must be THIS project's, on port 8081.** If another project's Metro squats 8081,
  the app loads that app's bundle → red-box `Cannot find native module 'ExpoLinking'`.
  Free the port: `lsof -ti:8081 | xargs kill`, then `npx expo start`.
- JS-only changes reload from Metro; native changes need a rebuild
  (`cd android && ./gradlew :app:installDebug`).

### 2e. Option B — Standalone release APK (no Metro; installable/shareable)

Signed with the project keystore at `android/app/elchi-release.keystore`
(creds in `android/gradle.properties`).

```bash
cd ~/Desktop/Elchi/elchi/android-app/android
# ⚠️ if you changed android-app/.env, clear the Metro cache first or the OLD URL
#    gets cached into the APK:
rm -rf "$TMPDIR"/metro-* ../node_modules/.cache
find app/build -iname "*.bundle" -delete 2>/dev/null

./gradlew :app:assembleRelease
# → app/build/outputs/apk/release/app-release.apk
adb install -r app/build/outputs/apk/release/app-release.apk
adb shell monkey -p uz.elchi.app -c android.intent.category.LAUNCHER 1
```

---

## 3. Log in / test

- **Any valid `+998 9x xxx xx xx` phone auto-registers** as client or driver on first login.
- **OTP is always `12345`** in dev mode (shown as a tappable "Demo OTP" chip).

| Role | Number to type | Notes |
|------|----------------|-------|
| Mijoz (client) | `90 111 11 11` | Full client app |
| Haydovchi (driver) | `90 222 22 22` | Driver app; needs admin **approval** to go online/bid |

Pre-seeded demo (after running the seed scripts): client with bids `+998901234567`,
approved drivers `+998901234576 / …71 / …72 / …73 / …74 / …75`.

---

## 4. Quick full-stack start (copy-paste)

```bash
# ── Terminal 1: backend ────────────────────────────────────────────────
cd ~/Desktop/Elchi/elchi
brew services start postgresql@18
.venv/bin/alembic upgrade head
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# ── Terminal 2: emulator + app ─────────────────────────────────────────
export JAVA_HOME="$(brew --prefix openjdk@17)/libexec/openjdk.jdk/Contents/Home"
export ANDROID_HOME="$HOME/Library/Android/sdk"
$ANDROID_HOME/emulator/emulator -avd Medium_Phone &
cd ~/Desktop/Elchi/elchi/android-app
npx expo run:android        # or: adb install -r android/app/build/outputs/apk/release/app-release.apk
```

---

## 5. Troubleshooting (issues we actually hit)

| Symptom in app | Real cause | Fix |
|----------------|-----------|-----|
| **"Serverga ulanib bo'lmadi"** (can't connect) | Backend down, wrong URL, or release build blocked cleartext HTTP | Start backend on `0.0.0.0:8000`; use `10.0.2.2` (emulator) / LAN IP (device); ensure release manifest has `android:usesCleartextTraffic="true"` |
| **"Xatolik yuz berdi"** (generic) | Backend returned an error (reached server) — often a DB schema gap | `.venv/bin/alembic upgrade head`; check the uvicorn log |
| Login hangs / never reaches backend | App has a **stale API URL baked in** (Mac LAN IP changed, or Metro cached the old `.env`) | Use `10.0.2.2`; for release, clear Metro cache + delete `*.bundle` then rebuild (see 2e) |
| Red-box **`Cannot find native module 'ExpoLinking'`** | App loaded a **different project's Metro** on port 8081 | Kill the other Metro (`lsof -ti:8081 \| xargs kill`), run this project's `npx expo start` |
| Google map is blank (just the "Google" logo) | Maps key not authorised for **Maps SDK for Android** | Enable "Maps SDK for Android" on the key in Google Cloud Console |
| Menu/overlay button over the map not tappable | Native map captures touches / button under status bar | Already fixed in `ClientApp.tsx` (safe-area inset + high elevation/zIndex) |
| Backend "up" then dies later | It was an orphaned background process | Run it in a dedicated terminal (or a process manager) so it stays alive |

**Verify the URL baked into a built APK** (sanity check after a release build):

```bash
cd /tmp && rm -rf c && mkdir c && unzip -qo <apk> "assets/*" -d c
strings c/assets/index.android.bundle | grep -oE "http://[0-9.]+:8000/api/v1" | sort -u
```

---

## 6. (Reference) Web frontend

There's also a web version at `frontend/` (React + Vite), the design source for the app:

```bash
cd ~/Desktop/Elchi/elchi/frontend
npm install && npm run dev        # http://127.0.0.1:5173  (set VITE_API_BASE_URL in .env)
```

See `android-app/README.md` for the app architecture and the port history (which layers
were reused from `frontend/` vs. rebuilt for React Native).
