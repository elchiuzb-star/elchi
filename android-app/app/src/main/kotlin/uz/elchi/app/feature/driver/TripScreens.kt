package uz.elchi.app.feature.driver

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.elchi.app.R
import uz.elchi.app.api.generated.ManifestItemDTO
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.api.generated.TripDTO
import uz.elchi.app.api.generated.TripStatus
import uz.elchi.app.feature.client.DateTimeDialog
import uz.elchi.app.feature.client.Load
import uz.elchi.app.feature.client.LoadFailed
import uz.elchi.app.feature.client.LoadingLine
import uz.elchi.app.feature.client.OrderRules
import uz.elchi.app.feature.client.ParcelRules
import uz.elchi.app.feature.client.StepScaffold
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.CardHeader
import uz.elchi.app.ui.components.CardRow
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiField
import uz.elchi.app.ui.components.EmptyState
import uz.elchi.app.ui.components.ItemCard
import uz.elchi.app.ui.components.ItemLine
import uz.elchi.app.ui.components.LadderRow
import uz.elchi.app.ui.components.ListCard
import uz.elchi.app.ui.components.ListRow
import uz.elchi.app.ui.components.LoadingState
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.PickerField
import uz.elchi.app.ui.components.RoundIconButton
import uz.elchi.app.ui.components.SelectField
import uz.elchi.app.ui.components.StatusLadder
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone
import java.time.Instant
import java.time.LocalDateTime

@Composable
internal fun appRu(): Boolean = LocalConfiguration.current.locales[0].language == "ru"

@Composable
internal fun languageTag(): String = LocalConfiguration.current.locales[0].toLanguageTag()

@Composable
internal fun tripStatusText(status: TripStatus): String = tOrNull(TripRules.statusKey(status)) ?: status.value

@Composable
internal fun commandLabel(command: TripCommand): String = tOrNull(command.labelKey) ?: command.wire

// -- driver-routes ----------------------------------------------------------------------------------------------

/** The Routes tab body (the gate is the caller's): the private plans, the add button, the next step per card. */
@Composable
internal fun TripsList(vm: TripsViewModel, onAdd: () -> Unit, onTrip: (String) -> Unit, tracker: uz.elchi.app.gps.DriverTracker? = null) {
    val s by vm.state.collectAsStateWithLifecycle()
    // Q148: the running trip's GPS bar above the list (it asks the permission an auto-start needs).
    if (tracker != null) uz.elchi.app.gps.DriverTrackingBar(tracker, TripRules.trackable(s.list)?.id, inset = 0.dp)
    when (val trips = s.trips) {
        Load.Loading -> LoadingState(count = 3)
        is Load.Failed -> LoadFailed(t(R.string.driverRoutes_title), trips.error, vm::refresh)
        is Load.Ready -> if (trips.value.isEmpty()) {
            EmptyState(ElchiIcon.ROUTE, t(R.string.driverRoutes_empty), Modifier.padding(top = 12.dp), description = t(R.string.driver_routes_privateHint))
            ElchiButton(t(R.string.driverRoutes_addRoute), onAdd, Modifier.fillMaxWidth(), ButtonVariant.SOFT, icon = ElchiIcon.PLUS)
        } else {
            Text(t(R.string.driver_routes_privateHint), style = Elchi.type.caption, color = Elchi.colors.muted)
            trips.value.forEach { trip ->
                TripCard(trip, busy = trip.id in s.busy, opensAt = s.opensAt[trip.id], onClick = { onTrip(trip.id) }, onAction = { vm.act(trip, it) })
            }
        }
    }
}

@Composable
private fun TripCard(trip: TripDTO, busy: Boolean, opensAt: Instant?, onClick: () -> Unit, onAction: (TripCommand) -> Unit) {
    val c = Elchi.colors
    val ru = appRu()
    val start = OrderRules.parseInstant(trip.plannedStartAt)
    val date = listOfNotNull(OrderRules.dayMonth(trip.plannedStartAt, languageTag()), start?.let(DriverTime::clock)).joinToString(", ")
    val lines = buildList {
        if (trip.status == TripStatus.PLANNED) add(ItemLine(t(R.string.driverRoutes_boardingWindowHint)))
        if (opensAt != null) add(ItemLine(t(R.string.driver_trip_windowOpensAt, "time" to DriverTime.clockOrDay(opensAt, Instant.now())), c.tone(Tone.WARN).fg))
    }
    val next = TripRules.nextAction(trip.status)
    // Design 07 §2.1-2.3: the status as a toned badge, the next step as the primary button, history faded.
    ItemCard(
        title = TripRules.routeTitle(trip, ru),
        modifier = if (TripRules.isActive(trip.status)) Modifier else Modifier.alpha(0.7f),
        icon = ElchiIcon.ROUTE,
        badge = tripStatusText(trip.status) to TripRules.statusTone(trip.status),
        sub = t(R.string.driverRoutes_tripMeta, "date" to date, "stops" to trip.stops.size, "seats" to trip.seatCapacity),
        lines = lines,
        onClick = onClick,
        footer = next?.let { command ->
            { ElchiButton(commandLabel(command), { onAction(command) }, Modifier.fillMaxWidth().height(46.dp), ButtonVariant.PRIMARY, ButtonSize.MEDIUM, loading = busy) }
        },
    )
}

// -- driver-add-route -------------------------------------------------------------------------------------------

/** `driver-add-route`: the car, corridor → route (with the stop filter), departure, seats and cargo room. */
@Composable
fun AddTripScreen(vm: AddTripViewModel, onBack: () -> Unit, onCreated: (String) -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val c = Elchi.colors
    val ru = appRu()
    var picking by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(s.created) { s.created?.let(onCreated) }
    val issues = if (s.showIssues) s.issues(Instant.now()) else emptySet()
    val required = t(R.string.driver_form_required)
    val serverIssue = s.serverIssue
    val limitText = serverIssue?.second?.let { t(R.string.driver_trip_vehicleLimit, "limit" to it) }
    fun fieldError(issue: TripFormIssue, plain: String): String? = when {
        serverIssue?.first == issue -> limitText ?: plain
        issue in issues -> plain
        else -> null
    }
    val noApproved = s.vehicles is Load.Ready && s.approved.isEmpty()
    StepScaffold(
        title = t(R.string.driverRoutes_addRoute),
        onBack = onBack,
        footer = {
            ElchiButton(t(R.string.common_save), vm::save, Modifier.fillMaxWidth(), enabled = !noApproved && s.vehicles is Load.Ready, loading = s.saving)
        },
    ) {
        when (val vehicles = s.vehicles) {
            Load.Loading -> LoadingState(count = 2)
            is Load.Failed -> LoadFailed(t(R.string.addRoute_vehicle), vehicles.error, vm::load)
            is Load.Ready -> if (noApproved) {
                // A car under review cannot carry anyone yet: say which state it is in instead of an empty list.
                Note(t(R.string.addRoute_vehicleNeedsReview), tone = Tone.WARN, title = t(R.string.addRoute_noApprovedVehicle))
                vehicles.value.forEach { v ->
                    ElchiCard(padding = PaddingValues(horizontal = 16.dp, vertical = 4.dp)) {
                        CardRow(t(R.string.addRoute_vehicle), "${v.makeModel} · ${v.plateMasked}", first = true, detail = tOrNull("vehicleStatus.${v.verificationStatus}") ?: v.verificationStatus)
                    }
                }
            } else if (s.approved.size == 1) {
                // Design 07 §3.1: the one approved car is fixed (Q94) - a read-only row, not a one-option picker.
                val v = s.approved.first()
                ElchiField(
                    t(R.string.addRoute_vehicleOption, "model" to v.makeModel, "plate" to v.plateMasked, "seats" to v.seatCapacity), {},
                    label = t(R.string.addRoute_vehicle),
                    hint = t(R.string.driver_trip_vehicleLocked),
                    enabled = false,
                    locked = true,
                )
            } else {
                SelectField(
                    label = t(R.string.addRoute_vehicle),
                    value = s.form.vehicleId,
                    options = s.approved.map { it.id to t(R.string.addRoute_vehicleOption, "model" to it.makeModel, "plate" to it.plateMasked, "seats" to it.seatCapacity) },
                    onSelect = { id -> s.approved.firstOrNull { it.id == id }?.let(vm::pickVehicle) },
                    placeholder = t(R.string.addRoute_vehiclePlaceholder),
                )
                if (TripFormIssue.VEHICLE in issues) Text(required, style = Elchi.type.caption, color = c.tone(Tone.ERR).fg)
            }
        }
        if (!noApproved) {
            when (val corridors = s.corridors) {
                Load.Loading -> LoadingLine(t(R.string.common_loading))
                is Load.Failed -> LoadFailed(t(R.string.addRoute_corridor), corridors.error, vm::load)
                is Load.Ready -> SelectField(
                    label = t(R.string.addRoute_corridor),
                    value = s.form.corridorId,
                    options = corridors.value.map { it.id to it.name },
                    onSelect = vm::pickCorridor,
                    placeholder = t(R.string.addRoute_corridorPlaceholder),
                )
            }
            RoutePicker(s, vm, ru, routeError = fieldError(TripFormIssue.ROUTE, required))
            PickerField(
                label = t(R.string.addRoute_departureTime),
                value = s.form.departure?.let(ParcelRules::display),
                placeholder = "--.--.----, --:--",
                onClick = { picking = true },
                error = TripFormIssue.DEPARTURE in issues || TripFormIssue.DEPARTURE_PAST in issues,
                // Design 07 §3.4: one pair of sentences on both apps.
                hint = Design07Rules.departureErrorKey(issues)?.let { tOrNull(it) },
            )
            // Design 07 §3.5: the three numbers in one row.
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ElchiField(
                    s.form.seats, { v -> vm.edit { it.copy(seats = v.filter(Char::isDigit).take(2)) } },
                    Modifier.weight(1f),
                    label = t(R.string.addRoute_freeSeats),
                    error = fieldError(TripFormIssue.SEATS, t(R.string.driver_form_positiveNumber)),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                )
                ElchiField(
                    s.form.cargoKg, { v -> vm.edit { it.copy(cargoKg = v.filter(Char::isDigit).take(5)) } },
                    Modifier.weight(1f),
                    label = t(R.string.driverProfileForm_cargoKg),
                    error = fieldError(TripFormIssue.CARGO_KG, t(R.string.driver_form_positiveNumber)),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                )
                ElchiField(
                    s.form.cargoLitres, { v -> vm.edit { it.copy(cargoLitres = v.filter(Char::isDigit).take(5)) } },
                    Modifier.weight(1f),
                    label = t(R.string.driverProfileForm_cargoLitres),
                    error = fieldError(TripFormIssue.CARGO_LITRES, t(R.string.driver_form_positiveNumber)),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                )
            }
            // Design 07 §3.6: the seat ceiling from the chosen car.
            val seatsNote = s.vehicle?.let { " " + t(R.string.driver_trip_seatsMaxNote, "count" to it.seatCapacity) }.orEmpty()
            Text(t(R.string.addRoute_plannedOnApprovedRoute) + seatsNote, style = Elchi.type.caption.copy(fontSize = 12.sp), color = c.muted)
        }
    }
    if (picking) {
        val initial = s.form.departure ?: LocalDateTime.now(ParcelRules.TASHKENT).plusHours(2).withMinute(0)
        DateTimeDialog(t(R.string.addRoute_departureTime), initial, onDismiss = { picking = false }) { picked ->
            picking = false
            vm.edit { it.copy(departure = picked) }
        }
    }
}

@Composable
private fun RoutePicker(s: AddTripViewModel.State, vm: AddTripViewModel, ru: Boolean, routeError: String?) {
    val c = Elchi.colors
    val catalog = s.catalog
    when {
        s.form.corridorId == null -> SelectField(t(R.string.addRoute_route), null as String?, emptyList(), {}, t(R.string.addRoute_pickCorridorFirst))
        catalog == null || catalog == Load.Loading -> LoadingLine(t(R.string.common_loading))
        catalog is Load.Failed -> LoadFailed(t(R.string.addRoute_route), catalog.error) { s.form.corridorId.let(vm::pickCorridor) }
        catalog is Load.Ready -> {
            val all = catalog.value.routes
            if (all.isEmpty()) {
                Note(t(R.string.addRoute_noApprovedRoute), tone = Tone.WARN)
                return
            }
            fun stopName(id: String) = catalog.value.stops[id]?.let { if (ru) it.nameRu ?: it.nameUz else it.nameUz } ?: "?"
            // More than one route: "which one passes Jizzax?" (GET /stops/search, corridor stops only).
            if (all.size > 1) {
                val filter = s.form.stopFilterName
                if (filter == null) {
                    ElchiField(
                        s.stopQuery, vm::searchStop,
                        placeholder = t(R.string.tripPlan_stopSearchLabel),
                        icon = ElchiIcon.SEARCH,
                    )
                    if (s.stopResults.isNotEmpty()) {
                        ListCard {
                            s.stopResults.forEachIndexed { i, stop ->
                                ListRow(if (ru) stop.nameRu ?: stop.nameUz else stop.nameUz, icon = ElchiIcon.PIN, description = stop.district.nameUz, first = i == 0, onClick = { vm.pickStopFilter(stop) })
                            }
                        }
                    }
                } else {
                    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(c.field).padding(horizontal = 14.dp, vertical = 4.dp)) {
                        Text(t(R.string.tripPlan_stopFilter, "name" to filter), Modifier.weight(1f).padding(vertical = 10.dp), style = Elchi.type.label, color = c.text)
                        ElchiButton(t(R.string.tripPlan_stopFilterClear), { vm.pickStopFilter(null) }, Modifier.height(40.dp), ButtonVariant.GHOST, ButtonSize.MEDIUM, horizontalPadding = 8.dp)
                    }
                    if (s.routes.isEmpty()) Note(t(R.string.tripPlan_stopFilterNone, "name" to filter), tone = Tone.WARN)
                }
            }
            if (s.routes.isNotEmpty()) {
                SelectField(
                    label = t(R.string.addRoute_route),
                    value = s.form.routeId,
                    options = s.routes.map { r ->
                        r.id to t(R.string.addRoute_routeOption, "stops" to r.stops.size, "km" to TripRules.km(r.distanceM), "hours" to TripRules.hours(r.durationS))
                    },
                    onSelect = vm::pickRoute,
                    placeholder = t(R.string.addRoute_routePlaceholder),
                    // The stops say which road it is - the numbers alone do not tell two routes apart.
                    hint = s.route?.stops?.sortedBy { it.seq }?.joinToString(" → ") { stopName(it.stopId) } ?: routeError,
                )
            }
        }
    }
}

// -- driver-trip-detail -----------------------------------------------------------------------------------------

/** `driver-trip-detail`: header, stops, free room per segment, the manifest, and the commands. */
@Composable
fun TripDetailScreen(vm: TripDetailViewModel, onBack: () -> Unit, tracker: uz.elchi.app.gps.DriverTracker? = null, onBooking: (String) -> Unit = {}) {
    val s by vm.state.collectAsStateWithLifecycle()
    var reasonFor by remember { mutableStateOf<TripCommand?>(null) }
    // Design 07 §4.7: a cancelled trip goes back to the list (the banner says the open offers were closed).
    LaunchedEffect(s.cancelled) { if (s.cancelled) onBack() }
    val running = (s.trip as? Load.Ready)?.value?.takeIf { TripRules.publishable(it.status) }?.id
    StepScaffold(
        title = t(R.string.trip_detailsTitle),
        onBack = onBack,
        banner = if (tracker != null) ({ uz.elchi.app.gps.DriverTrackingBar(tracker, running) }) else null,
        onRefresh = { vm.refresh() },
        refreshing = s.refreshing && s.trip is Load.Ready,
        actions = { RoundIconButton(ElchiIcon.REFRESH, t(R.string.proposal_refresh), { vm.refresh(manual = true) }, loading = s.refreshing) },
    ) {
        when (val trip = s.trip) {
            Load.Loading -> LoadingState(count = 3)
            is Load.Failed -> LoadFailed(t(R.string.trip_detailsTitle), trip.error) { vm.refresh() }
            is Load.Ready -> {
                TripHeader(trip.value)
                TripStops(trip.value)
                Availability(s, trip.value)
                Manifest(s, onBooking)
                TripCommands(trip.value, s.busy, s.opensAt, onCommand = { command -> if (command.needsReason) reasonFor = command else vm.act(command) })
            }
        }
    }
    reasonFor?.let { command ->
        ReasonDialog(
            title = commandLabel(command),
            danger = command == TripCommand.CANCEL,
            onConfirm = { reason ->
                reasonFor = null
                vm.act(command, reason)
            },
            onDismiss = { reasonFor = null },
        )
    }
}

@Composable
private fun TripHeader(trip: TripDTO) {
    val ru = appRu()
    val start = OrderRules.parseInstant(trip.plannedStartAt)
    val end = OrderRules.parseInstant(trip.plannedEndAt)
    val cutoff = OrderRules.parseInstant(trip.bookingCutoffAt)
    ElchiCard {
        CardHeader(TripRules.routeTitle(trip, ru), badge = tripStatusText(trip.status), badgeTone = TripRules.statusTone(trip.status))
        CardRow(t(R.string.tripDetail_departure), start?.let(DriverTime::dayClock) ?: "—", first = true, strong = true)
        CardRow(t(R.string.tripDetail_arrival), end?.let(DriverTime::dayClock) ?: "—")
        CardRow(t(R.string.tripDetail_vehicle), "${trip.vehicle.makeModel}, ${trip.vehicle.color} · ${trip.vehicle.plateMasked}")
        CardRow(t(R.string.tripDetail_seatsLabel), t(R.string.tripDetail_seatsValue, "count" to trip.seatCapacity))
        CardRow(t(R.string.tripDetail_cutoffLabel), cutoff?.let { t(R.string.tripDetail_cutoffValue, "time" to DriverTime.dayClock(it)) } ?: "—")
    }
}

@Composable
private fun TripStops(trip: TripDTO) {
    val ru = appRu()
    val stops = trip.stops.sortedBy { it.seq }
    // Design 07 §4.2: the dots follow the trip status (the server sends no per-stop passage).
    val states = Design07Rules.ladder(trip.status, stops.size)
    StatusLadder(
        stops.mapIndexed { i, stop ->
            val planned = OrderRules.parseInstant(stop.plannedArrivalAt)?.let(DriverTime::clock)
            val eta = OrderRules.parseInstant(stop.etaArrivalAt)?.let(DriverTime::clock)?.takeIf { it != planned }
            LadderRow(
                title = if (ru) stop.stop.nameRu ?: stop.stop.nameUz else stop.stop.nameUz,
                time = listOfNotNull(planned, eta?.let { "ETA $it" }).joinToString(" · ").ifEmpty { null },
                state = states[i],
            )
        },
    )
}

@Composable
private fun Availability(s: TripDetailViewModel.State, trip: TripDTO) {
    val ru = appRu()
    val names = trip.stops.associate { it.stop.id to (if (ru) it.stop.nameRu ?: it.stop.nameUz else it.stop.nameUz) }
    ElchiCard {
        CardHeader(t(R.string.tripDetail_availabilityTitle))
        when (val a = s.availability) {
            Load.Loading -> LoadingLine(t(R.string.common_loading))
            is Load.Failed -> Note(uz.elchi.app.i18n.errorText(a.error), Modifier.padding(vertical = 8.dp), tone = Tone.ERR)
            is Load.Ready -> if (a.value.segments.isEmpty()) {
                Text(t(R.string.tripDetail_availabilityEmpty), Modifier.padding(vertical = 10.dp), style = Elchi.type.label, color = Elchi.colors.muted)
            } else {
                val segments = a.value.segments.sortedBy { it.fromSeq }
                val computed = OrderRules.parseInstant(a.value.computedAt)?.let(DriverTime::clock) ?: "—"
                segments.forEachIndexed { i, seg ->
                    CardRow(
                        "${names[seg.fromStopId] ?: "?"} → ${names[seg.toStopId] ?: "?"}",
                        t(
                            R.string.tripDetail_segmentLine,
                            "seats" to seg.seatsRemaining,
                            "weight" to t(R.string.tripDetail_kg, "value" to seg.cargoRemainingWeightG / 1000),
                            "volume" to t(R.string.tripDetail_litres, "value" to seg.cargoRemainingVolumeMl / 1000),
                            "baggage" to t(R.string.tripDetail_litres, "value" to seg.baggageRemainingMl / 1000),
                        ),
                        first = i == 0,
                        detail = if (i == segments.lastIndex) t(R.string.tripDetail_computedNote, "time" to computed) else null,
                    )
                }
            }
        }
    }
}

@Composable
private fun Manifest(s: TripDetailViewModel.State, onBooking: (String) -> Unit) {
    val ru = appRu()
    ElchiCard {
        CardHeader(t(R.string.tripDetail_manifestTitle))
        when (val m = s.manifest) {
            Load.Loading -> LoadingLine(t(R.string.common_loading))
            is Load.Failed -> Note(uz.elchi.app.i18n.errorText(m.error), Modifier.padding(vertical = 8.dp), tone = Tone.ERR)
            is Load.Ready -> {
                val rows = m.value.stops.sortedBy { it.seq }.flatMap { stop ->
                    val place = stop.stop?.let { if (ru) it.nameRu ?: it.nameUz else it.nameUz } ?: stop.point?.district?.nameUz ?: "?"
                    val time = OrderRules.parseInstant(stop.plannedArrivalAt)?.let(DriverTime::clock).orEmpty()
                    stop.pickups.map { Triple("$place · $time · ${t(R.string.tripDetail_pickups)}", it, true) } +
                        stop.dropoffs.map { Triple("$place · $time · ${t(R.string.tripDetail_dropoffs)}", it, false) }
                }
                if (rows.isEmpty()) {
                    Text(t(R.string.driver_trip_manifestEmpty), Modifier.padding(vertical = 10.dp), style = Elchi.type.label, color = Elchi.colors.muted)
                } else {
                    rows.forEachIndexed { i, (key, item, pickup) -> ManifestRow(key, item, pickup, first = i == 0, onOpen = { onBooking(item.bookingId) }) }
                }
            }
        }
    }
}

@Composable
private fun ManifestRow(key: String, item: ManifestItemDTO, pickup: Boolean, first: Boolean, onOpen: () -> Unit) {
    val what = when {
        item.serviceType == ServiceType.PARCEL -> item.parcelSummary ?: t(R.string.tripDetail_parcel)
        else -> t(R.string.tripDetail_seats, "count" to (item.seats ?: 1))
    }
    val status = tOrNull("tripDetail.service.${item.serviceStatus}")
    // The phone only when the server sends it; otherwise say when it opens (Q142: a parcel's receiver at departure,
    // a passenger once on board).
    val phone = item.contactPhone ?: if (pickup) tOrNull(Design07Rules.phoneNoteKey(item.serviceType)) else null
    // Stage 09: the booking (its chat, "Keldim", support) opens from its manifest row.
    CardRow(key, listOfNotNull("${item.clientFirstName} — $what", status).joinToString(" · "), first = first, detail = phone, trailing = t(R.string.driverBooking_messages), onTrailing = onOpen)
}

@Composable
private fun TripCommands(trip: TripDTO, busy: TripCommand?, opensAt: Instant?, onCommand: (TripCommand) -> Unit) {
    val commands = TripRules.detailCommands(trip.status)
    val next = TripRules.nextAction(trip.status)
    if (trip.status == TripStatus.PLANNED) Text(t(R.string.driverRoutes_boardingWindowHint), style = Elchi.type.caption, color = Elchi.colors.muted)
    if (opensAt != null) Note(t(R.string.driver_trip_windowOpensAt, "time" to DriverTime.clockOrDay(opensAt, Instant.now())), tone = Tone.WARN)
    next?.let { ElchiButton(commandLabel(it), { onCommand(it) }, Modifier.fillMaxWidth(), loading = busy == it, enabled = busy == null) }
    // Refresh is the bar's icon now (design 07 §0.3).
    val pauseOrResume = commands.firstOrNull { it == TripCommand.INTERRUPT || it == TripCommand.RESUME }
    if (pauseOrResume != null) {
        ElchiButton(
            commandLabel(pauseOrResume), { onCommand(pauseOrResume) }, Modifier.fillMaxWidth().height(48.dp), ButtonVariant.SOFT, ButtonSize.MEDIUM,
            loading = busy == pauseOrResume, enabled = busy == null, horizontalPadding = 10.dp, maxLines = 2,
        )
    }
    if (TripCommand.CANCEL in commands) {
        ElchiButton(commandLabel(TripCommand.CANCEL), { onCommand(TripCommand.CANCEL) }, Modifier.fillMaxWidth().height(48.dp), ButtonVariant.DANGER_SOFT, ButtonSize.MEDIUM, loading = busy == TripCommand.CANCEL, enabled = busy == null)
    }
}

/**
 * The reason sheet for pause / resume / cancel: the server requires a reason and the operator reads it. Cancel is
 * the danger variant (the dialog itself is the confirmation).
 */
@Composable
internal fun ReasonDialog(title: String, danger: Boolean, onConfirm: (String) -> Unit, onDismiss: () -> Unit) {
    val c = Elchi.colors
    // The dialog window speaks the phone's language: every label is resolved here, in the app's.
    val label = t(R.string.common_reason)
    val hint = t(R.string.driver_trip_reasonHint)
    val back = t(R.string.confirmDialog_back)
    var reason by rememberSaveable { mutableStateOf("") }
    Dialog(onDismissRequest = onDismiss) {
        Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(28.dp)).background(c.card).padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text(title, style = Elchi.type.title.copy(fontSize = 19.sp, lineHeight = 23.sp), color = c.text)
            ElchiField(reason, { reason = it.take(300) }, label = label, hint = hint, singleLine = false, minHeight = 88.dp)
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                ElchiButton(
                    title, { onConfirm(reason.trim()) }, Modifier.weight(1f).height(48.dp),
                    if (danger) ButtonVariant.DANGER else ButtonVariant.PRIMARY, ButtonSize.MEDIUM,
                    enabled = reason.isNotBlank(), horizontalPadding = 10.dp, maxLines = 2,
                )
                ElchiButton(back, onDismiss, Modifier.weight(1f).height(48.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM, horizontalPadding = 10.dp)
            }
        }
    }
}
