package uz.elchi.app.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.JsonElement

/** The account part of `GET /api/v1/driver/profile`. */
@Serializable
data class DriverUser(
    val id: Long,
    val phone: String,
    @SerialName("full_name") val fullName: String? = null,
    val status: String? = null,
)

/**
 * `GET /api/v1/driver/profile` (v1, hand-typed like [AuthApi]). The vehicle fields are the car entered once (Q94);
 * [verificationStatus] is `new | pending | approved | rejected | blocked`. The rating is left out on purpose: this
 * stage never shows one (§9, no invented "4.5" for a new driver).
 */
@Serializable
data class DriverProfileDTO(
    val id: Long,
    val user: DriverUser? = null,
    @SerialName("full_name") val fullName: String? = null,
    @SerialName("car_model") val carModel: String? = null,
    @SerialName("car_color") val carColor: String? = null,
    @SerialName("plate_number") val plateNumber: String? = null,
    @SerialName("verification_status") val verificationStatus: String = "new",
    @SerialName("completed_orders") val completedOrders: Long? = null,
    /** v1 orders of the legacy app (Stage 09 profile "Jami (eski)"); not v2 bookings. */
    @SerialName("total_orders") val totalOrders: Long? = null,
    @SerialName("is_available") val isAvailable: Boolean = false,
)

/**
 * `PATCH /api/v1/driver/profile`: only the keys that are set go out (the JSON config drops nulls). A vehicle key
 * that already holds a value is refused with 403 `DRIVER_VEHICLE_LOCKED` (Q94), so a locked form sends the name only.
 */
@Serializable
data class DriverProfileUpdate(
    @SerialName("full_name") val fullName: String? = null,
    @SerialName("car_model") val carModel: String? = null,
    @SerialName("car_color") val carColor: String? = null,
    @SerialName("plate_number") val plateNumber: String? = null,
)

/** One row of `GET /api/v1/driver/documents`: the latest upload of a type. [fileUrl] is a short-lived signed link. */
@Serializable
data class DriverDocumentDTO(
    @SerialName("document_id") val documentId: Long,
    @SerialName("document_type") val documentType: String,
    @SerialName("file_url") val fileUrl: String? = null,
    val status: String,
    @SerialName("rejection_reason") val rejectionReason: String? = null,
)

@Serializable
private data class DriverDocumentCreate(
    @SerialName("document_type") val documentType: String,
    @SerialName("file_url") val fileUrl: String,
    @SerialName("mime_type") val mimeType: String,
    @SerialName("size_bytes") val sizeBytes: Long,
)

@Serializable
private data class AvailabilityUpdate(@SerialName("is_available") val isAvailable: Boolean)

@Serializable
private data class AvailabilityDTO(@SerialName("is_available") val isAvailable: Boolean)

/**
 * The driver's own record, which v2 does not replace: profile + car (Q94), the five verification documents and
 * the availability switch. All `/api/v1/driver/...`, envelope `{success, data, message}`; a non-driver gets 403.
 */
class DriverApi(private val transport: HttpTransport) {
    suspend fun profile(): DriverProfileDTO =
        transport.sendV1("GET", "/driver/profile", null, auth = true, DriverProfileDTO.serializer()).data

    /** The answer is a smaller dict; the caller reads the profile again. */
    suspend fun updateProfile(update: DriverProfileUpdate) {
        transport.sendV1("PATCH", "/driver/profile", transport.encode(DriverProfileUpdate.serializer(), update), auth = true, JsonElement.serializer())
    }

    suspend fun documents(): List<DriverDocumentDTO> =
        transport.sendV1("GET", "/driver/documents", null, auth = true, ListSerializer(DriverDocumentDTO.serializer())).data

    /**
     * Step 2 of an upload (step 1 is [FilesApi.upload] with the same type): a re-upload replaces the row and makes
     * it pending again; any upload moves a `new` or `rejected` driver to `pending`.
     */
    suspend fun submitDocument(type: String, fileUrl: String, mimeType: String, sizeBytes: Long): DriverDocumentDTO =
        transport.sendV1(
            "POST",
            "/driver/documents",
            transport.encode(DriverDocumentCreate.serializer(), DriverDocumentCreate(type, fileUrl, mimeType, sizeBytes)),
            auth = true,
            DriverDocumentDTO.serializer(),
        ).data

    /** On: 400 `DRIVER_NOT_APPROVED`, 403 `DRIVER_BLOCKED`. Off always works. Returns the stored value. */
    suspend fun setAvailability(on: Boolean): Boolean =
        transport.sendV1(
            "PATCH",
            "/driver/availability",
            transport.encode(AvailabilityUpdate.serializer(), AvailabilityUpdate(on)),
            auth = true,
            AvailabilityDTO.serializer(),
        ).data.isAvailable
}
