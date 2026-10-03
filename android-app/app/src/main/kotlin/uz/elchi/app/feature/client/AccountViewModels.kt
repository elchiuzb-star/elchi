package uz.elchi.app.feature.client

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import uz.elchi.app.api.AccountApi
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.AuthApi
import uz.elchi.app.api.BookingClientDTO
import uz.elchi.app.api.generated.AccountDeletionRequest
import uz.elchi.app.api.generated.AttributionRequest
import uz.elchi.app.api.generated.BlockDTO
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.api.generated.MyReferralsDTO
import uz.elchi.app.api.generated.NotificationDTO
import uz.elchi.app.api.generated.PromoBalanceDTO
import uz.elchi.app.api.generated.ReferralCodeDTO
import uz.elchi.app.api.generated.ReportDTO
import uz.elchi.app.api.generated.SupportContactsDTO
import uz.elchi.app.api.generated.SupportThreadDTO
import uz.elchi.app.api.generated.SupportTicketCreate
import uz.elchi.app.api.generated.SupportTicketDTO
import uz.elchi.app.api.generated.SupportTicketKind
import uz.elchi.app.deeplink.PendingReferral
import uz.elchi.app.deeplink.ReferralRules
import uz.elchi.app.session.SessionStore
import uz.elchi.app.ui.components.BannerCenter
import uz.elchi.app.ui.components.BannerText
import uz.elchi.app.ui.components.BannerTone
import java.time.Instant
import java.util.UUID

/** One `Idempotency-Key` per user action, reused on a retry of that same action until a definite answer. */
internal class ActionKeys {
    private val keys = mutableMapOf<String, String>()

    fun key(scope: String): String = keys.getOrPut(scope) { UUID.randomUUID().toString() }

    /** Forget the key once the server answered for sure (success or a refusal it stored), so the next try is new. */
    fun done(scope: String) {
        keys.remove(scope)
    }

    /** A timeout or a 5xx may still have landed: keep the key. Any other 4xx is a definite refusal. */
    fun settle(scope: String, error: Throwable?) {
        if (error == null || (error is ApiException && error.status in 400..499 && error.code != "IDEMPOTENCY_IN_PROGRESS")) done(scope)
    }
}

private suspend fun <T> attempt(block: suspend () -> T): Result<T> = try {
    Result.success(block())
} catch (e: CancellationException) {
    throw e
} catch (e: Exception) {
    Result.failure(e)
}

/**
 * `client-notifications` and the unread dot on the menu. `GET /notifications` pages by cursor; v2 has no
 * unread-count or read-all endpoint, so the dot comes from the first page of `unread=true` - read when home
 * appears and when the drawer opens, never on a timer.
 */
class InboxViewModel(private val api: ElchiApi) : ViewModel() {

    data class State(
        val items: List<NotificationDTO> = emptyList(),
        val loaded: Boolean = false,
        val error: Throwable? = null,
        val next: String? = null,
        val loadingMore: Boolean = false,
        val refreshing: Boolean = false,
        /** Unread items on the first `unread=true` page; [unreadMore] = that page was full. */
        val unread: Int = 0,
        val unreadMore: Boolean = false,
    )

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()

    fun refreshUnread() {
        viewModelScope.launch {
            attempt { api.listNotifications(unread = true, limit = PAGE) }.onSuccess { page ->
                _state.update { it.copy(unread = page.data.count { n -> !n.isRead }, unreadMore = page.meta?.nextCursor != null) }
            }
        }
    }

    fun refresh() {
        if (_state.value.refreshing) return
        _state.update { it.copy(refreshing = true) }
        viewModelScope.launch {
            attempt { api.listNotifications(limit = PAGE) }
                .onSuccess { page -> _state.update { it.copy(items = page.data, next = page.meta?.nextCursor, loaded = true, error = null) } }
                .onFailure { e -> _state.update { if (it.loaded) it else it.copy(error = e) } }
            _state.update { it.copy(refreshing = false) }
            refreshUnread()
        }
    }

    fun loadMore() {
        val s = _state.value
        val cursor = s.next ?: return
        if (s.loadingMore) return
        _state.update { it.copy(loadingMore = true) }
        viewModelScope.launch {
            attempt { api.listNotifications(cursor = cursor, limit = PAGE) }
                .onSuccess { page -> _state.update { it.copy(items = InboxRules.merge(it.items, page.data), next = page.meta?.nextCursor, loadingMore = false) } }
                .onFailure { _state.update { it.copy(loadingMore = false) } }
        }
    }

    /**
     * A push tap without a screen of its own: the newest matching item on the first page ([InboxRules.pushMatch]),
     * opened like a tap on its row (so it is also marked read). Null when none matches or the page cannot be read.
     */
    suspend fun openLatest(event: String, ref: String?): InboxTarget? {
        val items = attempt { api.listNotifications(limit = PAGE) }.getOrNull()?.data ?: return null
        val item = InboxRules.pushMatch(items, event, ref) ?: return null
        return open(item)
    }

    /** Marks [item] read (locally at once; the server call's failure is ignored) and says where it leads. */
    fun open(item: NotificationDTO): InboxTarget? {
        if (!item.isRead) {
            _state.update { it.copy(items = InboxRules.markRead(it.items, item.id), unread = (it.unread - 1).coerceAtLeast(0)) }
            viewModelScope.launch { attempt { api.readNotification(item.id) } }
        }
        return InboxRules.parseLink(item.link, item.params)
    }

    /**
     * "Hammasini o'qilgan deb belgilash" (§9): v2 has no read-all endpoint, so each loaded unread row is marked read
     * (at most one page, side by side); the list reads as read at once and a failed call is not undone.
     */
    fun readAll() {
        val unread = _state.value.items.filter { !it.isRead }.take(PAGE.toInt())
        if (unread.isEmpty()) return
        _state.update { s -> s.copy(items = s.items.map { if (it.isRead) it else it.copy(isRead = true) }, unread = 0, unreadMore = false) }
        viewModelScope.launch {
            unread.map { item -> async { attempt { api.readNotification(item.id) } } }.awaitAll()
            refreshUnread()
        }
    }

    private companion object {
        const val PAGE = 30L
    }
}

/**
 * `client-profile`: the numbers (v2 only, first page of each list, [ProfileRules.stats]) and the name. v2 has no
 * profile PATCH: the name goes to `PATCH /api/v1/client/profile`, then `GET /api/v1/auth/me` refreshes the stored
 * session so the drawer and home greet the person by the new name.
 */
class ProfileViewModel(
    private val api: ElchiApi,
    private val account: AccountApi,
    private val auth: AuthApi,
    private val sessions: SessionStore,
    private val now: () -> Instant = Instant::now,
) : ViewModel() {

    enum class Saved { OK }

    data class State(
        val stats: Load<ProfileStats> = Load.Loading,
        val name: String = "",
        val saving: Boolean = false,
        val saved: Saved? = null,
        val saveError: Throwable? = null,
        /** "Saqlash" was tapped with fewer than 2 letters: red border and "Kamida 2 ta harf kiriting." until edited. */
        val nameTooShort: Boolean = false,
    )

    private val _state = MutableStateFlow(State(name = sessions.current()?.user?.fullName.orEmpty()))
    val state: StateFlow<State> = _state.asStateFlow()

    init {
        load()
    }

    fun load() {
        viewModelScope.launch {
            val listings = async { attempt { api.listMyListings(limit = PAGE).data } }
            val bookings = async { attempt { api.listMyBookings(role = CLIENT, limit = PAGE).data.mapNotNull(BookingClientDTO::fromJson) } }
            val l = listings.await()
            val b = bookings.await()
            val error = l.exceptionOrNull() ?: b.exceptionOrNull()
            if (error != null) {
                _state.update { it.copy(stats = Load.Failed(error)) }
                return@launch
            }
            val mine = l.getOrThrow()
            val live = mine.filter { OrderRules.isLive(it.status) }.take(THREADS_FOR)
            val threads = live.map { listing -> async { attempt { listing.id to api.listListingProposals(listing.id, limit = PAGE).data } } }.awaitAll()
            // One failed offers call makes the offer count unknown ("—"), not smaller than it is.
            val byListing = if (threads.all { it.isSuccess }) threads.associate { it.getOrThrow() } else null
            _state.update { it.copy(stats = Load.Ready(ProfileRules.stats(mine, b.getOrThrow(), byListing, now()))) }
        }
    }

    fun setName(value: String) = _state.update { it.copy(name = value.take(NAME_MAX), saved = null, saveError = null, nameTooShort = false) }

    fun saveName() {
        val s = _state.value
        val name = ProfileRules.nameToSave(s.name, sessions.current()?.user?.fullName) ?: return
        if (s.saving) return
        if (ProfileRules.nameTooShort(name)) {
            _state.update { it.copy(nameTooShort = true, saved = null, saveError = null) }
            return
        }
        _state.update { it.copy(saving = true, saved = null, saveError = null) }
        viewModelScope.launch {
            attempt { account.updateClientName(name) }
                .onSuccess { profile ->
                    val saved = profile.fullName ?: name
                    // The stored session is what the drawer and home read; `/auth/me` is the source, the answer the fallback.
                    val user = attempt { auth.me() }.getOrNull()
                    sessions.current()?.let { session -> sessions.save(session.copy(user = user ?: session.user.copy(fullName = saved))) }
                    _state.update { it.copy(saving = false, saved = Saved.OK, name = user?.fullName ?: saved) }
                }
                .onFailure { e -> _state.update { it.copy(saving = false, saveError = e) } }
        }
    }

    private companion object {
        const val CLIENT = "client"
        const val PAGE = 50L
        const val THREADS_FOR = 10
        const val NAME_MAX = 120
    }
}

/**
 * `client-bonus` (web `BonusScreen`): balance, own code, entering a friend's code, campaigns. With promotions
 * switched off (`403 FEATURE_DISABLED`, `promotions_enabled`) only the balance stays: code, entry and campaigns
 * hide and the screen says the programme is off. Nothing here promises a parcel reward (Q131/Q147).
 */
class BonusViewModel(
    private val api: ElchiApi,
    private val referral: PendingReferral? = null,
    /** `client` (Stage 05 "Bonuslar") or `driver` (Stage 09 "Kredit va taklif kodi"). */
    val audience: String = AUDIENCE,
    /** Where "Kod nusxalandi: {code}" shows (design 05 toast); null = nowhere (tests). */
    private val banners: BannerCenter? = null,
) : ViewModel() {

    data class State(
        val balance: Load<PromoBalanceDTO> = Load.Loading,
        val referrals: Load<MyReferralsDTO> = Load.Loading,
        val code: ReferralCodeDTO? = null,
        val codeLoading: Boolean = true,
        val codeError: Throwable? = null,
        val programOff: Boolean = false,
        val entered: String = "",
        val entering: Boolean = false,
        val enterError: Throwable? = null,
        val accepted: Boolean = false,
        /** The code the server just accepted ("Kod qabul qilindi: {code}"). */
        val acceptedCode: String? = null,
        val audience: String = AUDIENCE,
    ) {
        val hasAttribution: Boolean get() = (referrals as? Load.Ready)?.value?.attributions?.any { it.audience == audience } == true

        /** Why the typed code cannot go yet (format, or the caller's own code); null = fine or not finished. */
        val entryErrorKey: String? get() = PromoRules.entryErrorKey(entered, code?.code)

        /** The code to send: a valid code that is not the caller's own. */
        val normalized: String? get() = PromoRules.normalizeCode(entered)?.takeIf { entryErrorKey == null }
    }

    // A code kept from a link (`elchi.../r/<code>`) is already in the field; the person still confirms it.
    private val _state = MutableStateFlow(State(entered = referral?.pending?.value?.let(PromoRules::typedCode).orEmpty(), audience = audience))
    val state: StateFlow<State> = _state.asStateFlow()
    private val keys = ActionKeys()

    init {
        refresh()
        // A link that arrives while this screen is open fills an empty field.
        referral?.let { store ->
            viewModelScope.launch {
                store.pending.collect { code ->
                    if (code != null) _state.update { if (it.entered.isEmpty() && !it.accepted) it.copy(entered = PromoRules.typedCode(code)) else it }
                }
            }
        }
    }

    fun refresh() {
        viewModelScope.launch {
            val balance = async { attempt { api.myPromoBalance().data } }
            val referrals = async { attempt { api.myReferrals().data } }
            balance.await().fold({ b -> _state.update { it.copy(balance = Load.Ready(b)) } }, { e -> _state.update { it.copy(balance = Load.Failed(e)) } })
            referrals.await().fold(
                { r ->
                    _state.update { it.copy(referrals = Load.Ready(r)) }
                    // Already attributed (the first attribution is never replaced): a kept code can no longer apply.
                    if (_state.value.hasAttribution) referral?.forget()
                },
                { e -> _state.update { it.copy(referrals = Load.Failed(e), programOff = it.programOff || PromoRules.isProgramOff(e)) } },
            )
        }
        loadCode()
    }

    /** `POST /me/referral-code`: the caller's code, made on first use (one key until the server answered). */
    fun loadCode() {
        _state.update { it.copy(codeLoading = true, codeError = null) }
        viewModelScope.launch {
            val result = attempt { api.myReferralCode(keys.key(CODE_SCOPE)).data }
            keys.settle(CODE_SCOPE, result.exceptionOrNull())
            result.fold(
                { code -> _state.update { it.copy(code = code, codeLoading = false, programOff = false) } },
                { e -> _state.update { it.copy(codeLoading = false, codeError = e.takeUnless(PromoRules::isProgramOff), programOff = it.programOff || PromoRules.isProgramOff(e)) } },
            )
        }
    }

    fun setEntered(value: String) = _state.update { it.copy(entered = PromoRules.typedCode(value), enterError = null, accepted = false, acceptedCode = null) }

    /** "Kodni nusxalash" put [code] on the clipboard: say so (design 05 "Kod nusxalandi: {code}"). */
    fun markCopied(code: String) {
        banners?.show(BannerTone.OK, BannerText.Key("client.bonus.codeCopied", params = mapOf("code" to code)))
    }

    fun submitCode() {
        val s = _state.value
        val code = s.normalized ?: return
        if (s.entering) return
        val scope = "attribute:$audience:$code"
        _state.update { it.copy(entering = true, enterError = null) }
        viewModelScope.launch {
            val result = attempt { api.attribute(AttributionRequest(audience = audience, code = code), keys.key(scope)) }
            keys.settle(scope, result.exceptionOrNull())
            // Made, or refused for good: the kept code is forgotten; the programme being off keeps it for later.
            referral?.let { if (ReferralRules.forgetAfter(result.exceptionOrNull(), code, it.pending.value)) it.forget() }
            result.fold(
                {
                    _state.update { it.copy(entering = false, accepted = true, acceptedCode = code, entered = "") }
                    attempt { api.myReferrals().data }.onSuccess { r -> _state.update { it.copy(referrals = Load.Ready(r)) } }
                },
                { e -> _state.update { it.copy(entering = false, enterError = e.takeUnless(PromoRules::isProgramOff), programOff = it.programOff || PromoRules.isProgramOff(e)) } },
            )
        }
    }

    companion object {
        const val AUDIENCE = "client"
        const val DRIVER_AUDIENCE = "driver"
        private const val CODE_SCOPE = "referral-code"
    }
}

/**
 * `safety-center` (web `BlockAndReportPanel`): the people I blocked and the reports I sent. Unblock sends
 * `DELETE /blocks/{user_id}` with an `Idempotency-Key`; a refusal keeps the row and says why - never a fake success
 * (the backend currently refuses it, `IDEMPOTENCY_KEY_REQUIRED`, see the report).
 */
class SafetyCenterViewModel(
    private val api: ElchiApi,
    /** Where "Blokdan chiqarildi" shows once the server agreed (design 05 toast); null = nowhere (tests). */
    private val banners: BannerCenter? = null,
) : ViewModel() {

    data class State(
        val blocks: Load<List<BlockDTO>> = Load.Loading,
        val reports: Paged<ReportDTO> = Paged(),
        val refreshing: Boolean = false,
        val unblocking: String? = null,
        /** The last failed unblock: the user id and why. */
        val unblockError: Pair<String, Throwable>? = null,
    )

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()
    private val keys = ActionKeys()

    init {
        refresh()
    }

    fun refresh() {
        _state.update { it.copy(refreshing = true) }
        viewModelScope.launch {
            val blocks = async { attempt { api.listBlocks().data } }
            val reports = async { attempt { api.listMyReports(limit = PAGE) } }
            val b = blocks.await()
            val r = reports.await()
            _state.update { s ->
                s.copy(
                    blocks = b.fold({ Load.Ready(it) }, { e -> if (s.blocks is Load.Ready) s.blocks else Load.Failed(e) }),
                    reports = r.fold({ Paged(it.data, loaded = true, next = it.meta?.nextCursor) }, { e -> if (s.reports.loaded && s.reports.error == null) s.reports else Paged(loaded = true, error = e) }),
                    refreshing = false,
                )
            }
        }
    }

    fun loadMoreReports() {
        val page = _state.value.reports
        val cursor = page.next ?: return
        if (page.loadingMore) return
        _state.update { it.copy(reports = it.reports.copy(loadingMore = true)) }
        viewModelScope.launch {
            attempt { api.listMyReports(cursor = cursor, limit = PAGE) }
                .onSuccess { r -> _state.update { s -> s.copy(reports = s.reports.copy(items = s.reports.items + r.data.filter { n -> s.reports.items.none { it.id == n.id } }, next = r.meta?.nextCursor, loadingMore = false)) } }
                .onFailure { _state.update { s -> s.copy(reports = s.reports.copy(loadingMore = false)) } }
        }
    }

    fun unblock(userId: String) {
        if (_state.value.unblocking != null) return
        val scope = "unblock:$userId"
        _state.update { it.copy(unblocking = userId, unblockError = null) }
        viewModelScope.launch {
            val result = attempt { api.deleteBlock(userId, keys.key(scope)) }
            keys.settle(scope, result.exceptionOrNull())
            result.fold(
                {
                    _state.update { s -> s.copy(unblocking = null, blocks = (s.blocks as? Load.Ready)?.let { Load.Ready(it.value.filterNot { b -> b.userId == userId }) } ?: s.blocks) }
                    banners?.show(BannerTone.OK, BannerText.Key("client.profile.unblocked"))
                },
                { e -> _state.update { it.copy(unblocking = null, unblockError = userId to e) } },
            )
        }
    }

    private companion object {
        const val PAGE = 20L
    }
}

/**
 * `support` "Yordam": who can be reached (S13; Q87: no line in the pilot, no hours promised), a ticket form and
 * my tickets. Tickets have no replies (no thread screen); the operator conversations are [SupportThreadsViewModel].
 * Contacts fail quietly - "no line" is also the truthful pilot answer.
 */
class HelpViewModel(private val api: ElchiApi) : ViewModel() {

    data class State(
        val contacts: SupportContactsDTO? = null,
        val tickets: Load<List<SupportTicketDTO>> = Load.Loading,
        /** The operator conversations, newest first (design 05: "Murojaatlarim · Hammasi (n)" + the newest card). */
        val threads: Load<List<SupportThreadDTO>> = Load.Loading,
        val draft: String = "",
        val sending: Boolean = false,
        val sent: Boolean = false,
        val sendError: Throwable? = null,
        val refreshing: Boolean = false,
    )

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()
    private val keys = ActionKeys()

    init {
        refresh()
    }

    fun refresh() {
        _state.update { it.copy(refreshing = true) }
        viewModelScope.launch {
            val contacts = async { attempt { api.supportContacts().data }.getOrNull() }
            val tickets = async { attempt { api.listMyTickets(limit = PAGE).data } }
            val threads = async { attempt { SupportThreadsViewModel.newestFirst(api.listMySupportThreads(limit = SupportThreadsViewModel.LIMIT).data) } }
            val c = contacts.await()
            val t = tickets.await()
            val th = threads.await()
            _state.update { s ->
                s.copy(
                    contacts = c ?: s.contacts,
                    tickets = t.fold({ Load.Ready(it) }, { e -> if (s.tickets is Load.Ready) s.tickets else Load.Failed(e) }),
                    threads = th.fold({ Load.Ready(it) }, { e -> if (s.threads is Load.Ready) s.threads else Load.Failed(e) }),
                    refreshing = false,
                )
            }
        }
    }

    fun setDraft(value: String) = _state.update { it.copy(draft = value.take(SafetyRules.TICKET_MAX), sent = false, sendError = null) }

    fun send() {
        val s = _state.value
        val text = s.draft.trim()
        if (!SafetyRules.ticketReady(text) || s.sending) return
        val scope = "ticket:$text"
        _state.update { it.copy(sending = true, sendError = null, sent = false) }
        viewModelScope.launch {
            val result = attempt { api.createSupportTicket(SupportTicketCreate(bookingId = null, kind = SupportTicketKind.SUPPORT, message = text), keys.key(scope)).data }
            keys.settle(scope, result.exceptionOrNull())
            result.fold(
                { ticket ->
                    _state.update { st ->
                        val list = (st.tickets as? Load.Ready)?.value.orEmpty().filterNot { it.id == ticket.id }
                        st.copy(sending = false, sent = true, draft = "", tickets = Load.Ready(listOf(ticket) + list))
                    }
                },
                { e -> _state.update { it.copy(sending = false, sendError = e) } },
            )
        }
    }

    private companion object {
        const val PAGE = 20L
    }
}

/** `my-support-threads` "Murojaatlarim": every operator conversation of mine (each belongs to a booking). */
class SupportThreadsViewModel(
    private val api: ElchiApi,
    /** Where the bar's refresh button says "Yangilandi" (design 05 toast); null = nowhere (tests). */
    private val banners: BannerCenter? = null,
) : ViewModel() {

    data class State(val threads: Load<List<SupportThreadDTO>> = Load.Loading, val refreshing: Boolean = false)

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()

    /** [announce]: the bar's refresh button was tapped - a success says "Yangilandi", a failure the reason. */
    fun refresh(announce: Boolean = false) {
        _state.update { it.copy(refreshing = true) }
        viewModelScope.launch {
            val result = attempt { newestFirst(api.listMySupportThreads(limit = LIMIT).data) }
            _state.update { s ->
                s.copy(
                    threads = result.fold({ Load.Ready(it) }, { e -> if (s.threads is Load.Ready) s.threads else Load.Failed(e) }),
                    refreshing = false,
                )
            }
            if (announce) result.fold({ banners?.show(BannerTone.OK, BannerText.Key("client.booking.refreshed")) }, { e -> banners?.error(e) })
        }
    }

    companion object {
        const val LIMIT = 50L

        /** Newest first: the conversation that moved last is the one to read. */
        fun newestFirst(list: List<SupportThreadDTO>): List<SupportThreadDTO> = list.sortedByDescending { OrderRules.parseInstant(it.createdAt) ?: Instant.MIN }
    }
}

/**
 * `account-delete`: `DELETE /me` (body `{}`, `Idempotency-Key`). The server anonymises at once and revokes the
 * tokens; a refusal lists what is still open ([DeletionRules.blockers]).
 * [beforeDelete] runs while the session still works (the push device is revoked then: afterwards no call can be
 * made); [afterRefusal] undoes it when the server definitely said no.
 */
class AccountDeleteViewModel(
    private val api: ElchiApi,
    private val beforeDelete: suspend () -> Unit = {},
    private val afterRefusal: () -> Unit = {},
) : ViewModel() {

    data class State(
        val confirmed: Boolean = false,
        val submitting: Boolean = false,
        val blockers: List<DeletionBlocker>? = null,
        val error: Throwable? = null,
    )

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()
    private val keys = ActionKeys()

    fun setConfirmed(value: Boolean) = _state.update { it.copy(confirmed = value) }

    fun submit(onDeleted: () -> Unit) {
        val s = _state.value
        if (!s.confirmed || s.submitting) return
        _state.update { it.copy(submitting = true, error = null, blockers = null) }
        viewModelScope.launch {
            attempt { beforeDelete() }
            val result = attempt { api.deleteMe(AccountDeletionRequest(), keys.key(SCOPE)) }
            keys.settle(SCOPE, result.exceptionOrNull())
            // A timeout may still have deleted the account: only a definite 4xx brings the push device back.
            (result.exceptionOrNull() as? ApiException)?.takeIf { it.status in 400..499 }?.let { afterRefusal() }
            result.fold(
                {
                    _state.update { it.copy(submitting = false) }
                    onDeleted()
                },
                { e ->
                    val blocked = e is ApiException && e.code == DeletionRules.BLOCKED
                    _state.update { it.copy(submitting = false, blockers = if (blocked) DeletionRules.blockers((e as ApiException).details) else null, error = if (blocked) null else e) }
                },
            )
        }
    }

    private companion object {
        const val SCOPE = "delete-me"
    }
}
