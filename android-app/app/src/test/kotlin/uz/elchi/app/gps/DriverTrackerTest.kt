package uz.elchi.app.gps

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.generated.PointRejectionDTO
import uz.elchi.app.api.generated.PointsBatchAck
import uz.elchi.app.api.generated.TrackingPointIn
import uz.elchi.app.api.generated.TrackingPointRejectReason
import uz.elchi.app.api.generated.TrackingSessionDTO
import uz.elchi.app.api.generated.TrackingSessionStatus

@OptIn(ExperimentalCoroutinesApi::class)
class DriverTrackerTest {
    private class FakeApi : TrackerApi {
        var created = mutableListOf<String>()
        val sent = mutableListOf<Pair<String, List<TrackingPointIn>>>()
        val closed = mutableListOf<String>()
        var createError: Exception? = null

        /** Default: accept everything. */
        var answer: (String, List<TrackingPointIn>) -> PointsBatchAck = { _, points -> PointsBatchAck(points.map { it.seq }, emptyList(), emptyList(), TrackingSessionStatus.ACTIVE) }

        override suspend fun create(tripId: String, deviceId: String, appVersion: String): TrackingSessionDTO {
            createError?.let { throw it }
            val id = "trs_${created.size + 1}"
            created += tripId
            return TrackingSessionDTO(id = id, recommendedIntervalS = 10, startedAt = "2026-10-01T08:00:00Z", status = TrackingSessionStatus.ACTIVE)
        }

        override suspend fun send(sessionId: String, points: List<TrackingPointIn>): PointsBatchAck {
            sent += sessionId to points
            return answer(sessionId, points)
        }

        override suspend fun close(sessionId: String) {
            closed += sessionId
        }
    }

    private class FakeStorage : TrackerStorage {
        var value: String? = null
        override fun read() = value
        override fun write(value: String) {
            this.value = value
        }

        override fun clear() {
            value = null
        }
    }

    private class FakePlatform : TrackerPlatform {
        var access = LocationAccess.PRECISE
        var available = true
        var onFix: ((GeoFix) -> Unit)? = null
        var online: (() -> Unit)? = null
        var serviceStarted = 0
        var serviceStopped = 0
        var updatesStopped = 0
        override fun available() = available
        override fun access() = access
        override fun startUpdates(intervalMs: Long, onFix: (GeoFix) -> Unit) {
            this.onFix = onFix
        }

        override fun stopUpdates() {
            updatesStopped += 1
            onFix = null
        }

        override fun requestCurrent(onDone: (GeoFix?) -> Unit) = onDone(null)
        override fun battery(): BatteryState? = BatteryState(64, charging = false)
        override fun inBackground() = false
        override fun startService(tripId: String) {
            serviceStarted += 1
        }

        override fun stopService() {
            serviceStopped += 1
        }

        override fun onOnline(listener: () -> Unit): () -> Unit {
            online = listener
            return { online = null }
        }

        override fun deviceId() = "android-test"
        override val appVersion = "android/test"
    }

    private var clock = 1_790_000_000_000L

    private fun fix(dtS: Long, lat: Double = 41.30, speed: Double? = 8.0) = GeoFix(lat, 69.24, 6.0, speed, 90.0, clock + dtS * 1000)

    private class Rig(val tracker: DriverTracker, val api: FakeApi, val storage: FakeStorage, val platform: FakePlatform, val job: Job)

    /** The tracker lives on [TestScope.backgroundScope]: its endless timer is cancelled when the test ends (also on failure). */
    private fun TestScope.rig(storage: FakeStorage = FakeStorage(), api: FakeApi = FakeApi(), platform: FakePlatform = FakePlatform()): Rig {
        val job = Job(backgroundScope.coroutineContext[Job])
        val scope = CoroutineScope(backgroundScope.coroutineContext + job)
        return Rig(DriverTracker(api, storage, platform, scope) { clock }, api, storage, platform, job)
    }

    @Test
    fun `start opens a session, the first fix goes out at once and the ACK empties the queue`() = runTest {
        val r = rig()
        r.tracker.start("trp_1")
        testScheduler.runCurrent()
        assertEquals(TrackerPhase.ACTIVE, r.tracker.state.value.phase)
        assertEquals(listOf("trp_1"), r.api.created)
        assertEquals(1, r.platform.serviceStarted)
        r.platform.onFix!!(fix(0))
        testScheduler.runCurrent()
        assertEquals(1, r.api.sent.size)
        assertEquals("trs_1", r.api.sent[0].first)
        assertEquals(0L, r.api.sent[0].second.single().seq)
        assertEquals(0, r.tracker.state.value.queued)
        assertEquals(clock, r.tracker.state.value.lastSentAt)
        r.job.cancel()
    }

    @Test
    fun `offline keeps the points queued and the network coming back drains them`() = runTest {
        val r = rig()
        var offline = true
        r.api.answer = { _, points ->
            if (offline) throw ApiException(0, ApiException.NETWORK, "down")
            PointsBatchAck(points.map { it.seq }, emptyList(), emptyList(), TrackingSessionStatus.ACTIVE)
        }
        r.tracker.start("trp_1")
        testScheduler.runCurrent()
        // Moving: one point per 10 s is kept.
        (0..4).forEach { r.platform.onFix!!(fix(it * 10L, lat = 41.30 + it * 0.001)) }
        testScheduler.runCurrent()
        val s = r.tracker.state.value
        assertTrue(s.offline)
        assertEquals(5, s.queued)
        assertTrue(r.storage.value!!.contains("trs_1")) // persisted across a restart
        offline = false
        r.platform.online!!()
        testScheduler.runCurrent()
        assertFalse(r.tracker.state.value.offline)
        assertEquals(0, r.tracker.state.value.queued)
        assertEquals(listOf(0L, 1L, 2L, 3L, 4L), r.api.sent.last().second.map { it.seq })
        r.job.cancel()
    }

    @Test
    fun `fixes too close together wait for the tick, the newest one is kept`() = runTest {
        val r = rig()
        r.tracker.start("trp_1")
        testScheduler.runCurrent()
        r.platform.onFix!!(fix(0))
        r.platform.onFix!!(fix(3, lat = 41.3001))
        r.platform.onFix!!(fix(6, lat = 41.3004)) // ~44 m away: the car's new place
        testScheduler.runCurrent()
        assertEquals(1, r.api.sent.sumOf { it.second.size })
        clock += 10_000
        testScheduler.advanceTimeBy(10_001)
        testScheduler.runCurrent()
        val all = r.api.sent.flatMap { it.second }
        assertEquals(2, all.size)
        assertEquals(41.3004, all.last().lat, 1e-9)
        r.job.cancel()
    }

    @Test
    fun `a standing phone reporting every 5 s keeps one point per 30 s`() = runTest {
        val r = rig()
        r.tracker.start("trp_1")
        testScheduler.runCurrent()
        val base = clock
        // 65 s of a standing phone: a fix every 5 s, the tracker's tick every 10 s.
        for (second in 0..65 step 5) {
            clock = base + second * 1000L
            r.platform.onFix!!(GeoFix(41.30, 69.24, 6.0, 0.0, null, clock))
            testScheduler.advanceTimeBy(5_000)
            testScheduler.runCurrent()
        }
        val times = r.api.sent.flatMap { it.second }.map { java.time.Instant.parse(it.capturedAt).toEpochMilli() - base }
        assertEquals(listOf(0L, 30_000L, 60_000L), times)
        r.job.cancel()
    }

    @Test
    fun `superseded by another device stops publishing and says so`() = runTest {
        val r = rig()
        r.api.answer = { _, _ -> throw ApiException(409, TrackerErrors.SUPERSEDED, "superseded") }
        r.tracker.start("trp_1")
        testScheduler.runCurrent()
        r.platform.onFix!!(fix(0))
        testScheduler.runCurrent()
        val s = r.tracker.state.value
        assertEquals(TrackerPhase.ENDED, s.phase)
        assertEquals(TrackerEndReason.SUPERSEDED, s.endReason)
        assertEquals(1, s.dropped) // the point that could not go is said, not hidden
        assertNull(r.storage.value)
        assertTrue(r.platform.serviceStopped > 0)
        // "Shu telefondan yuborish": a new session.
        r.api.answer = { _, points -> PointsBatchAck(points.map { it.seq }, emptyList(), emptyList(), TrackingSessionStatus.ACTIVE) }
        r.tracker.start("trp_1")
        testScheduler.runCurrent()
        assertEquals(TrackerPhase.ACTIVE, r.tracker.state.value.phase)
        assertEquals(2, r.api.created.size)
        r.job.cancel()
    }

    @Test
    fun `an ACK saying closed ends quietly as closed`() = runTest {
        val r = rig()
        r.api.answer = { _, points -> PointsBatchAck(points.map { it.seq }, emptyList(), emptyList(), TrackingSessionStatus.CLOSED) }
        r.tracker.start("trp_1")
        testScheduler.runCurrent()
        r.platform.onFix!!(fix(0))
        testScheduler.runCurrent()
        assertEquals(TrackerEndReason.CLOSED, r.tracker.state.value.endReason)
        r.job.cancel()
    }

    @Test
    fun `leftovers go to their own session first, the rest is renumbered into the new one`() = runTest {
        val storage = FakeStorage()
        val old = GpsOutbox.empty("trp_1", "trs_old").copy(
            nextSeq = 12,
            points = (10L..11L).map { QueuedPoint(it, clock - 60_000 + it * 1000, 41.0, 69.0, 5) },
        )
        storage.value = GpsOutbox.serialize(old)
        val r = rig(storage = storage)
        // The old session no longer takes points (network fine, but superseded on its side).
        r.api.answer = { session, points ->
            if (session == "trs_old") throw ApiException(409, TrackerErrors.SUPERSEDED, "superseded")
            PointsBatchAck(points.map { it.seq }, emptyList(), emptyList(), TrackingSessionStatus.ACTIVE)
        }
        r.tracker.start("trp_1")
        testScheduler.runCurrent()
        assertEquals("trs_old", r.api.sent[0].first)
        val toNew = r.api.sent.last()
        assertEquals("trs_1", toNew.first)
        assertEquals(listOf(0L, 1L), toNew.second.map { it.seq }) // renumbered in capture order
        assertEquals(0, r.tracker.state.value.queued)
        r.job.cancel()
    }

    @Test
    fun `rejected points leave the queue and are counted, a 422 drops only its batch`() = runTest {
        val r = rig()
        var calls = 0
        r.api.answer = { _, points ->
            calls += 1
            if (calls == 1) PointsBatchAck(emptyList(), emptyList(), points.map { PointRejectionDTO(TrackingPointRejectReason.TOO_OLD, it.seq) }, TrackingSessionStatus.ACTIVE)
            else throw ApiException(422, "VALIDATION_ERROR", "bad")
        }
        r.tracker.start("trp_1")
        testScheduler.runCurrent()
        r.platform.onFix!!(fix(0))
        testScheduler.runCurrent()
        assertEquals(1, r.tracker.state.value.dropped)
        r.platform.onFix!!(fix(10, lat = 41.31))
        clock += 10_000
        testScheduler.advanceTimeBy(10_001)
        testScheduler.runCurrent()
        assertEquals(2, r.tracker.state.value.dropped)
        assertEquals(0, r.tracker.state.value.queued)
        assertFalse(r.tracker.state.value.offline)
        r.job.cancel()
    }

    @Test
    fun `a too large answer splits the batch`() = runTest {
        val storage = FakeStorage()
        storage.value = GpsOutbox.serialize(
            GpsOutbox.empty("trp_1", "trs_1").copy(nextSeq = 3, points = (0L..2L).map { QueuedPoint(it, clock - 5000 + it, 41.0, 69.0, 5) }),
        )
        val r = rig(storage = storage)
        r.api.answer = { _, points ->
            if (points.size > 1) throw ApiException(400, TrackerErrors.TOO_LARGE, "too large")
            PointsBatchAck(points.map { it.seq }, emptyList(), emptyList(), TrackingSessionStatus.ACTIVE)
        }
        r.tracker.start("trp_1")
        testScheduler.runCurrent()
        // Leftovers drained to trs_1 one by one after the splits.
        assertEquals(3, r.api.sent.count { it.second.size == 1 })
        assertEquals(0, r.tracker.state.value.queued)
        r.job.cancel()
    }

    @Test
    fun `without the permission it asks instead of opening a session, and resumes once granted`() = runTest {
        val r = rig()
        r.platform.access = LocationAccess.NONE
        r.tracker.autoStart("trp_1")
        testScheduler.runCurrent()
        val s = r.tracker.state.value
        assertEquals(TrackerPhase.NEEDS_PERMISSION, s.phase)
        assertEquals(1, s.askPermission)
        assertTrue(r.api.created.isEmpty())
        // Resume on app start never asks by itself.
        r.tracker.resume("trp_1")
        testScheduler.runCurrent()
        assertEquals(1, r.tracker.state.value.askPermission)
        // Denied in the dialog.
        r.tracker.accessChanged(false)
        testScheduler.runCurrent()
        assertEquals(TrackerPhase.PERMISSION_DENIED, r.tracker.state.value.phase)
        // Granted later (settings): publishing starts by itself, approximate is said.
        r.platform.access = LocationAccess.APPROXIMATE
        r.tracker.accessChanged(true)
        testScheduler.runCurrent()
        assertEquals(TrackerPhase.ACTIVE, r.tracker.state.value.phase)
        assertEquals(LocationAccess.APPROXIMATE, r.tracker.state.value.access)
        r.job.cancel()
    }

    @Test
    fun `stop flushes, closes the session and forgets the outbox`() = runTest {
        val r = rig()
        r.tracker.start("trp_1")
        testScheduler.runCurrent()
        r.platform.onFix!!(fix(0))
        testScheduler.runCurrent()
        r.tracker.stop()
        testScheduler.runCurrent()
        assertEquals(listOf("trs_1"), r.api.closed)
        assertEquals(TrackerEndReason.STOPPED, r.tracker.state.value.endReason)
        assertNull(r.storage.value)
        assertTrue(r.platform.updatesStopped > 0)
        assertFalse(r.tracker.isRunning())
        r.job.cancel()
    }

    @Test
    fun `a failed K1 is an error with the server's code, the stored points are kept`() = runTest {
        val storage = FakeStorage()
        storage.value = GpsOutbox.serialize(GpsOutbox.empty("trp_1", "trs_old").copy(nextSeq = 1, points = listOf(QueuedPoint(0, clock - 1000, 41.0, 69.0, 5))))
        val api = FakeApi().apply {
            createError = ApiException(409, "INVALID_STATE_TRANSITION", "trip_not_running")
            answer = { _, _ -> throw ApiException(0, ApiException.NETWORK, "down") }
        }
        val r = rig(storage = storage, api = api)
        r.tracker.start("trp_1")
        testScheduler.runCurrent()
        assertEquals(TrackerPhase.ERROR, r.tracker.state.value.phase)
        assertEquals("INVALID_STATE_TRANSITION", r.tracker.state.value.errorCode)
        assertTrue(r.storage.value!!.contains("trs_old"))
        r.job.cancel()
    }

    @Test
    fun `the trip ending stops quietly and resume does not overrule a stop`() = runTest {
        val r = rig()
        r.tracker.start("trp_1")
        testScheduler.runCurrent()
        r.tracker.tripEnded("trp_1")
        testScheduler.runCurrent()
        assertEquals(TrackerEndReason.TRIP_FINISHED, r.tracker.state.value.endReason)
        r.tracker.resume("trp_1")
        testScheduler.runCurrent()
        assertEquals(1, r.api.created.size)
        r.job.cancel()
    }

    @Test
    fun `unavailable location services never open a session`() = runTest {
        val r = rig()
        r.platform.available = false
        r.tracker.start("trp_1")
        testScheduler.runCurrent()
        assertEquals(TrackerPhase.UNAVAILABLE, r.tracker.state.value.phase)
        assertTrue(r.api.created.isEmpty())
        r.job.cancel()
    }

    @Test
    fun `errors are read the contract's way`() {
        assertEquals(TrackerEndReason.SUPERSEDED, TrackerErrors.sessionEnd(ApiException(409, "TRACKING_SESSION_SUPERSEDED", "")))
        assertEquals(TrackerEndReason.CLOSED, TrackerErrors.sessionEnd(ApiException(409, "TRACKING_SESSION_CLOSED", "")))
        assertEquals(TrackerEndReason.CLOSED, TrackerErrors.sessionEnd(ApiException(404, "NOT_FOUND", "")))
        assertEquals(TrackerEndReason.UNAUTHORIZED, TrackerErrors.sessionEnd(ApiException(401, "UNAUTHORIZED", "")))
        assertNull(TrackerErrors.sessionEnd(ApiException(422, "VALIDATION_ERROR", "")))
        assertTrue(TrackerErrors.transient(ApiException(0, ApiException.NETWORK, "")))
        assertTrue(TrackerErrors.transient(ApiException(503, "SERVER_ERROR", "")))
        assertTrue(TrackerErrors.transient(ApiException(429, "RATE_LIMITED", "")))
        assertTrue(TrackerErrors.transient(IllegalStateException()))
        assertFalse(TrackerErrors.transient(ApiException(422, "VALIDATION_ERROR", "")))
        assertTrue(TrackerErrors.tooLarge(ApiException(400, "TRACKING_BATCH_TOO_LARGE", "")))
    }
}
