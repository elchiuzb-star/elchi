import SwiftUI

/// Every screen of the client's flow; the path (on top of the section) is the whole navigation state.
enum ClientRoute: Hashable {
    // Stage 02: posting a parcel request.
    case regions(EndSide)
    case districts(EndSide, RegionDTO)
    case point(EndSide, RegionDTO, DistrictDTO?)
    case routeSummary, contacts, parcel, photo, review, success
    // Stage 03: a listing of the client's, its offers, all negotiations.
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

/// Signed in as a client. Stage 02: home (map + sheet) -> place pickers -> the five request steps -> published.
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
            Group {
                switch section {
                case .home:
                    ClientHomeView(model: model, inbox: inbox, referralCode: container.links.referralCode, onMenu: openDrawer,
                                   onPick: startPick, onViewRoute: { path.append(.routeSummary) }, onReferral: { path.append(.bonus) })
                        // The map has no top bar to draw the banner under: it floats below the menu row (a link that
                        // cannot be opened says so here).
                        .overlay { BannerHost(center: container.banners, floating: true) }
                case .orders:
                    OrdersView(model: orders, onMenu: openDrawer, onNewOrder: { section = .home },
                               onOpenListing: openListing, onOpenBooking: openBooking, onOpenLegacy: { path.append(.legacyOrder($0)) },
                               onProposals: { path.append(.proposals) })
                case .notifications:
                    NotificationsView(model: inbox, leading: .menu, onLeading: openDrawer, onOpen: openTarget)
                case .profile:
                    ProfileView(model: profile, session: session, onMenu: openDrawer, onAction: profileAction)
                case .support:
                    SupportView(model: support, leading: .menu, onLeading: openDrawer) { path.append(.supportThreads) }
                case .settings:
                    settingsView(leading: .menu, onLeading: openDrawer)
                }
            }
            .navigationDestination(for: ClientRoute.self, destination: screen)
        }
        #if DEBUG
        // UI tests: straight to a v1 order by id (one that is not the client's shows the not-found state).
        .task {
            if let id = Int(UserDefaults.standard.string(forKey: "uiTestOpenLegacy") ?? ""), path.isEmpty {
                section = .orders
                path = [.legacyOrder(id)]
            }
        }
        #endif
        // A link (cold or warm start, or one that waited for sign-in): the same screens as a notification; a referral
        // link opens "Bonuslar va taklif kodi" with the code filled in.
        .onChange(of: container.links.serial, initial: true) { _, _ in takeLinks() }
        .overlay {
            if drawerOpen {
                ClientDrawer(session: session, section: section, unread: inbox.unread, unreadMore: inbox.unreadMore, onSelect: { choice in
                    section = choice
                    path = []
                    closeDrawer()
                }, onClose: closeDrawer, onLogout: {
                    closeDrawer()
                    confirmLogout = true
                })
                .transition(.opacity)
            }
        }
        .overlay {
            if confirmLogout {
                LogoutDialog(onLogout: logout, onStay: { confirmLogout = false })
            }
        }
    }

    /// A listing opened from the list starts clean: no earlier notice, no earlier share link.
    private func openListing(_ id: String) {
        orders.listing(id).reset()
        path.append(.listing(id))
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
            }
        case .routeSummary:
            RouteSummaryView(model: model, onBack: back, onChange: startPick) { path.append(.contacts) }
        case .contacts:
            ContactsView(model: model, onBack: back) { path.append(.parcel) }
        case .parcel:
            ParcelView(model: model, onBack: back) { path.append(.photo) }
        case .photo:
            PhotoView(model: model, onBack: back) { path.append(.review) }
        case .review:
            ReviewView(model: model, onBack: back, onEdit: { path = [.routeSummary] }) { path = [.success] }
        case .success:
            // "Buyurtmalarimga o'tish": the orders list, with the new request at the top.
            SuccessView(model: model) {
                model.clearPublished()
                section = .orders
                path = []
            }
        case .listing(let id):
            ListingDetailView(model: orders.listing(id), onBack: back, onEdit: { path.append(.listingEdit(id)) },
                              onBids: { path.append(.listingBids(id)) })
        case .listingEdit(let id):
            ListingEditView(model: orders.listing(id), onBack: back, onSaved: back)
        case .listingBids(let id):
            ListingBidsView(model: orders.listing(id), onBack: back, onAccepted: accepted)
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
            BookingChatView(model: booking.chat, agreedAt: ServerTime.parse(booking.booking.value?.createdAt), onBack: back)
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
            NotificationsView(model: inbox, leading: .back, onLeading: back, onOpen: openTarget)
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
                    openListing(listing)
                } else {
                    section = .orders
                    path = []
                }
            }
        case .supportThread(let id):
            path.append(.supportThread(id))
        case .trip:
            break
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

    /// After "Chiqish" in the confirm: v1 `/auth/logout`, then the session goes (the root shows sign-in).
    private func logout() {
        confirmLogout = false
        Task { await container.signOut() }
    }
}

// MARK: - Home

/// Full-screen map with the request sheet: Pochta heading (Taksi/Pochta only where passenger is on), the route
/// card, what the server said about the direction, and "Yo'nalishni ko'rish".
private struct ClientHomeView: View {
    let model: ParcelRequestModel
    let inbox: InboxModel
    /// The code kept from an `elchigo.uz/r/<code>` link (web `home.referralCodeSaved`); gone once it is forgotten.
    let referralCode: String?
    let onMenu: () -> Void
    let onPick: (EndSide) -> Void
    let onViewRoute: () -> Void
    /// "Bonuslar va taklif kodi", where the kept code fills the field.
    let onReferral: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(ThemeStore.self) private var theme
    @Environment(\.elchi) private var c
    @State private var sheetHeight: CGFloat = 0
    /// The map runs under the home indicator and so does the sheet's background, so both count as covered map.
    @State private var bottomSafeArea: CGFloat = 0

    var body: some View {
        ZStack(alignment: .bottom) {
            ElchiMap(markers: markers, polyline: model.routeLeg,
                     focus: markers.first?.point, zoom: 11, recentreLabel: strings.t("location.recentre"),
                     placeholder: strings.t("client.map.unavailable"),
                     placeholderInset: sheetHeight + bottomSafeArea)
                .ignoresSafeArea()
            sheet.onGeometryChange(for: CGFloat.self) { $0.size.height } action: { sheetHeight = $0 }
        }
        .onGeometryChange(for: CGFloat.self) { $0.safeAreaInsets.bottom } action: { bottomSafeArea = $0 }
        .overlay(alignment: .top) {
            HStack {
                RoundIconButton(.menu, label: strings.t("nav.menu"), dot: inbox.unread > 0,
                                dotLabel: strings.t("notifications.title"), action: onMenu)
                Spacer()
                ThemeSwitch(mode: theme.mode, lightLabel: strings.t("theme.light"), darkLabel: strings.t("theme.dark")) { theme.set($0) }
            }
            .padding(.horizontal, 16).padding(.top, 8)
        }
        .toolbar(.hidden, for: .navigationBar)
        .task { await model.loadCountryFlags() }
        .task { await inbox.refreshUnread() }
    }

    private var markers: [MapMarker] {
        [model.pickup.map { MapMarker($0.point, .origin) }, model.dropoff.map { MapMarker($0.point, .destination) }].compactMap { $0 }
    }

    private var sheet: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let referralCode {
                ElchiList {
                    ListRow(icon: .tag, title: strings.t("home.referralCodeSaved", ("code", referralCode)), highlighted: true,
                            first: true, action: onReferral)
                }
                .accessibilityIdentifier("elchi.home.referralCode")
            }
            if model.flags?.passengerEnabled == true {
                Segmented([(ServiceType.passenger, strings.t("home.modeTaxi")), (.parcel, strings.t("home.modeParcel"))],
                          selected: model.mode) { model.mode = $0 }
            } else {
                Text(strings.t("home.modeParcel")).font(ElchiFont.poppins(22, .medium, relativeTo: .title)).foregroundStyle(c.text)
                    .accessibilityAddTraits(.isHeader)
            }
            if model.mode == .passenger { Note(strings.t("client.home.taxiSoon")) }
            RouteCard(from: end(.pickup), to: end(.dropoff))
            directionState
            ElchiButton(strings.t("home.viewRoute"), action: onViewRoute).disabled(!model.canViewRoute)
            if model.parcelOpen == false && model.mode == .parcel {
                Text(strings.t("home.parcelClosed")).font(ElchiFont.poppins(13)).foregroundStyle(c.tone(.err).fg)
                    .frame(maxWidth: .infinity).multilineTextAlignment(.center)
            }
        }
        .padding(EdgeInsets(top: 24, leading: 16, bottom: 26, trailing: 16))
        .background {
            UnevenRoundedRectangle(topLeadingRadius: ElchiShape.sheet, topTrailingRadius: ElchiShape.sheet)
                .fill(c.card)
                .shadow(color: c.shadow, radius: 12, y: -6)
                .ignoresSafeArea(edges: .bottom)
        }
    }

    private func end(_ side: EndSide) -> RouteCard.End {
        let label = strings.t(side == .pickup ? "direction.from" : "direction.to")
        if let end = model.end(side) {
            return RouteCard.End(title: strings.title(end), detail: end.address ?? end.point.text, isSet: true, label: label) { onPick(side) }
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
                        item(.notifications, .bell, "notifications.title", "clientProfile.notificationsHint",
                             trailing: unread > 0 ? (unreadMore ? "\(unread)+" : "\(unread)") : nil)
                        item(.profile, .user, "nav.profile", "nav.profileHint")
                        item(.support, .head, "support.title", "clientProfile.helpHint")
                        item(.settings, .settings, "settingsScreen.title", "clientProfile.settingsHint")
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
