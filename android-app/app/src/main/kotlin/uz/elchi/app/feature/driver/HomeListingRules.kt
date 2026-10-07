package uz.elchi.app.feature.driver

import uz.elchi.app.api.generated.DirectionRequestItemDTO
import uz.elchi.app.api.generated.DirectionRequestsDTO
import uz.elchi.app.api.generated.DriverDirectionDTO
import uz.elchi.app.api.generated.ListingPublicDTO
import uz.elchi.app.api.generated.MatchType
import uz.elchi.app.api.generated.PriceBasis
import uz.elchi.app.api.generated.PromoBucketDTO
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.feature.client.OrderRules
import uz.elchi.app.feature.client.ParcelRules
import uz.elchi.app.feature.client.PromoRules
import uz.elchi.app.ui.theme.Tone
import java.time.Duration
import java.time.Instant

/** Home's chips (Royxat v3 1.9 / Safar v3 1.6): "Hammasi · Pochta · Yo'lovchi · Bugun". */
enum class HomeChip(val key: String) {
    ALL("driver.v3reg.chipAll"),
    PARCEL("driverFeed.modeParcel"),
    PASSENGER("offerCreate.servicePassenger"),
    TODAY("driver.feed.dateToday"),
}

/** The filter sheet's "Muddat" (DD5 serves at most 14 days, so the widest choice is the whole read). */
enum class HomePeriod(val key: String) {
    TODAY("driver.feed.dateToday"),
    TOMORROW("driver.feed.dateTomorrow"),
    DAYS3("driver.feed.date3"),
    DAYS14("driver.feed.date14"),
}

/** The filter sheet's "Saralash": nearest window first (the default), cheapest, dearest. */
enum class HomeSort(val key: String) {
    NEAREST("driver.v3reg.sortNearest"),
    CHEAP("driver.v3reg.sortCheap"),
    EXPENSIVE("driver.v3reg.sortExpensive"),
}

/** The filter sheet's "Narx": the client's total from this amount (minor units); [ANY] = no floor. */
enum class HomeMinPrice(val minor: Long) {
    ANY(0),
    FROM_100K(100_000_00),
    FROM_150K(150_000_00),
}

/** Everything the sheet sets; the default is no filter at all. */
data class HomeFilter(
    val period: HomePeriod = HomePeriod.DAYS14,
    val sort: HomeSort = HomeSort.NEAREST,
    val minPrice: HomeMinPrice = HomeMinPrice.ANY,
    /** `match_type == exact` only (Q158: «Aniq yo'nalish»). */
    val exactOnly: Boolean = false,
) {
    /** The badge on the filter button: how many choices differ from the default. */
    val count: Int
        get() = listOf(period != HomePeriod.DAYS14, sort != HomeSort.NEAREST, minPrice != HomeMinPrice.ANY, exactOnly).count { it }
}

/** One home card: a DD5 request and the direction that found it (the offer goes from that direction, DD6). */
data class HomeListing(val directionId: String, val item: DirectionRequestItemDTO) {
    val listing: ListingPublicDTO get() = item.listing
}

/** The greeting's seal (Royxat v3 1.4): green tick, amber alert, red for a decided refusal. */
enum class SealTone(val tone: Tone) { OK(Tone.OK), WARN(Tone.WARN), ERR(Tone.ERR) }

/**
 * Royxat v3 §1 / Safar v3 §1: the rules of the new driver home - the "Mijozlar e'lonlari" list built from the driver's
 * own directions (DD5 per active direction, merged), and the search, chips and filter sheet over it. DD5 returns the
 * whole ≤ 14-day list without paging, so filtering and sorting on the client is honest. Pure, so it is unit-tested.
 */
object HomeListingRules {
    /** Cards shown on home before "Barchasi" (the full list is the Moslar tab). */
    const val SHOWN = 5

    /** The directions whose requests home reads: the active ones (a paused direction asked to see nothing). */
    fun activeDirections(list: List<DriverDirectionDTO>): List<DriverDirectionDTO> = list.filter { it.status == DirectionRules.ACTIVE }

    private fun fitRank(fit: String): Int = when (fit) {
        DirectionRules.FITS_TRIP -> 0
        DirectionRules.NO_TRIP -> 1
        else -> 2
    }

    private fun matchRank(type: MatchType): Int = if (type == MatchType.EXACT) 0 else 1

    /**
     * The pages of every direction (and service) merged into one list, one card per listing: when two directions find
     * the same request, the better answer wins (fits the trip before needs a trip before another time; exact before
     * on the way), else the first direction read.
     */
    fun merge(pages: List<DirectionRequestsDTO>): List<HomeListing> {
        val best = LinkedHashMap<String, HomeListing>()
        pages.forEach { page ->
            page.items.forEach { item ->
                val id = item.listing.id
                val kept = best[id]
                val candidate = HomeListing(page.directionId, item)
                if (kept == null || better(candidate.item, kept.item)) best[id] = candidate
            }
        }
        return best.values.toList()
    }

    private fun better(a: DirectionRequestItemDTO, b: DirectionRequestItemDTO): Boolean {
        val fa = fitRank(a.fit)
        val fb = fitRank(b.fit)
        if (fa != fb) return fa < fb
        return matchRank(a.matchType) < matchRank(b.matchType)
    }

    // -- time ---------------------------------------------------------------------------------------------------

    /** The Tashkent span a period means: today = now → midnight, tomorrow = the next day, n days = now → now + n. */
    fun span(period: HomePeriod, now: Instant): Pair<Instant, Instant> {
        val midnight = now.atZone(ParcelRules.TASHKENT).toLocalDate().atStartOfDay(ParcelRules.TASHKENT).toInstant()
        val day = Duration.ofDays(1)
        return when (period) {
            HomePeriod.TODAY -> now to midnight.plus(day)
            HomePeriod.TOMORROW -> midnight.plus(day) to midnight.plus(day.multipliedBy(2))
            HomePeriod.DAYS3 -> now to now.plus(Duration.ofDays(3))
            HomePeriod.DAYS14 -> now to now.plus(Duration.ofDays(14))
        }
    }

    /** The client's window overlaps the span (a window that started and is still open counts for today). */
    fun inSpan(listing: ListingPublicDTO, span: Pair<Instant, Instant>): Boolean {
        val start = OrderRules.parseInstant(listing.departureWindowStart) ?: return false
        val end = OrderRules.parseInstant(listing.departureWindowEnd) ?: start
        return start.isBefore(span.second) && end.isAfter(span.first)
    }

    // -- chips, search, filter ----------------------------------------------------------------------------------

    /** The chips on screen: "Yo'lovchi" only while the passenger service is on (K7/Q89). */
    fun chips(passengerEnabled: Boolean): List<HomeChip> = HomeChip.entries.filter { it != HomeChip.PASSENGER || passengerEnabled }

    fun chipAllows(chip: HomeChip, listing: ListingPublicDTO, now: Instant): Boolean = when (chip) {
        HomeChip.ALL -> true
        HomeChip.PARCEL -> listing.serviceType == ServiceType.PARCEL
        HomeChip.PASSENGER -> listing.serviceType == ServiceType.PASSENGER
        HomeChip.TODAY -> inSpan(listing, span(HomePeriod.TODAY, now))
    }

    /** What the search box looks through: both places (address and district) and the parcel category's names. */
    fun searchText(listing: ListingPublicDTO): String = listOfNotNull(
        listing.originPoint?.address,
        listing.originPoint?.district?.nameUz,
        listing.destinationPoint?.address,
        listing.destinationPoint?.district?.nameUz,
        listing.parcelCategory?.nameUz,
        listing.parcelCategory?.nameRu,
    ).joinToString(" ").lowercase()

    /** Every word of the query somewhere in the card's text (case-insensitive); a blank query matches all. */
    fun matches(listing: ListingPublicDTO, query: String): Boolean {
        val words = query.trim().lowercase().split(Regex("\\s+")).filter { it.isNotEmpty() }
        if (words.isEmpty()) return true
        val text = searchText(listing)
        return words.all { text.contains(it) }
    }

    /** The list on home after the chip, the search and the sheet, in the chosen order. */
    fun apply(list: List<HomeListing>, chip: HomeChip, filter: HomeFilter, query: String, now: Instant): List<HomeListing> {
        val span = span(filter.period, now)
        val kept = list.filter { h ->
            val l = h.listing
            chipAllows(chip, l, now) &&
                inSpan(l, span) &&
                l.totalMinor >= filter.minPrice.minor &&
                (!filter.exactOnly || h.item.matchType == MatchType.EXACT) &&
                matches(l, query)
        }
        fun start(h: HomeListing) = OrderRules.parseInstant(h.listing.departureWindowStart) ?: Instant.MAX
        return when (filter.sort) {
            HomeSort.NEAREST -> kept.sortedBy(::start)
            HomeSort.CHEAP -> kept.sortedWith(compareBy<HomeListing> { it.listing.totalMinor }.thenBy(::start))
            HomeSort.EXPENSIVE -> kept.sortedWith(compareByDescending<HomeListing> { it.listing.totalMinor }.thenBy(::start))
        }
    }

    /** The empty line: a search or a filter is on → "change the filter", else "nothing in this category yet". */
    fun emptyKey(filter: HomeFilter, query: String): String =
        if (query.isNotBlank() || filter.count > 0) "driver.v3reg.emptyFiltered" else "driver.v3reg.emptyCategory"

    // -- a card -------------------------------------------------------------------------------------------------

    /** Per seat: the seat price "kishi boshiga"; otherwise the client's total, "jami". */
    fun perPerson(listing: ListingPublicDTO): Boolean = listing.priceBasis == PriceBasis.PER_SEAT

    fun shownPrice(listing: ListingPublicDTO): Long = if (perPerson(listing)) listing.unitPriceMinor else listing.totalMinor

    fun unitKey(listing: ListingPublicDTO): String = if (perPerson(listing)) "driver.v3reg.perPerson" else "common.total"

    /** The match tag (Q158 wording; there is no "Yaqin", Q159/Q160). Another time wins: it is what the driver must see. */
    fun tagKey(item: DirectionRequestItemDTO): String = when {
        item.fit == DirectionRules.TIME_DIFFERS -> "match.reason.time_differs"
        item.matchType == MatchType.EXACT -> "match.exact"
        else -> "match.on_route"
    }

    fun tagTone(item: DirectionRequestItemDTO): Tone = when {
        item.fit == DirectionRules.TIME_DIFFERS -> Tone.WARN
        item.matchType == MatchType.EXACT -> Tone.OK
        else -> Tone.BLUE
    }

    // -- greeting, seal, credit ---------------------------------------------------------------------------------

    /** "Jasur Toshmatov" → "Jasur"; nothing usable → null ("Salom!"). */
    fun firstName(fullName: String?): String? = fullName?.trim()?.split(Regex("\\s+"))?.firstOrNull()?.takeIf { it.isNotEmpty() }

    /** Approved = green; still collecting or under review = amber; rejected / blocked = red (a decision, Q96). */
    fun seal(state: VerifyState): SealTone = when (state) {
        VerifyState.APPROVED -> SealTone.OK
        VerifyState.INCOMPLETE, VerifyState.REVIEW -> SealTone.WARN
        VerifyState.REJECTED, VerifyState.BLOCKED -> SealTone.ERR
    }

    /** The seal's spoken label: "Tasdiqlangan" / "Tasdiqlanmagan"; a decided account says its own word. */
    fun sealLabelKey(state: VerifyState): String = when (seal(state)) {
        SealTone.OK -> "status.approved"
        SealTone.WARN -> "driver.v3reg.badgeUnverified"
        SealTone.ERR -> state.labelKey
    }

    /** The seal's tap: "Tasdiqlangan haydovchi" / "Tasdiqlash kutilmoqda — …"; rejected / blocked: the derived word. */
    fun sealToastKey(state: VerifyState): String = when (seal(state)) {
        SealTone.OK -> "driver.v3reg.badgeApproved"
        SealTone.WARN -> "driver.v3reg.badgePending"
        SealTone.ERR -> state.labelKey
    }

    /** The credit on the "Kredit va taklif kodi" card: what can be used now (never money, Q16/Q103); 0 = none. */
    fun creditMinor(buckets: List<PromoBucketDTO>): Long = PromoRules.driverBuckets(buckets).sumOf { it.availableMinor }
}
