package uz.elchi.app.feature.client

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.Text
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import uz.elchi.app.R
import uz.elchi.app.i18n.t
import uz.elchi.app.session.Session
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.ElchiDialog
import uz.elchi.app.ui.components.ListCard
import uz.elchi.app.ui.components.ListRow
import uz.elchi.app.ui.components.ListRowStyle
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi

/** Which drawer destination the screen behind it is. */
enum class DrawerPlace { HOME, ORDERS, NOTIFICATIONS }

/**
 * Everything the side menu needs from the flow: who is signed in, the unread state (read when home appears and
 * when the menu opens - [onOpened] - never on a timer) and where each row goes.
 */
data class DrawerNav(
    val session: Session,
    val unread: Int,
    val unreadMore: Boolean,
    val onHome: () -> Unit,
    val onOrders: () -> Unit,
    val onNotifications: () -> Unit,
    /** "Takliflarim" (8.1): every price negotiation, pushed over the current screen. */
    val onProposals: () -> Unit,
    val onProfile: () -> Unit,
    val onHelp: () -> Unit,
    val onSettings: () -> Unit,
    /** Signs out right away; the confirmation is asked by whoever calls it ([LogoutConfirm]). */
    val onSignOut: () -> Unit,
    val onOpened: () -> Unit,
) {
    /** "3", "30+", or null for none. */
    val unreadText: String? get() = when {
        unread <= 0 -> null
        unreadMore -> "$unread+"
        else -> unread.toString()
    }
}

/**
 * The client's side menu around a top-level screen (home, orders, notifications): [content] gets the function
 * that opens it. Closed, the drawer takes no edge swipe - on home that would fight the map's pans; the menu
 * button opens it.
 */
@Composable
fun ClientDrawerFrame(
    nav: DrawerNav,
    current: DrawerPlace,
    content: @Composable (openDrawer: () -> Unit) -> Unit,
) {
    val drawer = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    val c = Elchi.colors
    var confirmLogout by remember { mutableStateOf(false) }
    // System back closes an open drawer first (the drawer itself does not listen to it).
    BackHandler(enabled = drawer.isOpen) { scope.launch { drawer.close() } }
    LaunchedEffect(drawer.isOpen) { if (drawer.isOpen) nav.onOpened() }
    val go: (DrawerPlace?, () -> Unit) -> () -> Unit = { place, action -> { scope.launch { drawer.close() }; if (place != current) action() } }
    ModalNavigationDrawer(
        drawerState = drawer,
        gesturesEnabled = drawer.isOpen,
        scrimColor = Color(0x800A1226),
        drawerContent = {
            ModalDrawerSheet(
                modifier = Modifier.width(300.dp).fillMaxHeight(),
                drawerShape = RoundedCornerShape(topEnd = 0.dp, bottomEnd = 0.dp),
                drawerContainerColor = c.page,
                windowInsets = WindowInsets(0),
            ) {
                ClientDrawer(
                    nav,
                    current,
                    go = go,
                    onSignOut = { confirmLogout = true },
                )
            }
        },
    ) {
        content { scope.launch { drawer.open() } }
    }
    if (confirmLogout) {
        LogoutConfirm(
            onConfirm = {
                confirmLogout = false
                scope.launch { drawer.close() }
                nav.onSignOut()
            },
            onDismiss = { confirmLogout = false },
        )
    }
}

/** `dialogs`: "Chiqasizmi?" before any sign-out (drawer, profile, settings). */
@Composable
fun LogoutConfirm(onConfirm: () -> Unit, onDismiss: () -> Unit) {
    ElchiDialog(
        title = t(R.string.client_logout_confirmTitle),
        text = t(R.string.client_logout_confirmText),
        confirm = t(R.string.nav_logout),
        onConfirm = onConfirm,
        onDismiss = onDismiss,
        confirmVariant = ButtonVariant.DANGER,
        dismiss = t(R.string.client_logout_stay),
    )
}

/** `drawer`: who is signed in, the destinations, sign-out. */
@Composable
private fun ClientDrawer(nav: DrawerNav, current: DrawerPlace, go: (DrawerPlace?, () -> Unit) -> () -> Unit, onSignOut: () -> Unit) {
    val c = Elchi.colors
    val session = nav.session
    fun style(place: DrawerPlace) = if (current == place) ListRowStyle.CURRENT else ListRowStyle.NORMAL
    Column(
        Modifier.fillMaxSize().statusBarsPadding().verticalScroll(rememberScrollState()).padding(start = 16.dp, end = 16.dp, top = 40.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("ELCHI", Modifier.semantics { heading() }, style = Elchi.type.title.copy(fontSize = 20.sp, lineHeight = 24.sp), color = c.text)
            Text(session.user.fullName?.takeIf { it.isNotBlank() } ?: displayPhone(session.user.phone), style = Elchi.type.secondary, color = c.muted)
        }
        ListCard {
            ListRow(t(R.string.nav_home), icon = ElchiIcon.HOME, description = t(R.string.nav_homeHint), first = true, style = style(DrawerPlace.HOME), onClick = go(DrawerPlace.HOME, nav.onHome))
            ListRow(t(R.string.nav_orders), icon = ElchiIcon.PKG, description = t(R.string.nav_ordersHint), style = style(DrawerPlace.ORDERS), onClick = go(DrawerPlace.ORDERS, nav.onOrders))
            ListRow(
                t(R.string.notifications_title), icon = ElchiIcon.BELL, description = t(R.string.clientProfile_notificationsHint),
                style = style(DrawerPlace.NOTIFICATIONS), count = nav.unreadText, onClick = go(DrawerPlace.NOTIFICATIONS, nav.onNotifications),
            )
            ListRow(t(R.string.proposals_title), icon = ElchiIcon.TAG, description = t(R.string.client_offers_drawerHint), onClick = go(null, nav.onProposals))
            ListRow(t(R.string.nav_profile), icon = ElchiIcon.USER, description = t(R.string.nav_profileHint), onClick = go(null, nav.onProfile))
            ListRow(t(R.string.support_title), icon = ElchiIcon.HEAD, description = t(R.string.clientProfile_helpHint), onClick = go(null, nav.onHelp))
            ListRow(t(R.string.settingsScreen_title), icon = ElchiIcon.SETTINGS, description = t(R.string.clientProfile_settingsHint), onClick = go(null, nav.onSettings))
        }
        ListCard {
            ListRow(t(R.string.nav_logout), icon = ElchiIcon.LOGOUT, first = true, style = ListRowStyle.DANGER, onClick = onSignOut)
        }
    }
}
