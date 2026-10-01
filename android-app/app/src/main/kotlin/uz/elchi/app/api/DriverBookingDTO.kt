package uz.elchi.app.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import uz.elchi.app.api.generated.BookingPromoDriverDTO
import uz.elchi.app.api.generated.MediaRefDTO
import uz.elchi.app.api.generated.ParcelCategoryDTO
import uz.elchi.app.api.generated.ServiceType

/** The client as the driver sees it: first name only, the phone once the service started (Q44/Q142). */
@Serializable
data class BookingClientPartyDTO(
    val id: String,
    @SerialName("display_name") val displayName: String,
    @SerialName("contact_phone") val contactPhone: String? = null,
)

/** Q44/Q142: the receiver's name and phone - sent to the driver only after the trip departed; the sender's never. */
@Serializable
data class ParcelContactsDTO(
    @SerialName("receiver_name") val receiverName: String? = null,
    @SerialName("receiver_phone") val receiverPhone: String? = null,
)

/** The commission snapshot (driver and staff only, Q16/Q103). */
@Serializable
data class BookingFeeDTO(
    @SerialName("policy_id") val policyId: String? = null,
    @SerialName("policy_kind") val policyKind: String? = null,
    @SerialName("fee_bps") val feeBps: Long = 0,
    @SerialName("commission_minor") val commissionMinor: Long,
    @SerialName("net_minor") val netMinor: Long? = null,
)

/**
 * The driver's view of a booking (`BookingDTO` on the server: the client view plus the commission snapshot and the
 * driver's promo object). `GET /bookings/{id}` and `GET /me/bookings?role=driver` return it as raw JSON (the
 * generator types the client/driver union as JSON); this is what the driver screens read. No actions field: what the
 * driver may do follows from [serviceStatus] (`DriverBookingRules`).
 */
@Serializable
data class DriverBookingDTO(
    val id: String,
    @SerialName("viewer_side") val viewerSide: String? = null,
    @SerialName("service_type") val serviceType: ServiceType,
    @SerialName("service_status") val serviceStatus: String,
    val pickup: BookingEndDTO,
    val dropoff: BookingEndDTO,
    val quantity: Long = 1,
    @SerialName("unit_price_minor") val unitPriceMinor: Long,
    @SerialName("total_minor") val totalMinor: Long,
    val currency: String = "UZS",
    val version: Long = 0,
    @SerialName("trip_id") val tripId: String? = null,
    @SerialName("parcel_category") val parcelCategory: ParcelCategoryDTO? = null,
    val client: BookingClientPartyDTO? = null,
    @SerialName("parcel_contacts") val parcelContacts: ParcelContactsDTO? = null,
    @SerialName("parcel_photo") val parcelPhoto: MediaRefDTO? = null,
    val contact: BookingContactDTO? = null,
    @SerialName("cancellation_policy_summary") val cancellationPolicySummary: String? = null,
    val cancelled: BookingCancelledDTO? = null,
    @SerialName("listing_ids") val listingIds: BookingListingIdsDTO? = null,
    @SerialName("commission_status") val commissionStatus: String? = null,
    val fee: BookingFeeDTO? = null,
    /** Present only on a discounted booking: collect [BookingPromoDriverDTO.cashToCollectMinor], not [totalMinor]. */
    val promo: BookingPromoDriverDTO? = null,
    @SerialName("created_at") val createdAt: String,
    @SerialName("updated_at") val updatedAt: String? = null,
) {
    companion object {
        const val DRIVER = "driver"

        /** A row of the union, or null when it is not the driver's view. */
        fun fromJson(element: JsonElement): DriverBookingDTO? =
            runCatching { ElchiJson.decodeFromJsonElement(serializer(), element) }.getOrNull()?.takeIf { it.viewerSide == DRIVER }
    }
}
