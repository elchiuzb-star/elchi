package uz.elchi.app.gps

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.generated.PointsBatchAck
import uz.elchi.app.api.generated.TrackingPointIn
import uz.elchi.app.api.generated.TrackingSessionDTO
import uz.elchi.app.api.generated.TrackingSessionStatus

enum class TrackerPhase { IDLE, NEEDS_PERMISSION, STARTING, ACTIVE, PERMISSION_DENIED, UNAVAILABLE, ERROR, ENDED }

/** Why a publisher is no longer running. */
enum class TrackerEndReason { STOPPED, SUPERSEDED, CLOSED, TRIP_FINISHED, UNAUTHORIZED }

/** What the phone lets this app read: precise, approximate only (Android 12+ choice), or nothing. */
enum class LocationAccess { PRECISE, APPROXIMATE, NONE }

data class BatteryState(val pct: Int, val charging: Boolean)

/** A stretch without any fix: the app was in the background without the service, or the phone gave no position. */
data class TrackerGap(val from: Long, val to: Long, val cause: Cause) {
    enum class Cause { BACKGROUND, NO_FIX }
}

data class TrackerSnapshot(
    val phase: TrackerPhase = TrackerPhase.IDLE,
    val tripId: String? = null,
    val sessionId: String? = null,
    /** Points waiting for the server's ACK. */
    val queued: Int = 0,
    /** Points that will never reach the server (queue limits, server refusals) - missing history, said out loud. */
    val dropped: Int = 0,
    /** Device time of the last fix, and its accuracy. */
    val lastFixAt: Long? = null,
    val lastAccuracyM: Long? = null,
    /** Local time of the last successful ACK. */
    val lastSentAt: Long? = null,
    /** The last send failed for a transient reason (no network, 5xx); points are kept. */
    val offline: Boolean = false,
    val access: LocationAccess? = null,
    val battery: BatteryState? = null,
    val lastGap: TrackerGap? = null,
    val gapCount: Int = 0,
    val errorCode: String? = null,
    val endReason: TrackerEndReason? = null,
    /** The location foreground service is running: positions keep coming with the app in the background. */
    val serviceRunning: Boolean = false,
    /** Bumped when the screen should ask the location permission (an auto-start without it). */
    val askPermission: Int = 0,
) {
    val running: Boolean get() = phase == TrackerPhase.STARTING || phase == TrackerPhase.ACTIVE

    /** Background sending is real only while the service runs for an active session (never claimed otherwise). */
    val backgroundActive: Boolean get() = phase == TrackerPhase.ACTIVE && serviceRunning
}

/** K1-K3 as the tracker needs them. */
interface TrackerApi {
    suspend fun create(tripId: String, deviceId: String, appVersion: String): TrackingSessionDTO
    suspend fun send(sessionId: String, points: List<TrackingPointIn>): PointsBatchAck
    suspend fun close(sessionId: String)
}

/** The outbox file (one per install). */
interface TrackerStorage {
    fun read(): String?
    fun write(value: String)
    fun clear()
}

/** Everything the phone provides; a fake in unit tests. */
interface TrackerPlatform {
    /** Play services location exists on this phone. */
    fun available(): Boolean
    fun access(): LocationAccess

    /** Continuous updates (the provider's own cadence; sampling happens in the tracker). */
    fun startUpdates(intervalMs: Long, onFix: (GeoFix) -> Unit)
    fun stopUpdates()

    /** One fresh position (heartbeat for a standing car). [onDone] with null when none came. */
    fun requestCurrent(onDone: (GeoFix?) -> Unit)
    fun battery(): BatteryState?

    /** No activity of this app is started. */
    fun inBackground(): Boolean

    /** The ongoing-notification service; it reports back through [DriverTracker.setServiceRunning]. */
    fun startService(tripId: String)
    fun stopService()

    /** Connectivity came back; returns the unsubscribe. */
    fun onOnline(listener: () -> Unit): () -> Unit
    fun deviceId(): String
    val appVersion: String
}

/**
 * The driver's GPS publisher (spec §10.3, Q148): fixes -> outbox -> `points:batch`, for one running trip. A port of
 * the web `v2/driverTracker.ts`, made native: a foreground service of type `location` keeps the positions coming
 * while the app is in the background (the web cannot), and the notification says so.
 *
 * Lifecycle:
 *   start(trip)  - deliver what an earlier run left in storage to its own session, open a new writer session (K1),
 *                  move what that session could not take into the new one (renumbered), then watch the position and
 *                  send every `recommended_interval_s`. Points wait in the outbox across network failures and restarts.
 *   stop()       - the driver ends it: last flush, K3, forget the outbox.
 *   finishTrip() - the trip is completing: flush first, then the server closes the session as part of `complete`.
 * The server may end the session on its own - another device took over (`superseded`) or the trip ended (`closed`).
 *
 * All state lives on [scope] (one thread): every entry point hops onto it, so a late answer from an older run is
 * recognised by [generation] and ignored.
 */
class DriverTracker(
    private val api: TrackerApi,
    private val storage: TrackerStorage,
    private val platform: TrackerPlatform,
    private val scope: CoroutineScope,
    private val now: () -> Long = System::currentTimeMillis,
) {
    private val _state = MutableStateFlow(TrackerSnapshot())
    val state: StateFlow<TrackerSnapshot> = _state.asStateFlow()

    private var outbox: Outbox? = null
    private var lastRecorded: GeoFix? = null
    private var pendingFix: GeoFix? = null
    private var timer: Job? = null
    private var flushing: Job? = null
    private var unsubscribeOnline: (() -> Unit)? = null
    private var intervalMs = DEFAULT_INTERVAL_MS
    private var heartbeatPending = false
    private var backgroundSinceLastFix = false
    private var batchLimit = GpsOutbox.MAX_POINTS_PER_BATCH
    private var generation = 0

    private fun update(change: (TrackerSnapshot) -> TrackerSnapshot) = _state.update(change)

    private fun syncQueue() = update { it.copy(queued = outbox?.points?.size ?: 0, dropped = outbox?.dropped ?: it.dropped) }

    // --- commands -------------------------------------------------------------------------------------------------

    /** Whether this trip is already being published (or is on its way to be). */
    fun isRunning(tripId: String? = null): Boolean {
        val s = _state.value
        return s.running && (tripId == null || s.tripId == tripId)
    }

    fun start(tripId: String): Job = scope.launch { startNow(tripId) }

    fun stop(): Job = scope.launch { stopNow() }

    /** After `start_boarding` / `depart`: start unless this trip already publishes. */
    fun autoStart(tripId: String): Job = scope.launch { if (!isRunning(tripId)) startNow(tripId) }

    /**
     * On app start with a running trip: resume without a question only when the permission is already there and
     * nothing has run in this process yet (a driver who pressed "To'xtatish" is not overruled).
     */
    fun resume(tripId: String): Job = scope.launch {
        if (_state.value.phase == TrackerPhase.IDLE && platform.access() != LocationAccess.NONE) startNow(tripId)
    }

    /** The permission question was answered (or the person came back from the settings). */
    fun accessChanged(granted: Boolean): Job = scope.launch {
        val s = _state.value
        val tripId = s.tripId ?: return@launch
        when {
            granted && platform.access() != LocationAccess.NONE && (s.phase == TrackerPhase.NEEDS_PERMISSION || s.phase == TrackerPhase.PERMISSION_DENIED) -> startNow(tripId)
            !granted && s.phase == TrackerPhase.NEEDS_PERMISSION -> update { it.copy(phase = TrackerPhase.PERMISSION_DENIED, access = LocationAccess.NONE) }
        }
    }

    /** Called right before the trip's `complete`: the last points go out while the session still accepts them. */
    suspend fun flushBeforeComplete(tripId: String) {
        if (_state.value.tripId == tripId && _state.value.phase == TrackerPhase.ACTIVE) onScope { flushAll() }
    }

    /** The trip completed or was cancelled: the server closed the session; end quietly. */
    fun tripEnded(tripId: String): Job = scope.launch {
        if (_state.value.tripId == tripId && _state.value.phase != TrackerPhase.IDLE) end(TrackerEndReason.TRIP_FINISHED)
    }

    /** Sign-out: deliver and close while the token still works, then forget everything of this person. */
    suspend fun signOut() {
        onScope {
            stopNow()
            generation += 1
            _state.value = TrackerSnapshot(serviceRunning = _state.value.serviceRunning)
        }
    }

    fun onFix(fix: GeoFix) {
        val gen = generation
        scope.launch { handleFix(gen, fix) }
    }

    fun setServiceRunning(running: Boolean) = update { it.copy(serviceRunning = running) }

    /** Send what is queued now (the network came back, the screen asked). */
    fun flush(): Job = scope.launch { flushAll() }

    private suspend fun onScope(block: suspend () -> Unit) {
        scope.launch { block() }.join()
    }

    // --- start / stop -----------------------------------------------------------------------------------------------

    internal suspend fun startNow(tripId: String) {
        if (isRunning(tripId)) return
        if (isRunning()) stopNow()
        val gen = ++generation
        val kept = _state.value
        val base = TrackerSnapshot(battery = kept.battery, serviceRunning = kept.serviceRunning, askPermission = kept.askPermission, tripId = tripId)
        if (!platform.available()) {
            _state.value = base.copy(phase = TrackerPhase.UNAVAILABLE)
            return
        }
        val access = platform.access()
        if (access == LocationAccess.NONE) {
            // The screen asks; the answer comes back through accessChanged().
            _state.value = base.copy(phase = TrackerPhase.NEEDS_PERMISSION, access = access, askPermission = kept.askPermission + 1)
            return
        }
        _state.value = base.copy(phase = TrackerPhase.STARTING, access = access, battery = platform.battery() ?: kept.battery)

        // An earlier run's points belong to that run's session: deliver them there first, while it is still the
        // active one (the K1 below supersedes it). What it could not take moves to the new session of the same trip;
        // storage is only overwritten once the new session exists.
        val stored = GpsOutbox.parse(read())
        val leftover = stored?.let { drainLeftover(it) }
        if (gen != generation) return

        val session = try {
            api.create(tripId, platform.deviceId(), platform.appVersion)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            if (gen != generation) return
            update { it.copy(phase = TrackerPhase.ERROR, errorCode = (e as? ApiException)?.code ?: ApiException.NETWORK) }
            return
        }
        if (gen != generation) return

        val fresh = GpsOutbox.empty(tripId, session.id)
        outbox = if (leftover != null && leftover.tripId == tripId) GpsOutbox.adoptPoints(fresh, leftover, now()) else fresh
        lastRecorded = null
        pendingFix = null
        heartbeatPending = false
        batchLimit = GpsOutbox.MAX_POINTS_PER_BATCH
        intervalMs = session.recommendedIntervalS.coerceAtLeast(MIN_INTERVAL_S) * 1000
        persist()
        update { it.copy(phase = TrackerPhase.ACTIVE, sessionId = session.id, errorCode = null, endReason = null) }
        syncQueue()
        if (outbox?.points?.isNotEmpty() == true) scope.launch { flushAll() }

        backgroundSinceLastFix = platform.inBackground()
        platform.startUpdates(UPDATE_INTERVAL_MS) { fix -> onFix(fix) }
        platform.startService(tripId)
        unsubscribeOnline = platform.onOnline { flush() }
        timer = scope.launch {
            while (isActive) {
                delay(intervalMs)
                if (gen != generation) break
                tick(gen)
            }
        }
    }

    internal suspend fun stopNow() {
        val sessionId = _state.value.sessionId
        val wasActive = _state.value.phase == TrackerPhase.ACTIVE
        if (wasActive) flushAll()
        teardown()
        generation += 1
        if (wasActive && sessionId != null) {
            try {
                api.close(sessionId)
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                // The server closes the session with the trip anyway; the local stop stands.
            }
        }
        clearStorage()
        outbox = null
        update { it.copy(phase = TrackerPhase.ENDED, endReason = TrackerEndReason.STOPPED, queued = 0, offline = false) }
    }

    private fun end(reason: TrackerEndReason) {
        teardown()
        generation += 1
        clearStorage()
        val dropped = (outbox?.dropped ?: _state.value.dropped) + (outbox?.points?.size ?: 0)
        outbox = null
        update { it.copy(phase = TrackerPhase.ENDED, endReason = reason, queued = 0, dropped = dropped, offline = false) }
    }

    private fun teardown() {
        platform.stopUpdates()
        platform.stopService()
        timer?.cancel()
        timer = null
        unsubscribeOnline?.invoke()
        unsubscribeOnline = null
    }

    // --- fixes ----------------------------------------------------------------------------------------------------

    private fun handleFix(gen: Int, raw: GeoFix) {
        if (gen != generation || outbox == null) return
        heartbeatPending = false
        val s = _state.value
        val previous = s.lastFixAt
        var gap = s.lastGap
        var gaps = s.gapCount
        // Screen lock without the service, GPS switched off: the history really has a hole there - name it, never fill it.
        if (previous != null && raw.timeMs - previous > GAP_THRESHOLD_MS) {
            gap = TrackerGap(previous, raw.timeMs, if (backgroundSinceLastFix) TrackerGap.Cause.BACKGROUND else TrackerGap.Cause.NO_FIX)
            gaps += 1
        }
        backgroundSinceLastFix = platform.inBackground() && !s.serviceRunning
        val battery = platform.battery() ?: s.battery
        update {
            it.copy(
                lastFixAt = if (previous == null) raw.timeMs else maxOf(previous, raw.timeMs),
                lastAccuracyM = raw.accuracy.takeIf { a -> a.isFinite() }?.let { a -> Math.round(a) },
                lastGap = gap,
                gapCount = gaps,
                battery = battery,
            )
        }
        val fix = raw.copy(battery = battery?.pct)
        if (!GpsOutbox.shouldRecord(lastRecorded, fix)) {
            // Too soon after the last kept fix - but it may be the car's final position before it stops. Keep the
            // newest one; the next tick records it.
            val last = lastRecorded
            if (last == null || fix.timeMs > last.timeMs) pendingFix = fix
            return
        }
        record(fix)
    }

    private fun record(fix: GeoFix) {
        val box = outbox ?: return
        pendingFix = null
        val first = lastRecorded == null
        val next = GpsOutbox.enqueue(box, fix, now())
        if (next.nextSeq == box.nextSeq) return // a fix the contract would refuse: skipped, not sent
        outbox = next
        lastRecorded = fix
        persist()
        syncQueue()
        // The first point goes out at once, so a client does not wait a whole interval for the car to appear.
        if (first) scope.launch { flushAll() }
    }

    private suspend fun tick(gen: Int) {
        if (platform.access() == LocationAccess.NONE) {
            // Taken away in the settings: no position will come; queued points still go out.
            flushAll()
            if (gen != generation) return
            teardown()
            generation += 1
            update { it.copy(phase = TrackerPhase.PERMISSION_DENIED, access = LocationAccess.NONE) }
            return
        }
        val pending = pendingFix
        val last = lastRecorded
        if (pending != null && GpsOutbox.recordPending(last, pending)) record(pending) else pendingFix = null
        heartbeat(gen)
        flushAll()
    }

    /** One fresh fix when there was none for a while (a standing car, a lazy provider). */
    private fun heartbeat(gen: Int) {
        if (heartbeatPending) return
        if (platform.inBackground() && !_state.value.serviceRunning) return
        val last = _state.value.lastFixAt
        if (last != null && now() - last < HEARTBEAT_AFTER_MS) return
        heartbeatPending = true
        platform.requestCurrent { fix ->
            scope.launch {
                if (fix != null) handleFix(gen, fix) else heartbeatPending = false
            }
        }
    }

    // --- sending --------------------------------------------------------------------------------------------------

    /** Send queued batches until the queue is empty, the server ends the session, or the network fails. */
    internal suspend fun flushAll() {
        flushing?.let { if (it.isActive) return it.join() }
        val job = scope.launch { flushOnce() }
        flushing = job
        job.join()
    }

    private suspend fun flushOnce() {
        val gen = generation
        repeat(MAX_BATCHES_PER_FLUSH) {
            val box = outbox ?: return
            if (gen != generation) return
            val pruned = GpsOutbox.prune(box, now())
            outbox = pruned
            val batch = GpsOutbox.nextBatch(pruned, batchLimit)
            if (batch.isEmpty()) {
                syncQueue()
                return
            }
            val ack = try {
                api.send(pruned.sessionId, batch.map { it.toDto() })
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (gen != generation || outbox == null) return
                sessionEnd(e)?.let { reason ->
                    end(reason)
                    return
                }
                if (TrackerErrors.tooLarge(e) && batchLimit > 1) {
                    batchLimit = (batchLimit / 2).coerceAtLeast(1) // split and go on
                    return@repeat
                }
                if (TrackerErrors.transient(e)) {
                    update { it.copy(offline = true) }
                    return
                }
                // 422 and friends: this batch will never be accepted; drop it so it cannot block the rest.
                outbox = GpsOutbox.dropBatch(outbox ?: return, batch)
                persist()
                syncQueue()
                return@repeat
            }
            if (gen != generation) return
            outbox = GpsOutbox.applyAck(outbox ?: return, ack)
            persist()
            update { it.copy(lastSentAt = now(), offline = false) }
            syncQueue()
            if (ack.sessionStatus != TrackingSessionStatus.ACTIVE) {
                end(if (ack.sessionStatus == TrackingSessionStatus.SUPERSEDED) TrackerEndReason.SUPERSEDED else TrackerEndReason.CLOSED)
                return
            }
        }
    }

    /**
     * Best effort: an earlier run's points go to that run's session. Returns what is still undelivered (the network
     * failed, or that session no longer accepts points); per-point refusals are counted as missing history.
     */
    private suspend fun drainLeftover(leftover: Outbox): Outbox {
        var box = GpsOutbox.prune(leftover, now())
        var limit = GpsOutbox.MAX_POINTS_PER_BATCH
        var round = 0
        while (round < MAX_BATCHES_PER_FLUSH && box.points.isNotEmpty()) {
            round += 1
            val batch = GpsOutbox.nextBatch(box, limit)
            try {
                val ack = api.send(box.sessionId, batch.map { it.toDto() })
                box = GpsOutbox.applyAck(box, ack)
                if (ack.sessionStatus != TrackingSessionStatus.ACTIVE) break
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                when {
                    TrackerErrors.tooLarge(e) && limit > 1 -> limit = (limit / 2).coerceAtLeast(1)
                    !TrackerErrors.transient(e) && sessionEnd(e) == null -> box = GpsOutbox.dropBatch(box, batch)
                    else -> break
                }
            }
        }
        return box
    }

    private fun sessionEnd(error: Throwable): TrackerEndReason? = TrackerErrors.sessionEnd(error)

    // --- storage --------------------------------------------------------------------------------------------------

    private fun read(): String? = runCatching { storage.read() }.getOrNull()

    private fun persist() {
        val box = outbox ?: return
        runCatching { storage.write(GpsOutbox.serialize(box)) }
    }

    private fun clearStorage() {
        runCatching { storage.clear() }
    }

    companion object {
        /** Cap on batches sent back-to-back in one flush (a long offline stretch drains over several ticks). */
        const val MAX_BATCHES_PER_FLUSH = 20

        /** A standing phone may stop reporting: after this long without a fix one fresh position is asked for. */
        const val HEARTBEAT_AFTER_MS = 25_000L

        /** No position for longer than this is a gap worth telling the driver about. */
        const val GAP_THRESHOLD_MS = 90_000L

        /** At or below this level, without a charger, battery saver is likely to throttle location. */
        const val LOW_BATTERY_PCT = 20

        /** What the provider is asked for; the outbox keeps one per 10 s moving / 30 s standing. */
        const val UPDATE_INTERVAL_MS = 5_000L
        private const val DEFAULT_INTERVAL_MS = 10_000L
        private const val MIN_INTERVAL_S = 5L
    }
}

/** How a K1/K2 failure is read (pure, shared with the tests). */
object TrackerErrors {
    const val SUPERSEDED = "TRACKING_SESSION_SUPERSEDED"
    const val CLOSED = "TRACKING_SESSION_CLOSED"
    const val TOO_LARGE = "TRACKING_BATCH_TOO_LARGE"

    /** A failure after which retrying the same session is pointless. */
    fun sessionEnd(error: Throwable): TrackerEndReason? {
        val api = error as? ApiException ?: return null
        return when {
            api.code == SUPERSEDED -> TrackerEndReason.SUPERSEDED
            api.code == CLOSED || api.status == 404 -> TrackerEndReason.CLOSED
            api.status == 401 -> TrackerEndReason.UNAUTHORIZED
            else -> null
        }
    }

    /** Worth keeping the points for: no answer at all, a server fault, throttling, a timeout. */
    fun transient(error: Throwable): Boolean {
        val api = error as? ApiException ?: return true
        return api.code == ApiException.NETWORK || api.status == 0 || api.status >= 500 || api.status == 429 || api.status == 408
    }

    fun tooLarge(error: Throwable): Boolean = (error as? ApiException)?.code == TOO_LARGE
}
