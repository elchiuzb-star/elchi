package uz.elchi.app.feature.driver

import uz.elchi.app.api.generated.ActorSide
import uz.elchi.app.api.generated.ProposalStatus
import uz.elchi.app.api.generated.ProposalThreadDTO
import uz.elchi.app.api.generated.RegionDTO
import uz.elchi.app.api.generated.DistrictDTO
import uz.elchi.app.api.generated.SavedSearchDTO
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.api.generated.TripDTO
import uz.elchi.app.api.generated.TripStatus
import uz.elchi.app.feature.client.Load
import uz.elchi.app.feature.client.OrderRules
import uz.elchi.app.ui.components.LadderState
import uz.elchi.app.ui.theme.Tone
import java.time.Instant

/** A feed card's "you already offered here" (design 07 §5.7): the thread to open and what to say. */
sealed interface MyFeedOffer {
    val threadId: String

    /** "Siz taklif yubordingiz: {price}" - the current version's total (per-seat listings too, §11). */
    data class Sent(override val threadId: String, val totalMinor: Long) : MyFeedOffer

    /** "Mijoz qabul qildi". */
    data class Accepted(override val threadId: String) : MyFeedOffer
}

/** The Takliflarim card's badge (design 07 §8.1): the dictionary key and its tone. */
enum class ProposalBadge(val key: String, val tone: Tone) {
    WAITING("status.proposed", Tone.GRAY),
    COUNTERED("driver.offer.badgeCountered", Tone.WARN),
    MY_COUNTER("driver.offer.badgeMyCounter", Tone.BLUE),
    ACCEPTED("client.booking.amendStatusAccepted", Tone.OK),
    REJECTED("status.rejected", Tone.ERR),
    WITHDRAWN("status.withdrawn", Tone.GRAY),
    EXPIRED("status.expired", Tone.GRAY),
}

/** The Takliflarim card's status line (design 07 §8.2). Prices are totals in minor units. */
sealed interface ProposalCardLine {
    /** "Mijoz qarshi taklif yubordi: {price} (siz {mine} taklif qilgansiz)"; [mineMinor] null = not known yet. */
    data class ClientCounter(val priceMinor: Long, val mineMinor: Long?) : ProposalCardLine

    /** "Qarshi taklifingiz ({price}) yuborildi — mijoz javobi kutilmoqda." */
    data class MyCounter(val priceMinor: Long) : ProposalCardLine

    /** "Sizning taklifingiz - javob kutilmoqda". */
    data object Waiting : ProposalCardLine

    /** "Bron yaratildi — «Buyurtmalar» bo'limida ko'ring. …" */
    data object Accepted : ProposalCardLine

    /** Closed for good: the badge says it all, the line repeats the server word. */
    data class Closed(val statusKey: String) : ProposalCardLine
}

/** The counter price field's refusal (design 07 §8.5). */
enum class CounterIssue { EMPTY, SAME_AS_CLIENT }

/** What happens after the driver accepted the client's price (Q100, design 07 §8.7). */
sealed interface AcceptNav {
    /** Straight into the booking's chat, where the meeting point is agreed. */
    data class BookingChat(val bookingId: String) : AcceptNav

    /** The accept went through but the answer named no booking: stay on the thread (it reads itself again). */
    data object Stay : AcceptNav
}

/** Home's three tiles (design 07 §1.2); null = could not be counted ("—"). */
data class HomeStats(val trips: Int?, val offers: Int?, val bookings: Int?)

/** The design 07 additions on top of the Stage 08 rules: pure, so they are unit-tested. */
object Design07Rules {
    // -- feed (§5.7) --------------------------------------------------------------------------------------------

    /**
     * The driver's own threads by listing: an accepted one wins over an open one (the client already said yes);
     * among several open ones (should not happen: one open thread per driver and listing) the first is kept.
     */
    fun myFeedOffers(open: List<ProposalThreadDTO>, accepted: List<ProposalThreadDTO>, mine: Map<String, Long> = emptyMap()): Map<String, MyFeedOffer> {
        val out = linkedMapOf<String, MyFeedOffer>()
        open.forEach { thread ->
            val v = thread.currentVersion ?: return@forEach
            if (thread.state != OrderRules.STATE_OPEN) return@forEach
            // "Siz taklif yubordingiz": the driver's own price - under a client counter, the driver's earlier one.
            val total = if (v.authorSide == ActorSide.DRIVER) v.totalMinor else mine[thread.id] ?: previousDriverTotal(thread) ?: v.totalMinor
            out.putIfAbsent(thread.listingId, MyFeedOffer.Sent(thread.id, total))
        }
        accepted.forEach { thread ->
            if (thread.state == OrderRules.STATE_ACCEPTED || thread.bookingId != null) out[thread.listingId] = MyFeedOffer.Accepted(thread.id)
        }
        return out
    }

    // -- Takliflarim (§8.1, §8.2) -------------------------------------------------------------------------------

    /** The driver answered the client's counter with its own price: a driver version after the first. */
    fun isMyCounter(thread: ProposalThreadDTO): Boolean {
        val v = thread.currentVersion ?: return false
        return v.authorSide == ActorSide.DRIVER && v.revision > 1
    }

    fun badge(thread: ProposalThreadDTO, now: Instant): ProposalBadge = when (val line = OfferRules.line(thread, now)) {
        ThreadLine.Accepted -> ProposalBadge.ACCEPTED
        ThreadLine.Countered -> ProposalBadge.COUNTERED
        ThreadLine.Waiting -> if (isMyCounter(thread)) ProposalBadge.MY_COUNTER else ProposalBadge.WAITING
        is ThreadLine.Closed -> when (line.statusKey) {
            "proposalStatus.rejected" -> ProposalBadge.REJECTED
            "proposalStatus.withdrawn" -> ProposalBadge.WITHDRAWN
            "proposalStatus.accepted" -> ProposalBadge.ACCEPTED
            else -> ProposalBadge.EXPIRED
        }
    }

    /** The driver's latest own total before the client's current counter; null without the version history. */
    fun previousDriverTotal(thread: ProposalThreadDTO): Long? {
        val current = thread.currentVersion ?: return null
        return thread.versions.orEmpty()
            .filter { it.authorSide == ActorSide.DRIVER && it.revision < current.revision }
            .maxByOrNull { it.revision }
            ?.totalMinor
    }

    /** [mine] = the driver's previous total read from the thread's history (the list carries no versions). */
    fun cardLine(thread: ProposalThreadDTO, now: Instant, mine: Long? = previousDriverTotal(thread)): ProposalCardLine {
        val v = thread.currentVersion
        return when (val line = OfferRules.line(thread, now)) {
            ThreadLine.Accepted -> ProposalCardLine.Accepted
            ThreadLine.Countered -> ProposalCardLine.ClientCounter(v?.totalMinor ?: 0, mine)
            ThreadLine.Waiting -> if (v != null && isMyCounter(thread)) ProposalCardLine.MyCounter(v.totalMinor) else ProposalCardLine.Waiting
            is ThreadLine.Closed -> ProposalCardLine.Closed(line.statusKey)
        }
    }

    /** Countered cards get the blue outline (the driver's move). */
    fun outlined(badge: ProposalBadge): Boolean = badge == ProposalBadge.COUNTERED

    /** Withdrawn cards are faded in the design. */
    fun faded(badge: ProposalBadge): Boolean = badge == ProposalBadge.WITHDRAWN

    /** The "Takliflarim" pill's red count: open threads where the client countered. */
    fun counteredCount(open: List<ProposalThreadDTO>, now: Instant): Int = open.count { OfferRules.line(it, now) == ThreadLine.Countered }

    // -- counter (§8.5) -----------------------------------------------------------------------------------------

    /**
     * Empty, or the same unit price as the client's current version: a counter that does not move the price would
     * only burn a revision.
     */
    fun counterIssue(text: String, clientUnitMinor: Long?): CounterIssue? {
        val digits = text.filter(Char::isDigit)
        val unit = digits.toLongOrNull()?.takeIf { it > 0 }?.let { it * 100 } ?: return CounterIssue.EMPTY
        return if (clientUnitMinor != null && unit == clientUnitMinor) CounterIssue.SAME_AS_CLIENT else null
    }

    // -- accept (§8.7, Q100) ------------------------------------------------------------------------------------

    fun afterAccept(bookingId: String?): AcceptNav = bookingId?.takeIf { it.isNotBlank() }?.let { AcceptNav.BookingChat(it) } ?: AcceptNav.Stay

    // -- saved routes (§6.2, §6.3, §6.5) ------------------------------------------------------------------------

    /** The feed's current direction is already in the list (same ends, same service). */
    fun alreadySaved(saved: List<SavedSearchDTO>, query: FeedQuery?): Boolean {
        query ?: return false
        fun same(end: EndIds, district: String?, region: String?): Boolean = when {
            end.districtId != null -> district == end.districtId
            else -> district == null && region == end.regionId
        }
        return saved.any {
            it.serviceType == query.service &&
                same(query.origin, it.originDistrictId, it.originRegionId) &&
                same(query.destination, it.destinationDistrictId, it.destinationRegionId)
        }
    }

    fun atLimit(saved: List<SavedSearchDTO>): Boolean = saved.size >= FeedRules.SAVED_LIMIT

    /** One end of a saved route as the feed's pick; null when it cannot be (names not read yet). */
    fun feedEnd(districtId: String?, regionId: String?, regions: List<RegionDTO>, districts: Map<String, DistrictDTO>): FeedEnd? {
        if (districtId != null) {
            val d = districts[districtId] ?: return null
            val r = regions.firstOrNull { it.id == d.region.id }
            return FeedEnd(
                regionId = d.region.id,
                regionName = r?.nameUz ?: d.region.nameUz,
                regionNameRu = r?.nameRu,
                requiresDistrict = r?.requiresDistrict ?: true,
                districtId = d.id,
                districtName = d.nameUz,
                districtNameRu = d.nameRu,
            )
        }
        val r = regions.firstOrNull { it.id == regionId } ?: return null
        return FeedEnd(regionId = r.id, regionName = r.nameUz, regionNameRu = r.nameRu, requiresDistrict = r.requiresDistrict ?: true)
    }

    /** "Lentada ochish": the feed filter for a saved route (dates and service kept/switched), null when not possible. */
    fun filterFor(saved: SavedSearchDTO, current: FeedFilter, regions: List<RegionDTO>, districts: Map<String, DistrictDTO>): FeedFilter? {
        val origin = feedEnd(saved.originDistrictId, saved.originRegionId, regions, districts) ?: return null
        val destination = feedEnd(saved.destinationDistrictId, saved.destinationRegionId, regions, districts) ?: return null
        val service = saved.serviceType.takeIf { it != ServiceType.UNKNOWN } ?: current.serviceType
        return current.copy(service = service.value, origin = origin, destination = destination)
    }

    // -- add trip (§3.4) ----------------------------------------------------------------------------------------

    /** The departure field's error: one pair of keys on both apps. */
    fun departureErrorKey(issues: Set<TripFormIssue>): String? = when {
        TripFormIssue.DEPARTURE in issues -> "driver.trip.departureRequired"
        TripFormIssue.DEPARTURE_PAST in issues -> "driver.trip.departurePast"
        else -> null
    }

    // -- trips (§2.5, §2.6, §4.2, §4.5) -------------------------------------------------------------------------

    /** The success banner of a trip command: depart and cancel say what happened to the clients / offers. */
    fun commandBannerKey(command: TripCommand): String = when (command) {
        TripCommand.DEPART -> "driver.trip.departed"
        TripCommand.CANCEL -> "driver.trip.cancelled"
        else -> "driverRoutes.tripStatusUpdated"
    }

    /** One tracker session at a time: boarding another trip while one is live is refused on the client. */
    fun blocksStart(trips: List<TripDTO>, trip: TripDTO, command: TripCommand): Boolean =
        command == TripCommand.START_BOARDING && trips.any { it.id != trip.id && TripRules.publishable(it.status) }

    /** The places ladder from the trip status (per-place passage is not sent by the server). */
    fun ladder(status: TripStatus, count: Int): List<LadderState> = List(count) { i ->
        when (status) {
            TripStatus.COMPLETED -> LadderState.DONE
            TripStatus.IN_PROGRESS -> when (i) {
                0 -> LadderState.DONE
                1 -> LadderState.CURRENT
                else -> LadderState.TODO
            }
            TripStatus.BOARDING -> if (i == 0) LadderState.CURRENT else LadderState.TODO
            else -> LadderState.TODO
        }
    }

    /** Q142: when the manifest row's phone opens (parcel: at departure; passenger: once on board). */
    fun phoneNoteKey(service: ServiceType): String =
        if (service == ServiceType.PARCEL) "driver.trip.phoneAfterDepart" else "driver.trip.phoneAfterBoard"

    // -- home (§1.2) --------------------------------------------------------------------------------------------

    fun homeStats(trips: Load<List<TripDTO>>, open: Load<List<ProposalThreadDTO>>?, bookingStatuses: Load<List<String>>): HomeStats = HomeStats(
        trips = (trips as? Load.Ready)?.value?.count { TripRules.isActive(it.status) },
        offers = (open as? Load.Ready)?.value?.count { it.state == OrderRules.STATE_OPEN && it.currentVersion?.status == ProposalStatus.ACTIVE },
        bookings = (bookingStatuses as? Load.Ready)?.value?.count(DriverBookingRules::isActive),
    )
}
