package uz.elchi.app.feature.client

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.BookingClientDTO
import uz.elchi.app.api.generated.ApiWarning
import uz.elchi.app.api.generated.ChatMessageCreate
import uz.elchi.app.api.generated.ChatMessageDTO
import uz.elchi.app.api.generated.ChatThreadDTO
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.api.generated.QuickReplyCode
import uz.elchi.app.api.generated.SupportMessageCreate
import uz.elchi.app.api.generated.SupportThreadDTO
import uz.elchi.app.api.generated.SupportThreadOpen
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

/**
 * How many messages the booking chat had when this phone last had it open (design 04's unread badge on the driver
 * bar). There is no server unread count; this lives for the app's process only.
 */
object ChatSeenCounts {
    private val seen = ConcurrentHashMap<String, Long>()

    fun seen(bookingId: String): Long? = seen[bookingId]

    fun mark(bookingId: String, count: Long?) {
        if (count != null) seen[bookingId] = count
    }

    /** One more message this phone sent itself: never counted as unread. */
    fun bump(bookingId: String) {
        seen.computeIfPresent(bookingId) { _, n -> n + 1 }
    }
}

/**
 * `booking-chat` "Xabarlar" (Q100: the client's only chat is the booking's). There is no realtime channel for chat,
 * so the newest page is polled while the screen is started ([watch]); pages and polls are merged by id. A message
 * being sent is shown at once and keeps its `Idempotency-Key` until the server answered: a retry after a timeout can
 * never post it twice.
 */
class BookingChatViewModel(private val api: ElchiApi, val bookingId: String) : ViewModel() {

    data class State(
        val chat: ChatThreadDTO? = null,
        /** Oldest first. */
        val messages: List<ChatMessageDTO> = emptyList(),
        val loaded: Boolean = false,
        val loadError: Throwable? = null,
        /** `meta.next_cursor` of the oldest page read: older messages exist. */
        val olderCursor: String? = null,
        val loadingOlder: Boolean = false,
        val refreshing: Boolean = false,
        val draft: String = "",
        val outgoing: List<OutgoingMessage> = emptyList(),
        /**
         * Warnings of this phone's sends, by message id (CONTACT_INFO_MASKED: contacts were hidden before the driver
         * saw them) - said under the message they belong to.
         */
        val warnings: Map<String, List<ApiWarning>> = emptyMap(),
        /** Messages from the driver that arrived by polling and are not yet seen (the "Yangi xabar" pill). */
        val unseen: Int = 0,
        /** Bumped when a new message should bring the list to its end (own send, a poll while at the end). */
        val scrollNonce: Int = 0,
        /** The booking (design 04: the bar's "Jasur · Chevrolet Cobalt", "Kelishuv tuzildi", the closed reason). */
        val booking: BookingClientDTO? = null,
    ) {
        /** Unknown until the state is read: the composer waits rather than offering a closed chat. */
        val writable: Boolean get() = chat?.writable == true
    }

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        _state.update { it.copy(refreshing = true) }
        viewModelScope.launch {
            load(first = !_state.value.loaded)
            _state.update { it.copy(refreshing = false) }
        }
        viewModelScope.launch {
            runCatching { BookingClientDTO.anySide(api.getBooking(bookingId).data) }
                .onSuccess { booking -> if (booking != null) _state.update { it.copy(booking = booking) } }
                .onFailure { if (it is CancellationException) throw it }
        }
    }

    /** Polls while the caller's coroutine lives (the screen, while started). */
    suspend fun watch() {
        while (true) {
            delay(POLL_MS)
            load(first = false)
        }
    }

    private suspend fun load(first: Boolean) {
        try {
            val chat = api.getBookingChatState(bookingId).data
            val page = api.listBookingMessages(bookingId, limit = PAGE)
            // Read while the chat is open: the detail's badge counts from here.
            ChatSeenCounts.mark(bookingId, chat.messageCount)
            _state.update { s ->
                val merged = BookingRules.mergeMessages(s.messages, page.data)
                val fresh = if (first) 0 else BookingRules.newFromOthers(s.messages, merged)
                s.copy(
                    chat = chat,
                    messages = merged,
                    loaded = true,
                    loadError = null,
                    // Only the first read sets where "older" starts; a poll's cursor is its own newest page.
                    olderCursor = if (first) page.meta?.nextCursor else s.olderCursor,
                    unseen = s.unseen + fresh,
                    scrollNonce = if (first) s.scrollNonce + 1 else s.scrollNonce,
                )
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            _state.update { if (it.loaded) it else it.copy(loadError = e, loaded = false) }
        }
    }

    fun loadOlder() {
        val cursor = _state.value.olderCursor ?: return
        if (_state.value.loadingOlder) return
        _state.update { it.copy(loadingOlder = true) }
        viewModelScope.launch {
            try {
                val page = api.listBookingMessages(bookingId, cursor = cursor, limit = PAGE)
                _state.update { it.copy(messages = BookingRules.mergeMessages(it.messages, page.data), olderCursor = page.meta?.nextCursor, loadingOlder = false) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(loadingOlder = false) }
            }
        }
    }

    fun markSeen() = _state.update { if (it.unseen == 0) it else it.copy(unseen = 0) }

    fun setDraft(text: String) = _state.update { it.copy(draft = text.take(TEXT_MAX)) }

    fun sendDraft() {
        val text = _state.value.draft.trim()
        if (text.isEmpty()) return
        _state.update { it.copy(draft = "") }
        post(OutgoingMessage(UUID.randomUUID().toString(), text, null, UUID.randomUUID().toString()))
    }

    /** Q100 client quick replies: `at_stop`, `clarify_stop` (never `price_agreed` - the price is agreed). */
    fun sendQuick(code: QuickReplyCode) = post(OutgoingMessage(UUID.randomUUID().toString(), null, code.value, UUID.randomUUID().toString()))

    fun retry(localId: String) {
        val message = _state.value.outgoing.firstOrNull { it.localId == localId && it.failed } ?: return
        post(message.copy(failed = false, error = null))
    }

    fun discard(localId: String) = _state.update { s -> s.copy(outgoing = s.outgoing.filterNot { it.localId == localId }) }

    private fun post(message: OutgoingMessage) {
        _state.update { s -> s.copy(outgoing = s.outgoing.filterNot { it.localId == message.localId } + message, scrollNonce = s.scrollNonce + 1) }
        viewModelScope.launch {
            try {
                val body = ChatMessageCreate(text = message.text, quickReplyCode = message.quickReply?.let { code -> QuickReplyCode.entries.first { it.value == code } })
                val result = api.postBookingMessage(bookingId, body, message.idempotencyKey)
                ChatSeenCounts.bump(bookingId)
                _state.update { s ->
                    s.copy(
                        messages = BookingRules.mergeMessages(s.messages, listOf(result.data)),
                        outgoing = s.outgoing.filterNot { it.localId == message.localId },
                        warnings = if (result.warnings.isEmpty()) s.warnings else s.warnings + (result.data.id to result.warnings),
                        scrollNonce = s.scrollNonce + 1,
                    )
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                // A definite refusal is stored under its key on the server (a replay would answer the same), so the
                // retry of such a message gets a new key; a timeout or 5xx keeps the key and cannot double-post.
                val definite = e is ApiException && e.status in 400..499 && e.code != "IDEMPOTENCY_IN_PROGRESS"
                _state.update { s ->
                    s.copy(outgoing = s.outgoing.map {
                        if (it.localId != message.localId) it
                        else it.copy(failed = true, error = e, idempotencyKey = if (definite) UUID.randomUUID().toString() else it.idempotencyKey)
                    })
                }
                if (e is ApiException && e.code == CHAT_CLOSED) load(first = false)
            }
        }
    }

    companion object {
        /** No realtime exists for chat: the newest page every 12 s while the screen is open (spec 10-15 s). */
        const val POLL_MS = 12_000L
        private const val PAGE = 30L
        const val TEXT_MAX = 1000
        const val CHAT_CLOSED = "CHAT_CLOSED"
    }
}

/**
 * "Yordam / shikoyat" (Q141/Q146): the operator chat of this booking. `GET .../support-thread` says whether one is
 * open (null = none yet); the first message opens it (`POST .../support-thread`, open-or-return), later ones go to
 * the thread. A closed thread stays readable; "Yangi murojaat" opens a new one. Polled every 15 s while started.
 * Stage 05: also opened by [threadId] ("Murojaatlarim", an inbox link) - that thread is shown, closed or not, until
 * a new request replaces it; every thread belongs to a booking, so "Yangi murojaat" still opens one for it.
 */
class SupportViewModel(private val api: ElchiApi, private val bookingId: String?, threadId: String? = null) : ViewModel() {

    data class State(
        val thread: SupportThreadDTO? = null,
        val loaded: Boolean = false,
        val loadError: Throwable? = null,
        val refreshing: Boolean = false,
        val draft: String = "",
        val sending: Boolean = false,
        /** The last send failed; the text stays in the field, and sending it unchanged reuses its key. */
        val sendError: Throwable? = null,
        val warnings: List<ApiWarning> = emptyList(),
        /** The person asked for a new request after a closed one: the composer opens a fresh thread. */
        val startingNew: Boolean = false,
        val scrollNonce: Int = 0,
    ) {
        val closed: Boolean get() = thread?.status == CLOSED
        val canWrite: Boolean get() = thread == null || !closed || startingNew
    }

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()
    private var key: Pair<String, String>? = null
    /** The thread this screen was opened for; cleared when a new request makes another one current. */
    private var pinned: String? = threadId

    init {
        refresh()
    }

    /** The booking the conversation belongs to: given, or the loaded thread's. */
    private fun booking(): String? = bookingId ?: _state.value.thread?.bookingId

    fun refresh() {
        _state.update { it.copy(refreshing = true) }
        viewModelScope.launch {
            load()
            _state.update { it.copy(refreshing = false) }
        }
    }

    suspend fun watch() {
        while (true) {
            delay(POLL_MS)
            load()
        }
    }

    private suspend fun load() {
        try {
            val current = _state.value.thread
            val pinnedId = pinned
            // An open thread is read by its id; a thread opened by id stays that thread; otherwise the booking says
            // which one is current (maybe none).
            val thread = when {
                current != null && current.status != CLOSED -> api.getSupportThread(current.id).data
                pinnedId != null -> api.getSupportThread(pinnedId).data
                else -> booking()?.let { api.getBookingSupportThread(it).data }
            }
            _state.update { s ->
                val grew = (thread?.messages?.size ?: 0) > (s.thread?.messages?.size ?: 0)
                // While a new request is being written, a closed old thread stays what the screen shows.
                if (s.startingNew && thread?.status == CLOSED) s.copy(loaded = true, loadError = null)
                else s.copy(thread = thread, loaded = true, loadError = null, startingNew = if (thread != null && thread.status != CLOSED) false else s.startingNew, scrollNonce = if (grew) s.scrollNonce + 1 else s.scrollNonce)
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            _state.update { if (it.loaded) it else it.copy(loadError = e) }
        }
    }

    fun setDraft(text: String) = _state.update { it.copy(draft = text.take(TEXT_MAX)) }

    fun startNew() = _state.update { it.copy(startingNew = true, draft = "", sendError = null) }

    fun send() {
        val s = _state.value
        val text = s.draft.trim()
        if (text.isEmpty() || s.sending || !s.canWrite) return
        _state.update { it.copy(sending = true, sendError = null) }
        val thread = s.thread?.takeIf { it.status != CLOSED }
        val booking = booking()
        if (thread == null && booking == null) return
        val scope = "${thread?.id ?: "open"}:$text"
        val idem = key?.takeIf { it.first == scope }?.second ?: UUID.randomUUID().toString().also { key = scope to it }
        viewModelScope.launch {
            try {
                val result = if (thread == null) api.openSupportThread(booking!!, SupportThreadOpen(text = text), idem)
                else api.postSupportMessage(thread.id, SupportMessageCreate(text = text), idem)
                key = null
                pinned = null
                _state.update { it.copy(thread = result.data, sending = false, draft = "", startingNew = false, warnings = result.warnings, scrollNonce = it.scrollNonce + 1) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (e is ApiException && e.status in 400..499 && e.code != "IDEMPOTENCY_IN_PROGRESS") key = null
                _state.update { it.copy(sending = false, sendError = e) }
                if (e is ApiException && e.code == THREAD_CLOSED) load()
            }
        }
    }


    companion object {
        const val POLL_MS = 15_000L
        const val TEXT_MAX = 4000
        const val CLOSED = "closed"
        const val THREAD_CLOSED = "SUPPORT_THREAD_CLOSED"
    }
}
