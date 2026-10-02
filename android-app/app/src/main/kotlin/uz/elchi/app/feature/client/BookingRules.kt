package uz.elchi.app.feature.client

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.longOrNull
import uz.elchi.app.api.BookingClientDTO
import uz.elchi.app.api.BookingContactDTO
import uz.elchi.app.api.BookingDriverDTO
import uz.elchi.app.api.BookingNoShowReviewDTO
import uz.elchi.app.api.BookingVehicleDTO
import uz.elchi.app.api.generated.AmendmentDTO
import uz.elchi.app.api.generated.ChatMessageDTO
import uz.elchi.app.api.generated.ReputationDTO
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.api.generated.SupportMessageDTO
import uz.elchi.app.api.generated.TrackingFreshness
import uz.elchi.app.api.generated.TrackingLastPointDTO
import java.time.Duration
import java.time.Instant
import java.util.Locale

/** A step of the parcel status ladder on the tracking screen. */
enum class LadderStep(val key: String) {
    CONFIRMED("status.confirmed"),
    PREPARING("parcel.progress.tripPreparing"),
    DEPARTED("parcel.status.driverDeparted"),
    DELIVERED("parcel.progress.deliveredByOperator"),
    COMPLETED("app.progress.completed"),
}

enum class StepState { DONE, CURRENT, TODO }

/**
 * One rung: its state and, only where the booking really carries it, when it happened. [key] is the rung's words:
 * the parcel's by default, the passenger's own for Taksi (Mashinada, Yetib keldi).
 */
data class LadderItem(val step: LadderStep, val state: StepState, val at: String? = null, val key: String = step.key)

/** The plate as the client may see it now (Q64): the full number, or the masked one with "opens 30 min before". */
data class PlateView(val text: String, val full: Boolean)

/** The driver's phone (Q44/Q142): the number only while the server shows it; otherwise nothing to dial. */
data class PhoneView(val number: String?) {
    val visible: Boolean get() = number != null
}

/** The driver's reputation line: a real average with its counts, or "new, not rated yet" (never an invented 4.5). */
sealed interface ReputationLine {
    data class Rated(val average: String, val count: Long, val bookings: Long) : ReputationLine
    data object Unrated : ReputationLine
}

/** What the client may do with one amendment now. */
data class AmendmentActions(val open: Boolean, val canAccept: Boolean, val canReject: Boolean, val canWithdraw: Boolean)

/** A chat message this phone is still sending (or failed to send): same key on retry, so it can never double. */
data class OutgoingMessage(
    val localId: String,
    val text: String?,
    val quickReply: String?,
    val idempotencyKey: String,
    val failed: Boolean = false,
    val error: Throwable? = null,
)

/**
 * Pure rules of the booking screens (Stage 04): no Android, no network - unit-tested. The booking DTO has no
 * actions field, so what the client may do follows from `service_status` here, mirroring the server's state machine
 * (`mobile-app/src/app/bookingControls.ts`), with one deliberate difference: an amendment is offered only in
 * `confirmed` (the server refuses it once the trip is boarding; the web client offers it in `awaiting_pickup` too).
 */
object BookingRules {
    /** `PARCEL_BOOKING.cancel` leaves only these; after departure it is the return flow or support, not a cancel. */
    private val CANCELLABLE = setOf("confirmed", "awaiting_pickup")

    /** Live-location links make sense until the parcel is delivered or the booking is closed. */
    private val SHAREABLE = setOf("confirmed", "awaiting_pickup", "picked_up", "in_transit", "return_required")

    /** No further service state follows these (chat still reads, support still works). */
    val TERMINAL = setOf("completed", "cancelled", "no_show", "returned", "delivery_failed")

    /** The client's cancel reasons (`BookingCancel.reason_code`); `other` last so the list never forces a wrong one. */
    val CLIENT_CANCEL_REASONS = listOf("plans_changed", "found_other_option", "driver_unreachable", "other")

    /** Reason codes the dictionary has words for (`bookingCancel.reason.<code>`): both sides' own codes. */
    private val KNOWN_CANCEL_REASONS = setOf(
        "plans_changed", "found_other_option", "driver_unreachable", "other", "trip_changed", "vehicle_problem", "client_unreachable",
    )

    // -- availability ---------------------------------------------------------------------------------------------

    /** Q7/Q19: while a reported no-show waits for the operator only the operator may cancel. */
    fun canCancel(status: String, review: BookingNoShowReviewDTO? = null): Boolean = status in CANCELLABLE && !reviewPending(review)

    fun reviewPending(review: BookingNoShowReviewDTO?): Boolean = review?.status == "pending"

    /** Only before boarding: the server can never accept an amendment on a boarding trip. */
    fun canAmend(status: String): Boolean = status == "confirmed"

    /** S1: only a completed booking is rated (the 7-day window is the server's to check). */
    fun canRate(status: String): Boolean = status == "completed"

    fun canShareTracking(status: String): Boolean = status in SHAREABLE

    fun isTerminal(status: String): Boolean = status in TERMINAL

    // -- words for codes ------------------------------------------------------------------------------------------

    /** `bookingCancel.reason.<code>`, or null for a code the app has no words for (never shown raw). */
    fun cancelReasonKey(code: String?): String? = code?.takeIf { it in KNOWN_CANCEL_REASONS }?.let { "bookingCancel.reason.$it" }

    /** Why the server refused a cancel, as a dictionary key; null = the generic error sentence is right. */
    fun cancelRefusalKey(code: String?): String? = when (code) {
        "NO_SHOW_REVIEW_PENDING" -> "bookingCancel.refused.noShowPending"
        "CUSTODY_REQUIRES_RETURN_FLOW" -> "bookingCancel.refused.custody"
        // bookingCancel.refused.tooLate still says "nizo oching" - disputes are the support chat now (Q141).
        "INVALID_STATE_TRANSITION" -> "client.bookingCancel.tooLate"
        "VERSION_CONFLICT" -> "bookingCancel.refused.changed"
        else -> null
    }

    /** Who cancelled: the client is "Siz", the others by role. */
    fun bySideKey(side: String?): String? = when (side) {
        "client" -> "client.bookingDetail.bySideClient"
        "driver" -> "safety.driverTitle"
        "operator" -> "support.operator"
        "system" -> "client.bookingDetail.bySideSystem"
        else -> null
    }

    /** An amendment's word (`status.<status>`); "accepted" has its own - `status.accepted` means "driver chosen". */
    fun amendmentStatusKey(status: String): String = if (status == "accepted") "client.amendment.statusAccepted" else "status.$status"

    /** Waiting for an answer amber, in force green, refused red, taken back or lapsed grey. */
    fun amendmentTone(status: String): uz.elchi.app.ui.theme.Tone = when (status) {
        "proposed" -> uz.elchi.app.ui.theme.Tone.WARN
        "accepted" -> uz.elchi.app.ui.theme.Tone.OK
        "rejected" -> uz.elchi.app.ui.theme.Tone.ERR
        else -> uz.elchi.app.ui.theme.Tone.GRAY
    }

    /** `AMENDMENT_CONFLICT` reasons the client can act on; null = the generic sentence. */
    fun amendmentConflictKey(reason: String?): String? = when (reason) {
        "amendment_open" -> "client.amendment.openExists"
        "trip_not_planned" -> "client.amendment.conflict.tripNotPlanned"
        "booking_changed" -> "client.amendment.conflict.bookingChanged"
        "amendment_expired" -> "client.amendment.conflict.expired"
        else -> null
    }

    fun detailsReason(details: JsonElement?): String? = ((details as? JsonObject)?.get("reason") as? JsonPrimitive)?.contentOrNull

    fun detailsString(details: JsonElement?, key: String): String? = ((details as? JsonObject)?.get(key) as? JsonPrimitive)?.contentOrNull

    /** `RATE_LIMITED.details.retry_after_s`, at least one second; null when the server did not say. */
    fun retryAfterSeconds(details: JsonElement?): Long? =
        ((details as? JsonObject)?.get("retry_after_s") as? JsonPrimitive)?.let { it.longOrNull ?: it.contentOrNull?.toDoubleOrNull()?.let { d -> kotlin.math.ceil(d).toLong() } }
            ?.coerceAtLeast(1)

    // -- status ladder --------------------------------------------------------------------------------------------

    /** Taksi's rungs, in the ladder's five places: confirmed → awaited → in the car → arrived → completed. */
    private val PASSENGER_LADDER = listOf("status.confirmed", "status.awaiting_pickup", "status.onboard", "status.arrived", "app.progress.completed")

    /** Where a status sits on the ladder; null = off the ladder (cancelled, no-show, the parcel's return statuses). */
    fun ladderIndex(status: String, serviceType: ServiceType = ServiceType.PARCEL): Int? = if (serviceType == ServiceType.PASSENGER) {
        when (status) {
            "confirmed" -> 0
            "awaiting_pickup" -> 1
            "onboard" -> 2
            "arrived" -> 3
            "completed" -> 4
            else -> null
        }
    } else when (status) {
        "confirmed" -> 0
        "awaiting_pickup" -> 1
        // The system only knows that the trip departed, not that the parcel was handed over (Q139/Q142).
        "picked_up", "in_transit" -> 2
        "delivered" -> 3
        "completed" -> 4
        else -> null
    }

    /**
     * The ladder from the booking's own status. Times only where the DTO carries them: the booking's creation for
     * "Tasdiqlandi", the phones' opening (= the departure, Q142) for "yo'lga chiqdi". Off-ladder statuses leave every
     * rung that did not surely happen as to-do; the screen names the status separately.
     */
    fun ladder(booking: BookingClientDTO): List<LadderItem> {
        val passenger = booking.serviceType == ServiceType.PASSENGER
        val current = ladderIndex(booking.serviceStatus, booking.serviceType)
        return LadderStep.entries.mapIndexed { i, step ->
            val state = when {
                current == null -> if (i == 0) StepState.DONE else StepState.TODO
                // The last rung reached is done, not "in progress": nothing follows a completed booking.
                i < current || (i == current && step == LadderStep.COMPLETED) -> StepState.DONE
                i == current -> StepState.CURRENT
                else -> StepState.TODO
            }
            val at = when (step) {
                LadderStep.CONFIRMED -> booking.createdAt
                LadderStep.DEPARTED -> booking.contact?.visibleFrom?.takeIf { state != StepState.TODO }
                else -> null
            }
            LadderItem(step, state, at, key = if (passenger) PASSENGER_LADDER[i] else step.key)
        }
    }

    // -- driver card ----------------------------------------------------------------------------------------------

    fun plate(vehicle: BookingVehicleDTO): PlateView =
        vehicle.plateNumber?.takeIf { it.isNotBlank() }?.let { PlateView(it, full = true) } ?: PlateView(vehicle.plateMasked, full = false)

    /** The number only when the server both says phones are visible and sends one. */
    fun phone(driver: BookingDriverDTO?, contact: BookingContactDTO?): PhoneView =
        PhoneView(driver?.contactPhone?.takeIf { contact?.phonesVisible == true && it.isNotBlank() })

    /** `tel:` target for the dialer: digits and a leading plus only. */
    fun dialUri(phone: String): String = "tel:" + phone.filter { it.isDigit() || it == '+' }

    fun reputation(dto: ReputationDTO?, locale: Locale): ReputationLine {
        val average = dto?.averageRating
        if (dto == null || average == null || dto.ratingCount <= 0) return ReputationLine.Unrated
        return ReputationLine.Rated(formatRating(average, locale), dto.ratingCount, dto.completedBookings)
    }

    /** `4,7` in both app languages (the decimal comma of uz and ru). */
    fun formatRating(value: Double, locale: Locale): String = String.format(locale, "%.1f", value).replace('.', ',')

    // -- tracking -------------------------------------------------------------------------------------------------

    /** The share chips, in minutes (Q83: 15 min .. 24 h). */
    val GRANT_TTL_MINUTES = listOf(15, 60, 180, 360, 720, 1440)
    const val GRANT_TTL_DEFAULT = 60

    fun grantTtlMinutes(choice: Int): Long = choice.toLong().coerceIn(15, 1440)

    /** A grant's `url` may come relative ("/t/...") - resolved against the API's origin. */
    fun absoluteUrl(apiBase: String, url: String): String {
        if (url.startsWith("http://") || url.startsWith("https://")) return url
        val origin = Regex("^(https?://[^/]+)").find(apiBase)?.groupValues?.get(1) ?: return url
        return origin + (if (url.startsWith("/")) url else "/$url")
    }

    private fun rank(freshness: TrackingFreshness): Int = when (freshness) {
        TrackingFreshness.FRESH -> 0
        TrackingFreshness.DELAYED -> 1
        TrackingFreshness.LOST -> 2
        TrackingFreshness.NO_DATA -> 3
        TrackingFreshness.UNKNOWN -> -1
    }

    /** The bucket the point's age alone earns on this phone's clock (spec §10.5: 30 s / 120 s). */
    fun localFreshness(capturedAt: Instant, now: Instant): TrackingFreshness {
        val age = Duration.between(capturedAt, now).seconds.coerceAtLeast(0)
        return when {
            age <= FRESH_MAX_S -> TrackingFreshness.FRESH
            age <= DELAYED_MAX_S -> TrackingFreshness.DELAYED
            else -> TrackingFreshness.LOST
        }
    }

    /**
     * What the screen may claim: the server's bucket, re-aged on this phone's clock between pushes - and only ever
     * made WORSE by that (a skewed phone clock must not turn a lost signal "live"). No point = no data.
     */
    fun effectiveFreshness(server: TrackingFreshness, point: TrackingLastPointDTO?, now: Instant): TrackingFreshness {
        if (point == null) return TrackingFreshness.NO_DATA
        val captured = OrderRules.parseInstant(point.capturedAt) ?: return if (server == TrackingFreshness.UNKNOWN) TrackingFreshness.LOST else server
        val local = localFreshness(captured, now)
        if (server == TrackingFreshness.UNKNOWN) return local
        return if (rank(local) > rank(server)) local else server
    }

    const val FRESH_MAX_S = 30L
    const val DELAYED_MAX_S = 120L

    // -- chat -----------------------------------------------------------------------------------------------------

    /**
     * The chat as one list, oldest first: pages and polls arrive newest first and overlap, so messages are merged by
     * id (the newer copy wins - moderation may have hidden one since) and ordered by time, then id.
     */
    fun mergeMessages(existing: List<ChatMessageDTO>, incoming: List<ChatMessageDTO>): List<ChatMessageDTO> {
        val byId = LinkedHashMap<String, ChatMessageDTO>()
        existing.forEach { byId[it.id] = it }
        incoming.forEach { byId[it.id] = it }
        return byId.values.sortedWith(compareBy<ChatMessageDTO> { OrderRules.parseInstant(it.createdAt) ?: Instant.MIN }.thenBy { it.id })
    }

    /** Messages in [after] that [before] did not have and that someone else wrote (the "Yangi xabar" pill). */
    fun newFromOthers(before: List<ChatMessageDTO>, after: List<ChatMessageDTO>): Int {
        val known = before.mapTo(HashSet()) { it.id }
        return after.count { it.id !in known && !it.isMine }
    }

    /** Support thread messages oldest first (the DTO already sends them so; staff-only notes never reach a user). */
    fun supportMessages(messages: List<SupportMessageDTO>?): List<SupportMessageDTO> =
        messages.orEmpty().filter { it.staffOnly != true }.sortedWith(compareBy<SupportMessageDTO> { OrderRules.parseInstant(it.createdAt) ?: Instant.MIN }.thenBy { it.id })

    /** `support.status.<staff_status>` (waiting / assigned / answered / closed). */
    fun supportStatusKey(staffStatus: String): String = "support.status.$staffStatus"

    // -- amendments -----------------------------------------------------------------------------------------------

    /**
     * Only a `proposed` amendment inside its 2 h, on a booking that is still `confirmed`, is live: the server keeps a
     * driver's proposal `proposed` after the trip boarded but can never accept it then. The counterparty answers
     * (accept / reject), the author withdraws - the same turn rule as offers.
     */
    fun amendmentActions(amendment: AmendmentDTO, bookingStatus: String, now: Instant, mySide: String = "client"): AmendmentActions {
        val expires = OrderRules.parseInstant(amendment.expiresAt)
        val open = amendment.status == "proposed" && (expires == null || now.isBefore(expires)) && canAmend(bookingStatus)
        val mine = amendment.authorSide == mySide
        return AmendmentActions(open = open, canAccept = open && !mine, canReject = open && !mine, canWithdraw = open && mine)
    }

    /** One open amendment at a time (server rule): while one is live the form is replaced by a note. */
    fun hasOpenAmendment(amendments: List<AmendmentDTO>, bookingStatus: String, now: Instant): Boolean =
        amendments.any { amendmentActions(it, bookingStatus, now).open }

    /** A proposed amendment whose time ran out reads "expired" before the server's sweep does. */
    fun amendmentDisplayStatus(amendment: AmendmentDTO, now: Instant): String {
        val expires = OrderRules.parseInstant(amendment.expiresAt)
        return if (amendment.status == "proposed" && expires != null && !now.isBefore(expires)) "expired" else amendment.status
    }

    /** A price the amendment may send: positive whole so'm that differs from the agreed one. */
    fun amendmentPrice(digits: String, currentUnitMinor: Long): Long? = ParcelRules.soumToMinor(digits)?.takeIf { it != currentUnitMinor }
}
