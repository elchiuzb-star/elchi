package uz.elchi.app.feature.driver

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
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
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.elchi.app.R
import uz.elchi.app.api.generated.DistrictDTO
import uz.elchi.app.api.generated.FeedItemDTO
import uz.elchi.app.api.generated.MatchType
import uz.elchi.app.api.generated.RegionDTO
import uz.elchi.app.api.generated.SavedSearchDTO
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.feature.client.Load
import uz.elchi.app.feature.client.LoadFailed
import uz.elchi.app.feature.client.LoadingLine
import uz.elchi.app.feature.client.OrderRules
import uz.elchi.app.feature.client.StepScaffold
import uz.elchi.app.feature.client.categoryLimits
import uz.elchi.app.feature.client.categoryName
import uz.elchi.app.feature.client.seatsLine
import uz.elchi.app.feature.client.soum
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.Badge
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.CardRow
import uz.elchi.app.ui.components.Chip
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiDialog
import uz.elchi.app.ui.components.ElchiIconView
import uz.elchi.app.ui.theme.ElchiShape
import uz.elchi.app.ui.components.EmptyState
import uz.elchi.app.ui.components.ItemCard
import uz.elchi.app.ui.components.ListRow
import uz.elchi.app.ui.components.LoadingState
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.RouteCard
import uz.elchi.app.ui.components.SectionTitle
import uz.elchi.app.ui.components.Segmented
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone

// -- driver-feed ------------------------------------------------------------------------------------------------

/** The Matches tab body (the gate is the caller's): mode, direction, dates, notes, primary then alternatives. */
@Composable
internal fun ColumnScope.FeedBody(
    vm: FeedViewModel,
    onSaved: () -> Unit,
    onOffer: (FeedItemDTO) -> Unit,
    /** The driver's own threads (design 07 §5.7): a card already offered on says so and opens the thread. */
    proposals: ProposalsViewModel? = null,
    onThread: (String) -> Unit = {},
    /** Q148 on this tab root too (design 07 §4.9): the running trip's GPS bar. */
    trips: TripsViewModel? = null,
    tracker: uz.elchi.app.gps.DriverTracker? = null,
    /** False when the caller draws the Taksi/Pochta toggle itself (ADR-0027: shared with the direction feed). */
    showService: Boolean = true,
) {
    val s by vm.state.collectAsStateWithLifecycle()
    val c = Elchi.colors
    var picking by remember { mutableStateOf<Boolean?>(null) }
    val f = s.filter
    if (trips != null && tracker != null) {
        val ts by trips.state.collectAsStateWithLifecycle()
        TripRules.trackable(ts.list)?.let { running -> uz.elchi.app.gps.DriverTrackingBar(tracker, running.id, inset = 0.dp) }
    }
    val mine: Map<String, MyFeedOffer> = proposals?.let { p ->
        val ps by p.state.collectAsStateWithLifecycle()
        Design07Rules.myFeedOffers(ps.open, (ps.lists[ProposalTab.ACCEPTED] as? Load.Ready)?.value.orEmpty(), ps.mine)
    }.orEmpty()
    if (showService && s.passengerEnabled) {
        Segmented(
            listOf(ServiceType.PASSENGER to t(R.string.driverFeed_modeTaxi), ServiceType.PARCEL to t(R.string.driverFeed_modeParcel)),
            f.serviceType,
            vm::pickService,
        )
    }
    val ru = appRu()
    RouteCard(
        from = f.origin.label(ru),
        fromDetail = f.origin.region(ru).takeIf { f.origin.districtId != null },
        to = f.destination.label(ru),
        toDetail = f.destination.region(ru).takeIf { f.destination.districtId != null },
        fromPlaceholder = t(R.string.driverFeed_from),
        toPlaceholder = t(R.string.driverFeed_to),
        onFrom = { picking = true },
        onTo = { picking = false },
    )
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        FeedDays.entries.forEach { days ->
            Chip(tOrNull(days.key) ?: days.name, f.days == days, { vm.pickDays(days) }, filled = true)
        }
    }
    Text(t(R.string.driverFeed_districtHint), style = Elchi.type.caption.copy(fontSize = 12.sp), color = c.muted)
    // Design 07 §5.4: the count on the button ("Saqlangan yo'nalishlar (2)").
    ElchiButton(
        s.savedCount?.let { t(R.string.driver_feed_savedCount, "count" to it) } ?: t(R.string.driverFeed_savedSearches),
        onSaved, Modifier.fillMaxWidth().height(44.dp), ButtonVariant.SOFT, ButtonSize.MEDIUM, icon = ElchiIcon.ARCHIVE,
    )
    // Q158: no "bekat" on screen - the matches follow the confirmed road, the meeting place is agreed in the chat.
    Note(t(R.string.match_confirmedRoadsNote), tone = Tone.WARN)
    s.degraded.forEach { code -> tOrNull("warning.$code")?.let { Note(it, tone = Tone.GRAY) } }

    val query = FeedRules.query(f, java.time.Instant.now())
    when {
        query == null -> EmptyState(ElchiIcon.RADAR, t(R.string.driverFeed_emptyTitle), description = t(R.string.driverFeed_emptyPickFirst))
        s.loading && s.items.isEmpty() -> LoadingState(count = 2)
        s.error != null && s.items.isEmpty() -> LoadFailed(t(R.string.driverFeed_title), s.error!!, vm::refresh)
        s.loaded && s.items.isEmpty() -> EmptyState(ElchiIcon.RADAR, t(R.string.driverFeed_emptyTitle), description = t(R.string.driver_feed_emptyHint))
        else -> {
            val groups = s.groups
            groups.primary.forEach { item -> FeedCard(item, alternative = false, mine = mine[item.listing.id], onOffer = { onOffer(item) }, onThread = onThread) }
            if (groups.alternative.isNotEmpty()) {
                SectionTitle(t(R.string.match_alternativesTitle), Modifier.padding(top = 6.dp), description = t(R.string.match_alternativesNote))
                groups.alternative.forEach { item -> FeedCard(item, alternative = true, mine = mine[item.listing.id], onOffer = { onOffer(item) }, onThread = onThread) }
            }
            if (s.next != null) {
                ElchiButton(t(R.string.blockReport_loadMore), vm::loadMore, Modifier.fillMaxWidth().height(44.dp), ButtonVariant.GHOST, ButtonSize.MEDIUM, loading = s.loadingMore)
            }
        }
    }
    picking?.let { origin ->
        EndPickerDialog(
            title = t(if (origin) R.string.driverFeed_from else R.string.driverFeed_to),
            regions = (s.regions as? Load.Ready)?.value.orEmpty(),
            districts = s.districts,
            current = if (origin) f.origin else f.destination,
            onRegion = { region -> vm.pickRegion(origin, region) },
            onDistrict = { district ->
                vm.pickDistrict(origin, district)
                picking = null
            },
            onDismiss = { picking = null },
        )
    }
}

/**
 * The prototype's feed `item`: route (district names), the match badge (or an alternative's reason),
 * the window, what is carried, the client's total and "Taklif yuborish". Alternatives get a dashed frame.
 */
@Composable
private fun FeedCard(item: FeedItemDTO, alternative: Boolean, mine: MyFeedOffer? = null, onOffer: () -> Unit, onThread: (String) -> Unit = {}) {
    val c = Elchi.colors
    val ru = appRu()
    val l = item.listing
    val badge: Pair<String, Tone>? = if (alternative) {
        FeedRules.alternativeReason(item.match.reasons)?.let { reason ->
            (tOrNull("match.reason.$reason") ?: reason) to (if (reason == "time_differs") Tone.WARN else Tone.BLUE)
        } ?: (t(R.string.match_alternative) to Tone.GRAY)
    } else {
        FeedRules.matchKey(item.match.matchType)?.let { key -> (tOrNull(key) ?: key) to (if (item.match.matchType == MatchType.EXACT) Tone.OK else Tone.BLUE) }
    }
    val window = OrderRules.parseInstant(l.departureWindowStart)?.let { s -> OrderRules.parseInstant(l.departureWindowEnd)?.let { e -> DriverTime.range(s, e) } }
    val what = if (l.serviceType == ServiceType.PARCEL) {
        l.parcelCategory?.let { "${categoryName(it, ru)} · ${categoryLimits(it)}" }
    } else {
        // Taksi: "2 kishi · 2 × 150 000 so'm" - the client's price is per person.
        seatsLine(l.quantity, l.unitPriceMinor)
    }
    val shape = RoundedCornerShape(ElchiShape.card)
    val dash = c.outline
    Column(
        Modifier
            .fillMaxWidth()
            .then(if (alternative) Modifier else Modifier.shadow(12.dp, shape, ambientColor = c.shadow, spotColor = c.shadow))
            .clip(shape)
            .background(c.card)
            .then(
                if (alternative) Modifier.drawBehind {
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
                Text(
                    "${FeedRules.endName(l.originPoint, ru)} → ${FeedRules.endName(l.destinationPoint, ru)}",
                    style = Elchi.type.bodyStrong,
                    color = c.text,
                )
            }
            badge?.let { Badge(it.first, it.second) }
        }
        window?.let { Text(it, style = Elchi.type.caption, color = c.muted) }
        what?.let { Text(it, style = Elchi.type.caption, color = c.muted) }
        // Design 07 §5.6 / §5.7: the meta on the left (my offer, or the client's yes), the client's total on the right.
        val meta = when (mine) {
            is MyFeedOffer.Sent -> t(R.string.driver_feed_myOffer, "price" to soum(mine.totalMinor))
            is MyFeedOffer.Accepted -> t(R.string.driver_feed_clientAccepted)
            null -> null
        }
        Row(Modifier.fillMaxWidth().padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(meta.orEmpty(), Modifier.weight(1f), style = Elchi.type.caption.copy(fontWeight = FontWeight.SemiBold), color = if (mine is MyFeedOffer.Accepted) c.tone(Tone.OK).fg else c.accentText)
            Text(soum(l.totalMinor), style = Elchi.type.section.copy(fontWeight = FontWeight.SemiBold), color = c.text)
        }
        if (mine != null) {
            ElchiButton(t(R.string.driver_feed_viewOffer), { onThread(mine.threadId) }, Modifier.fillMaxWidth().height(46.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM)
        } else {
            ElchiButton(
                t(R.string.driverFeed_sendOffer), onOffer, Modifier.fillMaxWidth().height(46.dp),
                if (alternative) ButtonVariant.OUTLINE else ButtonVariant.PRIMARY, ButtonSize.MEDIUM,
            )
        }
    }
}

/** Region → district for one end. A region that does not require a district (Tashkent city) can be taken whole. */
@Composable
private fun EndPickerDialog(
    title: String,
    regions: List<RegionDTO>,
    districts: Map<String, List<DistrictDTO>>,
    current: FeedEnd,
    onRegion: (RegionDTO) -> Unit,
    onDistrict: (DistrictDTO?) -> Unit,
    onDismiss: () -> Unit,
) {
    val c = Elchi.colors
    var region by remember { mutableStateOf(regions.firstOrNull { it.id == current.regionId }?.takeIf { current.districtId == null && it.requiresDistrict != false }) }
    val loading = t(R.string.common_loading)
    val back = t(R.string.common_back)
    val ru = appRu()
    fun RegionDTO.name() = (if (ru) nameRu else null) ?: nameUz
    fun DistrictDTO.name() = (if (ru) nameRu else null) ?: nameUz
    val wholeRegion = region?.name()
    Dialog(onDismissRequest = onDismiss) {
        Column(Modifier.fillMaxWidth().heightIn(max = 560.dp).clip(RoundedCornerShape(28.dp)).background(c.card).padding(vertical = 16.dp)) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(region?.name() ?: title, Modifier.weight(1f), style = Elchi.type.title.copy(fontSize = 19.sp, lineHeight = 23.sp), color = c.text)
                if (region != null) {
                    Text(back, Modifier.clip(RoundedCornerShape(12.dp)).clickable(role = Role.Button) { region = null }.padding(10.dp), style = Elchi.type.label, color = c.accentText)
                }
            }
            Column(Modifier.verticalScroll(rememberScrollState())) {
                val r = region
                if (r == null) {
                    regions.forEach { item ->
                        ListRow(item.name(), first = true, onClick = {
                            onRegion(item)
                            region = item
                        })
                    }
                } else {
                    val list = districts[r.id]
                    if (r.requiresDistrict == false && wholeRegion != null) {
                        ListRow(wholeRegion, icon = ElchiIcon.CHECK, first = true, onClick = { onDistrict(null) })
                    }
                    if (list == null) {
                        Row(Modifier.padding(horizontal = 20.dp)) { LoadingLine(loading) }
                    } else {
                        // Tashkent city lists itself as its only district: the whole-region row already says it.
                        list.filterNot { r.requiresDistrict == false && it.name() == wholeRegion }.forEach { d ->
                            ListRow(d.name(), first = true, onClick = { onDistrict(d) })
                        }
                    }
                }
            }
        }
    }
}

// -- driver-saved-searches --------------------------------------------------------------------------------------

/** `driver-saved-searches`: what saving does, the current direction, save it, the list with delete. */
@Composable
fun SavedSearchesScreen(vm: SavedSearchesViewModel, feed: FeedViewModel, onBack: () -> Unit, onOpenedInFeed: () -> Unit = onBack) {
    val s by vm.state.collectAsStateWithLifecycle()
    val fs by feed.state.collectAsStateWithLifecycle()
    var deleting by remember { mutableStateOf<SavedSearchDTO?>(null) }
    val query = FeedRules.query(fs.filter, java.time.Instant.now())
    StepScaffold(title = t(R.string.savedSearches_title), onBack = onBack, onRefresh = vm::refresh, refreshing = false) {
        Text(t(R.string.savedSearches_intro), style = Elchi.type.secondary, color = Elchi.colors.text)
        ElchiCard {
            CardRow(
                t(R.string.savedSearches_currentDirection),
                if (query != null) "${fs.filter.origin.label(appRu())} → ${fs.filter.destination.label(appRu())}" else t(R.string.savedSearches_pickEndsFirst),
                first = true,
                muted = query == null,
            )
        }
        // Design 07 §6.2 / §6.3: grey "Allaqachon saqlangan" for the current ends, and no save past the limit.
        val list = (s.saved as? Load.Ready)?.value.orEmpty()
        val already = Design07Rules.alreadySaved(list, query)
        val full = Design07Rules.atLimit(list)
        ElchiButton(
            t(if (already) R.string.driver_routes_alreadySaved else R.string.savedSearches_save), vm::saveCurrent, Modifier.fillMaxWidth(),
            enabled = query != null && s.saved is Load.Ready, loading = s.saving, dimmed = already || full,
        )
        when (val saved = s.saved) {
            Load.Loading -> LoadingState(count = 2)
            is Load.Failed -> LoadFailed(t(R.string.savedSearches_title), saved.error, vm::refresh)
            is Load.Ready -> if (saved.value.isEmpty()) {
                EmptyState(ElchiIcon.ROUTE, t(R.string.savedSearches_emptyTitle), description = t(R.string.savedSearches_emptySubtitle))
            } else {
                saved.value.forEach { item ->
                    val range = OrderRules.dayRange(item.timeWindowStart, item.timeWindowEnd).orEmpty()
                    val title = FeedRules.savedRouteTitle(item, fs.names(appRu()))
                    val regions = (fs.regions as? Load.Ready)?.value.orEmpty()
                    val openable = Design07Rules.filterFor(item, fs.filter, regions, fs.allDistricts) != null
                    ItemCard(
                        title = title,
                        icon = ElchiIcon.ROUTE,
                        sub = "$range · ${t(if (item.notify) R.string.savedSearches_notifyOn else R.string.savedSearches_notifyOff)}",
                        footer = {
                            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                // Design 07 §6.5: the saved ends become the feed's filter.
                                ElchiButton(
                                    t(R.string.driver_routes_openInFeed), { if (vm.openInFeed(item, title.substringAfter("→ "))) onOpenedInFeed() },
                                    Modifier.weight(1f).height(44.dp), ButtonVariant.SOFT, ButtonSize.MEDIUM, enabled = openable, horizontalPadding = 10.dp, maxLines = 2,
                                )
                                ElchiButton(
                                    t(R.string.common_delete), { deleting = item }, Modifier.weight(1f).height(44.dp), ButtonVariant.DANGER_SOFT, ButtonSize.MEDIUM,
                                    loading = item.id in s.deleting, horizontalPadding = 10.dp,
                                )
                            }
                        },
                    )
                }
            }
        }
        val count = (s.saved as? Load.Ready)?.value?.size
        Text(count?.let { t(R.string.driver_routes_limitCount, "limit" to FeedRules.SAVED_LIMIT, "count" to it) } ?: t(R.string.driver_saved_limitHint, "limit" to FeedRules.SAVED_LIMIT), style = Elchi.type.caption.copy(fontSize = 11.sp), color = Elchi.colors.muted)
        Text(t(R.string.driver_saved_notifyNote), style = Elchi.type.caption.copy(fontSize = 11.sp), color = Elchi.colors.muted)
    }
    deleting?.let { item ->
        ElchiDialog(
            title = t(R.string.common_delete),
            text = "${FeedRules.savedRouteTitle(item, fs.names(appRu()))}. ${t(R.string.confirmDialog_cancelOrder_text)}",
            confirm = t(R.string.common_delete),
            onConfirm = {
                deleting = null
                vm.delete(item)
            },
            onDismiss = { deleting = null },
            confirmVariant = ButtonVariant.DANGER,
            dismiss = t(R.string.confirmDialog_back),
        )
    }
}
