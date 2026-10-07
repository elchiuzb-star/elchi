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

    // -- design 08 (v3) --------------------------------------------------------------------------------------------

    private val pending = uz.elchi.app.api.BookingNoShowReviewDTO(status = "pending")

    @Test
    fun `list badges are short, detail badges long, and a pending no-show review is said in both`() {
        assertEquals("status.in_transit", DriverBookingRules.badgeKey(ServiceType.PARCEL, "in_transit", short = true))
        assertEquals("status.in_transit", DriverBookingRules.badgeKey(ServiceType.PARCEL, "picked_up", short = true))
        assertEquals("status.delivered", DriverBookingRules.badgeKey(ServiceType.PARCEL, "delivered", short = true))
        assertEquals("parcel.status.driverDeparted", DriverBookingRules.badgeKey(ServiceType.PARCEL, "in_transit"))
        assertEquals("status.onboard", DriverBookingRules.badgeKey(ServiceType.PASSENGER, "onboard", short = true))
        // Q7: never "Kelmadi" before the operator decided - "Kelmadi · ko'rikda", red, in the list and the detail.
        assertEquals("driver.v3bkg.noShowReviewBadge", DriverBookingRules.badgeKey(ServiceType.PASSENGER, "awaiting_pickup", short = true, review = pending))
        assertEquals("driver.v3bkg.noShowReviewBadge", DriverBookingRules.badgeKey(ServiceType.PASSENGER, "awaiting_pickup", review = pending))
        assertEquals(Tone.ERR, DriverBookingRules.badgeTone(ServiceType.PASSENGER, "awaiting_pickup", pending))
        assertEquals(Tone.WARN, DriverBookingRules.badgeTone(ServiceType.PASSENGER, "awaiting_pickup", uz.elchi.app.api.BookingNoShowReviewDTO(status = "rejected")))
        assertEquals("status.no_show", DriverBookingRules.badgeKey(ServiceType.PASSENGER, "no_show", review = pending))
    }

    @Test
    fun `row icon, price basis and dimming follow the service`() {
        assertEquals(uz.elchi.app.ui.icons.ElchiIcon.PKG, DriverBookingRules.rowIcon(ServiceType.PARCEL))
        assertEquals(uz.elchi.app.ui.icons.ElchiIcon.PIN, DriverBookingRules.rowIcon(ServiceType.PASSENGER))
        assertFalse(DriverBookingRules.seatsPriced(booking()))
        assertTrue(DriverBookingRules.seatsPriced(booking().copy(serviceType = ServiceType.PASSENGER)))
        assertFalse(DriverBookingRules.seatsPriced(booking(promo = driverPromo).copy(serviceType = ServiceType.PASSENGER)))
        assertTrue(DriverBookingRules.dimmed("completed"))
        assertTrue(DriverBookingRules.dimmed("cancelled"))
        assertFalse(DriverBookingRules.dimmed("onboard"))
    }

    @Test
    fun `the hero pill and the GPS-off note read this phone's tracker`() {
        val off = uz.elchi.app.gps.TrackerSnapshot()
        val on = uz.elchi.app.gps.TrackerSnapshot(phase = uz.elchi.app.gps.TrackerPhase.ACTIVE, tripId = "trp_9")
        val otherTrip = on.copy(tripId = "trp_1")
        assertEquals(HeroChip.TRACKING, DriverBookingRules.heroChip("confirmed", "trp_9", on))
        assertEquals(HeroChip.TRACKING, DriverBookingRules.heroChip("awaiting_pickup", "trp_9", off))
        assertEquals(HeroChip.LIVE, DriverBookingRules.heroChip("onboard", "trp_9", on))
        assertEquals(HeroChip.LIVE, DriverBookingRules.heroChip("in_transit", "trp_9", on.copy(phase = uz.elchi.app.gps.TrackerPhase.STARTING)))
        assertEquals(HeroChip.GPS_OFF, DriverBookingRules.heroChip("onboard", "trp_9", off))
        assertEquals(HeroChip.GPS_OFF, DriverBookingRules.heroChip("in_transit", "trp_9", otherTrip))
        assertEquals(HeroChip.GPS_OFF, DriverBookingRules.heroChip("onboard", "trp_9", on.copy(phase = uz.elchi.app.gps.TrackerPhase.PERMISSION_DENIED)))
        assertTrue(DriverBookingRules.gpsOffWarn("onboard", "trp_9", off))
        assertFalse(DriverBookingRules.gpsOffWarn("onboard", "trp_9", on))
        assertFalse(DriverBookingRules.gpsOffWarn("arrived", "trp_9", off))
        assertFalse(DriverBookingRules.gpsOffWarn("onboard", null, off))
    }

    @Test
    fun `the arrived note is passenger only (Q139)`() {
        assertTrue(DriverBookingRules.arrivedNote(ServiceType.PASSENGER, "arrived"))
        assertFalse(DriverBookingRules.arrivedNote(ServiceType.PARCEL, "delivered"))
        assertFalse(DriverBookingRules.arrivedNote(ServiceType.PASSENGER, "onboard"))
    }

    private fun amendment(id: String, side: String, status: String, expires: String) = uz.elchi.app.api.generated.AmendmentDTO(
        authorSide = side, bookingId = "bkg_1", changes = ElchiJson.parseToJsonElement("{}"), expiresAt = expires, id = id,
        newQuantity = 2, newTotalMinor = 30000000, newUnitPriceMinor = 15000000, status = status, version = 1,
    )

    @Test
    fun `the detail says the driver's newest proposal - open or accepted - and nothing else`() {
        val now = Instant.parse("2026-10-01T10:00:00Z")
        val open = amendment("a1", "driver", "proposed", "2026-10-01T12:00:00Z")
        assertEquals(DriverAmendNotice.Pending(open), DriverBookingRules.amendNotice(listOf(open), "confirmed", now))
        // Expired, someone else's, or the booking moved on: no line.
        assertNull(DriverBookingRules.amendNotice(listOf(open.copy(expiresAt = "2026-10-01T09:00:00Z")), "confirmed", now))
        assertNull(DriverBookingRules.amendNotice(listOf(open.copy(authorSide = "client")), "confirmed", now))
        assertNull(DriverBookingRules.amendNotice(listOf(open), "awaiting_pickup", now))
        val accepted = amendment("a2", "driver", "accepted", "2026-10-01T11:00:00Z")
        assertEquals(DriverAmendNotice.Accepted(accepted), DriverBookingRules.amendNotice(listOf(accepted), "awaiting_pickup", now))
        assertNull(DriverBookingRules.amendNotice(listOf(accepted), "completed", now))
        // The newest (latest expiry) wins.
        val rejected = amendment("a3", "driver", "rejected", "2026-10-01T13:00:00Z")
        assertNull(DriverBookingRules.amendNotice(listOf(accepted, rejected), "confirmed", now))
        assertEquals(DriverAmendNotice.Pending(open), DriverBookingRules.amendNotice(listOf(accepted, open), "confirmed", now))
    }

    @Test
    fun `the proposal sentence drops the reason the amendment does not carry`() {
        val m = "\u2063"
        assertEquals(
            "Yangi narx taklifi yuborildi: 2 × 150 000 so'm — mijoz javobi kutilmoqda.",
            DriverBookingRules.dropReason("Yangi narx taklifi yuborildi: 2 × 150 000 so'm · Sabab: $m — mijoz javobi kutilmoqda.", m),
        )
        assertEquals(
            "Новая цена отправлена: 300 000 сум — ждём ответа клиента.",
            DriverBookingRules.dropReason("Новая цена отправлена: 300 000 сум · Причина: $m — ждём ответа клиента.", m),
        )
        assertEquals("no marker", DriverBookingRules.dropReason("no marker", m))
    }

    @Test
    fun `the call button rings the client after boarding, the receiver after departure, never the sender`() {
        val visibleContact = "{\"phones_visible\":true,\"support_available\":true}"
        val parcel = booking(status = "confirmed")
        assertEquals(ClientCall.AtDeparture, DriverBookingRules.clientCall(parcel))
        val departed = booking(status = "in_transit", contacts = "{\"receiver_name\":\"Dilshod\",\"receiver_phone\":\"+998901234567\"}")
        assertEquals(ClientCall.Open("+998901234567"), DriverBookingRules.clientCall(departed))
        assertEquals(ClientCall.Closed, DriverBookingRules.clientCall(booking(status = "completed")))
        val taxi = booking(status = "awaiting_pickup").copy(serviceType = ServiceType.PASSENGER)
        assertEquals(ClientCall.AfterBoard, DriverBookingRules.clientCall(taxi))
        val withPhone = taxi.copy(client = taxi.client!!.copy(contactPhone = "+998911112233"))
        // The server sent a number but says phones are hidden: still closed.
        assertEquals(ClientCall.AfterBoard, DriverBookingRules.clientCall(withPhone))
        val boarded = withPhone.copy(serviceStatus = "onboard", contact = ElchiJson.decodeFromString(uz.elchi.app.api.BookingContactDTO.serializer(), visibleContact))
        assertEquals(ClientCall.Open("+998911112233"), DriverBookingRules.clientCall(boarded))
    }

    @Test
    fun `tracking note claims background sending only while the service runs`() {
        val active = uz.elchi.app.gps.TrackerSnapshot(phase = uz.elchi.app.gps.TrackerPhase.ACTIVE, tripId = "trp_9")
        assertEquals("driverTracking.foregroundOnly", DriverBookingRules.trackingNoteKey(active))
        assertEquals("driver.gps.backgroundOn", DriverBookingRules.trackingNoteKey(active.copy(serviceRunning = true)))
        assertEquals("driverTracking.foregroundOnly", DriverBookingRules.trackingNoteKey(active.copy(phase = uz.elchi.app.gps.TrackerPhase.IDLE, serviceRunning = true)))
    }

    @Test
    fun `a proposal's reason is kept only once this phone sent it`() {
        DriverAmendReasons.clear()
        DriverAmendReasons.observe("bkg_r", "Yuk og'irroq", justSent = false)
        assertNull(DriverAmendReasons.sent("bkg_r"))
        DriverAmendReasons.observe("bkg_r", "", justSent = true)
        assertEquals("Yuk og'irroq", DriverAmendReasons.sent("bkg_r"))
        // A later emission of the same notice keeps it; another booking knows nothing.
        DriverAmendReasons.observe("bkg_r", "", justSent = true)
        assertEquals("Yuk og'irroq", DriverAmendReasons.sent("bkg_r"))
        assertNull(DriverAmendReasons.sent("bkg_other"))
        DriverAmendReasons.clear()
    }
}
