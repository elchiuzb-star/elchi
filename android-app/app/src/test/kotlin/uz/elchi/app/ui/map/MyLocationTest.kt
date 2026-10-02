package uz.elchi.app.ui.map

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.ui.map.MyLocationPhase.ASKING
import uz.elchi.app.ui.map.MyLocationPhase.CENTRED
import uz.elchi.app.ui.map.MyLocationPhase.DENIED
import uz.elchi.app.ui.map.MyLocationPhase.IDLE
import uz.elchi.app.ui.map.MyLocationPhase.LOCATING
import uz.elchi.app.ui.map.MyLocationPhase.UNAVAILABLE

class MyLocationTest {
    private val now = 1_000_000_000L
    private val tashkent = UserFix(GeoPoint(41.2995, 69.2401), 20f, now)
    private val uzbekistan = listOf(GeoPoint(37.18, 55.99), GeoPoint(45.59, 73.15))

    @Test
    fun `a tap without permission asks for it, and only once while the dialog is up`() {
        val asking = MyLocation.tap(MyLocationState(), granted = false, locationOn = true, nowMs = now)
        assertEquals(ASKING, asking.phase)
        assertSame(asking, MyLocation.tap(asking, granted = false, locationOn = true, nowMs = now))
    }

    @Test
    fun `granted in the dialog - locating, then the first fix centres the camera`() {
        val asking = MyLocationState(phase = ASKING)
        val locating = MyLocation.permissionResult(asking, granted = true, locationOn = true, nowMs = now)
        assertEquals(LOCATING, locating.phase)
        assertEquals(1, locating.attempt)
        val centred = MyLocation.fix(locating, tashkent)
        assertEquals(CENTRED, centred.phase)
        assertEquals(1, centred.centre)
        assertEquals(tashkent, centred.fix)
    }

    @Test
    fun `refused in the dialog (or never asked again) - denied`() {
        val denied = MyLocation.permissionResult(MyLocationState(phase = ASKING), granted = false, locationOn = true, nowMs = now)
        assertEquals(DENIED, denied.phase)
    }

    @Test
    fun `a tap with a fresh known fix centres at once, a stale one waits`() {
        val known = MyLocationState(fix = tashkent)
        val centred = MyLocation.tap(known, granted = true, locationOn = true, nowMs = now + 5_000)
        assertEquals(CENTRED, centred.phase)
        assertEquals(1, centred.centre)
        val stale = MyLocation.tap(known, granted = true, locationOn = true, nowMs = now + MyLocation.FRESH_MS + 1)
        assertEquals(LOCATING, stale.phase)
        assertEquals(0, stale.centre)
    }

    @Test
    fun `every tap centres again`() {
        var s = MyLocationState(fix = tashkent)
        s = MyLocation.tap(s, granted = true, locationOn = true, nowMs = now)
        s = MyLocation.tap(s, granted = true, locationOn = true, nowMs = now)
        assertEquals(2, s.centre)
    }

    @Test
    fun `location switched off - unavailable without waiting`() {
        val s = MyLocation.tap(MyLocationState(), granted = true, locationOn = false, nowMs = now)
        assertEquals(UNAVAILABLE, s.phase)
        assertEquals(UNAVAILABLE, MyLocation.permissionResult(MyLocationState(phase = ASKING), granted = true, locationOn = false, nowMs = now).phase)
    }

    @Test
    fun `no fix in time - unavailable, but a stale timeout does not end a newer wait`() {
        val first = MyLocation.tap(MyLocationState(), granted = true, locationOn = true, nowMs = now)
        assertEquals(UNAVAILABLE, MyLocation.timeout(first, first.attempt).phase)
        val second = MyLocation.tap(MyLocation.timeout(first, first.attempt), granted = true, locationOn = true, nowMs = now)
        assertEquals(LOCATING, MyLocation.timeout(second, first.attempt).phase)
        // A timeout after the fix came changes nothing.
        val centred = MyLocation.fix(second, tashkent)
        assertSame(centred, MyLocation.timeout(centred, second.attempt))
    }

    @Test
    fun `fixes without a tap move the dot only`() {
        val s = MyLocation.fix(MyLocationState(), tashkent)
        assertEquals(IDLE, s.phase)
        assertEquals(0, s.centre)
        assertEquals(tashkent, s.fix)
    }

    @Test
    fun `a pan leaves centred and closes a banner, but not a wait`() {
        assertEquals(IDLE, MyLocation.panned(MyLocationState(phase = CENTRED)).phase)
        assertEquals(IDLE, MyLocation.panned(MyLocationState(phase = DENIED)).phase)
        assertEquals(IDLE, MyLocation.panned(MyLocationState(phase = UNAVAILABLE)).phase)
        assertEquals(LOCATING, MyLocation.panned(MyLocationState(phase = LOCATING)).phase)
        assertEquals(IDLE, MyLocation.dismiss(MyLocationState(phase = DENIED)).phase)
        assertEquals(CENTRED, MyLocation.dismiss(MyLocationState(phase = CENTRED)).phase)
    }

    @Test
    fun `back from the settings with the permission finishes the tap`() {
        val s = MyLocation.resumed(MyLocationState(phase = DENIED), granted = true, locationOn = true, nowMs = now)
        assertEquals(LOCATING, s.phase)
    }

    @Test
    fun `permission taken away drops the dot`() {
        val s = MyLocation.resumed(MyLocationState(phase = CENTRED, fix = tashkent), granted = false, locationOn = true, nowMs = now)
        assertNull(s.fix)
        assertEquals(IDLE, s.phase)
        // While the dialog is up the app is paused and resumed: nothing changes.
        val asking = MyLocationState(phase = ASKING)
        assertSame(asking, MyLocation.resumed(asking, granted = false, locationOn = true, nowMs = now))
    }

    @Test
    fun `automatic centring only on an empty, untouched home inside Uzbekistan`() {
        assertTrue(MyLocation.autoCentre(tashkent, nothingMarked = true, userMovedMap = false, bounds = uzbekistan))
        assertFalse(MyLocation.autoCentre(tashkent, nothingMarked = false, userMovedMap = false, bounds = uzbekistan))
        assertFalse(MyLocation.autoCentre(tashkent, nothingMarked = true, userMovedMap = true, bounds = uzbekistan))
        val mountainView = UserFix(GeoPoint(37.42, -122.08), 5f, now)
        assertFalse(MyLocation.autoCentre(mountainView, nothingMarked = true, userMovedMap = false, bounds = uzbekistan))
    }
}
