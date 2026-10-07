package uz.elchi.app.feature.driver

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.api.generated.ActorSide
import uz.elchi.app.api.generated.DistrictDTO
import uz.elchi.app.api.generated.FeedSide
import uz.elchi.app.api.generated.ProposalStatus
import uz.elchi.app.api.generated.RegionDTO
import uz.elchi.app.api.generated.RegionRefDTO
import uz.elchi.app.api.generated.SavedSearchDTO
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.api.generated.TripStatus
import uz.elchi.app.feature.client.Load
import uz.elchi.app.ui.components.LadderState
import uz.elchi.app.ui.theme.Tone
import java.time.Instant

class Design07RulesTest {
    private val now: Instant = Instant.parse("2026-10-01T06:00:00Z")

    // -- feed: already offered / accepted (§5.7) ----------------------------------------------------------------

    @Test
    fun `feed marks an open thread with its current total and an accepted one as accepted`() {
        val open = S08.thread(S08.version(total = 9_000_000)).copy(id = "prt_open", listingId = "lst_a")
        val other = S08.thread(S08.version(total = 7_000_000)).copy(id = "prt_b", listingId = "lst_b")
        val accepted = S08.thread(S08.version(status = ProposalStatus.ACCEPTED), state = "accepted", bookingId = "bkg_1").copy(id = "prt_acc", listingId = "lst_c")
        val marks = Design07Rules.myFeedOffers(listOf(open, other), listOf(accepted))
        assertEquals(MyFeedOffer.Sent("prt_open", 9_000_000), marks["lst_a"])
        assertEquals(MyFeedOffer.Sent("prt_b", 7_000_000), marks["lst_b"])
        assertEquals(MyFeedOffer.Accepted("prt_acc"), marks["lst_c"])
        assertNull(marks["lst_none"])
    }

    @Test
    fun `under a client counter the feed shows the driver's own earlier price, not the client's`() {
        val countered = S08.thread(S08.version(author = ActorSide.CLIENT, revision = 2, total = 12_500_000)).copy(id = "prt_c", listingId = "lst_c")
        assertEquals(MyFeedOffer.Sent("prt_c", 14_500_000), Design07Rules.myFeedOffers(listOf(countered), emptyList(), mine = mapOf("prt_c" to 14_500_000L))["lst_c"])
        // History not read yet: the current total stands in.
        assertEquals(MyFeedOffer.Sent("prt_c", 12_500_000), Design07Rules.myFeedOffers(listOf(countered), emptyList())["lst_c"])
    }

    @Test
    fun `an accepted thread wins over an open one on the same listing, and closed threads mark nothing`() {
        val open = S08.thread(S08.version()).copy(id = "prt_open", listingId = "lst_a")
        val accepted = S08.thread(S08.version(), state = "accepted").copy(id = "prt_acc", listingId = "lst_a")
        assertEquals(MyFeedOffer.Accepted("prt_acc"), Design07Rules.myFeedOffers(listOf(open), listOf(accepted))["lst_a"])
        val closed = S08.thread(S08.version(status = ProposalStatus.WITHDRAWN), state = "closed").copy(listingId = "lst_x")
        assertTrue(Design07Rules.myFeedOffers(listOf(closed), emptyList()).isEmpty())
    }

    // -- Takliflarim badges and lines (§8.1, §8.2) ------------------------------------------------------------

    private val later = "2026-10-01T12:00:00Z"

    @Test
    fun `badge per state, with my counter as its own state`() {
        val waiting = S08.thread(S08.version(author = ActorSide.DRIVER, revision = 1, expires = later))
        val countered = S08.thread(S08.version(author = ActorSide.CLIENT, revision = 2, expires = later))
        val myCounter = S08.thread(S08.version(author = ActorSide.DRIVER, revision = 3, expires = later))
        val accepted = S08.thread(S08.version(status = ProposalStatus.ACCEPTED), state = "accepted", bookingId = "bkg_1")
        val rejected = S08.thread(S08.version(status = ProposalStatus.REJECTED), state = "closed")
        val withdrawn = S08.thread(S08.version(status = ProposalStatus.WITHDRAWN), state = "closed")
        val expired = S08.thread(S08.version(expires = "2026-10-01T05:00:00Z"))
        assertEquals(ProposalBadge.WAITING, Design07Rules.badge(waiting, now))
        assertEquals(ProposalBadge.COUNTERED, Design07Rules.badge(countered, now))
        assertEquals(ProposalBadge.MY_COUNTER, Design07Rules.badge(myCounter, now))
        assertEquals(ProposalBadge.ACCEPTED, Design07Rules.badge(accepted, now))
        assertEquals(ProposalBadge.REJECTED, Design07Rules.badge(rejected, now))
        assertEquals(ProposalBadge.WITHDRAWN, Design07Rules.badge(withdrawn, now))
        assertEquals(ProposalBadge.EXPIRED, Design07Rules.badge(expired, now))
        // Keys and tones as the design draws them.
        assertEquals("status.proposed" to Tone.GRAY, ProposalBadge.WAITING.key to ProposalBadge.WAITING.tone)
        assertEquals("driver.offer.badgeCountered" to Tone.WARN, ProposalBadge.COUNTERED.key to ProposalBadge.COUNTERED.tone)
        assertEquals("driver.offer.badgeMyCounter" to Tone.BLUE, ProposalBadge.MY_COUNTER.key to ProposalBadge.MY_COUNTER.tone)
        assertEquals("client.booking.amendStatusAccepted" to Tone.OK, ProposalBadge.ACCEPTED.key to ProposalBadge.ACCEPTED.tone)
        assertEquals("status.rejected" to Tone.ERR, ProposalBadge.REJECTED.key to ProposalBadge.REJECTED.tone)
        assertTrue(Design07Rules.outlined(ProposalBadge.COUNTERED))
        assertFalse(Design07Rules.outlined(ProposalBadge.WAITING))
        assertTrue(Design07Rules.faded(ProposalBadge.WITHDRAWN))
    }

    @Test
    fun `card lines carry the prices - client counter with my earlier price, my counter, waiting, accepted`() {
        val mine1 = S08.version(id = "v1", author = ActorSide.DRIVER, revision = 1, total = 11_000_000, status = ProposalStatus.SUPERSEDED)
        val client2 = S08.version(id = "v2", author = ActorSide.CLIENT, revision = 2, total = 9_000_000, expires = later)
        val withHistory = S08.thread(client2, versions = listOf(mine1, client2))
        assertEquals(ProposalCardLine.ClientCounter(9_000_000, 11_000_000), Design07Rules.cardLine(withHistory, now))
        // The list has no versions: the price the driver offered is not known yet (the sentence falls back).
        val noHistory = S08.thread(client2)
        assertEquals(ProposalCardLine.ClientCounter(9_000_000, null), Design07Rules.cardLine(noHistory, now))
        assertEquals(ProposalCardLine.ClientCounter(9_000_000, 10_000_000), Design07Rules.cardLine(noHistory, now, mine = 10_000_000))
        val mine3 = S08.version(id = "v3", author = ActorSide.DRIVER, revision = 3, total = 10_000_000, expires = later)
        assertEquals(ProposalCardLine.MyCounter(10_000_000), Design07Rules.cardLine(S08.thread(mine3), now))
        assertEquals(ProposalCardLine.Waiting, Design07Rules.cardLine(S08.thread(S08.version(expires = later)), now))
        assertEquals(ProposalCardLine.Accepted, Design07Rules.cardLine(S08.thread(S08.version(), state = "accepted", bookingId = "bkg_1"), now))
        assertEquals(ProposalCardLine.Closed("proposalStatus.rejected"), Design07Rules.cardLine(S08.thread(S08.version(status = ProposalStatus.REJECTED), state = "closed"), now))
    }

    @Test
    fun `previous driver total is the latest driver version before the current one`() {
        val v1 = S08.version(id = "v1", author = ActorSide.DRIVER, revision = 1, total = 12_000_000)
        val v2 = S08.version(id = "v2", author = ActorSide.CLIENT, revision = 2, total = 9_000_000)
        val v3 = S08.version(id = "v3", author = ActorSide.DRIVER, revision = 3, total = 11_000_000)
        val v4 = S08.version(id = "v4", author = ActorSide.CLIENT, revision = 4, total = 10_000_000)
        assertEquals(11_000_000L, Design07Rules.previousDriverTotal(S08.thread(v4, versions = listOf(v1, v2, v3, v4))))
        assertNull(Design07Rules.previousDriverTotal(S08.thread(v4)))
    }

    @Test
    fun `pill counts only open threads where the client countered`() {
        val countered = S08.thread(S08.version(author = ActorSide.CLIENT, revision = 2, expires = later))
        val waiting = S08.thread(S08.version(expires = later))
        val expiredCounter = S08.thread(S08.version(author = ActorSide.CLIENT, revision = 2, expires = "2026-10-01T05:00:00Z"))
        assertEquals(1, Design07Rules.counteredCount(listOf(countered, waiting, expiredCounter), now))
    }

    // -- counter (§8.5) ---------------------------------------------------------------------------------------

    @Test
    fun `counter price must be given and differ from the client's`() {
        assertEquals(CounterIssue.EMPTY, Design07Rules.counterIssue("", 9_000_000))
        assertEquals(CounterIssue.EMPTY, Design07Rules.counterIssue("0", 9_000_000))
        // 90 000 so'm = 9 000 000 minor: the same price would only burn a revision.
        assertEquals(CounterIssue.SAME_AS_CLIENT, Design07Rules.counterIssue("90000", 9_000_000))
        assertNull(Design07Rules.counterIssue("95000", 9_000_000))
        assertNull(Design07Rules.counterIssue("95000", null))
    }

    // -- accept → booking chat (§8.7, Q100) -------------------------------------------------------------------

    @Test
    fun `accept opens the booking chat when the booking is named, else stays`() {
        assertEquals(AcceptNav.BookingChat("bkg_7"), Design07Rules.afterAccept("bkg_7"))
        assertEquals(AcceptNav.Stay, Design07Rules.afterAccept(null))
        assertEquals(AcceptNav.Stay, Design07Rules.afterAccept(" "))
    }

    // -- saved routes (§6.2, §6.3, §6.5) ----------------------------------------------------------------------

    private fun saved(id: String, originRegion: String? = null, originDistrict: String? = null, destRegion: String? = null, destDistrict: String? = null, service: ServiceType = ServiceType.PARCEL) = SavedSearchDTO(
        createdAt = "2026-10-01T06:00:00Z", id = id, notify = true, quantity = 1, serviceType = service, side = FeedSide.REQUESTS,
        originRegionId = originRegion, originDistrictId = originDistrict,
        destinationRegionId = destRegion, destinationDistrictId = destDistrict,
        timeWindowEnd = "2026-10-15T06:00:00Z", timeWindowStart = "2026-10-01T06:00:00Z",
    )

    private val query = FeedQuery(ServiceType.PARCEL, "a", "b", EndIds("reg_tash", null), EndIds(null, "dst_sam"))

    @Test
    fun `already saved compares the ends and the service`() {
        assertTrue(Design07Rules.alreadySaved(listOf(saved("1", originRegion = "reg_tash", destDistrict = "dst_sam")), query))
        // The server may also fill the district's region: still the same route.
        assertTrue(Design07Rules.alreadySaved(listOf(saved("1", originRegion = "reg_tash", destRegion = "reg_sam", destDistrict = "dst_sam")), query))
        assertFalse(Design07Rules.alreadySaved(listOf(saved("1", originRegion = "reg_tash", destDistrict = "dst_sam", service = ServiceType.PASSENGER)), query))
        assertFalse(Design07Rules.alreadySaved(listOf(saved("1", originDistrict = "dst_chil", destDistrict = "dst_sam")), query))
        assertFalse(Design07Rules.alreadySaved(listOf(saved("1", originRegion = "reg_tash", destDistrict = "dst_sam")), null))
    }

    @Test
    fun `limit is ten`() {
        assertFalse(Design07Rules.atLimit(List(9) { saved("$it") }))
        assertTrue(Design07Rules.atLimit(List(10) { saved("$it") }))
    }

    @Test
    fun `open in feed rebuilds the ends from the catalogue`() {
        val regions = listOf(
            RegionDTO(code = "TK", id = "reg_tash", nameUz = "Toshkent shahri", nameRu = "Ташкент", requiresDistrict = false),
            RegionDTO(code = "SA", id = "reg_sam", nameUz = "Samarqand viloyati", requiresDistrict = true),
        )
        val districts = mapOf("dst_sam" to DistrictDTO(id = "dst_sam", nameUz = "Samarqand", nameRu = "Самарканд", region = RegionRefDTO("SA", "reg_sam", "Samarqand viloyati")))
        val f = Design07Rules.filterFor(saved("1", originRegion = "reg_tash", destDistrict = "dst_sam"), FeedFilter(days = FeedDays.THREE), regions, districts)!!
        assertEquals(FeedEnd(regionId = "reg_tash", regionName = "Toshkent shahri", regionNameRu = "Ташкент", requiresDistrict = false), f.origin)
        assertEquals("reg_sam", f.destination.regionId)
        assertEquals("dst_sam", f.destination.districtId)
        assertEquals("Самарканд", f.destination.districtNameRu)
        assertEquals(FeedDays.THREE, f.days)
        assertEquals(query.copy(dateFrom = "", dateTo = "").origin, FeedRules.endIds(f.origin))
        // An end with neither region nor district cannot be opened.
        assertNull(Design07Rules.filterFor(saved("2", destDistrict = "dst_sam"), FeedFilter(), regions, districts))
        assertNull(Design07Rules.filterFor(saved("3", originRegion = "reg_tash", destDistrict = "dst_unknown"), FeedFilter(), regions, districts))
    }

    // -- add trip (§3.4) --------------------------------------------------------------------------------------

    @Test
    fun `departure errors use the one pair of keys`() {
        assertEquals("driver.trip.departureRequired", Design07Rules.departureErrorKey(setOf(TripFormIssue.DEPARTURE, TripFormIssue.SEATS)))
        assertEquals("driver.trip.departurePast", Design07Rules.departureErrorKey(setOf(TripFormIssue.DEPARTURE_PAST)))
        assertNull(Design07Rules.departureErrorKey(setOf(TripFormIssue.SEATS)))
        val past = TripRules.issues(TripForm(departure = java.time.LocalDateTime.of(2026, 10, 1, 9, 0)), null, null, Instant.parse("2026-10-01T06:00:00Z"))
        assertEquals("driver.trip.departurePast", Design07Rules.departureErrorKey(past))
        assertEquals("driver.trip.departureRequired", Design07Rules.departureErrorKey(TripRules.issues(TripForm(), null, null, now)))
    }

    // -- trips ------------------------------------------------------------------------------------------------

    @Test
    fun `depart and cancel banners say what happened, one live trip at a time`() {
        assertEquals("driver.trip.departed", Design07Rules.commandBannerKey(TripCommand.DEPART))
        assertEquals("driver.trip.cancelled", Design07Rules.commandBannerKey(TripCommand.CANCEL))
        assertEquals("driverRoutes.tripStatusUpdated", Design07Rules.commandBannerKey(TripCommand.START_BOARDING))
        val live = S08.trip("live", TripStatus.BOARDING)
        val next = S08.trip("next", TripStatus.PLANNED)
        assertTrue(Design07Rules.blocksStart(listOf(live, next), next, TripCommand.START_BOARDING))
        assertFalse(Design07Rules.blocksStart(listOf(next), next, TripCommand.START_BOARDING))
        assertFalse(Design07Rules.blocksStart(listOf(live, next), live, TripCommand.DEPART))
    }

    @Test
    fun `stops ladder follows the trip status`() {
        assertEquals(List(3) { LadderState.TODO }, Design07Rules.ladder(TripStatus.PLANNED, 3))
        assertEquals(listOf(LadderState.CURRENT, LadderState.TODO, LadderState.TODO), Design07Rules.ladder(TripStatus.BOARDING, 3))
        assertEquals(listOf(LadderState.DONE, LadderState.CURRENT, LadderState.TODO), Design07Rules.ladder(TripStatus.IN_PROGRESS, 3))
        assertEquals(List(3) { LadderState.DONE }, Design07Rules.ladder(TripStatus.COMPLETED, 3))
    }

    @Test
    fun `phone note follows Q142 - parcel at departure, passenger on board`() {
        assertEquals("driver.trip.phoneAfterDepart", Design07Rules.phoneNoteKey(ServiceType.PARCEL))
        assertEquals("driver.trip.phoneAfterBoard", Design07Rules.phoneNoteKey(ServiceType.PASSENGER))
    }

    // -- home stats (§1.2) ------------------------------------------------------------------------------------

    @Test
    fun `home stats count live trips, open threads and live bookings, dash when unknown`() {
        val trips = listOf(
            S08.trip("a", TripStatus.PLANNED), S08.trip("b", TripStatus.IN_PROGRESS), S08.trip("c", TripStatus.INTERRUPTED),
            S08.trip("d", TripStatus.COMPLETED), S08.trip("e", TripStatus.CANCELLED),
        )
        val open = listOf(
            S08.thread(S08.version(expires = later)),
            S08.thread(S08.version(author = ActorSide.CLIENT, revision = 2, expires = later)),
        )
        val stats = Design07Rules.homeStats(Load.Ready(trips), Load.Ready(open), Load.Ready(listOf("awaiting_pickup", "completed", "in_transit", "cancelled")))
        assertEquals(HomeStats(trips = 3, offers = 2, bookings = 2), stats)
        val unknown = Design07Rules.homeStats(Load.Loading, null, Load.Failed(RuntimeException("x")))
        assertEquals(HomeStats(null, null, null), unknown)
    }
}
