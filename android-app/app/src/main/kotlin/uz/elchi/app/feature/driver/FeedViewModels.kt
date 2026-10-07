package uz.elchi.app.feature.driver

import android.content.Context
import androidx.core.content.edit
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import uz.elchi.app.api.generated.DistrictDTO
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.api.generated.FeedItemDTO
import uz.elchi.app.api.generated.FeedSide
import uz.elchi.app.api.generated.FeedSort
import uz.elchi.app.api.generated.RegionDTO
import uz.elchi.app.api.generated.SavedSearchDTO
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.feature.client.ActionKeys
import uz.elchi.app.feature.client.Load
import uz.elchi.app.ui.components.BannerCenter
import uz.elchi.app.ui.components.BannerText
import uz.elchi.app.ui.components.BannerTone
import java.time.Instant

/** The last feed filter, per driver (a shared phone keeps two drivers' routes apart). */
interface FeedFilterStore {
    fun load(): FeedFilter
    fun save(filter: FeedFilter)
}

class PrefsFeedFilterStore(context: Context, private val userId: Long) : FeedFilterStore {
    private val prefs = context.getSharedPreferences("elchi.driver", Context.MODE_PRIVATE)
    override fun load(): FeedFilter = FeedRules.decode(prefs.getString(key(), null))
    override fun save(filter: FeedFilter) = prefs.edit { putString(key(), FeedRules.encode(filter)) }
    private fun key() = "feed.filter.$userId"
}

/**
 * "Moslar" (`GET /feed`, side=requests, alternatives on, recommended order, cursor pages). The route filter is
 * region → district on each side; the date chips set the Tashkent day range. One per driver flow: the offer screen
 * takes its listing from here, and the saved routes read the current direction.
 */
class FeedViewModel(
    private val api: ElchiApi,
    private val store: FeedFilterStore,
    private val now: () -> Instant = Instant::now,
) : ViewModel() {
    data class State(
        val filter: FeedFilter = FeedFilter(),
        val regions: Load<List<RegionDTO>> = Load.Loading,
        /** Districts by region id, read when a region is picked. */
        val districts: Map<String, List<DistrictDTO>> = emptyMap(),
        val passengerEnabled: Boolean = false,
        val items: List<FeedItemDTO> = emptyList(),
        val loaded: Boolean = false,
        val loading: Boolean = false,
        val error: Throwable? = null,
        val next: String? = null,
        val loadingMore: Boolean = false,
        /** `meta.degraded` codes (e.g. ROUTING_UNAVAILABLE): a small note, not an error. */
        val degraded: List<String> = emptyList(),
        /** Every district id → name, for saved routes (read once, lazily). */
        val names: Map<String, String> = emptyMap(),
        val namesRu: Map<String, String> = emptyMap(),
        /** Every district read so far by id (a saved route's district → its region, design 07 §6.5). */
        val allDistricts: Map<String, DistrictDTO> = emptyMap(),
        /** "Saqlangan yo'nalishlar ({count})" (design 07 §5.4); null until read. */
        val savedCount: Int? = null,
    ) {
        fun names(ru: Boolean): Map<String, String> = if (ru) names + namesRu else names

        val groups: FeedGroups get() = FeedRules.split(items)
    }

    private val _state = MutableStateFlow(State(filter = store.load()))
    val state: StateFlow<State> = _state.asStateFlow()
    private var loadJob: Job? = null

    init {
        viewModelScope.launch {
            val regions = async { tryCall { api.listRegions().data } }
            val flags = async { tryCall { api.effectiveFlags().data.flags.passengerEnabled } }
            regions.await()
                .onSuccess { list -> _state.update { s -> s.copy(regions = Load.Ready(list), names = s.names + list.associate { it.id to it.nameUz }, namesRu = s.namesRu + list.associate { it.id to (it.nameRu ?: it.nameUz) }) } }
                .onFailure { e -> _state.update { it.copy(regions = Load.Failed(e)) } }
            val passenger = flags.await().getOrDefault(false)
            _state.update { s -> s.copy(passengerEnabled = passenger, filter = FeedRules.effectiveService(s.filter, passenger)) }
            listOfNotNull(_state.value.filter.origin.regionId, _state.value.filter.destination.regionId).distinct().forEach(::loadDistricts)
            refresh()
        }
    }

    fun loadDistricts(regionId: String) {
        if (regionId in _state.value.districts) return
        viewModelScope.launch {
            tryCall { api.listDistricts(regionId = regionId, limit = 200).data }
                .onSuccess { list -> _state.update { s -> s.copy(districts = s.districts + (regionId to list), allDistricts = s.allDistricts + list.associateBy { it.id }, names = s.names + list.associate { it.id to it.nameUz }, namesRu = s.namesRu + list.associate { it.id to (it.nameRu ?: it.nameUz) }) } }
        }
    }

    /** Every district's name at once (≤ 500), for the saved routes list. */
    fun loadAllNames() {
        viewModelScope.launch {
            tryCall { api.listDistricts(limit = 500).data }
                .onSuccess { list -> _state.update { s -> s.copy(allDistricts = s.allDistricts + list.associateBy { it.id }, names = s.names + list.associate { it.id to it.nameUz }, namesRu = s.namesRu + list.associate { it.id to (it.nameRu ?: it.nameUz) }) } }
        }
    }

    private fun setFilter(filter: FeedFilter) {
        _state.update { it.copy(filter = filter) }
        store.save(filter)
        refresh()
    }

    fun pickRegion(origin: Boolean, region: RegionDTO) {
        val end = FeedEnd(regionId = region.id, regionName = region.nameUz, regionNameRu = region.nameRu, requiresDistrict = region.requiresDistrict ?: true)
        val f = _state.value.filter
        setFilter(if (origin) f.copy(origin = end) else f.copy(destination = end))
        loadDistricts(region.id)
    }

    fun pickDistrict(origin: Boolean, district: DistrictDTO?) {
        val f = _state.value.filter
        val end = (if (origin) f.origin else f.destination).copy(districtId = district?.id, districtName = district?.nameUz, districtNameRu = district?.nameRu)
        setFilter(if (origin) f.copy(origin = end) else f.copy(destination = end))
    }

    fun pickDays(days: FeedDays) = setFilter(_state.value.filter.copy(days = days))

    fun pickService(service: ServiceType) = setFilter(_state.value.filter.copy(service = service.value))

    /** The saved routes' count for the feed's button (requests side only, as the saved screen lists them). */
    fun refreshSavedCount() {
        viewModelScope.launch {
            tryCall { api.listMySavedSearches(limit = 50).data }
                .onSuccess { list -> setSavedCount(list.count { it.side == FeedSide.REQUESTS }) }
        }
    }

    fun setSavedCount(count: Int) = _state.update { it.copy(savedCount = count) }

    /**
     * "Lentada ochish" (design 07 §6.5): the saved route's ends (and service) become the feed's filter. False when
     * an end cannot be shown as a pick (its district not read yet).
     */
    fun applySaved(saved: SavedSearchDTO): Boolean {
        val s = _state.value
        val regions = (s.regions as? Load.Ready)?.value.orEmpty()
        val filter = Design07Rules.filterFor(saved, s.filter, regions, s.allDistricts) ?: return false
        listOfNotNull(filter.origin.regionId, filter.destination.regionId).distinct().forEach(::loadDistricts)
        setFilter(FeedRules.effectiveService(filter, s.passengerEnabled))
        return true
    }

    fun refresh() {
        val query = FeedRules.query(_state.value.filter, now())
        refreshSavedCount()
        loadJob?.cancel()
        if (query == null) {
            _state.update { it.copy(items = emptyList(), loaded = false, loading = false, error = null, next = null, degraded = emptyList()) }
            return
        }
        _state.update { it.copy(loading = true, error = null) }
        loadJob = viewModelScope.launch {
            tryCall { fetch(query, cursor = null) }
                .onSuccess { page ->
                    _state.update { it.copy(items = page.data, loaded = true, loading = false, next = page.meta.nextCursor, degraded = page.meta.degraded.orEmpty()) }
                }
                .onFailure { e -> _state.update { it.copy(loading = false, loaded = true, error = e) } }
        }
    }

    fun loadMore() {
        val s = _state.value
        val cursor = s.next ?: return
        if (s.loadingMore || s.loading) return
        val query = FeedRules.query(s.filter, now()) ?: return
        _state.update { it.copy(loadingMore = true) }
        viewModelScope.launch {
            tryCall { fetch(query, cursor) }
                .onSuccess { page -> _state.update { st -> st.copy(items = (st.items + page.data).distinctBy { it.listing.id }, next = page.meta.nextCursor, loadingMore = false) } }
                .onFailure { _state.update { it.copy(loadingMore = false) } }
        }
    }

    private suspend fun fetch(query: FeedQuery, cursor: String?) = api.getFeed(
        serviceType = query.service,
        side = FeedSide.REQUESTS,
        dateFrom = query.dateFrom,
        dateTo = query.dateTo,
        originRegionId = query.origin.regionId,
        originDistrictId = query.origin.districtId,
        destinationRegionId = query.destination.regionId,
        destinationDistrictId = query.destination.districtId,
        sort = FeedSort.RECOMMENDED,
        includeAlternatives = true,
        cursor = cursor,
        limit = PAGE,
    ).data

    fun item(listingId: String): FeedItemDTO? = _state.value.items.firstOrNull { it.listing.id == listingId }

    private companion object {
        const val PAGE = 20L
    }
}

/** "Saqlangan yo'nalishlar": notify me about new requests on this direction (limit 10, Q83). */
class SavedSearchesViewModel(
    private val api: ElchiApi,
    private val banners: BannerCenter,
    private val feed: FeedViewModel,
    private val now: () -> Instant = Instant::now,
) : ViewModel() {
    data class State(
        val saved: Load<List<SavedSearchDTO>> = Load.Loading,
        val saving: Boolean = false,
        val deleting: Set<String> = emptySet(),
    )

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()
    private val keys = ActionKeys()

    init {
        feed.loadAllNames()
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            tryCall { api.listMySavedSearches(limit = 50).data }
                .onSuccess { list ->
                    val requests = list.filter { s -> s.side == FeedSide.REQUESTS }
                    _state.update { it.copy(saved = Load.Ready(requests)) }
                    feed.setSavedCount(requests.size)
                }
                .onFailure { e -> _state.update { if (it.saved is Load.Ready) it else it.copy(saved = Load.Failed(e)) } }
        }
    }

    fun saveCurrent() {
        if (_state.value.saving) return
        val query = FeedRules.query(feed.state.value.filter, now()) ?: return
        // Design 07 §6.2 / §6.3: the button is already grey for these; a tap still says why.
        val list = (_state.value.saved as? Load.Ready)?.value.orEmpty()
        if (Design07Rules.alreadySaved(list, query)) {
            banners.show(BannerTone.WARN, BannerText.Key("driver.routes.alreadySaved"))
            return
        }
        if (Design07Rules.atLimit(list)) {
            banners.show(BannerTone.WARN, BannerText.Key("driver.saved.limitHint", params = mapOf("limit" to FeedRules.SAVED_LIMIT.toString())))
            return
        }
        val body = FeedRules.savedSearchBody(query, now())
        val scope = "saved:${query.origin}:${query.destination}:${query.service}"
        _state.update { it.copy(saving = true) }
        banners.startAction()
        viewModelScope.launch {
            val result = tryCall { api.createSavedSearch(body, keys.key(scope)).data }
            keys.settle(scope, result.exceptionOrNull())
            banners.endAction()
            result
                .onSuccess {
                    banners.show(BannerTone.OK, BannerText.Key("driver.routes.savedNotify"))
                    refresh()
                }
                .onFailure { e -> banners.show(BannerTone.ERR, BannerText.Error(e)) }
            _state.update { it.copy(saving = false) }
        }
    }

    fun delete(saved: SavedSearchDTO) {
        if (saved.id in _state.value.deleting) return
        _state.update { it.copy(deleting = it.deleting + saved.id) }
        banners.startAction()
        viewModelScope.launch {
            val result = tryCall { api.deleteSavedSearch(saved.id) }
            banners.endAction()
            result
                .onSuccess {
                    banners.show(BannerTone.OK, BannerText.Key("savedSearches.deleted"))
                    _state.update { s -> s.copy(saved = (s.saved as? Load.Ready)?.let { r -> Load.Ready(r.value.filterNot { it.id == saved.id }) } ?: s.saved) }
                    ((_state.value.saved as? Load.Ready)?.value)?.let { feed.setSavedCount(it.size) }
                }
                .onFailure { e -> banners.show(BannerTone.ERR, BannerText.Error(e)) }
            _state.update { it.copy(deleting = it.deleting - saved.id) }
        }
    }

    /** "Lentada ochish": true when the feed now shows [saved] ([name] goes into the banner). */
    fun openInFeed(saved: SavedSearchDTO, name: String): Boolean {
        if (!feed.applySaved(saved)) return false
        banners.show(BannerTone.OK, BannerText.Key("driver.routes.openedInFeed", params = mapOf("name" to name)))
        return true
    }
}
