# Elchi Android App (Expo / React Native)

Native Android app for the Elchi intercity parcel-delivery marketplace, **client
+ driver** roles. It is a React Native rewrite of the mobile UI in
[`../frontend`](../frontend), reusing that project's API clients, DTO types, and
data hooks verbatim — only the UI layer is rebuilt with native components.

## Stack

- **Expo SDK 57** (React 19, React Native 0.86, New Architecture)
- **NativeWind v4** (Tailwind v3.4) — carries over the frontend's Tailwind
  classes + design tokens
- **React Navigation v7** — native-stack + bottom-tabs
- **expo-secure-store** — encrypted token storage (replaces web `localStorage`)
- Later phases: `react-native-maps`, `expo-image-picker`, `react-native-svg`

## Setup

```bash
cd android-app
npm install
cp .env.example .env      # set EXPO_PUBLIC_API_BASE_URL to the deployed backend
npm run android           # or: npm start, then run on a device/emulator
```

`.env` (only `EXPO_PUBLIC_`-prefixed vars reach the bundle):

```env
EXPO_PUBLIC_API_BASE_URL=https://<your-backend>/api/v1
EXPO_PUBLIC_GOOGLE_MAPS_API_KEY=
```

The backend **must be HTTPS** for on-device use.

## Scripts

- `npm run android` / `npm run ios` / `npm start` — Expo dev server
- `npm run typecheck` — `tsc --noEmit`

## What was ported from `frontend/`

The non-UI layers are plain fetch + TypeScript and were copied **verbatim**;
only three adaptations were needed for the native runtime.

| Location | Source | Change |
|----------|--------|--------|
| `src/types/` | `frontend/src/types` | none |
| `src/utils/` | `frontend/src/utils` | none |
| `src/api/` | `frontend/src/api` | `http.ts` env var; `files.api.ts` `File`→`RNFile` |
| `src/data/` | `frontend/src/data` | none |
| `src/auth/` | `frontend/src/auth` | `localStorage`→`expo-secure-store` shim |

Adaptations:

- **`src/api/http.ts`** — `import.meta.env.VITE_API_BASE_URL` →
  `process.env.EXPO_PUBLIC_API_BASE_URL`.
- **`src/auth/secureStorage.ts`** — a synchronous, `localStorage`-shaped façade
  over `expo-secure-store` (SDK 52+ sync `getItem`/`setItem`). `tokenStorage.ts`
  and `adminTokenStorage.ts` alias it as `localStorage`, so their original code
  is otherwise unchanged and the sync `getAccessToken()` API `http.ts` depends on
  is preserved.
- **`src/api/files.api.ts`** — uploads take an `RNFile` (`{ uri, name, type }`)
  from `expo-image-picker` instead of a DOM `File`.

> The admin API/data layer was copied along with the rest for completeness but
> is **not wired into any screen** — this app ships client + driver only.

## App-specific code

- `src/core/` — shared app types (`Role`, `ThemeMode`).
- `src/theme/` — design tokens (`tokens.ts`, ported from
  `frontend/src/styles/theme.css`) and `ThemeProvider` (owns the `themeMode`
  preference, drives NativeWind's color scheme, and derives the React Navigation
  theme — so classNames, tokens, and nav chrome all resolve to one light/dark
  state).
- `src/i18n/` — `translations.ts` (the uz/ru/en `T` dictionary, ported verbatim)
  and `I18nProvider`/`useT`.
- `src/auth/SessionProvider.tsx` — cold-start auth gate (`status`, `authedRole`,
  `login`, `logout`).
- `src/components/` — shared primitives: `Screen`, `ElchiLogo`, `buttons`.
- `src/screens/auth/` — `AuthFlow` state machine + `Splash`, `Onboarding`,
  `RoleSelect`, `Phone`, `Otp` screens.
- `src/screens/RoleHomeScreen.tsx` — temporary post-login landing (replaced by
  the real tab apps in phases 4–5).
- `src/navigation/RootNavigator.tsx` — swaps between `AuthFlow` and the role app
  based on session state.
- `global.css`, `tailwind.config.js` — NativeWind theme, tokens as CSS variables.

> Icons use `lucide-react-native` (chosen over `phosphor-react-native`, whose
> 1500-line barrel fails to resolve under Metro's dev bundler). They take
> explicit token colors, which is why `ThemeProvider` also exposes `colors`.
> The web "phone frame" + fake status bar were dropped — on-device the screen is
> the phone, so screens use `Screen` (SafeAreaView) instead.

### File uploads must not use `fetch`

Expo SDK 52+ replaces the global `fetch` with its "winter" implementation, which
rejects React Native's `{ uri, name, type }` FormData file part outright
(`Unsupported FormDataPart implementation` — see `expo/src/winter/fetch/convertFormData.ts`).
`src/api/files.api.ts` therefore posts multipart bodies via RN's `XMLHttpRequest`,
which does understand a native file URI. Everything else keeps using `apiRequest`
(`fetch`). If a new upload path throws that error, this is why.

Launching the image library needs no runtime permission request on SDK 57 —
`ImagePicker.launchImageLibraryAsync` handles it.

## Roadmap

- [x] **Phase 1** — Scaffold (Expo, NativeWind + tokens, navigation, theme)
- [x] **Phase 2** — Port shared core (types/utils/api/data/auth), adapt
      storage + env, verify bundle + typecheck
- [x] **Phase 3** — Auth flow: Splash → Onboarding → RoleSelect → Phone → OTP,
      wired to `session.ts`; theme + i18n providers; SecureStore-backed session
      gate. Post-login lands on a placeholder home.
- [x] **Phase 4** — Client app: hamburger drawer + screen switcher (`src/screens/client/`)
      holding the shared order draft. Order-creation flow (Home → City → District →
      Map picker → Contacts → Cargo photo → Review → Success) and lifecycle
      (Orders → Detail → Bids → Confirm → Rate / Dispute), plus Notifications,
      Profile, Support, and the shared SettingsPanel. Cargo photo uses
      `expo-image-picker`. Google Maps surfaces are placeholders until Phase 6.
- [x] **Phase 5** — Driver app (`src/screens/driver/`): bottom-nav + screen
      switcher — Home (greeting, active route, matching orders, stats), Routes
      (toggle/delete), Add Route (SelectField dropdowns), Orders (feed/history),
      Order Detail (status progress, other-bids, income report, advance status),
      Income (net card + bar chart + recent earnings), Documents (image upload),
      Edit Profile, Profile (availability toggle, vehicle), plus the Bid sheet.
- [x] **Phase 6** — Native surfaces. `react-native-maps` (Google) wired via
      `MapPanel` (read-only A/B route on client home + order-detail, client &
      driver) and a draggable center-pin `MapPickerScreen`; Maps key injected
      from `.env` via `app.config.js`. `expo-haptics` on key success moments.
      Verified on a local dev build (`expo run:android`) — map tiles + route
      render, backend connected over the LAN. **Push is deferred**: the backend
      has no device-token/FCM infrastructure, so remote push needs backend work
      first (see below).
- [x] **Phase 7** — Standalone signed **release APK** built locally
      (`./gradlew :app:assembleRelease`) with the JS bundle embedded (no Metro).
      Signed with a project release keystore. `eas.json` is included for cloud
      builds (`eas build`) once you have an Expo account.

## Native / dev build

Maps + secure-store etc. are native modules, so the app runs as a **development
build**, not Expo Go. The `android/` project is generated by `expo prebuild`.

```bash
# one-time env for Gradle
export JAVA_HOME=$(brew --prefix openjdk@17)/libexec/openjdk.jdk/Contents/Home
export ANDROID_HOME=$HOME/Library/Android/sdk
# build + install to a running emulator / connected device
npx expo run:android            # or: cd android && ./gradlew :app:installDebug
# serve JS (must be THIS project's Metro on 8081)
npx expo start
```

Gotcha: if another project's Metro is already on port 8081, the dev build loads
*its* bundle (red-box "Cannot find native module …"). Make sure the Metro on
8081 is this project's, or point the app's debug host at the right one.

## Release build (standalone signed APK)

A release APK embeds the JS bundle (no Metro needed) and is signed with the
project keystore at `android/app/elchi-release.keystore` (credentials in
`android/gradle.properties`). Because `android/` is gitignored, **back up the
keystore** if you want stable signing across `expo prebuild --clean` runs — a
new keystore means a different app signature.

```bash
export JAVA_HOME=$(brew --prefix openjdk@17)/libexec/openjdk.jdk/Contents/Home
export ANDROID_HOME=$HOME/Library/Android/sdk
cd android && ./gradlew :app:assembleRelease
# → android/app/build/outputs/apk/release/app-release.apk  (install: adb install -r <path>)
```

The backend URL baked into the release is whatever `EXPO_PUBLIC_API_BASE_URL` is
in `.env` at build time (currently the LAN IP — only reachable on the same
Wi-Fi as the Mac backend). For a truly shareable APK, deploy the backend to a
public HTTPS URL, set that in `.env`, and rebuild.

Release cert SHA-1 (for restricting the Google Maps key, if desired):
`CD:8F:7F:BE:54:06:CE:77:FB:9C:21:21:F7:42:FF:ED:B2:C5:5D:AC`.

Cloud builds (AAB for Play Store) via `eas.json`: `eas login && eas build -p android --profile production`.

## Push notifications (not yet implemented)

Remote push requires: (1) backend endpoints to store device push tokens and send
notifications, (2) a Firebase project + `google-services.json`, (3) client
registration via `expo-notifications`. The backend currently exposes only a
poll-based notifications list, so this is a follow-up once the backend adds push.

The UI reference for phases 3–5 is `frontend/src/app/App.tsx` (client + driver
screens) plus the design tokens above.
