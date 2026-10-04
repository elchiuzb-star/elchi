package uz.elchi.app.feature.driver

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.ElchiJson
import uz.elchi.app.api.generated.ApiWarning
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.api.generated.FeedItemDTO
import uz.elchi.app.api.generated.ListingOfferDTO
import uz.elchi.app.api.generated.ListingPublicDTO
import uz.elchi.app.api.generated.PriceBasis
import uz.elchi.app.api.generated.ProposalDecision
import uz.elchi.app.api.generated.ProposalThreadDTO
import uz.elchi.app.api.generated.TripDTO
import uz.elchi.app.api.generated.app__modules__wallet__schemas__FeeQuoteDTO as FeeQuoteDTO
import uz.elchi.app.feature.client.ActionKeys
import uz.elchi.app.feature.client.Load
import uz.elchi.app.feature.client.ParcelRules
import uz.elchi.app.ui.components.BannerCenter
import uz.elchi.app.ui.components.BannerText
import uz.elchi.app.ui.components.BannerTone
import java.time.Instant

/** The commission estimate under the price field: loading, the server's quote, or "cannot say now" (never a block). */
sealed interface FeeEstimate {
    data object None : FeeEstimate
    data object Loading : FeeEstimate
    data class Ready(val totalMinor: Long, val quote: FeeQuoteDTO) : FeeEstimate
    data object Unavailable : FeeEstimate
}

/** The last offer this driver sent, for the thread screen's notes (the band warning, a masked contact). */
data class SentOffer(val threadId: String, val warnings: List<ApiWarning>)

/**
 * The driver's offers (`GET /me/proposals?state=`), the counts the Orders tab and home show, and the shared notes
 * between the offer screen and a thread. One per driver flow.
 */
class ProposalsViewModel(private val api: ElchiApi, private val banners: BannerCenter? = null) : ViewModel() {
    data class State(
        val tab: ProposalTab = ProposalTab.OPEN,
        val lists: Map<ProposalTab, Load<List<ProposalThreadDTO>>> = emptyMap(),
        val refreshing: Boolean = false,
        /**
         * Thread id → the driver's previous total under the client's counter (design 07 §8.2). The list carries no
         * versions, so each countered thread is read once (`GET /proposals/{id}`).
         */
        val mine: Map<String, Long> = emptyMap(),
    ) {
        val current: Load<List<ProposalThreadDTO>> get() = lists[tab] ?: Load.Loading
        val open: List<ProposalThreadDTO> get() = (lists[ProposalTab.OPEN] as? Load.Ready)?.value.orEmpty()
    }

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()

    /** Set by the offer screen right before it opens the thread. */
    var lastSent: SentOffer? = null

    /** Countered thread revisions whose history was asked for (each read once). */
    private val asked = mutableSetOf<String>()

    init {
        refresh(ProposalTab.OPEN)
    }

    fun pick(tab: ProposalTab) {
        _state.update { it.copy(tab = tab) }
        refresh(tab)
    }

    /** [manual] = the bar's refresh icon: "Yangilandi" once read (design 07 §0.3). */
    fun refresh(tab: ProposalTab = _state.value.tab, manual: Boolean = false) {
        _state.update { it.copy(refreshing = true) }
        viewModelScope.launch {
            val result = tryCall { api.listMyProposals(state = tab.state, limit = PAGE).data }
            result
                .onSuccess { list -> _state.update { it.copy(lists = it.lists + (tab to Load.Ready(list))) } }
                .onFailure { e -> _state.update { s -> if (s.lists[tab] is Load.Ready) s else s.copy(lists = s.lists + (tab to Load.Failed(e))) } }
            _state.update { it.copy(refreshing = false) }
            if (manual && result.isSuccess) banners?.show(BannerTone.OK, BannerText.Key("client.booking.refreshed"))
            result.getOrNull()?.let(::readMine)
        }
    }

    /** The driver's own earlier price on each countered thread not read yet (the counter line's "siz … taklif qilgansiz"). */
    private fun readMine(list: List<ProposalThreadDTO>) {
        val now = Instant.now()
        list.filter { OfferRules.line(it, now) == ThreadLine.Countered }.forEach { thread ->
            val key = "${thread.id}:${thread.currentVersion?.revision}"
            if (key in asked) return@forEach
            asked += key
            viewModelScope.launch {
                tryCall { api.getProposal(thread.id).data }
                    .onSuccess { full -> Design07Rules.previousDriverTotal(full)?.let { total -> _state.update { it.copy(mine = it.mine + (thread.id to total)) } } }
                    .onFailure { asked -= key }
            }
        }
    }

    private companion object {
        const val PAGE = 50L
    }
}

/**
 * "Narx taklif qiling" (`POST /listings/{id}/proposals`): the request, the anonymous rival board (404 → hidden,
 * Q95), the trip it would ride, the pickup window, the price with a debounced commission estimate. A sent offer
 * opens its thread; an existing open one (`open_thread_exists`) opens instead of a second.
 */
class BidViewModel(
    private val api: ElchiApi,
    private val banners: BannerCenter,
    private val listingId: String,
    initial: FeedItemDTO?,
    private val trips: TripsViewModel,
    private val proposals: ProposalsViewModel,
    private val now: () -> Instant = Instant::now,
) : ViewModel() {
    data class State(
        val listing: Load<ListingPublicDTO> = Load.Loading,
        /** Null = the board is closed for this listing (404): not shown, offering still works. */
        val board: Load<BoardSummary>? = Load.Loading,
        val tripId: String? = null,
        val price: String = "",
        val fee: FeeEstimate = FeeEstimate.None,
        val sending: Boolean = false,
        val error: Throwable? = null,
        /** Set once: the thread to open (sent, or the one that already existed). */
        val openThread: String? = null,
        /** "Taklif narxini kiriting" under the field after a tap with no price (design 07 §7.11). */
        val priceMissing: Boolean = false,
    )

    private val _state = MutableStateFlow(State(listing = initial?.let { Load.Ready(it.listing) } ?: Load.Loading))
    val state: StateFlow<State> = _state.asStateFlow()
    private val keys = ActionKeys()
    private var feeJob: Job? = null

    init {
        initial?.let { prepare(it.listing) } ?: loadListing()
        loadBoard()
        trips.refresh()
    }

    private fun loadListing() {
        viewModelScope.launch {
            tryCall { ElchiJson.decodeFromJsonElement(ListingPublicDTO.serializer(), api.getListing(listingId).data) }
                .onSuccess { l ->
                    _state.update { it.copy(listing = Load.Ready(l)) }
                    prepare(l)
                }
                .onFailure { e -> _state.update { it.copy(listing = Load.Failed(e)) } }
        }
    }

    private fun prepare(listing: ListingPublicDTO) {
        if (_state.value.price.isEmpty()) setPrice(OfferRules.prefillPrice(listing))
    }

    fun loadBoard() {
        viewModelScope.launch {
            tryCall { api.listListingOffers(listingId, limit = 50).data }
                .onSuccess { offers -> _state.update { it.copy(board = Load.Ready(OfferRules.board(offers))) } }
                .onFailure { e -> _state.update { it.copy(board = if ((e as? ApiException)?.status == 404) null else Load.Failed(e)) } }
        }
    }

    fun candidates(all: List<TripDTO>): List<TripDTO> = OfferRules.candidateTrips(all, now())

    /** The chosen trip, else the preselected one once the trips are read. */
    fun trip(all: List<TripDTO>, listing: ListingPublicDTO): TripDTO? {
        val list = candidates(all)
        return list.firstOrNull { it.id == _state.value.tripId } ?: OfferRules.preselect(list, listing)
    }

    fun pickTrip(id: String) = _state.update { it.copy(tripId = id, error = null) }

    fun setPrice(text: String) {
        val digits = text.filter(Char::isDigit).take(MAX_DIGITS)
        _state.update { it.copy(price = digits, error = null, priceMissing = false) }
        quoteFee()
    }

    private fun totalMinor(listing: ListingPublicDTO, unitMinor: Long): Long =
        if (listing.priceBasis == PriceBasis.PER_SEAT) unitMinor * listing.quantity else unitMinor

    /** `GET /commission/quote`, 400 ms after the last keystroke. */
    private fun quoteFee() {
        feeJob?.cancel()
        val listing = (_state.value.listing as? Load.Ready)?.value
        val unit = ParcelRules.soumToMinor(_state.value.price)
        if (listing == null || unit == null || unit <= 0) {
            _state.update { it.copy(fee = FeeEstimate.None) }
            return
        }
        val total = totalMinor(listing, unit)
        _state.update { it.copy(fee = FeeEstimate.Loading) }
        feeJob = viewModelScope.launch {
            delay(FEE_DEBOUNCE_MS)
            tryCall { api.commissionQuote(listing.serviceType, total).data }
                .onSuccess { q -> _state.update { it.copy(fee = FeeEstimate.Ready(total, q)) } }
                .onFailure { _state.update { it.copy(fee = FeeEstimate.Unavailable) } }
        }
    }

    /** "Taklif yuborish" with the typed price; [clientPrice] = "Mijoz narxiga roziman" (the listing's own unit price). */
    fun send(trip: TripDTO?, clientPrice: Boolean = false) {
        val s = _state.value
        val listing = (s.listing as? Load.Ready)?.value ?: return
        if (s.sending) return
        val typed = ParcelRules.soumToMinor(s.price)?.takeIf { it > 0 }
        if (!clientPrice && typed == null) {
            _state.update { it.copy(priceMissing = true) }
            return
        }
        if (trip == null) return
        val window = OfferRules.pickupWindow(trip, listing) ?: return
        val unit = if (clientPrice) listing.unitPriceMinor else typed ?: return
        val body = OfferRules.proposalBody(listing, trip.id, window, unit)
        val scope = "offer:$listingId:${trip.id}:$unit"
        _state.update { it.copy(sending = true, error = null, tripId = trip.id) }
        banners.startAction()
        viewModelScope.launch {
            val result = tryCall { api.submitProposal(listingId, body, keys.key(scope)) }
            keys.settle(scope, result.exceptionOrNull())
            banners.endAction()
            result
                .onSuccess { r ->
                    proposals.lastSent = SentOffer(r.data.id, r.warnings)
                    val warn = r.warnings.firstOrNull()
                    if (warn != null) banners.show(BannerTone.WARN, BannerText.Key("warning.${warn.code}", fallback = warn.message))
                    else banners.show(BannerTone.OK, soumBanner("driver.offer.sentPrice", "price", r.data.currentVersion?.totalMinor ?: totalMinor(listing, unit)))
                    proposals.refresh(ProposalTab.OPEN)
                    _state.update { it.copy(sending = false, openThread = r.data.id) }
                }
                .onFailure { e ->
                    val existing = OfferRules.openThreadId(e)
                    _state.update { it.copy(sending = false, error = e.takeIf { existing == null }, openThread = existing) }
                    if (existing == null) banners.show(BannerTone.ERR, OfferRules.errorKey(e)?.let { BannerText.Key(it) } ?: BannerText.Error(e))
                }
        }
    }

    fun opened() = _state.update { it.copy(openThread = null) }

    private companion object {
        const val FEE_DEBOUNCE_MS = 400L
        const val MAX_DIGITS = 11
    }
}

/** What finished on a thread, for the screen's note. */
enum class ThreadNotice { COUNTERED, REJECTED, WITHDRAWN, ACCEPTED, TERMS_CHANGED }

/**
 * One negotiation seen by the driver (`GET /proposals/{id}`): the version history and the moves its turn allows
 * - accept the client's price (→ booking), reject, counter (while revisions remain), withdraw its own version.
 */
class ProposalThreadViewModel(
    private val api: ElchiApi,
    private val banners: BannerCenter,
    private val threadId: String,
    private val proposals: ProposalsViewModel,
    private val now: () -> Instant = Instant::now,
) : ViewModel() {
    data class State(
        val thread: Load<ProposalThreadDTO> = Load.Loading,
        val refreshing: Boolean = false,
        val busy: Boolean = false,
        val counterPrice: String = "",
        val fee: FeeEstimate = FeeEstimate.None,
        val notice: ThreadNotice? = null,
        val bookingId: String? = null,
        /** The accept must be confirmed again (the listing's terms version moved). */
        val reconfirm: Boolean = false,
        /** The counter field's refusal (empty, or the client's own price - design 07 §8.5). */
        val counterIssue: CounterIssue? = null,
        /** Set once after an accept: open this booking's chat (Q100, design 07 §8.7). */
        val openChat: String? = null,
    )

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()
    private val keys = ActionKeys()

    /** The send-time warnings of this thread's first version, if the offer screen just sent it. */
    val sentWarnings: List<ApiWarning> = proposals.lastSent?.takeIf { it.threadId == threadId }?.warnings.orEmpty()

    init {
        refresh()
    }

    /** [manual] = the bar's refresh icon: "Yangilandi" once read. */
    fun refresh(manual: Boolean = false) {
        _state.update { it.copy(refreshing = true) }
        viewModelScope.launch {
            tryCall { api.getProposal(threadId).data }
                .onSuccess { t ->
                    _state.update { it.copy(thread = Load.Ready(t), bookingId = it.bookingId ?: t.bookingId) }
                    quoteFee(t)
                    if (manual) banners.show(BannerTone.OK, BannerText.Key("client.booking.refreshed"))
                }
                .onFailure { e -> _state.update { if (it.thread is Load.Ready) it else it.copy(thread = Load.Failed(e)) } }
            _state.update { it.copy(refreshing = false) }
        }
    }

    /** The plain commission estimate on the current price (no promo quote in dev). */
    private fun quoteFee(thread: ProposalThreadDTO) {
        val v = thread.currentVersion ?: return
        if (OfferRules.driverPromo(v) != null || !OfferRules.actions(thread, now()).open) return
        viewModelScope.launch {
            _state.update { it.copy(fee = FeeEstimate.Loading) }
            tryCall { api.commissionQuote(serviceOf(thread), v.totalMinor).data }
                .onSuccess { q -> _state.update { it.copy(fee = FeeEstimate.Ready(v.totalMinor, q)) } }
                .onFailure { _state.update { it.copy(fee = FeeEstimate.Unavailable) } }
        }
    }

    /** A parcel version carries its cargo demand and no seats; a passenger one carries seats (quantity). */
    private fun serviceOf(thread: ProposalThreadDTO): uz.elchi.app.api.generated.ServiceType {
        val d = thread.currentVersion?.demand
        return if (d != null && (d.cargoWeightG > 0 || d.parcelLengthCm != null)) uz.elchi.app.api.generated.ServiceType.PARCEL
        else uz.elchi.app.api.generated.ServiceType.PASSENGER
    }

    fun setCounterPrice(text: String) = _state.update { it.copy(counterPrice = text.filter(Char::isDigit).take(11), counterIssue = null) }

    private fun current(): ProposalThreadDTO? = (_state.value.thread as? Load.Ready)?.value

    private fun command(scope: String, notice: ThreadNotice, ok: String, call: suspend (String) -> ProposalThreadDTO) {
        if (_state.value.busy) return
        _state.update { it.copy(busy = true, notice = null) }
        banners.startAction()
        viewModelScope.launch {
            val result = tryCall { call(keys.key(scope)) }
            keys.settle(scope, result.exceptionOrNull())
            banners.endAction()
            result
                .onSuccess { t ->
                    _state.update { it.copy(thread = Load.Ready(t), notice = notice, counterPrice = "", fee = FeeEstimate.None) }
                    quoteFee(t)
                    banners.show(BannerTone.OK, BannerText.Key(ok))
                    proposals.refresh()
                }
                .onFailure { e ->
                    banners.show(BannerTone.ERR, OfferRules.errorKey(e)?.let { BannerText.Key(it) } ?: BannerText.Error(e))
                    if (OfferRules.needsRefresh(e)) refresh()
                }
            _state.update { it.copy(busy = false) }
        }
    }

    /** False when the price was refused on the client (the field says why). */
    fun counter(): Boolean {
        val t = current() ?: return false
        val v = t.currentVersion ?: return false
        Design07Rules.counterIssue(_state.value.counterPrice, v.unitPriceMinor)?.let { issue ->
            _state.update { it.copy(counterIssue = issue) }
            return false
        }
        val unit = ParcelRules.soumToMinor(_state.value.counterPrice)?.takeIf { it > 0 } ?: return false
        command("counter:${v.revision}:$unit", ThreadNotice.COUNTERED, "proposals.counterSent") { key ->
            api.counterProposal(threadId, OfferRules.counterBody(v, unit), key).data
        }
        return true
    }

    fun reject() {
        val v = current()?.currentVersion ?: return
        command("reject:${v.revision}", ThreadNotice.REJECTED, "driver.offer.counterRejected") { key ->
            api.rejectProposal(threadId, ProposalDecision(expectedRevision = v.revision), key).data
        }
    }

    fun withdraw() {
        val v = current()?.currentVersion ?: return
        command("withdraw:${v.revision}", ThreadNotice.WITHDRAWN, "notification.proposal.withdrawn.title") { key ->
            api.withdrawProposal(threadId, ProposalDecision(expectedRevision = v.revision), key).data
        }
    }

    /**
     * Accept the client's version (AC05: never one's own). It carries the thread's `listing_terms_version`; on
     * `409 PROPOSAL_CHANGED` (the terms moved meanwhile) the thread is read again and the driver confirms again.
     */
    fun accept() {
        val t = current() ?: return
        val v = t.currentVersion ?: return
        if (_state.value.busy) return
        val body = OfferRules.acceptBody(t, v)
        val scope = "accept:${v.id}:${body.expectedListingTermsVersion}"
        _state.update { it.copy(busy = true, notice = null, reconfirm = false) }
        banners.startAction()
        viewModelScope.launch {
            val result = tryCall { api.acceptProposal(threadId, body, keys.key(scope)).data }
            keys.settle(scope, result.exceptionOrNull())
            banners.endAction()
            result
                .onSuccess { booking ->
                    val id = OfferRules.bookingId(booking)
                    // Q100 / design 07 §8.7: the booking's chat opens right away (the meeting point is agreed there).
                    val chat = (Design07Rules.afterAccept(id) as? AcceptNav.BookingChat)?.bookingId
                    _state.update { it.copy(notice = ThreadNotice.ACCEPTED, bookingId = id, openChat = chat) }
                    banners.show(BannerTone.OK, BannerText.Key("driver.offer.clientPriceAccepted"))
                    proposals.refresh(ProposalTab.OPEN)
                    proposals.refresh(ProposalTab.ACCEPTED)
                    refresh()
                }
                .onFailure { e ->
                    if (OfferRules.termsChanged(e)) {
                        _state.update { it.copy(notice = ThreadNotice.TERMS_CHANGED, reconfirm = true) }
                        banners.show(BannerTone.WARN, BannerText.Key("client.listingBids.termsChanged"))
                    } else {
                        banners.show(BannerTone.ERR, OfferRules.errorKey(e)?.let { BannerText.Key(it) } ?: BannerText.Error(e))
                    }
                    if (OfferRules.needsRefresh(e)) refresh()
                }
            _state.update { it.copy(busy = false) }
        }
    }

    fun reconfirmShown() = _state.update { it.copy(reconfirm = false) }

    fun chatOpened() = _state.update { it.copy(openChat = null) }
}

/** A banner whose `{param}` is a so'm amount in the reader's language ("120 000 so'm" / "120 000 сум"). */
internal fun soumBanner(key: String, param: String, minor: Long): BannerText.Key = BannerText.Key(
    key,
    // `{param}` becomes "120 000 {soumUnit}", then the unit key fills the rest (params go in before keyParams).
    params = mapOf(param to "${ParcelRules.groupThousands(ParcelRules.minorToSoum(minor))}\u00A0{soumUnit}"),
    keyParams = mapOf("soumUnit" to "common.soum"),
)
