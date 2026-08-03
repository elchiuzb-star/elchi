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
.venv/bin/python -m pip install -r requirements.txt

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

```bash
cd ~/Desktop/Elchi/elchi
.venv/bin/alembic upgrade head                # ALWAYS run after pulling
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0`, not `127.0.0.1` — otherwise emulators and phones can't reach it.

First time only, seed reference data:

```bash
.venv/bin/python scripts/seed_cities.py
.venv/bin/python scripts/seed_districts.py
.venv/bin/python scripts/seed_admin_required_data.py
```

### Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

> Known: ~12 tests in `test_auth.py` / `test_files.py` / `test_stage20_final_qa.py` fail
> because they read your personal `.env` and hardcode a 5-digit `dev_otp`. Pre-existing and
> unrelated to any recent change — compare against `git stash` before blaming your work.

---

## 2. Web app and admin panel

```bash
cd ~/Desktop/Elchi/elchi/frontend
VITE_API_BASE_URL=https://api.elchigo.uz/api/v1 npm run dev
```

- Client / driver → <http://localhost:5173/>
- Admin panel → <http://localhost:5173/admin>

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
