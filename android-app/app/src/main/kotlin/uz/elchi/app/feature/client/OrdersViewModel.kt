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
import uz.elchi.app.api.BookingClientDTO
import uz.elchi.app.api.ElchiJson
import uz.elchi.app.api.LegacyOrder
import uz.elchi.app.api.LegacyOrdersApi
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.api.generated.ListingDTO
import uz.elchi.app.api.generated.ProposalThreadDTO
import java.time.Instant

/** One list of the orders screen: what is loaded, where the next page starts, whether that page is loading. */
data class Paged<T>(
    val items: List<T> = emptyList(),
    val loaded: Boolean = false,
    val error: Throwable? = null,
    /** v2: `meta.next_cursor`; v1: the next page number as text. Null = nothing more. */
    val next: String? = null,
    val loadingMore: Boolean = false,
)

/** What the orders list says once after arriving from another screen. */
enum class OrdersNotice { DRIVER_CHOSEN, LISTING_CANCELLED }

/**
 * Stage 03, the signed-in client's orders: bookings, own listings (with their offer counts) and the read-only v1
 * orders, plus "Takliflarim" - every negotiation thread the client is a party of (`GET /me/proposals`) with the
 * same actions as a listing's bids screen ([board]).
 */
class OrdersViewModel(
    private val api: ElchiApi,
    private val legacy: LegacyOrdersApi,
    private val now: () -> Instant = Instant::now,
) : ViewModel() {

    data class State(
        val bookings: Paged<BookingClientDTO> = Paged(),
        val listings: Paged<ListingDTO> = Paged(),
        val legacy: Paged<LegacyOrder> = Paged(),
        /** v1 `pagination.total` of the first page (at least the rows loaded): the "Eski buyurtmalar (n)" row and the drawer row. */
        val legacyTotal: Int = 0,
        val legacyRefreshing: Boolean = false,
        /** Per listing id; missing = not asked (not live, beyond the first few) or the call failed. */
        val stats: Map<String, OfferStats> = emptyMap(),
        val refreshing: Boolean = false,
        val notice: OrdersNotice? = null,
        val proposals: Load<List<ProposalThreadDTO>> = Load.Loading,
        val proposalsRefreshing: Boolean = false,
        /** Thread id -> the client's own earlier total the driver answered ("sizniki ..."). */
        val previousTotals: Map<String, Long> = emptyMap(),
    ) {
        val loaded: Boolean get() = bookings.loaded && listings.loaded && legacy.loaded
        val empty: Boolean get() = loaded && bookings.items.isEmpty() && listings.items.isEmpty() && legacy.items.isEmpty()
        /** Every list failed: nothing to show but the error. */
        val failed: Throwable? get() = if (bookings.error != null && listings.error != null && legacy.error != null) listings.error else null
    }

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()

    /** Listing terms for accepts made from "Takliflarim" (the thread does not carry them). */
    val board = OfferBoard(
        viewModelScope,
        api,
        termsVersion = { thread -> ElchiJson.decodeFromJsonElement(ListingDTO.serializer(), api.getListing(thread.listingId).data).termsVersion },
        reload = { loadProposals() },
    )

    fun show(notice: OrdersNotice) = _state.update { it.copy(notice = notice) }

    fun consumeNotice() = _state.update { it.copy(notice = null) }

    /** The three lists from their first page, side by side; one failing does not blank the others. */
    fun refresh() {
        if (_state.value.refreshing) return
        _state.update { it.copy(refreshing = true) }
        viewModelScope.launch {
            val bookings = async { page { api.listMyBookings(role = CLIENT, limit = PAGE).let { r -> r.data.mapNotNull(BookingClientDTO::fromJson) to r.meta?.nextCursor } } }
            val listings = async { page { api.listMyListings(limit = PAGE).let { r -> r.data to r.meta?.nextCursor } } }
            val old = async { legacyFirstPage() }
            val b = bookings.await()
            val l = listings.await()
            val (o, total) = old.await()
            _state.update { it.copy(bookings = b, listings = l, legacy = o, legacyTotal = total, refreshing = false) }
            loadStats(l.items)
        }
    }

    private suspend fun legacyFirstPage(): Pair<Paged<LegacyOrder>, Int> {
        var total = 0
        val paged = page {
            legacy.clientOrders(1).let { p ->
                total = p.pagination.total
                p.items to (if (p.pagination.page < p.pagination.totalPages) "2" else null)
            }
        }
        return paged to maxOf(total, paged.items.size)
    }

    /** DESIGN10 §0: the archive screen's own pull to refresh - only the v1 list from its first page. */
    fun refreshLegacy() {
        if (_state.value.legacyRefreshing) return
        _state.update { it.copy(legacyRefreshing = true) }
        viewModelScope.launch {
            val (o, total) = legacyFirstPage()
            // A failed re-read keeps the rows on screen.
            _state.update { if (o.error != null && it.legacy.items.isNotEmpty()) it.copy(legacyRefreshing = false) else it.copy(legacy = o, legacyTotal = total, legacyRefreshing = false) }
        }
    }

    /** The drawer's "Eski buyurtmalar" row shows only for a client with v1 orders: read the first page once. */
    fun ensureLegacy() {
        if (_state.value.legacy.loaded || _state.value.legacyRefreshing) return
        refreshLegacy()
    }

    /**
     * The DTO carries no offer count, so the first few live listings ask for their threads in parallel; a failed
     * call leaves that row without the count rather than failing the screen.
     */
    private suspend fun loadStats(listings: List<ListingDTO>) {
        val live = listings.filter { OrderRules.isLive(it.status) }.take(STATS_FOR)
        val pairs = live.map { listing ->
            viewModelScope.async {
                runCatching { listing.id to OrderRules.offerStats(api.listListingProposals(listing.id, limit = 50).data, now()) }.getOrNull()
            }
        }.awaitAll().filterNotNull()
        _state.update { it.copy(stats = it.stats + pairs.toMap()) }
    }

    fun loadMoreBookings() = more({ it.bookings }, { s, p -> s.copy(bookings = p) }) { cursor ->
        api.listMyBookings(role = CLIENT, cursor = cursor, limit = PAGE).let { r -> r.data.mapNotNull(BookingClientDTO::fromJson) to r.meta?.nextCursor }
    }

    fun loadMoreListings() = more({ it.listings }, { s, p -> s.copy(listings = p) }, after = ::loadStats) { cursor ->
        api.listMyListings(cursor = cursor, limit = PAGE).let { r -> r.data to r.meta?.nextCursor }
    }

    fun loadMoreLegacy() = more({ it.legacy }, { s, p -> s.copy(legacy = p) }) { next ->
        val page = next.toInt()
        legacy.clientOrders(page).let { p -> p.items to (if (p.pagination.page < p.pagination.totalPages) (page + 1).toString() else null) }
    }

    private fun <T> more(
        get: (State) -> Paged<T>,
        set: (State, Paged<T>) -> State,
        after: suspend (List<T>) -> Unit = {},
        fetch: suspend (String) -> Pair<List<T>, String?>,
    ) {
        val current = get(_state.value)
        val next = current.next ?: return
        if (current.loadingMore) return
        _state.update { set(it, get(it).copy(loadingMore = true)) }
        viewModelScope.launch {
            try {
                val (items, cursor) = fetch(next)
                _state.update { s -> set(s, get(s).let { p -> p.copy(items = p.items + items, next = cursor, loadingMore = false) }) }
                after(items)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                // The rows already shown stay; the next scroll to the end tries again.
                _state.update { s -> set(s, get(s).copy(loadingMore = false)) }
            }
        }
    }

    /** A booking just made by an accept, at the top until the next read brings it from the server. */
    fun addBooking(booking: BookingClientDTO) = _state.update { s ->
        s.copy(bookings = s.bookings.copy(items = listOf(booking) + s.bookings.items.filter { it.id != booking.id }))
    }

    private suspend fun <T> page(block: suspend () -> Pair<List<T>, String?>): Paged<T> = try {
        val (items, next) = block()
        Paged(items = items, loaded = true, next = next)
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        Paged(loaded = true, error = e)
    }

    // -- Takliflarim --------------------------------------------------------------------------------------------

    fun refreshProposals() {
        _state.update { it.copy(proposalsRefreshing = true) }
        viewModelScope.launch {
            loadProposals()
            _state.update { it.copy(proposalsRefreshing = false) }
        }
    }

    private suspend fun loadProposals() {
        try {
            val threads = api.listMyProposals(limit = 50).data
            // Newest activity first: the thread that moved last is the one most likely waiting for an answer.
            val sorted = threads.sortedByDescending { t -> t.currentVersion?.createdAt?.let(OrderRules::parseInstant) ?: Instant.MIN }
            _state.update { it.copy(proposals = Load.Ready(sorted)) }
            val previous = previousClientTotals(api, sorted)
            _state.update { it.copy(previousTotals = previous) }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            _state.update { if (it.proposals is Load.Ready) it else it.copy(proposals = Load.Failed(e)) }
        }
    }

    private companion object {
        const val CLIENT = "client"
        const val PAGE = 20L
        const val STATS_FOR = 10
    }
}
