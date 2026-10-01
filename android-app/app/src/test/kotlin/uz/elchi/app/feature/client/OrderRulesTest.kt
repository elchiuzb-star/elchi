package uz.elchi.app.feature.client

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.api.BookingClientDTO
import uz.elchi.app.api.ElchiJson
import uz.elchi.app.api.generated.ListingDTO
import uz.elchi.app.api.generated.ListingStatus
import uz.elchi.app.api.generated.ProposalPromoClientDTO
import uz.elchi.app.api.generated.ProposalThreadDTO
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.ui.theme.Tone
import java.time.Instant
import java.time.LocalDateTime

class OrderRulesTest {
    /** 29.09.2026 15:00 in Tashkent. */
    private val now: Instant = Instant.parse("2026-09-29T10:00:00Z")

    private fun thread(
        id: String = "prp_1",
        state: String = "open",
        status: String = "active",
        author: String = "driver",
        expires: String = "2026-09-29T11:40:00Z",
        total: Long = 14_000_000,
        clientLeft: Int = 3,
        pickupStart: String = "2026-09-30T05:00:00Z",
        bucket: String? = "good",
        ratings: Int = 12,
        promo: String = "null",
        withVersion: Boolean = true,
    ): ProposalThreadDTO {
        val version = """{"id":"prv_$id","revision":2,"author_side":"$author","status":"$status","status_reason":null,
            "pickup_point":{"lat":41.3,"lng":69.2,"district":{"id":"dst_a","name_uz":"Chilonzor"},"address":"Toshkent, Chilonzor"},
            "dropoff_stop":{"id":"stp_b","name_uz":"Buxoro avtovokzali","name_ru":"Бухарский автовокзал"},
            "pickup_window_start":"$pickupStart","pickup_window_end":"2026-09-30T07:00:00Z","quantity":1,"price_basis":"total",
            "unit_price_minor":$total,"total_minor":$total,"currency":"UZS","expires_at":"$expires","created_at":"2026-09-29T09:48:00Z",
            "demand":{"baggage_ml":0,"cargo_weight_g":5000,"cargo_volume_ml":12000},"promo_quote":$promo,
            "price_revisions_left":{"client":$clientLeft,"driver":3}}"""
        val summary = """{"vehicle_class":"car","seat_capacity":4,"rating_bucket":${bucket?.let { "\"$it\"" } ?: "null"},"rating_count":$ratings,"completed_bookings":3}"""
        val json = """{"id":"$id","listing_id":"lst_1","state":"$state","client":{"side":"client","label":"Mijoz"},
            "driver":{"side":"driver","label":"Haydovchi #3"},"current_version":${if (withVersion) version else "null"},"driver_summary":$summary}"""
        return ElchiJson.decodeFromString(ProposalThreadDTO.serializer(), json)
    }

    private fun listing(status: String = "published", comment: String? = "Mo'rt narsa", price: Long = 15_000_000, kind: String = "request"): ListingDTO =
        ElchiJson.decodeFromString(
            ListingDTO.serializer(),
            """{"id":"lst_1","kind":"$kind","service_type":"parcel","status":"$status","version":4,"terms_version":2,
            "owner":{"id":"usr_1","display_name":"Demo"},"corridor_id":"cor_1",
            "origin_point":{"lat":41.3,"lng":69.2,"district":{"id":"dst_a","name_uz":"Toshkent shahri"},"address":"Oʻzbekiston, Toshkent, Chilonzor"},
            "destination_point":{"lat":39.7,"lng":64.4,"district":{"id":"dst_b","name_uz":"Buxoro"},"address":null},
            "departure_window_start":"2026-09-30T04:00:00Z","departure_window_end":"2026-09-30T13:00:00Z","timezone":"Asia/Tashkent",
            "price_basis":"total","unit_price_minor":$price,"quantity":1,"total_minor":$price,"currency":"UZS","payment_method":"cash",
            "expires_at":"2026-09-30T13:00:00Z","comment":${comment?.let { "\"$it\"" } ?: "null"},"view_count":14,"created_at":"2026-09-29T06:00:00Z"}""",
        )

    // -- negotiation --------------------------------------------------------------------------------------------

    @Test
    fun `the driver's live offer can be accepted, rejected and countered by the client`() {
        val a = OrderRules.negotiationActions(thread(), now)
        assertTrue(a.open && a.theirTurn && a.canAccept && a.canReject && a.canCounter)
        assertFalse(a.canWithdraw)
        assertEquals(3L, a.revisionsLeft)
    }

    @Test
    fun `the client's own counter can only be withdrawn (AC05)`() {
        val a = OrderRules.negotiationActions(thread(author = "client"), now)
        assertTrue(a.open && a.canWithdraw)
        assertFalse(a.theirTurn || a.canAccept || a.canReject || a.canCounter)
    }

    @Test
    fun `no price revision left means no counter - the web bug of offering it anyway is not copied`() {
        val a = OrderRules.negotiationActions(thread(clientLeft = 0), now)
        assertTrue(a.canAccept && a.canReject)
        assertFalse(a.canCounter)
        assertEquals(0L, a.revisionsLeft)
    }

    @Test
    fun `an offer past its expires_at is closed at once, before the server's sweep`() {
        val a = OrderRules.negotiationActions(thread(expires = "2026-09-29T10:00:00Z"), now)
        assertFalse(a.open || a.canAccept || a.canReject || a.canCounter || a.canWithdraw)
        assertTrue(a.expiredLocally)
        assertEquals("proposalStatus.expired", OrderRules.closedStatusKey(thread(expires = "2026-09-29T10:00:00Z"), now))
        // One second before, it is still live.
        assertTrue(OrderRules.negotiationActions(thread(expires = "2026-09-29T10:00:01Z"), now).open)
    }

    @Test
    fun `closed threads and closed versions allow nothing and say why`() {
        assertEquals(NegotiationActions.CLOSED, OrderRules.negotiationActions(thread(state = "closed", status = "rejected"), now))
        assertEquals(NegotiationActions.CLOSED, OrderRules.negotiationActions(thread(state = "open", status = "withdrawn"), now))
        assertEquals(NegotiationActions.CLOSED, OrderRules.negotiationActions(thread(withVersion = false), now))
        assertEquals("proposalStatus.rejected", OrderRules.closedStatusKey(thread(state = "closed", status = "rejected"), now))
        assertEquals("proposalStatus.accepted", OrderRules.closedStatusKey(thread(state = "accepted", status = "active"), now))
    }

    @Test
    fun `countdown rounds up to whole minutes`() {
        val version = thread().currentVersion!!
        assertEquals(6000L, OrderRules.secondsLeft(version, now)) // 1 h 40 min
        assertEquals(1L to 40L, OrderRules.countdownParts(6000))
        assertEquals(0L to 1L, OrderRules.countdownParts(45))
        assertEquals(0L to 55L, OrderRules.countdownParts(55 * 60))
        assertEquals(0L, OrderRules.secondsLeft(version, Instant.parse("2026-09-29T12:00:00Z")))
    }

    @Test
    fun `offers sort live first, then by the chosen order, and the cheapest open one is marked`() {
        val cheapClosed = thread(id = "a", state = "closed", status = "expired", total = 9_000_000)
        val mid = thread(id = "b", total = 14_000_000, pickupStart = "2026-09-30T09:00:00Z", bucket = "mixed", ratings = 5)
        val cheap = thread(id = "c", total = 13_500_000, pickupStart = "2026-09-30T11:00:00Z", bucket = "good", ratings = 2)
        val fast = thread(id = "d", total = 15_000_000, pickupStart = "2026-09-30T03:00:00Z", bucket = null, ratings = 0)
        val all = listOf(cheapClosed, mid, cheap, fast)
        assertEquals(listOf("c", "b", "d", "a"), OrderRules.sortOffers(all, OfferSort.CHEAPEST, now).map { it.id })
        assertEquals(listOf("d", "b", "c", "a"), OrderRules.sortOffers(all, OfferSort.FASTEST, now).map { it.id })
        assertEquals(listOf("c", "b", "d", "a"), OrderRules.sortOffers(all, OfferSort.RATING, now).map { it.id })
        assertEquals("c", OrderRules.cheapestOpen(all, now))
        assertNull(OrderRules.cheapestOpen(listOf(cheapClosed), now))
        // The client's own (cheaper) counter is waiting for the driver - it is not an offer to choose.
        val waiting = thread(id = "e", author = "client", total = 10_000_000)
        assertEquals("c", OrderRules.cheapestOpen(all + waiting, now))
        assertEquals(listOf("c", "b", "d", "e", "a"), OrderRules.sortOffers(all + waiting, OfferSort.CHEAPEST, now).map { it.id })
    }

    @Test
    fun `offer stats count live offers and the newest arrival`() {
        val stats = OrderRules.offerStats(listOf(thread(id = "a"), thread(id = "b", state = "closed", status = "rejected"), thread(id = "c", expires = "2026-09-29T09:00:00Z")), now)
        assertEquals(1, stats.open)
        assertEquals(Instant.parse("2026-09-29T09:48:00Z"), stats.latest)
    }

    // -- promo --------------------------------------------------------------------------------------------------

    @Test
    fun `bonus consent is sent only when ticked and only with a quote`() {
        val promo = """{"view":"client","fare_minor":14000000,"passenger_discount_minor":1000000,"cash_due_minor":13000000,"currency":"UZS"}"""
        val quote = thread(promo = promo).currentVersion!!.promoQuote as ProposalPromoClientDTO
        assertNull(OrderRules.acceptConsent(quote, ticked = false))
        assertNull(OrderRules.acceptConsent(null, ticked = true))
        val consent = OrderRules.acceptConsent(quote, ticked = true)!!
        assertEquals(1_000_000L, consent.passengerBonusMinor)
        assertEquals(13_000_000L, consent.cashDueMinor)
        assertEquals(13_000_000L, OrderRules.counterConsent(quote, ticked = true)!!.cashDueMinor)
        assertEquals("promo.noDiscount.noCampaign", OrderRules.noDiscountKey("no_campaign"))
        assertNull(OrderRules.noDiscountKey("something_new"))
        assertNull(OrderRules.noDiscountKey(null))
    }

    // -- listing edit -------------------------------------------------------------------------------------------

    private val form = OrderRules.editForm(listing())

    @Test
    fun `the edit form starts from the listing in Tashkent time`() {
        assertEquals("150000", form.priceDigits)
        assertEquals("Mo'rt narsa", form.comment)
        assertEquals(LocalDateTime.of(2026, 9, 30, 9, 0), form.windowStart)
        assertEquals(LocalDateTime.of(2026, 9, 30, 18, 0), form.windowEnd)
        assertTrue(OrderRules.planListingPatch(listing(), form, now).empty)
    }

    @Test
    fun `price and comment are not material (Q20)`() {
        val plan = OrderRules.planListingPatch(listing(), form.copy(priceDigits = "140000", comment = "  Ehtiyot bo'ling "), now)
        assertEquals(14_000_000L, plan.unitPriceMinor)
        assertEquals("Ehtiyot bo'ling", plan.comment)
        assertNull(plan.windowStartIso)
        assertFalse(plan.material)
        assertNull(plan.invalid)
        // Clearing the comment sends an empty one.
        assertEquals("", OrderRules.planListingPatch(listing(), form.copy(comment = "  "), now).comment)
    }

    @Test
    fun `a moved window is material on a live listing and travels as a pair`() {
        val plan = OrderRules.planListingPatch(listing(), form.copy(windowEnd = LocalDateTime.of(2026, 9, 30, 20, 0)), now)
        assertEquals("2026-09-30T09:00:00+05:00", plan.windowStartIso)
        assertEquals("2026-09-30T20:00:00+05:00", plan.windowEndIso)
        assertTrue(plan.material)
        assertTrue(OrderRules.planListingPatch(listing(status = "paused"), form.copy(windowStart = LocalDateTime.of(2026, 9, 30, 10, 0)), now).material)
        // A draft has no offers to close.
        assertFalse(OrderRules.planListingPatch(listing(status = "draft"), form.copy(windowStart = LocalDateTime.of(2026, 9, 30, 10, 0)), now).material)
    }

    @Test
    fun `invalid edits are named`() {
        assertEquals(EditInvalid.PRICE, OrderRules.planListingPatch(listing(), form.copy(priceDigits = ""), now).invalid)
        assertEquals(EditInvalid.WINDOW_INCOMPLETE, OrderRules.planListingPatch(listing(), form.copy(windowEnd = null), now).invalid)
        assertEquals(EditInvalid.WINDOW_ORDER, OrderRules.planListingPatch(listing(), form.copy(windowEnd = LocalDateTime.of(2026, 9, 30, 8, 0)), now).invalid)
        val past = form.copy(windowStart = LocalDateTime.of(2026, 9, 28, 9, 0), windowEnd = LocalDateTime.of(2026, 9, 29, 12, 0))
        assertEquals(EditInvalid.WINDOW_PAST, OrderRules.planListingPatch(listing(), past, now).invalid)
        assertEquals("window_order", EditInvalid.WINDOW_ORDER.key)
    }

    @Test
    fun `after a version conflict the typed fields stay and the others take the new values`() {
        val typed = form.copy(priceDigits = "121000")
        val fresh = form.copy(comment = "Changed on another phone", windowEnd = LocalDateTime.of(2026, 9, 30, 19, 0))
        val rebased = OrderRules.rebaseForm(typed, base = form, fresh = fresh)
        assertEquals("121000", rebased.priceDigits)
        assertEquals("Changed on another phone", rebased.comment)
        assertEquals(LocalDateTime.of(2026, 9, 30, 19, 0), rebased.windowEnd)
        assertEquals(form.windowStart, rebased.windowStart)
    }

    @Test
    fun `a trip offer's window is not the owner's to move`() {
        val plan = OrderRules.planListingPatch(listing(kind = "trip_offer"), form.copy(windowEnd = LocalDateTime.of(2026, 9, 30, 20, 0)), now)
        assertTrue(plan.empty)
        assertFalse(plan.material)
    }

    @Test
    fun `owner actions follow the listing status`() {
        assertTrue(OrderRules.canPause(ListingStatus.PUBLISHED) && !OrderRules.canPause(ListingStatus.PAUSED))
        assertTrue(OrderRules.canResume(ListingStatus.PAUSED) && !OrderRules.canResume(ListingStatus.PUBLISHED))
        assertTrue(listOf(ListingStatus.DRAFT, ListingStatus.PUBLISHED, ListingStatus.PAUSED).all { OrderRules.canEdit(it) && OrderRules.canCancel(it) })
        assertFalse(listOf(ListingStatus.FULFILLED, ListingStatus.EXPIRED, ListingStatus.CANCELLED).any { OrderRules.canEdit(it) || OrderRules.canCancel(it) })
        assertTrue(OrderRules.canShare(ListingStatus.PAUSED) && !OrderRules.canShare(ListingStatus.DRAFT))
    }

    // -- share --------------------------------------------------------------------------------------------------

    @Test
    fun `share chips in days become ttl hours within 1-336`() {
        assertEquals(listOf(24L, 48L, 72L, 168L, 336L), OrderRules.SHARE_TTL_DAYS.map(OrderRules::shareTtlHours))
        assertEquals(336L, OrderRules.shareTtlHours(30))
        assertEquals(1L, OrderRules.shareTtlHours(0))
        assertTrue(OrderRules.SHARE_TTL_DEFAULT_DAYS in OrderRules.SHARE_TTL_DAYS)
    }

    // -- statuses -----------------------------------------------------------------------------------------------

    @Test
    fun `listing statuses use the status words and the design's tones`() {
        assertEquals("status.published", OrderRules.listingStatusKey(ListingStatus.PUBLISHED))
        assertEquals(Tone.BLUE, OrderRules.statusTone("published"))
        assertEquals(Tone.GRAY, OrderRules.statusTone("paused"))
        assertEquals(Tone.GRAY, OrderRules.statusTone("expired"))
        assertEquals(Tone.GRAY, OrderRules.statusTone("draft"))
        assertEquals(Tone.OK, OrderRules.statusTone("fulfilled"))
        assertEquals(Tone.ERR, OrderRules.statusTone("cancelled"))
        assertEquals(Tone.GRAY, OrderRules.statusTone("something_new"))
    }

    @Test
    fun `a parcel in transit only says the driver departed (Q139, Q142)`() {
        assertEquals("parcel.status.driverDeparted", OrderRules.bookingStatusKey(ServiceType.PARCEL, "in_transit"))
        assertEquals("parcel.status.driverDeparted", OrderRules.bookingStatusKey(ServiceType.PARCEL, "picked_up"))
        assertEquals(Tone.BLUE, OrderRules.bookingTone(ServiceType.PARCEL, "picked_up"))
        assertEquals(Tone.BLUE, OrderRules.bookingTone(ServiceType.PARCEL, "in_transit"))
        assertEquals("parcel.progress.tripPreparing", OrderRules.bookingStatusKey(ServiceType.PARCEL, "awaiting_pickup"))
        assertEquals("parcel.progress.deliveredByOperator", OrderRules.bookingStatusKey(ServiceType.PARCEL, "delivered"))
        assertEquals("tripDetail.service.return_required", OrderRules.bookingStatusKey(ServiceType.PARCEL, "return_required"))
        assertEquals("status.confirmed", OrderRules.bookingStatusKey(ServiceType.PARCEL, "confirmed"))
        assertEquals("status.cancelled", OrderRules.bookingStatusKey(ServiceType.PARCEL, "cancelled"))
        assertEquals(Tone.ERR, OrderRules.bookingTone(ServiceType.PARCEL, "delivery_failed"))
        assertEquals("status.in_transit", OrderRules.bookingStatusKey(ServiceType.PASSENGER, "onboard"))
        assertEquals("status.completed", OrderRules.legacyStatusKey("completed"))
    }

    // -- money --------------------------------------------------------------------------------------------------

    @Test
    fun `legacy v1 prices are decimal so'm, final before suggested`() {
        assertEquals(7_000_000L, OrderRules.legacyPriceMinor(JsonPrimitive("70000.00"), JsonPrimitive("65000.00")))
        assertEquals(6_500_000L, OrderRules.legacyPriceMinor(JsonNull, JsonPrimitive("65000.00")))
        assertEquals(6_500_000L, OrderRules.legacyPriceMinor(null, JsonPrimitive(65000)))
        assertEquals(6_500_050L, OrderRules.legacyPriceMinor(null, JsonPrimitive("65000.5")))
        assertEquals(12_345_678L, OrderRules.legacyPriceMinor(JsonPrimitive(123456.78), null))
        assertNull(OrderRules.legacyPriceMinor(JsonPrimitive(""), JsonPrimitive("abc")))
        assertNull(OrderRules.legacyPriceMinor(JsonPrimitive("0"), null))
    }

    // -- names, dates -------------------------------------------------------------------------------------------

    @Test
    fun `route ends are named by stop, then district or address, else coordinates`() {
        val v = thread().currentVersion!!
        assertEquals("Chilonzor", OrderRules.shortEnd(v.pickupStop, v.pickupPoint, ru = false))
        assertEquals("Toshkent, Chilonzor", OrderRules.fullEnd(v.pickupStop, v.pickupPoint, ru = false))
        assertEquals("Buxoro avtovokzali", OrderRules.fullEnd(v.dropoffStop, v.dropoffPoint, ru = false))
        assertEquals("Бухарский автовокзал", OrderRules.shortEnd(v.dropoffStop, v.dropoffPoint, ru = true))
        val l = listing()
        assertEquals("Toshkent, Chilonzor", OrderRules.fullEnd(l.originStop, l.originPoint, ru = false))
        assertEquals("Buxoro", OrderRules.fullEnd(l.destinationStop, l.destinationPoint, ru = false))
    }

    @Test
    fun `dates are shown in Tashkent`() {
        assertEquals("30 sen", OrderRules.dayMonth("2026-09-30T04:00:00Z", "uz"))
        assertEquals("30.09", OrderRules.dayDot("2026-09-29T20:00:00Z")) // 01:00 next day in Tashkent is still 30.09
        assertEquals("30.09, 09:00 - 30.09, 18:00", OrderRules.windowText("2026-09-30T04:00:00Z", "2026-09-30T13:00:00Z"))
        assertEquals("30.09 - 30.09", OrderRules.dayRange("2026-09-30T04:00:00Z", "2026-09-30T13:00:00Z"))
        assertEquals(OrderRules.Ago.Minutes(12), OrderRules.ago(Instant.parse("2026-09-29T09:48:00Z"), now))
        assertEquals(OrderRules.Ago.Minutes(1), OrderRules.ago(now, now))
        assertEquals(OrderRules.Ago.Hours(2), OrderRules.ago(Instant.parse("2026-09-29T07:30:00Z"), now))
        assertEquals(OrderRules.Ago.Days(3), OrderRules.ago(Instant.parse("2026-09-26T09:00:00Z"), now))
    }

    // -- bookings -----------------------------------------------------------------------------------------------

    @Test
    fun `the client view of a booking is read from the raw union, a driver row is not`() {
        val json = ElchiJson.parseToJsonElement(
            """{"id":"bkg_1","viewer_side":"client","service_type":"parcel","service_status":"confirmed","cash_status":"pending",
            "pickup":{"point":{"lat":41.3,"lng":69.2,"district":{"id":"d","name_uz":"Chilonzor"}},"occurrence_seq":1,"window_start":"2026-09-30T05:00:00Z"},
            "dropoff":{"stop":{"id":"stp","name_uz":"Registon"},"occurrence_seq":3},"quantity":1,"unit_price_minor":14000000,"total_minor":14000000,
            "currency":"UZS","promo":{"view":"client","fare_minor":14000000,"passenger_discount_minor":1000000,"cash_due_minor":13000000,"currency":"UZS"},
            "created_at":"2026-09-29T10:00:00Z","listing_ids":{"request":"lst_1"},"contact":{"phones_visible":false}}""",
        )
        val booking = BookingClientDTO.fromJson(json)!!
        assertEquals("bkg_1", booking.id)
        assertEquals(13_000_000L, booking.promo!!.cashDueMinor)
        assertEquals("Registon", OrderRules.shortEnd(booking.dropoff.stop, booking.dropoff.point, ru = false))
        val driver = ElchiJson.parseToJsonElement(json.toString().replace("\"viewer_side\":\"client\"", "\"viewer_side\":\"driver\""))
        assertNull(BookingClientDTO.fromJson(driver))
    }
}
