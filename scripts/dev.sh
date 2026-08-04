#!/usr/bin/env bash
# Bring up the local Android dev environment in the order that actually works:
# emulators -> adb reverse -> Metro -> launch. Safe to re-run; it skips whatever
# is already up.
#
#   ./scripts/dev.sh          start everything
#   ./scripts/dev.sh stop     stop Metro (emulators are left running)
#
# Override defaults with env vars, e.g. to point at a local backend:
#   EXPO_PUBLIC_API_BASE_URL=http://10.0.2.2:8000/api/v1 ./scripts/dev.sh
set -euo pipefail

cd "$(dirname "$0")/.."
APP_DIR="$PWD/android-app"

AVDS=("Pixel_9_Pro" "Pixel_10_Pro")
PACKAGE="uz.elchi.app"
ACTIVITY=".MainActivity"
METRO_PORT="${METRO_PORT:-8081}"
API_BASE_URL="${EXPO_PUBLIC_API_BASE_URL:-https://api.elchigo.uz/api/v1}"
METRO_LOG="/tmp/elchi-metro.log"
BOOT_TIMEOUT=240

export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
# Android Studio bundles a JDK; no separate install needed.
export JAVA_HOME="${JAVA_HOME:-/Applications/Android Studio.app/Contents/jbr/Contents/Home}"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"

ADB="$ANDROID_HOME/platform-tools/adb"
EMULATOR="$ANDROID_HOME/emulator/emulator"

die() { echo "error: $*" >&2; exit 1; }

# Serial numbers are assigned in boot order and shuffle between runs, so always
# resolve them from the AVD name rather than hardcoding emulator-5554.
online_serials() { "$ADB" devices | awk 'NR>1 && $2=="device" {print $1}'; }

avd_of() { "$ADB" -s "$1" emu avd name 2>/dev/null | head -1 | tr -d '\r'; }

serial_for_avd() {
	local want="$1" s
	for s in $(online_serials); do
		[ "$(avd_of "$s")" = "$want" ] && { echo "$s"; return 0; }
	done
	return 1
}

stop_metro() {
	if lsof -ti:"$METRO_PORT" >/dev/null 2>&1; then
		lsof -ti:"$METRO_PORT" | xargs kill 2>/dev/null || true
		echo "Stopped Metro on :$METRO_PORT"
	else
		echo "Metro was not running on :$METRO_PORT"
	fi
	echo "Emulators left running. To close one: adb -s <serial> emu kill"
}

if [ "${1:-}" = "stop" ]; then
	stop_metro
	exit 0
fi

# ── Preflight ────────────────────────────────────────────────────────────────
[ -x "$ADB" ] || die "adb not found at $ADB (install Android Studio / platform-tools)"
[ -x "$EMULATOR" ] || die "emulator not found at $EMULATOR"
[ -d "$APP_DIR/node_modules" ] || die "run 'npm install' in android-app/ first"

available="$("$EMULATOR" -list-avds)"
for avd in "${AVDS[@]}"; do
	grep -qx "$avd" <<<"$available" || die "AVD '$avd' not found. Available:
$available"
done

# ── 1. Emulators ─────────────────────────────────────────────────────────────
echo "==> Emulators"
running="$(for s in $(online_serials); do avd_of "$s"; done)"
for avd in "${AVDS[@]}"; do
	if grep -qx "$avd" <<<"$running"; then
		echo "    $avd already running"
	else
		echo "    booting $avd"
		# No -no-snapshot-save: saving state on exit keeps logins and open apps.
		"$EMULATOR" -avd "$avd" >/dev/null 2>&1 &
	fi
done

echo "==> Waiting for boot (up to ${BOOT_TIMEOUT}s)"
deadline=$((SECONDS + BOOT_TIMEOUT))
for avd in "${AVDS[@]}"; do
	while :; do
		if serial="$(serial_for_avd "$avd" 2>/dev/null)"; then
			booted="$("$ADB" -s "$serial" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)"
			[ "$booted" = "1" ] && { echo "    $avd ready ($serial)"; break; }
		fi
		[ "$SECONDS" -lt "$deadline" ] || die "$avd did not finish booting in ${BOOT_TIMEOUT}s"
		sleep 3
	done
done

# ── 2. Metro ─────────────────────────────────────────────────────────────────
echo "==> Metro on :$METRO_PORT"
if curl -s --max-time 2 "http://127.0.0.1:$METRO_PORT/status" >/dev/null 2>&1; then
	echo "    already running"
else
	# EXPO_PUBLIC_* is inlined at bundle time, so it must be set for THIS process.
	(cd "$APP_DIR" && EXPO_PUBLIC_API_BASE_URL="$API_BASE_URL" \
		nohup npx expo start --dev-client --port "$METRO_PORT" >"$METRO_LOG" 2>&1 &)
	deadline=$((SECONDS + 120))
	until curl -s --max-time 2 "http://127.0.0.1:$METRO_PORT/status" >/dev/null 2>&1; do
		[ "$SECONDS" -lt "$deadline" ] || die "Metro did not start in 120s — see $METRO_LOG"
		sleep 2
	done
	echo "    started (log: $METRO_LOG)"
fi
echo "    API base URL: $API_BASE_URL"

# ── 3. Wire each device and launch ───────────────────────────────────────────
echo "==> Launching $PACKAGE"
for avd in "${AVDS[@]}"; do
	serial="$(serial_for_avd "$avd")"
	# adb reverse maps the device's localhost:8081 to Metro here. It does NOT
	# survive a reboot, which is what causes "Unable to load script".
	"$ADB" -s "$serial" reverse "tcp:$METRO_PORT" "tcp:$METRO_PORT" >/dev/null
	if ! "$ADB" -s "$serial" shell pm list packages "$PACKAGE" 2>/dev/null | grep -q "$PACKAGE"; then
		echo "    $avd ($serial): $PACKAGE NOT installed — run:"
		echo "        cd android-app && npx expo run:android --device $avd"
		continue
	fi
	# sys.boot_completed goes to 1 before the system can reliably start a
	# third-party activity, so a freshly booted emulator silently drops back to
	# the launcher. Verify it actually came up and retry.
	launched=false
	for _ in 1 2 3 4 5 6; do
		# am start names the activity explicitly; monkey can race a force-stop.
		"$ADB" -s "$serial" shell am start -n "$PACKAGE/$ACTIVITY" >/dev/null 2>&1 || true
		sleep 5
		if "$ADB" -s "$serial" shell dumpsys activity activities 2>/dev/null \
			| grep -m1 topResumedActivity | grep -q "$PACKAGE"; then
			launched=true
			break
		fi
	done
	if [ "$launched" = true ]; then
		echo "    $avd ($serial): launched"
	else
		echo "    $avd ($serial): WARNING — did not come to the foreground; open it manually"
	fi
done

echo
echo "Ready. Edit files and they hot-reload."
echo "  Metro log:  tail -f $METRO_LOG"
echo "  Stop Metro: ./scripts/dev.sh stop"
