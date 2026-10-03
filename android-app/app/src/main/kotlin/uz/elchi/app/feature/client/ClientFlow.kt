package uz.elchi.app.feature.client

import android.widget.Toast
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.createSavedStateHandle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.navigation.NavBackStackEntry
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.toRoute
import kotlinx.coroutines.launch
import kotlinx.serialization.Serializable
import uz.elchi.app.AppContainer
import uz.elchi.app.R
import uz.elchi.app.deeplink.DeepLinkRules
import uz.elchi.app.deeplink.DeepLinkTarget
import uz.elchi.app.i18n.AppLocale
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.withLocale
import uz.elchi.app.push.AskNotificationsOnce
import uz.elchi.app.push.PushRules
import uz.elchi.app.session.Session
import uz.elchi.app.ui.components.SystemBarIcons
import uz.elchi.app.ui.components.TitleBar
import uz.elchi.app.ui.theme.Elchi

@Serializable private data object Home
@Serializable private data class PickRegion(val end: String)
@Serializable private data class PickDistrict(val end: String, val regionId: String)
@Serializable private data class PickPoint(val end: String, val regionId: String, val districtId: String)
/** [editing]: opened from the review's pencil - the button saves and goes back to the review. */
@Serializable private data class RouteSummary(val editing: Boolean = false)
@Serializable private data class OrderContact(val editing: Boolean = false)
@Serializable private data object OrderReview
@Serializable private data object OrderSuccess
@Serializable private data object Orders
@Serializable private data object Proposals
/** [offers]: opened for an offer (a notification, a push) - the detail starts at its inline "Haydovchi takliflari". */
@Serializable private data class ListingDetail(val id: String, val offers: Boolean = false)
@Serializable private data class ListingEdit(val id: String)
@Serializable private data class BookingDetail(val id: String, val accepted: Boolean = false)
@Serializable private data class BookingChat(val id: String)
@Serializable private data class BookingTracking(val id: String)
@Serializable private data class BookingAmendment(val id: String)
@Serializable private data class BookingRating(val id: String)
@Serializable private data class BookingSafety(val id: String)
@Serializable private data class BookingSupport(val id: String)
@Serializable private data object Notifications
/** The same list pushed from the orders bell (design `notif` with a back button), not the drawer's root. */
@Serializable private data object NotificationsPushed
@Serializable private data object Profile
@Serializable private data object Bonus
@Serializable private data object SafetyCenter
@Serializable private data object Help
@Serializable private data object SupportThreads
@Serializable private data class SupportThread(val id: String)
@Serializable private data object Settings
@Serializable private data object AccountDelete
@Serializable private data class LegacyDetail(val id: Long)
@Serializable private data class LegacyBids(val id: Long)
@Serializable private data class LegacyRating(val id: Long)
@Serializable private data class LegacyDispute(val id: Long)

/**
 * Signed in as a client. Stage 02 (design "Buyurtma yaratish"): home (map + sheet) -> place picker (region ->
 * district -> point); Pochta: route (1/3) -> contact (2/3) -> review (3/3); Taksi: the whole request on the home
 * sheet -> review (1/1); then success. A review row's pencil opens its step in edit mode ("Saqlash va qaytish"). The draft lives in [ParcelRequestViewModel], one per signed-in person,
 * so it survives moving between the steps and a process restart. Stage 03: orders (drawer, success screen) ->
 * a listing's detail -> edit / driver offers -> accept, and "Takliflarim"; one [ListingViewModel] per opened
 * listing, scoped to its detail screen and shared with the screens opened from it. Stage 04: a booking's detail
 * (from the orders list, and right after an accept) -> chat, tracking, support chat, amendment, rating, safety; one
 * [BookingViewModel] per opened booking, shared the same way, and a model of its own for each polling screen.
 * Stage 05: the drawer's notifications (with the unread dot, [InboxViewModel], one per person), profile, help,
 * settings; from the profile the bonus screen, the operator conversations and the safety centre; account deletion.
 * Stage 06: a v1 order from the orders list (Q4, an archive) -> its bids, rating and problem report; one
 * [LegacyOrderViewModel] per opened order, on its detail entry, shared the same way. Outcomes show in the app banner.
 */
@Composable
fun ClientFlow(container: AppContainer, session: Session) {
    val nav = rememberNavController()
    val locale by container.locale.state.collectAsStateWithLifecycle()
    val ru = locale == AppLocale.RU
    val appContext = LocalContext.current.applicationContext
    val scope = rememberCoroutineScope()
    // Keyed by the person: another client signing in on this phone never sees the previous draft.
    val request: ParcelRequestViewModel = viewModel(
        key = "parcel-request-${session.user.id}",
        factory = viewModelFactory {
            initializer { ParcelRequestViewModel(container.api, container.files, container.geo, PhotoCompressor(appContext), createSavedStateHandle()) }
        },
    )
    val places: PlacePickerViewModel = viewModel(
        key = "place-picker-${session.user.id}",
        factory = viewModelFactory { initializer { PlacePickerViewModel(container.api, container.geo) { container.locale.state.value.tag } } },
    )
    val orders: OrdersViewModel = viewModel(
        key = "client-orders-${session.user.id}",
        factory = viewModelFactory { initializer { OrdersViewModel(container.api, container.legacyOrders) } },
    )
    val inbox: InboxViewModel = viewModel(
        key = "inbox-${session.user.id}",
        factory = viewModelFactory { initializer { InboxViewModel(container.api) } },
    )
    val inboxState by inbox.state.collectAsStateWithLifecycle()
    LaunchedEffect(session.user.id) { request.prefillSender(session.user.fullName, session.user.phone) }
    val toOrders: () -> Unit = { nav.navigate(Orders) { popUpTo<Home> { inclusive = false } } }
    val backToOrders: () -> Unit = { if (!nav.popBackStack<Orders>(inclusive = false)) toOrders() }
    // Q100: an accept lands on the new booking and opens its chat; back leads to the booking, then to the orders
    // list (which already shows the booking on top).
    val accepted: (Accepted) -> Unit = { result ->
        val booking = result.booking
        if (booking == null) {
            orders.show(OrdersNotice.DRIVER_CHOSEN)
            backToOrders()
        } else {
            orders.addBooking(booking)
            toOrders()
            nav.navigate(BookingDetail(booking.id, accepted = true))
            nav.navigate(BookingChat(booking.id))
        }
    }

    // Contacts and the photo reference stay on this phone only as long as the person is signed in.
    val forget: () -> Unit = {
        request.startOver()
        places.closePoint()
    }
    val signOut: () -> Unit = {
        forget()
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
        // The server already revoked every token of this account: nothing to call, only forget it here.
        forget()
        container.push.dropToken()
        container.sessions.clear()
        Toast.makeText(appContext, deletedText, Toast.LENGTH_LONG).show()
    }
    // v1 stores the cancel reason as text; like the web client it is the Uzbek sentence whatever the app language.
    val legacyCancelReason = remember(appContext) { appContext.withLocale(AppLocale.UZ).getString(R.string.client_legacy_cancelReason) }
    val toOrdersTop: () -> Unit = { nav.navigate(Orders) { popUpTo<Home> { inclusive = false }; launchSingleTop = true } }
    val drawer = DrawerNav(
        session = session,
        unread = inboxState.unread,
        unreadMore = inboxState.unreadMore,
        onHome = { nav.popBackStack<Home>(inclusive = false) },
        onOrders = toOrdersTop,
        onNotifications = { nav.navigate(Notifications) { popUpTo<Home> { inclusive = false }; launchSingleTop = true } },
        onProposals = { nav.navigate(Proposals) { launchSingleTop = true } },
        onProfile = { nav.navigate(Profile) { launchSingleTop = true } },
        onHelp = { nav.navigate(Help) { launchSingleTop = true } },
        onSettings = { nav.navigate(Settings) { launchSingleTop = true } },
        onSignOut = signOut,
        onOpened = inbox::refreshUnread,
    )
    // Where an inbox item leads; a link this app has no screen for (a trip) only marks it read.
    val openTarget: (InboxTarget) -> Unit = { target ->
        when (target) {
            is InboxTarget.Booking -> {
                nav.navigate(BookingDetail(target.id))
                if (target.chat) nav.navigate(BookingChat(target.id))
            }
            is InboxTarget.Listing -> nav.navigate(ListingDetail(target.id))
            // An offer opens its listing at the inline board (§0: the bids screen is now part of the detail).
            is InboxTarget.Proposal -> target.listingId?.let { nav.navigate(ListingDetail(it, offers = true)) } ?: nav.navigate(Proposals) { launchSingleTop = true }
            is InboxTarget.SupportThread -> nav.navigate(SupportThread(target.id))
            is InboxTarget.Trip, InboxTarget.Wallet -> Unit
        }
    }

    val debugLegacy by container.debugLegacyOrder.collectAsStateWithLifecycle()
    LaunchedEffect(debugLegacy) {
        debugLegacy?.let { id ->
            container.debugLegacyOrder.value = null
            nav.navigate(LegacyDetail(id))
        }
    }

    // A link from outside (cold or warm start, or one kept through sign-in): the inbox's screens; a referral code
    // opens the bonus screen with the code already in the entry field.
    val link by container.links.target.collectAsStateWithLifecycle()
    LaunchedEffect(link) {
        val target = link ?: return@LaunchedEffect
        if (!container.links.take(target)) return@LaunchedEffect
        when (val allowed = DeepLinkRules.forRole(target, session.user.mobileRole)) {
            is DeepLinkTarget.Referral -> nav.navigate(Bonus) { launchSingleTop = true }
            is DeepLinkTarget.Inbox -> {
                val toInbox = { nav.navigate(Notifications) { popUpTo<Home> { inclusive = false }; launchSingleTop = true } }
                val event = allowed.event
                // A push tap: the inbox row of the same event carries the real link (not in this effect's scope:
                // taking the link restarts the effect and would cancel the read).
                if (event == null) toInbox() else scope.launch {
                    val resolved = inbox.openLatest(event, allowed.ref)?.takeUnless { it is InboxTarget.Trip || it is InboxTarget.Wallet }
                    when {
                        resolved != null -> openTarget(resolved)
                        PushRules.fallsBackToThreads(event) -> nav.navigate(SupportThreads) { launchSingleTop = true }
                        else -> toInbox()
                    }
                }
            }
            DeepLinkTarget.SupportThreads -> nav.navigate(SupportThreads) { launchSingleTop = true }
            // Stage 10 (the public page's "Ilovani ochish"): only the owner has a screen for a listing; for anybody
            // else the server answers with the public DTO and the link "cannot be opened". A failed read opens the
            // detail anyway - it says why and retries. Not in this effect's scope (taking the link restarts it).
            is DeepLinkTarget.Listing -> scope.launch {
                val own = runCatching { DeepLinkRules.ownsListing(container.api.getListing(allowed.id).data) }.getOrNull()
                if (own == false) container.links.unsupported() else openTarget(InboxTarget.Listing(allowed.id))
            }
            else -> DeepLinkRules.inboxTarget(allowed)?.let(openTarget) ?: container.links.unsupported()
        }
    }
    val pendingReferral by container.referral.pending.collectAsStateWithLifecycle()
    // The home's referral row was closed (design: hidden for the session; the code itself stays kept).
    var referralHidden by rememberSaveable { mutableStateOf(false) }
    val toast = remember { FlowToast() }
    val account = session.user.fullName.orEmpty().trim() to ParcelRules.localDigits(session.user.phone)
    val pickedPickup = t(R.string.client_order_pointChosenPickup)
    val pickedDropoff = t(R.string.client_order_pointChosenDropoff)
    val currentLocation = t(R.string.home_currentLocation)
    // A push arrived (the notification is already shown, also in the foreground): the unread dot, and the open list.
    LaunchedEffect(inbox) {
        container.push.received.collect { if (inbox.state.value.loaded) inbox.refresh() else inbox.refreshUnread() }
    }

    CompositionLocalProvider(LocalFlowToast provides toast) {
    Box(Modifier.fillMaxSize()) {
    NavHost(nav, startDestination = Home) {
        composable<Home> {
            AskNotificationsOnce(container.push)
            ClientHomeScreen(
                vm = request,
                session = session,
                ru = ru,
                language = locale.tag,
                onPick = { end -> nav.navigate(PickRegion(end.name)) },
                onParcelForm = { nav.navigate(RouteSummary()) },
                onTaxiReview = { nav.navigate(OrderReview) { launchSingleTop = true } },
                drawer = drawer,
                referralCode = pendingReferral?.takeUnless { referralHidden },
                onReferral = { nav.navigate(Bonus) { launchSingleTop = true } },
                onReferralHide = { referralHidden = true },
            )
        }
        composable<PickRegion> { entry ->
            val route = entry.toRoute<PickRegion>()
            val end = End.valueOf(route.end)
            RegionScreen(
                vm = places,
                end = end,
                ru = ru,
                onBack = { nav.popBackStack() },
                onRegion = { region ->
                    places.pickRegion(region) { districtId ->
                        if (districtId != null) nav.navigate(PickPoint(route.end, region.id, districtId))
                        else nav.navigate(PickDistrict(route.end, region.id))
                    }
                },
            )
        }
        composable<PickDistrict> { entry ->
            val route = entry.toRoute<PickDistrict>()
            DistrictScreen(
                vm = places,
                regionId = route.regionId,
                ru = ru,
                onBack = { nav.popBackStack() },
                onDistrict = { district -> nav.navigate(PickPoint(route.end, route.regionId, district.id)) },
            )
        }
        composable<PickPoint> { entry ->
            val route = entry.toRoute<PickPoint>()
            val end = End.valueOf(route.end)
            PointPickerScreen(
                vm = places,
                end = end,
                regionId = route.regionId,
                districtId = route.districtId,
                existing = request.state.collectAsStateWithLifecycle().value.draft.end(end),
                ru = ru,
                onBack = {
                    places.closePoint()
                    nav.popBackStack()
                },
                onConfirm = { place ->
                    request.setEnd(end, place)
                    places.closePoint()
                    val name = if (place.current) currentLocation else place.label(ru)
                    toast.show((if (end == End.ORIGIN) pickedPickup else pickedDropoff).replace("{place}", name))
                    // Back to wherever the picker was opened from (home, or the route step's "O'zgartirish").
                    nav.popBackStack<PickRegion>(inclusive = true)
                },
            )
        }
        composable<RouteSummary> { entry ->
            val editing = entry.toRoute<RouteSummary>().editing
            RouteSummaryScreen(
                vm = request,
                ru = ru,
                editing = editing,
                onBack = { nav.popBackStack() },
                onChange = { end -> nav.navigate(PickRegion(end.name)) },
                onSave = { if (editing) nav.popBackStack() else nav.navigate(OrderContact()) },
            )
        }
        composable<OrderContact> { entry ->
            val editing = entry.toRoute<OrderContact>().editing
            OrderContactScreen(
                vm = request,
                ru = ru,
                editing = editing,
                account = account,
                onBack = { nav.popBackStack() },
                onNext = { if (editing) nav.popBackStack() else nav.navigate(OrderReview) },
            )
        }
        composable<OrderReview> {
            OrderReviewScreen(
                vm = request,
                ru = ru,
                account = account,
                onBack = { nav.popBackStack() },
                onEdit = { target ->
                    when {
                        // Taksi: everything is on the home sheet; it comes back here with "Saqlash va qaytish".
                        request.state.value.draft.taxi -> {
                            request.setEditingHome(true)
                            nav.popBackStack<Home>(inclusive = false)
                        }
                        target == EditTarget.CONTACT -> nav.navigate(OrderContact(editing = true))
                        else -> nav.navigate(RouteSummary(editing = true))
                    }
                },
                onPublished = { nav.navigate(OrderSuccess) { popUpTo<Home> { inclusive = false } } },
            )
        }
        composable<OrderSuccess> {
            OrderSuccessScreen(
                vm = request,
                ru = ru,
                onDone = {
                    request.startOver()
                    request.prefillSender(session.user.fullName, session.user.phone)
                    toOrders()
                },
                // A clean draft in the same service, back on the home.
                onNewOrder = {
                    request.startOver()
                    request.prefillSender(session.user.fullName, session.user.phone)
                    nav.popBackStack<Home>(inclusive = false)
                },
            )
        }
        composable<Orders> {
            ClientOrdersScreen(
                vm = orders,
                ru = ru,
                languageTag = locale.tag,
                onHome = { nav.popBackStack<Home>(inclusive = false) },
                onListing = { id -> nav.navigate(ListingDetail(id)) },
                onBooking = { id -> nav.navigate(BookingDetail(id)) },
                onLegacy = { id -> nav.navigate(LegacyDetail(id)) },
                onNotifications = { nav.navigate(NotificationsPushed) { launchSingleTop = true } },
                drawer = drawer,
            )
        }
        composable<LegacyDetail> { entry ->
            val vm = legacyViewModel(entry, entry.toRoute<LegacyDetail>().id, container, legacyCancelReason)
            LegacyDetailScreen(
                vm = vm,
                languageTag = locale.tag,
                onBack = { nav.popBackStack() },
                onBids = { nav.navigate(LegacyBids(vm.orderId)) },
                onRate = { nav.navigate(LegacyRating(vm.orderId)) },
                onDispute = { nav.navigate(LegacyDispute(vm.orderId)) },
                // The list reads itself again when it comes back into view.
                onCancelled = backToOrders,
            )
        }
        composable<LegacyBids> { entry ->
            val owner = remember(entry) { nav.getBackStackEntry<LegacyDetail>() }
            val vm = legacyViewModel(owner, entry.toRoute<LegacyBids>().id, container, legacyCancelReason)
            LegacyBidsScreen(vm = vm, languageTag = locale.tag, onBack = { nav.popBackStack() }, onSelected = { nav.popBackStack() })
        }
        composable<LegacyRating> { entry ->
            val owner = remember(entry) { nav.getBackStackEntry<LegacyDetail>() }
            val vm = legacyViewModel(owner, entry.toRoute<LegacyRating>().id, container, legacyCancelReason)
            LegacyRatingScreen(vm = vm, onBack = { nav.popBackStack() }, onDone = { nav.popBackStack() })
        }
        composable<LegacyDispute> { entry ->
            val owner = remember(entry) { nav.getBackStackEntry<LegacyDetail>() }
            val vm = legacyViewModel(owner, entry.toRoute<LegacyDispute>().id, container, legacyCancelReason)
            LegacyDisputeScreen(vm = vm, onBack = { nav.popBackStack() }, onDone = { nav.popBackStack() })
        }
        composable<Proposals> {
            ProposalsScreen(vm = orders, ru = ru, onBack = { nav.popBackStack() }, onAccepted = accepted)
        }
        composable<ListingDetail> { entry ->
            val route = entry.toRoute<ListingDetail>()
            val vm = listingViewModel(entry, route.id, container)
            ListingDetailScreen(
                vm = vm,
                ru = ru,
                languageTag = locale.tag,
                onBack = { nav.popBackStack() },
                onEdit = { nav.navigate(ListingEdit(vm.listingId)) },
                onCancelled = {
                    orders.show(OrdersNotice.LISTING_CANCELLED)
                    backToOrders()
                },
                onAccepted = accepted,
                scrollToOffers = route.offers,
            )
        }
        composable<ListingEdit> { entry ->
            val owner = remember(entry) { nav.getBackStackEntry<ListingDetail>() }
            val vm = listingViewModel(owner, entry.toRoute<ListingEdit>().id, container)
            ListingEditScreen(vm = vm, onBack = { nav.popBackStack() }, onSaved = { nav.popBackStack() })
        }
        composable<BookingDetail> { entry ->
            val route = entry.toRoute<BookingDetail>()
            val vm = bookingViewModel(entry, route.id, container)
            // Once per landing: the accept that made this booking is said on the detail screen, not on the list.
            LaunchedEffect(route.id) {
                if (route.accepted && !entry.savedStateHandle.contains(SHOWN)) {
                    entry.savedStateHandle[SHOWN] = true
                    vm.show(BookingNotice.DRIVER_CHOSEN)
                }
            }
            BookingDetailScreen(
                vm = vm,
                ru = ru,
                languageTag = locale.tag,
                onBack = { nav.popBackStack() },
                onChat = { nav.navigate(BookingChat(route.id)) },
                onTracking = { nav.navigate(BookingTracking(route.id)) },
                onAmend = { nav.navigate(BookingAmendment(route.id)) },
                onRate = { stars ->
                    vm.startRating(stars)
                    nav.navigate(BookingRating(route.id))
                },
                onSupport = { nav.navigate(BookingSupport(route.id)) },
                onSafety = { nav.navigate(BookingSafety(route.id)) },
            )
        }
        composable<BookingAmendment> { entry ->
            val owner = remember(entry) { nav.getBackStackEntry<BookingDetail>() }
            AmendmentScreen(vm = bookingViewModel(owner, entry.toRoute<BookingAmendment>().id, container), onBack = { nav.popBackStack() })
        }
        composable<BookingRating> { entry ->
            val owner = remember(entry) { nav.getBackStackEntry<BookingDetail>() }
            RatingScreen(vm = bookingViewModel(owner, entry.toRoute<BookingRating>().id, container), onBack = { nav.popBackStack() }, onDone = { nav.popBackStack() })
        }
        composable<BookingSafety> { entry ->
            val owner = remember(entry) { nav.getBackStackEntry<BookingDetail>() }
            SafetyScreen(vm = bookingViewModel(owner, entry.toRoute<BookingSafety>().id, container), onBack = { nav.popBackStack() })
        }
        composable<BookingChat> { entry ->
            val id = entry.toRoute<BookingChat>().id
            val vm: BookingChatViewModel = viewModel(key = "booking-chat-$id", factory = viewModelFactory { initializer { BookingChatViewModel(container.api, id) } })
            BookingChatScreen(vm = vm, onBack = { nav.popBackStack() })
        }
        composable<BookingSupport> { entry ->
            val id = entry.toRoute<BookingSupport>().id
            val vm: SupportViewModel = viewModel(key = "booking-support-$id", factory = viewModelFactory { initializer { SupportViewModel(container.api, bookingId = id) } })
            SupportChatScreen(vm = vm, onBack = { nav.popBackStack() })
        }
        composable<Notifications> {
            NotificationsScreen(vm = inbox, drawer = drawer, languageTag = locale.tag, onTarget = openTarget)
        }
        composable<NotificationsPushed> {
            NotificationsScreen(vm = inbox, drawer = null, languageTag = locale.tag, onTarget = openTarget, onBack = { nav.popBackStack() })
        }
        composable<Profile> {
            val vm: ProfileViewModel = viewModel(factory = viewModelFactory {
                initializer { ProfileViewModel(container.api, container.account, container.auth, container.sessions) }
            })
            ProfileScreen(
                vm = vm,
                session = session,
                onBack = { nav.popBackStack() },
                nav = ProfileNav(
                    onOrders = toOrdersTop,
                    onProposals = { nav.navigate(Proposals) },
                    onBonus = { nav.navigate(Bonus) },
                    onNotifications = drawer.onNotifications,
                    onThreads = { nav.navigate(SupportThreads) },
                    onSafety = { nav.navigate(SafetyCenter) },
                    onHelp = { nav.navigate(Help) },
                    onSettings = { nav.navigate(Settings) },
                    onHome = { nav.popBackStack<Home>(inclusive = false) },
                    onSignOut = signOut,
                ),
            )
        }
        composable<Bonus> {
            val vm: BonusViewModel = viewModel(factory = viewModelFactory { initializer { BonusViewModel(container.api, container.referral) } })
            BonusScreen(vm = vm, onBack = { nav.popBackStack() })
        }
        composable<SafetyCenter> {
            val vm: SafetyCenterViewModel = viewModel(factory = viewModelFactory { initializer { SafetyCenterViewModel(container.api) } })
            SafetyCenterScreen(vm = vm, onBack = { nav.popBackStack() })
        }
        composable<Help> {
            val vm: HelpViewModel = viewModel(factory = viewModelFactory { initializer { HelpViewModel(container.api) } })
            HelpScreen(vm = vm, onBack = { nav.popBackStack() }, onThreads = { nav.navigate(SupportThreads) })
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
        composable<BookingTracking> { entry ->
            val id = entry.toRoute<BookingTracking>().id
            val vm: TrackingViewModel = viewModel(
                key = "booking-tracking-$id",
                factory = viewModelFactory {
                    initializer { TrackingViewModel(container.api, id, container.liveSockets, container.trackingSocketUrl) { container.sessions.current()?.accessToken } }
                },
            )
            BookingTrackingScreen(vm = vm, onBack = { nav.popBackStack() })
        }
    }
    FlowToastHost(toast, Modifier.statusBarsPadding().padding(start = 16.dp, end = 16.dp, top = 8.dp))
    }
    }
}

private const val SHOWN = "accepted-shown"

/** The booking's model lives on its detail screen's back-stack entry; the screens opened from it borrow that store. */
@Composable
private fun bookingViewModel(owner: NavBackStackEntry, id: String, container: AppContainer): BookingViewModel =
    viewModel(
        viewModelStoreOwner = owner,
        key = "booking-$id",
        factory = viewModelFactory { initializer { BookingViewModel(container.api, container.files, container.apiBase, id) } },
    )

/** A v1 order's model lives on its detail screen's back-stack entry; bids, rating and dispute borrow that store. */
@Composable
private fun legacyViewModel(owner: NavBackStackEntry, id: Long, container: AppContainer, cancelReason: String): LegacyOrderViewModel =
    viewModel(
        viewModelStoreOwner = owner,
        key = "legacy-$id",
        factory = viewModelFactory {
            initializer { LegacyOrderViewModel(container.legacyOrders, container.files, container.banners, container.legacyRated, id, cancelReason) }
        },
    )

/** The listing's model lives on its detail screen's back-stack entry; edit and bids borrow that entry's store. */
@Composable
private fun listingViewModel(owner: NavBackStackEntry, id: String, container: AppContainer): ListingViewModel =
    viewModel(
        viewModelStoreOwner = owner,
        key = "listing-$id",
        factory = viewModelFactory { initializer { ListingViewModel(container.api, container.files, id) } },
    )

/**
 * Skeleton of the non-map steps: title bar, scrolling body, footer pinned above the keyboard on the prototype's
 * white strip with a hairline.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun StepScaffold(
    title: String,
    onBack: (() -> Unit)?,
    right: String? = null,
    onRight: (() -> Unit)? = null,
    /** Full-width strips under the title bar that stay put while the body scrolls (the outcome of a command). */
    banner: (@Composable ColumnScope.() -> Unit)? = null,
    footer: (@Composable ColumnScope.() -> Unit)? = null,
    /** Set = pull to refresh on the body ([refreshing] shows the indicator). */
    onRefresh: (() -> Unit)? = null,
    refreshing: Boolean = false,
    /** The order form's "n / total" pill on the right of the title, and the progress bar under it. */
    step: Pair<Int, Int>? = null,
    /** The body's scroll, when the screen moves it (back to the top to show its error list). */
    scrollState: ScrollState? = null,
    /** Round icon buttons at the right of the title bar (share, edit, refresh). */
    actions: (@Composable () -> Unit)? = null,
    /** The footer floats on the page colour without the white strip (the booking detail's driver bar). */
    footerOnPage: Boolean = false,
    body: @Composable ColumnScope.() -> Unit,
) {
    val c = Elchi.colors
    SystemBarIcons(dark = !c.isDark)
    Column(Modifier.fillMaxSize().background(c.page).imePadding()) {
        Column(Modifier.statusBarsPadding()) {
            TitleBar(onBack, t(R.string.common_back), title, right = right, onRight = onRight, trailing = step?.let { (n, total) -> { StepPill(n, total) } } ?: actions)
            if (step != null) StepProgress(step.first, step.second)
            banner?.invoke(this)
        }
        val bodyScroll = scrollState ?: rememberScrollState()
        val scroll: @Composable (Modifier) -> Unit = { modifier ->
            Column(
                modifier.verticalScroll(bodyScroll).padding(horizontal = 16.dp).padding(top = 6.dp, bottom = 18.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
                content = body,
            )
        }
        if (onRefresh != null) {
            PullToRefreshBox(isRefreshing = refreshing, onRefresh = onRefresh, modifier = Modifier.weight(1f).fillMaxWidth()) { scroll(Modifier.fillMaxSize()) }
        } else {
            scroll(Modifier.weight(1f))
        }
        if (footer != null) {
            Column(Modifier.fillMaxWidth().background(if (footerOnPage) c.page else c.card)) {
                if (!footerOnPage) Box(Modifier.fillMaxWidth().height(1.dp).background(c.line))
                Column(
                    Modifier.navigationBarsPadding().padding(start = if (footerOnPage) 12.dp else 16.dp, end = if (footerOnPage) 12.dp else 16.dp, top = if (footerOnPage) 8.dp else 12.dp, bottom = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                    content = footer,
                )
            }
        } else {
            Box(Modifier.navigationBarsPadding())
        }
    }
}

/** "1 / 3" on the title bar (design `stepT`). */
@Composable
private fun StepPill(n: Int, total: Int) {
    val c = Elchi.colors
    Text(
        "$n / $total",
        Modifier.clip(CircleShape).background(c.soft).padding(horizontal = 12.dp, vertical = 6.dp),
        style = Elchi.type.caption.copy(fontWeight = FontWeight.SemiBold),
        color = c.softText,
        maxLines = 1,
    )
}

/** The thin bar under the title: how far through the order form (design `stepPct`). */
@Composable
private fun StepProgress(n: Int, total: Int) {
    val c = Elchi.colors
    Box(Modifier.padding(start = 16.dp, end = 16.dp, bottom = 6.dp).fillMaxWidth().height(4.dp).clip(RoundedCornerShape(2.dp)).background(c.line)) {
        Box(Modifier.fillMaxWidth(n.toFloat() / total.coerceAtLeast(1)).fillMaxHeight().clip(RoundedCornerShape(2.dp)).background(c.brand))
    }
}
