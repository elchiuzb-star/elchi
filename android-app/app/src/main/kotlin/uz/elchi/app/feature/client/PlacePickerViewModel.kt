package uz.elchi.app.feature.client

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import uz.elchi.app.api.GeoApi
import uz.elchi.app.api.PlaceSuggestion
import uz.elchi.app.api.generated.DistrictDTO
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.api.generated.RegionDTO
import uz.elchi.app.ui.map.GeoPoint

/**
 * The place picker (Q88): region -> district -> a point on the map. Scoped to the client flow, so the region list
 * is loaded once. The point step keeps a candidate (the pin, a search result or the district centre) with its
 * reverse-geocoded name; nothing reaches the draft until "Shu joyni tanlash".
 */
class PlacePickerViewModel(
    private val api: ElchiApi,
    private val geo: GeoApi,
    /** "uz" / "ru" for the geocoder's answer. */
    private val language: () -> String,
) : ViewModel() {

    data class Candidate(
        val point: GeoPoint,
        /** A real address (without the country), or null when the geocoder has none - the coordinates stand. */
        val address: String? = null,
        val resolving: Boolean = false,
    )

    data class PointState(
        val region: RegionDTO? = null,
        val district: DistrictDTO? = null,
        val candidate: Candidate? = null,
        val query: String = "",
        val suggestions: List<PlaceSuggestion> = emptyList(),
        val searching: Boolean = false,
        /** The last search returned nothing (or failed): say so instead of an empty dropdown. */
        val searchMiss: Boolean = false,
        val searchError: Throwable? = null,
        val loadError: Throwable? = null,
        val confirming: Boolean = false,
    ) {
        /** Where the map opens: the district centre, else the region centre. */
        val centre: GeoPoint? get() =
            district?.let { d -> if (d.centerLat != null && d.centerLng != null) GeoPoint(d.centerLat, d.centerLng) else null }
                ?: region?.let { r -> if (r.centerLat != null && r.centerLng != null) GeoPoint(r.centerLat, r.centerLng) else null }

        val districtCentre: GeoPoint? get() = district?.let { d -> if (d.centerLat != null && d.centerLng != null) GeoPoint(d.centerLat, d.centerLng) else null }
    }

    private val _regions = MutableStateFlow<Load<List<RegionDTO>>>(Load.Loading)
    val regions: StateFlow<Load<List<RegionDTO>>> = _regions.asStateFlow()

    private val _districts = MutableStateFlow<Load<List<DistrictDTO>>>(Load.Loading)
    val districts: StateFlow<Load<List<DistrictDTO>>> = _districts.asStateFlow()
    private var districtsRegion: String? = null

    private val _point = MutableStateFlow(PointState())
    val point: StateFlow<PointState> = _point.asStateFlow()

    private var reverseJob: Job? = null
    private var searchJob: Job? = null
    init {
        loadRegions()
    }

    fun loadRegions() {
        _regions.value = Load.Loading
        viewModelScope.launch { _regions.value = load { api.listRegions().data } }
    }

    fun loadDistricts(regionId: String, force: Boolean = false) {
        if (!force && districtsRegion == regionId && _districts.value is Load.Ready) return
        districtsRegion = regionId
        _districts.value = Load.Loading
        viewModelScope.launch {
            val result = load { api.listDistricts(regionId = regionId, limit = 500).data.filter { it.isActive != false } }
            if (districtsRegion == regionId) _districts.value = result
        }
    }

    fun region(regionId: String): RegionDTO? = (_regions.value as? Load.Ready)?.value?.firstOrNull { it.id == regionId }

    /**
     * A region without districts (Toshkent shahri) goes straight to the map with its single district. [onDistrict]
     * gets that district's id, or null when the region needs the district step.
     */
    fun pickRegion(region: RegionDTO, onDistrict: (String?) -> Unit) {
        if (region.requiresDistrict != false) {
            loadDistricts(region.id)
            onDistrict(null)
            return
        }
        districtsRegion = region.id
        _districts.value = Load.Loading
        viewModelScope.launch {
            val result = load { api.listDistricts(regionId = region.id, limit = 500).data.filter { it.isActive != false } }
            _districts.value = result
            val only = (result as? Load.Ready)?.value?.firstOrNull()
            // No district in the catalogue: fall back to the district list (it shows its own "not found").
            onDistrict(only?.id)
        }
    }

    // -- point step ----------------------------------------------------------------------------------------------

    /**
     * Opens the point step for [regionId]/[districtId]. [existing] is the end being changed: the pin starts there
     * when it is in the same district. [mapUsable] false leaves the candidate empty until search or the centre.
     */
    fun openPoint(regionId: String, districtId: String, existing: Place?, mapUsable: Boolean) {
        val current = _point.value
        if (current.district?.id == districtId && current.region?.id == regionId) return
        _point.value = PointState()
        viewModelScope.launch {
            try {
                val region = region(regionId) ?: api.listRegions().data.firstOrNull { it.id == regionId }
                val district = ((_districts.value as? Load.Ready)?.value ?: api.listDistricts(regionId = regionId, limit = 500).data).firstOrNull { it.id == districtId }
                _point.update { it.copy(region = region, district = district) }
                val start = when {
                    existing != null && existing.districtId == districtId -> Candidate(GeoPoint(existing.lat, existing.lng), existing.address)
                    mapUsable -> _point.value.centre?.let { Candidate(it, resolving = true) }
                    else -> null
                }
                if (start != null) {
                    _point.update { it.copy(candidate = start) }
                    if (start.address == null) reverse(start.point, immediate = true)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _point.update { it.copy(loadError = e) }
            }
        }
    }

    /** The pin came to rest (map gesture): name it after 400 ms of stillness. */
    fun onPinMoved(point: GeoPoint) {
        _point.update { it.copy(candidate = Candidate(point, resolving = true)) }
        reverse(point, immediate = false)
    }

    fun useDistrictCentre() {
        val centre = _point.value.districtCentre ?: return
        _point.update { it.copy(candidate = Candidate(centre, resolving = true), suggestions = emptyList(), searchMiss = false) }
        reverse(centre, immediate = true)
    }

    private fun reverse(point: GeoPoint, immediate: Boolean) {
        reverseJob?.cancel()
        reverseJob = viewModelScope.launch {
            if (!immediate) delay(REVERSE_DEBOUNCE_MS)
            val address = try {
                val result = geo.reverseGeocode(point.lat, point.lng, language())
                if (result.hasRealAddress) ParcelRules.withoutCountry(result.formattedAddress!!) else null
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                null // no name is not an error: the coordinates are shown
            }
            _point.update { s -> if (s.candidate?.point == point) s.copy(candidate = s.candidate.copy(address = address, resolving = false)) else s }
        }
    }

    fun onQuery(text: String) {
        _point.update { it.copy(query = text, searchMiss = false, searchError = null) }
        searchJob?.cancel()
        val query = text.trim()
        if (query.length < 2) {
            _point.update { it.copy(suggestions = emptyList(), searching = false) }
            return
        }
        searchJob = viewModelScope.launch {
            delay(SUGGEST_DEBOUNCE_MS)
            _point.update { it.copy(searching = true) }
            val s = _point.value
            val near = s.centre
            try {
                val results = geo.suggest(query, language(), near?.lat, near?.lng, s.district?.nameUz)
                _point.update { it.copy(suggestions = results, searching = false, searchMiss = results.isEmpty()) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _point.update { it.copy(suggestions = emptyList(), searching = false, searchError = e) }
            }
        }
    }

    /** Turns the picked suggestion into a point; [onResolved] moves the map there. */
    fun pickSuggestion(suggestion: PlaceSuggestion, onResolved: (GeoPoint) -> Unit) {
        searchJob?.cancel()
        reverseJob?.cancel()
        _point.update { it.copy(searching = true, suggestions = emptyList()) }
        viewModelScope.launch {
            try {
                val place = geo.resolvePlace(suggestion.uri, language())
                val lat = place.lat
                val lng = place.lng
                if (lat == null || lng == null) {
                    _point.update { it.copy(searching = false, searchMiss = true) }
                    return@launch
                }
                val point = GeoPoint(lat, lng)
                val name = listOfNotNull(suggestion.title, suggestion.formattedAddress ?: suggestion.subtitle).joinToString(", ").ifBlank { null }
                    ?: place.formattedAddress?.let(ParcelRules::withoutCountry)
                _point.update { it.copy(searching = false, query = "", candidate = Candidate(point, address = name)) }
                onResolved(point)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _point.update { it.copy(searching = false, searchError = e) }
            }
        }
    }

    fun clearSearch() {
        searchJob?.cancel()
        _point.update { it.copy(query = "", suggestions = emptyList(), searching = false, searchMiss = false, searchError = null) }
    }

    /**
     * "Shu joyni tanlash": waits briefly for the name of the place if it is still being looked up (the address is
     * what the other side reads), then hands the place over. The coordinates alone are enough if the name is late.
     */
    fun confirm(onPlace: (Place) -> Unit) {
        if (_point.value.confirming) return
        _point.update { it.copy(confirming = true) }
        viewModelScope.launch {
            withTimeoutOrNull(CONFIRM_WAIT_MS) { reverseJob?.join() }
            _point.update { it.copy(confirming = false) }
            result()?.let(onPlace)
        }
    }

    /** The chosen place for the draft, or null while there is no candidate yet. */
    fun result(): Place? {
        val s = _point.value
        val region = s.region ?: return null
        val district = s.district ?: return null
        val candidate = s.candidate ?: return null
        return Place(
            regionId = region.id,
            regionUz = region.nameUz,
            regionRu = region.nameRu,
            districtId = district.id,
            districtUz = district.nameUz,
            districtRu = district.nameRu,
            lat = candidate.point.lat,
            lng = candidate.point.lng,
            address = candidate.address,
        )
    }

    /** Leaving the point step: the next open starts fresh (another end, another district). */
    fun closePoint() {
        reverseJob?.cancel()
        searchJob?.cancel()
        _point.value = PointState()
    }

    private suspend fun <T> load(block: suspend () -> T): Load<T> = try {
        Load.Ready(block())
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        Load.Failed(e)
    }

    private companion object {
        const val REVERSE_DEBOUNCE_MS = 400L
        const val SUGGEST_DEBOUNCE_MS = 300L
        const val CONFIRM_WAIT_MS = 4_000L
    }
}
