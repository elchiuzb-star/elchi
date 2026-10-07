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
import uz.elchi.app.api.generated.DirectionRequestItemDTO
import uz.elchi.app.api.generated.DirectionRequestsDTO
import uz.elchi.app.api.generated.DistrictDTO
import uz.elchi.app.api.generated.DriverDirectionDTO
import uz.elchi.app.api.generated.DriverDirectionPatch
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.api.generated.PriceBasis
import uz.elchi.app.api.generated.RegionDTO
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.api.generated.VehicleDTO
import uz.elchi.app.feature.client.ActionKeys
import uz.elchi.app.feature.client.Load
import uz.elchi.app.feature.client.ParcelRules
import uz.elchi.app.ui.components.BannerCenter
import uz.elchi.app.ui.components.BannerText
import uz.elchi.app.ui.components.BannerTone
import java.time.Instant

/**
 * ADR-0027: the driver's directions (`GET /me/driver-directions`) and the requests along the chosen one
 * (`GET /driver-directions/{id}/requests`). One per driver flow: the Routes tab lists and pauses them, the Moslar tab
 * shows the chosen one's feed, and the offer screen takes its request from here.
 */
class DirectionsViewModel(
    private val api: ElchiApi,
    private val banners: BannerCenter,
    private val now: () -> Instant = Instant::now,
) : ViewModel() {
    data class State(
        val directions: Load<List<DriverDirectionDTO>> = Load.Loading,
        val refreshing: Boolean = false,
        val selectedId: String? = null,
        val day: DirectionDay = DirectionDay.DAYS14,
        val service: ServiceType = ServiceType.PARCEL,
        /** Null = no direction to read (none yet). */
        val feed: Load<DirectionRequestsDTO>? = null,
        /** Direction ids with a pause / resume / archive in flight. */
        val busy: Set<String> = emptySet(),
    ) {
        val list: List<DriverDirectionDTO> get() = DirectionRules.live((directions as? Load.Ready)?.value.orEmpty())
        val selected: DriverDirectionDTO? get() = list.firstOrNull { it.id == selectedId }
    }

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()
    private var feedJob: Job? = null

    init {
        refresh()
    }

    /** The list, then the chosen direction's feed. */
    fun refresh() {
        _state.update { it.copy(refreshing = true) }
        viewModelScope.launch {
            tryCall { api.listMyDriverDirections().data }
                .onSuccess { list ->
                    _state.update { s -> s.copy(directions = Load.Ready(list), selectedId = DirectionRules.pickDirection(list, s.selectedId)) }
                }
                .onFailure { e -> _state.update { if (it.directions is Load.Ready) it else it.copy(directions = Load.Failed(e)) } }
            _state.update { it.copy(refreshing = false) }
            loadFeed()
        }
    }

    fun select(id: String) {
        if (_state.value.selectedId == id) return
        _state.update { it.copy(selectedId = id, feed = null) }
        loadFeed()
    }

    fun pickDay(day: DirectionDay) {
        if (_state.value.day == day) return
        _state.update { it.copy(day = day) }
        loadFeed()
    }

    /** The service follows the Moslar toggle (the corridor feed's), so both halves of the tab agree. */
    fun setService(service: ServiceType) {
        if (_state.value.service == service) return
        _state.update { it.copy(service = service) }
        loadFeed()
    }

    fun loadFeed() {
        val s = _state.value
        feedJob?.cancel()
        val direction = s.selected
        if (direction == null) {
            _state.update { it.copy(feed = null) }
            return
        }
        // A paused direction shows no requests (the server would answer, but the driver asked it to stop).
        if (direction.status != DirectionRules.ACTIVE) {
            _state.update { it.copy(feed = Load.Ready(DirectionRequestsDTO(activeTrip = direction.activeTrip, directionId = direction.id, items = emptyList()))) }
            return
        }
        if (s.feed !is Load.Ready || s.feed.value.directionId != direction.id) _state.update { it.copy(feed = Load.Loading) }
        val (from, to) = DirectionRules.range(s.day, now())
        feedJob = viewModelScope.launch {
            tryCall { api.listDirectionRequests(direction.id, s.service, from, to).data }
                .onSuccess { page -> _state.update { it.copy(feed = Load.Ready(page)) } }
                .onFailure { e -> _state.update { it.copy(feed = Load.Failed(e)) } }
        }
    }

    fun item(listingId: String): DirectionRequestItemDTO? =
        (_state.value.feed as? Load.Ready)?.value?.items?.firstOrNull { it.listing.id == listingId }

    /** Pause / resume ([status] = the new one) or archive, against the version on screen. */
    fun setStatus(direction: DriverDirectionDTO, status: String) {
        if (direction.id in _state.value.busy) return
        _state.update { it.copy(busy = it.busy + direction.id) }
        banners.startAction()
        viewModelScope.launch {
            val result = tryCall { api.patchDriverDirection(direction.id, DriverDirectionPatch(expectedVersion = direction.version, status = status)).data }
            banners.endAction()
            result
                // Safar v3 2.2: pausing says the feed now shows nothing for it; resuming / deleting say so.
                .onSuccess { banners.show(BannerTone.OK, BannerText.Key(DirectionRules.statusToastKey(status))) }
                .onFailure { e -> banners.show(BannerTone.ERR, BannerText.Error(e)) }
            _state.update { it.copy(busy = it.busy - direction.id) }
            refresh()
        }
    }

    /** After a new direction: show it and its feed. */
    fun added(direction: DriverDirectionDTO?) {
        if (direction != null) _state.update { it.copy(selectedId = direction.id, feed = null) }
        refresh()
    }
}

/**
 * "Yo'nalish qo'shish" (ADR-0027, Q150): where from → where to, each a region and (where the region asks for it) a
 * district. `POST /driver-directions`; `ROUTE_MISMATCH` and a duplicate are said in place.
 */
class AddDirectionViewModel(
    private val api: ElchiApi,
    private val banners: BannerCenter,
    private val vehicles: () -> List<VehicleDTO>?,
) : ViewModel() {
    data class State(
        val regions: Load<List<RegionDTO>> = Load.Loading,
        val districts: Map<String, Load<List<DistrictDTO>>> = emptyMap(),
        val form: DirectionForm = DirectionForm(),
        val showIssues: Boolean = false,
        val saving: Boolean = false,
        val notice: DirectionNotice? = null,
        /** Set once: the direction just created (the screen goes back). */
        val created: DriverDirectionDTO? = null,
    ) {
        val issues: Set<DirectionFormIssue> get() = DirectionRules.issues(form)
    }

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()
    private val keys = ActionKeys()

    init {
        loadRegions()
    }

    fun loadRegions() {
        _state.update { it.copy(regions = Load.Loading) }
        viewModelScope.launch {
            tryCall { api.listRegions().data }
                .onSuccess { list -> _state.update { it.copy(regions = Load.Ready(list)) } }
                .onFailure { e -> _state.update { it.copy(regions = Load.Failed(e)) } }
        }
    }

    fun loadDistricts(regionId: String) {
        if (_state.value.districts[regionId] is Load.Ready) return
        _state.update { it.copy(districts = it.districts + (regionId to Load.Loading)) }
        viewModelScope.launch {
            tryCall { api.listDistricts(regionId = regionId, limit = 200).data }
                .onSuccess { list -> _state.update { it.copy(districts = it.districts + (regionId to Load.Ready(list))) } }
                .onFailure { e -> _state.update { it.copy(districts = it.districts + (regionId to Load.Failed(e))) } }
        }
    }

    fun pickRegion(origin: Boolean, region: RegionDTO) {
        _state.update { s ->
            val f = s.form
            s.copy(
                form = if (origin) f.copy(originRegion = region, originDistrict = null) else f.copy(destinationRegion = region, destinationDistrict = null),
                notice = null,
            )
        }
        loadDistricts(region.id)
    }

    /** Null = the whole city (only where the region does not ask for a district). */
    fun pickDistrict(origin: Boolean, district: DistrictDTO?) {
        _state.update { s ->
            val f = s.form
            s.copy(form = if (origin) f.copy(originDistrict = district) else f.copy(destinationDistrict = district), notice = null)
        }
    }

    fun save() {
        val s = _state.value
        if (s.saving) return
        val body = DirectionRules.createBody(s.form, vehicles())
        if (body == null) {
            _state.update { it.copy(showIssues = true) }
            return
        }
        val scope = "direction:${body.origin.regionId}:${body.origin.districtId}:${body.destination.regionId}:${body.destination.districtId}"
        _state.update { it.copy(saving = true, notice = null) }
        banners.startAction()
        viewModelScope.launch {
            val result = tryCall { api.createDriverDirection(body, keys.key(scope)).data }
            keys.settle(scope, result.exceptionOrNull())
            banners.endAction()
            result
                .onSuccess { created ->
                    banners.show(BannerTone.OK, BannerText.Key("dir.added"))
                    _state.update { it.copy(saving = false, created = created) }
                }
                .onFailure { e ->
                    // No road / already there: product answers, said in place - not a failure banner.
                    val notice = DirectionRules.notice(e)
                    if (notice == null) banners.show(BannerTone.ERR, BannerText.Error(e))
                    _state.update { it.copy(saving = false, notice = notice) }
                }
        }
    }
}

/**
 * The offer from a direction (ADR-0027, Q152/Q153): the request, the rival board, the price with the commission
 * estimate - no trip to pick and no window to compute. `POST /driver-directions/{id}/offers`; a time conflict turns
 * the button into "propose HH:MM" (the same request with `pickup_at` = the car's ETA).
 */
class DirectionBidViewModel(
    private val api: ElchiApi,
    private val banners: BannerCenter,
    private val directionId: String,
    val item: DirectionRequestItemDTO?,
    private val proposals: ProposalsViewModel,
    private val onSent: () -> Unit = {},
) : ViewModel() {
    data class State(
        val board: Load<BoardSummary>? = Load.Loading,
        val price: String = "",
        val fee: FeeEstimate = FeeEstimate.None,
        val sending: Boolean = false,
        val priceMissing: Boolean = false,
        /** The car's ETA from a `TIME_WINDOW_CONFLICT`: the next send is a time proposal at it. */
        val conflictEta: String? = null,
        /** Too far (Q157) or already passed (Q154): one sentence on the screen. */
        val refusal: DirectionOfferOutcome? = null,
        val openThread: String? = null,
    )

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()
    private val keys = ActionKeys()
    private var feeJob: Job? = null

    init {
        item?.let { setPrice(OfferRules.prefillPrice(it.listing)) }
        loadBoard()
    }

    fun proposeAt(): String? = item?.let { DirectionRules.proposeAt(it, _state.value.conflictEta) }

    fun loadBoard() {
        val listingId = item?.listing?.id ?: return
        viewModelScope.launch {
            tryCall { api.listListingOffers(listingId, limit = 50).data }
                .onSuccess { offers -> _state.update { it.copy(board = Load.Ready(OfferRules.board(offers))) } }
                .onFailure { e -> _state.update { it.copy(board = if ((e as? ApiException)?.status == 404) null else Load.Failed(e)) } }
        }
    }

    fun setPrice(text: String) {
        val digits = text.filter(Char::isDigit).take(11)
        _state.update { it.copy(price = digits, priceMissing = false) }
        quoteFee()
    }

    private fun quoteFee() {
        feeJob?.cancel()
        val listing = item?.listing
        val unit = ParcelRules.soumToMinor(_state.value.price)
        if (listing == null || unit == null || unit <= 0) {
            _state.update { it.copy(fee = FeeEstimate.None) }
            return
        }
        val total = if (listing.priceBasis == PriceBasis.PER_SEAT) unit * listing.quantity else unit
        _state.update { it.copy(fee = FeeEstimate.Loading) }
        feeJob = viewModelScope.launch {
            delay(400)
            tryCall { api.commissionQuote(listing.serviceType, total).data }
                .onSuccess { q -> _state.update { it.copy(fee = FeeEstimate.Ready(total, q)) } }
                .onFailure { _state.update { it.copy(fee = FeeEstimate.Unavailable) } }
        }
    }

    /** "Taklif yuborish" (or "HH:MM ni taklif qilish"); [clientPrice] = the client's own unit price. */
    fun send(clientPrice: Boolean = false) {
        val listing = item?.listing ?: return
        val s = _state.value
        if (s.sending) return
        val typed = ParcelRules.soumToMinor(s.price)?.takeIf { it > 0 }
        if (!clientPrice && typed == null) {
            _state.update { it.copy(priceMissing = true) }
            return
        }
        val unit = if (clientPrice) listing.unitPriceMinor else typed ?: return
        val pickupAt = proposeAt()
        val body = DirectionRules.offerBody(listing.id, unit, pickupAt)
        val scope = DirectionRules.offerScope(directionId, listing.id, unit, pickupAt)
        _state.update { it.copy(sending = true, refusal = null) }
        banners.startAction()
        viewModelScope.launch {
            val result = tryCall { api.offerFromDirection(directionId, body, keys.key(scope)) }
            keys.settle(scope, result.exceptionOrNull())
            banners.endAction()
            result
                .onSuccess { r ->
                    val sent = DirectionRules.sent(r.data)
                    proposals.lastSent = SentOffer(sent.threadId, r.warnings)
                    banners.show(BannerTone.OK, BannerText.Key(sent.key, params = sent.time?.let { mapOf("time" to it) }.orEmpty()))
                    proposals.refresh(ProposalTab.OPEN)
                    onSent()
                    _state.update { it.copy(sending = false, openThread = sent.threadId) }
                }
                .onFailure { e ->
                    when (val outcome = DirectionRules.failed(e, pickupAt)) {
                        is DirectionOfferOutcome.ProposeTime -> _state.update { it.copy(sending = false, conflictEta = outcome.eta) }
                        is DirectionOfferOutcome.Existing -> _state.update { it.copy(sending = false, openThread = outcome.threadId) }
                        is DirectionOfferOutcome.TooFar, DirectionOfferOutcome.Passed -> _state.update { it.copy(sending = false, refusal = outcome) }
                        else -> {
                            banners.show(BannerTone.ERR, BannerText.Error(e))
                            _state.update { it.copy(sending = false) }
                        }
                    }
                }
        }
    }

    fun opened() = _state.update { it.copy(openThread = null) }
}
