package uz.elchi.app.feature.driver

import uz.elchi.app.api.ApiException
import uz.elchi.app.api.BookingNoShowReviewDTO
import uz.elchi.app.api.generated.BookingActionRequest
import uz.elchi.app.api.generated.ContactAttemptInput
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.feature.client.BookingRules
import uz.elchi.app.feature.client.OrderRules
import uz.elchi.app.feature.client.TaxiRules
import java.time.Duration
import java.time.Instant

/**
 * How the driver tried to reach the client before "Mijoz kelmadi" (`ContactAttemptInput.channel`). The contract's
 * values are `chat | quick_reply | arrived_signal | other`; a phone call has no value of its own, so it is `other`.
 */
enum class ContactChannel(val wire: String, val key: String) {
    CHAT("chat", "driver.noShow.channel.chat"),
    CALL("other", "driver.noShow.channel.call"),
}

/** "Mijoz kelmadi" right now (Q7: the driver reports, the operator decides). */
sealed interface NoShowState {
    /** Not a passenger booking waiting for its passenger. */
    data object Hidden : NoShowState

    /** Reported; the operator reviews it (`no_show_review.status = pending`). */
    data object Pending : NoShowState

    /** Shown but off: why (`driver.noShow.reason.<reason>`), and - when time is the reason - when it unlocks. */
    data class Locked(val reason: String, val unlocksAt: Instant? = null) : NoShowState

    data object Ready : NoShowState
}

/** A refused boarding, in the words the driver needs. */
sealed interface BoardError {
    /** `TRIP_NOT_STARTED`: the trip's boarding must be started first (the trip screen). */
    data object TripNotStarted : BoardError

    data class Other(val error: Throwable) : BoardError
}

/**
 * Pure rules of the driver's passenger booking (Taksi, design "Bron tafsiloti · yo'lovchi"): no Android, no network -
 * unit-tested. "Keldim" is shared with the parcel (`DriverBookingRules.canArrive`).
 */
object DriverTaxiRules {
    /** The announced wait before a no-show may be reported (the trip's `pickup_wait_minutes`, 10 by default). */
    val WAIT: Duration = Duration.ofMinutes(10)

    private fun passenger(serviceType: ServiceType) = TaxiRules.isPassenger(serviceType)

    /** "Yo'lovchini chiqardim": the passenger is waiting at the car. */
    fun showBoard(serviceType: ServiceType, status: String): Boolean = passenger(serviceType) && status == "awaiting_pickup"

    /** "Yo'lovchini tushirdim" (`drop_off`): the passenger is in the car. */
    fun showDropOff(serviceType: ServiceType, status: String): Boolean = passenger(serviceType) && status == "onboard"

    /** `board {expected_version}`: the passenger boards on the driver's word alone (Q163 retired the code). */
    fun boardBody(version: Long): BookingActionRequest = BookingActionRequest(expectedVersion = version)

    fun boardError(error: Throwable): BoardError {
        val api = error as? ApiException ?: return BoardError.Other(error)
        return if (api.code == "TRIP_NOT_STARTED") BoardError.TripNotStarted else BoardError.Other(error)
    }

    /** Server `check_no_show_report`: the wait counts from the arrival or the window start, whichever is later. */
    fun noShowUnlocksAt(arrivedAt: Instant, windowStart: Instant?): Instant =
        (if (windowStart != null && windowStart.isAfter(arrivedAt)) windowStart else arrivedAt).plus(WAIT)

    /**
     * Shown only while the passenger is awaited (`awaiting_pickup`); enabled once "Keldim" was recorded inside the
     * pickup window and the wait has passed. The server checks the same and is the judge.
     */
    fun noShow(serviceType: ServiceType, status: String, arrivedAt: String?, windowStart: String?, windowEnd: String?, review: BookingNoShowReviewDTO?, now: Instant): NoShowState {
        if (!passenger(serviceType) || status != "awaiting_pickup") return NoShowState.Hidden
        if (BookingRules.reviewPending(review)) return NoShowState.Pending
        val arrived = OrderRules.parseInstant(arrivedAt) ?: return NoShowState.Locked("arrival_not_recorded")
        val end = OrderRules.parseInstant(windowEnd)
        if (end != null && arrived.isAfter(end)) return NoShowState.Locked("driver_arrived_late")
        val unlocks = noShowUnlocksAt(arrived, OrderRules.parseInstant(windowStart))
        return if (now.isBefore(unlocks)) NoShowState.Locked("wait_time_not_elapsed", unlocks) else NoShowState.Ready
    }

    /**
     * `report_no_show {expected_version, contact_attempts, observed_at}`: one attempt per channel ticked, all "now"
     * (the sheet asks how, not when). Null without a channel - the server needs at least one attempt.
     */
    fun noShowBody(version: Long, channels: Set<ContactChannel>, now: Instant): BookingActionRequest? {
        if (channels.isEmpty()) return null
        val at = TaxiRules.iso(now)
        return BookingActionRequest(
            contactAttempts = ContactChannel.entries.filter { it in channels }.map { ContactAttemptInput(at = at, channel = it.wire) },
            expectedVersion = version,
            observedAt = at,
        )
    }

    /** `NO_SHOW_NOT_ALLOWED {reason}` → `driver.noShow.reason.<reason>`; `NO_SHOW_REVIEW_PENDING` → the pending text. */
    fun noShowRefusalKey(error: Throwable): String? {
        val api = error as? ApiException ?: return null
        return when (api.code) {
            "NO_SHOW_NOT_ALLOWED" -> BookingRules.detailsReason(api.details)?.takeIf { it in REASONS }?.let { "driver.noShow.reason.$it" } ?: "error.NO_SHOW_NOT_ALLOWED"
            "NO_SHOW_REVIEW_PENDING" -> "driver.noShow.pending"
            else -> null
        }
    }

    val REASONS = setOf("not_awaiting_pickup", "arrival_not_recorded", "driver_arrived_late", "wait_time_not_elapsed", "no_contact_attempt")
}
