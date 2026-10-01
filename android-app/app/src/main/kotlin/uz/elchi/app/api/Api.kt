package uz.elchi.app.api

import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.JsonElement
import uz.elchi.app.api.generated.ApiWarning
import uz.elchi.app.api.generated.PageMeta

/** A successful v2 answer: `data`, plus the warnings (Q43, Q90) and the cursor page the envelope carried. */
data class ApiResult<T>(val data: T, val warnings: List<ApiWarning> = emptyList(), val meta: PageMeta? = null)

/**
 * A refused or failed request. [code] is the server's `ErrorCode` (or [NETWORK] when nothing came back);
 * the UI turns it into a sentence (`ErrorText`), never shows [message] unless the code is unknown.
 */
class ApiException(
    val status: Int,
    val code: String,
    override val message: String,
    val details: JsonElement? = null,
) : Exception(message) {
    companion object {
        const val NETWORK = "NETWORK_ERROR"
        const val SERVER = "SERVER_ERROR"
    }
}

/** What the generated [uz.elchi.app.api.generated.ElchiApi] needs; [HttpTransport] is the real one. */
interface ApiTransport {
    fun <T> encode(serializer: KSerializer<T>, value: T): JsonElement

    suspend fun <T> send(
        method: String,
        path: String,
        query: List<Pair<String, Any?>>,
        body: JsonElement?,
        idempotencyKey: String?,
        result: KSerializer<T>,
    ): ApiResult<T>
}

/** A generated enum: [value] is what goes on the wire (`"client"`), not the Kotlin name (`CLIENT`). */
interface WireEnum {
    val value: String
}
