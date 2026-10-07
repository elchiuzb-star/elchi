package uz.elchi.app.feature.client

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.delay
import uz.elchi.app.R
import uz.elchi.app.api.BookingClientDTO
import uz.elchi.app.api.LegacyOrder
import uz.elchi.app.api.generated.ListingDTO
import uz.elchi.app.api.generated.ProposalThreadDTO
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.Banner
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.EmptyState
import uz.elchi.app.ui.components.ItemCard
import uz.elchi.app.ui.components.ItemLine
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.SectionTitle
import uz.elchi.app.ui.components.SystemBarIcons
import uz.elchi.app.ui.components.TitleBar
import uz.elchi.app.ui.components.RoundIconButton
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone
import java.time.Instant

// -- client-orders -----------------------------------------------------------------------------------------------

/**
 * `client-orders` "Buyurtmalar": bookings, the client's own listings (with live offer counts) and the read-only
 * v1 orders, each paged and loaded on its own; pull to refresh. A booking row opens the booking (Stage 04).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ClientOrdersScreen(
    vm: OrdersViewModel,
    ru: Boolean,
    languageTag: String,
    onHome: () -> Unit,
    onListing: (String) -> Unit,
    onBooking: (String) -> Unit,
    onLegacy: (Long) -> Unit,
    onNotifications: () -> Unit,
    drawer: DrawerNav,
) {
    val s by vm.state.collectAsStateWithLifecycle()
    val c = Elchi.colors
    SystemBarIcons(dark = !c.isDark)
    LaunchedEffect(Unit) { vm.refresh() }
    val list = rememberLazyListState()
    // The one-time banner ("Haydovchi tanlandi") stays a few seconds, then the list is the list again. The new
    // booking is the first row, so the list starts from the top.
    LaunchedEffect(s.notice) {
        if (s.notice != null) {
            list.scrollToItem(0)
            delay(NOTICE_MS)
            vm.consumeNotice()
        }
    }
    ClientDrawerFrame(drawer, DrawerPlace.ORDERS) { openDrawer ->
        Column(Modifier.fillMaxSize().background(c.page)) {
            Column(Modifier.statusBarsPadding()) {
                // The bell with the unread count opens the notifications (design `barBell`); "Takliflarim" moved to the drawer.
                val bellLabel = drawer.unreadText?.let { "${t(R.string.notifications_title)}, $it" } ?: t(R.string.notifications_title)
                TitleBar(
                    openDrawer, menuLabel(drawer.unreadText), t(R.string.orders_title), leadingIcon = ElchiIcon.MENU, leadingDot = drawer.unreadText != null,
                    trailing = { RoundIconButton(ElchiIcon.BELL, bellLabel, onNotifications, count = drawer.unreadText) },
                )
                s.notice?.let {
                    Banner(t(if (it == OrdersNotice.DRIVER_CHOSEN) R.string.listingBids_driverChosen else R.string.listingDetail_cancelled), Tone.OK)
                }
            }
            if (s.empty) {
                Column(Modifier.weight(1f)) {
                    EmptyState(ElchiIcon.PKG, t(R.string.orders_empty), Modifier.padding(top = 40.dp), description = t(R.string.client_orders_emptyText))
                }
                Column(Modifier.fillMaxWidth().background(c.card)) {
                    Box(Modifier.fillMaxWidth().height(1.dp).background(c.line))
                    Column(Modifier.navigationBarsPadding().padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 8.dp)) {
                        ElchiButton(t(R.string.nav_homeHint), onHome, Modifier.fillMaxWidth())
                    }
                }
                return@ClientDrawerFrame
            }
            val bookingsTitle = t(R.string.client_orders_bookings)
            val listingsTitle = t(R.string.client_orders_listings)
            val legacyTitle = t(R.string.orders_legacy)
            PullToRefreshBox(isRefreshing = s.refreshing && s.loaded, onRefresh = vm::refresh, modifier = Modifier.weight(1f)) {
                LazyColumn(
                    Modifier.fillMaxSize(),
                    state = list,
                    contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 6.dp, bottom = 24.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    if (!s.loaded) item { LoadingLine(t(R.string.common_loading)) }
                    s.failed?.let { error -> item { LoadFailed(t(R.string.orders_title), error, vm::refresh) } }
                    if (s.loaded && s.failed == null && listOf(s.bookings.error, s.listings.error, s.legacy.error).any { it != null }) {
                        item { Note(t(R.string.client_orders_partialFailed), tone = Tone.WARN) }
                    }
                    section(bookingsTitle, s.bookings, "booking", { it.id }, vm::loadMoreBookings) { BookingRow(it, ru, languageTag) { onBooking(it.id) } }
                    section(listingsTitle, s.listings, "listing", { it.id }, vm::loadMoreListings) { listing ->
                        ListingRow(listing, s.stats[listing.id], ru, languageTag) { onListing(listing.id) }
                    }
                    section(legacyTitle, s.legacy, "legacy", { it.id.toString() }, vm::loadMoreLegacy) { LegacyRow(it, languageTag) { onLegacy(it.id) } }
                    item { Box(Modifier.navigationBarsPadding()) }
                }
            }
        }
    }
}

/** A titled list section; its last row asks for the next page when there is one. */
private fun <T> LazyListScope.section(
    title: String,
    page: Paged<T>,
    prefix: String,
    key: (T) -> String,
    loadMore: () -> Unit,
    row: @Composable (T) -> Unit,
) {
    if (page.items.isEmpty()) return
    item(key = "$prefix-title") { SectionTitle(title) }
    items(page.items, key = { "$prefix-${key(it)}" }) { row(it) }
    if (page.next != null) {
        item(key = "$prefix-more") {
            LaunchedEffect(page.items.size) { loadMore() }
            LoadingLine(t(R.string.common_loading))
        }
    }
}

@Composable
private fun BookingRow(booking: BookingClientDTO, ru: Boolean, languageTag: String, onClick: () -> Unit) {
    val status = booking.serviceStatus
    ItemCard(
        title = "${OrderRules.shortEnd(booking.pickup.point, ru)} → ${OrderRules.shortEnd(booking.dropoff.point, ru)}",
        icon = ElchiIcon.PIN,
        badge = (tOrNull(OrderRules.bookingStatusKey(booking.serviceType, status)) ?: status) to OrderRules.clientBookingTone(booking.serviceType, status),
        // "29 sen, 10:00–12:00": the day and the agreed pickup window.
        meta = listOfNotNull(
            OrderRules.dayMonth(booking.pickup.windowStart ?: booking.createdAt, languageTag),
            OrderRules.hourMinute(booking.pickup.windowStart)?.let { s -> OrderRules.hourMinute(booking.pickup.windowEnd)?.let { "$s–$it" } ?: s },
        ).joinToString(", "),
        lines = if (TaxiRules.isPassenger(booking.serviceType)) listOf(ItemLine(seatsLine(booking.quantity, booking.unitPriceMinor))) else emptyList(),
        // Q103: with a discount the client hands over the cash due, not the fare.
        right = soum(booking.promo?.cashDueMinor ?: booking.totalMinor),
        onClick = onClick,
    )
}

/** Line 3 (1.4): "Yangi taklif: {ago}" (blue while an offer is open), "Haydovchi tanlandi", or "E'lon amal qiladi: 02.10 gacha". */
@Composable
private fun ListingRow(listing: ListingDTO, stats: OfferStats?, ru: Boolean, languageTag: String, onClick: () -> Unit) {
    val c = Elchi.colors
    val meta = when (val m = OrderRules.listingMeta(listing, stats)) {
        is ListingMeta.NewOffer -> t(R.string.client_listing_metaNewOffer, "ago" to agoText(OrderRules.ago(m.at, Instant.now()))) to (if (m.highlight) c.accentText else null)
        ListingMeta.DriverChosen -> t(R.string.listingBids_driverChosen) to null
        is ListingMeta.ValidUntil -> t(R.string.client_listing_metaValidUntil, "date" to m.date) to null
        null -> null
    }
    ListingItem(listing, stats, ru, languageTag, meta = meta, onClick = onClick)
}

/**
 * A v1 order (Q4, an archive): route, status, day, price (agreed, else the client's, else the suggested one - DECIMAL
 * so'm on the wire) and the bids while there are any. Opens its archive detail.
 */
@Composable
private fun LegacyRow(order: LegacyOrder, languageTag: String, onClick: () -> Unit) {
    val bids = order.bidsCount ?: 0
    ItemCard(
        title = "${order.fromCity ?: order.fromDistrict?.nameUz ?: "?"} → ${order.toCity ?: order.toDistrict?.nameUz ?: "?"}",
        badge = (tOrNull(OrderRules.legacyStatusKey(order.status)) ?: order.status) to OrderRules.statusTone(order.status),
        lines = if (bids > 0 && LegacyRules.bidsOpen(order.status)) listOf(ItemLine(t(R.string.app_orderCard_bids, "count" to bids), Elchi.colors.accentText)) else emptyList(),
        // v1 may send a naive timestamp (Q9: timestamptz migration pending); it is read as UTC, only the day is shown.
        meta = OrderRules.dayMonth(LegacyRules.isoInstant(order.createdAt), languageTag)?.let { "$it · ${t(R.string.client_listing_legacyArchive)}" },
        right = OrderRules.legacyPriceMinor(order.finalPrice, order.suggestedPrice, order.clientPrice)?.let { soum(it) },
        onClick = onClick,
    )
}

private const val NOTICE_MS = 4_000L

// -- client-proposals --------------------------------------------------------------------------------------------

/**
 * `props` "Takliflarim": every negotiation the client is a party of, as the same offer card as the listing's board
 * (8.3) with the route as its first line (the threads span listings); live first. Refresh is the bar's icon.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProposalsScreen(vm: OrdersViewModel, ru: Boolean, onBack: () -> Unit, onAccepted: (Accepted) -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val b by vm.board.state.collectAsStateWithLifecycle()
    val now by rememberNow()
    val c = Elchi.colors
    SystemBarIcons(dark = !c.isDark)
    LaunchedEffect(Unit) { vm.refreshProposals() }
    OfferNoticeToast(b.notice) { vm.board.consumeNotice() }
    LaunchedEffect(b.accepted) {
        b.accepted?.let {
            vm.board.consumeAccepted()
            onAccepted(it)
        }
    }
    val handlers = remember(vm) { OfferHandlers(vm.board) }
    Column(Modifier.fillMaxSize().background(c.page)) {
        Column(Modifier.statusBarsPadding()) {
            TitleBar(
                onBack, t(R.string.common_back), t(R.string.proposals_title),
                trailing = { RoundIconButton(ElchiIcon.REFRESH, t(R.string.proposal_refresh), vm::refreshProposals, loading = s.proposalsRefreshing && s.proposals is Load.Ready) },
            )
            OfferWarnings(b.warnings) { vm.board.consumeNotice() }
        }
        PullToRefreshBox(isRefreshing = s.proposalsRefreshing && s.proposals is Load.Ready, onRefresh = vm::refreshProposals, modifier = Modifier.weight(1f)) {
            LazyColumn(
                Modifier.fillMaxSize(),
                contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 6.dp, bottom = 24.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                when (val load = s.proposals) {
                    Load.Loading -> item { LoadingLine(t(R.string.common_loading)) }
                    is Load.Failed -> item { LoadFailed(t(R.string.proposals_title), load.error, vm::refreshProposals) }
                    is Load.Ready -> if (load.value.isEmpty()) {
                        item { EmptyState(ElchiIcon.TAG, t(R.string.client_proposals_emptyTitle), description = t(R.string.client_proposals_emptyText)) }
                    } else {
                        val sorted = load.value.sortedBy { if (OrderRules.negotiationActions(it, now).open) 0 else 1 }
                        items(sorted, key = { it.id }) { thread ->
                            OfferCard(
                                thread, b, handlers, now, ru,
                                previousTotal = s.previousTotals[thread.id],
                                route = thread.currentVersion?.let { "${OrderRules.shortEnd(it.pickupPoint, ru)} → ${OrderRules.shortEnd(it.dropoffPoint, ru)}" },
                                requestWindow = s.listings.items.firstOrNull { it.id == thread.listingId }?.let { it.departureWindowStart to it.departureWindowEnd },
                            )
                        }
                        item { Note(t(R.string.listingBids_identityHidden), tone = Tone.BLUE) }
                    }
                }
                item { Box(Modifier.navigationBarsPadding()) }
            }
        }
    }
    val confirming = (s.proposals as? Load.Ready)?.value?.firstOrNull { it.id == b.confirming }
    if (confirming != null) AcceptDialogFor(
        confirming, b, onConfirm = { vm.board.accept(confirming) }, onDismiss = vm.board::dismissAccept,
        requestWindow = s.listings.items.firstOrNull { it.id == confirming.listingId }?.let { it.departureWindowStart to it.departureWindowEnd },
    )
}
