package uz.elchi.app.feature.driver

import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.generated.ActorSide
import uz.elchi.app.api.generated.ApiWarning
import uz.elchi.app.api.generated.ListingStatus
import uz.elchi.app.api.generated.PriceBasis
import uz.elchi.app.api.generated.ProposalStatus
import uz.elchi.app.api.generated.TripStatus
import java.time.Instant

class OfferRulesTest {
    private val now: Instant = Instant.parse("2026-10-01T06:00:00Z")

    // -- what the offer screen shows (also the target of elchi://listings/{id}, Stage 10) ----------------------

    @Test
    fun `an unapproved driver sees the gate first, then a closed listing is one sentence, else the form`() {
        listOf(DriverStatus.NEW, DriverStatus.PENDING, DriverStatus.REJECTED, DriverStatus.BLOCKED).forEach { st ->
            assertEquals(st.name, BidView.GATE, OfferRules.bidView(st, ListingStatus.PUBLISHED))
            assertEquals(st.name, BidView.GATE, OfferRules.bidView(st, ListingStatus.EXPIRED))
        }
        assertEquals(BidView.FORM, OfferRules.bidView(DriverStatus.APPROVED, ListingStatus.PUBLISHED))
        // Status still loading: not the gate (the server refuses an unapproved driver anyway).
        assertEquals(BidView.FORM, OfferRules.bidView(null, ListingStatus.PUBLISHED))
        listOf(ListingStatus.PAUSED, ListingStatus.FULFILLED, ListingStatus.EXPIRED, ListingStatus.CANCELLED, ListingStatus.DRAFT, ListingStatus.UNKNOWN).forEach {
            assertEquals(it.name, BidView.CLOSED, OfferRules.bidView(DriverStatus.APPROVED, it))
            assertEquals(it.name, BidView.CLOSED, OfferRules.bidView(null, it))
        }
    }

    // -- pickup window ----------------------------------------------------------------------------------------

    @Test
    fun `stop-ended request - trip time at the origin plus minus 30 min, clipped to the client's window`() {
        val listing = S08.listing(originStop = S08.stop("stp_tash"), destinationStop = S08.stop("stp_sam"), windowStart = "2026-10-02T04:10:00Z", windowEnd = "2026-10-02T13:00:00Z")
        val trip = S08.trip(stops = listOf("stp_tash" to "2026-10-02T04:00:00Z", "stp_sam" to "2026-10-02T09:28:00Z"))
        val w = OfferRules.pickupWindow(trip, listing)!!
        assertEquals(Instant.parse("2026-10-02T04:10:00Z"), w.start) // clipped: the client asked from 09:10
        assertEquals(Instant.parse("2026-10-02T04:30:00Z"), w.end)
    }

    @Test
    fun `stop-ended request the trip misses, or a trip not passing the stop, has no window`() {
        val listing = S08.listing(originStop = S08.stop("stp_tash"), destinationStop = S08.stop("stp_sam"), windowStart = "2026-10-02T08:00:00Z", windowEnd = "2026-10-02T13:00:00Z")
        assertNull(OfferRules.pickupWindow(S08.trip(), listing))
        val elsewhere = S08.listing(originStop = S08.stop("stp_jiz"), destinationStop = S08.stop("stp_sam"))
        assertNull(OfferRules.pickupWindow(S08.trip(), elsewhere))
        assertNull(OfferRules.pickupWindow(null, listing))
    }

    @Test
    fun `point-ended request offers the client's own window`() {
        val listing = S08.listing()
        val w = OfferRules.pickupWindow(S08.trip(), listing)!!
        assertEquals(Instant.parse("2026-10-02T04:00:00Z"), w.start)
        assertEquals(Instant.parse("2026-10-02T13:00:00Z"), w.end)
    }

    @Test
    fun `trip candidates are planned before cutoff, preselect the one that fits the time`() {
        val past = S08.trip("past", cutoff = "2026-09-24T11:55:00Z", start = "2026-09-24T11:55:00Z", end = "2026-09-24T15:55:00Z")
        val boarding = S08.trip("boarding", status = TripStatus.BOARDING)
        val tomorrowLate = S08.trip("late", start = "2026-10-02T15:00:00Z", end = "2026-10-02T23:00:00Z", cutoff = "2026-10-02T15:00:00Z")
        val tomorrow = S08.trip("fit", start = "2026-10-02T05:00:00Z", end = "2026-10-02T13:00:00Z", cutoff = "2026-10-02T05:00:00Z")
        val candidates = OfferRules.candidateTrips(listOf(past, boarding, tomorrowLate, tomorrow), now)
        assertEquals(listOf("fit", "late"), candidates.map { it.id })
        assertEquals("fit", OfferRules.preselect(candidates.reversed(), S08.listing())?.id)
        assertNull(OfferRules.preselect(listOf(tomorrowLate), S08.listing()))
    }

    // -- offer body ---------------------------------------------------------------------------------------------

    @Test
    fun `offer body - point request sends no stop ids, stop request sends both`() {
        val window = PickupWindow(Instant.parse("2026-10-02T04:00:00Z"), Instant.parse("2026-10-02T05:00:00Z"))
        val point = OfferRules.proposalBody(S08.listing(), "trp_1", window, 11_000_000, message = "  ")
        assertNull(point.pickupStopId)
        assertNull(point.dropoffStopId)
        assertNull(point.message)
        assertEquals("trp_1", point.tripId)
        assertEquals("2026-10-02T09:00:00+05:00", point.pickupWindowStart)
        assertEquals("2026-10-02T10:00:00+05:00", point.pickupWindowEnd)
        assertEquals(1L, point.quantity)
        assertEquals(PriceBasis.TOTAL, point.priceBasis)
        assertEquals(11_000_000L, point.unitPriceMinor)

        val stops = OfferRules.proposalBody(S08.listing(originStop = S08.stop("stp_tash"), destinationStop = S08.stop("stp_sam"), basis = PriceBasis.PER_SEAT, quantity = 2), "trp_1", window, 5_000_000)
        assertEquals("stp_tash", stops.pickupStopId)
        assertEquals("stp_sam", stops.dropoffStopId)
        assertEquals(2L, stops.quantity)
        assertEquals(PriceBasis.PER_SEAT, stops.priceBasis)
        // One stop end and one point end: neither id (both or neither).
        val mixed = OfferRules.proposalBody(S08.listing(originStop = S08.stop("stp_tash")), "trp_1", window, 1)
        assertNull(mixed.pickupStopId)
        assertNull(mixed.dropoffStopId)
        assertEquals("120000", OfferRules.prefillPrice(S08.listing()))
    }

    // -- board and money ----------------------------------------------------------------------------------------

    @Test
    fun `board summary counts, finds the cheapest and the driver's own`() {
        val b = OfferRules.board(listOf(S08.offer("Haydovchi #4", 12_500_000), S08.offer("Haydovchi #1", 11_000_000), S08.offer("Haydovchi #2", 12_000_000, mine = true)))
        assertEquals(3, b.count)
        assertEquals(11_000_000L, b.cheapestMinor)
        assertEquals("Haydovchi #2", b.mine?.label)
        assertEquals(listOf("Haydovchi #1", "Haydovchi #2", "Haydovchi #4"), b.rows.map { it.label })
        val empty = OfferRules.board(emptyList())
        assertEquals(0, empty.count)
        assertNull(empty.cheapestMinor)
        assertNull(empty.mine)
        assertEquals("15", OfferRules.percent(1500))
        assertEquals("8,5", OfferRules.percent(850))
        assertEquals("0,25", OfferRules.percent(25))
    }

    @Test
    fun `price band warning carries floor and ceiling`() {
        val w = ApiWarning(code = "PRICE_OUTSIDE_REFERENCE", message = "m", details = buildJsonObject { put("floor_minor", 8_000_000); put("ceiling_minor", 15_000_000) })
        assertEquals(w, OfferRules.priceWarning(listOf(ApiWarning(code = "CONTACT_INFO_MASKED", message = "m"), w)))
        assertEquals(8_000_000L to 15_000_000L, OfferRules.band(w))
        assertNull(OfferRules.priceWarning(emptyList()))
    }

    // -- errors -------------------------------------------------------------------------------------------------

    @Test
    fun `errors map to sentences and an existing thread is opened instead`() {
        assertEquals("driverBid.tripWindowMismatch", OfferRules.errorKey(ApiException(409, "TIME_WINDOW_CONFLICT", "x")))
        assertEquals("client.listingBids.termsChanged", OfferRules.errorKey(ApiException(409, "PROPOSAL_CHANGED", "x")))
        assertNull(OfferRules.errorKey(ApiException(409, "BOOKING_CUTOFF_PASSED", "x"))) // error.BOOKING_CUTOFF_PASSED
        val open = ApiException(409, "INVALID_STATE_TRANSITION", "x", buildJsonObject { put("reason", "open_thread_exists"); put("thread_id", "prt_9") })
        assertEquals("prt_9", OfferRules.openThreadId(open))
        assertNull(OfferRules.openThreadId(ApiException(409, "INVALID_STATE_TRANSITION", "x", buildJsonObject { put("reason", "open_thread_exists") })))
        assertNull(OfferRules.openThreadId(ApiException(409, "ROUTE_MISMATCH", "x")))
    }

    // -- my offers ----------------------------------------------------------------------------------------------

    @Test
    fun `client countered - the driver may accept, reject, counter while revisions remain`() {
        val t = S08.thread(S08.version(author = ActorSide.CLIENT, driverLeft = 2))
        val a = OfferRules.actions(t, now)
        assertTrue(a.canAccept && a.canReject && a.canCounter)
        assertFalse(a.canWithdraw)
        assertEquals(2L, OfferRules.revisionsLeft(t))
        assertEquals(ThreadLine.Countered, OfferRules.line(t, now))
        val none = OfferRules.actions(S08.thread(S08.version(author = ActorSide.CLIENT, driverLeft = 0)), now)
        assertTrue(none.canAccept)
        assertFalse(none.canCounter)
    }

    @Test
    fun `own version pending - only withdraw`() {
        val t = S08.thread(S08.version(author = ActorSide.DRIVER))
        val a = OfferRules.actions(t, now)
        assertFalse(a.canAccept || a.canReject || a.canCounter)
        assertTrue(a.canWithdraw)
        assertEquals(ThreadLine.Waiting, OfferRules.line(t, now))
    }

    @Test
    fun `closed, accepted and locally expired threads`() {
        val expired = S08.thread(S08.version(expires = "2026-10-01T05:59:00Z"))
        assertFalse(OfferRules.actions(expired, now).open)
        assertTrue(OfferRules.actions(expired, now).expiredLocally)
        assertNull(OfferRules.secondsLeft(expired, now))
        assertEquals(ThreadLine.Accepted, OfferRules.line(S08.thread(S08.version(status = ProposalStatus.ACCEPTED), state = "accepted", bookingId = "bkg_1"), now))
        assertEquals(ThreadLine.Closed("proposalStatus.withdrawn"), OfferRules.line(S08.thread(S08.version(status = ProposalStatus.WITHDRAWN), state = "closed"), now))
        assertEquals(ThreadLine.Closed("proposalStatus.expired"), OfferRules.line(expired, now))
    }

    @Test
    fun `expiry counts down in whole minutes, rounded up`() {
        val t = S08.thread(S08.version(expires = "2026-10-01T07:12:01Z"))
        assertEquals(4321L, OfferRules.secondsLeft(t, now))
        assertEquals(1L to 13L, OfferRules.expiryParts(4321))
        assertEquals(0L to 1L, OfferRules.expiryParts(1))
        assertEquals(0L to 0L, OfferRules.expiryParts(0))
    }

    @Test
    fun `route title and history read the versions`() {
        val v1 = S08.version("prv_1", ActorSide.DRIVER, revision = 1, status = ProposalStatus.SUPERSEDED)
        val v2 = S08.version("prv_2", ActorSide.CLIENT, revision = 2)
        val t = S08.thread(v2, versions = listOf(v2, v1))
        assertEquals("Toshkent shahri → Samarqand", OfferRules.routeTitle(t, ru = false))
        assertEquals(listOf("prv_1", "prv_2"), OfferRules.history(t).map { it.id })
        assertEquals(listOf("prv_2"), OfferRules.history(S08.thread(v2)).map { it.id })
    }

    @Test
    fun `counter keeps the window, sends the price against the current revision`() {
        val v = S08.version(revision = 3)
        val body = OfferRules.counterBody(v, 11_500_000)
        assertEquals(3L, body.expectedRevision)
        assertEquals(11_500_000L, body.unitPriceMinor)
        assertEquals(v.pickupWindowStart, body.pickupWindowStart)
        assertEquals(v.pickupWindowEnd, body.pickupWindowEnd)
    }

    @Test
    fun `accept sends the version and the thread's listing terms version`() {
        val v = S08.version("prv_7", ActorSide.CLIENT)
        val body = OfferRules.acceptBody(S08.thread(v, listingTermsVersion = 3), v)
        assertEquals("prv_7", body.proposalVersionId)
        assertEquals(3L, body.expectedListingTermsVersion)
        assertNull(body.expectedListingVersion) // the server wants one of the two aliases, equal if both
        assertNull(body.promoDriverAck)
        val mismatch = ApiException(409, "PROPOSAL_CHANGED", "x", buildJsonObject { put("reason", "listing_terms_version_mismatch"); put("current_listing_terms_version", 4) })
        assertTrue(OfferRules.termsChanged(mismatch))
        assertTrue(OfferRules.needsRefresh(mismatch))
        assertFalse(OfferRules.termsChanged(ApiException(409, "VERSION_CONFLICT", "x")))
        assertEquals("bkg_1", OfferRules.bookingId(buildJsonObject { put("id", "bkg_1") }))
        assertNull(OfferRules.bookingId(null))
    }
}
