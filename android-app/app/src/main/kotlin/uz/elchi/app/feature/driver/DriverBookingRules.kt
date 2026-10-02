package uz.elchi.app.feature.driver

import uz.elchi.app.api.BookingNoShowReviewDTO
import uz.elchi.app.api.DriverBookingDTO
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.feature.client.BookingRules
import uz.elchi.app.feature.client.BookingViewModel
import uz.elchi.app.feature.client.OrderRules
import uz.elchi.app.ui.theme.Tone
import java.time.Duration
import java.time.Instant

/** The receiver line (Q44/Q142): the name and phone once the trip departed, else when it opens. Never the sender's. */
sealed interface ReceiverView {
    data class Visible(val name: String?, val phone: String) : ReceiverView
    data class Hidden(val visibleFrom: String?) : ReceiverView
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
    fun badgeKey(serviceType: ServiceType, status: String): String = when {
        serviceType == ServiceType.PARCEL && status in IN_TRANSIT -> "parcel.status.driverDeparted"
        serviceType == ServiceType.PARCEL && status == "delivered" -> "parcel.progress.deliveredByOperator"
        else -> "status.$status"
    }

    fun badgeTone(serviceType: ServiceType, status: String): Tone = OrderRules.bookingTone(serviceType, status)

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
