package uz.elchi.app.feature.client

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.windowInsetsBottomHeight
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
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
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
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
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiIconView
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.RoundIconButton
import uz.elchi.app.ui.components.RouteCard
import uz.elchi.app.ui.components.Segmented
import uz.elchi.app.ui.components.SystemBarIcons
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.map.ElchiMap
import uz.elchi.app.ui.map.GeoPoint
import uz.elchi.app.ui.map.MapFocus
import uz.elchi.app.ui.map.MapKitSupport
import uz.elchi.app.ui.map.MapMarker
import uz.elchi.app.ui.map.MyLocation
import uz.elchi.app.ui.map.MyLocationPhase
import uz.elchi.app.ui.map.decodePolyline
import uz.elchi.app.ui.map.legPath
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import java.time.Instant

/** Nothing marked yet: the whole country (south-west and north-east corners of Uzbekistan). */
private val UZBEKISTAN = listOf(GeoPoint(37.18, 55.99), GeoPoint(45.59, 73.15))

/** The one automatic move on an empty home: the user's city rather than their street. */
private const val AUTO_ZOOM = 11f

/**
 * `client-home`: full-screen map, floating menu + "Yordam", the service pill, the locate button (centres on the
 * phone and, while "Qayerdan" is empty, fills it), and the bottom sheet: referral row, Taksi/Pochta, the heading,
 * the route card with swap, the direction states, the Taksi block (window, seats, price, total) and the primary
 * button - grey until the route is ready, but its tap says what is missing.
 */
@Composable
fun ClientHomeScreen(
    vm: ParcelRequestViewModel,
    session: Session,
    ru: Boolean,
    language: String,
    onPick: (End) -> Unit,
    /** Pochta: the route step. */
    onParcelForm: () -> Unit,
    /** Taksi: the review (the whole request is on this sheet). */
    onTaxiReview: () -> Unit,
    drawer: DrawerNav,
    /** A referral code kept from a link and not used yet: a row on the sheet leads to the bonus screen (web home). */
    referralCode: String? = null,
    onReferral: () -> Unit = {},
    onReferralHide: () -> Unit = {},
) {
    // The unread dot on the menu is read when home appears (and again when the menu opens).
    LaunchedEffect(session.user.id) { drawer.onOpened() }
    ClientDrawerFrame(drawer, DrawerPlace.HOME) { openDrawer ->
        HomeContent(vm, ru, language, onMenu = openDrawer, unread = drawer.unreadText, onSupport = drawer.onHelp, onPick, onParcelForm, onTaxiReview, referralCode, onReferral, onReferralHide)
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
    language: String,
    onMenu: () -> Unit,
    unread: String?,
    onSupport: () -> Unit,
    onPick: (End) -> Unit,
    onParcelForm: () -> Unit,
    onTaxiReview: () -> Unit,
    referralCode: String?,
    onReferral: () -> Unit,
    onReferralHide: () -> Unit,
) {
    val s by vm.state.collectAsStateWithLifecycle()
    val c = Elchi.colors
    val density = LocalDensity.current
    val toast = LocalFlowToast.current
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
    // The locate tap with "Qayerdan" still empty: the fix it waits for also becomes the pickup (design `locate`).
    var fillOrigin by remember { mutableStateOf(false) }
    val locateSet = t(R.string.client_order_locateSet)
    val locateOutside = t(R.string.client_order_locateOutside)
    LaunchedEffect(myLocation.state.centre) {
        val fix = myLocation.state.fix
        if (myLocation.state.centre > 0 && fix != null) {
            userFocus = MapFocus.At(fix.point, MyLocation.ZOOM, myLocation.state.centre)
            if (fillOrigin) {
                fillOrigin = false
                vm.locateOrigin(fix.point, language) { outcome -> toast.show(if (outcome == LocateOutcome.SET) locateSet else locateOutside) }
            }
        }
    }
    LaunchedEffect(myLocation.state.phase) {
        if (myLocation.state.phase == MyLocationPhase.DENIED || myLocation.state.phase == MyLocationPhase.UNAVAILABLE) fillOrigin = false
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

    BoxWithConstraints(Modifier.fillMaxSize().background(c.field)) {
        val sheetMax = maxHeight * 0.74f
        ElchiMap(
            modifier = Modifier.fillMaxSize(),
            markers = markers,
            route = route,
            focus = focus,
            userLocation = myLocation.state.fix,
            padding = PaddingValues(top = topInset + 132.dp, bottom = with(density) { sheetHeight.toDp() } + 8.dp, start = 24.dp, end = 24.dp),
            // On the locate button's row, left of it, rather than above it.
            logoBottom = with(density) { panelHeight.toDp() } + 16.dp,
            onAvailability = { mapUsable = it },
            onCameraIdle = {
                userMovedMap = true
                myLocation.panned()
            },
            placeholderTitle = t(R.string.client_map_unavailable),
        )

        Column(Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 16.dp).padding(top = 8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                RoundIconButton(ElchiIcon.MENU, menuLabel(unread), onMenu, dot = unread != null)
                Spacer(Modifier.weight(1f))
                SupportPill(onSupport)
            }
            ServicePill(s.draft.taxi, Modifier.align(Alignment.CenterHorizontally).padding(top = 12.dp))
        }

        if (mapUsable) {
            MyLocationBanner(myLocation, Modifier.statusBarsPadding().padding(top = 124.dp, start = 16.dp, end = 16.dp))
        }

        Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth().imePadding().onSizeChanged { sheetHeight = it.height }) {
            // Right edge, just above the sheet: "my location" (crosshair) and, with a direction on the map, the
            // recentre-on-the-route button under it (route icon, so the two never look alike).
            if (mapUsable) {
                Column(
                    Modifier.align(Alignment.End).padding(start = 16.dp, end = 16.dp, bottom = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    MyLocationButton(myLocation, onTap = { if (s.draft.origin == null) fillOrigin = true }, loading = s.locating)
                    if (markers.isNotEmpty()) RoundIconButton(ElchiIcon.ROUTE, t(R.string.location_recentre), {
                        recentre++
                        myLocation.panned() // the camera leaves the user: the crosshair is no longer "on"
                    })
                }
            }
            Box(Modifier.heightIn(max = sheetMax).onSizeChanged { panelHeight = it.height }) {
                HomeSheet(s, vm, ru, onPick, onParcelForm, onTaxiReview, referralCode = referralCode, onReferral = onReferral, onReferralHide = onReferralHide)
            }
        }
    }
}

/** "Yordam" with the headset, top right (design; the theme lives in Settings). */
@Composable
private fun SupportPill(onClick: () -> Unit) {
    val c = Elchi.colors
    Row(
        Modifier
            .height(44.dp)
            .shadow(12.dp, CircleShape, ambientColor = c.shadow, spotColor = c.shadow)
            .clip(CircleShape)
            .background(c.card)
            .clickable(role = Role.Button, onClick = onClick)
            .padding(start = 12.dp, end = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        ElchiIconView(ElchiIcon.HEAD, c.text)
        Text(t(R.string.support_title), style = Elchi.type.buttonSmall, color = c.text)
    }
}

/** The floating "Posilka" / "Taksi" pill under the top bar (design `svcLabel`). */
@Composable
private fun ServicePill(taxi: Boolean, modifier: Modifier = Modifier) {
    val c = Elchi.colors
    Row(
        modifier
            .height(48.dp)
            .shadow(12.dp, CircleShape, ambientColor = c.shadow, spotColor = c.shadow)
            .clip(CircleShape)
            .background(c.card)
            .padding(start = 18.dp, end = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text(t(if (taxi) R.string.home_modeTaxi else R.string.orderForm_review_parcel), style = Elchi.type.bodyStrong.copy(fontWeight = FontWeight.Medium), color = c.text)
        Box(Modifier.size(34.dp).clip(CircleShape).background(c.field), contentAlignment = Alignment.Center) {
            ElchiIconView(if (taxi) ElchiIcon.CAR else ElchiIcon.PKG, c.text, size = 18.dp)
        }
    }
}

@Composable
private fun HomeSheet(
    s: ParcelRequestViewModel.State,
    vm: ParcelRequestViewModel,
    ru: Boolean,
    onPick: (End) -> Unit,
    onParcelForm: () -> Unit,
    onTaxiReview: () -> Unit,
    referralCode: String?,
    onReferral: () -> Unit,
    onReferralHide: () -> Unit,
) {
    val c = Elchi.colors
    val toast = LocalFlowToast.current
    val sheetShape = RoundedCornerShape(topStart = 32.dp, topEnd = 32.dp)
    val draft = s.draft
    val taxi = draft.taxi
    val ready = s.directionReady
    var showErrors by rememberSaveable { mutableStateOf(false) }
    var picking by rememberSaveable { mutableStateOf<WindowEdge?>(null) }
    val issues = if (taxi && ready) TaxiRules.homeIssues(draft, Instant.now()) else emptyList()
    if (issues.isEmpty()) showErrors = false
    val shown = if (showErrors) issues else emptyList()
    BottomPanel(Modifier.shadow(16.dp, sheetShape, ambientColor = c.shadow, spotColor = c.shadow).verticalScroll(rememberScrollState())) {
        if (referralCode != null) PromoRow(referralCode, onReferral, onReferralHide)
        if (s.passengerEnabled) {
            Segmented(listOf(ServiceMode.TAXI to t(R.string.home_modeTaxi), ServiceMode.PARCEL to t(R.string.home_modeParcel)), s.mode, vm::setMode)
        }
        Text(
            t(if (taxi) R.string.client_taxi_homeTitle else R.string.client_order_homeTitle),
            Modifier.semantics { heading() },
            style = Elchi.type.title.copy(fontSize = 22.sp, lineHeight = 27.sp),
            color = c.text,
        )
        RouteCard(
            from = draft.origin?.let { placeTitle(it, ru) },
            fromDetail = draft.origin?.areaLine(ru),
            to = draft.destination?.let { placeTitle(it, ru) },
            toDetail = draft.destination?.areaLine(ru),
            fromPlaceholder = t(R.string.direction_from),
            toPlaceholder = t(R.string.direction_to),
            onFrom = { onPick(End.ORIGIN) },
            onTo = { onPick(End.DESTINATION) },
            onSwap = vm::swapEnds,
            swapLabel = t(R.string.client_order_swap),
        )
        when (val d = s.direction) {
            Direction.Incomplete -> Unit
            Direction.Checking -> Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                CircularProgressIndicator(Modifier.size(16.dp), color = c.brand, strokeWidth = 2.dp)
                Text(t(R.string.home_checkingRoute), style = Elchi.type.label, color = c.muted)
            }
            is Direction.Ready -> {
                val p = d.preview
                Column(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(c.highlight).padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(2.dp),
                ) {
                    Text(t(R.string.home_estimatedTime, "corridor" to p.corridorName), style = Elchi.type.caption, color = c.softText)
                    Text(roadText(p.legDistanceM, p.legDurationS), style = Elchi.type.bodyStrong, color = c.text)
                }
                ParcelRules.offRouteMeters(p)?.let { Note(t(R.string.app_location_offRoute, "km" to ParcelRules.km(it)), tone = Tone.WARN) }
            }
            Direction.Mismatch -> Note(t(R.string.home_movePointHint), tone = Tone.ERR, title = t(R.string.app_location_previewMismatch))
            is Direction.Failed -> {
                Note(errorText(d.error), tone = Tone.ERR)
                ElchiButton(t(R.string.common_retry), vm::refreshDirection, Modifier.fillMaxWidth(), ButtonVariant.GHOST, ButtonSize.MEDIUM, icon = ElchiIcon.REFRESH)
            }
        }
        // Taksi: the whole request on the sheet once the route is ready (design `taxiHome`).
        if (taxi && ready && s.homeBlock != HomeBlock.PASSENGER_CLOSED) {
            FormLabel(t(R.string.client_taxi_departure)) {
                WindowTiles(
                    draft.start,
                    draft.endTime,
                    onEdge = { picking = it },
                    startError = RouteIssue.WINDOW_START in shown || RouteIssue.WINDOW_PAST in shown,
                    endError = RouteIssue.WINDOW_END in shown || RouteIssue.WINDOW_ORDER in shown,
                    onSheet = true,
                )
            }
            SeatCountPicker(TaxiRules.seatCount(draft), vm::setSeatCount, error = RouteIssue.SEATS in shown)
            FormLabel(tx("client.taxi.pricePerPerson", "Bir kishi uchun narx", "Цена за одного человека")) {
                PriceStepper(draft.priceDigits, { digits -> vm.edit { it.copy(priceDigits = digits) } }, error = RouteIssue.PRICE in shown, onSheet = true)
                Text(t(R.string.client_order_priceStepHint), style = Elchi.type.caption, color = c.muted)
            }
            TotalBar(draft)
            ErrorList(shown.map { issueText(it) })
        }
        // The chosen service closed on this corridor (or its flags could not be read): the button is off, and why.
        val closed = when (s.homeBlock) {
            HomeBlock.PARCEL_CLOSED -> t(R.string.home_parcelClosed)
            HomeBlock.PASSENGER_CLOSED -> t(R.string.home_passengerClosed)
            else -> null
        }
        val pickFirst = t(R.string.driverFeed_emptyPickFirst)
        val moveCloser = t(R.string.client_order_moveCloserFirst)
        ElchiButton(
            when {
                taxi && ready -> if (s.editingHome) t(R.string.client_order_saveAndReturn) else t(R.string.common_continue)
                taxi -> t(R.string.home_viewRoute)
                else -> t(R.string.client_order_toForm)
            },
            {
                when {
                    !ready -> when (s.direction) {
                        Direction.Mismatch -> toast.show(moveCloser)
                        Direction.Incomplete -> toast.show(pickFirst)
                        else -> Unit
                    }
                    taxi && issues.isNotEmpty() -> showErrors = true
                    taxi -> {
                        vm.setEditingHome(false)
                        onTaxiReview()
                    }
                    else -> onParcelForm()
                }
            },
            Modifier.fillMaxWidth(),
            // Closed on this corridor (server truth), or its flags still loading: off. Not ready yet: grey but tappable.
            enabled = closed == null && !(ready && s.serviceOpen == null),
            dimmed = !ready,
        )
        if (closed != null) {
            Text(closed, Modifier.fillMaxWidth(), style = Elchi.type.label.copy(fontWeight = FontWeight.Normal), color = Elchi.colors.danger, textAlign = TextAlign.Center)
        }
        Spacer(Modifier.windowInsetsBottomHeight(WindowInsets.navigationBars))
    }
    picking?.let { edge ->
        WindowSheet(
            edge = edge,
            start = draft.start,
            end = draft.endTime,
            onStart = { value -> vm.edit { it.copy(windowStart = ParcelRules.formatLocal(value)) } },
            onEnd = { value -> vm.edit { it.copy(windowEnd = ParcelRules.formatLocal(value)) } },
            onDismiss = { picking = null },
        )
    }
}

/** "Taklif kodi saqlandi: AB2CD3EF" / "Tasdiqlash uchun bosing", with an X that hides it for this session. */
@Composable
private fun PromoRow(code: String, onClick: () -> Unit, onHide: () -> Unit) {
    val c = Elchi.colors
    val close = t(R.string.common_close)
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(c.highlight).padding(start = 14.dp, end = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(
            Modifier.weight(1f).clickable(role = Role.Button, onClick = onClick).padding(vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            ElchiIconView(ElchiIcon.TAG, c.accentText, size = 18.dp)
            Column {
                Text(t(R.string.client_order_promoSaved, "code" to code), style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold), color = c.softText)
                Text(t(R.string.client_order_promoTap), style = Elchi.type.caption, color = c.accentText)
            }
        }
        Box(
            Modifier.size(44.dp).clip(CircleShape).clickable(role = Role.Button, onClick = onHide).semantics { contentDescription = close },
            contentAlignment = Alignment.Center,
        ) {
            Box(Modifier.size(30.dp).clip(CircleShape).background(c.card), contentAlignment = Alignment.Center) { ElchiIconView(ElchiIcon.X, c.text, size = 14.dp) }
        }
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
