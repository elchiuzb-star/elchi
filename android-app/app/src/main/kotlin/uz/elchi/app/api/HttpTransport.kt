package uz.elchi.app.api

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import uz.elchi.app.api.generated.ApiWarning
import uz.elchi.app.api.generated.ErrorBody
import uz.elchi.app.api.generated.PageMeta
import uz.elchi.app.session.RefreshFailure
import uz.elchi.app.session.Session
import uz.elchi.app.session.SessionRules
import uz.elchi.app.session.SessionStorage
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * The one HTTP layer: v1 for auth (ADR-0006), the geocoder proxy and uploads, v2 for everything else. Adds the bearer token, refreshes it once
 * on 401 (single-flight, so a rotated refresh token is never spent twice), and unwraps the `{success, data}`
 * envelope into [ApiResult] or [ApiException].
 */
class HttpTransport(
    v1BaseUrl: String,
    private val sessions: SessionStorage,
    private val client: OkHttpClient = defaultClient(),
) : ApiTransport {
    private val v1 = v1BaseUrl.trimEnd('/')
    private val v2 = v1.replace(Regex("/api/v1$"), "/api/v2")
    private val refreshLock = Mutex()

    override fun <T> encode(serializer: KSerializer<T>, value: T): JsonElement = ElchiJson.encodeToJsonElement(serializer, value)

    override suspend fun <T> send(
        method: String,
        path: String,
        query: List<Pair<String, Any?>>,
        body: JsonElement?,
        idempotencyKey: String?,
        result: KSerializer<T>,
    ): ApiResult<T> = request(v2, method, path, query, jsonBody(method, body), idempotencyKey, auth = true, result)

    /** `/api/v1` - only what v2 does not replace: auth, the geocoder proxy (`/geo/...`), legacy orders (read-only). */
    suspend fun <T> sendV1(
        method: String,
        path: String,
        body: JsonElement?,
        auth: Boolean,
        result: KSerializer<T>,
        query: List<Pair<String, Any?>> = emptyList(),
    ): ApiResult<T> = request(v1, method, path, query, jsonBody(method, body), null, auth, result)

    /**
     * Raw bytes of a file the API links to (a parcel photo's short-lived signed `/api/v1/files/...` URL), with the
     * same token and one refresh on 401. [pathOrUrl] is absolute or relative to the API host.
     */
    suspend fun download(pathOrUrl: String, retried: Boolean = false): ByteArray {
        val api = v1.toHttpUrl()
        val url = if (pathOrUrl.startsWith("http")) pathOrUrl.toHttpUrl() else api.resolve(pathOrUrl)
            ?: throw ApiException(0, ApiException.SERVER, "bad file url")
        // The bearer token goes only to our own API host - never to a storage host a signed link may point at.
        val token = if (url.host == api.host && url.port == api.port) sessions.current()?.accessToken else null
        val request = Request.Builder().url(url).get().apply { if (token != null) header("Authorization", "Bearer $token") }.build()
        val (status, bytes) = withContext(Dispatchers.IO) {
            try {
                client.newCall(request).execute().use { response -> response.code to response.body.bytes() }
            } catch (e: IOException) {
                throw ApiException(0, ApiException.NETWORK, e.message ?: "network error")
            }
        }
        if (status == 401 && token != null && !retried && refresh(token)) return download(pathOrUrl, retried = true)
        if (status !in 200..299) throw ApiException(status, ApiException.SERVER, "HTTP $status")
        return bytes
    }

    /**
     * `/api/v1` multipart upload (`/files/upload`), with the same token, refresh and envelope as every other call.
     * The body is built from bytes in memory, so it can be sent a second time after a token refresh.
     */
    suspend fun <T> uploadV1(path: String, body: MultipartBody, result: KSerializer<T>): ApiResult<T> =
        request(v1, "POST", path, emptyList(), body, null, auth = true, result)

    private fun jsonBody(method: String, body: JsonElement?): RequestBody? =
        body?.let { ElchiJson.encodeToString(JsonElement.serializer(), it).toRequestBody(JSON) }
            ?: if (method == "GET" || method == "DELETE") null else "{}".toRequestBody(JSON)

    private suspend fun <T> request(
        base: String,
        method: String,
        path: String,
        query: List<Pair<String, Any?>>,
        body: RequestBody?,
        idempotencyKey: String?,
        auth: Boolean,
        result: KSerializer<T>,
        retried: Boolean = false,
    ): ApiResult<T> {
        val token = if (auth) sessions.current()?.accessToken else null
        val request = Request.Builder()
            .url(url(base, path, query))
            .method(method, body)
            .header("Accept", "application/json")
            // Q110: this client renders F_cash wherever a discounted booking shows money. A rendering capability, never an authority.
            .header("X-Elchi-Client-Features", "promo_cash_v1")
            .apply {
                if (token != null) header("Authorization", "Bearer $token")
                if (idempotencyKey != null) header("Idempotency-Key", idempotencyKey)
            }
            .build()

        val (status, raw) = execute(request)
        if (status == 401 && token != null && !retried && refresh(token)) {
            return request(base, method, path, query, body, idempotencyKey, auth, result, retried = true)
        }
        return unwrap(status, raw, result)
    }

    private suspend fun execute(request: Request): Pair<Int, String?> = withContext(Dispatchers.IO) {
        try {
            client.newCall(request).execute().use { response: Response -> response.code to response.body.string() }
        } catch (e: IOException) {
            throw ApiException(0, ApiException.NETWORK, e.message ?: "network error")
        }
    }

    private fun <T> unwrap(status: Int, raw: String?, result: KSerializer<T>): ApiResult<T> {
        val envelope = raw?.let { runCatching { ElchiJson.parseToJsonElement(it).jsonObject }.getOrNull() }
            ?: throw ApiException(status, ApiException.SERVER, "HTTP $status without a JSON body")
        val success = envelope["success"]?.jsonPrimitive?.booleanOrNull
        if (success == true) {
            // A few endpoints declare the whole envelope as their response model (`/feed` → `FeedEnvelope`, with
            // its own `meta.degraded`): the generator then asks for that type, which is the body, not `data`.
            val whole = result.descriptor.serialName.endsWith(ENVELOPE_SUFFIX)
            return ApiResult(
                data = ElchiJson.decodeFromJsonElement(result, if (whole) envelope else envelope["data"] ?: JsonNull),
                warnings = envelope.decodeOrNull("warnings", ListSerializer(ApiWarning.serializer())) ?: emptyList(),
                meta = envelope.decodeOrNull("meta", PageMeta.serializer()),
            )
        }
        val error = envelope.decodeOrNull("error", ErrorBody.serializer())
            ?: throw ApiException(status, ApiException.SERVER, "HTTP $status")
        throw ApiException(status, error.code, error.message, error.details)
    }

    private fun <T> JsonObject.decodeOrNull(key: String, serializer: KSerializer<T>): T? =
        this[key]?.takeIf { it !is JsonNull }?.let { runCatching { ElchiJson.decodeFromJsonElement(serializer, it) }.getOrNull() }

    /** Returns true when a new access token is in place. Offline keeps the session; a rejected token expires it. */
    private suspend fun refresh(staleAccessToken: String): Boolean = refreshLock.withLock {
        val session = sessions.current() ?: return false
        if (session.accessToken != staleAccessToken) return true // another request already refreshed it
        val body = jsonBody("POST", ElchiJson.encodeToJsonElement(RefreshRequest.serializer(), RefreshRequest(session.refreshToken)))
        return try {
            val tokens = request(v1, "POST", "/auth/refresh", emptyList(), body, null, auth = false, TokenResponse.serializer(), retried = true).data
            sessions.save(Session(tokens.accessToken, tokens.refreshToken, tokens.user))
            true
        } catch (e: ApiException) {
            // Offline or a server fault keeps the session for the next try; a refused token ends it, and the app
            // says so (the session-expired dialog) instead of silently dropping to the entry flow.
            if (SessionRules.refreshFailure(e.status, e.code) == RefreshFailure.EXPIRED) sessions.expire()
            false
        }
    }

    private fun url(base: String, path: String, query: List<Pair<String, Any?>>): HttpUrl {
        val builder = (base + path).toHttpUrl().newBuilder()
        for ((key, value) in query) {
            if (value == null || value == "") continue
            builder.addQueryParameter(key, if (value is WireEnum) value.value else value.toString())
        }
        return builder.build()
    }

    companion object {
        private val JSON = "application/json".toMediaType()
        private const val ENVELOPE_SUFFIX = "Envelope"

        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .build()
    }
}
