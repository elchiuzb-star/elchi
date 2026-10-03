import SwiftUI

/// Every screen of the client's flow; the path (on top of the section) is the whole navigation state.
enum ClientRoute: Hashable {
    // Stage 02: posting a parcel request.
    case regions(EndSide)
    case districts(EndSide, RegionDTO)
    case point(EndSide, RegionDTO, DistrictDTO?)
    // BOSQICH 02 design: Pochta = route (1/3) -> contacts (2/3) -> review (3/3); Taksi = home -> review.
    case routeSummary, contacts, review, success
    // Stage 03: a listing of the client's (its offers inline, BOSQICH 03), all negotiations. `listingBids` is the
    // same detail opened at "Haydovchi takliflari" (a notification about an offer).
    case listing(String)
    case listingEdit(String)
    case listingBids(String)
    case proposals
    // Stage 04: a booking of the client's and what hangs off it.
    case booking(String)
    case bookingChat(String)
    case bookingTracking(String)
    case bookingAmend(String)
    case bookingRating(String)
    case bookingSupport(String)
    case bookingSafety(String)
    // Stage 05: the account's own screens (pushed from the profile, a notification or another screen).
    case notifications
    case bonus
    case safetyCenter
    case support
    case supportThreads
    case supportThread(String)
    case settings
    case accountDelete
    // Stage 06: a legacy (v1) order's archive and what it still allows (Q4).
    case legacyOrder(Int)
    case legacyBids(Int)
    case legacyRating(Int)
    case legacyDispute(Int)
}

/// The drawer's sections: each is a root with the menu button.
enum ClientSection: Hashable {
    case home, orders, notifications, profile, support, settings
}

/// The operator chats opened by thread id ("Murojaatlarim", a notification), one model per thread for the session.
@MainActor
final class SupportChatModels {
    private let api: ElchiAPI
    private let keys: ActionKeys
    private var models: [String: SupportChatModel] = [:]

    init(api: ElchiAPI, keys: ActionKeys) {
        self.api = api
        self.keys = keys
    }

    func model(_ threadId: String) -> SupportChatModel {
        if let model = models[threadId] { return model }
        let model = SupportChatModel(threadId: threadId, api: api, keys: keys)
        models[threadId] = model
        return model
    }
}

/// Signed in as a client. Stage 02 (BOSQICH 02 design): home (map + sheet) -> place pickers -> Pochta's three steps or
/// Taksi's review -> published.
/// Stage 03: Buyurtmalar (from the drawer or after publishing) -> a listing -> its offers / edit, and Takliflarim.
/// Stage 04: a booking (from the list, or straight after accept) -> chat, tracking, amendments, rating, support,
/// safety. Stage 05: notifications, profile, bonus, safety centre, support, settings, account deletion, sign-out
/// confirm. One `ParcelRequestModel` and one `ClientOrdersModel` live here, so a draft and the lists survive navigation.
struct ClientFlow: View {
    let container: AppContainer
    let session: Session
    @State private var model: ParcelRequestModel
    @State private var orders: ClientOrdersModel
    @State private var section: ClientSection = .home
    @State private var path: [ClientRoute] = []
    @State private var drawerOpen = false
    /// Where a place pick returns to: home, or the route step when "O'zgartirish" started it.
    @State private var pickReturn: [ClientRoute] = []
    @State private var inbox: InboxModel
    @State private var profile: ProfileModel
    @State private var bonus: BonusModel
    @State private var safety: SafetyCenterModel
    @State private var support: SupportModel
    @State private var threads: SupportThreadsModel
    @State private var supportChats: SupportChatModels
    @State private var accountDelete: AccountDeleteModel
    @State private var confirmLogout = false
    /// A step opened from the review's pencil: it saves with "Saqlash va qaytish" and returns to the review.
    @State private var editing = false
    /// The kept referral code's row was closed for this session (the code itself stays).
    @State private var promoHidden = false
    @Environment(LocaleStore.self) private var strings

    init(container: AppContainer, session: Session) {
        self.container = container
        self.session = session
        _model = State(initialValue: ParcelRequestModel(api: container.api, geo: container.geo, files: container.files, user: session.user))
        let transport = container.transport
        let sessions = container.sessions
        let connection = TrackingConnection(socketURL: TrackingSocket.url(apiBase: container.apiBase),
                                            accessToken: { sessions.current()?.accessToken })
        let orders = ClientOrdersModel(api: container.api, legacyAPI: container.legacyOrders,
                                       mediaURL: { transport.mediaURL($0) }, banners: container.banners, connection: connection)
        #if DEBUG
        // UI tests: a small v1 page, so paging shows with a handful of orders.
        if let size = Int(UserDefaults.standard.string(forKey: "uiTestLegacyPage") ?? ""), size > 0 { orders.legacyPageSize = size }
        #endif
        _orders = State(initialValue: orders)
        let api = container.api
        let keys = orders.keys
        _inbox = State(initialValue: InboxModel(api: api))
        _profile = State(initialValue: ProfileModel(api: api, profileAPI: container.clientProfile, auth: container.auth, sessions: sessions))
        _bonus = State(initialValue: BonusModel(api: api, keys: keys, links: container.links))
        _safety = State(initialValue: SafetyCenterModel(api: api, keys: keys))
        _support = State(initialValue: SupportModel(api: api, keys: keys))
        _threads = State(initialValue: SupportThreadsModel(api: api))
        _supportChats = State(initialValue: SupportChatModels(api: api, keys: keys))
        _accountDelete = State(initialValue: AccountDeleteModel(api: api, keys: keys))
    }

    var body: some View {
        NavigationStack(path: $path) {
            sectionRoot
            .navigationDestination(for: ClientRoute.self, destination: screen)
        }
        #if DEBUG
        // UI tests: straight to a v1 order by id (one that is not the client's shows the not-found state).
        .task {
            if let id = Int(UserDefaults.standard.string(forKey: "uiTestOpenLegacy") ?? ""), path.isEmpty {
                section = .orders
                path = [.legacyOrder(id)]
            }
            // Screenshots / UI tests: `-uiTestOpenBooking bkg_…` or `-uiTestOpenListing lst_…` opens it over the orders list.
            if let id = UserDefaults.standard.string(forKey: "uiTestOpenBooking"), path.isEmpty {
                section = .orders
                openBooking(id)
            } else if let id = UserDefaults.standard.string(forKey: "uiTestOpenListing"), path.isEmpty {
                section = .orders
                openListing(id)
            }
        }
        #endif
        // A link (cold or warm start, or one that waited for sign-in): the same screens as a notification; a referral
        // link opens "Bonuslar va taklif kodi" with the code filled in.
        .onChange(of: container.links.serial, initial: true) { _, _ in takeLinks() }
        .overlay { drawer }
        .overlay {
            if confirmLogout {
                LogoutDialog(onLogout: logout, onStay: { confirmLogout = false })
            }
        }
    }

    /// The section the drawer chose, at the root of the stack.
    @ViewBuilder
    private var sectionRoot: some View {
        switch section {
        case .home:
            ClientHomeView(model: model, inbox: inbox, banners: container.banners,
                           referralCode: promoHidden ? nil : container.links.referralCode, editing: editing,
                           onMenu: openDrawer, onSupport: { path.append(.support) },
                           onPick: startPick, onGo: homeGo, onReferral: { path.append(.bonus) }, onPromoClose: { promoHidden = true },
                           toast: toast)
                // The map has no top bar to draw the banner under: it floats below the menu row (a link that
                // cannot be opened says so here).
                .overlay { BannerHost(center: container.banners, floating: true) }
        case .orders:
            OrdersView(model: orders, inbox: inbox, onMenu: openDrawer, onNotifications: { path.append(.notifications) },
                       onNewOrder: { section = .home },
                       onOpenListing: { openListing($0) }, onOpenBooking: openBooking, onOpenLegacy: { path.append(.legacyOrder($0)) })
        case .notifications:
            NotificationsView(model: inbox, leading: .menu, onLeading: openDrawer, readAll: true, onOpen: openTarget)
        case .profile:
            ProfileView(model: profile, session: session, onMenu: openDrawer, onAction: profileAction)
        case .support:
            SupportView(model: support, leading: .menu, onLeading: openDrawer) { path.append(.supportThreads) }
        case .settings:
            settingsView(leading: .menu, onLeading: openDrawer)
        }
    }

    /// Side menu over everything (the unread count read again each time it opens).
    @ViewBuilder
    private var drawer: some View {
        if drawerOpen {
            ClientDrawer(session: session, section: section, unread: inbox.unread, unreadMore: inbox.unreadMore, onSelect: { choice in
                section = choice
                path = []
                closeDrawer()
            }, onProposals: {
                // "Takliflarim" (BOSQICH 03): over the orders list, so back lands there.
                section = .orders
                path = [.proposals]
                closeDrawer()
            }, onClose: closeDrawer, onLogout: {
                closeDrawer()
                confirmLogout = true
            })
            .transition(.opacity)
        }
    }

    /// A listing opened from the list starts clean: no earlier notice, no earlier share link. `offers`: scrolled to
    /// its drivers' offers.
    private func openListing(_ id: String, offers: Bool = false) {
        orders.listing(id).reset()
        path.append(offers ? .listingBids(id) : .listing(id))
    }

    /// The same for a booking: no earlier notice, no earlier tracking link.
    private func openBooking(_ id: String) {
        orders.booking(id).reset()
        path.append(.booking(id))
    }

    private func openDrawer() {
        withAnimation(.easeOut(duration: 0.25)) { drawerOpen = true }
        Task { await inbox.refreshUnread() }
    }
    private func closeDrawer() { withAnimation(.easeIn(duration: 0.2)) { drawerOpen = false } }

    @ViewBuilder
    private func screen(_ route: ClientRoute) -> some View {
        let back = { if !path.isEmpty { path.removeLast() } }
        switch route {
        case .regions(let side):
            RegionPickerView(model: model, side: side, onBack: back) { region in
                path.append(region.requiresDistrict == false ? .point(side, region, nil) : .districts(side, region))
            }
        case .districts(let side, let region):
            DistrictPickerView(model: model, region: region, side: side, onBack: back) { district in
                path.append(.point(side, region, district))
            }
        case .point(let side, let region, let district):
            PointPickerView(model: model, side: side, region: region, district: district, locale: strings.locale, onBack: back) { end in
                model.setEnd(side, end)
                path = pickReturn
                toast(strings.t(side == .pickup ? "client.order.pointChosenPickup" : "client.order.pointChosenDropoff",
                                 ("place", strings.place(end))))
            }
        case .routeSummary:
            RouteSummaryView(model: model, editing: editing, onBack: leaveStep, onChange: startPick) { stepDone(next: .contacts) }
        case .contacts:
            ContactsView(model: model, editing: editing, onBack: leaveStep, onContinue: { stepDone(next: .review) }, toast: toast)
        case .review:
            ReviewView(model: model, onBack: back, onEdit: editFromReview) { path = [.success] }
        case .success:
            // "Buyurtmalarimga o'tish": the orders list, with the new request at the top; "Yangi buyurtma": an empty home.
            SuccessView(model: model, onOrders: {
                model.clearPublished()
                section = .orders
                path = []
            }, onNewOrder: {
                model.clearPublished()
                section = .home
                path = []
            })
        case .listing(let id):
            ListingDetailView(model: orders.listing(id), onBack: back, onEdit: { path.append(.listingEdit(id)) }, onAccepted: accepted)
        case .listingEdit(let id):
            ListingEditView(model: orders.listing(id), onBack: back, onSaved: back)
        case .listingBids(let id):
            ListingDetailView(model: orders.listing(id), focusOffers: true, onBack: back, onEdit: { path.append(.listingEdit(id)) },
                              onAccepted: accepted)
        case .proposals:
            ProposalsView(model: orders.proposals, onBack: back, onAccepted: accepted)
        case .booking(let id):
            let booking = orders.booking(id)
            BookingDetailView(model: booking, onBack: back, onChat: { path.append(.bookingChat(id)) },
                              onTracking: { path.append(.bookingTracking(id)) }, onAmend: { path.append(.bookingAmend(id)) },
                              onRate: { path.append(.bookingRating(id)) }, onSupport: { path.append(.bookingSupport(id)) },
                              onSafety: { path.append(.bookingSafety(id)) })
        case .bookingChat(let id):
            let booking = orders.booking(id)
            let dto = booking.booking.value
            // BOSQICH 04: the bar's second line "Jasur · Chevrolet Cobalt"; a cancelled booking's closed chat says so.
            BookingChatView(model: booking.chat, agreedAt: ServerTime.parse(dto?.createdAt), onBack: back,
                            subtitle: dto?.driver.map { [$0.displayName, $0.vehicle.makeModel].filter { !$0.isEmpty }.joined(separator: " · ") },
                            cancelled: dto?.serviceStatus == "cancelled" || dto?.serviceStatus == "no_show")
        case .bookingTracking(let id):
            BookingTrackingView(booking: orders.booking(id), onBack: back)
        case .bookingAmend(let id):
            AmendmentView(booking: orders.booking(id), onBack: back)
        case .bookingRating(let id):
            RatingView(booking: orders.booking(id), onBack: back)
        case .bookingSupport(let id):
            SupportChatView(model: orders.booking(id).support, onBack: back)
        case .bookingSafety(let id):
            SafetyView(booking: orders.booking(id), onBack: back)
        case .notifications:
            NotificationsView(model: inbox, leading: .back, onLeading: back, readAll: true, onOpen: openTarget)
        case .bonus:
            BonusView(model: bonus, onBack: back)
        case .safetyCenter:
            SafetyCenterView(model: safety, onBack: back)
        case .support:
            SupportView(model: support, leading: .back, onLeading: back) { path.append(.supportThreads) }
        case .supportThreads:
            SupportThreadsView(model: threads, onBack: back) { path.append(.supportThread($0)) }
        case .supportThread(let id):
            SupportChatView(model: supportChats.model(id), onBack: back, title: strings.t("support.threadTitle"))
        case .settings:
            settingsView(leading: .back, onLeading: back)
        case .legacyOrder(let id):
            LegacyOrderDetailView(model: orders.legacyOrder(id), onBack: back, onBids: { path.append(.legacyBids(id)) },
                                  onRate: { path.append(.legacyRating(id)) }, onDispute: { path.append(.legacyDispute(id)) },
                                  onCancelled: {
                                      back()
                                      Task { await orders.refresh() }
                                  })
        case .legacyBids(let id):
            LegacyBidsView(model: orders.legacyOrder(id), onBack: back, onSelected: back)
        case .legacyRating(let id):
            LegacyRatingView(model: orders.legacyOrder(id), onBack: back)
        case .legacyDispute(let id):
            LegacyDisputeView(model: orders.legacyOrder(id), onBack: back)
        case .accountDelete:
            AccountDeleteView(model: accountDelete, onBack: back) {
                let notice = strings.t("client.accountDelete.done")
                Task { await container.endDeletedSession(notice: notice) }
            }
        }
    }

    private func settingsView(leading: ElchiIcon, onLeading: @escaping () -> Void) -> some View {
        SettingsView(leading: leading, onLeading: onLeading, onHelp: { path.append(.support) },
                     onDeleteAccount: {
                         accountDelete.confirmed = false
                         path.append(.accountDelete)
                     },
                     onLogout: { confirmLogout = true })
    }

    /// Where a notification leads (its `link`); an unknown target stays on the list.
    private func openTarget(_ target: InboxTarget) {
        switch target {
        case .booking(let id, let chat):
            openBooking(id)
            if chat { path.append(.bookingChat(id)) }
        case .listing(let id):
            openListing(id)
        case .proposal(let id):
            // The listing the negotiation belongs to, when the server says which; otherwise the orders list.
            Task {
                if let listing = await inbox.listingId(ofProposal: id) {
                    openListing(listing, offers: true)
                } else {
                    section = .orders
                    path = []
                }
            }
        case .supportThread(let id):
            path.append(.supportThread(id))
        case .trip, .wallet:
            break
        }
    }

    /// Stage 10 (`elchi://listings/{id}`): the owner gets the listing's detail; somebody else's listing (clients do
    /// not view each other's) or a missing one is a sentence. A listing already in the orders list is the owner's.
    private func openListingLink(_ id: String) async {
        let outcome: ListingLinkOutcome
        if orders.listings.value?.contains(where: { $0.id == id }) == true {
            outcome = .ownListing
        } else {
            do {
                outcome = ListingLinkRules.client(try await container.api.getListing(listingId: id).data)
            } catch {
                guard ListingLinkRules.isMissing(error) else { container.banners.error(error); return }
                outcome = ListingLinkRules.client(nil)
            }
        }
        if outcome == .ownListing {
            section = .orders
            path = []
            openListing(id)
        } else if let key = ListingLinkRules.messageKey(outcome) {
            container.banners.show(.key(key), tone: .warn)
        }
    }

    private func takeLinks() {
        let links = container.links
        if links.takeReferralArrival() {
            closeForLink()
            path = [.bonus]
        }
        guard case .open(let target)? = links.takePending(for: .client), let inbox = DeepLinkRules.inboxTarget(target) else { return }
        closeForLink()
        if case .listing(let id) = inbox {
            Task { await openListingLink(id) }
            return
        }
        switch inbox {
        case .booking, .listing:
            section = .orders
            path = []
        default:
            path = []
        }
        openTarget(inbox)
    }

    private func closeForLink() {
        drawerOpen = false
        confirmLogout = false
    }

    private func profileAction(_ action: ProfileView.ProfileAction) {
        switch action {
        case .orders:
            section = .orders
            path = []
        case .proposals: path.append(.proposals)
        case .bonus: path.append(.bonus)
        case .notifications: path.append(.notifications)
        case .threads: path.append(.supportThreads)
        case .safety: path.append(.safetyCenter)
        case .help: path.append(.support)
        case .settings: path.append(.settings)
        case .home:
            section = .home
            path = []
        case .logout: confirmLogout = true
        }
    }

    /// A booking was made (Q100): the orders list underneath with the booking at the top and a short ok strip, the
    /// booking's detail on it, and its chat open - back from the chat is the booking, back again the list.
    private func accepted(_ listingId: String, _ booking: ClientBookingDTO) {
        section = .orders
        orders.booking(booking.id, initial: booking).reset()
        path = [.booking(booking.id), .bookingChat(booking.id)]
        Task { await orders.accepted(listingId: listingId, banner: strings.t("listingBids.driverChosen")) }
    }

    private func startPick(_ side: EndSide) {
        pickReturn = path
        path.append(.regions(side))
    }

    /// The home's primary button once it may go on: Pochta to the route step, Taksi (its block valid) to the review -
    /// or, when the review sent the person here to edit, back to it.
    private func homeGo() {
        if model.mode == .passenger {
            editing = false
            path = [.review]
        } else {
            editing = false
            path = [.routeSummary]
        }
    }

    /// A step's primary button with nothing missing: on to `next`, or back to the review when editing.
    private func stepDone(next: ClientRoute) {
        if editing {
            editing = false
            if !path.isEmpty { path.removeLast() }
        } else {
            path.append(next)
        }
    }

    /// Back out of a step: an edit started from the review is over.
    private func leaveStep() {
        editing = false
        if !path.isEmpty { path.removeLast() }
    }

    /// A pencil (or "Tahrirlash") on the review: the step opens in edit mode. Taksi's route lives on the home itself.
    private func editFromReview(_ step: OrderStep) {
        editing = true
        if model.mode == .passenger {
            path = []
        } else {
            path.append(step == .contact ? .contacts : .routeSummary)
        }
    }

    /// The design's short confirmations ("Qabul qiluvchi: …", "Olib ketish joyi tanlandi: …").
    private func toast(_ text: String) {
        container.banners.show(.text(text), tone: .info, hideAfter: .seconds(3))
    }

    /// After "Chiqish" in the confirm: v1 `/auth/logout`, then the session goes (the root shows sign-in).
    private func logout() {
        confirmLogout = false
        Task { await container.signOut() }
    }
}

// MARK: - Home

/// Full-screen map with the request sheet (BOSQICH 02): the referral row, Taksi / Pochta (only where passenger is on,
/// K7/Q89), the heading, the route card with its swap, what the server said about the direction, the Taksi block
/// (window, people, price, total) and the primary button - grey but tappable until the direction is ready, where a tap
/// says what to do first.
private struct ClientHomeView: View {
    @Bindable var model: ParcelRequestModel
    let inbox: InboxModel
    /// The my-location button's denied / not-found sentences go to the app's banner.
    let banners: BannerCenter
    /// The code kept from an `elchigo.uz/r/<code>` link (web `home.referralCodeSaved`); gone once it is forgotten.
    let referralCode: String?
    /// The review sent the person here to change the Taksi answers: the button says "Saqlash va qaytish".
    let editing: Bool
    let onMenu: () -> Void
    let onSupport: () -> Void
    let onPick: (EndSide) -> Void
    let onGo: () -> Void
    /// "Bonuslar va taklif kodi", where the kept code fills the field.
    let onReferral: () -> Void
    let onPromoClose: () -> Void
    let toast: (String) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var sheetHeight: CGFloat = 0
    /// The sheet content's natural height (the scroll area never grows past it).
    @State private var contentHeight: CGFloat = 400
    /// The map runs under the home indicator and so does the sheet's background, so both count as covered map.
    @State private var bottomSafeArea: CGFloat = 0
    /// "You are here": CoreLocation runs only while this home is on screen (and the app in front).
    @State private var myLocation = MyLocationModel()
    @State private var onScreen = false
    @State private var windowEdge: WindowEdge?
    /// A tap on "Davom etish" with something missing in the Taksi block: the red list shows (and stays live).
    @State private var showErrors = false
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.openURL) private var openURL

    private var taxi: Bool { model.mode == .passenger }

    var body: some View {
        ZStack(alignment: .bottom) {
            ElchiMap(markers: markers, polyline: model.routeLeg,
                     focus: markers.first?.point, zoom: 11, recentreLabel: strings.t("location.recentre"),
                     myLocation: MyLocationControl(model: myLocation, label: strings.t("client.map.myLocation"),
                                                   locatingLabel: strings.t("client.map.locating")),
                     placeholder: strings.t("client.map.unavailable"),
                     placeholderInset: sheetHeight + bottomSafeArea)
                .ignoresSafeArea()
            VStack(spacing: 0) {
                // The floating top controls' room (menu row + service pill): the sheet never grows over them.
                Color.clear.frame(height: 128).allowsHitTesting(false)
                Spacer(minLength: 0)
                sheet.onGeometryChange(for: CGFloat.self) { $0.size.height } action: { sheetHeight = $0 }
            }
        }
        .onGeometryChange(for: CGFloat.self) { $0.safeAreaInsets.bottom } action: { bottomSafeArea = $0 }
        .overlay(alignment: .top) {
            VStack(spacing: 12) {
                HStack {
                    RoundIconButton(.menu, label: strings.t("nav.menu"), dot: inbox.unread > 0,
                                    dotLabel: strings.t("notifications.title"), action: onMenu)
                    Spacer()
                    Button(action: onSupport) {
                        HStack(spacing: 8) {
                            ElchiIcon.head.image(size: 20)
                            Text(strings.t("support.title")).font(ElchiFont.poppins(14, .medium))
                        }
                        .foregroundStyle(c.text)
                        .padding(.leading, 12).padding(.trailing, 16)
                        .frame(height: 44)
                        .background(c.card, in: Capsule())
                        .shadow(color: c.shadow, radius: 12, y: 6)
                    }
                    .buttonStyle(PressFade())
                    .accessibilityIdentifier("elchi.home.support")
                }
                // The chosen service, floating over the map (design 1.2).
                HStack(spacing: 10) {
                    Text(strings.t(taxi ? "home.modeTaxi" : "orderForm.review.parcel")).font(ElchiFont.poppins(15, .medium)).foregroundStyle(c.text)
                    (taxi ? ElchiIcon.car : ElchiIcon.pkg).image(size: 18).foregroundStyle(c.text)
                        .frame(width: 34, height: 34).background(c.field, in: Circle())
                }
                .padding(.leading, 18).padding(.trailing, 8)
                .frame(height: 48)
                .background(c.card, in: Capsule())
                .shadow(color: c.shadow, radius: 12, y: 6)
                .accessibilityElement(children: .combine)
            }
            .padding(.horizontal, 16).padding(.top, 8)
        }
        .toolbar(.hidden, for: .navigationBar)
        .task { await model.loadCountryFlags() }
        .task { await inbox.refreshUnread() }
        // The camera moves on its own once at most: the first fix on an empty home, inside Uzbekistan, before the
        // person touched the map (MyLocationLogic). With a place chosen it stays on the route until the button.
        .onChange(of: markers.isEmpty) { _, empty in myLocation.homeEmpty(empty) }
        .onChange(of: model.mode) { _, _ in showErrors = false }
        .onAppear {
            myLocation.onDenied = { [banners, openURL] in
                banners.show(.key("client.map.locationDenied"), tone: .warn) {
                    // iOS asks only once: after a denial the switch is in Settings.
                    if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
                }
            }
            myLocation.onUnavailable = { [banners] in
                banners.show(.key("client.map.locationUnavailable"), tone: .warn, hideAfter: .seconds(6))
            }
            // The design's locate: the map centres on the person and an empty "Qayerdan" becomes the current location.
            myLocation.onCentred = { [model, banners, strings, toast] fix in
                guard model.pickup == nil else { return }
                model.language = strings.locale
                Task {
                    switch await model.fillPickup(from: fix.point) {
                    case .set: toast(strings.t("client.order.locateSet"))
                    case .outside: banners.show(.text(strings.t("client.order.locateOutside")), tone: .warn, hideAfter: .seconds(6))
                    case .kept: break
                    }
                }
            }
            // Before `appear`: a first fix must know whether a place is chosen.
            myLocation.homeEmpty(markers.isEmpty)
            onScreen = true
            if scenePhase != .background { myLocation.appear() }
        }
        .onDisappear {
            onScreen = false
            myLocation.disappear()
        }
        // `.inactive` is also the permission prompt itself: only the background stops the updates.
        .onChange(of: scenePhase) { _, phase in
            if phase == .background { myLocation.disappear() } else if onScreen { myLocation.appear() }
        }
        .sheet(item: $windowEdge) { edge in
            DepartureWindowSheet(edge: edge, start: model.windowStart, end: model.windowEnd) { start, end in
                model.windowStart = start
                model.windowEnd = end
                windowEdge = nil
            }
        }
    }

    private var markers: [MapMarker] {
        [model.pickup.map { MapMarker($0.point, .origin) }, model.dropoff.map { MapMarker($0.point, .destination) }].compactMap { $0 }
    }

    /// The sheet as tall as its content; where that does not fit under the top controls (the Taksi block, a small
    /// phone, the keyboard) it scrolls.
    private var sheet: some View {
        ScrollView {
            sheetContent.onGeometryChange(for: CGFloat.self) { $0.size.height } action: { contentHeight = $0 }
        }
        .scrollBounceBehavior(.basedOnSize)
        .scrollDismissesKeyboard(.interactively)
        // As tall as the content, at most the room the layout leaves under the top controls.
        .frame(maxHeight: contentHeight)
        .clipShape(UnevenRoundedRectangle(topLeadingRadius: ElchiShape.sheet, topTrailingRadius: ElchiShape.sheet))
        .background {
            UnevenRoundedRectangle(topLeadingRadius: ElchiShape.sheet, topTrailingRadius: ElchiShape.sheet)
                .fill(c.card)
                .shadow(color: c.shadow, radius: 12, y: -6)
                .ignoresSafeArea(edges: .bottom)
        }
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button(strings.t("client.keyboard.done")) {
                    UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
                }
                .font(ElchiFont.poppins(15, .semibold))
                .accessibilityIdentifier("elchi.keyboard.done")
            }
        }
    }

    private var sheetContent: some View {
        VStack(alignment: .leading, spacing: 14) {
            if let referralCode { promo(referralCode) }
            // K7/Q89: the Taksi / Pochta choice exists only where passenger is enabled.
            if model.taxiVisible {
                Segmented([(ServiceType.passenger, strings.t("home.modeTaxi")), (.parcel, strings.t("home.modeParcel"))],
                          selected: model.mode) { model.mode = $0 }
                    .accessibilityIdentifier("elchi.home.mode")
            }
            Text(strings.t(taxi ? "client.taxi.homeTitle" : "client.order.homeTitle"))
                .font(ElchiFont.poppins(20, .medium, relativeTo: .title)).foregroundStyle(c.text)
                .accessibilityAddTraits(.isHeader)
            RouteCard(from: end(.pickup), to: end(.dropoff), swapLabel: strings.t("client.order.swap"),
                      onSwap: model.pickup == nil && model.dropoff == nil ? nil : { model.swapEnds() })
            directionState
            if taxi && model.directionReady { taxiBlock }
            ElchiButton(buttonTitle, dimmed: !canGo, action: go)
                .disabled(model.directionReady && model.closedKey != nil)
                .accessibilityIdentifier("elchi.home.go")
            if let closed = model.closedKey {
                Text(strings.t(closed)).font(ElchiFont.poppins(13)).foregroundStyle(c.tone(.err).fg)
                    .frame(maxWidth: .infinity).multilineTextAlignment(.center)
            }
        }
        .padding(EdgeInsets(top: 22, leading: 16, bottom: 26, trailing: 16))
    }

    private func promo(_ code: String) -> some View {
        HStack(spacing: 10) {
            Button(action: onReferral) {
                HStack(spacing: 10) {
                    ElchiIcon.tag.image(size: 18).foregroundStyle(c.accentText)
                    VStack(alignment: .leading, spacing: 0) {
                        Text(strings.t("client.order.promoSaved", ("code", code))).font(ElchiFont.poppins(13, .semibold))
                            .foregroundStyle(c.isDark ? c.tone(.blue).noteText : Color(hex: 0x0B3E73)).lineLimit(1)
                        Text(strings.t("client.order.promoTap")).font(ElchiFont.caption).foregroundStyle(c.accentText)
                    }
                    Spacer(minLength: 0)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(PressFade())
            .accessibilityIdentifier("elchi.home.referralCode")
            Button(action: onPromoClose) {
                ElchiIcon.x.image(size: 14).foregroundStyle(c.text)
                    .frame(width: 30, height: 30).background(c.card, in: Circle())
                    .frame(width: 44, height: 44).contentShape(Circle())
            }
            .buttonStyle(PressFade())
            .accessibilityLabel(strings.t("common.close"))
        }
        .padding(.leading, 14).padding(.trailing, 3).padding(.vertical, 3)
        .background(c.isDark ? Color(hex: 0x0E2A45) : Color(hex: 0xEAF5FF), in: RoundedRectangle(cornerRadius: 18))
    }

    // MARK: Taksi block

    @ViewBuilder
    private var taxiBlock: some View {
        let shown = showErrors ? model.taxiHomeBlockers : []
        VStack(alignment: .leading, spacing: 6) {
            BlockLabel(text: strings.t("client.taxi.departure"))
            WindowTiles(start: model.windowStart, end: model.windowEnd, errorStart: shown.contains(where: \.marksStart),
                        errorEnd: shown.contains(where: \.marksEnd)) { windowEdge = $0 }
        }
        .onAppear { model.suggestWindowIfEmpty() }
        VStack(alignment: .leading, spacing: 6) {
            BlockLabel(text: strings.t("seatPicker.howMany"), trailing: strings.seatValue(model.seatCount))
            SeatCountPicker(count: $model.seatCount, error: shown.contains(.seats))
        }
        VStack(alignment: .leading, spacing: 6) {
            BlockLabel(text: Self.withoutUnit(strings.t("routeSummary.pricePerPerson")))
            PriceStepper(digits: $model.priceDigits, label: strings.t("routeSummary.pricePerPerson"), error: shown.contains(.price))
            Text(strings.t("client.order.priceStepHint")).font(ElchiFont.caption).foregroundStyle(c.muted)
        }
        TotalBar(who: TaxiSeats.isWholeCabin(model.seatCount) ? strings.t("client.taxi.wholeCabinLower")
                    : strings.t("orderForm.review.peopleCount", ("count", model.seatCount ?? 1)),
                 total: model.priceMinor > 0 ? strings.money(model.passengerTotalMinor) : "—")
        if !shown.isEmpty { ErrorList(lines: shown.map { strings.t($0.key) }, compact: true) }
    }

    /// "Bir kishi uchun narx (so'm)" -> "Bir kishi uchun narx": the stepper already says so'm.
    static func withoutUnit(_ label: String) -> String {
        label.replacingOccurrences(of: #"\s*\([^)]*\)\s*$"#, with: "", options: .regularExpression)
    }

    // MARK: The button

    private var buttonTitle: String {
        if taxi {
            guard model.directionReady else { return strings.t("home.viewRoute") }
            return strings.t(editing ? "client.order.saveAndReturn" : "common.continue")
        }
        return strings.t("client.order.toForm")
    }

    /// Bright only when the direction is ready and the chosen service is open there.
    private var canGo: Bool { model.canViewRoute }

    private func go() {
        guard model.directionReady else {
            if case .mismatch = model.direction {
                toast(strings.t("client.order.moveCloserFirst"))
            } else {
                toast(strings.t("driverFeed.emptyPickFirst"))
            }
            return
        }
        guard model.canViewRoute else { return }
        if taxi && !model.taxiHomeBlockers.isEmpty {
            showErrors = true
            return
        }
        showErrors = false
        onGo()
    }

    private func end(_ side: EndSide) -> RouteCard.End {
        let label = strings.t(side == .pickup ? "direction.from" : "direction.to")
        if let end = model.end(side) {
            return RouteCard.End(title: strings.place(end), detail: strings.area(end), isSet: true, label: label) { onPick(side) }
        }
        return RouteCard.End(title: label, detail: nil, isSet: false, label: label) { onPick(side) }
    }

    @ViewBuilder
    private var directionState: some View {
        switch model.direction {
        case .idle:
            EmptyView()
        case .checking:
            HStack(spacing: 8) {
                ProgressView()
                Text(strings.t("home.checkingRoute")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
            }
        case .ready(let preview):
            ElchiCard(tint: .blue) {
                CardRow(strings.t("home.estimatedTime", ("corridor", preview.corridorName)),
                        strings.routeFigures(distanceM: preview.legDistanceM, durationS: preview.legDurationS), first: true, strong: true)
            }
            if let km = RouteFigures.offRouteKilometres(preview) {
                Note(strings.t("app.location.offRoute", ("km", km)), tone: .warn)
            }
        case .mismatch:
            Note(strings.t("home.movePointHint"), tone: .err, title: strings.t("app.location.previewMismatch"))
        case .failed(let error):
            Note(strings.errorText(error), tone: .err)
            ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { model.retryDirection() }
        }
    }
}

// MARK: - Drawer

/// Side menu: who is signed in, the sections (Bildirishnomalar with its unread count), sign out (with a confirm).
private struct ClientDrawer: View {
    let session: Session
    let section: ClientSection
    let unread: Int
    let unreadMore: Bool
    let onSelect: (ClientSection) -> Void
    let onProposals: () -> Void
    let onClose: () -> Void
    let onLogout: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        ZStack(alignment: .leading) {
            Color(hex: 0x0A1226, opacity: 0.5).ignoresSafeArea()
                .onTapGesture(perform: onClose)
                .accessibilityElement()
                .accessibilityLabel(strings.t("nav.closeMenu"))
                .accessibilityAddTraits(.isButton)
                .accessibilityAction { onClose() }
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("ELCHI").font(ElchiFont.poppins(20, .medium)).foregroundStyle(c.text).accessibilityAddTraits(.isHeader)
                        if let name = session.user.fullName, !name.isEmpty {
                            Text(name).font(ElchiFont.secondary).foregroundStyle(c.muted)
                        }
                        Text(UzPhone.display(session.user.phone)).font(ElchiFont.secondary).foregroundStyle(c.muted)
                    }
                    ElchiList {
                        item(.home, .home, "nav.home", "nav.homeHint", first: true)
                        item(.orders, .pkg, "nav.orders", "nav.ordersHint")
                        item(.notifications, .bell, "app.nav.messages", "notifications.title",
                             trailing: unread > 0 ? (unreadMore ? "\(unread)+" : "\(unread)") : nil)
                        // BOSQICH 03: "Takliflarim / Narx kelishuvlari" (a screen over the orders, not a section).
                        ListRow(icon: .tag, title: strings.t("proposals.title"), description: strings.t("client.offers.drawerHint"),
                                action: onProposals)
                            .accessibilityIdentifier("elchi.drawer.proposals")
                        item(.profile, .user, "nav.profile", "nav.profileHint")
                        item(.support, .head, "support.title", "clientProfile.helpHint")
                        item(.settings, .settings, "settingsScreen.title", "driver.profile.settingsHint")
                    }
                    ElchiList {
                        ListRow(icon: .logout, title: strings.t("nav.logout"), danger: true, first: true, action: onLogout)
                    }
                }
                .padding(EdgeInsets(top: 14, leading: 16, bottom: 24, trailing: 16))
            }
            .frame(width: 300)
            .background(c.page.ignoresSafeArea())
            .transition(.move(edge: .leading))
        }
    }

    private func item(_ target: ClientSection, _ icon: ElchiIcon, _ title: String, _ hint: String, trailing: String? = nil,
                      first: Bool = false) -> some View {
        ListRow(icon: icon, title: strings.t(title), description: strings.t(hint), trailing: trailing, highlighted: section == target,
                first: first) { onSelect(target) }
            .accessibilityIdentifier("elchi.drawer.\(target)")
            .overlay(alignment: .topLeading) {
                // The unread dot on the bell (the count is the trailing text), so the state is not the number alone.
                if trailing != nil {
                    Circle().fill(c.danger).frame(width: 9, height: 9).offset(x: 42, y: 12).accessibilityHidden(true)
                }
            }
    }
}
