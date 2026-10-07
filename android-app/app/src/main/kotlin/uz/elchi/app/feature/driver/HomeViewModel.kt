package uz.elchi.app.feature.driver

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import uz.elchi.app.api.generated.DirectionRequestItemDTO
import uz.elchi.app.api.generated.DriverDirectionDTO
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.feature.client.Load
import java.time.Instant

/**
 * The new driver home (Royxat v3 §1, Safar v3 §1): "Mijozlar e'lonlari" = DD5 (`GET /driver-directions/{id}/requests`)
 * for every active direction and every service on, over the whole 14 days, merged into one list; the chip, search
 * and filter sheet are applied on the client ([HomeListingRules]). Also the "Kredit va taklif kodi" card's amount
 * (`GET /me/promo-balance`). One per driver flow, so the choices survive a tab switch.
 */
class HomeViewModel(
    private val api: ElchiApi,
    private val now: () -> Instant = Instant::now,
) : ViewModel() {
    data class State(
        /** Null = nothing to read (no active direction). */
        val listings: Load<List<HomeListing>>? = Load.Loading,
        val chip: HomeChip = HomeChip.ALL,
        val filter: HomeFilter = HomeFilter(),
        val query: String = "",
        /** The driver credit that can be used now; Failed / 0 = "Hozircha kredit yo'q". */
        val credit: Load<Long> = Load.Loading,
    ) {
        val all: List<HomeListing> get() = (listings as? Load.Ready)?.value.orEmpty()
    }

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()
    private var job: Job? = null
    private var lastKey: String? = null

    /** The list for these directions; [force] reads again even when nothing changed (pull to refresh, back on home). */
    fun load(directions: List<DriverDirectionDTO>, passengerEnabled: Boolean, force: Boolean = false) {
        val active = HomeListingRules.activeDirections(directions)
        val services = if (passengerEnabled) listOf(ServiceType.PARCEL, ServiceType.PASSENGER) else listOf(ServiceType.PARCEL)
        val key = active.joinToString { "${it.id}:${it.version}" } + "|" + services.joinToString()
        if (!force && key == lastKey && _state.value.listings is Load.Ready) return
        lastKey = key
        job?.cancel()
        if (active.isEmpty()) {
            _state.update { it.copy(listings = null) }
            return
        }
        if (_state.value.listings !is Load.Ready) _state.update { it.copy(listings = Load.Loading) }
        val (from, to) = DirectionRules.range(DirectionDay.DAYS14, now())
        job = viewModelScope.launch {
            val reads = active.flatMap { d -> services.map { service -> d.id to service } }.map { (id, service) ->
                async { tryCall { api.listDirectionRequests(id, service, from, to).data } }
            }.awaitAll()
            val pages = reads.mapNotNull { it.getOrNull() }
            val failure = reads.firstNotNullOfOrNull { it.exceptionOrNull() }
            _state.update {
                // One direction failing still shows the others; all failing is a failed read.
                it.copy(listings = if (pages.isEmpty() && failure != null) Load.Failed(failure) else Load.Ready(HomeListingRules.merge(pages)))
            }
        }
    }

    fun loadCredit() {
        viewModelScope.launch {
            tryCall { api.myPromoBalance().data }
                .onSuccess { b -> _state.update { it.copy(credit = Load.Ready(HomeListingRules.creditMinor(b.buckets))) } }
                .onFailure { e -> _state.update { it.copy(credit = Load.Failed(e)) } }
        }
    }

    fun pickChip(chip: HomeChip) = _state.update { it.copy(chip = chip) }

    fun setFilter(filter: HomeFilter) = _state.update { it.copy(filter = filter) }

    fun setQuery(query: String) = _state.update { it.copy(query = query.take(60)) }

    /** The cards on home after the chip, search and sheet. */
    fun shown(s: State = _state.value): List<HomeListing> = HomeListingRules.apply(s.all, s.chip, s.filter, s.query, now())

    /** A card's request, for the listing detail and the offer screens (the item is already in memory, no read). */
    fun item(listingId: String): DirectionRequestItemDTO? = _state.value.all.firstOrNull { it.listing.id == listingId }?.item
}
