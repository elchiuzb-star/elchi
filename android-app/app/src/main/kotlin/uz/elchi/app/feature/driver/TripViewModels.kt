package uz.elchi.app.feature.driver

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import uz.elchi.app.api.ElchiJson
import uz.elchi.app.api.generated.CorridorDTO
import uz.elchi.app.api.generated.DriverDirectionDTO
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.api.generated.RouteVersionDTO
import uz.elchi.app.api.generated.TripActionRequest
import uz.elchi.app.api.generated.TripAvailabilityDTO
import uz.elchi.app.api.generated.TripDTO
import uz.elchi.app.api.generated.TripManifestDTO
import uz.elchi.app.api.generated.VehicleDTO
import uz.elchi.app.feature.client.ActionKeys
import uz.elchi.app.feature.client.Load
import uz.elchi.app.ui.components.BannerCenter
import uz.elchi.app.ui.components.BannerText
import uz.elchi.app.ui.components.BannerTone
import java.time.Instant

internal suspend fun <T> tryCall(block: suspend () -> T): Result<T> = try {
    Result.success(block())
} catch (e: CancellationException) {
    throw e
} catch (e: Exception) {
    Result.failure(e)
}

/** A trip command's refusal for the banner: `error.<CODE>` (incl. TRIP_HAS_UNRESOLVED_BOOKINGS, SCHEDULE_CONFLICT). */
internal fun tripBanner(error: Throwable): BannerText = BannerText.Error(error)

/** What a trip command means for GPS publishing (the driver's tracker; a fake in tests). */
interface TripGps {
    /** Before `complete`: deliver what is queued while the session still accepts it. */
    suspend fun beforeComplete(tripId: String)

    /** After a successful command. */
    fun after(tripId: String, effect: GpsEffect)
}

/** [TripGps] on the app's one publisher. */
class TrackerTripGps(private val tracker: uz.elchi.app.gps.DriverTracker) : TripGps {
    override suspend fun beforeComplete(tripId: String) = tracker.flushBeforeComplete(tripId)

    override fun after(tripId: String, effect: GpsEffect) {
        when (effect) {
            GpsEffect.START -> tracker.autoStart(tripId)
            GpsEffect.FINISH -> tracker.tripEnded(tripId)
            GpsEffect.NONE -> Unit
        }
    }
}

/**
 * Runs one trip command (`POST /trips/{id}/actions/{action}` with the trip's version and an Idempotency-Key that
 * survives a retry of the same press). Returns the new trip, or the failure after the banner said it.
 */
internal class TripCommandRunner(private val api: ElchiApi, private val banners: BannerCenter, private val gps: TripGps? = null) {
    private val keys = ActionKeys()

    suspend fun run(trip: TripDTO, command: TripCommand, reason: String?): Result<TripDTO> {
        val scope = "${trip.id}:${command.wire}:${trip.version}"
        banners.startAction()
        // Q148: the last points leave while the session still takes them; `complete` then closes it.
        if (command == TripCommand.COMPLETE) gps?.beforeComplete(trip.id)
        val result = tryCall {
            api.tripAction(trip.id, command.wire, TripActionRequest(expectedVersion = trip.version, reason = reason?.trim()?.takeIf { it.isNotEmpty() }), keys.key(scope)).data
        }
        keys.settle(scope, result.exceptionOrNull())
        banners.endAction()
        // Boarding and departure are when a client may look for the car (§10.6): publishing starts; the end stops it.
        if (result.isSuccess) gps?.after(trip.id, TripRules.gpsEffect(command))
        result
            .onSuccess { banners.show(BannerTone.OK, BannerText.Key(Design07Rules.commandBannerKey(command))) }
            .onFailure { e ->
                val opens = TripRules.boardingOpensAt(e)
                if (opens != null) {
                    banners.show(BannerTone.WARN, BannerText.Key("driver.trip.windowOpensAt", params = mapOf("time" to DriverTime.clockOrDay(opens, Instant.now()))))
                } else {
                    banners.show(BannerTone.ERR, tripBanner(e))
                }
            }
        return result
    }
}

/**
 * "Yo'nalishlarim": the driver's private trip plans (Q138 - never shown to clients). One per driver flow: the
 * offer screen reads the same list to pick a trip from.
 */
class TripsViewModel(private val api: ElchiApi, private val banners: BannerCenter, gps: TripGps? = null) : ViewModel() {
    data class State(
        val trips: Load<List<TripDTO>> = Load.Loading,
        val refreshing: Boolean = false,
        /** Trip ids with a command in flight. */
        val busy: Set<String> = emptySet(),
        /** "Chiqish oynasi 10:30 da ochiladi" under a planned card after a too-early press. */
        val opensAt: Map<String, Instant> = emptyMap(),
        /** ADR-0028: the driver's directions, only to name a trip by the direction it serves (no stops to name it). */
        val directions: List<DriverDirectionDTO> = emptyList(),
    ) {
        val list: List<TripDTO> get() = (trips as? Load.Ready)?.value.orEmpty()

        fun direction(tripId: String): DriverDirectionDTO? = TripRules.directionOf(tripId, directions)
    }

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()
    private val runner = TripCommandRunner(api, banners, gps)

    init {
        refresh()
    }

    fun refresh() {
        if (_state.value.refreshing) return
        _state.update { it.copy(refreshing = true) }
        viewModelScope.launch {
            val directions = async { tryCall { api.listMyDriverDirections().data } }
            tryCall { api.listMyTrips(limit = PAGE).data }
                .onSuccess { list -> _state.update { it.copy(trips = Load.Ready(TripRules.ordered(list))) } }
                .onFailure { e -> _state.update { if (it.trips is Load.Ready) it else it.copy(trips = Load.Failed(e)) } }
            // A missing name is not an error: the card then shows the trip's times.
            directions.await().onSuccess { list -> _state.update { it.copy(directions = list) } }
            _state.update { it.copy(refreshing = false) }
        }
    }

    /** The card's next-step button. */
    fun act(trip: TripDTO, command: TripCommand) {
        if (trip.id in _state.value.busy) return
        // Design 07 §2.6: one tracker session at a time.
        if (Design07Rules.blocksStart(_state.value.list, trip, command)) {
            banners.show(BannerTone.WARN, BannerText.Key("driver.trip.oneLiveTrip"))
            return
        }
        _state.update { it.copy(busy = it.busy + trip.id) }
        viewModelScope.launch {
            val result = runner.run(trip, command, reason = null)
            val opens = result.exceptionOrNull()?.let(TripRules::boardingOpensAt)
            _state.update { s -> s.copy(busy = s.busy - trip.id, opensAt = if (opens != null) s.opensAt + (trip.id to opens) else s.opensAt - trip.id) }
            if (result.isSuccess || result.exceptionOrNull()?.let(TripRules::needsRefresh) == true) refresh()
        }
    }

    private companion object {
        const val PAGE = 50L
    }
}

/** The corridor's catalogue the add-trip form needs: its confirmed routes (ADR-0028: no stops). */
data class CorridorCatalog(val routes: List<RouteVersionDTO>)

/**
 * "Yo'nalish qo'shish" (web ConnectedApp.tsx:6246): an approved car, a corridor → a confirmed route, the
 * departure, the free seats and the cargo room. `POST /trips` with an Idempotency-Key.
 */
class AddTripViewModel(
    private val api: ElchiApi,
    private val banners: BannerCenter,
    private val now: () -> Instant = Instant::now,
) : ViewModel() {
    data class State(
        val vehicles: Load<List<VehicleDTO>> = Load.Loading,
        val corridors: Load<List<CorridorDTO>> = Load.Loading,
        val catalog: Load<CorridorCatalog>? = null,
        val form: TripForm = TripForm(),
        val saving: Boolean = false,
        val showIssues: Boolean = false,
        /** The field the server said the car cannot take (VEHICLE_NOT_ELIGIBLE) and the car's limit. */
        val serverIssue: Pair<TripFormIssue, Long?>? = null,
        val error: Throwable? = null,
        /** Set once: the new trip's id (the screen opens its detail). */
        val created: String? = null,
    ) {
        val approved: List<VehicleDTO> get() = TripRules.approvedVehicles((vehicles as? Load.Ready)?.value.orEmpty())
        val vehicle: VehicleDTO? get() = approved.firstOrNull { it.id == form.vehicleId }
        val routes: List<RouteVersionDTO> get() = (catalog as? Load.Ready)?.value?.routes.orEmpty()
        val route: RouteVersionDTO? get() = routes.firstOrNull { it.id == form.routeId }
        fun issues(now: Instant): Set<TripFormIssue> = TripRules.issues(form, vehicle, route, now)
    }

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()
    private val keys = ActionKeys()

    init {
        load()
    }

    fun load() {
        viewModelScope.launch {
            val vehicles = async { tryCall { api.listMyVehicles().data } }
            val corridors = async { tryCall { api.listCorridors().data } }
            vehicles.await()
                .onSuccess { list ->
                    _state.update { s ->
                        val approved = TripRules.approvedVehicles(list)
                        // One approved car: chosen for the driver, with its seats and cargo room filled in.
                        val form = if (s.form.vehicleId == null && approved.size == 1) TripRules.formFromVehicle(s.form, approved.first()) else s.form
                        s.copy(vehicles = Load.Ready(list), form = form)
                    }
                }
                .onFailure { e -> _state.update { it.copy(vehicles = Load.Failed(e)) } }
            corridors.await()
                .onSuccess { list -> _state.update { it.copy(corridors = Load.Ready(list)) } }
                .onFailure { e -> _state.update { it.copy(corridors = Load.Failed(e)) } }
        }
    }

    fun pickVehicle(vehicle: VehicleDTO) = _state.update { it.copy(form = TripRules.formFromVehicle(it.form, vehicle), serverIssue = null) }

    fun pickCorridor(id: String) {
        if (_state.value.form.corridorId == id && _state.value.catalog is Load.Ready) return
        _state.update { it.copy(form = it.form.copy(corridorId = id, routeId = null), catalog = Load.Loading) }
        viewModelScope.launch {
            val r = tryCall { api.listCorridorRoutes(id).data }
            if (_state.value.form.corridorId != id) return@launch
            val error = r.exceptionOrNull()
            if (error != null) {
                _state.update { it.copy(catalog = Load.Failed(error)) }
                return@launch
            }
            val list = r.getOrThrow().filter { it.status == CONFIRMED }
            _state.update { s ->
                s.copy(
                    catalog = Load.Ready(CorridorCatalog(list)),
                    // A single route needs no choice.
                    form = if (list.size == 1) s.form.copy(routeId = list.first().id) else s.form,
                )
            }
        }
    }

    fun pickRoute(id: String) = _state.update { it.copy(form = it.form.copy(routeId = id)) }

    fun edit(change: (TripForm) -> TripForm) = _state.update { it.copy(form = change(it.form), serverIssue = null, error = null) }

    fun save() {
        val s = _state.value
        if (s.saving) return
        val vehicle = s.vehicle
        val route = s.route
        if (vehicle == null || route == null || s.issues(now()).isNotEmpty()) {
            _state.update { it.copy(showIssues = true) }
            return
        }
        val body = TripRules.buildTripCreate(s.form, vehicle, route)
        // Same form, same key: a retry after a timeout cannot plan the trip twice.
        val scope = "trip:${body.hashCode()}"
        _state.update { it.copy(saving = true, showIssues = true, error = null, serverIssue = null) }
        banners.startAction()
        viewModelScope.launch {
            val result = tryCall { api.createTrip(body, keys.key(scope)).data }
            keys.settle(scope, result.exceptionOrNull())
            banners.endAction()
            result
                .onSuccess { trip ->
                    // Design 07 §3.7: "Safar rejalashtirildi: Toshkent – Samarqand" (a trip, not a route).
                    val corridor = (s.corridors as? Load.Ready)?.value?.firstOrNull { it.id == s.form.corridorId }?.name
                    if (corridor != null) banners.show(BannerTone.OK, BannerText.Key("driver.trip.saved", params = mapOf("route" to corridor)))
                    else banners.show(BannerTone.OK, BannerText.Key("addRoute.added"))
                    _state.update { it.copy(saving = false, created = trip.id) }
                }
                .onFailure { e ->
                    val issue = TripRules.vehicleLimitIssue(e)
                    _state.update { it.copy(saving = false, error = e.takeIf { issue == null }, serverIssue = issue?.let { i -> i to TripRules.vehicleLimit(e) }) }
                    if (issue == null) banners.show(BannerTone.ERR, tripBanner(e))
                }
        }
    }

    private companion object {
        const val CONFIRMED = "confirmed"
    }
}

/** `GET /trips/{id}` + `/availability` + `/manifest`, and the commands; every command reads all three again. */
class TripDetailViewModel(
    private val api: ElchiApi,
    private val banners: BannerCenter,
    private val tripId: String,
    private val onChanged: () -> Unit,
    gps: TripGps? = null,
    /** The driver's other trips, for the one-live-trip guard (design 07 §2.6). */
    private val liveTrips: () -> List<TripDTO> = { emptyList() },
) : ViewModel() {
    data class State(
        val trip: Load<TripDTO> = Load.Loading,
        val availability: Load<TripAvailabilityDTO> = Load.Loading,
        val manifest: Load<TripManifestDTO> = Load.Loading,
        val refreshing: Boolean = false,
        val busy: TripCommand? = null,
        val opensAt: Instant? = null,
        /** Set once the trip was cancelled: the screen goes back to the list (design 07 §4.7). */
        val cancelled: Boolean = false,
    )

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()
    private val runner = TripCommandRunner(api, banners, gps)

    init {
        refresh()
    }

    /** [manual] = the bar's refresh icon: "Yangilandi" once the trip is read again. */
    fun refresh(manual: Boolean = false) {
        if (_state.value.refreshing) return
        _state.update { it.copy(refreshing = true) }
        viewModelScope.launch {
            val trip = async { tryCall { ElchiJson.decodeFromJsonElement(TripDTO.serializer(), api.getTrip(tripId).data) } }
            val availability = async { tryCall { api.getTripAvailability(tripId).data } }
            val manifest = async { tryCall { api.getTripManifest(tripId).data } }
            trip.await()
                .onSuccess { t -> _state.update { it.copy(trip = Load.Ready(t)) } }
                .onFailure { e -> _state.update { if (it.trip is Load.Ready) it else it.copy(trip = Load.Failed(e)) } }
            availability.await()
                .onSuccess { a -> _state.update { it.copy(availability = Load.Ready(a)) } }
                .onFailure { e -> _state.update { if (it.availability is Load.Ready) it else it.copy(availability = Load.Failed(e)) } }
            manifest.await()
                .onSuccess { m -> _state.update { it.copy(manifest = Load.Ready(m)) } }
                .onFailure { e -> _state.update { if (it.manifest is Load.Ready) it else it.copy(manifest = Load.Failed(e)) } }
            _state.update { it.copy(refreshing = false) }
            if (manual) banners.show(BannerTone.OK, BannerText.Key("client.booking.refreshed"))
        }
    }

    fun act(command: TripCommand, reason: String? = null) {
        val trip = (_state.value.trip as? Load.Ready)?.value ?: return
        if (_state.value.busy != null) return
        if (Design07Rules.blocksStart(liveTrips(), trip, command)) {
            banners.show(BannerTone.WARN, BannerText.Key("driver.trip.oneLiveTrip"))
            return
        }
        _state.update { it.copy(busy = command) }
        viewModelScope.launch {
            val result = runner.run(trip, command, reason)
            result.onSuccess { t -> _state.update { it.copy(trip = Load.Ready(t), cancelled = command == TripCommand.CANCEL) } }
            _state.update { it.copy(busy = null, opensAt = result.exceptionOrNull()?.let(TripRules::boardingOpensAt)) }
            refresh()
            if (result.isSuccess) onChanged()
        }
    }
}
