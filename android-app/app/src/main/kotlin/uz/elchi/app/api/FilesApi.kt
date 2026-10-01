package uz.elchi.app.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody

/** `POST /api/v1/files/upload` answer. [fileUrl] is a short-lived signed reference the listing body sends back. */
@Serializable
data class UploadedFile(
    @SerialName("file_url") val fileUrl: String,
    val type: String? = null,
    @SerialName("mime_type") val mimeType: String? = null,
    @SerialName("size_bytes") val sizeBytes: Long? = null,
)

class FilesApi(private val transport: HttpTransport) {
    /**
     * One file of [type] (`cargo_photo`, or a driver document type: `passport`, `selfie`, `license`,
     * `car_document`, `car_photo`). The form field is `type` - the backend reads `Form(alias="type")`, the same name
     * the web client sends - and checks the file's magic bytes and size per type (`FILE_TOO_LARGE` 413,
     * `VALIDATION_ERROR` 400).
     */
    suspend fun upload(bytes: ByteArray, fileName: String, type: String, mimeType: String): UploadedFile {
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("type", type)
            .addFormDataPart("file", fileName, bytes.toRequestBody(mimeType.toMediaType()))
            .build()
        return transport.uploadV1("/files/upload", body, UploadedFile.serializer()).data
    }

    /** A parcel photo (`cargo_photo`), always the JPEG the photo pipeline made. */
    suspend fun uploadCargoPhoto(jpeg: ByteArray, fileName: String): UploadedFile = upload(jpeg, fileName, CARGO_PHOTO, JPEG)

    /** A cargo photo the API returned as a short-lived signed link (`ParcelDetails.photo.url`, Q6). */
    suspend fun download(url: String): ByteArray = transport.download(url)

    companion object {
        private const val CARGO_PHOTO = "cargo_photo"
        const val JPEG = "image/jpeg"
        const val PDF = "application/pdf"
    }
}
