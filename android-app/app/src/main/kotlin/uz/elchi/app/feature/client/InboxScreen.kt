package uz.elchi.app.feature.client

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.ui.Alignment
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.elchi.app.R
import uz.elchi.app.api.generated.NotificationDTO
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.EmptyState
import uz.elchi.app.ui.components.ItemCard
import uz.elchi.app.ui.components.SkeletonCard
import uz.elchi.app.ui.components.SystemBarIcons
import uz.elchi.app.ui.components.TitleBar
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import java.time.Instant

/**
 * `client-notifications` "Bildirishnomalar": a drawer screen for a client ([drawer]), a pushed screen with a back
 * button for a driver ([onBack], Stage 07). Unread rows are outlined with a "Yangi" badge; a tap marks the row read
 * and opens where it leads ([onTarget]; an unknown link only marks it read). Pull to refresh, "Yana yuklash" for
 * older pages.
 */
@Composable
fun NotificationsScreen(vm: InboxViewModel, drawer: DrawerNav?, languageTag: String, onTarget: (InboxTarget) -> Unit, onBack: (() -> Unit)? = null) {
    val c = Elchi.colors
    SystemBarIcons(dark = !c.isDark)
    LaunchedEffect(Unit) { vm.refresh() }
    if (drawer == null) {
        InboxContent(vm, languageTag, onTarget) { TitleBar(onBack, t(R.string.common_back), t(R.string.notifications_title)) }
        return
    }
    ClientDrawerFrame(drawer, DrawerPlace.NOTIFICATIONS) { openDrawer ->
        InboxContent(vm, languageTag, onTarget) {
            TitleBar(openDrawer, menuLabel(drawer.unreadText), t(R.string.notifications_title), leadingIcon = ElchiIcon.MENU, leadingDot = drawer.unreadText != null)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun InboxContent(vm: InboxViewModel, languageTag: String, onTarget: (InboxTarget) -> Unit, bar: @Composable () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val c = Elchi.colors
    Column(Modifier.fillMaxSize().background(c.page)) {
        Column(Modifier.statusBarsPadding()) { bar() }
        PullToRefreshBox(isRefreshing = s.refreshing && s.loaded, onRefresh = vm::refresh, modifier = Modifier.weight(1f)) {
            LazyColumn(
                Modifier.fillMaxSize(),
                contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 6.dp, bottom = 24.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                when {
                    !s.loaded && s.error != null -> item { LoadFailed(t(R.string.notifications_title), s.error!!, vm::refresh) }
                    !s.loaded -> items(3) { SkeletonCard(t(R.string.common_loading), lines = 2) }
                    s.items.isEmpty() -> item {
                        EmptyState(ElchiIcon.BELL, t(R.string.notifications_empty), Modifier.padding(top = 40.dp), description = t(R.string.client_notifications_emptyHint))
                    }
                    else -> {
                        if (s.items.any { !it.isRead }) item(key = "read-all") {
                            Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) {
                                Text(
                                    t(R.string.client_inbox_readAll),
                                    Modifier.heightIn(min = 36.dp).clip(CircleShape).clickable(role = Role.Button, onClick = vm::readAll).padding(horizontal = 6.dp, vertical = 8.dp),
                                    style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold),
                                    color = c.accentText,
                                )
                            }
                        }
                        val now = Instant.now()
                        items(s.items, key = { it.id }) { item -> NotificationRow(item, now, languageTag) { vm.open(item)?.let(onTarget) } }
                        if (s.next != null) item(key = "more") {
                            ElchiButton(
                                t(R.string.blockReport_loadMore), vm::loadMore, Modifier.fillMaxWidth(), ButtonVariant.GHOST, ButtonSize.MEDIUM,
                                icon = ElchiIcon.REFRESH, loading = s.loadingMore,
                            )
                        }
                    }
                }
                item { Box(Modifier.navigationBarsPadding()) }
            }
        }
    }
}

@Composable
private fun NotificationRow(item: NotificationDTO, now: Instant, languageTag: String, onClick: () -> Unit) {
    val context = LocalContext.current
    val params = InboxRules.params(item.params)
    val title = InboxRules.firstKnown(InboxRules.titleKeys(item)) { context.tOrNull(it, *params) } ?: item.type
    val body = InboxRules.firstKnown(InboxRules.bodyKeys(item)) { context.tOrNull(it, *params) }
    ItemCard(
        title = title,
        badge = if (item.isRead) null else t(R.string.client_notifications_new) to Tone.ERR,
        sub = body,
        meta = inboxTime(item.createdAt, now, languageTag),
        highlighted = !item.isRead,
        onClick = onClick,
    )
}

/** "10:24", "Kecha, 08:12", "12 sen". */
@Composable
internal fun inboxTime(createdAt: String?, now: Instant, languageTag: String): String? = when (val time = InboxRules.time(createdAt, now, languageTag)) {
    is InboxTime.Today -> time.time
    is InboxTime.Yesterday -> t(R.string.client_notifications_yesterday, "time" to time.time)
    is InboxTime.Day -> time.date
    null -> null
}
