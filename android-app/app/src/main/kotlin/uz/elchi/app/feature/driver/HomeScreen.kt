package uz.elchi.app.feature.driver

import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.elchi.app.R
import uz.elchi.app.api.generated.ListingPublicDTO
import uz.elchi.app.api.generated.ParcelType
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.feature.client.InboxViewModel
import uz.elchi.app.feature.client.Load
import uz.elchi.app.feature.client.LoadFailed
import uz.elchi.app.feature.client.ParcelRules
import uz.elchi.app.feature.client.ProfileRules
import uz.elchi.app.feature.client.categoryName
import uz.elchi.app.feature.client.soum
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiIconView
import uz.elchi.app.ui.components.LoadingState
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.PendingReferralRow
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone

/** The design's navy (#0E2350); on dark pages a lighter navy so it still separates from the page. */
@Composable
internal fun driverNavy(): Color = if (Elchi.colors.isDark) Color(0xFF1B3563) else Elchi.colors.navy

/** The flat grey of the v3 round buttons and chips (#E9EDF2). */
@Composable
private fun flatGrey(): Color = if (Elchi.colors.isDark) Elchi.colors.field else Color(0xFFE9EDF2)

/**
 * `driver-home` (Royxat v3 §1 + Safar v3 §1): no h1 bar - avatar, navy balance pill and bell; "Salom, {name}!" with
 * the verification seal; then, once approved, the search, chips and the "Mijozlar e'lonlari" list built from the
 * driver's own directions, the three tiles and the credit card. Before approval: the warning (or the decided note
 * with support, Q96), the checklist and the next step - there are no listings to show yet (1.13).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun DriverHomeTab(
    driver: DriverViewModel,
    inbox: InboxViewModel,
    work: DriverWork,
    nav: DriverNav,
    onMatches: () -> Unit,
    onProfileTab: () -> Unit,
    bottomInset: Dp,
) {
    val s by driver.state.collectAsStateWithLifecycle()
    val unread by inbox.state.collectAsStateWithLifecycle()
    val pendingReferral by driver.pendingReferral.collectAsStateWithLifecycle()
    val ds by work.directions.state.collectAsStateWithLifecycle()
    val fs by work.feed.state.collectAsStateWithLifecycle()
    val hs by work.home.state.collectAsStateWithLifecycle()
    val approved = s.status == DriverStatus.APPROVED
    val directions = ds.list
    // Back on home: the credit and the listings are read again (an offer or a new request may have changed them).
    LaunchedEffect(Unit) {
        work.home.loadCredit()
        if (approved && ds.directions is Load.Ready) work.home.load(directions, fs.passengerEnabled, force = true)
    }
    LaunchedEffect(approved, directions, fs.passengerEnabled) {
        if (approved && ds.directions is Load.Ready) work.home.load(directions, fs.passengerEnabled)
    }
    PullToRefreshBox(
        isRefreshing = s.refreshing && s.profile is Load.Ready,
        onRefresh = {
            driver.refresh()
            inbox.refreshUnread()
            work.home.loadCredit()
            if (approved) {
                work.directions.refresh()
                work.home.load(directions, fs.passengerEnabled, force = true)
            }
        },
        modifier = Modifier.fillMaxSize(),
    ) {
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).statusBarsPadding().padding(horizontal = 16.dp).padding(top = 10.dp, bottom = bottomInset),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            val profile = (s.profile as? Load.Ready)?.value
            HomeHeader(
                name = profile?.fullName,
                balance = (s.wallet as? Load.Ready)?.value?.let { soum(it) } ?: "—",
                unread = unread.unread,
                unreadMore = unread.unreadMore,
                onProfile = onProfileTab,
                onWallet = nav.onWallet,
                onBell = nav.onNotifications,
            )
            pendingReferral?.let { code ->
                PendingReferralRow(
                    t(R.string.link_referralSaved, "code" to code), driver::confirmReferral, loading = s.referralBusy,
                    sub = t(R.string.client_order_promoTap), onDismiss = driver::forgetReferral, dismissLabel = t(R.string.common_close),
                )
            }
            when (val p = s.profile) {
                Load.Loading -> LoadingState(count = 2)
                is Load.Failed -> LoadFailed(t(R.string.driverProfileForm_title), p.error, driver::refresh)
                is Load.Ready -> {
                    val st = DriverStatus.from(p.value.verificationStatus)
                    val verify = s.verify ?: DriverRules.verifyState(st, s.profileDone, s.documents)
                    Greeting(HomeListingRules.firstName(p.value.fullName), verify)
                    if (st == DriverStatus.APPROVED) {
                        // Q148: a running trip's GPS state, right on the home screen.
                        val trips by work.trips.state.collectAsStateWithLifecycle()
                        TripRules.trackable(trips.list)?.let { running -> uz.elchi.app.gps.DriverTrackingBar(work.tracker, running.id, inset = 0.dp) }
                        HomeListings(work.home, hs, directions.isEmpty() && ds.directions is Load.Ready, fs.passengerEnabled, work, nav, onMatches)
                        DriverHomeWork(work, nav, onMatches)
                    } else {
                        // Royxat v3 1.6: the status card is gone. Not decided: one amber line; decided: the reason
                        // and the way on (Q96) - the design's "faol bo'la olmaysiz" alone would hide the decision.
                        val decided = DriverRules.gate(st) == GateVariant.DECIDED
                        Note(t(if (decided) R.string.app_driverGate_decided else R.string.driverHome_availabilityLocked), tone = if (decided) Tone.ERR else Tone.WARN)
                        ChecklistCard(
                            DriverRules.checklist(p.value, s.vehicles, s.documents, verify),
                            onProfile = nav.onProfileForm,
                            onDocuments = nav.onDocuments,
                            onReview = onMatches,
                        )
                        ElchiButton(tOrNull(DriverRules.profileButtonKey(s.profileDone)).orEmpty(), nav.onProfileForm, Modifier.fillMaxWidth())
                        ElchiButton(t(R.string.driverHome_uploadDocuments), nav.onDocuments, Modifier.fillMaxWidth(), ButtonVariant.SOFT)
                        if (DriverRules.showsSupport(st)) {
                            ElchiButton(t(R.string.app_driverGate_support), nav.onHelp, Modifier.fillMaxWidth(), ButtonVariant.NEUTRAL, icon = ElchiIcon.HEAD)
                        }
                    }
                }
            }
            // Royxat v3 1.16: every status; never shown as money (Q16/Q103).
            CreditCard(hs.credit, nav.onBonus)
        }
    }
}

// -- header and greeting ----------------------------------------------------------------------------------------

@Composable
private fun HomeHeader(name: String?, balance: String, unread: Int, unreadMore: Boolean, onProfile: () -> Unit, onWallet: () -> Unit, onBell: () -> Unit) {
    val c = Elchi.colors
    val profileLabel = t(R.string.app_nav_profile)
    val walletLabel = t(R.string.driverHome_commissionBalance)
    val count = when {
        unread <= 0 -> null
        unreadMore -> "$unread+"
        else -> unread.toString()
    }
    val bellLabel = if (count != null) t(R.string.driverHome_notificationsUnread, "count" to count) else t(R.string.notifications_title)
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Box(
            Modifier.size(52.dp).clip(CircleShape).background(c.soft)
                .clickable(role = Role.Button, onClick = onProfile).semantics { contentDescription = profileLabel },
            contentAlignment = Alignment.Center,
        ) {
            val initials = ProfileRules.initials(name)
            if (initials != null) Text(initials, style = Elchi.type.bodyStrong.copy(fontSize = 17.sp), color = c.softText)
            else ElchiIconView(ElchiIcon.USER, c.softText, size = 22.dp)
        }
        Spacer(Modifier.weight(1f))
        // The navy balance pill: "—" while unread or unreadable, never a made-up zero (Q22: before approval too).
        Row(
            Modifier.height(52.dp).shadow(14.dp, CircleShape, ambientColor = c.shadow, spotColor = c.shadow).clip(CircleShape).background(driverNavy())
                .clickable(role = Role.Button, onClick = onWallet)
                .clearAndSetSemantics { contentDescription = "$walletLabel: $balance" }
                .padding(start = 6.dp, end = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Box(Modifier.size(40.dp).clip(CircleShape).background(c.brand), contentAlignment = Alignment.Center) { ElchiIconView(ElchiIcon.WALLET, c.onBrand, size = 18.dp) }
            Column {
                Text(t(R.string.driver_v3reg_balanceLabel), style = Elchi.type.caption.copy(fontSize = 10.5.sp, lineHeight = 12.sp), color = Color(0xFF9FB6D6))
                Text(balance, style = Elchi.type.secondary.copy(fontWeight = FontWeight.SemiBold, lineHeight = 17.sp), color = Color.White, maxLines = 1)
            }
        }
        Box(
            Modifier.size(52.dp).clip(CircleShape).background(flatGrey()).clickable(role = Role.Button, onClick = onBell).semantics { contentDescription = bellLabel },
            contentAlignment = Alignment.Center,
        ) {
            ElchiIconView(ElchiIcon.BELL, c.text, size = 22.dp)
            // Royxat v3 1.1: a dot while something is unread (the count is in the spoken label).
            if (count != null) Box(Modifier.align(Alignment.TopEnd).padding(top = 13.dp, end = 14.dp).size(10.dp).clip(CircleShape).background(flatGrey()).padding(1.5.dp).clip(CircleShape).background(Color(0xFFE0413A)))
        }
    }
}

@Composable
private fun Greeting(firstName: String?, verify: VerifyState) {
    val c = Elchi.colors
    val context = LocalContext.current
    val seal = HomeListingRules.seal(verify)
    val tone = c.tone(seal.tone)
    val label = tOrNull(HomeListingRules.sealLabelKey(verify)).orEmpty()
    val toast = tOrNull(HomeListingRules.sealToastKey(verify)).orEmpty()
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            firstName?.let { t(R.string.driver_v3reg_greeting, "name" to it) } ?: t(R.string.driver_v3reg_greetingNoName),
            Modifier.weight(1f, fill = false).semantics { heading() },
            style = Elchi.type.title.copy(fontSize = 27.sp, lineHeight = 32.sp, fontWeight = FontWeight.SemiBold),
            color = c.text,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
        Box(
            Modifier.size(26.dp).clip(CircleShape).background(tone.bg)
                .clickable(role = Role.Button) { Toast.makeText(context, toast, Toast.LENGTH_SHORT).show() }
                .semantics { contentDescription = label },
            contentAlignment = Alignment.Center,
        ) { ElchiIconView(if (seal == SealTone.OK) ElchiIcon.CHECK else ElchiIcon.ALERT, tone.fg, size = 15.dp) }
    }
}

// -- listings ---------------------------------------------------------------------------------------------------

@Composable
private fun ColumnScope.HomeListings(
    vm: HomeViewModel,
    hs: HomeViewModel.State,
    noDirections: Boolean,
    passengerEnabled: Boolean,
    work: DriverWork,
    nav: DriverNav,
    onMatches: () -> Unit,
) {
    val c = Elchi.colors
    var sheet by rememberSaveable { mutableStateOf(false) }
    val shown = vm.shown(hs)
    SearchPill(hs, shown.size, onQuery = vm::setQuery, onFilter = { sheet = true })
    // The chip the driver left on stays valid when the passenger service goes off.
    val chips = HomeListingRules.chips(passengerEnabled)
    val chip = hs.chip.takeIf { it in chips } ?: HomeChip.ALL
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        chips.forEach { item -> PillChoice(tOrNull(item.key) ?: item.name, item == chip, height = 48.dp, horizontal = 22.dp) { vm.pickChip(item) } }
    }
    Row(Modifier.fillMaxWidth().padding(top = 2.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(t(R.string.driver_v3reg_listingsTitle), Modifier.weight(1f).semantics { heading() }, style = Elchi.type.section.copy(fontSize = 19.sp, lineHeight = 24.sp), color = c.text)
        Text(
            t(R.string.driver_v3reg_seeAll),
            Modifier.clip(CircleShape).clickable(role = Role.Button, onClick = onMatches).padding(horizontal = 6.dp, vertical = 6.dp),
            style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold), color = c.accentText,
        )
    }
    val ps by work.proposals.state.collectAsStateWithLifecycle()
    val mine = Design07Rules.myFeedOffers(ps.open, (ps.lists[ProposalTab.ACCEPTED] as? Load.Ready)?.value.orEmpty(), ps.mine)
    when (val list = hs.listings) {
        // No active direction: say why the list is empty and where to add one (Royxat v3 1.12, decision 1).
        null -> ElchiCard(padding = PaddingValues(16.dp)) {
            Text(t(if (noDirections) R.string.dir_noDirections else R.string.dir_paused), style = Elchi.type.bodyStrong, color = c.text)
            Text(t(R.string.dir_noDirectionsHint), Modifier.padding(top = 4.dp, bottom = 12.dp), style = Elchi.type.caption, color = c.muted)
            if (noDirections) ElchiButton(t(R.string.driverRoutes_addRoute), nav.onAddDirection, Modifier.fillMaxWidth(), icon = ElchiIcon.PLUS)
            else ElchiButton(t(R.string.driverRoutes_title), nav.onRoutes, Modifier.fillMaxWidth(), ButtonVariant.SOFT, icon = ElchiIcon.ROUTE)
        }
        Load.Loading -> LoadingState(count = 2, lines = 2)
        is Load.Failed -> LoadFailed(t(R.string.driver_v3reg_listingsTitle), list.error) { vm.load(work.directions.state.value.list, passengerEnabled, force = true) }
        is Load.Ready -> if (shown.isEmpty()) {
            Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(22.dp)).background(c.card).padding(horizontal = 16.dp, vertical = 24.dp), contentAlignment = Alignment.Center) {
                Text(tOrNull(HomeListingRules.emptyKey(hs.filter, hs.query)).orEmpty(), style = Elchi.type.label.copy(fontWeight = FontWeight.Normal), color = c.muted)
            }
        } else {
            shown.take(HomeListingRules.SHOWN).forEach { h ->
                val threadId = mine[h.listing.id]?.threadId ?: h.item.myThreadId
                HomeListingCard(
                    h,
                    threadId = threadId,
                    onOpen = { nav.onListing(h.directionId, h.listing.id) },
                    onOffer = { nav.onDirectionOffer(h.directionId, h.listing.id) },
                    onThread = { threadId?.let(nav.onThread) },
                )
            }
        }
    }
    if (sheet) FilterSheet(hs.filter, count = shown.size, onChange = vm::setFilter, onClose = { sheet = false })
}

/** The 64dp search pill: the query, a sub-line saying the scope (or the result count) and the filter, ✕ and filter. */
@Composable
private fun SearchPill(hs: HomeViewModel.State, results: Int, onQuery: (String) -> Unit, onFilter: () -> Unit) {
    val c = Elchi.colors
    val filter = hs.filter
    val parts = buildList {
        add(tOrNull(filter.period.key).orEmpty())
        if (filter.sort != HomeSort.NEAREST) add(tOrNull(filter.sort.key).orEmpty())
        if (filter.minPrice != HomeMinPrice.ANY) add(priceLabel(filter.minPrice))
        if (filter.exactOnly) add(t(R.string.match_exact))
    }
    val head = if (hs.query.isNotBlank()) t(R.string.driver_v3reg_searchResults, "count" to results) else t(R.string.driver_v3reg_searchScope)
    val sub = (listOf(head) + parts).joinToString(" · ")
    val placeholder = t(R.string.driver_v3reg_searchPlaceholder)
    val searchLabel = t(R.string.driver_v3reg_searchA11y)
    val filterLabel = t(R.string.driver_v3reg_filter)
    Row(
        Modifier.fillMaxWidth().height(64.dp).shadow(14.dp, RoundedCornerShape(32.dp), ambientColor = c.shadow, spotColor = c.shadow)
            .clip(RoundedCornerShape(32.dp)).background(c.card).padding(start = 18.dp, end = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        ElchiIconView(ElchiIcon.SEARCH, c.muted, size = 22.dp)
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
            BasicTextField(
                value = hs.query,
                onValueChange = onQuery,
                modifier = Modifier.fillMaxWidth().semantics { contentDescription = searchLabel },
                singleLine = true,
                textStyle = Elchi.type.bodyStrong.copy(color = c.text),
                cursorBrush = SolidColor(c.brand),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                decorationBox = { inner ->
                    Box {
                        if (hs.query.isEmpty()) Text(placeholder, style = Elchi.type.bodyStrong, color = c.placeholder, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        inner()
                    }
                },
            )
            Text(sub, style = Elchi.type.caption, color = c.placeholder, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        if (hs.query.isNotEmpty()) {
            val clear = t(R.string.driver_v3reg_clear)
            Box(
                Modifier.size(28.dp).clip(CircleShape).background(c.field).clickable(role = Role.Button) { onQuery("") }.semantics { contentDescription = clear },
                contentAlignment = Alignment.Center,
            ) { ElchiIconView(ElchiIcon.X, c.muted, size = 13.dp) }
        }
        val count = filter.count
        Box(
            Modifier.size(52.dp).clip(CircleShape).background(if (count > 0) driverNavy() else c.page)
                .clickable(role = Role.Button, onClick = onFilter)
                .semantics { contentDescription = if (count > 0) "$filterLabel: $count" else filterLabel },
            contentAlignment = Alignment.Center,
        ) {
            ElchiIconView(ElchiIcon.SLIDERS, if (count > 0) Color.White else c.text, size = 20.dp)
            if (count > 0) {
                Text(
                    count.toString(),
                    Modifier.align(Alignment.TopEnd).offset(x = (-6).dp, y = 6.dp).defaultMinSize(minWidth = 16.dp).height(16.dp).clip(CircleShape).background(c.brand).padding(horizontal = 4.dp),
                    style = Elchi.type.badge.copy(fontSize = 10.sp, lineHeight = 16.sp, fontWeight = FontWeight.Bold),
                    color = c.onBrand,
                )
            }
        }
    }
}

/** A pill choice in the v3 look: navy when chosen, white with a hairline otherwise. */
@Composable
internal fun PillChoice(text: String, selected: Boolean, height: Dp = 40.dp, horizontal: Dp = 16.dp, onClick: () -> Unit) {
    val c = Elchi.colors
    Box(
        Modifier.height(height).clip(CircleShape).background(if (selected) driverNavy() else c.card)
            .then(if (selected) Modifier else Modifier.border(1.dp, c.line, CircleShape))
            .selectable(selected, role = Role.RadioButton, onClick = onClick)
            .padding(horizontal = horizontal),
        contentAlignment = Alignment.Center,
    ) { Text(text, style = Elchi.type.buttonSmall, color = if (selected) Color.White else c.text, maxLines = 1) }
}

@Composable
private fun priceLabel(price: HomeMinPrice): String =
    if (price == HomeMinPrice.ANY) t(R.string.driver_v3reg_priceAny)
    else t(R.string.driver_v3reg_priceFrom, "amount" to ParcelRules.groupThousands(ParcelRules.minorToSoum(price.minor)))

/** Kind icon (Safar v3 5.5): a person, an envelope for documents, a bag, else a box. */
internal fun kindIcon(listing: ListingPublicDTO): ElchiIcon = when {
    listing.serviceType == ServiceType.PASSENGER -> ElchiIcon.USER
    listing.parcelType == ParcelType.DOCUMENTS -> ElchiIcon.ENV
    listing.parcelType == ParcelType.BAG || listing.parcelType == ParcelType.CLOTHING -> ElchiIcon.BAG
    else -> ElchiIcon.PKG
}

/** What a card's chip says: the parcel's category name (Q140: no numbers), or "2 kishi". */
@Composable
internal fun infoChip(listing: ListingPublicDTO): String =
    if (listing.serviceType == ServiceType.PARCEL) listing.parcelCategory?.let { categoryName(it, appRu()) } ?: t(R.string.tripDetail_parcel)
    else t(R.string.seatPicker_peopleCount, "count" to listing.quantity)

/** "02.10, 09:00–18:00": the client's window in Tashkent. */
internal fun windowLine(listing: ListingPublicDTO): String =
    "${DirectionRules.dayClock(listing.departureWindowStart)}–${DirectionRules.clock(listing.departureWindowEnd)}"

/** One home card (Royxat v3 1.12): kind, places, window, price + unit, the info chip, the match tag and "Taklif". */
@Composable
private fun HomeListingCard(h: HomeListing, threadId: String?, onOpen: () -> Unit, onOffer: () -> Unit, onThread: () -> Unit) {
    val c = Elchi.colors
    val l = h.listing
    val shape = RoundedCornerShape(Elchi.look.cardRadius)
    val openLabel = t(R.string.driver_v3trip_openListing)
    Column(
        Modifier.fillMaxWidth().shadow(14.dp, shape, ambientColor = c.shadow, spotColor = c.shadow).clip(shape).background(c.card)
            .clickable(role = Role.Button, onClickLabel = openLabel, onClick = onOpen).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Box(Modifier.size(40.dp).clip(CircleShape).background(c.highlight), contentAlignment = Alignment.Center) { ElchiIconView(kindIcon(l), c.accentText, size = 18.dp) }
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(placeTitle(l), style = Elchi.type.bodyStrong.copy(fontSize = 16.sp), color = c.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(windowLine(l), style = Elchi.type.caption.copy(fontSize = 12.5.sp), color = c.muted, maxLines = 1)
            }
            Column(horizontalAlignment = Alignment.End) {
                Text(soum(HomeListingRules.shownPrice(l)), style = Elchi.type.bodyStrong, color = c.text, maxLines = 1)
                Text(tOrNull(HomeListingRules.unitKey(l)).orEmpty().lowercase(), style = Elchi.type.caption.copy(fontSize = 11.sp), color = c.muted)
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(
                    infoChip(l),
                    Modifier.weight(1f, fill = false).clip(CircleShape).background(c.page).padding(horizontal = 10.dp, vertical = 6.dp),
                    style = Elchi.type.caption.copy(fontWeight = FontWeight.Medium), color = c.text, maxLines = 1, overflow = TextOverflow.Ellipsis,
                )
                val tone = c.tone(HomeListingRules.tagTone(h.item))
                Text(
                    tOrNull(HomeListingRules.tagKey(h.item)).orEmpty(),
                    Modifier.clip(CircleShape).background(tone.bg).padding(horizontal = 10.dp, vertical = 6.dp),
                    style = Elchi.type.caption.copy(fontWeight = FontWeight.SemiBold), color = tone.fg, maxLines = 1,
                )
            }
            if (threadId != null) {
                // Already offered: open that offer, never a second one.
                SmallPill(t(R.string.driver_feed_viewOffer), c.field, c.text, onThread)
            } else {
                SmallPill(t(R.string.driver_v3reg_offer), driverNavy(), Color.White, onOffer)
            }
        }
    }
}

@Composable
private fun SmallPill(text: String, bg: Color, fg: Color, onClick: () -> Unit) {
    Box(
        Modifier.heightIn(min = 38.dp).clip(CircleShape).background(bg).clickable(role = Role.Button, onClick = onClick).padding(horizontal = 13.dp, vertical = 8.dp),
        contentAlignment = Alignment.Center,
    ) { Text(text, style = Elchi.type.label, color = fg, maxLines = 1) }
}

// -- the filter sheet -------------------------------------------------------------------------------------------

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FilterSheet(filter: HomeFilter, count: Int, onChange: (HomeFilter) -> Unit, onClose: () -> Unit) {
    val c = Elchi.colors
    ModalBottomSheet(onDismissRequest = onClose, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true), containerColor = c.card) {
        Column(Modifier.padding(horizontal = 16.dp).padding(bottom = 16.dp).navigationBarsPadding(), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(t(R.string.driver_v3reg_filter), Modifier.weight(1f).semantics { heading() }, style = Elchi.type.title.copy(fontSize = 20.sp, fontWeight = FontWeight.SemiBold), color = c.text)
                Text(
                    t(R.string.driver_v3reg_clear),
                    Modifier.clip(CircleShape).clickable(role = Role.Button) { onChange(HomeFilter()) }.padding(6.dp),
                    style = Elchi.type.secondary.copy(fontWeight = FontWeight.SemiBold), color = c.accentText,
                )
            }
            FilterGroup(t(R.string.driver_v3reg_filterPeriod), HomePeriod.entries, filter.period, { tOrNull(it.key).orEmpty() }) { onChange(filter.copy(period = it)) }
            FilterGroup(t(R.string.driver_v3reg_filterSort), HomeSort.entries, filter.sort, { tOrNull(it.key).orEmpty() }) { onChange(filter.copy(sort = it)) }
            FilterGroup(t(R.string.common_price), HomeMinPrice.entries, filter.minPrice, { priceLabel(it) }) { onChange(filter.copy(minPrice = it)) }
            Row(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).border(1.dp, c.line, RoundedCornerShape(18.dp))
                    .toggleable(filter.exactOnly, role = Role.Switch) { onChange(filter.copy(exactOnly = it)) }
                    .padding(horizontal = 14.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
                    Text(t(R.string.driver_v3reg_exactOnly), style = Elchi.type.secondary.copy(fontWeight = FontWeight.SemiBold), color = c.text)
                    Text(t(R.string.driver_v3reg_exactOnlyHint), style = Elchi.type.caption, color = c.muted)
                }
                V3Switch(filter.exactOnly)
            }
            ElchiButton(
                if (count > 0) t(R.string.driver_v3reg_showCount, "count" to count) else t(R.string.driver_v3reg_noResults),
                onClose, Modifier.fillMaxWidth(),
            )
        }
    }
}

@Composable
private fun <T> FilterGroup(title: String, options: List<T>, selected: T, label: @Composable (T) -> String, onPick: (T) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(title, style = Elchi.type.label, color = Elchi.colors.muted)
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            options.forEach { option -> PillChoice(label(option), option == selected) { onPick(option) } }
        }
    }
}

/** The v3 switch: 48×28 track, brand when on (drawn only; the row carries the toggle semantics). */
@Composable
internal fun V3Switch(on: Boolean, modifier: Modifier = Modifier, enabled: Boolean = true) {
    val c = Elchi.colors
    Box(
        modifier.width(52.dp).height(30.dp).alpha(if (enabled) 1f else 0.5f).clip(CircleShape).background(if (on) c.brand else c.outline).padding(3.dp),
        contentAlignment = if (on) Alignment.CenterEnd else Alignment.CenterStart,
    ) { Box(Modifier.size(24.dp).shadow(1.dp, CircleShape).clip(CircleShape).background(Color.White)) }
}

// -- credit -----------------------------------------------------------------------------------------------------

/** "Kredit va taklif kodi" (Royxat v3 1.16): the usable driver credit, or "Hozircha kredit yo'q"; tap = the bonus screen. */
@Composable
private fun CreditCard(credit: Load<Long>, onBonus: () -> Unit) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(30.dp)
    val amount = (credit as? Load.Ready)?.value?.takeIf { it > 0 }
    Row(
        Modifier.fillMaxWidth().shadow(14.dp, shape, ambientColor = c.shadow, spotColor = c.shadow).clip(shape).background(c.card)
            .clickable(role = Role.Button, onClick = onBonus).padding(18.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(t(R.string.driverProfile_action_bonus), style = Elchi.type.section.copy(fontSize = 20.sp, lineHeight = 25.sp), color = c.text)
            Text(
                if (amount != null) t(R.string.driver_v3reg_creditAmount, "amount" to soum(amount)) else t(R.string.driver_bonus_noCreditTitle),
                style = Elchi.type.bodyStrong, color = if (amount != null) c.accentText else c.muted,
            )
        }
        Box(Modifier.size(48.dp).clip(CircleShape).background(c.field), contentAlignment = Alignment.Center) { ElchiIconView(ElchiIcon.GIFT, c.accentText, size = 22.dp) }
    }
}
