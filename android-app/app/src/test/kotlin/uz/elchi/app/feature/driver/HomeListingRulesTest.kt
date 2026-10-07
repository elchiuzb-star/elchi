package uz.elchi.app.feature.driver

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.api.generated.Currency
import uz.elchi.app.api.generated.DirectionRequestItemDTO
import uz.elchi.app.api.generated.DirectionRequestsDTO
import uz.elchi.app.api.generated.MatchType
import uz.elchi.app.api.generated.PriceBasis
import uz.elchi.app.api.generated.PromoBucketDTO
import uz.elchi.app.api.generated.PromoInstrument
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.ui.theme.Tone
import java.time.Instant

/** Royxat v3 §1 / Safar v3 §1: the new home's "Mijozlar e'lonlari" rules. */
class HomeListingRulesTest {
    // 2026-10-02 09:00 Tashkent.
    private val now = Instant.parse("2026-10-02T04:00:00Z")

    private fun item(
        id: String,
        fit: String = DirectionRules.FITS_TRIP,
        type: MatchType = MatchType.EXACT,
        start: String = "2026-10-02T06:00:00Z",
        end: String = "2026-10-02T10:00:00Z",
        price: Long = 12_000_000,
        service: ServiceType = ServiceType.PARCEL,
        basis: PriceBasis = PriceBasis.TOTAL,
        quantity: Long = 1,
    ) = DirectionRequestItemDTO(
        fit = fit,
        listing = S08.listing(id = id, windowStart = start, windowEnd = end, unitMinor = price, service = service, basis = basis, quantity = quantity),
        matchType = type,
    )

    private fun page(direction: String, vararg items: DirectionRequestItemDTO) = DirectionRequestsDTO(directionId = direction, items = items.toList())

    private fun home(vararg items: DirectionRequestItemDTO) = items.map { HomeListing("dir_1", it) }

    @Test
    fun mergeKeepsOneCardPerListingAndTheBetterAnswer() {
        val merged = HomeListingRules.merge(
            listOf(
                page("dir_a", item("l1", fit = DirectionRules.NO_TRIP), item("l2", type = MatchType.ON_ROUTE)),
                page("dir_b", item("l1", fit = DirectionRules.FITS_TRIP), item("l2", type = MatchType.EXACT), item("l3")),
            ),
        )
        assertEquals(listOf("l1", "l2", "l3"), merged.map { it.listing.id })
        // The better answer wins, and the offer then goes from the direction that gave it.
        assertEquals("dir_b", merged[0].directionId)
        assertEquals(DirectionRules.FITS_TRIP, merged[0].item.fit)
        assertEquals("dir_b", merged[1].directionId)
        assertEquals(MatchType.EXACT, merged[1].item.matchType)
    }

    @Test
    fun mergeKeepsTheFirstDirectionOnATie() {
        val merged = HomeListingRules.merge(listOf(page("dir_a", item("l1")), page("dir_b", item("l1"))))
        assertEquals("dir_a", merged.single().directionId)
    }

    @Test
    fun chipsHidePassengerWhileTheServiceIsOff() {
        assertEquals(listOf(HomeChip.ALL, HomeChip.PARCEL, HomeChip.TODAY), HomeListingRules.chips(passengerEnabled = false))
        assertEquals(HomeChip.entries, HomeListingRules.chips(passengerEnabled = true))
    }

    @Test
    fun chipFiltersByServiceAndToday() {
        val parcel = item("p")
        val passenger = item("x", service = ServiceType.PASSENGER, basis = PriceBasis.PER_SEAT, quantity = 2)
        val tomorrow = item("t", start = "2026-10-03T05:00:00Z", end = "2026-10-03T08:00:00Z")
        val list = home(parcel, passenger, tomorrow)
        fun ids(chip: HomeChip) = HomeListingRules.apply(list, chip, HomeFilter(), "", now).map { it.listing.id }
        assertEquals(listOf("p", "x", "t"), ids(HomeChip.ALL))
        assertEquals(listOf("p", "t"), ids(HomeChip.PARCEL))
        assertEquals(listOf("x"), ids(HomeChip.PASSENGER))
        assertEquals(listOf("p", "x"), ids(HomeChip.TODAY))
    }

    @Test
    fun periodSpansInTashkentDays() {
        // A window that started and is still open counts for today; tomorrow is the whole next Tashkent day.
        val open = item("open", start = "2026-10-02T02:00:00Z", end = "2026-10-02T05:00:00Z")
        val tomorrowNight = item("late", start = "2026-10-03T18:00:00Z", end = "2026-10-03T18:30:00Z") // 23:00 Tashkent
        val inFive = item("five", start = "2026-10-07T05:00:00Z", end = "2026-10-07T07:00:00Z")
        val list = home(open, tomorrowNight, inFive)
        fun ids(p: HomePeriod) = HomeListingRules.apply(list, HomeChip.ALL, HomeFilter(period = p), "", now).map { it.listing.id }
        assertEquals(listOf("open"), ids(HomePeriod.TODAY))
        assertEquals(listOf("late"), ids(HomePeriod.TOMORROW))
        assertEquals(listOf("open", "late"), ids(HomePeriod.DAYS3))
        assertEquals(listOf("open", "late", "five"), ids(HomePeriod.DAYS14))
    }

    @Test
    fun sortMinimumPriceAndExactOnly() {
        val a = item("a", price = 9_000_000, start = "2026-10-02T08:00:00Z", end = "2026-10-02T09:00:00Z")
        val b = item("b", price = 16_000_000, type = MatchType.ON_ROUTE, start = "2026-10-02T05:00:00Z", end = "2026-10-02T09:00:00Z")
        val c = item("c", price = 12_000_000, start = "2026-10-02T06:00:00Z", end = "2026-10-02T09:00:00Z")
        val list = home(a, b, c)
        fun ids(f: HomeFilter) = HomeListingRules.apply(list, HomeChip.ALL, f, "", now).map { it.listing.id }
        assertEquals(listOf("b", "c", "a"), ids(HomeFilter()))
        assertEquals(listOf("a", "c", "b"), ids(HomeFilter(sort = HomeSort.CHEAP)))
        assertEquals(listOf("b", "c", "a"), ids(HomeFilter(sort = HomeSort.EXPENSIVE)))
        assertEquals(listOf("b", "c"), ids(HomeFilter(minPrice = HomeMinPrice.FROM_100K)))
        assertEquals(listOf("b"), ids(HomeFilter(minPrice = HomeMinPrice.FROM_150K)))
        assertEquals(listOf("c", "a"), ids(HomeFilter(exactOnly = true)))
    }

    @Test
    fun filterCountsOnlyWhatDiffersFromTheDefault() {
        assertEquals(0, HomeFilter().count)
        assertEquals(4, HomeFilter(HomePeriod.TODAY, HomeSort.CHEAP, HomeMinPrice.FROM_100K, exactOnly = true).count)
        assertEquals("driver.v3reg.emptyCategory", HomeListingRules.emptyKey(HomeFilter(), " "))
        assertEquals("driver.v3reg.emptyFiltered", HomeListingRules.emptyKey(HomeFilter(), "sam"))
        assertEquals("driver.v3reg.emptyFiltered", HomeListingRules.emptyKey(HomeFilter(exactOnly = true), ""))
    }

    @Test
    fun searchLooksThroughPlacesCaseInsensitivelyWordByWord() {
        val l = item("l").listing // Toshkent, Amir Temur 2 -> Samarqand, Amir Temur 18
        assertTrue(HomeListingRules.matches(l, ""))
        assertTrue(HomeListingRules.matches(l, "SAMARQAND"))
        assertTrue(HomeListingRules.matches(l, "toshkent samar"))
        assertFalse(HomeListingRules.matches(l, "buxoro"))
        assertFalse(HomeListingRules.matches(l, "toshkent buxoro"))
    }

    @Test
    fun cardPriceUnitAndTag() {
        val seats = item("s", service = ServiceType.PASSENGER, basis = PriceBasis.PER_SEAT, quantity = 2, price = 15_000_000)
        assertEquals(15_000_000L, HomeListingRules.shownPrice(seats.listing))
        assertEquals("driver.v3reg.perPerson", HomeListingRules.unitKey(seats.listing))
        val parcel = item("p", price = 12_000_000)
        assertEquals(12_000_000L, HomeListingRules.shownPrice(parcel.listing))
        assertEquals("common.total", HomeListingRules.unitKey(parcel.listing))
        assertEquals("match.exact", HomeListingRules.tagKey(parcel))
        assertEquals(Tone.OK, HomeListingRules.tagTone(parcel))
        assertEquals("match.on_route", HomeListingRules.tagKey(item("r", type = MatchType.ON_ROUTE)))
        assertEquals("match.reason.time_differs", HomeListingRules.tagKey(item("t", fit = DirectionRules.TIME_DIFFERS)))
        assertEquals(Tone.WARN, HomeListingRules.tagTone(item("t", fit = DirectionRules.TIME_DIFFERS)))
    }

    @Test
    fun firstNameAndSeal() {
        assertEquals("Jasur", HomeListingRules.firstName("  Jasur  Toshmatov "))
        assertNull(HomeListingRules.firstName("   "))
        assertNull(HomeListingRules.firstName(null))
        assertEquals(SealTone.OK, HomeListingRules.seal(VerifyState.APPROVED))
        assertEquals(SealTone.WARN, HomeListingRules.seal(VerifyState.INCOMPLETE))
        assertEquals(SealTone.WARN, HomeListingRules.seal(VerifyState.REVIEW))
        assertEquals(SealTone.ERR, HomeListingRules.seal(VerifyState.REJECTED))
        assertEquals(SealTone.ERR, HomeListingRules.seal(VerifyState.BLOCKED))
        assertEquals("driver.v3reg.badgeApproved", HomeListingRules.sealToastKey(VerifyState.APPROVED))
        assertEquals("driver.v3reg.badgePending", HomeListingRules.sealToastKey(VerifyState.REVIEW))
        // A decision is not "waiting": the derived word, not "kutilmoqda".
        assertEquals(VerifyState.REJECTED.labelKey, HomeListingRules.sealToastKey(VerifyState.REJECTED))
        assertEquals("driver.v3reg.badgeUnverified", HomeListingRules.sealLabelKey(VerifyState.INCOMPLETE))
    }

    @Test
    fun creditCountsOnlyTheDriversUsableCredit() {
        fun bucket(instrument: PromoInstrument, available: Long, service: ServiceType = ServiceType.PARCEL) = PromoBucketDTO(
            availableMinor = available, consumedMinor = 0, currency = Currency.UZS, expiredMinor = 0, instrument = instrument,
            reservedMinor = 500, reversedMinor = 0, serviceType = service, underReviewMinor = 0,
        )
        assertEquals(0L, HomeListingRules.creditMinor(emptyList()))
        assertEquals(
            300_000L,
            HomeListingRules.creditMinor(
                listOf(
                    bucket(PromoInstrument.DRIVER_CREDIT, 200_000),
                    bucket(PromoInstrument.DRIVER_CREDIT, 100_000, ServiceType.PASSENGER),
                    bucket(PromoInstrument.PASSENGER_BONUS, 900_000),
                ),
            ),
        )
    }
}
