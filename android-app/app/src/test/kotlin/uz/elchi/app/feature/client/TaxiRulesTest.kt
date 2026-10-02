package uz.elchi.app.feature.client

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.BookingClientDTO
import uz.elchi.app.api.ElchiJson
import uz.elchi.app.api.generated.CashReceiptDTO
import uz.elchi.app.api.generated.Currency
import uz.elchi.app.api.generated.EffectiveFlagValuesDTO
import uz.elchi.app.api.generated.ListingCreate
import uz.elchi.app.api.generated.ListingDTO
import uz.elchi.app.api.generated.PriceBasis
import uz.elchi.app.api.generated.ServiceType
import java.time.Instant

class TaxiRulesTest {
    /** 29.09.2026 15:00 in Tashkent. */
    private val now: Instant = Instant.parse("2026-09-29T10:00:00Z")

    private val tashkent = Place(regionId = "reg_tk", regionUz = "Toshkent shahri", districtId = "dst_tk", districtUz = "Toshkent shahri", lat = 41.2856, lng = 69.2044, address = "Chilonzor")
    private val samarkand = Place(regionId = "reg_sa", regionUz = "Samarqand viloyati", districtId = "dst_sa", districtUz = "Samarqand", lat = 39.6547, lng = 66.9758, stopId = "stp_reg", stopUz = "Registon")

    private fun draft(seats: List<String> = listOf("rear-right", "rear-left")) = ParcelDraft(
        origin = tashkent,
        destination = samarkand,
        windowStart = "2026-09-30T09:00",
        windowEnd = "2026-09-30T18:00",
        priceDigits = "150000",
        comment = "  ",
        taxi = true,
        seats = seats,
    )

    private fun flags(passenger: Boolean, parcel: Boolean = true) =
        EffectiveFlagValuesDTO(driverListingEnabled = false, parcelEnabled = parcel, passengerEnabled = passenger, trackingEnabled = true)

    // -- flags --------------------------------------------------------------------------------------------------

    @Test
    fun `the Taksi segment shows only while the country flag is on, and a failed read hides it`() {
        assertTrue(TaxiRules.passengerOffered(flags(passenger = true), failed = false))
        assertFalse(TaxiRules.passengerOffered(flags(passenger = false), failed = false))
        assertFalse(TaxiRules.passengerOffered(flags(passenger = true), failed = true))
        assertFalse(TaxiRules.passengerOffered(null, failed = false))
    }

    @Test
    fun `the corridor decides - a closed or unreadable passenger flag keeps the button off with its sentence`() {
        val open = TaxiRules.serviceOpen(flags(passenger = true), loading = false, failed = false, passenger = true)
        assertEquals(true, open)
        assertEquals(HomeBlock.NONE, TaxiRules.homeBlock(taxi = true, directionReady = true, open = open))
        val closed = TaxiRules.serviceOpen(flags(passenger = false), loading = false, failed = false, passenger = true)
        assertEquals(HomeBlock.PASSENGER_CLOSED, TaxiRules.homeBlock(taxi = true, directionReady = true, open = closed))
        val failed = TaxiRules.serviceOpen(flags(passenger = true), loading = false, failed = true, passenger = true)
        assertEquals(HomeBlock.PASSENGER_CLOSED, TaxiRules.homeBlock(taxi = true, directionReady = true, open = failed))
        // Still loading, or no direction yet: off, without a "closed" sentence.
        assertNull(TaxiRules.serviceOpen(flags(passenger = true), loading = true, failed = false, passenger = true))
        assertEquals(HomeBlock.NOT_READY, TaxiRules.homeBlock(taxi = true, directionReady = true, open = null))
        assertEquals(HomeBlock.NOT_READY, TaxiRules.homeBlock(taxi = true, directionReady = false, open = true))
        // Pochta reads its own flag.
        val parcel = TaxiRules.serviceOpen(flags(passenger = true, parcel = false), loading = false, failed = false, passenger = false)
        assertEquals(HomeBlock.PARCEL_CLOSED, TaxiRules.homeBlock(taxi = false, directionReady = true, open = parcel))
    }

    // -- seats --------------------------------------------------------------------------------------------------

    @Test
    fun `seats toggle in picking order and never down to zero`() {
        var seats = listOf("rear-right")
        seats = TaxiRules.toggleSeat(seats, "front")
        assertEquals(listOf("rear-right", "front"), seats)
        assertEquals(2, TaxiRules.seatOrder(seats, "front"))
        assertNull(TaxiRules.seatOrder(seats, "rear-left"))
        seats = TaxiRules.toggleSeat(seats, "rear-right")
        assertEquals(listOf("front"), seats)
        assertEquals(listOf("front"), TaxiRules.toggleSeat(seats, "front"))
        assertEquals(listOf("front"), TaxiRules.toggleSeat(seats, "driver"))
        assertEquals(4, TaxiRules.seatCount(draft(seats = listOf("front", "rear-left", "rear-middle", "rear-right"))))
    }

    @Test
    fun `the total is the count times the price per person`() {
        assertEquals(30_000_000L, TaxiRules.totalMinor(15_000_000L, 2))
        assertEquals(15_000_000L, TaxiRules.totalMinor(15_000_000L, 1))
    }

    // -- the request --------------------------------------------------------------------------------------------

    @Test
    fun `a passenger request needs the route, window, price and seats - no contacts, parcel or photo`() {
        assertTrue(TaxiRules.readyToPublish(draft(), directionReady = true, now = now))
        assertFalse(TaxiRules.readyToPublish(draft(), directionReady = false, now = now))
        assertFalse(TaxiRules.readyToPublish(draft().copy(priceDigits = ""), directionReady = true, now = now))
        assertFalse(TaxiRules.readyToPublish(draft(seats = emptyList()), directionReady = true, now = now))
        // The parcel's rules would refuse it (no photo), the passenger's do not ask for one.
        assertFalse(ParcelRules.readyToPublish(draft(), directionReady = true, now = now))
    }

    @Test
    fun `the passenger body is per seat with the seat block and no parcel`() {
        val body = TaxiRules.buildListingCreate(draft())
        val json = ElchiJson.encodeToJsonElement(ListingCreate.serializer(), body).jsonObject
        assertEquals("request", json["kind"]!!.jsonPrimitive.content)
        assertEquals("passenger", json["service_type"]!!.jsonPrimitive.content)
        assertEquals("per_seat", json["price_basis"]!!.jsonPrimitive.content)
        assertEquals("15000000", json["unit_price_minor"]!!.jsonPrimitive.content)
        val passenger = json["passenger"]!!.jsonObject
        assertEquals("2", passenger["seat_count"]!!.jsonPrimitive.content)
        assertEquals("2", passenger["adults"]!!.jsonPrimitive.content)
        assertTrue(json["parcel"] == null || json["parcel"] == JsonNull)
        // The ends exactly as for a parcel: a point with its district, a verified stop by id.
        assertEquals("dst_tk", json["origin_point"]!!.jsonObject["district_id"]!!.jsonPrimitive.content)
        assertEquals("stp_reg", json["destination_stop_id"]!!.jsonPrimitive.content)
        assertEquals("2026-09-30T09:00:00+05:00", json["departure_window_start"]!!.jsonPrimitive.content)
        assertEquals(Currency.UZS, body.currency)
        assertEquals(PriceBasis.PER_SEAT, body.priceBasis)
        assertNull(body.comment)
    }

    // -- seat-count edit (Q145) -----------------------------------------------------------------------------------

    private fun listing(status: String = "published", seats: Long = 2, children: Long? = null, service: String = "passenger", kind: String = "request"): ListingDTO =
        ElchiJson.decodeFromString(
            ListingDTO.serializer(),
            """{"id":"lst_1","kind":"$kind","service_type":"$service","status":"$status","version":4,"terms_version":2,
            "owner":{"id":"usr_1","display_name":"Demo"},"corridor_id":"cor_1",
            "origin_point":{"lat":41.3,"lng":69.2,"district":{"id":"dst_a","name_uz":"Toshkent shahri"},"address":null},
            "destination_point":{"lat":39.7,"lng":64.4,"district":{"id":"dst_b","name_uz":"Buxoro"},"address":null},
            "departure_window_start":"2026-09-30T04:00:00Z","departure_window_end":"2026-09-30T13:00:00Z","timezone":"Asia/Tashkent",
            "price_basis":"per_seat","unit_price_minor":15000000,"quantity":$seats,"total_minor":${15_000_000 * seats},"currency":"UZS","payment_method":"cash",
            "passenger":${if (service == "passenger") """{"seat_count":$seats,"adults":${seats - (children ?: 0)},"children":${children ?: "null"},"amenities":["air_conditioning"]}""" else "null"},
            "expires_at":"2026-09-30T13:00:00Z","comment":null,"view_count":3,"created_at":"2026-09-29T06:00:00Z"}""",
        )

    @Test
    fun `only an open passenger request's seats are editable`() {
        assertTrue(TaxiRules.seatsEditable(listing()))
        assertTrue(TaxiRules.seatsEditable(listing(status = "paused")))
        assertFalse(TaxiRules.seatsEditable(listing(status = "fulfilled")))
        assertFalse(TaxiRules.seatsEditable(listing(service = "parcel")))
    }

    @Test
    fun `a new seat count sends the whole block, expires open offers, and is checked`() {
        val l = listing()
        val form = OrderRules.editForm(l)
        assertEquals("2", form.seats)
        val plan = OrderRules.planListingPatch(l, form.copy(seats = "3"), now)
        assertEquals(3L, plan.passenger?.seatCount)
        assertEquals(3L, plan.passenger?.adults)
        // The rest of the block travels unchanged (the server replaces it).
        assertEquals(l.passenger?.amenities, plan.passenger?.amenities)
        assertTrue(plan.material)
        assertFalse(plan.empty)
        assertNull(plan.invalid)
        // Unchanged: nothing to send.
        assertTrue(OrderRules.planListingPatch(l, form, now).empty)
        assertEquals(EditInvalid.SEATS, OrderRules.planListingPatch(l, form.copy(seats = "0"), now).invalid)
        assertEquals(EditInvalid.SEATS, OrderRules.planListingPatch(l, form.copy(seats = "9"), now).invalid)
        assertEquals(EditInvalid.SEATS, OrderRules.planListingPatch(l, form.copy(seats = ""), now).invalid)
        val withChild = listing(seats = 3, children = 1)
        assertEquals(EditInvalid.SEATS_CHILDREN, OrderRules.planListingPatch(withChild, OrderRules.editForm(withChild).copy(seats = "1"), now).invalid)
        assertEquals(1L, OrderRules.planListingPatch(withChild, OrderRules.editForm(withChild).copy(seats = "2"), now).passenger?.adults)
        // A draft's offers do not exist yet: not material.
        assertFalse(OrderRules.planListingPatch(listing(status = "draft"), form.copy(seats = "3"), now).material)
    }

    // -- the booking (client) -----------------------------------------------------------------------------------

    @Test
    fun `the code shows until boarding, the cash record from boarding, complete only after the drop-off`() {
        val p = ServiceType.PASSENGER
        assertTrue(TaxiRules.showBoardingCode(p, "confirmed"))
        assertTrue(TaxiRules.showBoardingCode(p, "awaiting_pickup"))
        assertFalse(TaxiRules.showBoardingCode(p, "onboard"))
        assertFalse(TaxiRules.showBoardingCode(ServiceType.PARCEL, "awaiting_pickup"))
        assertFalse(TaxiRules.showCash(p, "awaiting_pickup"))
        assertTrue(TaxiRules.showCash(p, "onboard"))
        assertTrue(TaxiRules.showCash(p, "arrived"))
        assertTrue(TaxiRules.showCash(p, "completed"))
        assertFalse(TaxiRules.showCash(p, "cancelled"))
        assertFalse(TaxiRules.showCash(ServiceType.PARCEL, "completed"))
        assertTrue(TaxiRules.canComplete(p, "arrived"))
        assertFalse(TaxiRules.canComplete(p, "onboard"))
        assertFalse(TaxiRules.canComplete(p, "completed"))
    }

    @Test
    fun `a passenger booking's statuses read as words, not codes`() {
        val p = ServiceType.PASSENGER
        assertEquals("status.onboard", OrderRules.bookingStatusKey(p, "onboard"))
        assertEquals("status.arrived", OrderRules.bookingStatusKey(p, "arrived"))
        assertEquals("status.no_show", OrderRules.bookingStatusKey(p, "no_show"))
        assertEquals("status.confirmed", OrderRules.bookingStatusKey(p, "confirmed"))
        assertEquals(uz.elchi.app.ui.theme.Tone.BLUE, OrderRules.bookingTone(p, "onboard"))
        assertEquals(uz.elchi.app.ui.theme.Tone.ERR, OrderRules.bookingTone(p, "no_show"))
    }

    @Test
    fun `the passenger ladder has its own rungs`() {
        val booking = ElchiJson.decodeFromString(
            BookingClientDTO.serializer(),
            """{"id":"bkg_1","viewer_side":"client","service_type":"passenger","service_status":"onboard","quantity":2,"unit_price_minor":15000000,
            "total_minor":30000000,"created_at":"2026-09-29T06:00:00Z","pickup":{"stop":null,"point":null},"dropoff":{"stop":null,"point":null},
            "cash_status":"unpaid","cash_receipt":null,"price_basis":"per_seat","quantity_amendable":false,"no_show_review":{"status":"pending","reported_at":"2026-09-29T07:00:00Z"}}""",
        )
        val ladder = BookingRules.ladder(booking)
        assertEquals(listOf("status.confirmed", "status.awaiting_pickup", "status.onboard", "status.arrived", "app.progress.completed"), ladder.map { it.key })
        assertEquals(listOf(StepState.DONE, StepState.DONE, StepState.CURRENT, StepState.TODO, StepState.TODO), ladder.map { it.state })
        assertNull(BookingRules.ladderIndex("no_show", ServiceType.PASSENGER))
        assertEquals("per_seat", booking.priceBasis)
        assertFalse(booking.quantityAmendable)
        assertTrue(BookingRules.reviewPending(booking.noShowReview))
    }

    @Test
    fun `the reissue wait reads minutes and seconds under an hour, hours and minutes above`() {
        assertEquals(ReissueWait.Minutes(1, 30), TaxiRules.reissueWait(90))
        assertEquals(ReissueWait.Minutes(0, 1), TaxiRules.reissueWait(0))
        assertEquals(ReissueWait.Hours(5, 2), TaxiRules.reissueWait(5 * 3600 + 61))
        assertEquals(ReissueWait.Hours(2, 0), TaxiRules.reissueWait(7200))
        val limited = ApiException(429, "PROOF_REISSUE_LIMITED", "limited", buildJsonObject { put("retry_after_s", 95); put("reissues_left", 2) })
        assertEquals(95L to 2L, TaxiRules.reissueLimit(limited))
        assertNull(TaxiRules.reissueLimit(ApiException(409, "INVALID_STATE_TRANSITION", "no")))
    }

    // -- the cash record ----------------------------------------------------------------------------------------

    private fun receipt(side: String, status: String = "reported_paid", version: Long = 1) = CashReceiptDTO(
        amountMinor = 30_000_000, bookingId = "bkg_1", bookingVersion = 5, currency = Currency.UZS, id = "crc_1",
        reportedAt = "2026-09-29T09:20:00Z", reportedBySide = side, status = status, version = version,
    )

    @Test
    fun `each side sees report, wait, decide, confirmed or contested`() {
        assertEquals(CashView.REPORT, TaxiRules.cashView("unpaid", null, "client"))
        assertEquals(CashView.REPORT, TaxiRules.cashView(null, null, "driver"))
        assertEquals(CashView.AWAITING_OTHER, TaxiRules.cashView("reported_paid", receipt("driver"), "driver"))
        assertEquals(CashView.DECIDE, TaxiRules.cashView("reported_paid", receipt("driver"), "client"))
        assertEquals(CashView.BOTH_CONFIRMED, TaxiRules.cashView("acknowledged", receipt("driver", "acknowledged"), "client"))
        assertEquals(CashView.CONTESTED, TaxiRules.cashView("contested", receipt("client", "contested"), "driver"))
    }

    @Test
    fun `a report needs a note only when the amount differs from the cash due`() {
        val due = 30_000_000L
        val exact = TaxiRules.cashReport(5, "300000", "", due, now)!!
        assertEquals(30_000_000L, exact.amountMinor)
        assertEquals(5L, exact.expectedVersion)
        assertNull(exact.note)
        assertEquals("2026-09-29T15:00:00+05:00", exact.reportedAt)
        assertNull(TaxiRules.cashReport(5, "250000", " ", due, now))
        assertEquals("Qolganini ertaga beradi", TaxiRules.cashReport(5, "250000", " Qolganini ertaga beradi ", due, now)!!.note)
        assertNull(TaxiRules.cashReport(5, "", "", due, now))
        assertTrue(TaxiRules.cashNoteRequired(25_000_000, due))
        assertFalse(TaxiRules.cashNoteRequired(due, due))
        assertFalse(TaxiRules.cashNoteRequired(null, due))
    }

    @Test
    fun `acknowledge and contest answer the receipt's own version, a contest needs a comment`() {
        val r = receipt("driver", version = 2)
        assertEquals(2L, TaxiRules.acknowledgeBody(r).expectedVersion)
        assertNull(TaxiRules.acknowledgeBody(r).comment)
        assertNull(TaxiRules.contestBody(r, "  "))
        val contest = TaxiRules.contestBody(r, " Faqat 250 000 berdim ")!!
        assertEquals("Faqat 250 000 berdim", contest.comment)
        assertEquals(2L, contest.expectedVersion)
    }
}
