package uz.elchi.app.feature.driver

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
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
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.session.Session
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiIconView
import uz.elchi.app.ui.components.ListCard
import uz.elchi.app.ui.components.LoadingState
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.SystemBarIcons
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone

/** The bottom navigation's four places (Royxat / Safar v3 §0: "Yo'nalishlar" is now the second segment of Moslar). */
enum class DriverTab(val icon: ElchiIcon, val labelKey: String) {
    HOME(ElchiIcon.HOME, "app.nav.home"),
    MATCHES(ElchiIcon.RADAR, "app.nav.matches"),
    ORDERS(ElchiIcon.CLIP, "app.nav.orders"),
    PROFILE(ElchiIcon.USER, "app.nav.profile"),
}

/** Moslar's segments (Safar v3 0.1): the direction feed, and "Yo'nalishlarim" (the directions and their trips). */
enum class MatchesSegment { FEED, ROUTES }

/** Room under a tab's scrolling content for the floating tab bar (Safar v3 0.5: 110px). */
internal val FloatingNavInset = 110.dp

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
    segment: MatchesSegment = MatchesSegment.FEED,
    onSegment: (MatchesSegment) -> Unit = {},
) {
    val c = Elchi.colors
    SystemBarIcons(dark = !c.isDark)
    // Back from the form, the documents or the inbox: the status, balance and bell may have changed.
    LaunchedEffect(Unit) {
        driver.refresh()
        inbox.refreshUnread()
    }
    // Back on a tab (or onto another one): its list may have changed on another screen.
    LaunchedEffect(tab, segment) {
        when (tab) {
            DriverTab.MATCHES -> {
                work.directions.refresh()
                if (segment == MatchesSegment.ROUTES) {
                    work.trips.refresh()
                } else {
                    work.feed.refresh()
                    // Design 07 §5.7 / §0.2: "already offered" on the cards and the pill's counter count.
                    work.proposals.refresh(ProposalTab.OPEN)
                    work.proposals.refresh(ProposalTab.ACCEPTED)
                }
            }
            DriverTab.ORDERS -> {
                work.proposals.refresh(ProposalTab.OPEN)
                work.bookings.refresh()
            }
            DriverTab.HOME -> {
                // The home listings come from the directions (DD5 per active one) and know the offers already sent.
                work.directions.refresh()
                work.feed.refresh()
                work.proposals.refresh(ProposalTab.OPEN)
                work.proposals.refresh(ProposalTab.ACCEPTED)
                work.trips.refresh()
                work.bookings.refresh()
            }
            DriverTab.PROFILE -> work.trips.refresh()
        }
    }
    Box(Modifier.fillMaxSize().background(c.page)) {
        when (tab) {
            DriverTab.HOME -> DriverHomeTab(
                driver, inbox, work, nav,
                onMatches = { onSegment(MatchesSegment.FEED); onTab(DriverTab.MATCHES) },
                onProfileTab = { onTab(DriverTab.PROFILE) },
                bottomInset = FloatingNavInset,
            )
            // Safar v3 0.1-0.4: one title for both segments; "+" on Yo'nalishlarim, the "Takliflarim" pill on the feed.
            DriverTab.MATCHES -> GatedTab(
                driver, t(R.string.driverFeed_title), nav,
                onPlus = nav.onAddDirection.takeIf { segment == MatchesSegment.ROUTES },
                onRefresh = {
                    work.directions.refresh()
                    if (segment == MatchesSegment.ROUTES) work.trips.refresh() else work.feed.refresh()
                },
                action = if (segment == MatchesSegment.FEED) ({ ProposalsPill(work.proposals, nav.onProposals) }) else null,
            ) {
                // Q148: the running trip's GPS state once, above both segments.
                val ts by work.trips.state.collectAsStateWithLifecycle()
                TripRules.trackable(ts.list)?.let { running -> uz.elchi.app.gps.DriverTrackingBar(work.tracker, running.id, inset = 0.dp) }
                val ds by work.directions.state.collectAsStateWithLifecycle()
                val feedCount = (ds.feed as? Load.Ready)?.value?.items?.let(DirectionRules::mainCount) ?: 0
                SegmentBar(
                    listOf(
                        Triple(MatchesSegment.FEED, t(R.string.app_nav_orders), feedCount),
                        Triple(MatchesSegment.ROUTES, t(R.string.driverRoutes_title), DirectionRules.activeCount(ds.list)),
                    ),
                    segment, onSegment,
                )
                if (segment == MatchesSegment.ROUTES) {
                    // ADR-0027 (Q150): the driver's directions first; the trips the system made from them below (Q148).
                    DirectionsBody(work.directions, work.trips, onAdd = nav.onAddDirection, onFeed = nav.onDirectionFeed, onTrip = nav.onTrip)
                } else {
                    MatchesBody(work, nav)
                }
            }
            // Not gated (design 06 §0.3, D16): a driver blocked while holding bookings still sees and serves them.
            DriverTab.ORDERS -> OrdersTab(driver, work, nav)
            DriverTab.PROFILE -> DriverProfileTab(driver, work, session, nav)
        }
        val record by driver.state.collectAsStateWithLifecycle()
        // Before approval the work tab shows the gate: a small lock on its icon (design 06 §0.2).
        val locked = record.status?.let { DriverRules.gate(it) != GateVariant.NONE } == true
        BottomNav(tab, onTab, Modifier.align(Alignment.BottomCenter), lockedTabs = if (locked) setOf(DriverTab.MATCHES) else emptySet())
    }
}

/** Moslar's segmented control with a count on each side (Safar v3 0.2; 0 hides the count). */
@Composable
private fun SegmentBar(items: List<Triple<MatchesSegment, String, Int>>, selected: MatchesSegment, onSelect: (MatchesSegment) -> Unit) {
    val c = Elchi.colors
    Row(
        Modifier.fillMaxWidth().clip(CircleShape).background(if (c.isDark) c.field else Color(0xFFE4E9EF)).padding(4.dp).selectableGroup(),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        items.forEach { (value, label, count) ->
            val on = value == selected
            Row(
                Modifier.weight(1f).height(40.dp)
                    .then(if (on) Modifier.shadow(3.dp, CircleShape, ambientColor = c.shadow, spotColor = c.shadow) else Modifier)
                    .clip(CircleShape).background(if (on) c.card else Color.Transparent)
                    .selectable(on, role = Role.Tab) { if (!on) onSelect(value) },
                horizontalArrangement = Arrangement.spacedBy(6.dp, Alignment.CenterHorizontally),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(label, style = Elchi.type.buttonSmall.copy(fontWeight = if (on) FontWeight.SemiBold else FontWeight.Medium), color = if (on) c.text else c.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
                if (count > 0) {
                    Text(
                        count.toString(),
                        Modifier.heightIn(min = 20.dp).clip(CircleShape).background(if (on) driverNavy() else c.outline).padding(horizontal = 6.dp, vertical = 2.dp),
                        style = Elchi.type.badge.copy(fontWeight = FontWeight.Bold),
                        color = if (on) Color.White else c.text,
                    )
                }
            }
        }
    }
}

/** "Buyurtmalar" for every status: the bookings; the "Takliflarim" entry only once approved (no offers before). */
@Composable
private fun OrdersTab(driver: DriverViewModel, work: DriverWork, nav: DriverNav) {
    val s by driver.state.collectAsStateWithLifecycle()
    val approved = s.status == DriverStatus.APPROVED
    TabFrame(
        // Design 07 §9.1: "Buyurtmalar tarixi".
        title = t(R.string.driverOrders_title),
        refreshing = s.refreshing && s.profile is Load.Ready,
        onRefresh = {
            driver.refresh()
            if (approved) work.proposals.refresh(ProposalTab.OPEN)
            work.bookings.refresh()
        },
    ) {
        DriverOrdersBody(work.bookings, work.proposals, nav.onProposals, nav.onBooking, showProposals = approved)
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
    /** ADR-0027: the driver's directions and the chosen one's requests. */
    val directions: DirectionsViewModel,
    /** Royxat / Safar v3 §1: the home's "Mijozlar e'lonlari" (all active directions merged) and the credit. */
    val home: HomeViewModel,
)

/**
 * Safar v3 0.5: a floating navy pill of 56dp icon circles - white, the current one brand blue. The labels are kept as
 * each tab's spoken name (the design shows icons only).
 */
@Composable
private fun BottomNav(current: DriverTab, onTab: (DriverTab) -> Unit, modifier: Modifier = Modifier, lockedTabs: Set<DriverTab> = emptySet()) {
    val c = Elchi.colors
    Row(
        modifier
            .navigationBarsPadding()
            .padding(bottom = 18.dp)
            .shadow(18.dp, CircleShape, ambientColor = c.shadow, spotColor = c.shadow)
            .clip(CircleShape)
            .background(driverNavy())
            .padding(8.dp)
            .selectableGroup(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        DriverTab.entries.forEach { item ->
            val active = item == current
            val label = tOrNull(item.labelKey) ?: item.name
            Box(
                Modifier
                    .size(56.dp)
                    .clip(CircleShape)
                    .background(if (active) c.brand else if (c.isDark) c.card else Color.White)
                    .selectable(active, role = Role.Tab) { onTab(item) }
                    .semantics { contentDescription = label },
                contentAlignment = Alignment.Center,
            ) {
                ElchiIconView(item.icon, if (active) c.onBrand else if (c.isDark) c.text else c.navy, size = 22.dp)
                if (item in lockedTabs) {
                    Box(
                        Modifier.align(Alignment.Center).offset(x = 10.dp, y = 9.dp).size(16.dp).clip(CircleShape).background(if (active) c.brand else if (c.isDark) c.card else Color.White),
                        contentAlignment = Alignment.Center,
                    ) { ElchiIconView(ElchiIcon.LOCK, c.placeholder, size = 11.dp) }
                }
            }
        }
    }
}

/** The design's `h1` top: a large title and, on home, the bell with its unread count. */
@Composable
private fun H1Bar(title: String, bell: String? = null, bellLabel: String? = null, onBell: (() -> Unit)? = null, onPlus: (() -> Unit)? = null, action: (@Composable () -> Unit)? = null) {
    val c = Elchi.colors
    Row(Modifier.fillMaxWidth().height(64.dp).padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(
            title,
            Modifier.weight(1f).semantics { heading() },
            style = Elchi.type.title.copy(fontSize = 24.sp, lineHeight = 30.sp, fontWeight = FontWeight.SemiBold),
            color = c.text,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        if (onPlus != null) {
            // Safar v3: the brand "+" (aria "Yo'nalish qo'shish").
            val addLabel = t(R.string.driverRoutes_addRoute)
            Box(
                Modifier.size(44.dp).clip(CircleShape).background(c.brand).clickable(role = Role.Button, onClick = onPlus).semantics { contentDescription = addLabel },
                contentAlignment = Alignment.Center,
            ) { ElchiIconView(ElchiIcon.PLUS, c.onBrand, size = 20.dp) }
        }
        action?.invoke()
        if (onBell != null) {
            Box(Modifier.size(48.dp)) {
                Box(
                    Modifier
                        .fillMaxSize()
                        .clip(CircleShape)
                        .background(if (c.isDark) c.field else Color(0xFFE9EDF2))
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
    /** Anything else at the bar's right (design 07: the Moslar "Takliflarim" pill). */
    action: (@Composable () -> Unit)? = null,
    body: @Composable ColumnScope.() -> Unit,
) {
    Column(Modifier.fillMaxSize()) {
        Column(Modifier.statusBarsPadding()) { H1Bar(title, bell, bellLabel, onBell, onPlus, action) }
        PullToRefreshBox(isRefreshing = refreshing, onRefresh = onRefresh, modifier = Modifier.weight(1f).fillMaxWidth()) {
            Column(
                Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp).padding(top = 6.dp).navigationBarsPadding().padding(bottom = FloatingNavInset),
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

/**
 * Home's 3-step checklist until approval (design 06 §1.7): a numbered circle (green tick when done, red cross when
 * rejected), the title, the sub-line and a chevron. Step 3 opens the Matches tab, where the gate explains the wait.
 */
@Composable
internal fun ChecklistCard(list: Checklist, onProfile: () -> Unit, onDocuments: () -> Unit, onReview: () -> Unit) {
    ListCard {
        ChecklistRow(1, t(R.string.driver_checklist_profileTitle), list.profile, first = true, onClick = onProfile)
        ChecklistRow(2, t(R.string.driverDocs_title), list.documents, onClick = onDocuments)
        ChecklistRow(3, t(R.string.driver_checklist_reviewTitle), list.review, onClick = onReview)
    }
}

@Composable
private fun ChecklistRow(number: Int, title: String, step: ChecklistStep, first: Boolean = false, onClick: () -> Unit) {
    val c = Elchi.colors
    val ok = c.tone(Tone.OK)
    val err = c.tone(Tone.ERR)
    val sub = step.subText ?: step.subKey?.let { tOrNull(it, *step.params.toList().toTypedArray()) }.orEmpty()
    val (bg, fg) = when (step.mark) {
        StepMark.DONE -> ok.bg to ok.fg
        StepMark.FAILED -> err.bg to err.fg
        StepMark.OPEN -> c.field to c.muted
    }
    Column {
        if (!first) Box(Modifier.fillMaxWidth().height(1.dp).background(c.field))
        Row(
            Modifier.fillMaxWidth().clickable(role = Role.Button, onClick = onClick).heightIn(min = 60.dp).padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Box(Modifier.size(26.dp).clip(CircleShape).background(bg), contentAlignment = Alignment.Center) {
                when (step.mark) {
                    StepMark.DONE -> ElchiIconView(ElchiIcon.CHECK, fg, size = 14.dp)
                    StepMark.FAILED -> ElchiIconView(ElchiIcon.X, fg, size = 14.dp)
                    StepMark.OPEN -> Text(number.toString(), style = Elchi.type.badge.copy(fontSize = 12.sp, fontWeight = FontWeight.Bold), color = fg)
                }
            }
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
                Text(title, style = Elchi.type.secondary.copy(fontWeight = FontWeight.SemiBold), color = c.text)
                if (sub.isNotEmpty()) Text(sub, style = Elchi.type.caption, color = if (step.alert) err.fg else c.muted)
            }
            ElchiIconView(ElchiIcon.CHEV_R, c.placeholder, size = 16.dp)
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
    action: (@Composable () -> Unit)? = null,
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
        action = action.takeIf { approved },
    ) {
        WithProfile(driver, s.profile) { profile ->
            val status = DriverStatus.from(profile.verificationStatus)
            if (DriverRules.gate(status) == GateVariant.NONE) {
                content()
            } else {
                VerificationGate(
                    status, onDocuments = nav.onDocuments, onProfile = nav.onProfileForm, onSupport = nav.onHelp,
                    statusWord = s.verify?.let { tOrNull(it.labelKey) },
                    profileLabel = tOrNull(DriverRules.profileButtonKey(s.profileDone)),
                )
            }
        }
    }
}

/**
 * Why this driver cannot take work yet and what to do (Q96, web `DriverVerificationGate`). rejected / blocked are
 * decided: no upload changes them, so the only way on is support.
 */
@Composable
fun VerificationGate(
    status: DriverStatus,
    onDocuments: () -> Unit,
    onProfile: () -> Unit,
    onSupport: () -> Unit,
    /** The derived word (design 06 §4.1, "To'ldirilmagan" / "Ko'rib chiqilmoqda"); null = the server's. */
    statusWord: String? = null,
    /** "Profilni ko'rish" once the car is stored (§4.2); null = "Profilni to'ldirish". */
    profileLabel: String? = null,
) {
    val decided = DriverRules.gate(status) == GateVariant.DECIDED
    val statusLine = t(R.string.app_driverGate_status, "status" to (statusWord ?: statusText(status)))
    val body = t(if (decided) R.string.app_driverGate_decided else R.string.app_driverGate_pending)
    Note("$statusLine. $body", tone = if (decided) Tone.ERR else Tone.WARN, title = t(R.string.app_driverGate_title))
    if (decided) {
        ElchiButton(t(R.string.app_driverGate_support), onSupport, Modifier.fillMaxWidth(), ButtonVariant.SOFT, icon = ElchiIcon.HEAD)
    } else {
        ElchiButton(t(R.string.app_driverGate_documents), onDocuments, Modifier.fillMaxWidth())
        ElchiButton(profileLabel ?: t(R.string.app_driverGate_profile), onProfile, Modifier.fillMaxWidth(), ButtonVariant.SOFT)
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
