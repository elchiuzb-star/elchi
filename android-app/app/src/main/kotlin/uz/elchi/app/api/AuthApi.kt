package uz.elchi.app.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import uz.elchi.app.session.AuthUser
import uz.elchi.app.session.MobileRole

@Serializable
data class RefreshRequest(@SerialName("refresh_token") val refreshToken: String)

@Serializable
data class TokenResponse(
    @SerialName("access_token") val accessToken: String,
    @SerialName("refresh_token") val refreshToken: String,
    val user: AuthUser,
)

@Serializable
data class OtpSent(
    @SerialName("otp_sent") val otpSent: Boolean,
    val phone: String,
    /** Only when the backend runs without SMS (development); the verify screen shows it. */
    @SerialName("dev_otp") val devOtp: String? = null,
    /** The server's cooldown before another code may be requested. */
    @SerialName("resend_after_seconds") val resendAfterSeconds: Int? = null,
)

@Serializable
private data class OtpRequest(val phone: String, val role: String)

@Serializable
private data class OtpVerify(val phone: String, val role: String, val otp: String)

/** Auth stays on `/api/v1` (ADR-0006); the token it issues is accepted by v2. */
class AuthApi(private val transport: HttpTransport) {
    suspend fun requestOtp(phone: String, role: MobileRole): OtpSent =
        transport.sendV1("POST", "/auth/request-otp", json(OtpRequest.serializer(), OtpRequest(phone, role.wire)), auth = false, OtpSent.serializer()).data

    suspend fun verifyOtp(phone: String, role: MobileRole, otp: String): TokenResponse =
        transport.sendV1("POST", "/auth/verify-otp", json(OtpVerify.serializer(), OtpVerify(phone, role.wire, otp)), auth = false, TokenResponse.serializer()).data

    suspend fun me(): AuthUser = transport.sendV1("GET", "/auth/me", null, auth = true, AuthUser.serializer()).data

    suspend fun logout(refreshToken: String) {
        transport.sendV1("POST", "/auth/logout", json(RefreshRequest.serializer(), RefreshRequest(refreshToken)), auth = true, JsonElement.serializer())
    }

    private fun <T> json(serializer: kotlinx.serialization.KSerializer<T>, value: T) = transport.encode(serializer, value)
}
