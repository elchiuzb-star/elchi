package uz.elchi.app.feature.client

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.windowInsetsBottomHeight
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.elchi.app.R
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.session.Session
import uz.elchi.app.ui.components.BottomPanel
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.CardRow
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.PendingReferralRow
import uz.elchi.app.ui.components.RoundIconButton
import uz.elchi.app.ui.components.RouteCard
import uz.elchi.app.ui.components.Segmented
import uz.elchi.app.ui.components.SystemBarIcons
import uz.elchi.app.ui.components.ThemeSwitch
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.map.ElchiMap
import uz.elchi.app.ui.map.GeoPoint
import uz.elchi.app.ui.map.MapFocus
import uz.elchi.app.ui.map.MapKitSupport
import uz.elchi.app.ui.map.MapMarker
import uz.elchi.app.ui.map.MyLocation
import uz.elchi.app.ui.map.decodePolyline
import uz.elchi.app.ui.map.legPath
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.ThemeMode
import uz.elchi.app.ui.theme.Tone

/** Nothing marked yet: the whole country (south-west and north-east corners of Uzbekistan). */
private val UZBEKISTAN = listOf(GeoPoint(37.18, 55.99), GeoPoint(45.59, 73.15))

/** The one automatic move on an empty home: the user's city rather than their street. */
private const val AUTO_ZOOM = 11f

/**
 * `client-home`: full-screen map, floating menu + theme switch, bottom sheet with the service heading, the route
 * card and "Yo'nalishni ko'rish" (enabled once the direction is ready and parcels are open on that corridor).
 */
@Composable
fun ClientHomeScreen(
    vm: ParcelRequestViewModel,
    session: Session,
    ru: Boolean,
    themeMode: ThemeMode,
    onTheme: (ThemeMode) -> Unit,
    onPick: (End) -> Unit,
    onViewRoute: () -> Unit,
    drawer: DrawerNav,
    /** A referral code kept from a link and not used yet: a row on the sheet leads to the bonus screen (web home). */
    referralCode: String? = null,
    onReferral: () -> Unit = {},
) {
    // The unread dot on the menu is read when home appears (and again when the menu opens).
    LaunchedEffect(session.user.id) { drawer.onOpened() }
    ClientDrawerFrame(drawer, DrawerPlace.HOME) { openDrawer ->
        HomeContent(vm, ru, themeMode, onTheme, onMenu = openDrawer, unread = drawer.unreadText, onPick, onViewRoute, referralCode, onReferral)
    }
}

/** The menu button's label, with the unread count when there is one ("Menyu, Bildirishnomalar: 3"). */
@Composable
internal fun menuLabel(unread: String?): String =
    if (unread == null) t(R.string.nav_menu) else "${t(R.string.nav_menu)}, ${t(R.string.notifications_title)}: $unread"

@Composable
private fun HomeContent(
    vm: ParcelRequestViewModel,
    ru: Boolean,
    themeMode: ThemeMode,
    onTheme: (ThemeMode) -> Unit,
    onMenu: () -> Unit,
    unread: String?,
    onPick: (End) -> Unit,
    onViewRoute: () -> Unit,
    referralCode: String?,
    onReferral: () -> Unit,
) {
    val s by vm.state.collectAsStateWithLifecycle()
    val c = Elchi.colors
    val density = LocalDensity.current
    SystemBarIcons(dark = !c.isDark)
    var sheetHeight by remember { mutableIntStateOf(0) }
    var panelHeight by remember { mutableIntStateOf(0) }
    var recentre by remember { mutableIntStateOf(0) }
    var mapUsable by remember { mutableStateOf(MapKitSupport.likelyAvailable) }
    val myLocation = rememberMyLocation()

    val origin = s.draft.origin
    val destination = s.draft.destination
    val markers = listOfNotNull(
        origin?.let { MapMarker(GeoPoint(it.lat, it.lng), MapMarker.Kind.ORIGIN) },
        destination?.let { MapMarker(GeoPoint(it.lat, it.lng), MapMarker.Kind.DESTINATION) },
    )
    val route = remember(s.preview?.routePolyline, markers) {
        legPath(s.preview?.routePolyline?.let(::decodePolyline).orEmpty(), markers.firstOrNull { it.kind == MapMarker.Kind.ORIGIN }?.point, markers.firstOrNull { it.kind == MapMarker.Kind.DESTINATION }?.point)
    }
    val fit = remember(markers, route, recentre) {
        val points = markers.map { it.point } + route
        MapFocus.Fit(points.ifEmpty { UZBEKISTAN }, recentre)
    }
    // The camera goes to the user only on a tap (or once, on an empty home); a new place or the recentre button
    // frames the direction again.
    var userFocus by remember { mutableStateOf<MapFocus.At?>(null) }
    LaunchedEffect(markers, route, recentre) { userFocus = null }
    LaunchedEffect(myLocation.state.centre) {
        val fix = myLocation.state.fix
        if (myLocation.state.centre > 0 && fix != null) userFocus = MapFocus.At(fix.point, MyLocation.ZOOM, myLocation.state.centre)
    }
    var userMovedMap by remember { mutableStateOf(false) }
    var firstFixSeen by remember { mutableStateOf(false) }
    LaunchedEffect(myLocation.state.fix != null) {
        val fix = myLocation.state.fix ?: return@LaunchedEffect
        if (firstFixSeen) return@LaunchedEffect
        firstFixSeen = true
        if (MyLocation.autoCentre(fix, markers.isEmpty(), userMovedMap, UZBEKISTAN)) userFocus = MapFocus.At(fix.point, AUTO_ZOOM, -1)
    }
    val focus = userFocus ?: fit
    val topInset = with(density) { WindowInsets.statusBars.getTop(this).toDp() }

    Box(Modifier.fillMaxSize().background(c.field)) {
        ElchiMap(
            modifier = Modifier.fillMaxSize(),
            markers = markers,
            route = route,
            focus = focus,
            userLocation = myLocation.state.fix,
            padding = PaddingValues(top = topInset + 72.dp, bottom = with(density) { sheetHeight.toDp() } + 8.dp, start = 24.dp, end = 24.dp),
            // On the recentre button's row, left of it, rather than above it.
            logoBottom = with(density) { panelHeight.toDp() } + 16.dp,
            onAvailability = { mapUsable = it },
            onCameraIdle = {
                userMovedMap = true
                myLocation.panned()
            },
            placeholderTitle = t(R.string.client_map_unavailable),
        )

        Row(
            Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            RoundIconButton(ElchiIcon.MENU, menuLabel(unread), onMenu, dot = unread != null)
            Spacer(Modifier.weight(1f))
            ThemeSwitch(themeMode, onTheme, t(R.string.theme_light), t(R.string.theme_dark))
        }

        if (mapUsable) {
            MyLocationBanner(myLocation, Modifier.statusBarsPadding().padding(top = 64.dp, start = 16.dp, end = 16.dp))
        }

        Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth().onSizeChanged { sheetHeight = it.height }) {
            // Right edge, just above the sheet: "my location" (crosshair) and, with a direction on the map, the
            // recentre-on-the-route button under it (route icon, so the two never look alike).
            if (mapUsable) {
                Column(
                    Modifier.align(Alignment.End).padding(start = 16.dp, end = 16.dp, bottom = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    MyLocationButton(myLocation)
                    if (markers.isNotEmpty()) RoundIconButton(ElchiIcon.ROUTE, t(R.string.location_recentre), {
                        recentre++
                        myLocation.panned() // the camera leaves the user: the crosshair is no longer "on"
                    })
                }
            }
            Box(Modifier.onSizeChanged { panelHeight = it.height }) {
                HomeSheet(s, ru, vm::setMode, onPick, onViewRoute, retry = vm::refreshDirection, referralCode = referralCode, onReferral = onReferral)
            }
        }
    }
}

@Composable
private fun HomeSheet(
    s: ParcelRequestViewModel.State,
    ru: Boolean,
    onMode: (ServiceMode) -> Unit,
    onPick: (End) -> Unit,
    onViewRoute: () -> Unit,
    retry: () -> Unit,
    referralCode: String?,
    onReferral: () -> Unit,
) {
    val c = Elchi.colors
    val sheetShape = RoundedCornerShape(topStart = 32.dp, topEnd = 32.dp)
    BottomPanel(Modifier.shadow(16.dp, sheetShape, ambientColor = c.shadow, spotColor = c.shadow).verticalScroll(rememberScrollState())) {
        if (referralCode != null) PendingReferralRow(t(R.string.home_referralCodeSaved, "code" to referralCode), onReferral)
        if (s.passengerEnabled) {
            Segmented(listOf(ServiceMode.TAXI to t(R.string.home_modeTaxi), ServiceMode.PARCEL to t(R.string.home_modeParcel)), s.mode, onMode)
        } else {
            Text(t(R.string.home_modeParcel), Modifier.semantics { heading() }, style = Elchi.type.title.copy(fontSize = 22.sp, lineHeight = 27.sp), color = c.text)
        }
        val origin = s.draft.origin
        val destination = s.draft.destination
        RouteCard(
            from = origin?.district(ru),
            fromDetail = origin?.label(ru),
            to = destination?.district(ru),
            toDetail = destination?.label(ru),
            fromPlaceholder = t(R.string.direction_from),
            toPlaceholder = t(R.string.direction_to),
            onFrom = { onPick(End.ORIGIN) },
            onTo = { onPick(End.DESTINATION) },
        )
        if (s.mode == ServiceMode.TAXI) {
            Note(t(R.string.client_home_taxiSoon))
        } else {
            when (val d = s.direction) {
                Direction.Incomplete -> Unit
                Direction.Checking -> Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    CircularProgressIndicator(Modifier.size(16.dp), color = c.brand, strokeWidth = 2.dp)
                    Text(t(R.string.home_checkingRoute), style = Elchi.type.label, color = c.muted)
                }
                is Direction.Ready -> {
                    val p = d.preview
                    ElchiCard(background = c.highlight) {
                        CardRow(t(R.string.home_estimatedTime, "corridor" to p.corridorName), roadText(p.legDistanceM, p.legDurationS), first = true, strong = true)
                    }
                    ParcelRules.offRouteMeters(p)?.let { Note(t(R.string.app_location_offRoute, "km" to ParcelRules.km(it)), tone = Tone.WARN) }
                }
                Direction.Mismatch -> Note(t(R.string.home_movePointHint), tone = Tone.ERR, title = t(R.string.app_location_previewMismatch))
                is Direction.Failed -> {
                    Note(errorText(d.error), tone = Tone.ERR)
                    ElchiButton(t(R.string.common_retry), retry, Modifier.fillMaxWidth(), ButtonVariant.GHOST, ButtonSize.MEDIUM, icon = ElchiIcon.REFRESH)
                }
            }
        }
        ElchiButton(t(R.string.home_viewRoute), onViewRoute, Modifier.fillMaxWidth(), enabled = s.canContinueFromHome)
        if (s.mode == ServiceMode.PARCEL && s.parcelEnabled == false) {
            Text(t(R.string.home_parcelClosed), Modifier.fillMaxWidth(), style = Elchi.type.label.copy(fontWeight = FontWeight.Normal), color = Elchi.colors.danger, textAlign = TextAlign.Center)
        }
        Spacer(Modifier.windowInsetsBottomHeight(WindowInsets.navigationBars))
    }
}

/** `308 km · 4 soat 35 daqiqa` - the road between the two marked places, not the whole corridor. */
@Composable
internal fun roadText(meters: Long, seconds: Long): String = "${t(R.string.app_distance_km, "value" to ParcelRules.km(meters))} · ${durationText(seconds)}"

@Composable
internal fun durationText(seconds: Long): String {
    val (hours, minutes) = ParcelRules.durationParts(seconds)
    return when {
        hours > 0 && minutes > 0 -> t(R.string.app_duration_hoursMinutes, "hours" to hours, "minutes" to minutes)
        hours > 0 -> t(R.string.app_duration_hours, "hours" to hours)
        else -> t(R.string.app_duration_minutes, "minutes" to minutes)
    }
}

internal fun displayPhone(phone: String): String {
    val digits = ParcelRules.localDigits(phone)
    return if (digits.length == 9) "+998 ${ParcelRules.groupPhone(digits)}" else phone
}
