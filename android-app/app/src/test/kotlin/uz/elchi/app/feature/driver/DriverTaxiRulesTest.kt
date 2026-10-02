package uz.elchi.app.feature.driver

import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.BookingNoShowReviewDTO
import uz.elchi.app.api.DriverBookingDTO
import uz.elchi.app.api.ElchiJson
import uz.elchi.app.api.generated.ServiceType
import java.time.Instant

class DriverTaxiRulesTest {
    private val p = ServiceType.PASSENGER
    private val windowStart = "2026-09-29T10:00:00Z"
    private val windowEnd = "2026-09-29T11:00:00Z"

    // -- board ----------------------------------------------------------------------------------------------------

    @Test
    fun `the code field is for the awaited passenger, drop-off for the one in the car`() {
        assertTrue(DriverTaxiRules.showBoard(p, "awaiting_pickup"))
        assertFalse(DriverTaxiRules.showBoard(p, "confirmed"))
        assertFalse(DriverTaxiRules.showBoard(ServiceType.PARCEL, "awaiting_pickup"))
        assertTrue(DriverTaxiRules.showDropOff(p, "onboard"))
        assertFalse(DriverTaxiRules.showDropOff(p, "arrived"))
    }

    @Test
    fun `the code keeps six digits and goes with the booking's version`() {
        assertEquals("482916", DriverTaxiRules.normaliseCode("48 29-16 7"))
        assertTrue(DriverTaxiRules.codeComplete("482916"))
        assertFalse(DriverTaxiRules.codeComplete("48291"))
        val body = DriverTaxiRules.boardBody(7, "482916")
        assertEquals("482916", body.code)
        assertEquals(7L, body.expectedVersion)
    }

    @Test
    fun `board refusals map to attempts left, exhausted, trip not started`() {
        val wrong = ApiException(422, "PROOF_INVALID", "wrong", buildJsonObject { put("proof_kind", "boarding_code"); put("attempts_left", 4) })
        assertEquals(BoardError.Wrong(4), DriverTaxiRules.boardError(wrong))
        assertEquals(BoardError.Wrong(null), DriverTaxiRules.boardError(ApiException(422, "PROOF_INVALID", "wrong")))
        assertEquals(BoardError.Exceeded, DriverTaxiRules.boardError(ApiException(409, "PROOF_ATTEMPTS_EXCEEDED", "no")))
        assertEquals(BoardError.TripNotStarted, DriverTaxiRules.boardError(ApiException(409, "TRIP_NOT_STARTED", "no")))
        assertTrue(DriverTaxiRules.boardError(ApiException(409, "VERSION_CONFLICT", "no")) is BoardError.Other)
    }

    // -- no-show (Q7) ---------------------------------------------------------------------------------------------

    private fun state(status: String = "awaiting_pickup", arrived: String? = "2026-09-29T10:05:00Z", review: String? = null, now: String = "2026-09-29T10:20:00Z") =
        DriverTaxiRules.noShow(p, status, arrived, windowStart, windowEnd, review?.let { BookingNoShowReviewDTO(status = it) }, Instant.parse(now))

    @Test
    fun `no-show unlocks ten minutes after the later of the arrival and the window start`() {
        assertEquals(NoShowState.Ready, state())
        assertEquals(NoShowState.Locked("wait_time_not_elapsed", Instant.parse("2026-09-29T10:15:00Z")), state(now = "2026-09-29T10:10:00Z"))
        // Arrived before the window opened: the wait counts from the window start.
        assertEquals(NoShowState.Locked("wait_time_not_elapsed", Instant.parse("2026-09-29T10:10:00Z")), state(arrived = "2026-09-29T09:40:00Z", now = "2026-09-29T10:05:00Z"))
        assertEquals(Instant.parse("2026-09-29T10:10:00Z"), DriverTaxiRules.noShowUnlocksAt(Instant.parse("2026-09-29T09:40:00Z"), Instant.parse(windowStart)))
    }

    @Test
    fun `no-show is off without Keldim, after a late arrival, hidden outside the wait and pending once reported`() {
        assertEquals(NoShowState.Locked("arrival_not_recorded"), state(arrived = null))
        assertEquals(NoShowState.Locked("driver_arrived_late"), state(arrived = "2026-09-29T11:30:00Z", now = "2026-09-29T12:00:00Z"))
        assertEquals(NoShowState.Hidden, state(status = "confirmed"))
        assertEquals(NoShowState.Hidden, state(status = "onboard"))
        assertEquals(NoShowState.Hidden, DriverTaxiRules.noShow(ServiceType.PARCEL, "awaiting_pickup", null, windowStart, windowEnd, null, Instant.parse("2026-09-29T10:20:00Z")))
        assertEquals(NoShowState.Pending, state(review = "pending"))
        // A rejected report does not block a new one.
        assertEquals(NoShowState.Ready, state(review = "rejected"))
    }

    @Test
    fun `the no-show body carries one attempt per channel and the version`() {
        val now = Instant.parse("2026-09-29T10:20:00Z")
        assertNull(DriverTaxiRules.noShowBody(9, emptySet(), now))
        val body = DriverTaxiRules.noShowBody(9, setOf(ContactChannel.CALL, ContactChannel.CHAT), now)!!
        assertEquals(9L, body.expectedVersion)
        assertEquals(listOf("chat", "other"), body.contactAttempts!!.map { it.channel })
        assertEquals("2026-09-29T15:20:00+05:00", body.contactAttempts!!.first().at)
        assertEquals("2026-09-29T15:20:00+05:00", body.observedAt)
        assertNull(body.code)
    }

    @Test
    fun `no-show refusals map to the driver's reasons`() {
        fun refused(reason: String?) = ApiException(409, "NO_SHOW_NOT_ALLOWED", "no", reason?.let { buildJsonObject { put("reason", it) } })
        assertEquals("driver.noShow.reason.wait_time_not_elapsed", DriverTaxiRules.noShowRefusalKey(refused("wait_time_not_elapsed")))
        assertEquals("driver.noShow.reason.no_contact_attempt", DriverTaxiRules.noShowRefusalKey(refused("no_contact_attempt")))
        assertEquals("error.NO_SHOW_NOT_ALLOWED", DriverTaxiRules.noShowRefusalKey(refused("something_new")))
        assertEquals("error.NO_SHOW_NOT_ALLOWED", DriverTaxiRules.noShowRefusalKey(refused(null)))
        assertEquals("driver.noShow.pending", DriverTaxiRules.noShowRefusalKey(ApiException(409, "NO_SHOW_REVIEW_PENDING", "no")))
        assertNull(DriverTaxiRules.noShowRefusalKey(ApiException(409, "VERSION_CONFLICT", "no")))
    }

    // -- the driver's booking -------------------------------------------------------------------------------------

    private fun booking(status: String, review: String? = null): DriverBookingDTO = DriverBookingDTO.fromJson(
        ElchiJson.parseToJsonElement(
            """{"id":"bkg_1","viewer_side":"driver","service_type":"passenger","service_status":"$status","quantity":2,"price_basis":"per_seat",
            "unit_price_minor":15000000,"total_minor":30000000,"version":4,"trip_id":"trp_1","created_at":"2026-09-29T06:00:00Z",
            "pickup":{"stop":null,"point":null,"window_start":"$windowStart","window_end":"$windowEnd"},"dropoff":{"stop":null,"point":null},
            "client":{"id":"usr_c","display_name":"Aziza","contact_phone":null},"cash_status":"reported_paid",
            "cash_receipt":{"amount_minor":30000000,"booking_id":"bkg_1","booking_version":4,"currency":"UZS","id":"crc_1","reported_at":"2026-09-29T11:00:00Z",
              "reported_by_side":"client","status":"reported_paid","version":1},
            "no_show_review":${review?.let { """{"status":"$it","reported_at":"2026-09-29T10:30:00Z"}""" } ?: "null"},"quantity_amendable":false}""",
        ),
    )!!

    @Test
    fun `the driver DTO reads the passenger fields, and a pending no-show blocks the driver's cancel`() {
        val b = booking("awaiting_pickup", review = "pending")
        assertEquals("per_seat", b.priceBasis)
        assertEquals("reported_paid", b.cashStatus)
        assertEquals("client", b.cashReceipt?.reportedBySide)
        assertEquals("pending", b.noShowReview?.status)
        assertFalse(DriverBookingRules.actions(b.serviceStatus, null, b.updatedAt, Instant.parse("2026-09-29T10:00:00Z"), b.noShowReview).cancel)
        assertTrue(DriverBookingRules.actions("awaiting_pickup", null, null, Instant.parse("2026-09-29T10:00:00Z"), null).cancel)
        // "Keldim" stays until it is sent, in both pre-service statuses.
        assertTrue(DriverBookingRules.actions("awaiting_pickup", null, null, Instant.parse("2026-09-29T10:00:00Z")).arrive)
        assertFalse(DriverBookingRules.actions("awaiting_pickup", "2026-09-29T10:05:00Z", null, Instant.parse("2026-09-29T10:00:00Z")).arrive)
        // The trip runs while the passenger is in the car: the GPS bar stays.
        assertEquals("trp_1", DriverBookingRules.gpsTripId("onboard", "trp_1"))
        assertEquals(30_000_000L, DriverBookingRules.cashToCollectMinor(b))
    }

    @Test
    fun `a capacity refusal is told apart from other offer errors`() {
        assertTrue(OfferRules.capacityShort(ApiException(409, "CAPACITY_UNAVAILABLE", "full")))
        assertFalse(OfferRules.capacityShort(ApiException(409, "QUANTITY_MISMATCH", "no")))
        assertFalse(OfferRules.capacityShort(null))
    }
}
