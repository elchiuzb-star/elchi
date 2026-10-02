package uz.elchi.app.ui.map

/** A position of this phone for the "you are here" dot: where, how sure (metres, radius of the halo), when. */
data class UserFix(val point: GeoPoint, val accuracyM: Float, val timeMs: Long)

/**
 * The "my location" button on the client home map. IDLE: nothing asked. ASKING: the system permission dialog is
 * up. LOCATING: waiting for a first fix after a tap (spinner on the button). CENTRED: the camera went to the user
 * (until they pan). DENIED / UNAVAILABLE: a banner (no permission; no fix in time or location off).
 */
enum class MyLocationPhase { IDLE, ASKING, LOCATING, CENTRED, DENIED, UNAVAILABLE }

/**
 * [fix] is the latest known position (also drives the dot); [centre] is bumped every time the camera should move
 * to it (MapFocus nonce); [attempt] identifies one LOCATING wait, so a stale timeout does not end a newer one.
 */
data class MyLocationState(
    val phase: MyLocationPhase = MyLocationPhase.IDLE,
    val fix: UserFix? = null,
    val centre: Int = 0,
    val attempt: Int = 0,
)

/** Pure state machine of the button; the screen turns phases into the dialog, the spinner and the banners. */
object MyLocation {
    /** A tap centres on a known position no older than this; an older one waits for a fresh fix. */
    const val FRESH_MS = 2 * 60_000L

    /** No fix this long after a tap: "location unavailable". */
    const val TIMEOUT_MS = 10_000L

    /** The camera's zoom on the user (a few streets around). */
    const val ZOOM = 14f

    /**
     * The button was tapped. [granted]: any location permission; [locationOn]: the phone's location switch;
     * [nowMs] for the freshness of the known fix.
     */
    fun tap(s: MyLocationState, granted: Boolean, locationOn: Boolean, nowMs: Long): MyLocationState = when {
        s.phase == MyLocationPhase.ASKING -> s // the dialog is already up
        !granted -> s.copy(phase = MyLocationPhase.ASKING)
        else -> locate(s, locationOn, nowMs)
    }

    /** The answer of the permission dialog. */
    fun permissionResult(s: MyLocationState, granted: Boolean, locationOn: Boolean, nowMs: Long): MyLocationState =
        if (granted) locate(s, locationOn, nowMs) else s.copy(phase = MyLocationPhase.DENIED)

    /**
     * The screen came back (e.g. from the app's settings). A permission granted there while the "denied" banner was
     * up finishes what the tap started; a permission taken away drops the dot.
     */
    fun resumed(s: MyLocationState, granted: Boolean, locationOn: Boolean, nowMs: Long): MyLocationState = when {
        !granted && s.phase != MyLocationPhase.ASKING -> s.copy(fix = null, phase = if (s.phase == MyLocationPhase.DENIED) s.phase else MyLocationPhase.IDLE)
        granted && s.phase == MyLocationPhase.DENIED -> locate(s, locationOn, nowMs)
        else -> s
    }

    /** A new position: the dot moves; a tap waiting for it centres the camera. */
    fun fix(s: MyLocationState, fix: UserFix): MyLocationState =
        if (s.phase == MyLocationPhase.LOCATING) s.copy(fix = fix, phase = MyLocationPhase.CENTRED, centre = s.centre + 1) else s.copy(fix = fix)

    /** [attempt]'s wait ran out without a fix. */
    fun timeout(s: MyLocationState, attempt: Int): MyLocationState =
        if (s.phase == MyLocationPhase.LOCATING && s.attempt == attempt) s.copy(phase = MyLocationPhase.UNAVAILABLE) else s

    /** The person panned or zoomed: the camera is no longer on them; a banner goes too. */
    fun panned(s: MyLocationState): MyLocationState = when (s.phase) {
        MyLocationPhase.CENTRED, MyLocationPhase.DENIED, MyLocationPhase.UNAVAILABLE -> s.copy(phase = MyLocationPhase.IDLE)
        else -> s
    }

    /** The banner's close button. */
    fun dismiss(s: MyLocationState): MyLocationState =
        if (s.phase == MyLocationPhase.DENIED || s.phase == MyLocationPhase.UNAVAILABLE) s.copy(phase = MyLocationPhase.IDLE) else s

    private fun locate(s: MyLocationState, locationOn: Boolean, nowMs: Long): MyLocationState {
        val known = s.fix
        return when {
            !locationOn -> s.copy(phase = MyLocationPhase.UNAVAILABLE)
            known != null && nowMs - known.timeMs <= FRESH_MS -> s.copy(phase = MyLocationPhase.CENTRED, centre = s.centre + 1)
            else -> s.copy(phase = MyLocationPhase.LOCATING, attempt = s.attempt + 1)
        }
    }

    /**
     * The one automatic move (empty home, first fix): only when nothing is marked yet, the person has not moved the
     * map, and the fix is inside [bounds] (south-west, north-east) - abroad, the country view stays.
     */
    fun autoCentre(fix: UserFix, nothingMarked: Boolean, userMovedMap: Boolean, bounds: List<GeoPoint>): Boolean {
        if (!nothingMarked || userMovedMap || bounds.size != 2) return false
        val (sw, ne) = bounds
        return fix.point.lat in sw.lat..ne.lat && fix.point.lng in sw.lng..ne.lng
    }
}
