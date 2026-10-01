package uz.elchi.app.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import uz.elchi.app.api.generated.BookingPromoClientDTO
import uz.elchi.app.api.generated.MediaRefDTO
import uz.elchi.app.api.generated.ParcelCategoryDTO
import uz.elchi.app.api.generated.PointEndDTO
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.api.generated.StopRefDTO

/** One end of a booking: a verified stop or the agreed map point (Q88), with its window. */
@Serializable
data class BookingEndDTO(
    val stop: StopRefDTO? = null,
    val point: PointEndDTO? = null,
    @SerialName("window_start") val windowStart: String? = null,
    @SerialName("window_end") val windowEnd: String? = null,
    @SerialName("planned_arrival_at") val plannedArrivalAt: String? = null,
)

@Serializable
data class BookingListingIdsDTO(val request: String? = null, val supply: String? = null)

@Serializable
data class BookingCancelledDTO(
    @SerialName("by_side") val bySide: String? = null,
    @SerialName("reason_code") val reasonCode: String? = null,
    @SerialName("fault_side") val faultSide: String? = null,
    val at: String? = null,
)

/**
 * The car after accept (Q64): make/model, colour and the masked plate; [plateNumber] only once the full plate is
 * visible (trip boarding or <= 30 min before the pickup), [plateNumberVisibleFrom] says when.
 */
@Serializable
data class BookingVehicleDTO(
    @SerialName("vehicle_class") val vehicleClass: String,
    @SerialName("seat_capacity") val seatCapacity: Long,
    @SerialName("make_model") val makeModel: String,
    val color: String,
    @SerialName("plate_masked") val plateMasked: String,
    @SerialName("plate_number") val plateNumber: String? = null,
    @SerialName("plate_number_visible_from") val plateNumberVisibleFrom: String? = null,
)

/** The assigned driver as the client sees it: first name only, the car, the phone once the service started (Q44). */
@Serializable
data class BookingDriverDTO(
    /** `usr_...`: the reputation lookup and a block use it. */
    val id: String,
    @SerialName("display_name") val displayName: String,
    val vehicle: BookingVehicleDTO,
    @SerialName("contact_phone") val contactPhone: String? = null,
)

/** When phones are shown (Q44/Q142: from the trip's departure until 24 h after the end) and whether support exists. */
@Serializable
data class BookingContactDTO(
    @SerialName("phones_visible") val phonesVisible: Boolean = false,
    @SerialName("visible_from") val visibleFrom: String? = null,
    @SerialName("visible_until") val visibleUntil: String? = null,
    @SerialName("chat_thread_id") val chatThreadId: String? = null,
    @SerialName("support_available") val supportAvailable: Boolean = true,
)

/** Q7: a reported no-show the operator is reviewing - while `pending` only the operator may cancel. */
@Serializable
data class BookingNoShowReviewDTO(val status: String? = null)

/**
 * The client's view of a booking (`BookingClientDTO` on the server: no commission, fee or wallet, Q16). The
 * generated API returns the client/driver union of `GET /me/bookings` and `POST /proposals/{id}/accept` as raw
 * JSON; this is the part of the client shape the orders list and the booking screens read. [promo] present = the
 * client hands the driver [BookingPromoClientDTO.cashDueMinor], not [totalMinor] (Q103). There is no actions field:
 * what the client may do follows from [serviceStatus] (`BookingRules`).
 */
@Serializable
data class BookingClientDTO(
    val id: String,
    @SerialName("viewer_side") val viewerSide: String? = null,
    @SerialName("service_type") val serviceType: ServiceType,
    @SerialName("service_status") val serviceStatus: String,
    @SerialName("cash_status") val cashStatus: String? = null,
    val pickup: BookingEndDTO,
    val dropoff: BookingEndDTO,
    val quantity: Long = 1,
    @SerialName("unit_price_minor") val unitPriceMinor: Long,
    @SerialName("total_minor") val totalMinor: Long,
    val currency: String = "UZS",
    val promo: BookingPromoClientDTO? = null,
    @SerialName("created_at") val createdAt: String,
    val cancelled: BookingCancelledDTO? = null,
    @SerialName("listing_ids") val listingIds: BookingListingIdsDTO? = null,
    // Stage 04: the booking screens.
    /** `expected_version` of cancel and of a new amendment. */
    val version: Long = 0,
    @SerialName("trip_id") val tripId: String? = null,
    @SerialName("parcel_category") val parcelCategory: ParcelCategoryDTO? = null,
    val driver: BookingDriverDTO? = null,
    /** Q6: a short-lived signed link to the cargo photo; the booking is read again for a fresh one. */
    @SerialName("parcel_photo") val parcelPhoto: MediaRefDTO? = null,
    val contact: BookingContactDTO? = null,
    @SerialName("no_show_review") val noShowReview: BookingNoShowReviewDTO? = null,
    @SerialName("cancellation_policy_summary") val cancellationPolicySummary: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
) {
    companion object {
        /** A row of the union, or null when it is not the client's view (a driver row never belongs here). */
        fun fromJson(element: JsonElement): BookingClientDTO? =
            runCatching { ElchiJson.decodeFromJsonElement(serializer(), element) }.getOrNull()?.takeIf { it.viewerSide == null || it.viewerSide == CLIENT }

        /**
         * The fields both sides share, from either view (the driver screens reuse the Stage 04 amendment, tracking and
         * safety screens). The driver's `promo` is another shape (Q103), so it is left out here - never read as the
         * client's cash due.
         */
        fun anySide(element: JsonElement): BookingClientDTO? {
            val obj = element as? kotlinx.serialization.json.JsonObject ?: return null
            val shared = if (obj["viewer_side"]?.let { (it as? kotlinx.serialization.json.JsonPrimitive)?.content } == CLIENT) obj else kotlinx.serialization.json.JsonObject(obj - "promo")
            return runCatching { ElchiJson.decodeFromJsonElement(serializer(), shared) }.getOrNull()
        }

        const val CLIENT = "client"
    }
}
