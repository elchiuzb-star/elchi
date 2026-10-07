package uz.elchi.app.feature.client

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.elchi.app.R
import uz.elchi.app.api.LegacyOrder
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.Chip
import uz.elchi.app.ui.components.EmptyListState
import uz.elchi.app.ui.components.ItemCard
import uz.elchi.app.ui.components.ItemLine
import uz.elchi.app.ui.components.LoadingState
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.SystemBarIcons
import uz.elchi.app.ui.components.TitleBar
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone

/*
 * DESIGN10 (BOSQICH 10) "Eski buyurtmalar": the client's v1 orders on a screen of their own (Q4, an archive). From the
 * drawer it is a top-level screen with the menu; from the orders list's row it is pushed with a back arrow.
 */

/**
 * The archive list: a grey note (true wording - started orders can still be finished here, `listNote`), the chips
 * "Hammasi / Yakunlangan / Bekor qilingan / Nizoli" filtered on the phone (the v1 list takes one status), and the
 * cards. With a filter on and few rows, the next page is read by itself. Pull to refresh reads the first page again.
 */
@Composable
fun LegacyListScreen(vm: OrdersViewModel, onLegacy: (Long) -> Unit, onBack: () -> Unit, drawer: DrawerNav?) {
    SystemBarIcons(dark = !Elchi.colors.isDark)
    LaunchedEffect(Unit) { vm.refreshLegacy() }
    if (drawer == null) {
        LegacyListContent(vm, onLegacy) { TitleBar(onBack, t(R.string.common_back), t(R.string.orders_legacy)) }
        return
    }
    ClientDrawerFrame(drawer, DrawerPlace.LEGACY) { openDrawer ->
        LegacyListContent(vm, onLegacy) {
            TitleBar(openDrawer, menuLabel(drawer.unreadText), t(R.string.orders_legacy), leadingIcon = ElchiIcon.MENU, leadingDot = drawer.unreadText != null)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LegacyListContent(vm: OrdersViewModel, onLegacy: (Long) -> Unit, bar: @Composable () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val c = Elchi.colors
    var filter by rememberSaveable { mutableStateOf(LegacyRules.Filter.ALL) }
    val page = s.legacy
    val shown = page.items.filter { LegacyRules.matches(filter, it.status) }
    // A filter that leaves few rows keeps reading pages until the screen fills or the history ends.
    LaunchedEffect(filter, page.items.size, page.next) {
        if (page.loaded && page.next != null && !page.loadingMore && shown.size < LegacyRules.FILL_ROWS) vm.loadMoreLegacy()
    }
    Column(Modifier.fillMaxSize().background(c.page)) {
        Column(Modifier.statusBarsPadding()) { bar() }
        PullToRefreshBox(isRefreshing = s.legacyRefreshing && page.loaded, onRefresh = vm::refreshLegacy, modifier = Modifier.weight(1f)) {
            LazyColumn(
                Modifier.fillMaxSize(),
                contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 6.dp, bottom = 24.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                item(key = "note") { Note(t(R.string.client_v3archive_listNote), tone = Tone.GRAY) }
                item(key = "chips") {
                    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        LegacyRules.Filter.entries.forEach { option ->
                            Chip(tOrNull(option.labelKey) ?: option.name, selected = option == filter, onClick = { filter = option }, filled = true)
                        }
                    }
                }
                when {
                    !page.loaded -> item(key = "loading") { LoadingState() }
                    page.error != null && page.items.isEmpty() -> item(key = "failed") { LoadFailed(t(R.string.orders_legacy), page.error, vm::refreshLegacy) }
                    shown.isEmpty() && page.next == null -> item(key = "empty") { EmptyListState(Modifier.padding(top = 24.dp)) }
                    else -> {
                        items(shown, key = { "legacy-${it.id}" }) { order -> LegacyListRow(order) { onLegacy(order.id) } }
                        if (page.next != null) item(key = "more") {
                            LaunchedEffect(page.items.size) { vm.loadMoreLegacy() }
                            LoadingLine(t(R.string.common_loading))
                        }
                    }
                }
                item { Box(Modifier.navigationBarsPadding()) }
            }
        }
    }
}

/** DESIGN10 1.3/1.4: route, status, "EL-10422 · 04.08.2026", price; the bids line while bidding (spec). */
@Composable
private fun LegacyListRow(order: LegacyOrder, onClick: () -> Unit) {
    val bids = order.bidsCount ?: 0
    ItemCard(
        title = "${order.fromCity ?: order.fromDistrict?.nameUz ?: "?"} → ${order.toCity ?: order.toDistrict?.nameUz ?: "?"}",
        badge = (tOrNull(OrderRules.legacyStatusKey(order.status)) ?: order.status) to OrderRules.statusTone(order.status),
        lines = if (bids > 0 && LegacyRules.bidsOpen(order.status)) listOf(ItemLine(t(R.string.app_orderCard_bids, "count" to bids), Elchi.colors.accentText)) else emptyList(),
        meta = LegacyRules.numberAndDate(order.orderNumber, order.createdAt),
        right = OrderRules.legacyPriceMinor(order.finalPrice, order.suggestedPrice, order.clientPrice)?.let { soum(it) },
        onClick = onClick,
    )
}
