package uz.elchi.app.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** `PATCH /api/v1/client/profile` answer; only the name is read back (the phone never changes here). */
@Serializable
data class ClientProfileDTO(@SerialName("full_name") val fullName: String? = null)

@Serializable
private data class ClientProfileUpdate(@SerialName("full_name") val fullName: String)

/**
 * The client's name: v2 has no profile PATCH, so it stays on `/api/v1` (hand-typed like [AuthApi]);
 * `400 VALIDATION_ERROR` means a blank name. Contact details in a name are filtered by the server (Q43).
 */
class AccountApi(private val transport: HttpTransport) {
    suspend fun updateClientName(fullName: String): ClientProfileDTO =
        transport.sendV1(
            "PATCH",
            "/client/profile",
            transport.encode(ClientProfileUpdate.serializer(), ClientProfileUpdate(fullName)),
            auth = true,
            ClientProfileDTO.serializer(),
        ).data
}
