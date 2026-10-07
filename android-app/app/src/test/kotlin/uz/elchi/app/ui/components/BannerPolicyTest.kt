package uz.elchi.app.ui.components

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.api.ApiException

class BannerPolicyTest {

    @Test
    fun `only success leaves after 4 seconds, errors, warnings and info stay until tapped`() {
        assertEquals(4_000L, BannerPolicy.autoHideMs(BannerTone.OK))
        assertNull(BannerPolicy.autoHideMs(BannerTone.INFO))
        assertNull(BannerPolicy.autoHideMs(BannerTone.WARN))
        assertNull(BannerPolicy.autoHideMs(BannerTone.ERR))
    }

    @Test
    fun `every banner that stays carries the close mark`() {
        assertFalse(BannerPolicy.closable(BannerTone.OK))
        assertTrue(BannerPolicy.closable(BannerTone.INFO))
        assertTrue(BannerPolicy.closable(BannerTone.WARN))
        assertTrue(BannerPolicy.closable(BannerTone.ERR))
    }

    @Test
    fun `a starting action leaves a standing warning in place`() {
        val center = BannerCenter()
        center.warning("CONTACT_INFO_MASKED")
        center.startAction()
        assertEquals(BannerTone.WARN, center.banner.value?.tone)
    }

    @Test
    fun `offline and 429 read the same everywhere, other codes keep their own sentence`() {
        assertEquals("error.offline", BannerPolicy.errorKey(ApiException(0, ApiException.NETWORK, "timeout")))
        assertEquals("error.RATE_LIMITED", BannerPolicy.errorKey(ApiException(429, "RATE_LIMITED", "slow down")))
        // v1 answers 429 with its own code; the status alone decides.
        assertEquals("error.RATE_LIMITED", BannerPolicy.errorKey(ApiException(429, "TOO_MANY_REQUESTS", "slow down")))
        assertNull(BannerPolicy.errorKey(ApiException(400, "ORDER_INVALID_STATUS", "x")))
        assertNull(BannerPolicy.errorKey(IllegalStateException()))
        assertEquals("warning.CONTACT_INFO_MASKED", BannerPolicy.warningKey("CONTACT_INFO_MASKED"))
    }

    @Test
    fun `the next action clears a standing error and shows the loading line`() {
        val center = BannerCenter()
        center.error(ApiException(0, ApiException.NETWORK, "offline"))
        assertEquals(BannerTone.ERR, center.banner.value?.tone)
        center.startAction()
        assertNull(center.banner.value)
        assertTrue(center.loading.value)
        center.endAction()
        assertFalse(center.loading.value)
    }

    @Test
    fun `a starting action leaves a success banner in place`() {
        val center = BannerCenter()
        center.ok(1)
        center.startAction()
        assertEquals(BannerTone.OK, center.banner.value?.tone)
    }

    @Test
    fun `dismissing an older banner keeps a newer one`() {
        val center = BannerCenter()
        center.warning("CONTACT_INFO_MASKED")
        val first = center.banner.value!!.id
        center.info(BannerText.Plain("new offer"))
        center.dismiss(first)
        assertEquals(BannerTone.INFO, center.banner.value?.tone)
        center.dismiss(center.banner.value!!.id)
        assertNull(center.banner.value)
    }

    @Test
    fun `a warning carries its dictionary key and the server's text as fallback`() {
        val center = BannerCenter()
        center.warning("CONTACT_INFO_MASKED", "masked")
        assertEquals(BannerText.Key("warning.CONTACT_INFO_MASKED", "masked"), center.banner.value?.text)
        assertEquals(BannerTone.WARN, center.banner.value?.tone)
    }
}
