package uz.elchi.app.feature.client

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.LegacyCity
import uz.elchi.app.api.LegacyDriver
import uz.elchi.app.api.LegacyOrderDetail
import java.time.Instant
import java.time.LocalDateTime
import java.util.Locale

class LegacyRulesTest {

    // -- status -> actions --------------------------------------------------------------------------------------

    @Test
    fun `each v1 status offers exactly the actions left in its life cycle`() {
        val expected = mapOf(
            "draft" to LegacyActions(cancel = true),
            "published" to LegacyActions(viewBids = true, cancel = true),
            "bidding" to LegacyActions(viewBids = true, cancel = true),
            "accepted" to LegacyActions(cancel = true, report = true),
            "picked_up" to LegacyActions(report = true),
            "in_transit" to LegacyActions(report = true),
            "delivered" to LegacyActions(confirmDelivery = true, report = true),
            "confirmed" to LegacyActions(rate = true),
            "cancelled" to LegacyActions(),
            "disputed" to LegacyActions(),
            "something_new" to LegacyActions(),
        )
        expected.forEach { (status, actions) -> assertEquals(status, actions, LegacyRules.actions(status, ratedThisSession = false)) }
    }

    @Test
    fun `a confirmed order rated in this session no longer offers the rating`() {
        assertEquals(LegacyActions(), LegacyRules.actions("confirmed", ratedThisSession = true))
        // Rating only follows a confirmation: the flag changes nothing elsewhere.
        assertEquals(LegacyActions(confirmDelivery = true, report = true), LegacyRules.actions("delivered", ratedThisSession = true))
    }

    @Test
    fun `bids are open only while published or bidding`() {
        assertTrue(LegacyRules.bidsOpen("published"))
        assertTrue(LegacyRules.bidsOpen("bidding"))
        listOf("draft", "accepted", "in_transit", "delivered", "confirmed", "cancelled", "disputed").forEach { assertFalse(it, LegacyRules.bidsOpen(it)) }
    }

    @Test
    fun `the cancel sheet says a driver is waiting only once one was chosen`() {
        assertEquals("confirmDialog.cancelOrder.acceptedText", LegacyRules.cancelTextKey("accepted"))
        listOf("draft", "published", "bidding").forEach { assertEquals("confirmDialog.cancelOrder.text", LegacyRules.cancelTextKey(it)) }
    }

    // -- phone ----------------------------------------------------------------------------------------------------

    @Test
    fun `the driver's phone shows from accepted on and never before`() {
        val driver = LegacyDriver(fullName = "Sardor", phone = "+998931112233")
        listOf("accepted", "picked_up", "in_transit", "delivered", "confirmed", "disputed").forEach {
            assertTrue(it, LegacyRules.phoneVisible(it))
            assertEquals(it, "+998931112233", LegacyRules.driverPhone(it, driver))
        }
        listOf("draft", "published", "bidding", "cancelled").forEach {
            assertFalse(it, LegacyRules.phoneVisible(it))
            assertNull(it, LegacyRules.driverPhone(it, driver))
        }
        assertNull(LegacyRules.driverPhone("accepted", driver.copy(phone = " ")))
        assertNull(LegacyRules.driverPhone("accepted", null))
    }

    // -- dispute --------------------------------------------------------------------------------------------------

    @Test
    fun `the dispute sends the server's enum code, never a sentence`() {
        assertEquals(
            listOf("delayed", "lost", "damaged", "receiver_denied", "wrong_address", "payment_issue", "prohibited_item", "other"),
            LegacyRules.DISPUTE_REASONS,
        )
        assertEquals("delayed", LegacyRules.DEFAULT_DISPUTE_REASON)
        assertEquals("lost", LegacyRules.disputeReason("lost"))
        // The web client's Uzbek text is refused by the server with 400: it falls back to the default code.
        assertEquals("delayed", LegacyRules.disputeReason("Haydovchi kelmadi"))
        assertEquals("delayed", LegacyRules.disputeReason(null))
        assertEquals("client.legacy.dispute.reason.receiver_denied", LegacyRules.disputeReasonKey("receiver_denied"))
    }

    // -- Yandex links -------------------------------------------------------------------------------------------

    @Test
    fun `the pickup link puts longitude first and the route link latitude first`() {
        assertEquals("https://yandex.uz/maps/?pt=69.2401,41.2995&z=16&l=map", LegacyRules.yandexPointUrl(lat = 41.2995, lng = 69.2401))
        assertEquals("https://yandex.uz/maps/?rtext=~39.6542,66.9597&rtt=auto", LegacyRules.yandexRouteUrl(lat = 39.6542, lng = 66.9597))
        // Whole degrees and tiny fractions stay plain decimals (no "1.0E-4").
        assertEquals("https://yandex.uz/maps/?pt=69,41&z=16&l=map", LegacyRules.yandexPointUrl(41.0, 69.0))
        assertEquals("https://yandex.uz/maps/?rtext=~0.0001,66.5&rtt=auto", LegacyRules.yandexRouteUrl(0.0001, 66.5))
    }

    @Test
    fun `a map point needs both halves and is not the empty 0,0`() {
        assertTrue(LegacyRules.hasPoint(41.3, 69.2))
        assertFalse(LegacyRules.hasPoint(41.3, null))
        assertFalse(LegacyRules.hasPoint(null, 69.2))
        assertFalse(LegacyRules.hasPoint(0.0, 0.0))
        val order = LegacyOrderDetail(id = 1, status = "bidding", dropoffLat = 39.6, dropoffLng = 66.9)
        assertTrue(LegacyRules.hasAnyPoint(order))
        assertFalse(LegacyRules.hasAnyPoint(order.copy(dropoffLng = null)))
    }

    // -- money ----------------------------------------------------------------------------------------------------

    @Test
    fun `the price is decimal so'm, agreed before the client's before the suggested`() {
        val order = LegacyOrderDetail(
            id = 4, status = "in_transit",
            suggestedPrice = JsonPrimitive(60000.0), clientPrice = JsonPrimitive(67000.0), finalPrice = JsonPrimitive(72000.0),
        )
        assertEquals(7_200_000L, LegacyRules.priceMinor(order))
        assertEquals(6_700_000L, LegacyRules.priceMinor(order.copy(finalPrice = JsonNull)))
        assertEquals(6_000_000L, LegacyRules.priceMinor(order.copy(finalPrice = null, clientPrice = null)))
        assertEquals(6_550_050L, LegacyRules.priceMinor(order.copy(finalPrice = JsonPrimitive("65500.50"))))
        assertNull(LegacyRules.priceMinor(order.copy(finalPrice = null, clientPrice = null, suggestedPrice = JsonPrimitive("0"))))
        assertEquals(6_800_000L, LegacyRules.bidPriceMinor(JsonPrimitive(68000.0)))
        assertEquals("68${ParcelRules.NBSP}000${ParcelRules.NBSP}so'm", ParcelRules.formatSoum(LegacyRules.bidPriceMinor(JsonPrimitive(68000.0))!!, "so'm"))
    }

    @Test
    fun `a driver without ratings shows no score, a rated one a comma decimal`() {
        assertNull(LegacyRules.ratingText(0.0, Locale.forLanguageTag("uz")))
        assertNull(LegacyRules.ratingText(null, Locale.forLanguageTag("uz")))
        assertEquals("★ 4,6", LegacyRules.ratingText(4.62, Locale.forLanguageTag("uz")))
        assertEquals("★ 5,0", LegacyRules.ratingText(5.0, Locale.forLanguageTag("ru")))
    }

    @Test
    fun `the route names the regions, else the districts`() {
        val order = LegacyOrderDetail(id = 1, status = "published", fromCity = LegacyCity(1, "Toshkent shahri"), toCity = LegacyCity(3, "Samarqand viloyati"))
        assertEquals("Toshkent shahri → Samarqand viloyati", LegacyRules.route(order))
        assertEquals("? → ?", LegacyRules.route(LegacyOrderDetail(id = 2, status = "draft")))
    }

    // -- time -----------------------------------------------------------------------------------------------------

    @Test
    fun `a naive v1 timestamp is UTC and shows on the Tashkent clock`() {
        assertEquals(Instant.parse("2026-09-30T10:28:41.297437Z"), LegacyRules.parseTimestamp("2026-09-30T10:28:41.297437"))
        assertEquals(LocalDateTime.of(2026, 9, 30, 15, 28, 41, 297_437_000), LegacyRules.tashkent("2026-09-30T10:28:41.297437"))
        assertEquals("30.09, 15:28", LegacyRules.displayTime("2026-09-30T10:28:41.297437"))
    }

    @Test
    fun `an offset or Z timestamp is read as given`() {
        assertEquals("30.09, 15:28", LegacyRules.displayTime("2026-09-30T15:28:41.270557+05:00"))
        assertEquals("30.09, 15:28", LegacyRules.displayTime("2026-09-30T10:28:41Z"))
        // Just before midnight UTC is already the next day in Tashkent.
        assertEquals("01.10, 03:30", LegacyRules.displayTime("2026-09-30T22:30:00"))
        assertEquals("2026-09-30T22:30:00Z", LegacyRules.isoInstant("2026-09-30T22:30:00"))
        assertNull(LegacyRules.displayTime(""))
        assertNull(LegacyRules.displayTime("yesterday"))
        assertNull(LegacyRules.displayTime(null))
    }

    // -- refusals -------------------------------------------------------------------------------------------------

    @Test
    fun `404 and 403 are the not-found state, other failures are not`() {
        assertTrue(LegacyRules.isNotFound(ApiException(404, "NOT_FOUND", "Order not found")))
        assertTrue(LegacyRules.isNotFound(ApiException(403, "FORBIDDEN", "not yours")))
        assertFalse(LegacyRules.isNotFound(ApiException(0, ApiException.NETWORK, "offline")))
        assertFalse(LegacyRules.isNotFound(ApiException(500, "SERVER_ERROR", "boom")))
        assertFalse(LegacyRules.isNotFound(IllegalStateException()))
    }

    @Test
    fun `v1 refusals read as client sentences`() {
        assertEquals("client.legacy.error.orderChanged", LegacyRules.errorKey(ApiException(400, "ORDER_INVALID_STATUS", "x")))
        assertEquals("client.legacy.error.bidGone", LegacyRules.errorKey(ApiException(409, "BID_NOT_ACTIVE", "x")))
        listOf("DRIVER_NOT_APPROVED", "DRIVER_BLOCKED", "DRIVER_NOT_AVAILABLE").forEach {
            assertEquals(it, "client.legacy.error.driverUnavailable", LegacyRules.errorKey(ApiException(400, it, "x")))
        }
        assertEquals("client.legacy.dispute.exists", LegacyRules.errorKey(ApiException(409, "ALREADY_EXISTS", "x")))
        // Offline and 429 keep the app-wide mapping (BannerPolicy).
        assertNull(LegacyRules.errorKey(ApiException(429, "RATE_LIMITED", "x")))
        assertNull(LegacyRules.errorKey(IllegalStateException()))
        assertTrue(LegacyRules.ratingAlreadyDone(ApiException(409, "ALREADY_EXISTS", "x")))
        assertFalse(LegacyRules.ratingAlreadyDone(ApiException(400, "ORDER_INVALID_STATUS", "x")))
        assertTrue(LegacyRules.bidGone(ApiException(409, "BID_NOT_ACTIVE", "x")))
        assertTrue(LegacyRules.statusChanged(ApiException(400, "ORDER_INVALID_STATUS", "x")))
        assertFalse(LegacyRules.statusChanged(ApiException(409, "BID_NOT_ACTIVE", "x")))
    }
}
