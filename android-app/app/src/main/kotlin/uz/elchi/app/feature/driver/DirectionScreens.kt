package uz.elchi.app.feature.driver

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.elchi.app.R
import uz.elchi.app.api.generated.DirectionRequestItemDTO
import uz.elchi.app.api.generated.DistrictDTO
import uz.elchi.app.api.generated.DriverDirectionDTO
import uz.elchi.app.api.generated.ListingPublicDTO
import uz.elchi.app.api.generated.MatchType
import uz.elchi.app.api.generated.PriceBasis
import uz.elchi.app.api.generated.RegionDTO
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.feature.client.Load
import uz.elchi.app.feature.client.LoadFailed
import uz.elchi.app.feature.client.LoadingLine
import uz.elchi.app.feature.client.ParcelRules
import uz.elchi.app.feature.client.StepScaffold
import uz.elchi.app.feature.client.categoryLimits
import uz.elchi.app.feature.client.categoryName
import uz.elchi.app.feature.client.seatsLine
import uz.elchi.app.feature.client.seatsPrice
import uz.elchi.app.feature.client.soum
import uz.elchi.app.gps.DriverTrackingBar
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.Badge
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.Chip
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiDialog
import uz.elchi.app.ui.components.ElchiField
import uz.elchi.app.ui.components.ElchiIconView
import uz.elchi.app.ui.components.EmptyState
import uz.elchi.app.ui.components.ListRow
import uz.elchi.app.ui.components.LoadingState
import uz.elchi.app.ui.components.NotFoundState
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.PickerField
import uz.elchi.app.ui.components.SectionTitle
import uz.elchi.app.ui.components.Segmented
import uz.elchi.app.ui.components.SelectField
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.ElchiShape
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone

// -- driver-routes: "Yo'nalishlarim" (ADR-0027, Q150) ---------------------------------------------------------------

/**
 * The Routes tab body (the gate is the caller's): the driver's directions - pause, resume, archive, open their
 * requests - and below them the trips the system made from the offers, with every existing trip operation (Q148).
 * The manual trip form stays reachable from the trips section only, as a fallback.
 */
@Composable
internal fun ColumnScope.DirectionsBody(
    vm: DirectionsViewModel,
    trips: TripsViewModel,
    tracker: uz.elchi.app.gps.DriverTracker?,
    onAdd: () -> Unit,
    onFeed: (String) -> Unit,
    onTrip: (String) -> Unit,
    onAddTrip: () -> Unit,
) {
    val s by vm.state.collectAsStateWithLifecycle()
    val ts by trips.state.collectAsStateWithLifecycle()
    var archiving by remember { mutableStateOf<DriverDirectionDTO?>(null) }
    if (tracker != null) DriverTrackingBar(tracker, TripRules.trackable(ts.list)?.id, inset = 0.dp)
    when (val list = s.directions) {
        Load.Loading -> LoadingState(count = 2)
        is Load.Failed -> LoadFailed(t(R.string.driverRoutes_title), list.error, vm::refresh)
        is Load.Ready -> if (s.list.isEmpty()) {
            EmptyState(ElchiIcon.ROUTE, t(R.string.dir_empty), Modifier.padding(top = 8.dp), description = t(R.string.dir_emptyHint))
            ElchiButton(t(R.string.driverRoutes_addRoute), onAdd, Modifier.fillMaxWidth(), icon = ElchiIcon.PLUS)
        } else {
            s.list.forEach { direction ->
                DirectionCard(
                    direction,
                    busy = direction.id in s.busy,
                    onFeed = { onFeed(direction.id) },
                    onToggle = { vm.setStatus(direction, DirectionRules.toggledStatus(direction)) },
                    onArchive = { archiving = direction },
                )
            }
        }
    }
    // The trips the system made (Q148: boarding, departure, the manifest and GPS stay where they were).
    SectionTitle(t(R.string.dir_tripsTitle), Modifier.padding(top = 10.dp), description = t(R.string.dir_tripsHint))
    when (val list = ts.trips) {
        Load.Loading -> LoadingState(count = 1)
        is Load.Failed -> LoadFailed(t(R.string.dir_tripsTitle), list.error, trips::refresh)
        is Load.Ready -> list.value.forEach { trip ->
            TripCard(trip, busy = trip.id in ts.busy, opensAt = ts.opensAt[trip.id], direction = ts.direction(trip.id), onClick = { onTrip(trip.id) }, onAction = { trips.act(trip, it) })
        }
    }
    ElchiButton(t(R.string.driver_offer_planTrip), onAddTrip, Modifier.fillMaxWidth().height(44.dp), ButtonVariant.GHOST, ButtonSize.MEDIUM, icon = ElchiIcon.PLUS)
    archiving?.let { direction ->
        val title = DirectionRules.title(direction, appRu())
        ElchiDialog(
            title = t(R.string.dir_archive),
            text = t(R.string.dir_archiveConfirm, "title" to title),
            confirm = t(R.string.dir_archive),
            onConfirm = {
                archiving = null
                vm.setStatus(direction, DirectionRules.ARCHIVED)
            },
            onDismiss = { archiving = null },
            confirmVariant = ButtonVariant.DANGER,
            dismiss = t(R.string.confirmDialog_back),
        )
    }
}

@Composable
private fun DirectionCard(direction: DriverDirectionDTO, busy: Boolean, onFeed: () -> Unit, onToggle: () -> Unit, onArchive: () -> Unit) {
    val c = Elchi.colors
    val ru = appRu()
    val active = direction.status == DirectionRules.ACTIVE
    ElchiCard(padding = PaddingValues(horizontal = 16.dp, vertical = 14.dp)) {
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ElchiIconView(ElchiIcon.ROUTE, c.accentText, size = 18.dp)
                    Text(DirectionRules.title(direction, ru), style = Elchi.type.bodyStrong, color = c.text)
                }
                Badge(t(if (active) R.string.dir_statusActive else R.string.dir_statusPaused), if (active) Tone.OK else Tone.GRAY)
            }
            direction.viaDistrictNames?.takeIf { it.isNotEmpty() }?.let { names ->
                Text(t(R.string.dir_via, "names" to names.joinToString(", ")), style = Elchi.type.caption, color = c.muted)
            }
            Text(
                t(R.string.dir_capacity, "seats" to direction.seatCapacity, "kg" to DirectionRules.kg(direction.cargoCapacityWeightG)),
                style = Elchi.type.caption, color = c.muted,
            )
            val trip = direction.activeTrip
            Text(
                if (trip != null) t(R.string.dir_trip, "date" to DirectionRules.dayClock(trip.plannedStartAt), "status" to tripStatusText(trip.status), "seats" to trip.seatsBooked)
                else t(R.string.dir_noTrip),
                style = Elchi.type.secondary, color = c.text,
            )
            Row(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                ElchiButton(
                    t(R.string.dir_openRequests), onFeed, Modifier.weight(1f).height(44.dp), ButtonVariant.PRIMARY, ButtonSize.MEDIUM,
                    enabled = active, horizontalPadding = 10.dp, maxLines = 2,
                )
                ElchiButton(
                    t(if (active) R.string.dir_pause else R.string.dir_resume), onToggle, Modifier.weight(1f).height(44.dp), ButtonVariant.SOFT, ButtonSize.MEDIUM,
                    loading = busy, horizontalPadding = 10.dp, maxLines = 2,
                )
            }
            ElchiButton(
                t(R.string.dir_archive), onArchive, Modifier.fillMaxWidth().height(40.dp), ButtonVariant.GHOST, ButtonSize.MEDIUM,
                enabled = !busy, icon = ElchiIcon.TRASH,
            )
        }
    }
}

// -- driver-feed: the direction's requests (ADR-0027, Q151) ---------------------------------------------------------

/**
 * The Moslar tab body: the GPS bar, the service toggle, the chosen direction's requests in the server's three
 * answers, then the corridor search (`GET /feed`) as the secondary "all requests" view.
 */
@Composable
internal fun ColumnScope.MatchesBody(work: DriverWork, nav: DriverNav) {
    val fs by work.feed.state.collectAsStateWithLifecycle()
    val ts by work.trips.state.collectAsStateWithLifecycle()
    TripRules.trackable(ts.list)?.let { running -> DriverTrackingBar(work.tracker, running.id, inset = 0.dp) }
    val service = fs.filter.serviceType
    LaunchedEffect(service) { work.directions.setService(service) }
    if (fs.passengerEnabled) {
        Segmented(
            listOf(ServiceType.PASSENGER to t(R.string.driverFeed_modeTaxi), ServiceType.PARCEL to t(R.string.driverFeed_modeParcel)),
            service,
            work.feed::pickService,
        )
    }
    val ps by work.proposals.state.collectAsStateWithLifecycle()
    val mine = Design07Rules.myFeedOffers(ps.open, (ps.lists[ProposalTab.ACCEPTED] as? Load.Ready)?.value.orEmpty(), ps.mine)
    DirectionFeed(work.directions, mine, onAdd = nav.onAddDirection, onOffer = nav.onDirectionOffer, onThread = nav.onThread)
    SectionTitle(t(R.string.dir_districtSearch), Modifier.padding(top = 12.dp))
    FeedBody(work.feed, onSaved = nav.onSavedSearches, onOffer = nav.onOffer, proposals = work.proposals, onThread = nav.onThread, showService = false)
}

@Composable
private fun ColumnScope.DirectionFeed(
    vm: DirectionsViewModel,
    mine: Map<String, MyFeedOffer>,
    onAdd: () -> Unit,
    onOffer: (String, String) -> Unit,
    onThread: (String) -> Unit,
) {
    val s by vm.state.collectAsStateWithLifecycle()
    val c = Elchi.colors
    val ru = appRu()
    if (s.directions is Load.Loading) {
        LoadingState(count = 1)
        return
    }
    val list = s.list
    if (list.isEmpty()) {
        if (s.directions is Load.Failed) {
            LoadFailed(t(R.string.dir_feedPick), (s.directions as Load.Failed).error, vm::refresh)
            return
        }
        ElchiCard(padding = PaddingValues(16.dp), bordered = true) {
            Text(t(R.string.dir_noDirections), style = Elchi.type.bodyStrong, color = c.text)
            Text(t(R.string.dir_noDirectionsHint), Modifier.padding(top = 4.dp, bottom = 12.dp), style = Elchi.type.caption, color = c.muted)
            ElchiButton(t(R.string.driverRoutes_addRoute), onAdd, Modifier.fillMaxWidth().height(44.dp), size = ButtonSize.MEDIUM, icon = ElchiIcon.PLUS)
        }
        return
    }
    if (list.size > 1) {
        SelectField(
            label = t(R.string.dir_feedPick),
            value = s.selectedId,
            options = list.map { it.id to DirectionRules.title(it, ru) },
            onSelect = vm::select,
            placeholder = t(R.string.dir_feedPick),
        )
    } else {
        Text(DirectionRules.title(list.first(), ru), style = Elchi.type.bodyStrong, color = c.text)
    }
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        DirectionDay.entries.forEach { day -> Chip(tOrNull(day.key) ?: day.name, s.day == day, { vm.pickDay(day) }, filled = true) }
    }
    val selected = s.selected
    if (selected != null && selected.status != DirectionRules.ACTIVE) {
        Note(t(R.string.dir_paused), tone = Tone.GRAY)
        return
    }
    when (val feed = s.feed) {
        null, Load.Loading -> LoadingState(count = 1)
        is Load.Failed -> LoadFailed(t(R.string.dir_openRequests), feed.error, vm::loadFeed)
        is Load.Ready -> {
            feed.value.activeTrip?.let { trip ->
                Note(t(R.string.dir_trip, "date" to DirectionRules.dayClock(trip.plannedStartAt), "status" to tripStatusText(trip.status), "seats" to trip.seatsBooked), tone = Tone.BLUE)
            }
            val groups = DirectionRules.group(feed.value.items)
            val directionId = feed.value.directionId
            listOf(
                Triple(R.string.dir_group_fits, R.string.dir_group_fitsNote, groups.fits),
                Triple(R.string.dir_group_new, R.string.dir_group_newNote, groups.fresh),
                Triple(R.string.dir_group_time, R.string.dir_group_timeNote, groups.otherTime),
            ).forEach { (title, note, items) ->
                if (items.isNotEmpty()) {
                    SectionTitle(t(title), Modifier.padding(top = 4.dp), description = t(note))
                    items.forEach { item ->
                        DirectionRequestCard(item, mine[item.listing.id], onOffer = { onOffer(directionId, item.listing.id) }, onThread = onThread)
                    }
                }
            }
            if (feed.value.items.isEmpty()) Text(t(R.string.dir_feedEmpty), Modifier.padding(horizontal = 4.dp), style = Elchi.type.caption, color = c.muted)
        }
    }
}

/** What is carried: a parcel's category and limits, or "2 kishi · 2 × 150 000 so'm". */
@Composable
private fun whatLine(listing: ListingPublicDTO): String? =
    if (listing.serviceType == ServiceType.PARCEL) listing.parcelCategory?.let { "${categoryName(it, appRu())} · ${categoryLimits(it)}" }
    else seatsLine(listing.quantity, listing.unitPriceMinor)

@Composable
private fun placeTitle(listing: ListingPublicDTO): String {
    val fallback = t(R.string.app_endLabel_mapPlace)
    return "${DirectionRules.place(listing.originPoint, fallback)} → ${DirectionRules.place(listing.destinationPoint, fallback)}"
}

/** One request along the direction: places (never a stop, Q158), the client's window, the car's time, the price. */
@Composable
private fun DirectionRequestCard(item: DirectionRequestItemDTO, mine: MyFeedOffer?, onOffer: () -> Unit, onThread: (String) -> Unit) {
    val c = Elchi.colors
    val l = item.listing
    val otherTime = item.fit == DirectionRules.TIME_DIFFERS
    val shape = RoundedCornerShape(ElchiShape.card)
    val dash = c.tone(Tone.WARN).fg.copy(alpha = 0.6f)
    Column(
        Modifier
            .fillMaxWidth()
            .then(if (otherTime) Modifier else Modifier.shadow(12.dp, shape, ambientColor = c.shadow, spotColor = c.shadow))
            .clip(shape)
            .background(c.card)
            .then(
                if (otherTime) Modifier.drawBehind {
                    drawRoundRect(
                        dash,
                        cornerRadius = CornerRadius(ElchiShape.card.toPx()),
                        style = Stroke(width = 1.5.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(6.dp.toPx(), 5.dp.toPx()))),
                    )
                } else Modifier,
            )
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ElchiIconView(ElchiIcon.PIN, c.accentText, size = 16.dp)
                Text(placeTitle(l), style = Elchi.type.bodyStrong, color = c.text)
            }
            FeedRules.matchKey(item.matchType)?.let { key -> Badge(tOrNull(key) ?: key, if (item.matchType == MatchType.EXACT) Tone.OK else Tone.BLUE) }
        }
        Text(t(R.string.dir_card_asked, "start" to DirectionRules.dayClock(l.departureWindowStart), "end" to DirectionRules.clock(l.departureWindowEnd)), style = Elchi.type.caption, color = c.muted)
        item.pickupEta?.let { eta ->
            Text(
                t(R.string.dir_card_eta, "time" to DirectionRules.dayClock(eta)),
                style = Elchi.type.caption.copy(fontWeight = if (otherTime) FontWeight.SemiBold else FontWeight.Normal),
                color = if (otherTime) c.tone(Tone.WARN).fg else c.text,
            )
        }
        if (item.fit == DirectionRules.NO_TRIP) {
            item.suggestedDepartureAt?.let { Text(t(R.string.dir_card_departure, "time" to DirectionRules.dayClock(it)), style = Elchi.type.caption, color = c.muted) }
        }
        whatLine(l)?.let { Text(it, style = Elchi.type.caption, color = c.muted) }
        // Design 07 §5.6 / §5.7 reused: my offer (or the client's yes) on the left, the client's total on the right.
        val threadId = mine?.threadId ?: item.myThreadId
        val meta = when (mine) {
            is MyFeedOffer.Sent -> t(R.string.driver_feed_myOffer, "price" to soum(mine.totalMinor))
            is MyFeedOffer.Accepted -> t(R.string.driver_feed_clientAccepted)
            null -> if (item.myThreadId != null) t(R.string.dir_card_myOffer) else null
        }
        Row(Modifier.fillMaxWidth().padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(meta.orEmpty(), Modifier.weight(1f), style = Elchi.type.caption.copy(fontWeight = FontWeight.SemiBold), color = if (mine is MyFeedOffer.Accepted) c.tone(Tone.OK).fg else c.accentText)
            Text(soum(l.totalMinor), style = Elchi.type.section.copy(fontWeight = FontWeight.SemiBold), color = c.text)
        }
        if (threadId != null) {
            ElchiButton(t(R.string.driver_feed_viewOffer), { onThread(threadId) }, Modifier.fillMaxWidth().height(46.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM)
        } else {
            ElchiButton(t(R.string.driverFeed_sendOffer), onOffer, Modifier.fillMaxWidth().height(46.dp), if (otherTime) ButtonVariant.OUTLINE else ButtonVariant.PRIMARY, ButtonSize.MEDIUM)
        }
    }
}

// -- driver-add-route: the direction form (ADR-0027, Q150) --------------------------------------------------------

/** "Yo'nalish qo'shish": where from → where to and nothing else; the server finds the road. */
@Composable
fun AddDirectionScreen(vm: AddDirectionViewModel, onBack: () -> Unit, onCreated: (DriverDirectionDTO) -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    var picking by remember { mutableStateOf<Boolean?>(null) }
    LaunchedEffect(s.created) { s.created?.let(onCreated) }
    StepScaffold(
        title = t(R.string.driverRoutes_addRoute),
        onBack = onBack,
        footer = {
            ElchiButton(t(R.string.dir_save), vm::save, Modifier.fillMaxWidth(), loading = s.saving, dimmed = s.issues.isNotEmpty())
        },
    ) {
        Text(t(R.string.dir_formHint), style = Elchi.type.secondary, color = Elchi.colors.muted)
        when (val regions = s.regions) {
            Load.Loading -> LoadingState(count = 2)
            is Load.Failed -> LoadFailed(t(R.string.dir_region), regions.error, vm::loadRegions)
            is Load.Ready -> {
                val issues = if (s.showIssues) s.issues else emptySet()
                DirectionEndFields(
                    title = t(R.string.driverFeed_from), regions = regions.value, region = s.form.originRegion, district = s.form.originDistrict,
                    regionMissing = DirectionFormIssue.ORIGIN_REGION in issues, districtMissing = DirectionFormIssue.ORIGIN_DISTRICT in issues,
                    onRegion = { vm.pickRegion(true, it) }, onDistrict = { picking = true },
                )
                DirectionEndFields(
                    title = t(R.string.driverFeed_to), regions = regions.value, region = s.form.destinationRegion, district = s.form.destinationDistrict,
                    regionMissing = DirectionFormIssue.DESTINATION_REGION in issues, districtMissing = DirectionFormIssue.DESTINATION_DISTRICT in issues,
                    onRegion = { vm.pickRegion(false, it) }, onDistrict = { picking = false },
                )
            }
        }
        // ROUTE_MISMATCH / a duplicate: a product answer in place, not an error look.
        s.notice?.let { Note(tOrNull(it.key) ?: it.key, tone = Tone.WARN) }
    }
    picking?.let { origin ->
        val region = if (origin) s.form.originRegion else s.form.destinationRegion
        if (region != null) {
            DistrictSearchDialog(
                region = region,
                districts = s.districts[region.id],
                onRetry = { vm.loadDistricts(region.id) },
                onPick = { district ->
                    vm.pickDistrict(origin, district)
                    picking = null
                },
                onDismiss = { picking = null },
            )
        }
    }
}

@Composable
private fun DirectionEndFields(
    title: String,
    regions: List<RegionDTO>,
    region: RegionDTO?,
    district: DistrictDTO?,
    regionMissing: Boolean,
    districtMissing: Boolean,
    onRegion: (RegionDTO) -> Unit,
    onDistrict: () -> Unit,
) {
    val c = Elchi.colors
    val ru = appRu()
    val required = t(R.string.driver_form_required)
    Text(title, Modifier.padding(top = 6.dp), style = Elchi.type.section, color = c.text)
    SelectField(
        label = t(R.string.dir_region),
        value = region?.id,
        options = regions.map { it.id to ((if (ru) it.nameRu else null) ?: it.nameUz) },
        onSelect = { id -> regions.firstOrNull { it.id == id }?.let(onRegion) },
        placeholder = t(R.string.dir_regionPlaceholder),
        hint = if (regionMissing) required else null,
    )
    val needs = DirectionRules.needsDistrict(region)
    PickerField(
        label = t(R.string.dir_district),
        value = district?.let { (if (ru) it.nameRu else null) ?: it.nameUz } ?: if (region != null && !needs) t(R.string.dir_wholeCity) else null,
        placeholder = if (needs) t(R.string.dir_districtPlaceholder) else t(R.string.dir_wholeCity),
        onClick = { if (region != null) onDistrict() },
        trailingIcon = ElchiIcon.SEARCH,
        error = districtMissing,
        hint = if (districtMissing) required else null,
    )
}

/** The region's districts with a search box; a city without districts offers "the whole city" first. */
@Composable
private fun DistrictSearchDialog(
    region: RegionDTO,
    districts: Load<List<DistrictDTO>>?,
    onRetry: () -> Unit,
    onPick: (DistrictDTO?) -> Unit,
    onDismiss: () -> Unit,
) {
    val c = Elchi.colors
    val ru = appRu()
    // The dialog window speaks the phone's language: every label is resolved here, in the app's.
    val searchLabel = t(R.string.dir_districtSearch)
    val whole = t(R.string.dir_wholeCity)
    val loading = t(R.string.common_loading)
    val regionName = (if (ru) region.nameRu else null) ?: region.nameUz
    var query by remember { mutableStateOf("") }
    Dialog(onDismissRequest = onDismiss) {
        Column(Modifier.fillMaxWidth().heightIn(max = 600.dp).clip(RoundedCornerShape(28.dp)).background(c.card).padding(vertical = 16.dp)) {
            Text(regionName, Modifier.padding(horizontal = 20.dp, vertical = 4.dp), style = Elchi.type.title.copy(fontSize = 19.sp, lineHeight = 23.sp), color = c.text)
            ElchiField(query, { query = it.take(40) }, Modifier.padding(horizontal = 16.dp, vertical = 8.dp), placeholder = searchLabel, icon = ElchiIcon.SEARCH)
            Column(Modifier.verticalScroll(rememberScrollState())) {
                if (!DirectionRules.needsDistrict(region)) ListRow(whole, icon = ElchiIcon.CHECK, first = true, onClick = { onPick(null) })
                when (districts) {
                    null, Load.Loading -> Row(Modifier.padding(horizontal = 20.dp)) { LoadingLine(loading) }
                    is Load.Failed -> Column(Modifier.padding(horizontal = 16.dp)) { LoadFailed(regionName, districts.error, onRetry) }
                    is Load.Ready -> DirectionRules.searchDistricts(districts.value, query)
                        // Tashkent city lists itself as its only district: the whole-city row already says it.
                        .filterNot { !DirectionRules.needsDistrict(region) && it.nameUz == region.nameUz }
                        .forEach { d -> ListRow((if (ru) d.nameRu else null) ?: d.nameUz, first = true, onClick = { onPick(d) }) }
                }
            }
        }
    }
}

// -- driver-direction-bid: the offer from a direction (ADR-0027, Q152/Q153) ---------------------------------------

/** The offer from a direction: price only - the server takes, re-times or plans the trip. */
@Composable
fun DirectionBidScreen(vm: DirectionBidViewModel, driver: DriverViewModel, nav: DriverNav, onBack: () -> Unit, onThread: (String) -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val ds by driver.state.collectAsStateWithLifecycle()
    val c = Elchi.colors
    LaunchedEffect(s.openThread) {
        s.openThread?.let {
            vm.opened()
            onThread(it)
        }
    }
    val item = vm.item
    val status = ds.status
    val gated = status != null && DriverRules.gate(status) != GateVariant.NONE
    val proposeAt = vm.proposeAt()
    StepScaffold(
        title = t(R.string.driverBid_title),
        onBack = onBack,
        footer = if (!gated && item != null) {
            {
                ElchiButton(
                    proposeAt?.let { t(R.string.dir_bid_proposeTime, "time" to DirectionRules.clock(it)) } ?: t(R.string.driverBid_send),
                    { vm.send() }, Modifier.fillMaxWidth(),
                    loading = s.sending, dimmed = (s.price.toLongOrNull() ?: 0) <= 0, maxLines = 2,
                )
            }
        } else null,
    ) {
        if (gated && status != null) {
            VerificationGate(
                status, onDocuments = nav.onDocuments, onProfile = nav.onProfileForm, onSupport = nav.onHelp,
                statusWord = ds.verify?.let { tOrNull(it.labelKey) },
                profileLabel = tOrNull(DriverRules.profileButtonKey(ds.profileDone)),
            )
            return@StepScaffold
        }
        if (item == null) {
            NotFoundState(onBack)
            return@StepScaffold
        }
        val l = item.listing
        ElchiCard(padding = PaddingValues(horizontal = 16.dp, vertical = 14.dp), background = if (c.isDark) c.field else Color(0xFFEEF1F5)) {
            Text(placeTitle(l), style = Elchi.type.bodyStrong, color = c.text)
            Text(t(R.string.driverBid_clientPrice, "price" to soum(l.totalMinor)), Modifier.padding(top = 4.dp), style = Elchi.type.label, color = c.muted)
            whatLine(l)?.let { Text(it, style = Elchi.type.caption, color = c.muted) }
            Text(t(R.string.dir_card_asked, "start" to DirectionRules.dayClock(l.departureWindowStart), "end" to DirectionRules.clock(l.departureWindowEnd)), style = Elchi.type.caption, color = c.muted)
        }
        item.pickupEta?.let { eta ->
            ElchiCard(padding = PaddingValues(horizontal = 16.dp, vertical = 12.dp), background = if (c.isDark) c.field else Color(0xFFEAF5FF)) {
                Text(t(R.string.driverBid_pickupWindow), style = Elchi.type.caption.copy(fontWeight = FontWeight.SemiBold), color = c.accentText)
                Text(t(R.string.dir_card_eta, "time" to DirectionRules.dayClock(eta)), Modifier.padding(top = 2.dp), style = Elchi.type.bodyStrong, color = c.text)
                if (item.fit == DirectionRules.NO_TRIP) {
                    item.suggestedDepartureAt?.let { Text(t(R.string.dir_bid_planned, "time" to DirectionRules.dayClock(it)), Modifier.padding(top = 2.dp), style = Elchi.type.caption, color = c.muted) }
                }
            }
        }
        if (proposeAt != null) {
            Note(
                t(R.string.dir_bid_timeProposal, "time" to DirectionRules.dayClock(proposeAt), "start" to DirectionRules.dayClock(l.departureWindowStart), "end" to DirectionRules.clock(l.departureWindowEnd)),
                tone = Tone.WARN,
            )
        }
        when (val refusal = s.refusal) {
            is DirectionOfferOutcome.TooFar -> Note(t(R.string.dir_bid_tooFar, "early" to refusal.early, "late" to refusal.late), tone = Tone.ERR)
            DirectionOfferOutcome.Passed -> Note(t(R.string.dir_passed), tone = Tone.ERR)
            else -> Unit
        }
        RivalBoard(s.board, vm::loadBoard)
        val perSeat = l.priceBasis == PriceBasis.PER_SEAT
        ElchiField(
            s.price, vm::setPrice,
            label = t(R.string.driverBid_priceLabel) + if (perSeat) " " + t(R.string.listingEdit_perSeatSuffix).trim() else "",
            hint = if (perSeat) ParcelRules.soumToMinor(s.price)?.let { "${seatsPrice(l.quantity, it)} = ${soum(it * l.quantity)}" } else null,
            placeholder = t(R.string.driverBid_pricePlaceholder),
            error = if (s.priceMissing) t(R.string.driver_offer_priceRequired) else null,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            suffix = t(R.string.common_soum),
        )
        ElchiButton(
            t(R.string.driver_bid_acceptClientPrice, "price" to soum(l.totalMinor)), { vm.send(clientPrice = true) },
            Modifier.fillMaxWidth(), ButtonVariant.SOFT, enabled = !s.sending, maxLines = 2,
        )
        FeeBlock(s.fee, prompt = s.price.isEmpty())
        Text(t(R.string.driverBid_noHoldNote), style = Elchi.type.caption.copy(fontSize = 12.sp), color = c.muted)
    }
}
