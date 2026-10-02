package uz.elchi.app.feature.client

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.longOrNull
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.generated.CashReceiptDTO
import uz.elchi.app.api.generated.CashReceiptDecision
import uz.elchi.app.api.generated.CashReceiptReport
import uz.elchi.app.api.generated.Currency
import uz.elchi.app.api.generated.EffectiveFlagValuesDTO
import uz.elchi.app.api.generated.ListingCreate
import uz.elchi.app.api.generated.ListingDTO
import uz.elchi.app.api.generated.ListingKind
import uz.elchi.app.api.generated.PassengerDetails
import uz.elchi.app.api.generated.PaymentMethod
import uz.elchi.app.api.generated.PointEndInput
import uz.elchi.app.api.generated.PriceBasis
import uz.elchi.app.api.generated.ServiceType
import java.time.Instant
import java.time.format.DateTimeFormatter

/**
 * The passenger seats of a normal sedan, in the order a person reads them (web `SeatPicker.tsx`). What is booked is
 * the COUNT: there is no seat map in the contract and nothing obliges a driver to seat anyone in a given place, so
 * the picture only helps a person count ("three of us, two in the back"); the screen says the exact seat is agreed
 * with the driver.
 */
enum class Seat(val id: String, val key: String) {
    FRONT("front", "seatPicker.front"),
    REAR_LEFT("rear-left", "seatPicker.rearLeft"),
    REAR_MIDDLE("rear-middle", "seatPicker.rearMiddle"),
    REAR_RIGHT("rear-right", "seatPicker.rearRight"),
}

/** Whether the home's primary button may lead on, and why not (the sentence under it). */
enum class HomeBlock { NONE, NOT_READY, PARCEL_CLOSED, PASSENGER_CLOSED }

/** The cash record's state for one side (`app.cash.*`, design `cash-ack`). */
enum class CashView {
    /** Nothing reported yet: the amount field and "Naqd berildi/olindi deb qayd qilish". */
    REPORT,

    /** This side reported: "Siz qayd qildingiz …" + waiting for the other side. */
    AWAITING_OTHER,

    /** The other side reported: "Tasdiqlayman" / "Rozi emasman". */
    DECIDE,

    BOTH_CONFIRMED,

    /** Contested: the operator reviews it (Q78). */
    CONTESTED,
}

/** `PROOF_REISSUE_LIMITED.details.retry_after_s` as the sentence needs it: minutes + seconds, or hours + minutes. */
sealed interface ReissueWait {
    data class Minutes(val minutes: Long, val seconds: Long) : ReissueWait
    data class Hours(val hours: Long, val minutes: Long) : ReissueWait
}

/**
 * Pure rules of the passenger service (Taksi) on the client side, and the cash record both sides share: no Android,
 * no network - unit-tested. Everything here is reached only behind the effective `passenger_enabled` flag (K7/Q5/
 * Q89/Q91): a new request needs it; an existing passenger booking stays visible and operable whatever the flag says.
 */
object TaxiRules {
    /** The cabin has four passenger seats: the picker's cap (the edit accepts up to [MAX_SEATS]). */
    val PICKER_SEATS: Int = Seat.entries.size
    const val MIN_SEATS = 1
    const val MAX_SEATS = 8

    /** The design's start: one seat, rear right (`client-route-summary` `B.seats(['s3'])`). */
    val DEFAULT_SEATS: List<String> = listOf(Seat.REAR_RIGHT.id)

    // -- flags (K7/Q5/Q89) --------------------------------------------------------------------------------------

    /** The Taksi/Pochta segment: only when the country-scope flag says passenger is on (a failed read = off). */
    fun passengerOffered(countryFlags: EffectiveFlagValuesDTO?, failed: Boolean): Boolean = !failed && countryFlags?.passengerEnabled == true

    /** One service on the matched corridor: true / false, null while its flags load. A failed read = closed. */
    fun serviceOpen(flags: EffectiveFlagValuesDTO?, loading: Boolean, failed: Boolean, passenger: Boolean): Boolean? = when {
        failed -> false
        loading || flags == null -> null
        passenger -> flags.passengerEnabled
        else -> flags.parcelEnabled
    }

    /** "Yo'nalishni ko'rish": both places on a confirmed route and the chosen service open on that corridor. */
    fun homeBlock(taxi: Boolean, directionReady: Boolean, open: Boolean?): HomeBlock = when {
        open == false -> if (taxi) HomeBlock.PASSENGER_CLOSED else HomeBlock.PARCEL_CLOSED
        !directionReady || open == null -> HomeBlock.NOT_READY
        else -> HomeBlock.NONE
    }

    // -- seats ----------------------------------------------------------------------------------------------------

    /** Tap on a seat: on/off in the order picked; never down to zero (a request for nobody is not a request). */
    fun toggleSeat(selected: List<String>, id: String): List<String> {
        if (Seat.entries.none { it.id == id }) return selected
        val next = if (id in selected) selected - id else selected + id
        return next.ifEmpty { selected }
    }

    /** The seat's place in the picking order (1-based) for its badge; null when not picked. */
    fun seatOrder(selected: List<String>, id: String): Int? = selected.indexOf(id).takeIf { it >= 0 }?.plus(1)

    fun seatCount(draft: ParcelDraft): Int = draft.seats.count { id -> Seat.entries.any { it.id == id } }

    /** `count × unit`, the price basis `per_seat` (never float). */
    fun totalMinor(unitMinor: Long, count: Long): Long = unitMinor * count

    // -- the request ----------------------------------------------------------------------------------------------

    /** The route step's issues for a passenger request: the parcel's, plus a seat count inside the cabin. */
    fun routeIssues(draft: ParcelDraft, directionReady: Boolean, now: Instant): List<RouteIssue> =
        ParcelRules.routeIssues(draft, directionReady, now)

    fun seatsValid(draft: ParcelDraft): Boolean = seatCount(draft) in MIN_SEATS..PICKER_SEATS

    /** A passenger request has no contacts, parcel or photo steps: route + window + price + seats. */
    fun readyToPublish(draft: ParcelDraft, directionReady: Boolean, now: Instant): Boolean =
        routeIssues(draft, directionReady, now).isEmpty() && seatsValid(draft)

    /**
     * `POST /listings` for a passenger request: the ends as for a parcel, `price_basis = per_seat`, the unit price per
     * person and `passenger {seat_count, adults}` - this version asks for no children, baggage or amenities.
     */
    fun buildListingCreate(draft: ParcelDraft): ListingCreate {
        val origin = checkNotNull(draft.origin) { "origin" }
        val destination = checkNotNull(draft.destination) { "destination" }
        val start = checkNotNull(draft.start) { "window start" }
        val end = checkNotNull(draft.endTime) { "window end" }
        val price = checkNotNull(ParcelRules.soumToMinor(draft.priceDigits)) { "price" }
        val seats = seatCount(draft).toLong()
        check(seats in MIN_SEATS..PICKER_SEATS) { "seats" }
        return ListingCreate(
            kind = ListingKind.REQUEST,
            serviceType = ServiceType.PASSENGER,
            originStopId = origin.stopId,
            originPoint = if (origin.stopId == null) point(origin) else null,
            destinationStopId = destination.stopId,
            destinationPoint = if (destination.stopId == null) point(destination) else null,
            departureWindowStart = ParcelRules.toOffsetIso(start),
            departureWindowEnd = ParcelRules.toOffsetIso(end),
            timezone = ParcelRules.TIMEZONE,
            priceBasis = PriceBasis.PER_SEAT,
            unitPriceMinor = price,
            currency = Currency.UZS,
            paymentMethod = PaymentMethod.CASH,
            comment = draft.comment.trim().ifEmpty { null },
            passenger = PassengerDetails(seatCount = seats, adults = seats),
        )
    }

    private fun point(place: Place) = PointEndInput(lat = place.lat, lng = place.lng, districtId = place.districtId, address = place.address)

    fun isPassenger(serviceType: ServiceType): Boolean = serviceType == ServiceType.PASSENGER

    // -- seat-count edit (Q145, web `listingEdit.ts`) -------------------------------------------------------------

    /** Only the client's own passenger request, before a booking exists (the server refuses it afterwards, D9). */
    fun seatsEditable(listing: ListingDTO): Boolean =
        listing.kind == ListingKind.REQUEST && listing.serviceType == ServiceType.PASSENGER && listing.passenger != null && OrderRules.canEdit(listing.status)

    /**
     * The new passenger block when the typed count differs: the WHOLE block travels (the server replaces it), with
     * `adults = seats - children`. Returns the block (or null = unchanged) and a reason it cannot be sent.
     */
    fun seatsPatch(listing: ListingDTO, typed: String): Pair<PassengerDetails?, EditInvalid?> {
        val block = listing.passenger ?: return null to null
        val seats = typed.trim().toLongOrNull()
        val children = block.children ?: 0
        return when {
            seats == null || seats !in MIN_SEATS..MAX_SEATS -> null to EditInvalid.SEATS
            seats <= children -> null to EditInvalid.SEATS_CHILDREN
            seats == block.seatCount -> null to null
            else -> block.copy(seatCount = seats, adults = seats - children) to null
        }
    }

    // -- the passenger booking (client) ---------------------------------------------------------------------------

    /** Before the passenger is in the car: the boarding code is the client's to show (Q44). */
    private val CODE_STATUSES = setOf("confirmed", "awaiting_pickup")

    /** The service started (server `has_started`): from here the cash handover can be recorded. */
    private val CASH_STATUSES = setOf("onboard", "arrived", "completed")

    fun showBoardingCode(serviceType: ServiceType, status: String): Boolean = isPassenger(serviceType) && status in CODE_STATUSES

    fun showCash(serviceType: ServiceType, status: String): Boolean = isPassenger(serviceType) && status in CASH_STATUSES

    /** "Manzilga yetib keldim" (`complete`): the passenger confirms the arrival the driver recorded (`drop_off`). */
    fun canComplete(serviceType: ServiceType, status: String): Boolean = isPassenger(serviceType) && status == "arrived"

    /** `PROOF_REISSUE_LIMITED.details.retry_after_s` → what to wait: under an hour in minutes + seconds. */
    fun reissueWait(retryAfterSeconds: Long): ReissueWait {
        val s = retryAfterSeconds.coerceAtLeast(1)
        if (s < 3600) return ReissueWait.Minutes(s / 60, s % 60)
        // Whole minutes, rounded up so the sentence never promises a moment too early.
        val minutes = (s + 59) / 60
        return ReissueWait.Hours(minutes / 60, minutes % 60)
    }

    /** `details.retry_after_s` / `details.reissues_left` of a refused reissue; null when it was another refusal. */
    fun reissueLimit(error: Throwable): Pair<Long?, Long?>? {
        val api = error as? ApiException ?: return null
        if (api.code != "PROOF_REISSUE_LIMITED") return null
        return detailLong(api.details, "retry_after_s") to detailLong(api.details, "reissues_left")
    }

    fun detailLong(details: JsonElement?, key: String): Long? =
        ((details as? JsonObject)?.get(key) as? JsonPrimitive)?.let { it.longOrNull ?: it.contentOrNull?.toDoubleOrNull()?.toLong() }

    // -- the cash record (both sides) -----------------------------------------------------------------------------

    /**
     * The newest receipt on the booking decides, with `cash_status` as the fallback: `unpaid` → report; reported by
     * this side → waiting; by the other → decide; then confirmed or contested.
     */
    fun cashView(cashStatus: String?, receipt: CashReceiptDTO?, mySide: String): CashView = when (cashStatus ?: receipt?.status) {
        "acknowledged" -> CashView.BOTH_CONFIRMED
        "contested" -> CashView.CONTESTED
        "reported_paid" -> when {
            receipt == null -> CashView.AWAITING_OTHER
            receipt.reportedBySide == mySide -> CashView.AWAITING_OTHER
            else -> CashView.DECIDE
        }
        else -> CashView.REPORT
    }

    /** The server asks for a note whenever the reported amount differs from the cash due. */
    fun cashNoteRequired(amountMinor: Long?, dueMinor: Long): Boolean = amountMinor != null && amountMinor != dueMinor

    /** `POST /bookings/{id}/cash-receipts`; null while the amount is empty or a differing amount has no note. */
    fun cashReport(bookingVersion: Long, amountDigits: String, note: String, dueMinor: Long, now: Instant): CashReceiptReport? {
        val amount = ParcelRules.soumToMinor(amountDigits) ?: return null
        val text = note.trim()
        if (cashNoteRequired(amount, dueMinor) && text.isEmpty()) return null
        return CashReceiptReport(amountMinor = amount, expectedVersion = bookingVersion, note = text.ifEmpty { null }, reportedAt = iso(now))
    }

    fun acknowledgeBody(receipt: CashReceiptDTO): CashReceiptDecision = CashReceiptDecision(expectedVersion = receipt.version)

    /** "Rozi emasman" needs a comment (the server refuses an empty one): the operator reads it. */
    fun contestBody(receipt: CashReceiptDTO, comment: String): CashReceiptDecision? =
        comment.trim().takeIf { it.isNotEmpty() }?.let { CashReceiptDecision(comment = it, expectedVersion = receipt.version) }

    fun iso(instant: Instant): String = instant.atZone(ParcelRules.TASHKENT).toOffsetDateTime().withNano(0).format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)
}
