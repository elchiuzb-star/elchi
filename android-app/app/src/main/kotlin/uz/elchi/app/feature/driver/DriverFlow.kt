package uz.elchi.app.feature.driver

import android.content.Context
import android.net.Uri
import android.widget.Toast
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.toRoute
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import uz.elchi.app.AppContainer
import uz.elchi.app.R
import uz.elchi.app.deeplink.DeepLinkRules
import uz.elchi.app.deeplink.DeepLinkTarget
import uz.elchi.app.feature.client.AccountDeleteScreen
import uz.elchi.app.feature.client.AccountDeleteViewModel
import uz.elchi.app.feature.client.FaqSet
import uz.elchi.app.feature.client.HelpScreen
import uz.elchi.app.feature.client.HelpViewModel
import uz.elchi.app.feature.client.InboxTarget
import uz.elchi.app.feature.client.InboxViewModel
import uz.elchi.app.feature.client.NotificationsScreen
import uz.elchi.app.feature.client.PhotoCompressor
import uz.elchi.app.feature.client.SafetyCenterScreen
import uz.elchi.app.feature.client.SafetyCenterViewModel
import uz.elchi.app.feature.client.SettingsScreen
import uz.elchi.app.feature.client.SupportChatScreen
import uz.elchi.app.feature.client.SupportThreadsScreen
import uz.elchi.app.feature.client.SupportThreadsViewModel
import uz.elchi.app.feature.client.SupportViewModel
import uz.elchi.app.i18n.t
import uz.elchi.app.push.AskNotificationsOnce
import uz.elchi.app.push.PushRules
import uz.elchi.app.session.Session

@Serializable private data object Tabs
@Serializable private data object ProfileForm
@Serializable private data object Documents
@Serializable private data object Notifications
@Serializable private data object Help
@Serializable private data object SupportThreads
@Serializable private data class SupportThread(val id: String)
@Serializable private data object SafetyCenter
@Serializable private data object Settings
@Serializable private data object AccountDelete

/**
 * Signed in as a driver (Stage 07): a bottom-navigation shell (home, routes, matches, orders, profile). Until the
 * operator approves the driver, routes / matches / orders show the verification gate (Q96); after approval they say
 * the next stage fills them. From home and the profile menu: the profile form (the car entered once, Q94), the five
 * documents, and the Stage 05 screens that are the same for both roles (notifications, help, operator threads,
 * safety centre, settings, account deletion). [DriverViewModel] is the one copy of the driver record every tab reads.
 */
@Composable
fun DriverFlow(container: AppContainer, session: Session) {
    val nav = rememberNavController()
    val locale by container.locale.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val appContext = context.applicationContext
    val scope = rememberCoroutineScope()
    val driver: DriverViewModel = viewModel(
        key = "driver-${session.user.id}",
        factory = viewModelFactory { initializer { DriverViewModel(container.api, container.driver, container.banners, container.referral) } },
    )
    val inbox: InboxViewModel = viewModel(
        key = "driver-inbox-${session.user.id}",
        factory = viewModelFactory { initializer { InboxViewModel(container.api) } },
    )
    var tab by rememberSaveable { mutableStateOf(DriverTab.HOME) }

    val signOut: () -> Unit = {
        scope.launch {
            // While the tokens still work: this phone stops getting this person's pushes.
            container.push.unregister()
            runCatching { container.auth.logout(session.refreshToken) }
            container.sessions.clear()
            // The person asked to leave: a refresh refused on the way out is not a "session expired".
            container.sessions.dismissExpired()
        }
    }
    val deletedText = t(R.string.client_accountDelete_done)
    val accountDeleted: () -> Unit = {
        container.push.dropToken()
        container.sessions.clear()
        Toast.makeText(appContext, deletedText, Toast.LENGTH_LONG).show()
    }
    // A driver has no booking or listing screens yet (Stage 08): those links only mark the item read.
    val openTarget: (InboxTarget) -> Unit = { target ->
        if (target is InboxTarget.SupportThread) nav.navigate(SupportThread(target.id))
    }
    val routes = DriverNav(
        onProfileForm = { nav.navigate(ProfileForm) { launchSingleTop = true } },
        onDocuments = { nav.navigate(Documents) { launchSingleTop = true } },
        onNotifications = { nav.navigate(Notifications) { launchSingleTop = true } },
        onHelp = { nav.navigate(Help) { launchSingleTop = true } },
        onThreads = { nav.navigate(SupportThreads) { launchSingleTop = true } },
        onSafety = { nav.navigate(SafetyCenter) { launchSingleTop = true } },
        onSettings = { nav.navigate(Settings) { launchSingleTop = true } },
        onSignOut = signOut,
    )

    // A link from outside (cold or warm start, or kept through sign-in). A driver can open the operator conversation;
    // a referral code shows as the home row (tap = confirm); bookings, listings and proposals are client screens
    // for now, so they say "cannot be opened in the app".
    val link by container.links.target.collectAsStateWithLifecycle()
    LaunchedEffect(link) {
        val target = link ?: return@LaunchedEffect
        if (!container.links.take(target)) return@LaunchedEffect
        when (val allowed = DeepLinkRules.forRole(target, session.user.mobileRole)) {
            is DeepLinkTarget.Referral -> {
                nav.popBackStack<Tabs>(inclusive = false)
                tab = DriverTab.HOME
            }
            is DeepLinkTarget.SupportThread -> nav.navigate(SupportThread(allowed.id))
            DeepLinkTarget.SupportThreads -> nav.navigate(SupportThreads) { launchSingleTop = true }
            is DeepLinkTarget.Inbox -> {
                val event = allowed.event
                // A push tap: the inbox row of the same event carries the real link; a driver opens only the
                // operator conversation from it so far (see ClientFlow for why this is not in the effect's scope).
                if (event == null) nav.navigate(Notifications) { launchSingleTop = true } else scope.launch {
                    val thread = inbox.openLatest(event, allowed.ref) as? InboxTarget.SupportThread
                    when {
                        thread != null -> nav.navigate(SupportThread(thread.id))
                        PushRules.fallsBackToThreads(event) -> nav.navigate(SupportThreads) { launchSingleTop = true }
                        else -> nav.navigate(Notifications) { launchSingleTop = true }
                    }
                }
            }
            else -> container.links.unsupported()
        }
    }
    // A push arrived (the notification is already shown, also in the foreground): the unread dot, and the open list.
    LaunchedEffect(inbox) {
        container.push.received.collect { if (inbox.state.value.loaded) inbox.refresh() else inbox.refreshUnread() }
    }

    NavHost(nav, startDestination = Tabs) {
        composable<Tabs> {
            AskNotificationsOnce(container.push)
            DriverShell(
                driver = driver,
                inbox = inbox,
                session = session,
                tab = tab,
                onTab = { tab = it },
                nav = routes,
            )
        }
        composable<ProfileForm> {
            val vm: DriverProfileFormViewModel = viewModel(factory = viewModelFactory {
                initializer { DriverProfileFormViewModel(container.api, container.driver, container.banners, driver::refresh) }
            })
            DriverProfileFormScreen(vm = vm, onBack = { nav.popBackStack() })
        }
        composable<Documents> {
            val vm: DriverDocumentsViewModel = viewModel(factory = viewModelFactory {
                initializer { DriverDocumentsViewModel(container.driver, container.files, ContentDocumentSource(appContext), container.banners, driver::refresh) }
            })
            DriverDocumentsScreen(vm = vm, onBack = { nav.popBackStack() })
        }
        composable<Notifications> {
            NotificationsScreen(vm = inbox, drawer = null, languageTag = locale.tag, onTarget = openTarget, onBack = { nav.popBackStack() })
        }
        composable<Help> {
            val vm: HelpViewModel = viewModel(factory = viewModelFactory { initializer { HelpViewModel(container.api) } })
            HelpScreen(vm = vm, onBack = { nav.popBackStack() }, onThreads = { nav.navigate(SupportThreads) }, faq = FaqSet.DRIVER)
        }
        composable<SupportThreads> {
            val vm: SupportThreadsViewModel = viewModel(factory = viewModelFactory { initializer { SupportThreadsViewModel(container.api) } })
            SupportThreadsScreen(vm = vm, onBack = { nav.popBackStack() }, onThread = { id -> nav.navigate(SupportThread(id)) })
        }
        composable<SupportThread> { entry ->
            val id = entry.toRoute<SupportThread>().id
            val vm: SupportViewModel = viewModel(key = "support-thread-$id", factory = viewModelFactory { initializer { SupportViewModel(container.api, bookingId = null, threadId = id) } })
            SupportChatScreen(vm = vm, onBack = { nav.popBackStack() })
        }
        composable<SafetyCenter> {
            val vm: SafetyCenterViewModel = viewModel(factory = viewModelFactory { initializer { SafetyCenterViewModel(container.api, container.account) } })
            SafetyCenterScreen(vm = vm, onBack = { nav.popBackStack() })
        }
        composable<Settings> {
            SettingsScreen(
                themeMode = container.theme.state.collectAsStateWithLifecycle().value,
                onTheme = container.theme::set,
                locale = locale,
                onLocale = container.locale::set,
                onBack = { nav.popBackStack() },
                onHelp = { nav.navigate(Help) },
                onDeleteAccount = { nav.navigate(AccountDelete) },
                onSignOut = signOut,
            )
        }
        composable<AccountDelete> {
            val vm: AccountDeleteViewModel = viewModel(factory = viewModelFactory { initializer { AccountDeleteViewModel(container.api, container.push::unregister) { container.appScope.launch { container.push.sync() } } } })
            AccountDeleteScreen(vm = vm, onBack = { nav.popBackStack() }, onDeleted = accountDeleted)
        }
    }
}

/** Where the driver screens lead outside the tabs. */
data class DriverNav(
    val onProfileForm: () -> Unit,
    val onDocuments: () -> Unit,
    val onNotifications: () -> Unit,
    val onHelp: () -> Unit,
    val onThreads: () -> Unit,
    val onSafety: () -> Unit,
    val onSettings: () -> Unit,
    /** Signs out right away; the confirmation is asked by the caller. */
    val onSignOut: () -> Unit,
)

/** Picked files through the content resolver: images via the Stage 02 photo pipeline, PDFs byte for byte. */
private class ContentDocumentSource(private val context: Context) : DocumentSource {
    override suspend fun image(uri: Uri): ByteArray = PhotoCompressor(context).compress(uri, prefix = "document").bytes

    override suspend fun file(uri: Uri, maxBytes: Long): DocumentSource.Picked = withContext(Dispatchers.IO) {
        val resolver = context.contentResolver
        // Never more than one byte over the limit in memory: a 60 MB scan is refused, not loaded.
        val bytes = resolver.openInputStream(uri)?.use { stream ->
            val out = java.io.ByteArrayOutputStream()
            val buffer = ByteArray(64 * 1024)
            while (out.size() <= maxBytes) {
                val read = stream.read(buffer)
                if (read < 0) break
                out.write(buffer, 0, read)
            }
            out.toByteArray()
        } ?: throw DocumentFileError(DocumentFileError.Kind.UNREADABLE)
        DocumentSource.Picked(bytes, resolver.getType(uri))
    }
}
