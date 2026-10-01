package uz.elchi.app.feature.client

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.ElchiJson
import uz.elchi.app.api.LiveSocket
import uz.elchi.app.api.LiveSocketFactory
import uz.elchi.app.api.LiveSocketListener
import uz.elchi.app.api.generated.BookingTrackingDTO
import uz.elchi.app.api.generated.TrackingFreshness

/** How the position is arriving right now. */
enum class LiveTransport { IDLE, SOCKET, POLL }

/**
 * What the tracking screen knows about the live position. [closedReason] is the server's reason the window is not
 * open (`parcel_not_picked_up`, `booking_finished`, ...), [featureOff] the corridor's `tracking_enabled` switched
 * off; neither is an error.
 */
data class LiveState(
    val data: BookingTrackingDTO? = null,
    val closedReason: String? = null,
    val featureOff: Boolean = false,
    val error: Throwable? = null,
    val transport: LiveTransport = LiveTransport.IDLE,
    /** 404 / 4404: this booking is not (or no longer) visible - nothing is retried. */
    val gone: Boolean = false,
    val loaded: Boolean = false,
)

/**
 * The viewer side of live tracking (spec §10.3 step 5; the web's `useLiveTracking`): the K8 WebSocket pushes a
 * snapshot every ~5 s; while it is not delivering, the HTTP snapshot is polled every 15 s and the socket is retried
 * with a 5 -> 60 s backoff. The server re-checks the viewer and the window on every push, so only what arrives moves
 * the marker. Close codes: 4401 (the HTTP call refreshes the token, one retry), 4403 (window closed: poll, reconnect
 * once a poll says it is open), 4404 (stop), anything else (retry with backoff).
 *
 * [run] lives exactly as long as its caller's coroutine (the screen, while started): cancelling it closes the socket
 * and stops polling.
 */
class LiveTrackingSession(
    private val bookingId: String,
    private val fetch: suspend () -> BookingTrackingDTO,
    private val sockets: LiveSocketFactory?,
    private val socketUrl: String,
    private val accessToken: () -> String?,
    private val update: ((LiveState) -> LiveState) -> Unit,
    private val pollMs: Long = POLL_MS,
) {
    private sealed interface Event {
        data class Opened(val gen: Int) : Event
        data class Message(val gen: Int, val text: String) : Event
        data class Closed(val gen: Int, val code: Int) : Event
        data object PollTick : Event
        data object Reconnect : Event
    }

    suspend fun run() = coroutineScope {
        val events = Channel<Event>(Channel.UNLIMITED)
        var socket: LiveSocket? = null
        var gen = 0
        // While the socket delivers, a slower HTTP answer is older news: it must not move the marker back.
        var socketLive = false
        var attempts = 0
        var authRetried = false
        var windowClosed = false
        var finished = false
        var reconnect: Job? = null

        fun connect() {
            val factory = sockets ?: return
            if (finished || socket != null || reconnect?.isActive == true) return
            val mine = ++gen
            socket = try {
                factory.open(socketUrl, object : LiveSocketListener {
                    override fun onOpen() { events.trySend(Event.Opened(mine)) }
                    override fun onMessage(text: String) { events.trySend(Event.Message(mine, text)) }
                    override fun onClosed(code: Int) { events.trySend(Event.Closed(mine, code)) }
                })
            } catch (e: Exception) {
                null
            }
            if (socket == null) update { it.copy(transport = LiveTransport.POLL) }
        }

        fun scheduleReconnect() {
            if (finished || reconnect?.isActive == true) return
            val wait = (RECONNECT_BASE_MS shl attempts.coerceAtMost(4)).coerceAtMost(RECONNECT_MAX_MS)
            attempts += 1
            reconnect = launch {
                delay(wait)
                events.send(Event.Reconnect)
            }
        }

        suspend fun poll() {
            try {
                val value = fetch()
                if (socketLive) return
                update { it.copy(data = value, closedReason = null, featureOff = false, error = null, loaded = true, transport = if (socket == null) LiveTransport.POLL else it.transport) }
                // The window opened while we were polling: the socket is worth another try.
                if (windowClosed && value.window.isOpen) {
                    windowClosed = false
                    connect()
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: ApiException) {
                when {
                    e.status == 404 || e.code == NOT_FOUND -> {
                        finished = true
                        update { it.copy(gone = true, loaded = true, transport = LiveTransport.IDLE) }
                    }
                    e.code == WINDOW_NOT_OPEN -> {
                        val reason = BookingRules.detailsReason(e.details)
                        windowClosed = true
                        // A finished booking never reopens its window: nothing more to wait for.
                        if (reason in FINAL_REASONS) finished = true
                        update { it.copy(closedReason = reason ?: WINDOW_UNKNOWN, featureOff = false, error = null, loaded = true, data = if (reason in FINAL_REASONS) null else it.data) }
                    }
                    e.code == FEATURE_DISABLED -> update { it.copy(featureOff = true, error = null, loaded = true) }
                    else -> update { it.copy(error = e, loaded = true) }
                }
            } catch (e: Exception) {
                update { it.copy(error = e, loaded = true) }
            }
        }

        val ticker = launch {
            while (isActive) {
                delay(pollMs)
                events.send(Event.PollTick)
            }
        }
        try {
            poll()
            if (!windowClosed && !finished) connect()
            if (sockets == null) update { it.copy(transport = LiveTransport.POLL) }
            while (!finished) {
                when (val event = events.receive()) {
                    is Event.Opened -> if (event.gen == gen) {
                        val token = accessToken()
                        val frame = buildJsonObject {
                            put("action", "subscribe")
                            put("booking_id", bookingId)
                            if (token != null) put("access_token", token)
                        }
                        socket?.send(frame.toString())
                    }
                    is Event.Message -> if (event.gen == gen) {
                        val message = runCatching { ElchiJson.parseToJsonElement(event.text).jsonObject }.getOrNull() ?: continue
                        when ((message["type"] as? JsonPrimitive)?.contentOrNull) {
                            TYPE_POINT -> {
                                val data = message["data"]?.let { runCatching { ElchiJson.decodeFromJsonElement(BookingTrackingDTO.serializer(), it) }.getOrNull() } ?: continue
                                attempts = 0
                                authRetried = false
                                socketLive = true
                                update { it.copy(data = data, closedReason = null, featureOff = false, error = null, loaded = true, transport = LiveTransport.SOCKET) }
                            }
                            TYPE_STALE -> {
                                val freshness = ((message["data"] as? JsonObject)?.get("freshness") as? JsonPrimitive)?.contentOrNull
                                val value = TrackingFreshness.entries.firstOrNull { it.value == freshness && it != TrackingFreshness.UNKNOWN }
                                if (value != null) update { s -> s.copy(data = s.data?.copy(freshness = value)) }
                            }
                        }
                    }
                    is Event.Closed -> if (event.gen == gen) {
                        socket = null
                        socketLive = false
                        update { it.copy(transport = LiveTransport.POLL) }
                        when (event.code) {
                            CLOSE_NOT_FOUND -> {
                                finished = true
                                update { it.copy(gone = true, transport = LiveTransport.IDLE) }
                            }
                            // Window closed: polling says when it opens again (poll() reconnects then).
                            CLOSE_WINDOW -> {
                                windowClosed = true
                                poll()
                            }
                            CLOSE_AUTH -> if (!authRetried) {
                                authRetried = true
                                // The HTTP call refreshes an expired access token; the retry carries the new one.
                                poll()
                                connect()
                            }
                            else -> scheduleReconnect()
                        }
                    }
                    Event.PollTick -> if (!socketLive) poll()
                    Event.Reconnect -> {
                        reconnect = null
                        if (!windowClosed) connect()
                    }
                }
            }
        } finally {
            ticker.cancel()
            reconnect?.cancel()
            socket?.close()
            socket = null
            update { it.copy(transport = LiveTransport.IDLE) }
        }
    }

    companion object {
        const val POLL_MS = 15_000L
        const val RECONNECT_BASE_MS = 5_000L
        const val RECONNECT_MAX_MS = 60_000L
        const val CLOSE_AUTH = 4401
        const val CLOSE_WINDOW = 4403
        const val CLOSE_NOT_FOUND = 4404
        const val TYPE_POINT = "tracking.point"
        const val TYPE_STALE = "tracking.stale"
        const val WINDOW_NOT_OPEN = "TRACKING_WINDOW_NOT_OPEN"
        const val FEATURE_DISABLED = "FEATURE_DISABLED"
        const val NOT_FOUND = "NOT_FOUND"
        const val WINDOW_UNKNOWN = "not_yet_open"
        val FINAL_REASONS = setOf("booking_finished", "trip_finished")
    }
}
