package uz.elchi.app.feature.driver

import uz.elchi.app.api.BookingNoShowReviewDTO
import uz.elchi.app.api.DriverBookingDTO
import uz.elchi.app.api.generated.AmendmentDTO
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.feature.client.BookingRules
import uz.elchi.app.feature.client.BookingSide
import uz.elchi.app.feature.client.BookingViewModel
import uz.elchi.app.feature.client.OrderRules
import uz.elchi.app.feature.client.TaxiRules
import uz.elchi.app.gps.TrackerSnapshot
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Tone
import java.time.Duration
import java.time.Instant

/** The receiver line (Q44/Q142): the name and phone once the trip departed, else when it opens. Never the sender's. */
sealed interface ReceiverView {
    data class Visible(val name: String?, val phone: String) : ReceiverView
    data class Hidden(val visibleFrom: String?) : ReceiverView
}

/** The map hero's pill (design 08 2.1): from this phone's own tracker, never a server claim (§9/Q148). */
enum class HeroChip { LIVE, GPS_OFF, TRACKING }

/** The driver's newest own price proposal, as the detail says it (design 08 7.4). */
sealed interface DriverAmendNotice {
    data class Pending(val amendment: AmendmentDTO) : DriverAmendNotice
    data class Accepted(val amendment: AmendmentDTO) : DriverAmendNotice
}

/**
 * The reason the driver typed for its last price proposal, per booking, kept on this phone only: `AmendmentDTO`
 * carries no reason (BLOCKED), so the detail can say it only for a proposal sent from here (design 08 7.4).
 */
object DriverAmendReasons {
    private val sent = java.util.concurrent.ConcurrentHashMap<String, String>()
    private val typed = java.util.concurrent.ConcurrentHashMap<String, String>()

    /** The form's text as it changes; [justSent] = the server took the proposal (the form was then cleared). */
    fun observe(bookingId: String, reason: String, justSent: Boolean) {
        if (reason.isNotBlank()) typed[bookingId] = reason.trim()
        if (justSent) typed.remove(bookingId)?.let { sent[bookingId] = it }
    }

    fun sent(bookingId: String): String? = sent[bookingId]

    fun clear() {
        sent.clear()
        typed.clear()
    }
}

/** The contact bar's call button (design 08 2.8; Q44/Q142): a number to dial, or why there is none yet. */
sealed interface ClientCall {
    data class Open(val phone: String) : ClientCall

    /** Taksi: the client's phone opens once the passenger boarded (`driver.trip.phoneAfterBoard`). */
    data object AfterBoard : ClientCall

    /** Pochta: the receiver's phone opens at the trip's departure (`client.booking.callLockedParcel`). */
    data object AtDeparture : ClientCall

    /** The booking is over: the phones are hidden again (`client.booking.callClosed`). */
    data object Closed : ClientCall
}

/** What the driver may do with a parcel booking now (passenger is off: no boarding code, cash receipt or no-show). */
data class DriverBookingActions(
    val arrive: Boolean,
    val amend: Boolean,
    val cancel: Boolean,
    val rate: Boolean,
    /** "Haydovchi yo'lga chiqdi. … operator qayd etadi" (Q139/Q143/Q144). */
    val transitNote: Boolean,
)

/**
 * Pure rules of the driver's booking screens (Stage 09): no Android, no network - unit-tested. The DTO has no actions
 * field: what the driver may do follows from `service_status`, the server's state machine (parcel: delivered and
 * completed are recorded by an operator, Q139/Q144).
 */
object DriverBookingRules {
    /** Server `PRE_SERVICE_STATUSES`: "Keldim" is a signal before the service starts (recorded once). */
    private val ARRIVE = BookingViewModel.ARRIVE_STATUSES

    /** The trip runs (boarding / on the way): the booking screens show the GPS bar. */
    private val TRIP_RUNNING = setOf("awaiting_pickup", "picked_up", "in_transit", "onboard")

    private val IN_TRANSIT = setOf("picked_up", "in_transit")

    /** The S1 rating window after completion (the server is the judge; this only hides a dead button). */
    val RATING_WINDOW: Duration = Duration.ofDays(7)

    val CANCEL_REASONS: List<String> get() = BookingViewModel.DRIVER_CANCEL_REASONS

    /**
     * The badge (web `bookingBadgeLabel`, CA:578): a parcel "in transit" only means the trip departed (Q142), a
     * "delivered" was recorded by an operator; everything else is `status.<status>`.
     */
    fun badgeKey(serviceType: ServiceType, status: String, short: Boolean = false, review: BookingNoShowReviewDTO? = null): String = when {
        // Q7: only the operator sets `no_show`; while it reviews the driver's report the badge says so (design 08 1.7).
        status == "awaiting_pickup" && BookingRules.reviewPending(review) -> NO_SHOW_REVIEW_KEY
        // The list says it short ("Yo'lda" / "Yetkazildi"), the detail in full (design 08 1.6).
        short && serviceType == ServiceType.PARCEL && status in IN_TRANSIT -> "status.in_transit"
        short && serviceType == ServiceType.PARCEL && status == "delivered" -> "status.delivered"
        serviceType == ServiceType.PARCEL && status in IN_TRANSIT -> "parcel.status.driverDeparted"
        serviceType == ServiceType.PARCEL && status == "delivered" -> "parcel.progress.deliveredByOperator"
        else -> "status.$status"
    }

    const val NO_SHOW_REVIEW_KEY = "driver.v3bkg.noShowReviewBadge"

    fun badgeTone(serviceType: ServiceType, status: String, review: BookingNoShowReviewDTO? = null): Tone =
        if (status == "awaiting_pickup" && BookingRules.reviewPending(review)) Tone.ERR else OrderRules.bookingTone(serviceType, status)

    /** The list row's icon: a package for Pochta, a pin for Taksi (design 08 1.3, as the client's orders). */
    fun rowIcon(serviceType: ServiceType): ElchiIcon = if (serviceType == ServiceType.PARCEL) ElchiIcon.PKG else ElchiIcon.PIN

    /** Taksi without a discount shows the per-seat basis "2 × 150 000 so'm"; otherwise the total (design 08 1.5). */
    fun seatsPriced(booking: DriverBookingDTO): Boolean = TaxiRules.isPassenger(booking.serviceType) && booking.promo == null

    /** Finished rows are drawn quieter (design 08 1.9). */
    fun dimmed(status: String): Boolean = BookingRules.isTerminal(status)

    /** The service is under way: the passenger in the car, or the parcel on the road (the GPS should be sending). */
    fun serviceLive(status: String): Boolean = status in LIVE

    private val LIVE = setOf("onboard", "picked_up", "in_transit")

    /** This phone is publishing the booking's trip (starting counts: it is being switched on, not off). */
    fun trackerOn(snapshot: TrackerSnapshot, tripId: String?): Boolean = tripId != null && snapshot.running && snapshot.tripId == tripId

    fun heroChip(status: String, tripId: String?, snapshot: TrackerSnapshot): HeroChip = when {
        !serviceLive(status) || tripId == null -> HeroChip.TRACKING
        trackerOn(snapshot, tripId) -> HeroChip.LIVE
        else -> HeroChip.GPS_OFF
    }

    /** "Joylashuv yuborilmayapti …" (design 08 3.7): the service runs and this phone is not sending its trip. */
    fun gpsOffWarn(status: String, tripId: String?, snapshot: TrackerSnapshot): Boolean = heroChip(status, tripId, snapshot) == HeroChip.GPS_OFF

    /** "Manzilga yetildi. Naqd to'lovni qayd qiling…" - Taksi only (Q139: no parcel cash, design 08 3.5/4.5). */
    fun arrivedNote(serviceType: ServiceType, status: String): Boolean = TaxiRules.isPassenger(serviceType) && status == "arrived"

    /**
     * Design 08 7.4: the newest proposal the driver made - still open ("…mijoz javobi kutilmoqda", the amend button
     * hidden) or accepted ("Mijoz yangi narxni qabul qildi"). Rejected, withdrawn and expired ones say nothing here.
     */
    fun amendNotice(amendments: List<AmendmentDTO>, bookingStatus: String, now: Instant): DriverAmendNotice? {
        val mine = amendments.filter { it.authorSide == BookingSide.DRIVER.wire }
            .maxByOrNull { OrderRules.parseInstant(it.expiresAt) ?: Instant.MIN } ?: return null
        return when (BookingRules.amendmentDisplayStatus(mine, now)) {
            "proposed" -> DriverAmendNotice.Pending(mine).takeIf { BookingRules.canAmend(bookingStatus) }
            "accepted" -> DriverAmendNotice.Accepted(mine).takeIf { !BookingRules.isTerminal(bookingStatus) }
            else -> null
        }
    }

    /**
     * The proposal sentence without its reason: `AmendmentDTO` carries no reason (BLOCKED), so the "· Sabab: {reason}"
     * part is cut where the [marker] stood in for it.
     */
    fun dropReason(text: String, marker: String): String =
        if (marker !in text) text else text.replace(Regex("\\s*·[^·—]*?" + Regex.escape(marker)), "").replace(marker, "")

    /** Who the bar's call button rings: the client after boarding (Taksi), the receiver after departure (Pochta). */
    fun clientCall(booking: DriverBookingDTO): ClientCall {
        if (BookingRules.isTerminal(booking.serviceStatus)) return ClientCall.Closed
        return if (TaxiRules.isPassenger(booking.serviceType)) {
            val phone = booking.client?.contactPhone?.takeIf { it.isNotBlank() && booking.contact?.phonesVisible != false }
            phone?.let { ClientCall.Open(it) } ?: ClientCall.AfterBoard
        } else {
            (receiver(booking) as? ReceiverView.Visible)?.let { ClientCall.Open(it.phone) } ?: ClientCall.AtDeparture
        }
    }

    /** Design 08 11.2: background sending is said only while the location service really runs. */
    fun trackingNoteKey(snapshot: TrackerSnapshot): String = if (snapshot.backgroundActive) "driver.gps.backgroundOn" else "driverTracking.foregroundOnly"

    /** Q103: on a discounted booking the driver collects the promo's cash, otherwise the agreed total. */
    fun cashToCollectMinor(booking: DriverBookingDTO): Long = booking.promo?.cashToCollectMinor ?: booking.totalMinor

    /** What the balance is charged (Q103: the driver may see it): the promo's charged commission, else the fee. */
    fun commissionMinor(booking: DriverBookingDTO): Long? = booking.promo?.commissionChargedMinor ?: booking.fee?.commissionMinor

    /** `fee_bps` as a percent without trailing zeros (`1500` -> "15", `1250` -> "12.5"). */
    fun percent(bps: Long): String = if (bps % 100 == 0L) (bps / 100).toString() else (bps / 100.0).toString()

    /** The number only when the server sends one (after departure); the server is the authority (Q44/Q142). */
    fun receiver(booking: DriverBookingDTO): ReceiverView {
        val contacts = booking.parcelContacts
        val phone = contacts?.receiverPhone?.takeIf { it.isNotBlank() }
        return if (phone != null) ReceiverView.Visible(contacts.receiverName?.trim()?.takeIf { it.isNotEmpty() }, phone) else ReceiverView.Hidden(booking.contact?.visibleFrom)
    }

    fun canArrive(status: String, arrivedAt: String?): Boolean = status in ARRIVE && arrivedAt == null

    /** Within the rating window after the booking's last change (the completion). */
    fun ratingOpen(status: String, updatedAt: String?, now: Instant): Boolean {
        if (!BookingRules.canRate(status)) return false
        val done = OrderRules.parseInstant(updatedAt) ?: return true
        return now.isBefore(done.plus(RATING_WINDOW))
    }

    fun actions(status: String, arrivedAt: String?, updatedAt: String?, now: Instant, review: BookingNoShowReviewDTO? = null): DriverBookingActions = DriverBookingActions(
        arrive = canArrive(status, arrivedAt),
        amend = BookingRules.canAmend(status),
        // Q7/Q19: while the driver's "Mijoz kelmadi" waits for the operator only the operator may cancel.
        cancel = BookingRules.canCancel(status, review),
        rate = ratingOpen(status, updatedAt, now),
        transitNote = status in IN_TRANSIT,
    )

    /** The trip id the GPS bar is about, while the booking's trip runs. */
    fun gpsTripId(status: String, tripId: String?): String? = tripId?.takeIf { status in TRIP_RUNNING }

    /** Why the server refused a driver's cancel, as a dictionary key; null = the generic error sentence. */
    fun cancelRefusalKey(code: String?): String? = BookingRules.cancelRefusalKey(code)

    fun isActive(status: String): Boolean = !BookingRules.isTerminal(status)

    /**
     * Running trips first, then upcoming pickups (soonest first), then live bookings whose pickup window is long
     * past (latest first), then the history (latest first).
     */
    fun ordered(bookings: List<DriverBookingDTO>, now: Instant = Instant.now()): List<DriverBookingDTO> {
        val (live, done) = bookings.partition { isActive(it.serviceStatus) }
        fun pickup(b: DriverBookingDTO) = OrderRules.parseInstant(b.pickup.windowStart ?: b.createdAt) ?: Instant.MAX
        fun windowEnd(b: DriverBookingDTO) = OrderRules.parseInstant(b.pickup.windowEnd ?: b.pickup.windowStart ?: b.createdAt)
        val (running, waiting) = live.partition { it.serviceStatus in TRIP_RUNNING }
        val (overdue, upcoming) = waiting.partition { windowEnd(it)?.isBefore(now.minus(OVERDUE_AFTER)) == true }
        return running.sortedBy(::pickup) + upcoming.sortedBy(::pickup) + overdue.sortedByDescending(::pickup) +
            done.sortedByDescending { OrderRules.parseInstant(it.updatedAt ?: it.createdAt) ?: Instant.MIN }
    }

    /** A pickup window this long gone sorts after the upcoming ones (the trip never ran). */
    private val OVERDUE_AFTER: Duration = Duration.ofHours(12)
}
