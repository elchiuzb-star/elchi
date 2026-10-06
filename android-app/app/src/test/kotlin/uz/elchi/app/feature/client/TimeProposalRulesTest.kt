package uz.elchi.app.feature.client

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import uz.elchi.app.feature.driver.S08

/** ADR-0027 (Q153): the client's line for a driver's time proposal. */
class TimeProposalRulesTest {
    @Test
    fun `a time proposal reads the driver's pickup against the client's own window`() {
        val v = S08.version().copy(outsideRequestWindow = true, pickupWindowStart = "2026-10-06T17:30:00Z")
        assertEquals(
            TimeProposalParts(time = "06.10, 22:30", start = "06.10, 13:00", end = "15:00"),
            TimeProposalRules.parts(v, "2026-10-06T08:00:00Z", "2026-10-06T10:00:00Z"),
        )
        // The window unknown (a thread without its listing at hand): the time still shows.
        assertEquals(TimeProposalParts("06.10, 22:30", "-", "-"), TimeProposalRules.parts(v, null, null))
    }

    @Test
    fun `an ordinary offer has no line`() {
        assertNull(TimeProposalRules.parts(S08.version(), "2026-10-06T08:00:00Z", "2026-10-06T10:00:00Z"))
        assertNull(TimeProposalRules.parts(S08.version().copy(outsideRequestWindow = false), null, null))
        assertNull(TimeProposalRules.parts(null, null, null))
    }
}
