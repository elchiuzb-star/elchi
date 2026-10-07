package uz.elchi.app.feature.driver

import android.content.Context
import android.net.Uri
import android.widget.Toast
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.navigation.NavBackStackEntry
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
import uz.elchi.app.feature.client.AmendmentScreen
import uz.elchi.app.feature.client.BonusScreen
import uz.elchi.app.feature.client.BonusViewModel
import uz.elchi.app.feature.client.BookingChatScreen
import uz.elchi.app.feature.client.BookingChatViewModel
import uz.elchi.app.feature.client.BookingSide
import uz.elchi.app.feature.client.BookingTrackingScreen
import uz.elchi.app.feature.client.BookingViewModel
import uz.elchi.app.feature.client.RatingScreen
import uz.elchi.app.feature.client.SafetyScreen
import uz.elchi.app.feature.client.TrackingViewModel
import uz.elchi.app.gps.DriverTrackingBar
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
@Serializable private data object AddTrip
@Serializable private data object AddDirection
@Serializable private data class DirectionBid(val directionId: String, val listingId: String)
@Serializable private data class TripDetail(val id: String)
@Serializable private data object SavedSearches
@Serializable private data class Bid(val listingId: String)
@Serializable private data object Proposals
@Serializable private data class ProposalThread(val id: String)
@Serializable private data class DriverBooking(val id: String)
@Serializable private data class DriverBookingChat(val id: String)
@Serializable private data class DriverBookingTracking(val id: String)
@Serializable private data class DriverBookingAmendment(val id: String)
@Serializable private data class DriverBookingRating(val id: String)
@Serializable private data class DriverBookingSafety(val id: String)
@Serializable private data class DriverBookingSupport(val id: String)
@Serializable private data object Wallet
@Serializable private data object DriverBonus

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
    // Stage 08: the trips, the feed and the offers live as long as the driver flow (tabs and screens share them).
    val gps = remember(container) { TrackerTripGps(container.tracker) }
    val trips: TripsViewModel = viewModel(
        key = "driver-trips-${session.user.id}",
        factory = viewModelFactory { initializer { TripsViewModel(container.api, container.banners, gps) } },
    )
    val feed: FeedViewModel = viewModel(
        key = "driver-feed-${session.user.id}",
        factory = viewModelFactory { initializer { FeedViewModel(container.api, PrefsFeedFilterStore(appContext, session.user.id)) } },
    )
    val proposals: ProposalsViewModel = viewModel(
        key = "driver-proposals-${session.user.id}",
        factory = viewModelFactory { initializer { ProposalsViewModel(container.api, container.banners) } },
    )
    // Stage 09: the bookings and the profile's numbers.
    val bookings: DriverBookingsViewModel = viewModel(
        key = "driver-bookings-${session.user.id}",
        factory = viewModelFactory { initializer { DriverBookingsViewModel(container.api) } },
    )
    val stats: DriverStatsViewModel = viewModel(
        key = "driver-stats-${session.user.id}",
        factory = viewModelFactory { initializer { DriverStatsViewModel(container.api) } },
    )
    // ADR-0027: the directions ("Yo'nalishlarim") and the requests along them.
    val directions: DirectionsViewModel = viewModel(
        key = "driver-directions-${session.user.id}",
        factory = viewModelFactory { initializer { DirectionsViewModel(container.api, container.banners) } },
    )
    val work = DriverWork(trips, feed, proposals, bookings, stats, container.tracker, directions)
    // Q148: a trip already running when the app starts publishes again without a tap where the permission is given.
    val tripList by trips.state.collectAsStateWithLifecycle()
    val running = TripRules.trackable(tripList.list)?.id
    LaunchedEffect(running) { running?.let { container.tracker.resume(it) } }
    var tab by rememberSaveable { mutableStateOf(DriverTab.HOME) }

    val signOut: () -> Unit = {
        scope.launch {
            // While the tokens still work: the queued GPS points go out and the session closes (K3), and this
            // phone stops getting this person's pushes.
            container.tracker.signOut()
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
    // Stage 09: every driver target opens (booking and its chat, offer thread, trip, wallet); a client listing
    // only marks the item read.
    val openTarget: (InboxTarget) -> Unit = { target ->
        when (target) {
            is InboxTarget.SupportThread -> nav.navigate(SupportThread(target.id))
            is InboxTarget.Proposal -> nav.navigate(ProposalThread(target.id))
            is InboxTarget.Trip -> nav.navigate(TripDetail(target.id))
            is InboxTarget.Booking -> {
                nav.navigate(DriverBooking(target.id))
                if (target.chat) nav.navigate(DriverBookingChat(target.id))
            }
            InboxTarget.Wallet -> nav.navigate(Wallet) { launchSingleTop = true }
            is InboxTarget.Listing -> Unit
        }
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
        onAddTrip = { nav.navigate(AddTrip) { launchSingleTop = true } },
        onTrip = { id -> nav.navigate(TripDetail(id)) },
        onSavedSearches = { nav.navigate(SavedSearches) { launchSingleTop = true } },
        onOffer = { item -> nav.navigate(Bid(item.listing.id)) },
        onProposals = { nav.navigate(Proposals) { launchSingleTop = true } },
        onThread = { id -> nav.navigate(ProposalThread(id)) },
        onBooking = { id -> nav.navigate(DriverBooking(id)) },
        onWallet = { nav.navigate(Wallet) { launchSingleTop = true } },
        onBonus = { nav.navigate(DriverBonus) { launchSingleTop = true } },
        onRoutes = { tab = DriverTab.ROUTES },
        onOrders = { tab = DriverTab.ORDERS },
        onAddDirection = { nav.navigate(AddDirection) { launchSingleTop = true } },
        onDirectionFeed = { id ->
            directions.select(id)
            tab = DriverTab.MATCHES
        },
        onDirectionOffer = { directionId, listingId -> nav.navigate(DirectionBid(directionId, listingId)) },
    )

    // A link from outside (cold or warm start, or kept through sign-in, a push or the GPS notification's tap): the
    // driver's screens; a referral code shows as the home row (tap = confirm); a client listing (the public page's
    // "Ilovani ochish", Stage 10) is the offer screen, which shows the Q96 gate or the "no longer open" sentence itself.
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
            is DeepLinkTarget.Listing -> nav.navigate(Bid(allowed.id)) { launchSingleTop = true }
            is DeepLinkTarget.Inbox -> {
                val event = allowed.event
                // A push tap: the inbox row of the same event carries the real link (see ClientFlow for why this is
                // not in the effect's scope).
                if (event == null) nav.navigate(Notifications) { launchSingleTop = true } else scope.launch {
                    val resolved = inbox.openLatest(event, allowed.ref)?.takeUnless { it is InboxTarget.Listing }
                    when {
                        resolved != null -> openTarget(resolved)
                        PushRules.fallsBackToThreads(event) -> nav.navigate(SupportThreads) { launchSingleTop = true }
                        else -> nav.navigate(Notifications) { launchSingleTop = true }
                    }
                }
            }
            else -> DeepLinkRules.inboxTarget(allowed)?.let(openTarget) ?: container.links.unsupported()
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
                work = work,
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
            DriverProfileFormScreen(vm = vm, onBack = { nav.popBackStack() }, onHelp = routes.onHelp)
        }
        composable<Documents> {
            val vm: DriverDocumentsViewModel = viewModel(factory = viewModelFactory {
                initializer { DriverDocumentsViewModel(container.driver, container.files, ContentDocumentSource(appContext), container.banners, driver::refresh) }
            })
            val record by driver.state.collectAsStateWithLifecycle()
            DriverDocumentsScreen(vm = vm, onBack = { nav.popBackStack() }, account = record.status)
        }
        composable<Notifications> {
            NotificationsScreen(vm = inbox, drawer = null, languageTag = locale.tag, onTarget = openTarget, onBack = { nav.popBackStack() })
        }
        composable<Help> {
            val vm: HelpViewModel = viewModel(factory = viewModelFactory { initializer { HelpViewModel(container.api) } })
            HelpScreen(vm = vm, onBack = { nav.popBackStack() }, onThreads = { nav.navigate(SupportThreads) }, onThread = { id -> nav.navigate(SupportThread(id)) }, faq = FaqSet.DRIVER)
        }
        composable<SupportThreads> {
            val vm: SupportThreadsViewModel = viewModel(factory = viewModelFactory { initializer { SupportThreadsViewModel(container.api, container.banners) } })
            SupportThreadsScreen(vm = vm, onBack = { nav.popBackStack() }, onThread = { id -> nav.navigate(SupportThread(id)) })
        }
        composable<SupportThread> { entry ->
            val id = entry.toRoute<SupportThread>().id
            val vm: SupportViewModel = viewModel(key = "support-thread-$id", factory = viewModelFactory { initializer { SupportViewModel(container.api, bookingId = null, threadId = id) } })
            SupportChatScreen(vm = vm, onBack = { nav.popBackStack() })
        }
        composable<SafetyCenter> {
            val vm: SafetyCenterViewModel = viewModel(factory = viewModelFactory { initializer { SafetyCenterViewModel(container.api, container.banners) } })
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
                banners = container.banners,
            )
        }
        composable<AddTrip> {
            val vm: AddTripViewModel = viewModel(factory = viewModelFactory { initializer { AddTripViewModel(container.api, container.banners) } })
            AddTripScreen(vm = vm, onBack = { nav.popBackStack() }, onCreated = { id ->
                trips.refresh()
                nav.navigate(TripDetail(id)) { popUpTo<AddTrip> { inclusive = true } }
            })
        }
        composable<AddDirection> {
            val vm: AddDirectionViewModel = viewModel(factory = viewModelFactory {
                initializer { AddDirectionViewModel(container.api, container.banners) { driver.state.value.vehicles } }
            })
            AddDirectionScreen(vm = vm, onBack = { nav.popBackStack() }, onCreated = { created ->
                directions.added(created)
                nav.popBackStack()
            })
        }
        composable<DirectionBid> { entry ->
            val route = entry.toRoute<DirectionBid>()
            val vm: DirectionBidViewModel = viewModel(key = "direction-bid-${route.directionId}-${route.listingId}", factory = viewModelFactory {
                initializer {
                    DirectionBidViewModel(container.api, container.banners, route.directionId, directions.item(route.listingId), proposals) {
                        directions.refresh()
                        trips.refresh()
                    }
                }
            })
            DirectionBidScreen(
                vm = vm, driver = driver, nav = routes,
                onBack = { nav.popBackStack() },
                onThread = { threadId -> nav.navigate(ProposalThread(threadId)) { popUpTo<DirectionBid> { inclusive = true } } },
            )
        }
        composable<TripDetail> { entry ->
            val id = entry.toRoute<TripDetail>().id
            val vm: TripDetailViewModel = viewModel(key = "trip-$id", factory = viewModelFactory { initializer { TripDetailViewModel(container.api, container.banners, id, trips::refresh, gps, liveTrips = { trips.state.value.list }) } })
            TripDetailScreen(
                vm = vm,
                onBack = { nav.popBackStack() },
                tracker = container.tracker,
                direction = tripList.direction(id),
                // The manifest's "Xabarlar": the booking's chat, over its detail (back = the booking).
                onBooking = { bookingId ->
                    nav.navigate(DriverBooking(bookingId))
                    nav.navigate(DriverBookingChat(bookingId))
                },
            )
        }
        composable<SavedSearches> {
            val vm: SavedSearchesViewModel = viewModel(factory = viewModelFactory { initializer { SavedSearchesViewModel(container.api, container.banners, feed) } })
            // "Lentada ochish" (design 07 §6.5): back to the feed, which now shows the saved direction.
            SavedSearchesScreen(vm = vm, feed = feed, onBack = { nav.popBackStack() }, onOpenedInFeed = {
                nav.popBackStack<Tabs>(inclusive = false)
                tab = DriverTab.MATCHES
            })
        }
        composable<Bid> { entry ->
            val id = entry.toRoute<Bid>().listingId
            val vm: BidViewModel = viewModel(key = "bid-$id", factory = viewModelFactory { initializer { BidViewModel(container.api, container.banners, id, feed.item(id), trips, proposals) } })
            BidScreen(
                vm = vm, trips = trips, driver = driver, nav = routes,
                onBack = { nav.popBackStack() },
                onAddTrip = { nav.navigate(AddTrip) { launchSingleTop = true } },
                onThread = { threadId -> nav.navigate(ProposalThread(threadId)) { popUpTo<Bid> { inclusive = true } } },
            )
        }
        composable<Proposals> {
            ProposalsScreen(vm = proposals, onBack = { nav.popBackStack() }, onThread = { id -> nav.navigate(ProposalThread(id)) })
        }
        composable<ProposalThread> { entry ->
            val id = entry.toRoute<ProposalThread>().id
            val vm: ProposalThreadViewModel = viewModel(key = "thread-$id", factory = viewModelFactory { initializer { ProposalThreadViewModel(container.api, container.banners, id, proposals) } })
            ProposalThreadScreen(
                vm = vm, onBack = { nav.popBackStack() }, onBooking = { bookingId -> nav.navigate(DriverBooking(bookingId)) },
                // Q100 / design 07 §8.7: after the accept, straight into the booking's chat (back = the booking).
                onBookingChat = { bookingId ->
                    nav.navigate(DriverBooking(bookingId)) { popUpTo<ProposalThread> { inclusive = true } }
                    nav.navigate(DriverBookingChat(bookingId))
                },
            )
        }
        composable<DriverBooking> { entry ->
            val id = entry.toRoute<DriverBooking>().id
            DriverBookingDetailScreen(
                vm = driverBookingViewModel(entry, id, container),
                tracker = container.tracker,
                onBack = { nav.popBackStack() },
                nav = DriverBookingNav(
                    onChat = { nav.navigate(DriverBookingChat(id)) },
                    onTracking = { nav.navigate(DriverBookingTracking(id)) },
                    onAmend = { nav.navigate(DriverBookingAmendment(id)) },
                    onRate = { nav.navigate(DriverBookingRating(id)) },
                    onSupport = { nav.navigate(DriverBookingSupport(id)) },
                    onSafety = { nav.navigate(DriverBookingSafety(id)) },
                    onTrip = { tripId -> nav.navigate(TripDetail(tripId)) },
                ),
            )
        }
        composable<DriverBookingAmendment> { entry ->
            val owner = remember(entry) { nav.getBackStackEntry<DriverBooking>() }
            AmendmentScreen(vm = driverBookingViewModel(owner, entry.toRoute<DriverBookingAmendment>().id, container), onBack = { nav.popBackStack() })
        }
        composable<DriverBookingRating> { entry ->
            val owner = remember(entry) { nav.getBackStackEntry<DriverBooking>() }
            RatingScreen(vm = driverBookingViewModel(owner, entry.toRoute<DriverBookingRating>().id, container), onBack = { nav.popBackStack() }, onDone = { nav.popBackStack() })
        }
        composable<DriverBookingSafety> { entry ->
            val owner = remember(entry) { nav.getBackStackEntry<DriverBooking>() }
            SafetyScreen(vm = driverBookingViewModel(owner, entry.toRoute<DriverBookingSafety>().id, container), onBack = { nav.popBackStack() })
        }
        composable<DriverBookingChat> { entry ->
            val id = entry.toRoute<DriverBookingChat>().id
            val vm: BookingChatViewModel = viewModel(key = "driver-booking-chat-$id", factory = viewModelFactory { initializer { BookingChatViewModel(container.api, id) } })
            // The GPS bar on top while this booking's trip runs (the detail below in the back stack knows the status).
            val detail = remember(entry) { runCatching { nav.getBackStackEntry<DriverBooking>() }.getOrNull() }
            val gpsTrip = detail?.let { driverBookingViewModel(it, id, container).state.collectAsStateWithLifecycle().value.value }
                ?.let { DriverBookingRules.gpsTripId(it.serviceStatus, it.tripId) }
            BookingChatScreen(vm = vm, onBack = { nav.popBackStack() }, side = BookingSide.DRIVER, top = gpsTrip?.let { trip -> { DriverTrackingBar(container.tracker, trip) } })
        }
        composable<DriverBookingSupport> { entry ->
            val id = entry.toRoute<DriverBookingSupport>().id
            val vm: SupportViewModel = viewModel(key = "driver-booking-support-$id", factory = viewModelFactory { initializer { SupportViewModel(container.api, bookingId = id) } })
            SupportChatScreen(vm = vm, onBack = { nav.popBackStack() })
        }
        composable<DriverBookingTracking> { entry ->
            val id = entry.toRoute<DriverBookingTracking>().id
            val vm: TrackingViewModel = viewModel(
                key = "driver-booking-tracking-$id",
                factory = viewModelFactory {
                    initializer { TrackingViewModel(container.api, id, container.liveSockets, container.trackingSocketUrl) { container.sessions.current()?.accessToken } }
                },
            )
            BookingTrackingScreen(vm = vm, onBack = { nav.popBackStack() })
        }
        composable<Wallet> {
            val vm: WalletViewModel = viewModel(factory = viewModelFactory { initializer { WalletViewModel(container.api, container.banners, driver::refresh) } })
            WalletScreen(vm = vm, onBack = { nav.popBackStack() }, onHelp = { nav.navigate(Help) })
        }
        composable<DriverBonus> {
            val vm: BonusViewModel = viewModel(factory = viewModelFactory { initializer { BonusViewModel(container.api, container.referral, BonusViewModel.DRIVER_AUDIENCE, container.banners) } })
            BonusScreen(vm = vm, onBack = { nav.popBackStack() })
        }
        composable<AccountDelete> {
            val vm: AccountDeleteViewModel = viewModel(factory = viewModelFactory { initializer { AccountDeleteViewModel(container.api, container.push::unregister) { container.appScope.launch { container.push.sync() } } } })
            AccountDeleteScreen(vm = vm, onBack = { nav.popBackStack() }, onDeleted = accountDeleted, onOrders = {
                nav.popBackStack<Tabs>(inclusive = false)
                tab = DriverTab.ORDERS
            })
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
    val onAddTrip: () -> Unit = {},
    val onTrip: (String) -> Unit = {},
    val onSavedSearches: () -> Unit = {},
    val onOffer: (uz.elchi.app.api.generated.FeedItemDTO) -> Unit = {},
    val onProposals: () -> Unit = {},
    val onThread: (String) -> Unit = {},
    val onBooking: (String) -> Unit = {},
    val onWallet: () -> Unit = {},
    val onBonus: () -> Unit = {},
    val onRoutes: () -> Unit = {},
    val onOrders: () -> Unit = {},
    /** ADR-0027: the direction form, a direction's requests on the Moslar tab, and an offer from a direction. */
    val onAddDirection: () -> Unit = {},
    val onDirectionFeed: (String) -> Unit = {},
    val onDirectionOffer: (directionId: String, listingId: String) -> Unit = { _, _ -> },
)

/** A driver booking's model lives on its detail entry; the amendment, rating, safety and chat screens borrow it. */
@Composable
private fun driverBookingViewModel(owner: NavBackStackEntry, id: String, container: AppContainer): BookingViewModel =
    viewModel(
        viewModelStoreOwner = owner,
        key = "driver-booking-$id",
        factory = viewModelFactory {
            initializer { BookingViewModel(container.api, container.files, container.apiBase, id, side = BookingSide.DRIVER) }
        },
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
