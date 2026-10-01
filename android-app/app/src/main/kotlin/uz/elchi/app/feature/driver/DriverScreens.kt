package uz.elchi.app.feature.driver

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.elchi.app.R
import uz.elchi.app.api.DriverProfileDTO
import uz.elchi.app.feature.client.InboxViewModel
import uz.elchi.app.feature.client.Load
import uz.elchi.app.feature.client.LoadFailed
import uz.elchi.app.feature.client.LogoutConfirm
import uz.elchi.app.feature.client.ProfileRules
import uz.elchi.app.feature.client.displayPhone
import uz.elchi.app.feature.client.soum
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.session.Session
import uz.elchi.app.ui.components.Badge
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiIconView
import uz.elchi.app.ui.components.EmptyState
import uz.elchi.app.ui.components.ListCard
import uz.elchi.app.ui.components.ListRow
import uz.elchi.app.ui.components.ListRowStyle
import uz.elchi.app.ui.components.LoadingState
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.PendingReferralRow
import uz.elchi.app.ui.components.RoundIconButton
import uz.elchi.app.ui.components.SectionTitle
import uz.elchi.app.ui.components.SystemBarIcons
import uz.elchi.app.ui.components.ToggleRow
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone

/** The bottom navigation's five places (web `BottomNav`). Matches and Orders have different icons (the design). */
enum class DriverTab(val icon: ElchiIcon, val labelKey: String) {
    HOME(ElchiIcon.HOME, "app.nav.home"),
    ROUTES(ElchiIcon.ROUTE, "app.nav.routes"),
    MATCHES(ElchiIcon.RADAR, "app.nav.matches"),
    ORDERS(ElchiIcon.CLIP, "app.nav.orders"),
    PROFILE(ElchiIcon.USER, "app.nav.profile"),
}

/** The tab screens over the bottom navigation; the record is read again whenever the shell comes back into view. */
@Composable
fun DriverShell(
    driver: DriverViewModel,
    inbox: InboxViewModel,
    work: DriverWork,
    session: Session,
    tab: DriverTab,
    onTab: (DriverTab) -> Unit,
    nav: DriverNav,
) {
    val c = Elchi.colors
    SystemBarIcons(dark = !c.isDark)
    // Back from the form, the documents or the inbox: the status, balance and bell may have changed.
    LaunchedEffect(Unit) {
        driver.refresh()
        inbox.refreshUnread()
    }
    // Back on a tab (or onto another one): its list may have changed on another screen.
    LaunchedEffect(tab) {
        when (tab) {
            DriverTab.ROUTES -> work.trips.refresh()
            DriverTab.MATCHES -> work.feed.refresh()
            DriverTab.ORDERS -> {
                work.proposals.refresh(ProposalTab.OPEN)
                work.bookings.refresh()
            }
            DriverTab.HOME -> {
                work.proposals.refresh(ProposalTab.OPEN)
                work.trips.refresh()
            }
            DriverTab.PROFILE -> work.trips.refresh()
        }
    }
    Column(Modifier.fillMaxSize().background(c.page)) {
        Box(Modifier.weight(1f).fillMaxWidth()) {
            when (tab) {
                DriverTab.HOME -> DriverHomeTab(driver, inbox, work, nav, onMatches = { onTab(DriverTab.MATCHES) })
                DriverTab.ROUTES -> GatedTab(driver, t(R.string.driverRoutes_title), nav, onPlus = nav.onAddTrip, onRefresh = work.trips::refresh) {
                    TripsList(work.trips, onAdd = nav.onAddTrip, onTrip = nav.onTrip, tracker = work.tracker)
                }
                DriverTab.MATCHES -> GatedTab(driver, t(R.string.driverFeed_title), nav, onRefresh = work.feed::refresh) {
                    FeedBody(work.feed, onSaved = nav.onSavedSearches, onOffer = nav.onOffer)
                }
                DriverTab.ORDERS -> GatedTab(driver, t(R.string.app_nav_orders), nav, onRefresh = { work.proposals.refresh(ProposalTab.OPEN); work.bookings.refresh() }) {
                    DriverOrdersBody(work.bookings, work.proposals, nav.onProposals, nav.onBooking)
                }
                DriverTab.PROFILE -> DriverProfileTab(driver, work, session, nav)
            }
        }
        BottomNav(tab, onTab)
    }
}

/** The work screens' shared state, one each per driver flow (trips, feed, offers, bookings, profile numbers). */
class DriverWork(
    val trips: TripsViewModel,
    val feed: FeedViewModel,
    val proposals: ProposalsViewModel,
    val bookings: DriverBookingsViewModel,
    val stats: DriverStatsViewModel,
    val tracker: uz.elchi.app.gps.DriverTracker,
)

/** 70dp bar, rounded top, the current tab in brand blue with a heavier label. */
@Composable
private fun BottomNav(current: DriverTab, onTab: (DriverTab) -> Unit) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp)
    Box(Modifier.fillMaxWidth().shadow(16.dp, shape, ambientColor = c.shadow, spotColor = c.shadow).clip(shape).background(c.card)) {
        Row(Modifier.fillMaxWidth().navigationBarsPadding().height(70.dp).selectableGroup()) {
            DriverTab.entries.forEach { item ->
                val active = item == current
                val label = tOrNull(item.labelKey) ?: item.name
                Column(
                    Modifier.weight(1f).fillMaxSize().selectable(active, role = Role.Tab) { onTab(item) },
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(4.dp, Alignment.CenterVertically),
                ) {
                    ElchiIconView(item.icon, if (active) c.brand else c.placeholder, size = 22.dp)
                    Text(
                        label,
                        style = Elchi.type.badge.copy(fontSize = 10.sp, fontWeight = if (active) FontWeight.SemiBold else FontWeight.Medium),
                        color = if (active) c.accentText else c.placeholder,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
    }
}

/** The design's `h1` top: a large title and, on home, the bell with its unread count. */
@Composable
private fun H1Bar(title: String, bell: String? = null, bellLabel: String? = null, onBell: (() -> Unit)? = null, onPlus: (() -> Unit)? = null) {
    val c = Elchi.colors
    Row(Modifier.fillMaxWidth().height(64.dp).padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(
            title,
            Modifier.weight(1f).semantics { heading() },
            style = Elchi.type.title.copy(fontSize = 26.sp, lineHeight = 32.sp),
            color = c.text,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        if (onPlus != null) RoundIconButton(ElchiIcon.PLUS, t(R.string.driverRoutes_addRoute), onPlus)
        if (onBell != null) {
            Box(Modifier.size(44.dp)) {
                Box(
                    Modifier
                        .fillMaxSize()
                        .shadow(12.dp, CircleShape, ambientColor = c.shadow, spotColor = c.shadow)
                        .clip(CircleShape)
                        .background(c.card)
                        .clickable(role = Role.Button, onClick = onBell)
                        .semantics { contentDescription = bellLabel ?: title },
                    contentAlignment = Alignment.Center,
                ) { ElchiIconView(ElchiIcon.BELL, c.text) }
                if (bell != null) {
                    Text(
                        bell,
                        Modifier
                            .align(Alignment.TopEnd)
                            .heightIn(min = 20.dp)
                            .clip(CircleShape)
                            .background(c.tone(Tone.ERR).fg)
                            .padding(horizontal = 6.dp, vertical = 2.dp),
                        style = Elchi.type.badge,
                        color = Color.White,
                        maxLines = 1,
                    )
                }
            }
        }
    }
}

/** A tab's frame: the h1 bar and a scrolling, pull-to-refresh body. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TabFrame(
    title: String,
    refreshing: Boolean,
    onRefresh: () -> Unit,
    bell: String? = null,
    bellLabel: String? = null,
    onBell: (() -> Unit)? = null,
    onPlus: (() -> Unit)? = null,
    body: @Composable ColumnScope.() -> Unit,
) {
    Column(Modifier.fillMaxSize()) {
        Column(Modifier.statusBarsPadding()) { H1Bar(title, bell, bellLabel, onBell, onPlus) }
        PullToRefreshBox(isRefreshing = refreshing, onRefresh = onRefresh, modifier = Modifier.weight(1f).fillMaxWidth()) {
            Column(
                Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp).padding(top = 6.dp, bottom = 18.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
                content = body,
            )
        }
    }
}

/** Loading / failed first read of the driver record, else [content] with it. */
@Composable
private fun ColumnScope.WithProfile(driver: DriverViewModel, profile: Load<DriverProfileDTO>, content: @Composable ColumnScope.(DriverProfileDTO) -> Unit) {
    when (profile) {
        Load.Loading -> LoadingState()
        is Load.Failed -> LoadFailed(t(R.string.driverProfileForm_title), profile.error, driver::refresh)
        is Load.Ready -> content(profile.value)
    }
}

@Composable
internal fun statusText(status: DriverStatus): String = tOrNull(DriverRules.statusKey(status)) ?: status.wire

// -- driver-home ----------------------------------------------------------------------------------------------

/**
 * `driver-home`: the referral code kept from a link (tap = confirm it), balance (Q22: before approval too), the
 * translated verification status, the availability switch and the next step. The GPS bar is Stage 09.
 */
@Composable
private fun DriverHomeTab(driver: DriverViewModel, inbox: InboxViewModel, work: DriverWork, nav: DriverNav, onMatches: () -> Unit) {
    val s by driver.state.collectAsStateWithLifecycle()
    val unread by inbox.state.collectAsStateWithLifecycle()
    val pendingReferral by driver.pendingReferral.collectAsStateWithLifecycle()
    val c = Elchi.colors
    val status = s.status
    val bell = when {
        unread.unread <= 0 -> null
        unread.unreadMore -> "${unread.unread}+"
        else -> unread.unread.toString()
    }
    TabFrame(
        // Until the record is read the tab's own name, not a guess at the status.
        title = status?.let { tOrNull(DriverRules.homeTitleKey(it)) } ?: t(R.string.app_nav_home),
        refreshing = s.refreshing && s.profile is Load.Ready,
        onRefresh = {
            driver.refresh()
            inbox.refreshUnread()
        },
        bell = bell,
        bellLabel = if (bell != null) t(R.string.driverHome_notificationsUnread, "count" to bell) else t(R.string.notifications_title),
        onBell = nav.onNotifications,
    ) {
        pendingReferral?.let { code ->
            PendingReferralRow(t(R.string.driverHome_pendingReferral, "code" to code), driver::confirmReferral, loading = s.referralBusy)
        }
        // Q148: a running trip's GPS state, right on the home screen.
        val trips by work.trips.state.collectAsStateWithLifecycle()
        TripRules.trackable(trips.list)?.let { running -> uz.elchi.app.gps.DriverTrackingBar(work.tracker, running.id, inset = 0.dp) }
        // The balance row (tap = "Komissiya balansi"): "—" while it loads or when it cannot be read, never a made-up zero.
        ListCard {
            Row(
                Modifier.fillMaxWidth().clickable(role = Role.Button, onClick = nav.onWallet).heightIn(min = 56.dp).padding(horizontal = 14.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Box(Modifier.size(38.dp).clip(CircleShape).background(if (c.isDark) c.field else Color(0xFFEEF4FA)), contentAlignment = Alignment.Center) {
                    ElchiIconView(ElchiIcon.WALLET, c.accentText, size = 18.dp)
                }
                Text(t(R.string.driverHome_commissionBalance), Modifier.weight(1f), style = Elchi.type.secondary.copy(fontWeight = FontWeight.SemiBold), color = c.text)
                val wallet = s.wallet
                Text(if (wallet is Load.Ready) soum(wallet.value) else "—", style = Elchi.type.secondary.copy(fontWeight = FontWeight.SemiBold), color = c.text)
                ElchiIconView(ElchiIcon.CHEV_R, c.placeholder, size = 18.dp)
            }
        }
        WithProfile(driver, s.profile) { profile ->
            val st = DriverStatus.from(profile.verificationStatus)
            val tone = c.tone(DriverRules.statusTone(st))
            ElchiCard(padding = PaddingValues(horizontal = 16.dp, vertical = 12.dp)) {
                Text(t(R.string.driver_home_verificationLabel), style = Elchi.type.caption, color = c.muted)
                Row(Modifier.padding(top = 2.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Box(Modifier.size(8.dp).clip(CircleShape).background(tone.fg))
                    Text(statusText(st), style = Elchi.type.bodyStrong, color = tone.fg)
                }
                Text(tOrNull(DriverRules.homeHintKey(st)).orEmpty(), Modifier.padding(top = 4.dp), style = Elchi.type.caption, color = c.muted)
            }
            ToggleRow(
                title = t(R.string.driverHome_availabilityTitle),
                description = tOrNull(DriverRules.availabilitySubtitleKey(st, profile.isAvailable)).orEmpty(),
                checked = profile.isAvailable,
                onChange = driver::setAvailability,
                enabled = DriverRules.availabilityEnabled(st, profile.isAvailable) && !s.availabilityBusy,
            )
            if (st == DriverStatus.APPROVED) {
                ElchiButton(t(R.string.driverHome_viewMatchingOrders), onMatches, Modifier.fillMaxWidth(), ButtonVariant.SOFT, icon = ElchiIcon.RADAR)
                ProposalsEntry(work.proposals, nav.onProposals)
            } else {
                ElchiButton(t(R.string.driverHome_completeProfile), nav.onProfileForm, Modifier.fillMaxWidth())
                ElchiButton(t(R.string.driverHome_uploadDocuments), nav.onDocuments, Modifier.fillMaxWidth(), ButtonVariant.SOFT)
                if (DriverRules.showsSupport(st)) {
                    ElchiButton(t(R.string.app_driverGate_support), nav.onHelp, Modifier.fillMaxWidth(), ButtonVariant.NEUTRAL, icon = ElchiIcon.HEAD)
                }
            }
        }
    }
}

// -- routes / matches / orders ----------------------------------------------------------------------------------

/** Before approval: the verification gate (Q96). After: [content], the tab's own work. */
@Composable
private fun GatedTab(
    driver: DriverViewModel,
    title: String,
    nav: DriverNav,
    onPlus: (() -> Unit)? = null,
    onRefresh: () -> Unit,
    content: @Composable ColumnScope.() -> Unit,
) {
    val s by driver.state.collectAsStateWithLifecycle()
    val approved = s.status?.let { DriverRules.gate(it) == GateVariant.NONE } == true
    TabFrame(
        title = title,
        refreshing = s.refreshing && s.profile is Load.Ready,
        onRefresh = {
            driver.refresh()
            if (approved) onRefresh()
        },
        onPlus = onPlus.takeIf { approved },
    ) {
        WithProfile(driver, s.profile) { profile ->
            val status = DriverStatus.from(profile.verificationStatus)
            if (DriverRules.gate(status) == GateVariant.NONE) {
                content()
            } else {
                VerificationGate(status, onDocuments = nav.onDocuments, onProfile = nav.onProfileForm, onSupport = nav.onHelp)
            }
        }
    }
}

/**
 * Why this driver cannot take work yet and what to do (Q96, web `DriverVerificationGate`). rejected / blocked are
 * decided: no upload changes them, so the only way on is support.
 */
@Composable
fun VerificationGate(status: DriverStatus, onDocuments: () -> Unit, onProfile: () -> Unit, onSupport: () -> Unit) {
    val decided = DriverRules.gate(status) == GateVariant.DECIDED
    val statusLine = t(R.string.app_driverGate_status, "status" to statusText(status))
    val body = t(if (decided) R.string.app_driverGate_decided else R.string.app_driverGate_pending)
    Note("$statusLine. $body", tone = if (decided) Tone.ERR else Tone.WARN, title = t(R.string.app_driverGate_title))
    if (decided) {
        ElchiButton(t(R.string.app_driverGate_support), onSupport, Modifier.fillMaxWidth(), ButtonVariant.SOFT, icon = ElchiIcon.HEAD)
    } else {
        ElchiButton(t(R.string.app_driverGate_documents), onDocuments, Modifier.fillMaxWidth())
        ElchiButton(t(R.string.app_driverGate_profile), onProfile, Modifier.fillMaxWidth(), ButtonVariant.SOFT)
    }
}

// -- profile tab ------------------------------------------------------------------------------------------------

/** The full driver profile (Stage 09, [DriverProfileBody]) in the tab frame. */
@Composable
private fun DriverProfileTab(driver: DriverViewModel, work: DriverWork, session: Session, nav: DriverNav) {
    val s by driver.state.collectAsStateWithLifecycle()
    TabFrame(
        title = t(R.string.app_nav_profile),
        refreshing = s.refreshing && s.profile is Load.Ready,
        onRefresh = {
            driver.refresh()
            work.stats.refresh()
            work.trips.refresh()
        },
    ) {
        DriverProfileBody(driver, work.stats, work.trips, session, nav)
    }
}
