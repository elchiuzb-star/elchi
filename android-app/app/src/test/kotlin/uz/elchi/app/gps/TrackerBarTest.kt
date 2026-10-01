package uz.elchi.app.gps

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class TrackerBarTest {
    private val now = 1_790_000_100_000L
    private val clock: (Long) -> String = { "T${(it - 1_790_000_000_000L) / 1000}" }

    private fun model(s: TrackerSnapshot, trip: String? = "trp_1") = TrackerBar.model(s, trip, now, clock)

    private fun keys(m: BarModel?) = m!!.notes.map { it.key }

    @Test
    fun `nothing is shown without a running trip unless something happened`() {
        assertNull(model(TrackerSnapshot(), trip = null))
        assertNull(model(TrackerSnapshot(phase = TrackerPhase.ENDED, endReason = TrackerEndReason.STOPPED), trip = null))
        assertEquals("driverTracking.superseded", model(TrackerSnapshot(phase = TrackerPhase.ENDED, endReason = TrackerEndReason.SUPERSEDED), trip = null)!!.title.key)
    }

    @Test
    fun `idle offers to start and says the permission question is coming`() {
        val m = model(TrackerSnapshot())!!
        assertEquals("driverTracking.idle", m.title.key)
        assertEquals(listOf("driverTracking.idleHint", "gps.permissionPrompt"), keys(m))
        assertEquals(BarAction.START, m.action)
        assertEquals(listOf("driverTracking.idleHint"), keys(model(TrackerSnapshot(access = LocationAccess.PRECISE))))
    }

    @Test
    fun `sending only for a fix of the last 30 s, background claimed only with the service`() {
        val live = TrackerSnapshot(phase = TrackerPhase.ACTIVE, tripId = "trp_1", lastFixAt = now - 20_000, lastSentAt = now - 5_000, access = LocationAccess.PRECISE)
        val m = model(live)!!
        assertEquals("driverTracking.sending", m.title.key)
        assertTrue(m.sending)
        assertEquals(BarDot.GREEN, m.dot)
        assertEquals(BarAction.STOP, m.action)
        assertEquals(listOf("driverTracking.lastSent", "driverTracking.foregroundOnly"), keys(m))
        assertEquals("T95", m.notes[0].params["time"])
        // The service runs: background sending is said - and only then.
        assertTrue("driver.gps.backgroundOn" in keys(model(live.copy(serviceRunning = true))))
        assertFalse("driver.gps.backgroundOn" in keys(model(live.copy(serviceRunning = true, phase = TrackerPhase.STARTING))))
        // A stale fix is not "sending".
        val stale = model(live.copy(lastFixAt = now - 31_000))!!
        assertEquals("driverTracking.waitingFix", stale.title.key)
        assertEquals(BarDot.AMBER, stale.dot)
        assertEquals("driverTracking.waitingFirstFix", model(live.copy(lastFixAt = null))!!.title.key)
    }

    @Test
    fun `every problem is named`() {
        val s = TrackerSnapshot(
            phase = TrackerPhase.ACTIVE, tripId = "trp_1", lastFixAt = now - 70_000, lastAccuracyM = 140, queued = 12, offline = true,
            battery = BatteryState(18, charging = false), access = LocationAccess.APPROXIMATE, dropped = 3,
            lastGap = TrackerGap(now - 800_000, now - 100_000, TrackerGap.Cause.NO_FIX),
        )
        val m = model(s)!!
        assertEquals(
            listOf(
                "driverTracking.lowAccuracy", "driverTracking.queuedOffline", "driverTracking.stalled", "driverTracking.gapNoFix",
                "driverTracking.lowBattery", "driver.gps.preciseOff", "driverTracking.foregroundOnly", "driverTracking.dropped",
            ),
            keys(m),
        )
        assertEquals("140", m.notes[0].params["meters"])
        assertEquals("12", m.notes[1].params["count"])
        assertEquals("18", m.notes[4].params["pct"])
        assertEquals("3", m.notes.last().params["count"])
        // Charging: no battery warning; queued but online: no offline line.
        val calm = keys(model(s.copy(battery = BatteryState(18, charging = true), offline = false)))
        assertFalse("driverTracking.lowBattery" in calm)
        assertFalse("driverTracking.queuedOffline" in calm)
    }

    @Test
    fun `failures map to their sentence and action`() {
        assertEquals(BarAction.PERMISSION, model(TrackerSnapshot(phase = TrackerPhase.PERMISSION_DENIED))!!.action)
        assertEquals(listOf("driver.gps.permissionHint"), keys(model(TrackerSnapshot(phase = TrackerPhase.PERMISSION_DENIED))))
        assertEquals("driver.gps.unavailable", model(TrackerSnapshot(phase = TrackerPhase.UNAVAILABLE))!!.title.key)
        assertEquals("driverTracking.error.network", model(TrackerSnapshot(phase = TrackerPhase.ERROR, errorCode = "NETWORK_ERROR"))!!.title.key)
        assertEquals("driverTracking.error.disabled", model(TrackerSnapshot(phase = TrackerPhase.ERROR, errorCode = "FEATURE_DISABLED"))!!.title.key)
        assertEquals("driverTracking.error.notRunning", model(TrackerSnapshot(phase = TrackerPhase.ERROR, errorCode = "INVALID_STATE_TRANSITION"))!!.title.key)
        assertEquals("driverTracking.error.generic", model(TrackerSnapshot(phase = TrackerPhase.ERROR, errorCode = "X"))!!.title.key)
        val superseded = model(TrackerSnapshot(phase = TrackerPhase.ENDED, tripId = "trp_1", endReason = TrackerEndReason.SUPERSEDED))!!
        assertEquals(BarAction.TAKE_OVER, superseded.action)
        assertEquals("driverTracking.closed", model(TrackerSnapshot(phase = TrackerPhase.ENDED, tripId = "trp_1", endReason = TrackerEndReason.CLOSED))!!.title.key)
        assertEquals("driverTracking.unauthorized", model(TrackerSnapshot(phase = TrackerPhase.ENDED, tripId = "trp_1", endReason = TrackerEndReason.UNAUTHORIZED))!!.title.key)
        val stopped = model(TrackerSnapshot(phase = TrackerPhase.ENDED, tripId = "trp_1", endReason = TrackerEndReason.STOPPED, dropped = 2))!!
        assertEquals("driverTracking.stopped", stopped.title.key)
        assertEquals(listOf("driverTracking.dropped"), keys(stopped))
        assertEquals("driverTracking.starting", model(TrackerSnapshot(phase = TrackerPhase.STARTING))!!.title.key)
    }

    @Test
    fun `another trip's publisher reads as idle for this screen's trip`() {
        val other = TrackerSnapshot(phase = TrackerPhase.ACTIVE, tripId = "trp_2", lastFixAt = now, access = LocationAccess.PRECISE)
        val m = model(other, trip = "trp_1")!!
        assertEquals("driverTracking.idle", m.title.key)
        assertEquals(BarAction.START, m.action)
    }
}
