package uz.elchi.app.feature.client

import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.ElchiJson
import uz.elchi.app.api.LiveSocket
import uz.elchi.app.api.LiveSocketFactory
import uz.elchi.app.api.LiveSocketListener
import uz.elchi.app.api.generated.BookingTrackingDTO
import uz.elchi.app.api.generated.TrackingFreshness

@OptIn(ExperimentalCoroutinesApi::class)
class LiveTrackingSessionTest {
    private fun dto(freshness: String = "fresh", open: Boolean = true, reason: String = "open"): String =
        """{"booking_id":"bkg_1","window":{"is_open":$open,"reason":"$reason","opens_at":null},"freshness":"$freshness",
        "last_point":{"lat":41.3,"lng":69.2,"accuracy_m":8,"low_accuracy":false,"captured_at":"2026-09-29T13:00:00Z","received_at":"2026-09-29T13:00:01Z"}}"""

    private fun tracking(freshness: String = "fresh"): BookingTrackingDTO = ElchiJson.decodeFromString(BookingTrackingDTO.serializer(), dto(freshness))

    private class FakeSocket(val url: String, val listener: LiveSocketListener) : LiveSocket {
        val sent = mutableListOf<String>()
        var closed = false
        override fun send(text: String): Boolean = sent.add(text)
        override fun close() {
            closed = true
        }
    }

    private class Sockets : LiveSocketFactory {
        val opened = mutableListOf<FakeSocket>()
        override fun open(url: String, listener: LiveSocketListener): LiveSocket = FakeSocket(url, listener).also { opened += it }
    }

    private fun windowClosed(reason: String) = ApiException(403, "TRACKING_WINDOW_NOT_OPEN", "closed", buildJsonObject { put("reason", reason) })

    @Test
    fun socketDeliversAndPollingStops_tokenGoesInTheFirstFrameNotTheUrl() = runTest {
        val sockets = Sockets()
        var fetches = 0
        var state = LiveState()
        val session = LiveTrackingSession("bkg_1", { fetches++; tracking("delayed") }, sockets, "ws://h/api/v2/ws", { "jwt-1" }, { state = it(state) })
        val job = launch { session.run() }
        runCurrent()
        assertEquals(1, fetches)
        assertEquals(1, sockets.opened.size)
        assertEquals("ws://h/api/v2/ws", sockets.opened[0].url)
        sockets.opened[0].listener.onOpen()
        runCurrent()
        val frame = sockets.opened[0].sent.single()
        assertTrue(frame.contains("\"action\":\"subscribe\"") && frame.contains("\"booking_id\":\"bkg_1\"") && frame.contains("\"access_token\":\"jwt-1\""))
        sockets.opened[0].listener.onMessage("""{"type":"tracking.point","booking_id":"bkg_1","data":${dto("fresh")}}""")
        runCurrent()
        assertEquals(LiveTransport.SOCKET, state.transport)
        assertEquals(TrackingFreshness.FRESH, state.data?.freshness)
        // While the socket is live, the 15 s poll does not run.
        advanceTimeBy(46_000)
        runCurrent()
        assertEquals(1, fetches)
        // tracking.stale downgrades the shown bucket.
        sockets.opened[0].listener.onMessage("""{"type":"tracking.stale","data":{"freshness":"lost"}}""")
        runCurrent()
        assertEquals(TrackingFreshness.LOST, state.data?.freshness)
        job.cancel()
        runCurrent()
        assertTrue(sockets.opened[0].closed)
        assertEquals(LiveTransport.IDLE, state.transport)
    }

    @Test
    fun closedWindowPollsAndConnectsOnceItOpens() = runTest {
        val sockets = Sockets()
        var open = false
        var fetches = 0
        var state = LiveState()
        val session = LiveTrackingSession(
            "bkg_1",
            { fetches++; if (open) tracking() else throw windowClosed("parcel_not_picked_up") },
            sockets, "ws://h/api/v2/ws", { "jwt" }, { state = it(state) },
        )
        val job = launch { session.run() }
        runCurrent()
        assertEquals("parcel_not_picked_up", state.closedReason)
        assertTrue(sockets.opened.isEmpty()) // no socket while the window is closed
        open = true
        advanceTimeBy(15_001)
        runCurrent()
        assertEquals(2, fetches)
        assertEquals(null, state.closedReason)
        assertEquals(1, sockets.opened.size)
        job.cancel()
    }

    @Test
    fun finishedBookingStopsEverything() = runTest {
        val sockets = Sockets()
        var fetches = 0
        var state = LiveState()
        val session = LiveTrackingSession("bkg_1", { fetches++; throw windowClosed("booking_finished") }, sockets, "ws://h", { "jwt" }, { state = it(state) })
        session.run() // returns by itself
        assertEquals(1, fetches)
        assertEquals("booking_finished", state.closedReason)
        assertTrue(sockets.opened.isEmpty())
    }

    @Test
    fun closeCodes_4401RetriesOnceAfterAPoll_4403PollsAndWaits_4404Stops_othersBackOff() = runTest {
        val sockets = Sockets()
        var fetches = 0
        var state = LiveState()
        val session = LiveTrackingSession("bkg_1", { fetches++; tracking() }, sockets, "ws://h", { "jwt" }, { state = it(state) })
        val job = launch { session.run() }
        runCurrent()
        assertEquals(1, sockets.opened.size)
        // 4401: one HTTP call (which refreshes the token), then one new socket.
        sockets.opened[0].listener.onClosed(LiveTrackingSession.CLOSE_AUTH)
        runCurrent()
        assertEquals(2, fetches)
        assertEquals(2, sockets.opened.size)
        // A second 4401 without a delivered point: no more retries, polling only.
        sockets.opened[1].listener.onClosed(LiveTrackingSession.CLOSE_AUTH)
        runCurrent()
        assertEquals(2, sockets.opened.size)
        assertEquals(LiveTransport.POLL, state.transport)
        advanceTimeBy(15_001)
        runCurrent()
        assertEquals(3, fetches) // the first read, the auth poll, the 15 s tick
        job.cancel()

        // Any other close: reconnect after the 5 s backoff, doubling.
        val sockets2 = Sockets()
        val session2 = LiveTrackingSession("bkg_1", { tracking() }, sockets2, "ws://h", { "jwt" }, { })
        val job2 = launch { session2.run() }
        runCurrent()
        sockets2.opened[0].listener.onClosed(1011)
        runCurrent()
        advanceTimeBy(4_000)
        runCurrent()
        assertEquals(1, sockets2.opened.size)
        advanceTimeBy(1_500)
        runCurrent()
        assertEquals(2, sockets2.opened.size)
        sockets2.opened[1].listener.onClosed(LiveSocketListener.ABNORMAL)
        runCurrent()
        advanceTimeBy(9_000)
        runCurrent()
        assertEquals(2, sockets2.opened.size) // second wait is 10 s
        advanceTimeBy(1_500)
        runCurrent()
        assertEquals(3, sockets2.opened.size)
        job2.cancel()

        // 4404: gone, nothing retried, the session ends.
        val sockets3 = Sockets()
        var state3 = LiveState()
        val session3 = LiveTrackingSession("bkg_1", { tracking() }, sockets3, "ws://h", { "jwt" }, { state3 = it(state3) })
        val job3 = launch { session3.run() }
        runCurrent()
        sockets3.opened[0].listener.onClosed(LiveTrackingSession.CLOSE_NOT_FOUND)
        runCurrent()
        assertTrue(state3.gone)
        assertFalse(job3.isActive)
    }

    @Test
    fun slowerHttpAnswerDoesNotOverwriteASocketPoint() = runTest {
        val sockets = Sockets()
        var state = LiveState()
        var first = true
        val session = LiveTrackingSession(
            "bkg_1",
            { if (first) { first = false; tracking("fresh") } else tracking("lost") },
            sockets, "ws://h", { "jwt" }, { state = it(state) },
        )
        val job = launch { session.run() }
        runCurrent()
        sockets.opened[0].listener.onMessage("""{"type":"tracking.point","data":${dto("fresh")}}""")
        runCurrent()
        // 4403 then a poll: the socket is no longer live, the poll result is taken.
        sockets.opened[0].listener.onClosed(LiveTrackingSession.CLOSE_WINDOW)
        runCurrent()
        assertEquals(TrackingFreshness.LOST, state.data?.freshness)
        job.cancel()
    }
}
