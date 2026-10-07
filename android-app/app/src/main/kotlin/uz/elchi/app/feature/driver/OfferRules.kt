package uz.elchi.app.feature.driver

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.longOrNull
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.generated.AcceptRequest
import uz.elchi.app.api.generated.ActorSide
import uz.elchi.app.api.generated.ApiWarning
import uz.elchi.app.api.generated.ListingOfferDTO
import uz.elchi.app.api.generated.ListingPublicDTO
import uz.elchi.app.api.generated.ListingStatus
import uz.elchi.app.api.generated.PromoDriverAckInput
import uz.elchi.app.api.generated.ProposalCounter
import uz.elchi.app.api.generated.ProposalCreate
import uz.elchi.app.api.generated.ProposalPromoDriverDTO
import uz.elchi.app.api.generated.ProposalThreadDTO
import uz.elchi.app.api.generated.ProposalVersionDTO
import uz.elchi.app.api.generated.TripDTO
import uz.elchi.app.feature.client.NegotiationActions
import uz.elchi.app.feature.client.OrderRules
import uz.elchi.app.feature.client.ParcelRules
import java.time.Instant
import java.time.format.DateTimeFormatter

/** When the driver offers to pick up: an interval inside the client's window. */
data class PickupWindow(val start: Instant, val end: Instant)

/** The anonymous rival board (Q40/Q95): how many, the cheapest, the driver's own current offer. */
data class BoardSummary(val count: Int, val cheapestMinor: Long?, val mine: ListingOfferDTO?, val rows: List<ListingOfferDTO>)

/** "Takliflarim" filter (`GET /me/proposals?state=`). */
enum class ProposalTab(val state: String) { OPEN("open"), ACCEPTED("accepted"), CLOSED("closed") }

/** What a thread's status line says, from the latest version. */
sealed interface ThreadLine {
    /** The client countered: the driver's move (`negotiation.clientCountered`). */
    data object Countered : ThreadLine

    /** The driver's own version is waiting for the client (`negotiation.waitingForAnswer`). */
    data object Waiting : ThreadLine

    /** Accepted: a booking exists. */
    data object Accepted : ThreadLine

    /** Closed for good: `proposalStatus.<status>` (rejected / withdrawn / expired / superseded). */
    data class Closed(val statusKey: String) : ThreadLine
}

/** The offer screen and "Takliflarim", pure. */
/** What the offer screen shows (it is also where `elchi://listings/{id}` leads a driver, Stage 10). */
enum class BidView {
    /** Not approved (Q96): the verification gate, never the price field. */
    GATE,

    /** The listing no longer takes offers (paused, fulfilled, expired, cancelled): one sentence, no form. */
    CLOSED,

    /** The request, the rival board and the price form. */
    FORM,
}

object OfferRules {
    // -- the offer screen ----------------------------------------------------------------------------------------

    /**
     * [status] = the driver's status, null while it is still being read (the form shows; the server refuses an
     * unapproved driver anyway, `DRIVER_NOT_ELIGIBLE`); [listing] = the listing's status. The gate comes first: an
     * unapproved driver learns why it cannot offer before whether this listing would take one.
     */
    fun bidView(status: DriverStatus?, listing: ListingStatus): BidView = when {
        status != null && DriverRules.gate(status) != GateVariant.NONE -> BidView.GATE
        listing != ListingStatus.PUBLISHED -> BidView.CLOSED
        else -> BidView.FORM
    }

    /** Planned trips still taking bookings, soonest first: the only ones an offer can be made from. */
    fun candidateTrips(trips: List<TripDTO>, now: Instant): List<TripDTO> =
        trips.filter { TripRules.offerable(it, now) }.sortedBy { OrderRules.parseInstant(it.plannedStartAt) ?: Instant.MAX }

    /**
     * Web `proposalPickupWindow` (ADR-0028): every request ends at points, so the client's own window is offered and
     * the server checks the trip's position along the road; null without a trip or a readable window.
     */
    fun pickupWindow(trip: TripDTO?, listing: ListingPublicDTO): PickupWindow? {
        trip ?: return null
        val askedFrom = OrderRules.parseInstant(listing.departureWindowStart) ?: return null
        val askedTo = OrderRules.parseInstant(listing.departureWindowEnd) ?: return null
        return PickupWindow(askedFrom, askedTo)
    }

    /**
     * The trip to start with: the first candidate that runs while the client's window is open. Null = let the
     * driver choose.
     */
    fun preselect(candidates: List<TripDTO>, listing: ListingPublicDTO): TripDTO? {
        val from = OrderRules.parseInstant(listing.departureWindowStart)
        val to = OrderRules.parseInstant(listing.departureWindowEnd)
        return candidates.firstOrNull { trip ->
            val start = OrderRules.parseInstant(trip.plannedStartAt)
            val end = OrderRules.parseInstant(trip.plannedEndAt)
            from != null && to != null && start != null && end != null && !start.isAfter(to) && !end.isBefore(from)
        }
    }

    private fun iso(instant: Instant): String =
        instant.atZone(ParcelRules.TASHKENT).toOffsetDateTime().format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)

    /**
     * `POST /listings/{id}/proposals`: the trip, the window, the request's quantity and price basis, the price. No
     * place ids (ADR-0028): the places come from the listing.
     */
    fun proposalBody(listing: ListingPublicDTO, tripId: String, window: PickupWindow, unitPriceMinor: Long, message: String? = null): ProposalCreate {
        return ProposalCreate(
            message = message?.trim()?.takeIf { it.isNotEmpty() },
            pickupWindowEnd = iso(window.end),
            pickupWindowStart = iso(window.start),
            priceBasis = listing.priceBasis,
            quantity = listing.quantity,
            tripId = tripId,
            unitPriceMinor = unitPriceMinor,
        )
    }

    /** The price field's start: the client's own unit price, in whole so'm. */
    fun prefillPrice(listing: ListingPublicDTO): String = ParcelRules.minorToSoum(listing.unitPriceMinor).toString()

    /** The board: cheapest first (ties keep the server order); the driver's own row is marked, not hidden. */
    fun board(offers: List<ListingOfferDTO>): BoardSummary {
        val rows = offers.sortedBy { it.totalMinor }
        return BoardSummary(count = offers.size, cheapestMinor = rows.firstOrNull()?.totalMinor, mine = offers.firstOrNull { it.isMine }, rows = rows)
    }

    /** `15` / `8,5` (bps → percent, no trailing zero). */
    fun percent(bps: Long): String {
        val whole = bps / 100
        val rest = bps % 100
        if (rest == 0L) return whole.toString()
        return "$whole,${rest.toString().padStart(2, '0').trimEnd('0')}"
    }

    /** The price band warning (Q90): advice after the offer went out, never a block. */
    fun priceWarning(warnings: List<ApiWarning>): ApiWarning? = warnings.firstOrNull { it.code == PRICE_OUTSIDE_REFERENCE }

    /** `floor_minor` / `ceiling_minor` of the band warning. */
    fun band(warning: ApiWarning): Pair<Long?, Long?> {
        val details = warning.details as? JsonObject ?: return null to null
        fun long(key: String) = (details[key] as? JsonPrimitive)?.longOrNull
        return long("floor_minor") to long("ceiling_minor")
    }

    /** `INVALID_STATE_TRANSITION {reason: open_thread_exists, thread_id}`: this driver already has an offer here. */
    fun openThreadId(error: Throwable): String? {
        val api = error as? ApiException ?: return null
        if (api.code != "INVALID_STATE_TRANSITION") return null
        val details = api.details as? JsonObject ?: return null
        if ((details["reason"] as? JsonPrimitive)?.contentOrNull != "open_thread_exists") return null
        return (details["thread_id"] as? JsonPrimitive)?.contentOrNull
    }

    /** Offer-screen refusals the generic `error.<CODE>` does not say well. */
    fun errorKey(error: Throwable): String? = when ((error as? ApiException)?.code) {
        "TIME_WINDOW_CONFLICT" -> "driverBid.tripWindowMismatch"
        "PROPOSAL_CHANGED" -> "client.listingBids.termsChanged"
        else -> null
    }

    // -- my offers -----------------------------------------------------------------------------------------------

    /** The driver's moves on a thread (web `auction.ts`, seen from the driver side). */
    fun actions(thread: ProposalThreadDTO, now: Instant): NegotiationActions = OrderRules.negotiationActions(thread, now, ActorSide.DRIVER)

    fun revisionsLeft(thread: ProposalThreadDTO): Long = thread.currentVersion?.priceRevisionsLeft?.driver ?: 0

    fun line(thread: ProposalThreadDTO, now: Instant): ThreadLine {
        if (thread.state == OrderRules.STATE_ACCEPTED || thread.bookingId != null) return ThreadLine.Accepted
        val a = actions(thread, now)
        if (!a.open) return ThreadLine.Closed(OrderRules.closedStatusKey(thread, now))
        return if (a.theirTurn) ThreadLine.Countered else ThreadLine.Waiting
    }

    /** Seconds until the current version expires; null on a closed thread. */
    fun secondsLeft(thread: ProposalThreadDTO, now: Instant): Long? {
        if (!actions(thread, now).open) return null
        return thread.currentVersion?.let { OrderRules.secondsLeft(it, now) }
    }

    /** "1 soat 12 daqiqa" parts, rounded up to whole minutes. */
    fun expiryParts(seconds: Long): Pair<Long, Long> = OrderRules.countdownParts(seconds)

    /** "Chilonzor → Registon" of a thread: the latest version's pickup and drop-off (district of the point). */
    fun routeTitle(thread: ProposalThreadDTO, ru: Boolean): String {
        val v = thread.currentVersion ?: thread.versions?.lastOrNull() ?: return "?"
        return "${FeedRules.endName(v.pickupPoint, ru)} → ${FeedRules.endName(v.dropoffPoint, ru)}"
    }

    /** Versions oldest first, for the history. */
    fun history(thread: ProposalThreadDTO): List<ProposalVersionDTO> = (thread.versions ?: listOfNotNull(thread.currentVersion)).sortedBy { it.revision }

    /** The money block's numbers, only for a driver view promo quote (off in dev). */
    fun driverPromo(version: ProposalVersionDTO?): ProposalPromoDriverDTO? = version?.promoQuote as? ProposalPromoDriverDTO

    /** `POST /proposals/{id}/counter`: a new price on the same window, against the current revision. */
    fun counterBody(version: ProposalVersionDTO, unitPriceMinor: Long): ProposalCounter = ProposalCounter(
        expectedRevision = version.revision,
        pickupWindowEnd = version.pickupWindowEnd,
        pickupWindowStart = version.pickupWindowStart,
        unitPriceMinor = unitPriceMinor,
    )

    /**
     * `POST /proposals/{id}/accept` against the listing terms version the thread shows (Q54,
     * `ProposalThreadDTO.listing_terms_version`). A driver ack goes with a promo quote when there is one.
     */
    fun acceptBody(thread: ProposalThreadDTO, version: ProposalVersionDTO): AcceptRequest {
        val promo = driverPromo(version)
        return AcceptRequest(
            expectedListingTermsVersion = thread.listingTermsVersion,
            promoDriverAck = promo?.let { PromoDriverAckInput(cashToCollectMinor = it.cashToCollectMinor, commissionChargedMinor = it.commissionChargedMinor) },
            proposalVersionId = version.id,
        )
    }

    /** `CAPACITY_UNAVAILABLE`: the trip has fewer free seats (or less room) than the request needs. */
    fun capacityShort(error: Throwable?): Boolean = (error as? ApiException)?.code == "CAPACITY_UNAVAILABLE"

    /** `409 PROPOSAL_CHANGED`: the terms moved under the driver - read the thread again and ask to confirm again. */
    fun termsChanged(error: Throwable): Boolean = (error as? ApiException)?.code == "PROPOSAL_CHANGED"

    /** The booking an accept created (`BookingDTO.id`); the body is a union, read loosely. */
    fun bookingId(body: JsonElement?): String? = ((body as? JsonObject)?.get("id") as? JsonPrimitive)?.contentOrNull

    /** After these the thread on screen is stale: read it again. */
    fun needsRefresh(error: Throwable): Boolean =
        (error as? ApiException)?.code in setOf("VERSION_CONFLICT", "PROPOSAL_CHANGED", "PROPOSAL_EXPIRED", "INVALID_STATE_TRANSITION")

    const val PRICE_OUTSIDE_REFERENCE = "PRICE_OUTSIDE_REFERENCE"
}
