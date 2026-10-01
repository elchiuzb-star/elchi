package uz.elchi.app.feature.client

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.windowInsetsBottomHeight
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.elchi.app.R
import uz.elchi.app.api.generated.DistrictDTO
import uz.elchi.app.api.generated.RegionDTO
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.ui.components.BottomPanel
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.CardRow
import uz.elchi.app.ui.components.Chip
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiField
import uz.elchi.app.ui.components.ElchiIconView
import uz.elchi.app.ui.components.ListCard
import uz.elchi.app.ui.components.ListRow
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.SystemBarIcons
import uz.elchi.app.ui.components.TitleBar
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.map.ElchiMap
import uz.elchi.app.ui.map.GeoPoint
import uz.elchi.app.ui.map.MapFocus
import uz.elchi.app.ui.map.MapKitSupport
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone

private fun RegionDTO.name(ru: Boolean) = if (ru) nameRu ?: nameUz else nameUz
private fun DistrictDTO.name(ru: Boolean) = if (ru) nameRu ?: nameUz else nameUz

@Composable
private fun endTitle(end: End) = t(if (end == End.ORIGIN) R.string.direction_from else R.string.direction_to)

/** Case- and apostrophe-insensitive contains ("Farg'ona" = "fargʻona" = "fargona"). */
private fun matches(name: String, query: String): Boolean {
    fun norm(s: String) = s.lowercase().replace(Regex("[ʻ'’`ʼ]"), "")
    return norm(name).contains(norm(query.trim()))
}

// -- client-location-selector ------------------------------------------------------------------------------------

@Composable
fun RegionScreen(vm: PlacePickerViewModel, end: End, ru: Boolean, onBack: () -> Unit, onRegion: (RegionDTO) -> Unit) {
    val regions by vm.regions.collectAsStateWithLifecycle()
    var query by rememberSaveable { mutableStateOf("") }
    StepScaffold(title = endTitle(end), onBack = onBack) {
        ElchiField(query, { query = it }, placeholder = t(R.string.location_search), icon = ElchiIcon.SEARCH, keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search))
        Text(t(R.string.client_location_pickRegionSubtitle), style = Elchi.type.label.copy(fontWeight = FontWeight.Normal), color = Elchi.colors.muted)
        when (val r = regions) {
            Load.Loading -> LoadingLine(t(R.string.location_regionsLoading))
            is Load.Failed -> LoadFailed(t(R.string.location_regionsLoadFailed), r.error, vm::loadRegions)
            is Load.Ready -> {
                val shown = r.value.filter { matches(it.name(ru), query) || matches(it.nameUz, query) }
                if (shown.isEmpty()) {
                    Note(t(R.string.location_regionNotFound), tone = Tone.GRAY)
                } else {
                    ListCard {
                        shown.forEachIndexed { i, region ->
                            ListRow(
                                region.name(ru),
                                icon = ElchiIcon.PIN,
                                description = t(if (region.requiresDistrict == false) R.string.location_noDistrict else R.string.location_districtRequired),
                                first = i == 0,
                                onClick = { onRegion(region) },
                            )
                        }
                    }
                }
            }
        }
    }
}

// -- client-district-selector ------------------------------------------------------------------------------------

@Composable
fun DistrictScreen(vm: PlacePickerViewModel, regionId: String, ru: Boolean, onBack: () -> Unit, onDistrict: (DistrictDTO) -> Unit) {
    LaunchedEffect(regionId) { vm.loadDistricts(regionId) }
    val districts by vm.districts.collectAsStateWithLifecycle()
    val regions by vm.regions.collectAsStateWithLifecycle()
    val region = (regions as? Load.Ready)?.value?.firstOrNull { it.id == regionId }
    var query by rememberSaveable { mutableStateOf("") }
    StepScaffold(title = t(R.string.location_pickDistrict), onBack = onBack, right = region?.name(ru)) {
        ElchiField(query, { query = it }, placeholder = t(R.string.location_search), icon = ElchiIcon.SEARCH, keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search))
        when (val d = districts) {
            Load.Loading -> LoadingLine(t(R.string.location_districtsLoading))
            is Load.Failed -> LoadFailed(t(R.string.location_districtsLoadFailed), d.error) { vm.loadDistricts(regionId, force = true) }
            is Load.Ready -> {
                val shown = d.value.filter { matches(it.name(ru), query) || matches(it.nameUz, query) }
                if (shown.isEmpty()) {
                    Note(t(R.string.location_districtNotFound), tone = Tone.GRAY)
                } else {
                    ListCard {
                        shown.forEachIndexed { i, district ->
                            ListRow(district.name(ru), first = i == 0, onClick = { onDistrict(district) })
                        }
                    }
                }
            }
        }
    }
}

// -- client-point-picker -----------------------------------------------------------------------------------------

/**
 * A fixed centre pin over the map: the camera moves, the pin stays, the place under it is named after the map
 * rests. Without a map the same screen works from search and the district centre.
 */
@Composable
fun PointPickerScreen(
    vm: PlacePickerViewModel,
    end: End,
    regionId: String,
    districtId: String,
    existing: Place?,
    ru: Boolean,
    onBack: () -> Unit,
    onConfirm: (Place) -> Unit,
) {
    val c = Elchi.colors
    val density = LocalDensity.current
    val focusManager = LocalFocusManager.current
    var mapUsable by remember { mutableStateOf(MapKitSupport.likelyAvailable) }
    // The fixed pin waits for drawn tiles: over the loading surface it would only hide the spinner.
    var mapShown by remember { mutableStateOf(false) }
    LaunchedEffect(regionId, districtId) { vm.openPoint(regionId, districtId, existing, mapUsable) }
    val s by vm.point.collectAsStateWithLifecycle()
    SystemBarIcons(dark = !c.isDark)
    // System back leaves the same way as the back button (the half-picked place is dropped).
    BackHandler(onBack = onBack)

    var sheetHeight by remember { mutableIntStateOf(0) }
    // Title bar (64) + search field (50 + 8): the suggestions dropdown floats over the map without moving it.
    val headerHeight = with(density) { WindowInsets.statusBars.getTop(this).toDp() } + 122.dp
    var focus by remember { mutableStateOf<MapFocus?>(null) }
    // First frame of the map: the existing point up close (it was placed on a street), else the district centre,
    // else the region centre - the last two only once the district has loaded, so the zoom matches what is known.
    LaunchedEffect(s.district?.id) {
        if (focus == null) {
            val placed = existing?.takeIf { it.districtId == districtId }?.let { GeoPoint(it.lat, it.lng) }
            val centre = s.centre
            focus = when {
                placed != null -> MapFocus.At(placed, 16f)
                centre != null -> MapFocus.At(centre, if (s.district?.centerLat != null) 14f else 9f)
                else -> null
            }
        }
    }
    val mapPadding = PaddingValues(top = headerHeight, bottom = with(density) { sheetHeight.toDp() })

    Box(Modifier.fillMaxSize().background(c.field).imePadding()) {
        ElchiMap(
            modifier = Modifier.fillMaxSize(),
            focus = focus,
            padding = mapPadding,
            onCameraIdle = vm::onPinMoved,
            onAvailability = {
                mapUsable = it
                mapShown = it
            },
            placeholderTitle = t(R.string.client_map_unavailable),
            placeholderText = t(R.string.client_map_unavailableHint),
        )
        if (mapShown) {
            // The fixed pin: its tip is the centre of the free map area, which is the camera target.
            Box(Modifier.fillMaxSize().padding(mapPadding), contentAlignment = Alignment.Center) {
                ElchiIconView(ElchiIcon.PIN, c.pin, Modifier.offset(y = (-18).dp), size = 40.dp, contentDescription = t(R.string.location_chosenPlace))
            }
        }

        Column(Modifier.fillMaxWidth().statusBarsPadding()) {
            TitleBar(onBack, t(R.string.common_back), endTitle(end), right = s.region?.let { if (ru) it.nameRu ?: it.nameUz else it.nameUz })
            MapSearch(s, ru, onQuery = vm::onQuery, onClear = vm::clearSearch, mapUsable = mapUsable, onPick = { suggestion ->
                focusManager.clearFocus()
                vm.pickSuggestion(suggestion) { point -> focus = MapFocus.At(point, 16f) }
            })
        }

        Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth().onSizeChanged { sheetHeight = it.height }) {
            BottomPanel(Modifier.shadow(16.dp, RoundedCornerShape(topStart = 32.dp, topEnd = 32.dp), ambientColor = c.shadow, spotColor = c.shadow).heightIn(max = 460.dp).verticalScroll(rememberScrollState())) {
                val districtName = s.district?.let { if (ru) it.nameRu ?: it.nameUz else it.nameUz }
                val regionName = s.region?.let { if (ru) it.nameRu ?: it.nameUz else it.nameUz }
                if (districtName != null) {
                    Text(listOfNotNull(districtName, regionName.takeIf { it != districtName }).joinToString(", "), style = Elchi.type.secondary.copy(fontWeight = FontWeight.SemiBold), color = c.text)
                }
                s.loadError?.let { Note(errorText(it), tone = Tone.ERR) }
                if (s.stops.isNotEmpty() || (!mapUsable && s.districtCentre != null)) {
                    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        if (!mapUsable && s.districtCentre != null) {
                            Chip(t(R.string.client_pointPicker_useDistrictCentre), selected = false, onClick = vm::useDistrictCentre, icon = ElchiIcon.LOCATE)
                        }
                        s.stops.forEach { stop ->
                            Chip(if (ru) stop.nameRu ?: stop.nameUz else stop.nameUz, selected = s.candidate?.stop?.id == stop.id, onClick = {
                                vm.pickStop(stop)
                                focus = MapFocus.At(GeoPoint(stop.point.lat, stop.point.lng), 16f)
                            }, icon = ElchiIcon.PIN)
                        }
                    }
                }
                if (!mapUsable && s.district != null && s.districtCentre == null) Note(t(R.string.location_mapKeyMissingNoCentre), tone = Tone.WARN)
                val candidate = s.candidate
                ElchiCard(bordered = true) {
                    when {
                        candidate == null -> CardRow(t(R.string.location_chosenPlace), t(R.string.location_placeNotMarked), first = true, muted = true)
                        else -> {
                            val coords = ParcelRules.coordinates(candidate.point.lat, candidate.point.lng)
                            val name = candidate.stop?.let { if (ru) it.nameRu ?: it.nameUz else it.nameUz } ?: candidate.address
                            CardRow(
                                t(R.string.location_chosenPlace),
                                when {
                                    name != null -> name
                                    candidate.resolving -> t(R.string.location_addressResolving)
                                    else -> coords
                                },
                                first = true,
                                detail = if (name != null || candidate.resolving) coords else null,
                                muted = name == null && candidate.resolving,
                            )
                        }
                    }
                }
                Text(t(R.string.location_radiusHintKm, "km" to 5), style = Elchi.type.caption, color = c.muted)
                ElchiButton(
                    t(R.string.location_pickThisPlace),
                    { vm.confirm(onConfirm) },
                    Modifier.fillMaxWidth(),
                    enabled = candidate != null && s.district != null,
                    loading = s.confirming,
                )
                Spacer(Modifier.windowInsetsBottomHeight(WindowInsets.navigationBars))
            }
        }
    }
}

/** The search field floating over the map, with its suggestions right under it. */
@Composable
private fun MapSearch(
    s: PlacePickerViewModel.PointState,
    ru: Boolean,
    onQuery: (String) -> Unit,
    onClear: () -> Unit,
    mapUsable: Boolean,
    onPick: (uz.elchi.app.api.PlaceSuggestion) -> Unit,
) {
    val c = Elchi.colors
    val placeholder = t(R.string.location_searchPlaceholder)
    val clearLabel = t(R.string.common_close)
    Column(Modifier.padding(horizontal = 16.dp).padding(top = 4.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(
            Modifier
                .fillMaxWidth()
                .heightIn(min = 50.dp)
                .shadow(12.dp, CircleShape, ambientColor = c.shadow, spotColor = c.shadow)
                .clip(CircleShape)
                .background(c.card)
                .padding(start = 18.dp, end = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            ElchiIconView(ElchiIcon.SEARCH, c.muted, size = 18.dp)
            BasicTextField(
                value = s.query,
                onValueChange = onQuery,
                singleLine = true,
                textStyle = Elchi.type.secondary.copy(color = c.text),
                cursorBrush = SolidColor(c.brand),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                modifier = Modifier.weight(1f).semantics { contentDescription = placeholder },
                decorationBox = { inner ->
                    Box(contentAlignment = Alignment.CenterStart) {
                        if (s.query.isEmpty()) Text(placeholder, style = Elchi.type.secondary, color = c.placeholder, maxLines = 1)
                        inner()
                    }
                },
            )
            when {
                s.searching -> CircularProgressIndicator(Modifier.padding(10.dp).size(18.dp), color = c.brand, strokeWidth = 2.dp)
                s.query.isNotEmpty() -> Box(
                    Modifier.size(44.dp).clip(CircleShape).clickable(role = Role.Button, onClick = onClear).semantics { contentDescription = clearLabel },
                    contentAlignment = Alignment.Center,
                ) { ElchiIconView(ElchiIcon.X, c.muted, size = 18.dp) }
            }
        }
        when {
            s.suggestions.isNotEmpty() -> ListCard(Modifier.heightIn(max = 300.dp).verticalScroll(rememberScrollState())) {
                s.suggestions.forEachIndexed { i, suggestion ->
                    ListRow(
                        suggestion.title ?: suggestion.formattedAddress ?: "",
                        description = listOfNotNull(suggestion.subtitle ?: suggestion.formattedAddress, suggestion.distanceM?.let { distanceText(it) }).joinToString(" · ").ifEmpty { null },
                        first = i == 0,
                        chevron = false,
                        onClick = { onPick(suggestion) },
                    )
                }
            }
            s.searchError != null -> SearchNote(errorText(s.searchError))
            s.searchMiss && s.query.isNotEmpty() -> SearchNote(t(if (mapUsable) R.string.location_searchMiss else R.string.client_pointPicker_searchMissNoMap))
        }
    }
}

@Composable
private fun SearchNote(text: String) {
    ElchiCard(padding = PaddingValues(horizontal = 16.dp, vertical = 12.dp)) {
        Text(text, style = Elchi.type.label.copy(fontWeight = FontWeight.Normal), color = Elchi.colors.muted, maxLines = 3, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
private fun distanceText(meters: Double): String =
    if (meters < 1000) t(R.string.location_distanceM, "m" to meters.toInt()) else t(R.string.location_distanceKm, "km" to ParcelRules.km(meters.toLong()))

@Composable
internal fun LoadingLine(text: String) {
    Row(Modifier.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        CircularProgressIndicator(Modifier.size(18.dp), color = Elchi.colors.brand, strokeWidth = 2.dp)
        Text(text, style = Elchi.type.label, color = Elchi.colors.muted)
    }
}

@Composable
internal fun LoadFailed(title: String, error: Throwable, onRetry: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Note(errorText(error), tone = Tone.ERR, title = title)
        ElchiButton(t(R.string.common_retry), onRetry, Modifier.fillMaxWidth(), ButtonVariant.GHOST, ButtonSize.MEDIUM, icon = ElchiIcon.REFRESH)
    }
}
