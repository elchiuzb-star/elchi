package uz.elchi.app.feature.driver

import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.generated.DirectionEndDTO
import uz.elchi.app.api.generated.DirectionOfferDTO
import uz.elchi.app.api.generated.DirectionRequestItemDTO
import uz.elchi.app.api.generated.DirectionTripRefDTO
import uz.elchi.app.api.generated.DistrictDTO
import uz.elchi.app.api.generated.DriverDirectionDTO
import uz.elchi.app.api.generated.MatchType
import uz.elchi.app.api.generated.PointEndDTO
import uz.elchi.app.api.generated.RegionDTO
import uz.elchi.app.api.generated.RegionRefDTO
import uz.elchi.app.api.generated.TripStatus
import uz.elchi.app.api.generated.DistrictRefDTO
import java.time.Instant

/** ADR-0027: the direction screens' rules - a port of the web `directionFeed.test.ts` plus the native form and offer. */
class DirectionRulesTest {
    private fun item(id: String, fit: String, eta: String? = null) = DirectionRequestItemDTO(
        fit = fit, listing = S08.listing(id = id), matchType = MatchType.EXACT, pickupEta = eta,
    )

    private fun error(status: Int, code: String, vararg details: Pair<String, Any>) = ApiException(
        status, code, "x",
        buildJsonObject {
            details.forEach { (k, v) ->
                when (v) {
                    is String -> put(k, v)
                    is Boolean -> put(k, v)
                    is Number -> put(k, JsonPrimitive(v))
                }
            }
        },
    )

    private fun direction(id: String, status: String) = DriverDirectionDTO(
        cargoCapacityVolumeMl = 400_000, cargoCapacityWeightG = 80_400, createdAt = "2026-10-06T06:00:00Z",
        destination = end("reg_sam", "Samarqand viloyati", "dst_toy", "Toyloq"), id = id,
        origin = end("reg_tash", "Toshkent shahri"), seatCapacity = 4, status = status, updatedAt = "2026-10-06T06:00:00Z",
        vehicleId = "veh_1", version = 1,
    )

    private fun end(regionId: String, region: String, districtId: String? = null, district: String? = null, districtRu: String? = null) =
        DirectionEndDTO(regionId = regionId, regionNameUz = region, regionNameRu = "г. $region", districtId = districtId, districtNameUz = district, districtNameRu = districtRu)

    private val tashkent = RegionDTO(code = "TK", id = "reg_tash", nameUz = "Toshkent shahri", requiresDistrict = false)
    private val samarqand = RegionDTO(code = "SA", id = "reg_sam", nameUz = "Samarqand viloyati", requiresDistrict = true)
    private fun district(id: String, name: String, ru: String? = null) = DistrictDTO(id = id, nameUz = name, nameRu = ru, region = RegionRefDTO("SA", "reg_sam", "Samarqand viloyati"))

    // -- the feed -----------------------------------------------------------------------------------------------

    @Test
    fun `cuts the page into the three answers and keeps the server's order inside each`() {
        val groups = DirectionRules.group(listOf(item("a", "no_trip"), item("b", "fits_trip"), item("c", "time_differs"), item("d", "fits_trip")))
        assertEquals(listOf("b", "d"), groups.fits.map { it.listing.id })
        assertEquals(listOf("a"), groups.fresh.map { it.listing.id })
        assertEquals(listOf("c"), groups.otherTime.map { it.listing.id })
        // An unknown fit (a future value, or "passed") is never drawn in a group.
        assertTrue(DirectionRules.group(listOf(item("e", "passed"))).let { it.fits.isEmpty() && it.fresh.isEmpty() && it.otherTime.isEmpty() })
    }

    private val now: Instant = Instant.parse("2026-10-06T08:30:00Z") // 13:30 in Tashkent

    @Test
    fun `today runs from now to Tashkent midnight`() {
        val (from, to) = DirectionRules.range(DirectionDay.TODAY, now)
        assertEquals(Instant.parse("2026-10-06T08:30:00Z"), java.time.OffsetDateTime.parse(from).toInstant())
        assertEquals(Instant.parse("2026-10-06T19:00:00Z"), java.time.OffsetDateTime.parse(to).toInstant())
    }

    @Test
    fun `tomorrow is the whole next Tashkent day and 3 or 14 days run from now`() {
        val (from, to) = DirectionRules.range(DirectionDay.TOMORROW, now)
        assertEquals(Instant.parse("2026-10-06T19:00:00Z"), java.time.OffsetDateTime.parse(from).toInstant())
        assertEquals(Instant.parse("2026-10-07T19:00:00Z"), java.time.OffsetDateTime.parse(to).toInstant())
        assertEquals(Instant.parse("2026-10-09T08:30:00Z"), java.time.OffsetDateTime.parse(DirectionRules.range(DirectionDay.DAYS3, now).second).toInstant())
        assertEquals(Instant.parse("2026-10-20T08:30:00Z"), java.time.OffsetDateTime.parse(DirectionRules.range(DirectionDay.DAYS14, now).second).toInstant())
        // Safar v3 5.3: the four chips in the design's order.
        assertEquals(listOf(DirectionDay.TODAY, DirectionDay.TOMORROW, DirectionDay.DAYS3, DirectionDay.DAYS14), DirectionDay.entries)
        // Sent with the Tashkent offset, like the corridor feed's range.
        assertTrue(from.endsWith("+05:00"))
    }

    @Test
    fun `shows Tashkent wall time`() {
        assertEquals("22:04", DirectionRules.clock("2026-10-06T17:04:13Z"))
        assertEquals("-", DirectionRules.clock(null))
        assertEquals("07.10, 00:30", DirectionRules.dayClock("2026-10-06T19:30:00Z")) // past midnight: the next day
    }

    @Test
    fun `names the district, or the region of a city without districts`() {
        assertEquals("Toshkent shahri", DirectionRules.endName(end("reg_tash", "Toshkent shahri"), ru = false))
        assertEquals("Карши", DirectionRules.endName(end("reg_qa", "Qashqadaryo", "dst_q", "Qarshi", "Карши"), ru = true))
        assertEquals("Toshkent shahri → Toyloq", DirectionRules.title(direction("drd_1", "active"), ru = false))
        assertEquals(80L, DirectionRules.kg(80_400))
    }

    @Test
    fun `a card names places by address or district, never by a stop (ADR-0028)`() {
        assertEquals("Xaritadagi joy", DirectionRules.place(null, "Xaritadagi joy"))
        val point = PointEndDTO(address = "Toshkent, Amir Temur 2", district = DistrictRefDTO("dst_t", "Yunusobod"), lat = 41.3, lng = 69.2)
        assertEquals("Toshkent, Amir Temur 2", DirectionRules.place(point, "?"))
        assertEquals("Yunusobod", DirectionRules.place(point.copy(address = " "), "?"))
        assertEquals("?", DirectionRules.place(point.copy(address = null, district = null), "?"))
    }

    @Test
    fun `the feed opens on the chosen direction while it is live, else the first active one`() {
        val list = listOf(direction("a", "paused"), direction("b", "active"), direction("c", "archived"))
        assertEquals("a", DirectionRules.pickDirection(list, "a"))
        assertEquals("b", DirectionRules.pickDirection(list, "c"))
        assertEquals("b", DirectionRules.pickDirection(list, null))
        assertEquals("a", DirectionRules.pickDirection(listOf(direction("a", "paused")), null))
        assertNull(DirectionRules.pickDirection(emptyList(), "x"))
        assertEquals(listOf("a", "b"), DirectionRules.live(list).map { it.id })
        assertEquals("paused", DirectionRules.toggledStatus(direction("b", "active")))
        assertEquals("active", DirectionRules.toggledStatus(direction("a", "paused")))
    }

    // -- the add form -------------------------------------------------------------------------------------------

    @Test
    fun `the form needs both regions and a district where the region asks for one`() {
        assertEquals(
            setOf(DirectionFormIssue.ORIGIN_REGION, DirectionFormIssue.DESTINATION_REGION),
            DirectionRules.issues(DirectionForm()),
        )
        // Tashkent city is whole; Samarqand viloyati needs a district.
        val partial = DirectionForm(originRegion = tashkent, destinationRegion = samarqand)
        assertEquals(setOf(DirectionFormIssue.DESTINATION_DISTRICT), DirectionRules.issues(partial))
        assertNull(DirectionRules.createBody(partial, emptyList()))
        val ready = partial.copy(destinationDistrict = district("dst_toy", "Toyloq"))
        assertTrue(DirectionRules.issues(ready).isEmpty())
    }

    @Test
    fun `the body is two ends only - the car only when there is more than one approved`() {
        val form = DirectionForm(originRegion = tashkent, destinationRegion = samarqand, destinationDistrict = district("dst_toy", "Toyloq"))
        val one = DirectionRules.createBody(form, listOf(S08.vehicle(), S08.vehicle(status = "pending", id = "veh_2")))!!
        assertEquals("reg_tash", one.origin.regionId)
        assertNull(one.origin.districtId)
        assertEquals("reg_sam", one.destination.regionId)
        assertEquals("dst_toy", one.destination.districtId)
        assertNull(one.vehicleId)
        assertNull(one.seatCapacity)
        val two = DirectionRules.createBody(form, listOf(S08.vehicle(id = "veh_1"), S08.vehicle(id = "veh_2")))!!
        assertEquals("veh_1", two.vehicleId)
    }

    @Test
    fun `the district search matches either language`() {
        val list = listOf(district("d1", "Toyloq", "Тайлак"), district("d2", "Urgut", "Ургут"))
        assertEquals(listOf("d1"), DirectionRules.searchDistricts(list, "toy").map { it.id })
        assertEquals(listOf("d2"), DirectionRules.searchDistricts(list, "ургут").map { it.id })
        assertEquals(2, DirectionRules.searchDistricts(list, "  ").size)
    }

    @Test
    fun `tells no-road, duplicate and passed-pickup apart`() {
        assertTrue(DirectionRules.isNoRoad(error(409, "ROUTE_MISMATCH")))
        assertEquals(DirectionNotice.NO_ROAD, DirectionRules.notice(error(409, "ROUTE_MISMATCH")))
        assertTrue(DirectionRules.isDuplicate(error(400, "VALIDATION_ERROR", "reason" to "direction_exists")))
        assertFalse(DirectionRules.isDuplicate(error(400, "VALIDATION_ERROR", "reason" to "district_required")))
        assertEquals(DirectionNotice.EXISTS, DirectionRules.notice(error(400, "VALIDATION_ERROR", "reason" to "direction_exists")))
        assertNull(DirectionRules.notice(error(400, "VALIDATION_ERROR", "reason" to "district_required")))
        assertTrue(DirectionRules.isPickupPassed(error(409, "BOOKING_CUTOFF_PASSED", "reason" to "pickup_passed")))
        assertFalse(DirectionRules.isPickupPassed(error(409, "BOOKING_CUTOFF_PASSED")))
    }

    // -- the offer ----------------------------------------------------------------------------------------------

    @Test
    fun `reads the car's ETA from a time conflict, unless no proposal can work (Q157)`() {
        val conflict = error(409, "TIME_WINDOW_CONFLICT", "reason" to "trip_time_differs", "eta" to "2026-10-06T17:04:13+00:00")
        assertEquals("2026-10-06T17:04:13+00:00", DirectionRules.timeProposalEta(conflict))
        assertNull(DirectionRules.timeProposalEta(error(409, "ROUTE_MISMATCH")))
        val far = error(409, "TIME_WINDOW_CONFLICT", "eta" to "2026-10-06T18:43:13+00:00", "time_proposal_possible" to false)
        assertNull(DirectionRules.timeProposalEta(far))
        assertEquals(3L to 12L, DirectionRules.timeProposalTooFar(far))
        val tooFar = error(409, "TIME_WINDOW_CONFLICT", "reason" to "time_proposal_too_far", "max_early_minutes" to 120, "max_late_minutes" to 600)
        assertEquals(2L to 10L, DirectionRules.timeProposalTooFar(tooFar))
        assertNull(DirectionRules.timeProposalTooFar(conflict))
    }

    @Test
    fun `an offer's outcome - created, retimed, plain, propose the ETA, too far, passed, existing`() {
        fun dto(created: Boolean, retimed: Boolean) = DirectionOfferDTO(
            thread = S08.thread(S08.version()), timeProposal = false, tripCreated = created, tripRetimed = retimed,
            trip = DirectionTripRefDTO(id = "trp_9", plannedEndAt = "2026-10-07T06:00:00Z", plannedStartAt = "2026-10-07T01:20:00Z", seatsBooked = 0, status = TripStatus.PLANNED),
        )
        assertEquals(DirectionOfferOutcome.Sent("prt_1", "dir.bid.tripCreated", "07.10, 06:20"), DirectionRules.sent(dto(created = true, retimed = false)))
        assertEquals("dir.bid.tripRetimed", DirectionRules.sent(dto(created = false, retimed = true)).key)
        assertEquals(DirectionOfferOutcome.Sent("prt_1", "driverBid.sent", null), DirectionRules.sent(dto(created = false, retimed = false)))

        val conflict = error(409, "TIME_WINDOW_CONFLICT", "eta" to "2026-10-06T17:04:13+00:00")
        assertEquals(DirectionOfferOutcome.ProposeTime("2026-10-06T17:04:13+00:00"), DirectionRules.failed(conflict, pickupAt = null))
        // Already a time proposal and still refused: not another proposal loop - the generic sentence.
        assertTrue(DirectionRules.failed(conflict, pickupAt = "2026-10-06T17:04:13+00:00") is DirectionOfferOutcome.Failed)
        assertEquals(DirectionOfferOutcome.TooFar(3, 12), DirectionRules.failed(error(409, "TIME_WINDOW_CONFLICT", "time_proposal_possible" to false), null))
        assertEquals(DirectionOfferOutcome.Passed, DirectionRules.failed(error(409, "BOOKING_CUTOFF_PASSED", "reason" to "pickup_passed"), null))
        assertEquals(
            DirectionOfferOutcome.Existing("prt_7"),
            DirectionRules.failed(error(409, "INVALID_STATE_TRANSITION", "reason" to "open_thread_exists", "thread_id" to "prt_7"), null),
        )
        assertTrue(DirectionRules.failed(error(409, "ROUTE_CHANGED"), null) is DirectionOfferOutcome.Failed)
    }

    @Test
    fun `a time proposal resends the same request with pickup_at = the ETA, under its own idempotency key`() {
        val fits = item("l1", "fits_trip", eta = "2026-10-06T05:00:00Z")
        val other = item("l2", "time_differs", eta = "2026-10-06T17:04:13Z")
        // A request the trip reaches on time: no pickup_at, until a conflict hands one back.
        assertNull(DirectionRules.proposeAt(fits, null))
        assertEquals("2026-10-06T17:04:13+00:00", DirectionRules.proposeAt(fits, "2026-10-06T17:04:13+00:00"))
        // "Vaqti boshqa": the offer is a time proposal at the car's ETA from the start.
        assertEquals("2026-10-06T17:04:13Z", DirectionRules.proposeAt(other, null))

        val first = DirectionRules.offerBody("l1", 12_000_000, null, message = "  ")
        assertEquals("l1", first.listingId)
        assertEquals(12_000_000L, first.unitPriceMinor)
        assertNull(first.pickupAt)
        assertNull(first.message)
        val again = DirectionRules.offerBody("l1", 12_000_000, "2026-10-06T17:04:13+00:00")
        assertEquals("2026-10-06T17:04:13+00:00", again.pickupAt)
        // A retry of the same body keeps its key (same scope); the time proposal is a different request.
        assertEquals(DirectionRules.offerScope("drd_1", "l1", 12_000_000, null), DirectionRules.offerScope("drd_1", "l1", 12_000_000, null))
        assertFalse(DirectionRules.offerScope("drd_1", "l1", 12_000_000, null) == DirectionRules.offerScope("drd_1", "l1", 12_000_000, again.pickupAt))
    }

    @Test
    fun `the main list is one flat list and another time stays apart`() {
        val items = listOf(item("a", DirectionRules.NO_TRIP), item("b", DirectionRules.TIME_DIFFERS), item("c", DirectionRules.FITS_TRIP))
        val (main, other) = DirectionRules.mainAndOtherTime(items)
        assertEquals(listOf("c", "a"), main.map { it.listing.id })
        assertEquals(listOf("b"), other.map { it.listing.id })
        assertEquals(2, DirectionRules.mainCount(items))
    }

    @Test
    fun `status toasts and the active count for the Moslar segment`() {
        assertEquals("dir.paused", DirectionRules.statusToastKey(DirectionRules.PAUSED))
        assertEquals("dir.updated", DirectionRules.statusToastKey(DirectionRules.ACTIVE))
        assertEquals("dir.archived", DirectionRules.statusToastKey(DirectionRules.ARCHIVED))
        assertEquals(1, DirectionRules.activeCount(listOf(direction("a", DirectionRules.ACTIVE), direction("b", DirectionRules.PAUSED))))
        assertEquals(listOf("a"), HomeListingRules.activeDirections(listOf(direction("a", DirectionRules.ACTIVE), direction("b", DirectionRules.PAUSED))).map { it.id })
    }
}
