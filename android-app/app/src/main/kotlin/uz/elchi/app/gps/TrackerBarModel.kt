package uz.elchi.app.gps

/** One sentence of the bar: a dictionary key (`driverTracking.*`, `driver.gps.*`) or the Android-only `gps.permissionPrompt`. */
data class BarText(val key: String, val params: Map<String, String> = emptyMap())

enum class BarDot { GREEN, AMBER, RED, GRAY }

enum class BarAction {
    /** Start for the screen's trip (asks the permission first when it is missing). */
    START,
    STOP,

    /** Ask the permission again (or open the app's settings when Android no longer asks). */
    PERMISSION,
    RETRY,
    TAKE_OVER,
}

data class BarModel(val dot: BarDot, val title: BarText, val notes: List<BarText>, val action: BarAction?) {
    /** The "sending" title is the only one that claims a live position (and only for a fix of the last 30 s). */
    val sending: Boolean get() = title.key == "driverTracking.sending"
}

/**
 * What the driver's GPS bar says (design 'gps-bar', web `DriverTrackingBar.tsx`) - pure, so every state is tested.
 * It says exactly what is happening: "sending" only while this phone gave a position in the last 30 seconds, queued
 * and lost points counted, and background sending claimed only while the location service really runs (§10.5: never a
 * "GPS faol" otherwise).
 */
object TrackerBar {
    /** A visible app with no position for this long gets the "check GPS / battery saver" hint. */
    const val STALLED_AFTER_S = 60L

    /** Accuracy worse than this is said (the server's low-confidence threshold, `LOW_ACCURACY_THRESHOLD_M`). */
    const val LOW_ACCURACY_M = 100L

    private val ERROR_KEY = mapOf(
        "FEATURE_DISABLED" to "driverTracking.error.disabled",
        "INVALID_STATE_TRANSITION" to "driverTracking.error.notRunning",
        "NETWORK_ERROR" to "driverTracking.error.network",
    )

    /**
     * The bar for a screen whose trip is [contextTripId] (null = no running trip on this screen), or null when there
     * is nothing to say. [clock] / [clockSeconds] format a device time (Tashkent).
     */
    fun model(
        s: TrackerSnapshot,
        contextTripId: String?,
        nowMs: Long,
        clock: (Long) -> String,
        clockSeconds: (Long) -> String = clock,
    ): BarModel? {
        // Another trip's state is not this screen's: for the screen's own trip the publisher is simply idle.
        val state = if (contextTripId != null && s.tripId != null && s.tripId != contextTripId) TrackerSnapshot(access = s.access) else s
        val quietEnd = state.phase == TrackerPhase.ENDED && (state.endReason == TrackerEndReason.STOPPED || state.endReason == TrackerEndReason.TRIP_FINISHED)
        if (contextTripId == null && (state.phase == TrackerPhase.IDLE || quietEnd)) return null

        val notes = mutableListOf<BarText>()
        val model = when (state.phase) {
            TrackerPhase.IDLE, TrackerPhase.NEEDS_PERMISSION -> {
                notes += BarText("driverTracking.idleHint")
                if (state.access == null || state.access == LocationAccess.NONE) notes += BarText("gps.permissionPrompt")
                BarModel(BarDot.GRAY, BarText("driverTracking.idle"), notes, BarAction.START)
            }
            TrackerPhase.STARTING -> BarModel(BarDot.GRAY, BarText("driverTracking.starting"), notes, null)
            TrackerPhase.ACTIVE -> active(state, nowMs, clock, clockSeconds, notes)
            TrackerPhase.PERMISSION_DENIED -> {
                notes += BarText("driver.gps.permissionHint")
                BarModel(BarDot.RED, BarText("driverTracking.permissionDenied"), notes, BarAction.PERMISSION)
            }
            TrackerPhase.UNAVAILABLE -> BarModel(BarDot.RED, BarText("driver.gps.unavailable"), notes, null)
            TrackerPhase.ERROR -> BarModel(BarDot.RED, BarText(ERROR_KEY[state.errorCode] ?: "driverTracking.error.generic"), notes, BarAction.RETRY)
            TrackerPhase.ENDED -> {
                val title = when (state.endReason) {
                    TrackerEndReason.SUPERSEDED -> "driverTracking.superseded"
                    TrackerEndReason.UNAUTHORIZED -> "driverTracking.unauthorized"
                    TrackerEndReason.CLOSED -> "driverTracking.closed"
                    else -> "driverTracking.stopped"
                }
                val action = when {
                    contextTripId == null -> null
                    state.endReason == TrackerEndReason.SUPERSEDED -> BarAction.TAKE_OVER
                    else -> BarAction.START
                }
                BarModel(BarDot.GRAY, BarText(title), notes, action)
            }
        }
        if (state.dropped > 0) notes += BarText("driverTracking.dropped", mapOf("count" to state.dropped.toString()))
        return model
    }

    private fun active(s: TrackerSnapshot, nowMs: Long, clock: (Long) -> String, clockSeconds: (Long) -> String, notes: MutableList<BarText>): BarModel {
        val ageS = s.lastFixAt?.let { (nowMs - it).coerceAtLeast(0) / 1000 }
        val sending = ageS != null && ageS <= GpsOutbox.FRESH_MAX_AGE_SECONDS
        val title = when {
            sending -> BarText("driverTracking.sending")
            s.lastFixAt == null -> BarText("driverTracking.waitingFirstFix")
            else -> BarText("driverTracking.waitingFix", mapOf("time" to clock(s.lastFixAt)))
        }
        s.lastSentAt?.let { notes += BarText("driverTracking.lastSent", mapOf("time" to clockSeconds(it))) }
        s.lastAccuracyM?.takeIf { it > LOW_ACCURACY_M }?.let { notes += BarText("driverTracking.lowAccuracy", mapOf("meters" to it.toString())) }
        if (s.queued > 0 && s.offline) notes += BarText("driverTracking.queuedOffline", mapOf("count" to s.queued.toString()))
        if (ageS != null && ageS > STALLED_AFTER_S) notes += BarText("driverTracking.stalled")
        s.lastGap?.let { gap ->
            val key = if (gap.cause == TrackerGap.Cause.BACKGROUND) "driverTracking.gapBackground" else "driverTracking.gapNoFix"
            notes += BarText(key, mapOf("from" to clock(gap.from), "to" to clock(gap.to)))
        }
        s.battery?.takeIf { !it.charging && it.pct <= DriverTracker.LOW_BATTERY_PCT }?.let {
            notes += BarText("driverTracking.lowBattery", mapOf("pct" to it.pct.toString()))
        }
        if (s.access == LocationAccess.APPROXIMATE) notes += BarText("driver.gps.preciseOff")
        // Q148 native: background sending is claimed only while the service runs; otherwise the honest web sentence.
        notes += BarText(if (s.backgroundActive) "driver.gps.backgroundOn" else "driverTracking.foregroundOnly")
        return BarModel(if (sending) BarDot.GREEN else BarDot.AMBER, title, notes, BarAction.STOP)
    }
}
