package uz.elchi.app.feature.driver

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.api.BookingClientDTO
import uz.elchi.app.api.DriverBookingDTO
import uz.elchi.app.api.ElchiJson
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.feature.client.BookingRules
import uz.elchi.app.feature.client.BookingViewModel
import uz.elchi.app.ui.theme.Tone
import java.time.Instant

class DriverBookingRulesTest {
    /** A driver's `GET /bookings/{id}` as the server sends it (BookingDTO: commission snapshot, client party). */
    private fun json(status: String = "confirmed", contacts: String = "null", promo: String = "null", updated: String = "2026-10-01T08:00:00Z") = """
        {"id":"bkg_1","viewer_side":"driver","service_type":"parcel","service_status":"$status","cash_status":"not_applicable",
         "parcel_category":{"id":"pct_1","code":"small_box","icon_key":"box","name_uz":"Kichik quti","name_ru":"Маленькая коробка","max_weight_g":5000,"max_volume_ml":20000,"max_length_cm":40,"max_width_cm":30,"max_height_cm":20},
         "quantity_amendable":false,"version":4,"trip_id":"trp_9","listing_ids":{"request":"lst_1","supply":null},
         "accepted_proposal_version_id":"prv_1","quantity":1,"price_basis":"total","unit_price_minor":12000000,"total_minor":12000000,
         "currency":"UZS","payment_method":"cash",
         "pickup":{"stop":null,"point":{"lat":41.28,"lng":69.2,"district":{"id":"dst_1","name_uz":"Chilonzor"}},"occurrence_seq":1,
                   "window_start":"2026-10-01T09:00:00Z","window_end":"2026-10-01T13:00:00Z"},
         "dropoff":{"stop":{"id":"stp_2","name_uz":"Registon"},"point":null,"occurrence_seq":2},
         "driver":{"id":"usr_d","display_name":"Jasur","vehicle":{"vehicle_class":"sedan","seat_capacity":4,"make_model":"Cobalt","color":"Oq","plate_masked":"01***KA"}},
         "client":{"id":"usr_c","display_name":"Aziza"},
         "parcel_contacts":$contacts,
         "contact":{"phones_visible":false,"visible_from":"2026-10-01T10:00:00Z","support_available":true},
         "policy_versions":{"listing_version":1,"listing_terms_version":1,"cancellation_policy":"pilot"},
         "cancellation_policy_summary":"Pilot: jarima yo'q.",
         "commission_status":"held",
         "fee":{"policy_id":"cmp_1","policy_kind":"percent","fee_bps":1500,"commission_minor":1800000,"net_minor":10200000},
         "promo":$promo,
         "created_at":"2026-09-30T08:00:00Z","updated_at":"$updated"}
    """.trimIndent()

    private fun booking(status: String = "confirmed", contacts: String = "null", promo: String = "null", updated: String = "2026-10-01T08:00:00Z"): DriverBookingDTO =
        DriverBookingDTO.fromJson(ElchiJson.parseToJsonElement(json(status, contacts, promo, updated)))!!

    private val driverPromo = """{"view":"driver","fare_minor":12000000,"passenger_discount_minor":1000000,"cash_to_collect_minor":11000000,
        "base_commission_minor":1800000,"passenger_discount_covered_minor":1000000,"driver_credit_minor":200000,"commission_charged_minor":1600000,
        "driver_keeps_minor":9400000,"currency":"UZS"}"""

    @Test
    fun `the driver view parses, and the shared part serves the reused screens without the driver's promo`() {
        val element = ElchiJson.parseToJsonElement(json(promo = driverPromo))
        val view = DriverBookingDTO.fromJson(element)!!
        assertEquals("Aziza", view.client!!.displayName)
        assertEquals(1500L, view.fee!!.feeBps)
        assertEquals(11000000L, view.promo!!.cashToCollectMinor)
        // The client decoder refuses a driver row; the shared one keeps the common fields and drops the promo.
        assertNull(BookingClientDTO.fromJson(element))
        val shared = BookingClientDTO.anySide(element)!!
        assertEquals("bkg_1", shared.id)
        assertEquals(4L, shared.version)
        assertNull(shared.promo)
        // A client row is not the driver's.
        val clientRow = ElchiJson.parseToJsonElement(json().replace("\"viewer_side\":\"driver\"", "\"viewer_side\":\"client\""))
        assertNull(DriverBookingDTO.fromJson(clientRow))
    }

    @Test
    fun `badges follow the parcel rules - departed and operator-recorded`() {
        assertEquals("parcel.status.driverDeparted", DriverBookingRules.badgeKey(ServiceType.PARCEL, "in_transit"))
        assertEquals("parcel.status.driverDeparted", DriverBookingRules.badgeKey(ServiceType.PARCEL, "picked_up"))
        assertEquals("parcel.progress.deliveredByOperator", DriverBookingRules.badgeKey(ServiceType.PARCEL, "delivered"))
        assertEquals("status.awaiting_pickup", DriverBookingRules.badgeKey(ServiceType.PARCEL, "awaiting_pickup"))
        assertEquals("status.return_required", DriverBookingRules.badgeKey(ServiceType.PARCEL, "return_required"))
        assertEquals("status.confirmed", DriverBookingRules.badgeKey(ServiceType.PARCEL, "confirmed"))
        assertEquals(Tone.BLUE, DriverBookingRules.badgeTone(ServiceType.PARCEL, "picked_up"))
        assertEquals(Tone.WARN, DriverBookingRules.badgeTone(ServiceType.PARCEL, "awaiting_pickup"))
    }

    @Test
    fun `actions by status - parcel only, no codes, no cash receipt, no no-show`() {
        val now = Instant.parse("2026-10-01T12:00:00Z")
        val confirmed = DriverBookingRules.actions("confirmed", null, null, now)
        assertTrue(confirmed.arrive && confirmed.amend && confirmed.cancel)
        assertFalse(confirmed.rate || confirmed.transitNote)
        val awaiting = DriverBookingRules.actions("awaiting_pickup", null, null, now)
        assertTrue(awaiting.arrive && awaiting.cancel)
        assertFalse(awaiting.amend) // the server refuses an amendment once the trip boards
        // "Keldim" only once.
        assertFalse(DriverBookingRules.actions("awaiting_pickup", "2026-10-01T09:10:00Z", null, now).arrive)
        val transit = DriverBookingRules.actions("in_transit", null, null, now)
        assertTrue(transit.transitNote)
        assertFalse(transit.arrive || transit.cancel || transit.amend || transit.rate)
        listOf("delivered", "cancelled", "returned").forEach { status ->
            val a = DriverBookingRules.actions(status, null, null, now)
            assertFalse(status, a.arrive || a.cancel || a.amend || a.rate)
        }
        assertTrue(DriverBookingRules.actions("completed", null, "2026-09-30T12:00:00Z", now).rate)
    }

    @Test
    fun `rating the client is offered for 7 days after completion`() {
        val done = "2026-10-01T08:00:00Z"
        assertTrue(DriverBookingRules.ratingOpen("completed", done, Instant.parse("2026-10-08T07:59:00Z")))
        assertFalse(DriverBookingRules.ratingOpen("completed", done, Instant.parse("2026-10-08T08:01:00Z")))
        assertFalse(DriverBookingRules.ratingOpen("delivered", done, Instant.parse("2026-10-01T09:00:00Z")))
        assertTrue(DriverBookingRules.ratingOpen("completed", null, Instant.parse("2027-01-01T00:00:00Z")))
    }

    @Test
    fun `cash to collect is the promo's cash when discounted, else the total, and the commission is shown`() {
        val plain = booking()
        assertEquals(12000000L, DriverBookingRules.cashToCollectMinor(plain))
        assertEquals(1800000L, DriverBookingRules.commissionMinor(plain))
        val discounted = booking(promo = driverPromo)
        assertEquals(11000000L, DriverBookingRules.cashToCollectMinor(discounted))
        assertEquals(1600000L, DriverBookingRules.commissionMinor(discounted))
        assertEquals("15", DriverBookingRules.percent(1500))
        assertEquals("12.5", DriverBookingRules.percent(1250))
    }

    @Test
    fun `the receiver phone shows only when the server sends it - never the sender's`() {
        val hidden = DriverBookingRules.receiver(booking(status = "awaiting_pickup"))
        assertEquals(ReceiverView.Hidden("2026-10-01T10:00:00Z"), hidden)
        val emptyPhone = DriverBookingRules.receiver(booking(contacts = """{"receiver_name":"Dilnoza","receiver_phone":" "}"""))
        assertTrue(emptyPhone is ReceiverView.Hidden)
        val visible = DriverBookingRules.receiver(booking(status = "in_transit", contacts = """{"receiver_name":" Dilnoza ","receiver_phone":"+998915552211"}"""))
        assertEquals(ReceiverView.Visible("Dilnoza", "+998915552211"), visible)
        val noName = DriverBookingRules.receiver(booking(status = "in_transit", contacts = """{"receiver_phone":"+998915552211"}"""))
        assertEquals(ReceiverView.Visible(null, "+998915552211"), noName)
    }

    @Test
    fun `the driver's cancel reasons and refusals`() {
        assertEquals(listOf("trip_changed", "vehicle_problem", "client_unreachable", "other"), DriverBookingRules.CANCEL_REASONS)
        DriverBookingRules.CANCEL_REASONS.forEach { assertNotNull(it, BookingRules.cancelReasonKey(it)) }
        assertEquals("bookingCancel.refused.changed", DriverBookingRules.cancelRefusalKey("VERSION_CONFLICT"))
        assertEquals("bookingCancel.refused.custody", DriverBookingRules.cancelRefusalKey("CUSTODY_REQUIRES_RETURN_FLOW"))
        assertNull(DriverBookingRules.cancelRefusalKey("SOMETHING_ELSE"))
        assertEquals(setOf("confirmed", "awaiting_pickup"), BookingViewModel.ARRIVE_STATUSES)
    }

    @Test
    fun `the GPS bar belongs to bookings of a running trip`() {
        assertNull(DriverBookingRules.gpsTripId("confirmed", "trp_9"))
        assertEquals("trp_9", DriverBookingRules.gpsTripId("awaiting_pickup", "trp_9"))
        assertEquals("trp_9", DriverBookingRules.gpsTripId("in_transit", "trp_9"))
        assertNull(DriverBookingRules.gpsTripId("completed", "trp_9"))
        assertNull(DriverBookingRules.gpsTripId("in_transit", null))
    }

    @Test
    fun `the list shows live bookings first, then the history`() {
        val a = booking(status = "completed", updated = "2026-09-29T08:00:00Z").copy(id = "a")
        val b = booking(status = "confirmed").copy(id = "b", pickup = booking().pickup.copy(windowStart = "2026-10-03T09:00:00Z"))
        val c = booking(status = "in_transit").copy(id = "c")
        val d = booking(status = "cancelled", updated = "2026-09-30T08:00:00Z").copy(id = "d")
        // An old confirmed booking whose pickup window ended days ago (the trip never ran) goes after the upcoming one.
        val stale = booking(status = "confirmed").copy(id = "s", pickup = booking().pickup.copy(windowStart = "2026-09-28T09:00:00Z", windowEnd = "2026-09-28T13:00:00Z"))
        val now = Instant.parse("2026-10-01T10:00:00Z")
        assertEquals(listOf("c", "b", "s", "d", "a"), DriverBookingRules.ordered(listOf(a, stale, b, c, d), now).map { it.id })
    }
}
