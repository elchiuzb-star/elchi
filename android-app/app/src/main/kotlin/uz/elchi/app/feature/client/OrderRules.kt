package uz.elchi.app.feature.client

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import uz.elchi.app.api.generated.ActorSide
import uz.elchi.app.api.generated.ListingDTO
import uz.elchi.app.api.generated.ListingKind
import uz.elchi.app.api.generated.ListingStatus
import uz.elchi.app.api.generated.PassengerDetails
import uz.elchi.app.api.generated.PointEndDTO
import uz.elchi.app.api.generated.PriceBasis
import uz.elchi.app.api.generated.PromoConsentInput
import uz.elchi.app.api.generated.ProposalPromoClientDTO
import uz.elchi.app.api.generated.ProposalPromoConsent
import uz.elchi.app.api.generated.ProposalStatus
import uz.elchi.app.api.generated.ProposalThreadDTO
import uz.elchi.app.api.generated.ProposalVersionDTO
import uz.elchi.app.api.generated.RatingBucket
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.ui.theme.Tone
import java.math.BigDecimal
import java.math.RoundingMode
import java.time.Duration
import java.time.Instant
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * What either side may do with a negotiation right now - `mobile-app/src/app/auction.ts`, with two fixes:
 * an offer whose `expires_at` has passed is closed at once (the server's sweep may not have run yet), and "another
 * price" is offered only while this side still has a price revision (the web shows it and lets the server refuse).
 */
data class NegotiationActions(
    /** The thread is live and its current version can still be answered. */
    val open: Boolean,
    /** The other side spoke last, so the ball is here. */
    val theirTurn: Boolean,
    /** AC05: never your own version. */
    val canAccept: Boolean,
    val canReject: Boolean,
    val canCounter: Boolean,
    /** You can take back what you wrote, not what they wrote. */
    val canWithdraw: Boolean,
    /** How many more times this side may change the price. */
    val revisionsLeft: Long,
    /** Still "active" on the server, but its time is over: shown as expired, nothing can be pressed. */
    val expiredLocally: Boolean,
) {
    companion object {
        val CLOSED = NegotiationActions(open = false, theirTurn = false, canAccept = false, canReject = false, canCounter = false, canWithdraw = false, revisionsLeft = 0, expiredLocally = false)
    }
}

/** The bids screen's sort chips. */
enum class OfferSort { CHEAPEST, FASTEST, RATING }

/** Why an edit cannot be sent as typed (`listingOwner.invalid.<name>`). */
enum class EditInvalid(val key: String) {
    PRICE("price"), WINDOW_INCOMPLETE("window_incomplete"), WINDOW_ORDER("window_order"), WINDOW_PAST("window_past"),
    // Q145: a passenger request's seat count (1..8, more than the children).
    SEATS("seats"), SEATS_CHILDREN("seats_children"),
}

/** What the edit form holds: so'm digits as typed and the window as Tashkent wall-clock times. */
data class ListingEditForm(
    val priceDigits: String,
    val comment: String,
    val windowStart: LocalDateTime?,
    val windowEnd: LocalDateTime?,
    /** Q145: the seat count of a passenger request, as typed; empty for other listings. */
    val seats: String = "",
)

/**
 * `mobile-app/src/app/listingEdit.ts` (`planListingPatch`): only the fields that change travel, and Q20 decides
 * whether the edit is material - on a live listing a moved window expires every open offer; a new price or comment
 * does not. The screen asks for the second tap ("Tushundim, saqlash") only when [material].
 */
data class ListingPatchPlan(
    val unitPriceMinor: Long? = null,
    /** Set = the comment changes; an empty string clears it (sent as null). */
    val comment: String? = null,
    val windowStartIso: String? = null,
    val windowEndIso: String? = null,
    val material: Boolean = false,
    val invalid: EditInvalid? = null,
    /** Q145: the whole passenger block with the new count (the server replaces the block); null = unchanged. */
    val passenger: PassengerDetails? = null,
) {
    val empty: Boolean get() = unitPriceMinor == null && comment == null && windowStartIso == null && passenger == null
}

/** Offers on one listing, for its row in the orders list: live ones and when the newest arrived. */
data class OfferStats(val open: Int, val latest: Instant?)

/** The third line of a listing's row (design `meta`): what is new, that a driver was chosen, or how long it runs. */
sealed interface ListingMeta {
    /** "Yangi taklif: 12 daqiqa oldin" - [highlight] (blue) while an offer is still open. */
    data class NewOffer(val at: Instant, val highlight: Boolean) : ListingMeta
    /** "Haydovchi tanlandi" */
    data object DriverChosen : ListingMeta
    /** "E'lon amal qiladi: 02.10 gacha" */
    data class ValidUntil(val date: String) : ListingMeta
}

/** The offer card's badge, following the chosen sort (design `badges`). */
enum class OfferBadge { CHEAPEST, FASTEST, RATED }

/** Why the counter form cannot be sent as typed (shown in red under the field after a tap on "Yuborish"). */
enum class CounterProblem { EMPTY, SAME }

/**
 * What the counter form works in: the per-seat price for a Taksi request priced per person (the server multiplies
 * by the seats), else the whole price. [base] prefills the field and is what "the same price" compares with.
 */
data class CounterUnits(val perSeat: Boolean, val quantity: Long, val base: Long) {
    /** The total the client would agree to for [unitMinor] ("Jami: ..."). */
    fun total(unitMinor: Long): Long = if (perSeat) unitMinor * quantity else unitMinor
}

/** The 5-step tracker under the listing's status (design `L.steps`): how far it got, or that it stopped. */
data class ListingProgress(val step: Int, val stopped: Boolean)

/** Pure rules of the orders, listing and offers screens: no Android, no network - unit-tested. */
object OrderRules {
    /** `marketplace.service.LIVE_STATUSES`: where offers exist that an edit could expire. */
    private val LIVE = setOf(ListingStatus.PUBLISHED, ListingStatus.PAUSED)
    private val EDITABLE = setOf(ListingStatus.DRAFT, ListingStatus.PUBLISHED, ListingStatus.PAUSED)

    // -- negotiation --------------------------------------------------------------------------------------------

    fun negotiationActions(thread: ProposalThreadDTO, now: Instant, mySide: ActorSide = ActorSide.CLIENT): NegotiationActions {
        val version = thread.currentVersion ?: return NegotiationActions.CLOSED
        if (thread.state != STATE_OPEN || version.status != ProposalStatus.ACTIVE) return NegotiationActions.CLOSED
        val expires = parseInstant(version.expiresAt)
        if (expires == null || !now.isBefore(expires)) return NegotiationActions.CLOSED.copy(expiredLocally = true)
        val theirTurn = version.authorSide != mySide
        val left = if (mySide == ActorSide.CLIENT) version.priceRevisionsLeft.client else version.priceRevisionsLeft.driver
        return NegotiationActions(
            open = true,
            theirTurn = theirTurn,
            // AC05: accepting your own version would let one person make a booking alone.
            canAccept = theirTurn,
            canReject = theirTurn,
            canCounter = theirTurn && left > 0,
            canWithdraw = !theirTurn,
            revisionsLeft = left,
            expiredLocally = false,
        )
    }

    /**
     * The word for a closed offer (`proposalStatus.<status>`): "muddati tugagan" also for one the server still
     * calls active but whose time has run out.
     */
    fun closedStatusKey(thread: ProposalThreadDTO, now: Instant): String {
        val version = thread.currentVersion ?: return "proposalStatus.expired"
        if (version.status == ProposalStatus.ACTIVE) return if (thread.state == STATE_ACCEPTED) "proposalStatus.accepted" else "proposalStatus.expired"
        return "proposalStatus.${version.status.value}"
    }

    /** Seconds left on an open offer (never negative); null when the time cannot be read. */
    fun secondsLeft(version: ProposalVersionDTO, now: Instant): Long? =
        parseInstant(version.expiresAt)?.let { Duration.between(now, it).seconds.coerceAtLeast(0) }

    /** Rounds a countdown up to whole minutes, so "1 daqiqa" stays true until the last second. */
    fun countdownParts(seconds: Long): Pair<Long, Long> {
        val minutes = (seconds + 59) / 60
        return (minutes / 60) to (minutes % 60)
    }

    /**
     * The offers in the chosen order. Offers the client can answer come first, then its own counters waiting for a
     * driver, then closed ones; within each: cheapest total, earliest pickup, or the better rating group (more
     * ratings first within a group). Ties keep the server order.
     */
    fun sortOffers(threads: List<ProposalThreadDTO>, sort: OfferSort, now: Instant): List<ProposalThreadDTO> {
        val live = compareBy<ProposalThreadDTO> { t ->
            val a = negotiationActions(t, now)
            if (a.canAccept) 0 else if (a.open) 1 else 2
        }
        val byChoice: Comparator<ProposalThreadDTO> = when (sort) {
            OfferSort.CHEAPEST -> compareBy { it.currentVersion?.totalMinor ?: Long.MAX_VALUE }
            OfferSort.FASTEST -> compareBy { it.currentVersion?.pickupWindowStart?.let(::parseInstant) ?: Instant.MAX }
            OfferSort.RATING -> compareBy<ProposalThreadDTO> { ratingRank(it.driverSummary?.ratingBucket) }
                .thenByDescending { it.driverSummary?.ratingCount ?: 0 }
                .thenBy { it.currentVersion?.totalMinor ?: Long.MAX_VALUE }
        }
        return threads.sortedWith(live.then(byChoice))
    }

    private fun ratingRank(bucket: RatingBucket?): Int = when (bucket) {
        RatingBucket.GOOD -> 0
        RatingBucket.NEW_VERIFIED -> 1
        RatingBucket.MIXED -> 2
        RatingBucket.LOW -> 3
        else -> 4
    }

    /**
     * The one offer that gets the "Eng arzon" badge: the lowest total among those the client can choose now (open,
     * the driver's price); null when there is none. The client's own counter is not an offer to choose.
     */
    fun cheapestOpen(threads: List<ProposalThreadDTO>, now: Instant): String? =
        threads.filter { negotiationActions(it, now).canAccept }.minByOrNull { it.currentVersion?.totalMinor ?: Long.MAX_VALUE }?.id

    /** Live offers and the newest one's arrival (any state), for the listing's row. */
    fun offerStats(threads: List<ProposalThreadDTO>, now: Instant): OfferStats = OfferStats(
        open = threads.count { negotiationActions(it, now).open },
        latest = threads.mapNotNull { t -> t.currentVersion?.createdAt?.let(::parseInstant) }.maxOrNull(),
    )

    /**
     * The badge each offer the client can choose gets under the chosen sort: the cheapest one ("Eng arzon"), the
     * earliest pickup ("Eng tez"), or every driver in the `good` rating group ("Yaxshi baholangan" - a group, never
     * a number, U6). Offers waiting for the driver and closed ones get none.
     */
    fun sortBadges(threads: List<ProposalThreadDTO>, sort: OfferSort, now: Instant): Map<String, OfferBadge> {
        val choosable = threads.filter { negotiationActions(it, now).canAccept }
        return when (sort) {
            OfferSort.CHEAPEST -> cheapestOpen(threads, now)?.let { mapOf(it to OfferBadge.CHEAPEST) }.orEmpty()
            OfferSort.FASTEST -> choosable.minByOrNull { it.currentVersion?.pickupWindowStart?.let(::parseInstant) ?: Instant.MAX }
                ?.takeIf { it.currentVersion?.pickupWindowStart?.let(::parseInstant) != null }
                ?.let { mapOf(it.id to OfferBadge.FASTEST) }.orEmpty()
            OfferSort.RATING -> choosable.filter { it.driverSummary?.ratingBucket == RatingBucket.GOOD }.associate { it.id to OfferBadge.RATED }
        }
    }

    /** "Qarshi taklif": the driver answered the client's counter with a price of its own (its version after the first). */
    fun driverCountered(thread: ProposalThreadDTO): Boolean {
        val version = thread.currentVersion ?: return false
        return version.authorSide == ActorSide.DRIVER && version.revision > 1
    }

    /**
     * The client's own price the driver answered ("sizniki 135 000 so'm"): the newest earlier version the client
     * wrote. Only a thread read with its versions (`GET /proposals/{id}`) knows it; the list sends none.
     */
    fun clientPreviousTotal(thread: ProposalThreadDTO): Long? {
        val current = thread.currentVersion ?: return null
        return thread.versions.orEmpty()
            .filter { it.authorSide == ActorSide.CLIENT && it.revision < current.revision }
            .maxByOrNull { it.revision }?.totalMinor
    }

    /**
     * Why a closed offer closed, in the design's words (`status_reason`): expired, rejected, withdrawn, another
     * driver chosen, the listing cancelled, its terms changed; an accepted one says so. Unknown reasons fall back
     * to the version's status.
     */
    fun closedReasonKey(thread: ProposalThreadDTO, now: Instant): String {
        val version = thread.currentVersion ?: return "status.expired"
        if (thread.state == STATE_ACCEPTED || version.status == ProposalStatus.ACCEPTED) return "client.amendment.statusAccepted"
        // Still "active" on the server, but its time ran out (the sweep has not run yet).
        if (version.status == ProposalStatus.ACTIVE) return "status.expired"
        return when (version.statusReason) {
            "ttl_expired", "listing_expired", "expired" -> "status.expired"
            "rejected" -> "amendment.rejected"
            "withdrawn" -> "client.offers.closed.withdrawn"
            "demand_fulfilled", "capacity_gone" -> "client.offers.closed.demandFulfilled"
            "listing_closed" -> "notification.listing.cancelled.title"
            "listing_changed" -> "client.offers.closed.listingChanged"
            else -> when (version.status) {
                ProposalStatus.REJECTED -> "amendment.rejected"
                ProposalStatus.WITHDRAWN -> "client.offers.closed.withdrawn"
                else -> "status.expired"
            }
        }
    }

    /**
     * The counter form's units for [version] (§6, the Taksi fix): a `per_seat` offer is countered per person - the
     * field holds and compares the seat price and `unit_price_minor` carries it; anything else is the whole price.
     */
    fun counterUnits(version: ProposalVersionDTO): CounterUnits {
        val perSeat = version.priceBasis == PriceBasis.PER_SEAT
        return CounterUnits(perSeat = perSeat, quantity = version.quantity.coerceAtLeast(1), base = if (perSeat) version.unitPriceMinor else version.totalMinor)
    }

    /** The price the counter sends as `unit_price_minor`; null with the reason the tap is refused. */
    fun counterCheck(digits: String, units: CounterUnits): Pair<Long?, CounterProblem?> {
        val minor = ParcelRules.soumToMinor(digits) ?: return null to CounterProblem.EMPTY
        if (minor == units.base) return null to CounterProblem.SAME
        return minor to null
    }

    // -- listing detail -----------------------------------------------------------------------------------------

    /**
     * The row's meta line: a published listing with offers says when the newest came (blue while one is open); a
     * fulfilled one that a driver was chosen; a live one until when it runs; an expired or cancelled one nothing.
     */
    fun listingMeta(listing: ListingDTO, stats: OfferStats?): ListingMeta? = when {
        listing.status == ListingStatus.FULFILLED -> ListingMeta.DriverChosen
        listing.status == ListingStatus.PUBLISHED && stats?.latest != null -> ListingMeta.NewOffer(stats.latest, highlight = stats.open > 0)
        listing.status in LIVE -> dayDot(listing.expiresAt)?.let { ListingMeta.ValidUntil(it) }
        else -> null
    }

    /** The client calls a fulfilled request "Bron qilindi"; every other status keeps its shared word. */
    fun clientListingStatusKey(status: ListingStatus): String =
        if (status == ListingStatus.FULFILLED) "client.listing.statusFulfilled" else listingStatusKey(status)

    /**
     * Tracker: 0 published, 1 once any offer exists, 2 a driver was chosen, 3 on the way, 4 done (the booking's
     * status, when known). An expired or cancelled listing stopped: all grey, the offers step crossed out.
     */
    fun listingProgress(listing: ListingDTO, threads: List<ProposalThreadDTO>, bookingStatus: String?): ListingProgress {
        if (listing.status == ListingStatus.EXPIRED || listing.status == ListingStatus.CANCELLED) return ListingProgress(1, stopped = true)
        val step = when {
            bookingStatus == "completed" -> 4
            bookingStatus in ON_THE_WAY -> 3
            listing.status == ListingStatus.FULFILLED -> 2
            threads.isNotEmpty() -> 1
            else -> 0
        }
        return ListingProgress(step, stopped = false)
    }

    private val ON_THE_WAY = setOf("in_transit", "picked_up", "onboard", "arrived", "delivered")

    /** The status notice under the listing card: (dictionary key, tone), or null for a published one. */
    fun listingNotice(status: ListingStatus): Pair<String, Tone>? = when (status) {
        ListingStatus.PAUSED -> "client.listing.noticePaused" to Tone.GRAY
        ListingStatus.EXPIRED -> "client.listing.noticeExpired" to Tone.GRAY
        ListingStatus.CANCELLED -> "client.listing.noticeCancelled" to Tone.ERR
        ListingStatus.FULFILLED -> "client.listing.noticeFulfilled" to Tone.OK
        else -> null
    }

    /** "Chilonzor, 9-kvartal" -> "Chilonzor": the first comma part of a place name. */
    fun shortPlace(name: String): String = name.substringBefore(',').trim().ifEmpty { name }

    /** `29.09, 09:00` */
    fun dayTime(value: String?): String? = tashkent(value)?.let(ParcelRules::displayShort)

    /** `10:00` */
    fun hourMinute(value: String?): String? = tashkent(value)?.let { "%02d:%02d".format(it.hour, it.minute) }

    /**
     * The offer's pickup window for its grey box: times only when it is the listing's day ("10:00 – 12:00"), else
     * with the day ("30.09, 10:00 – 12:00").
     */
    fun offerWindow(start: String?, end: String?, listingDay: String?): String? {
        val s = tashkent(start) ?: return null
        val e = tashkent(end)
        val day = s.format(DateTimeFormatter.ofPattern("dd.MM"))
        val times = listOfNotNull(hourMinute(start), e?.let { hourMinute(end) }).joinToString(" – ")
        val endDay = e?.format(DateTimeFormatter.ofPattern("dd.MM"))
        return when {
            endDay != null && endDay != day -> "${ParcelRules.displayShort(s)} – ${ParcelRules.displayShort(e)}"
            listingDay == null || listingDay == day -> times
            else -> "$day, $times"
        }
    }

    // -- promo (only when the server sends a quote; never in dev, Q131/Q147) -------------------------------------

    /** The client's consent body - sent only when the person ticked "Bonusni ishlataman", with the numbers shown. */
    fun acceptConsent(quote: ProposalPromoClientDTO?, ticked: Boolean): PromoConsentInput? =
        if (quote != null && ticked) PromoConsentInput(cashDueMinor = quote.cashDueMinor, passengerBonusMinor = quote.passengerDiscountMinor) else null

    fun counterConsent(quote: ProposalPromoClientDTO?, ticked: Boolean): ProposalPromoConsent? =
        if (quote != null && ticked) ProposalPromoConsent(cashDueMinor = quote.cashDueMinor, passengerBonusMinor = quote.passengerDiscountMinor) else null

    /** `promo.noDiscount.<name>` for the server's reason; null for a reason this app has no words for. */
    fun noDiscountKey(reason: String?): String? = when (reason) {
        "service_not_eligible" -> "promo.noDiscount.serviceNotEligible"
        "bonus_expired" -> "promo.noDiscount.bonusExpired"
        "bonus_reserved" -> "promo.noDiscount.bonusReserved"
        "bonus_on_hold" -> "promo.noDiscount.bonusOnHold"
        "no_campaign" -> "promo.noDiscount.noCampaign"
        "client_update_required" -> "promo.noDiscount.clientUpdateRequired"
        "trip_terms" -> "promo.noDiscount.tripTerms"
        else -> null
    }

    // -- listing owner ------------------------------------------------------------------------------------------

    fun canPause(status: ListingStatus) = status == ListingStatus.PUBLISHED
    fun canResume(status: ListingStatus) = status == ListingStatus.PAUSED
    fun canEdit(status: ListingStatus) = status in EDITABLE
    fun canCancel(status: ListingStatus) = status in EDITABLE
    /** Share links exist only for a listing people can still answer (`LISTING_NOT_OPEN` otherwise). */
    fun canShare(status: ListingStatus) = status in LIVE
    fun isLive(status: ListingStatus) = status in LIVE

    /** A trip offer's window comes from its trip; only a client request lets its owner move the window. */
    fun windowEditable(listing: ListingDTO) = listing.kind == ListingKind.REQUEST

    fun editForm(listing: ListingDTO): ListingEditForm = ListingEditForm(
        priceDigits = ParcelRules.minorToSoum(listing.unitPriceMinor).toString(),
        comment = listing.comment.orEmpty(),
        windowStart = parseInstant(listing.departureWindowStart)?.let { LocalDateTime.ofInstant(it, ParcelRules.TASHKENT) },
        windowEnd = parseInstant(listing.departureWindowEnd)?.let { LocalDateTime.ofInstant(it, ParcelRules.TASHKENT) },
        seats = listing.passenger?.takeIf { TaxiRules.seatsEditable(listing) }?.seatCount?.toString().orEmpty(),
    )

    /**
     * After a VERSION_CONFLICT: the fields the person changed ([typed] differs from [base]) stay theirs; every other
     * field takes the listing's new value ([fresh]), so saving again does not undo the other change.
     */
    fun rebaseForm(typed: ListingEditForm, base: ListingEditForm, fresh: ListingEditForm): ListingEditForm = ListingEditForm(
        priceDigits = if (typed.priceDigits != base.priceDigits) typed.priceDigits else fresh.priceDigits,
        comment = if (typed.comment != base.comment) typed.comment else fresh.comment,
        windowStart = if (typed.windowStart != base.windowStart) typed.windowStart else fresh.windowStart,
        windowEnd = if (typed.windowEnd != base.windowEnd) typed.windowEnd else fresh.windowEnd,
        seats = if (typed.seats != base.seats) typed.seats else fresh.seats,
    )

    fun planListingPatch(listing: ListingDTO, form: ListingEditForm, now: Instant): ListingPatchPlan {
        var invalid: EditInvalid? = null
        var price: Long? = null
        var comment: String? = null
        var start: String? = null
        var end: String? = null
        var material = false

        val minor = ParcelRules.soumToMinor(form.priceDigits)
        if (minor == null) invalid = EditInvalid.PRICE else if (minor != listing.unitPriceMinor) price = minor

        val typed = form.comment.trim()
        if (typed != listing.comment.orEmpty().trim()) comment = typed

        if (windowEditable(listing)) {
            val s = form.windowStart?.atZone(ParcelRules.TASHKENT)?.toInstant()
            val e = form.windowEnd?.atZone(ParcelRules.TASHKENT)?.toInstant()
            when {
                s == null || e == null -> invalid = invalid ?: EditInvalid.WINDOW_INCOMPLETE
                !e.isAfter(s) -> invalid = invalid ?: EditInvalid.WINDOW_ORDER
                !e.isAfter(now) -> invalid = invalid ?: EditInvalid.WINDOW_PAST
                else -> {
                    val moved = s != parseInstant(listing.departureWindowStart) || e != parseInstant(listing.departureWindowEnd)
                    if (moved) {
                        // The server checks the pair (end after start), so both ends always travel together.
                        start = ParcelRules.toOffsetIso(form.windowStart)
                        end = ParcelRules.toOffsetIso(form.windowEnd)
                        material = listing.status in LIVE
                    }
                }
            }
        }
        var passenger: PassengerDetails? = null
        if (TaxiRules.seatsEditable(listing)) {
            val (block, seatsInvalid) = TaxiRules.seatsPatch(listing, form.seats)
            if (seatsInvalid != null) {
                invalid = invalid ?: seatsInvalid
            } else if (block != null) {
                // Q20: a new count expires the open offers - drivers offer again for the new number of people.
                passenger = block
                material = material || listing.status in LIVE
            }
        }
        return ListingPatchPlan(price, comment, start, end, material, invalid, passenger)
    }

    // -- share links --------------------------------------------------------------------------------------------

    /** The design's chips, in days. */
    val SHARE_TTL_DAYS = listOf(1, 2, 3, 7, 14)
    const val SHARE_TTL_DEFAULT_DAYS = 2

    /** Days on the chip to the API's `ttl_hours` (1..336). */
    fun shareTtlHours(days: Int): Long = (days * 24L).coerceIn(1, 336)

    // -- statuses -----------------------------------------------------------------------------------------------

    /**
     * The colour a status earns (`STATUS_TONE` in the web client): waiting grey, moving blue, a person has to act
     * amber, finished green, broken red. The badge's dot keeps the meaning without the colour.
     */
    fun statusTone(status: String): Tone = when (status) {
        "published", "in_transit", "boarding", "in_progress", "bidding", "onboard", "arrived" -> Tone.BLUE
        "pending", "accepted", "selected", "picked_up", "awaiting_pickup", "return_required" -> Tone.WARN
        "delivered", "confirmed", "approved", "completed", "fulfilled" -> Tone.OK
        "cancelled", "rejected", "disputed", "no_show", "interrupted", "delivery_failed" -> Tone.ERR
        else -> Tone.GRAY // draft, paused, expired, returned, unknown
    }

    fun listingStatusKey(status: ListingStatus): String = "status.${status.value}"

    /**
     * A booking's words. For a parcel the system only knows that the trip is being prepared and that it departed -
     * not that the parcel was handed over (Q139/Q142) - so "in transit" reads "Haydovchi yo'lga chiqdi".
     */
    fun bookingStatusKey(serviceType: ServiceType, status: String): String = if (serviceType == ServiceType.PARCEL) {
        when (status) {
            "awaiting_pickup" -> "parcel.progress.tripPreparing"
            "in_transit", "picked_up" -> "parcel.status.driverDeparted"
            "delivered" -> "parcel.progress.deliveredByOperator"
            "return_required", "returned", "delivery_failed" -> "tripDetail.service.$status"
            // Design 04: "Yakunlandi" (the rung's word), not the adjective "Yakunlangan".
            "completed" -> "app.progress.completed"
            else -> "status.$status"
        }
    } else {
        when (status) {
            // Design 04: "Olib ketish kutilmoqda" - the driver's "Keldim" is a separate signal, not this status.
            "awaiting_pickup" -> "status.awaiting_pickup"
            "completed" -> "app.progress.completed"
            // Taksi: "Mashinada" / "Yetib keldi" rather than the raw codes.
            "onboard" -> "status.onboard"
            "arrived" -> "status.arrived"
            else -> "status.$status"
        }
    }

    /**
     * The client's booking badge (design 04 `TONES`): agreed and waiting amber, under way blue, delivered / arrived /
     * completed green, cancelled and no-show red. The driver's screens keep [bookingTone].
     */
    fun clientBookingTone(serviceType: ServiceType, status: String): Tone = when (status) {
        "confirmed", "awaiting_pickup" -> Tone.WARN
        "in_transit", "picked_up", "onboard" -> Tone.BLUE
        "delivered", "arrived", "completed" -> Tone.OK
        else -> bookingTone(serviceType, status)
    }

    /** A parcel "picked up" by the retired driver ladder sits on the "departed" step (and colour), no further. */
    fun bookingTone(serviceType: ServiceType, status: String): Tone =
        if (serviceType == ServiceType.PARCEL && status == "picked_up") Tone.BLUE else statusTone(status)

    fun legacyStatusKey(status: String): String = "status.$status"

    // -- money --------------------------------------------------------------------------------------------------

    /**
     * A v1 order's price in minor units: `final_price` once agreed, else the client's own price, else the suggested
     * one. v1 sends DECIMAL so'm as a string (`"70000.00"`) or a number - never minor units. Null when none can be read.
     */
    fun legacyPriceMinor(finalPrice: JsonElement?, suggestedPrice: JsonElement?, clientPrice: JsonElement? = null): Long? =
        (decimalSoum(finalPrice) ?: decimalSoum(clientPrice) ?: decimalSoum(suggestedPrice))?.let(::soumDecimalToMinor)

    private fun decimalSoum(value: JsonElement?): BigDecimal? {
        if (value == null || value is JsonNull || value !is JsonPrimitive) return null
        return value.content.trim().takeIf { it.isNotEmpty() }?.let { runCatching { BigDecimal(it) }.getOrNull() }?.takeIf { it.signum() > 0 }
    }

    private fun soumDecimalToMinor(soum: BigDecimal): Long = soum.multiply(BigDecimal(100)).setScale(0, RoundingMode.HALF_UP).toLong()

    // -- names, dates -------------------------------------------------------------------------------------------

    /**
     * A short name for a route end ("Toshkent → Buxoro"): the district the point was marked in, else its address,
     * else - honestly - the coordinates (ADR-0028: an end is always a point).
     */
    fun shortEnd(point: PointEndDTO?, ru: Boolean): String =
        point?.district?.nameUz
            ?: point?.address?.let(ParcelRules::withoutCountry)?.takeIf { it.isNotBlank() }
            ?: point?.let { ParcelRules.coordinates(it.lat, it.lng) }
            ?: "?"

    /** The full name for a detail row: the address, else the district or coordinates. */
    fun fullEnd(point: PointEndDTO?, ru: Boolean): String =
        point?.address?.let(ParcelRules::withoutCountry)?.takeIf { it.isNotBlank() }
            ?: point?.district?.nameUz
            ?: point?.let { ParcelRules.coordinates(it.lat, it.lng) }
            ?: "?"

    fun parseInstant(value: String?): Instant? = value?.let { runCatching { Instant.parse(it) }.getOrNull() ?: runCatching { java.time.OffsetDateTime.parse(it).toInstant() }.getOrNull() }

    fun tashkent(value: String?): LocalDateTime? = parseInstant(value)?.let { LocalDateTime.ofInstant(it, ParcelRules.TASHKENT) }

    /** `29 sen` / `29 сент.` - the list's day, in Tashkent, in the app's language. */
    fun dayMonth(value: String?, languageTag: String): String? =
        tashkent(value)?.format(DateTimeFormatter.ofPattern("d MMM", Locale.forLanguageTag(languageTag)))

    /** `02.10` */
    fun dayDot(value: String?): String? = tashkent(value)?.format(DateTimeFormatter.ofPattern("dd.MM"))

    /** `29.09, 09:00 - 29.09, 18:00` */
    fun windowText(start: String?, end: String?): String? {
        val s = tashkent(start) ?: return null
        val e = tashkent(end) ?: return ParcelRules.displayShort(s)
        return "${ParcelRules.displayShort(s)} - ${ParcelRules.displayShort(e)}"
    }

    /** `29.09 - 29.09` */
    fun dayRange(start: String?, end: String?): String? {
        val s = dayDot(start) ?: return null
        return dayDot(end)?.let { "$s - $it" } ?: s
    }

    /** How long ago, as the unit the sentence needs: minutes under an hour, hours under a day, then days. */
    sealed interface Ago {
        data class Minutes(val value: Long) : Ago
        data class Hours(val value: Long) : Ago
        data class Days(val value: Long) : Ago
    }

    fun ago(then: Instant, now: Instant): Ago {
        val minutes = Duration.between(then, now).toMinutes().coerceAtLeast(1)
        return when {
            minutes < 60 -> Ago.Minutes(minutes)
            minutes < 24 * 60 -> Ago.Hours(minutes / 60)
            else -> Ago.Days(minutes / (24 * 60))
        }
    }

    const val STATE_OPEN = "open"
    const val STATE_ACCEPTED = "accepted"
    const val STATE_CLOSED = "closed"

    /** The one reason code the app sends when the owner cancels its request (ListingCancel.reason_code). */
    const val CANCEL_REASON = "client_changed_plan"
}
