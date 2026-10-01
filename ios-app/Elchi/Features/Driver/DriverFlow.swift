import SwiftUI

/// The driver's bottom tabs (web `BottomNav`). Moslar and Buyurtmalar have different icons (radar / clip).
enum DriverTab: String, CaseIterable, Hashable {
    case home, routes, matches, orders, profile

    var icon: ElchiIcon {
        switch self {
        case .home: .home
        case .routes: .route
        case .matches: .radar
        case .orders: .clip
        case .profile: .user
        }
    }

    var labelKey: String { "app.nav.\(rawValue)" }
}

/// Screens pushed over the tabs (the bar shows only on the tab roots).
enum DriverRoute: Hashable {
    case profileForm
    case documents
    // Stage 05 screens, reused as they are (v2, role-agnostic).
    case notifications
    case support
    case supportThreads
    case supportThread(String)
    case safetyCenter
    case settings
    case accountDelete
    // Stage 08: trips, feed, offers.
    case trip(String)
    case addTrip
    case feedEnd(origin: Bool)
    case savedRoutes
    case offer(String)
    case proposals
    case thread(String)
}

/// Signed in as a driver (Stage 07): home (status, balance, availability), the verification gate on Routes / Matches /
/// Orders until approved (Stage 08 fills those tabs), and the profile menu - the profile + vehicle form (locked after
/// the first save, Q94), the five documents, and the Stage 05 account screens.
struct DriverFlow: View {
    let container: AppContainer
    let session: Session
    @State private var driver: DriverModel
    @State private var form: DriverProfileFormModel
    @State private var tab: DriverTab = .home
    @State private var path: [DriverRoute] = []
    @State private var inbox: InboxModel
    @State private var safety: SafetyCenterModel
    @State private var support: SupportModel
    @State private var threads: SupportThreadsModel
    @State private var supportChats: SupportChatModels
    @State private var accountDelete: AccountDeleteModel
    @State private var trips: TripsModel
    @State private var addTrip: AddTripModel
    @State private var feed: FeedModel
    @State private var saved: SavedRoutesModel
    @State private var proposals: DriverProposalsModel
    @State private var confirmLogout = false
    /// "Taklif kodi saqlandi" was tapped and the attribution is on its way.
    @State private var applyingReferral = false
    @Environment(LocaleStore.self) private var strings

    init(container: AppContainer, session: Session) {
        self.container = container
        self.session = session
        let driver = DriverModel(driverAPI: container.driver, api: container.api, files: container.files, banners: container.banners)
        _driver = State(initialValue: driver)
        _form = State(initialValue: DriverProfileFormModel(driver: driver))
        let api = container.api
        let keys = driver.keys
        _inbox = State(initialValue: InboxModel(api: api))
        _safety = State(initialValue: SafetyCenterModel(api: api, keys: keys))
        _support = State(initialValue: SupportModel(api: api, keys: keys))
        _threads = State(initialValue: SupportThreadsModel(api: api))
        _supportChats = State(initialValue: SupportChatModels(api: api, keys: keys))
        _accountDelete = State(initialValue: AccountDeleteModel(api: api, keys: keys))
        let banners = container.banners
        _trips = State(initialValue: TripsModel(api: api, banners: banners, keys: keys))
        _addTrip = State(initialValue: AddTripModel(api: api, keys: keys))
        _feed = State(initialValue: FeedModel(api: api, market: MarketAPI(transport: container.transport), userId: session.user.id))
        _saved = State(initialValue: SavedRoutesModel(api: api, banners: banners, keys: keys))
        _proposals = State(initialValue: DriverProposalsModel(api: api, banners: banners, keys: keys))
    }

    var body: some View {
        NavigationStack(path: $path) {
            root
                .safeAreaInset(edge: .bottom, spacing: 0) { DriverTabBar(selected: tab) { tab = $0 } }
                .navigationDestination(for: DriverRoute.self, destination: screen)
        }
        #if DEBUG
        // UI tests: open straight on a tab or a pushed screen.
        .task {
            let defaults = UserDefaults.standard
            if let raw = defaults.string(forKey: "uiTestDriverTab"), let start = DriverTab(rawValue: raw) { tab = start }
            switch defaults.string(forKey: "uiTestDriverScreen") {
            case "form": path = [.profileForm]
            case "documents": path = [.documents]
            case "support": path = [.support]
            case "proposals": path = [.proposals]
            case "saved": path = [.savedRoutes]
            default: break
            }
        }
        #endif
        // A link (cold or warm start, or one that waited for sign-in): an operator chat opens; a referral code shows
        // as the home's "Taklif kodi saqlandi" row; the rest has no driver screen yet.
        .onChange(of: container.links.serial, initial: true) { _, _ in takeLinks() }
        .overlay {
            if confirmLogout {
                LogoutDialog(onLogout: logout, onStay: { confirmLogout = false })
            }
        }
    }

    @ViewBuilder
    private var root: some View {
        switch tab {
        case .home:
            DriverHomeView(driver: driver, inbox: inbox, referralCode: container.links.referralCode, applyingReferral: applyingReferral,
                           onReferral: { Task { await applyReferral() } }, onBell: { path.append(.notifications) },
                           onProfile: openForm, onDocuments: openDocuments, onSupport: { path.append(.support) },
                           onMatches: { tab = .matches }, onProposals: { path.append(.proposals) })
        case .routes, .matches, .orders:
            if driver.status?.isApproved == true {
                work
            } else {
                // Q96: until approved these tabs say why and what is next (the server refuses the work anyway).
                DriverGatedTab(tab: tab, driver: driver, onDocuments: openDocuments, onProfile: openForm,
                               onSupport: { path.append(.support) })
                    .id(tab)
            }
        case .profile:
            DriverProfileMenu(driver: driver, session: session, onAction: menuAction)
        }
    }

    /// Stage 08: the approved driver's trips, feed and orders.
    @ViewBuilder
    private var work: some View {
        switch tab {
        case .routes:
            TripsTabView(trips: trips, onAdd: openAddTrip) { path.append(.trip($0)) }
        case .matches:
            FeedTabView(feed: feed, onPickEnd: { path.append(.feedEnd(origin: $0)) }, onSaved: { path.append(.savedRoutes) }) { item in
                feed.forgetOffer(item.listing.id)
                path.append(.offer(item.listing.id))
            }
        default:
            DriverOrdersTab(proposals: proposals) { path.append(.proposals) }
        }
    }

    private func openAddTrip() {
        addTrip.reset(vehicles: (driver.vehicles ?? []).filter { $0.verificationStatus == "approved" })
        path.append(.addTrip)
    }

    /// A saved trip: back to the offer it was planned for, or on to its detail.
    private func tripSaved(_ trip: TripDTO) {
        trips.added(trip)
        container.banners.ok("addRoute.added")
        if !path.isEmpty { path.removeLast() }
        if case .offer? = path.last { return }
        path.append(.trip(trip.id))
    }

    /// After an offer: its thread replaces the offer screen, with "Taklif yuborildi" and any price advice.
    private func offerSent(_ thread: ProposalThreadDTO?, id: String, warnings: [ApiWarning]) {
        let model = proposals.thread(id, initial: thread)
        model.adopt(warnings)
        if thread != nil { container.banners.ok("driverBid.sent") }
        if !path.isEmpty { path.removeLast() }
        path.append(.thread(id))
        Task { await proposals.load(.open) }
    }

    @ViewBuilder
    private func screen(_ route: DriverRoute) -> some View {
        let back = { if !path.isEmpty { path.removeLast() } }
        switch route {
        case .profileForm:
            DriverProfileFormView(driver: driver, form: form, onBack: back)
        case .documents:
            DriverDocumentsView(driver: driver, mediaURL: { [transport = container.transport] in transport.mediaURL($0) }, onBack: back)
        case .notifications:
            NotificationsView(model: inbox, leading: .back, onLeading: back, onOpen: openTarget)
        case .support:
            // The same screen with the driver's questions (`driver.faq*`) instead of the client's.
            SupportView(model: support, leading: .back, onLeading: back, faqPrefix: "driver.faq") { path.append(.supportThreads) }
        case .supportThreads:
            SupportThreadsView(model: threads, onBack: back) { path.append(.supportThread($0)) }
        case .supportThread(let id):
            SupportChatView(model: supportChats.model(id), onBack: back, title: strings.t("support.threadTitle"))
        case .safetyCenter:
            SafetyCenterView(model: safety, onBack: back)
        case .settings:
            SettingsView(leading: .back, onLeading: back, onHelp: { path.append(.support) },
                         onDeleteAccount: {
                             accountDelete.confirmed = false
                             path.append(.accountDelete)
                         },
                         onLogout: { confirmLogout = true })
        case .accountDelete:
            AccountDeleteView(model: accountDelete, onBack: back) {
                let notice = strings.t("client.accountDelete.done")
                Task { await container.endDeletedSession(notice: notice) }
            }
        case .trip(let id):
            TripDetailView(model: trips.detail(id), trips: trips, onBack: back)
        case .addTrip:
            AddTripView(model: addTrip, driver: driver, onBack: back, onSaved: tripSaved)
        case .feedEnd(let origin):
            FeedEndPickerView(feed: feed, origin: origin, onDone: back)
        case .savedRoutes:
            SavedRoutesView(model: saved, feed: feed, onBack: back)
        case .offer(let id):
            if let model = feed.offer(id, keys: driver.keys) {
                OfferView(model: model, trips: trips, onBack: back, onAddTrip: openAddTrip) { thread, threadId, warnings in
                    offerSent(thread, id: threadId, warnings: warnings)
                }
            }
        case .proposals:
            DriverProposalsView(model: proposals, onBack: back) { thread in path.append(.thread(thread.id)) ; _ = proposals.thread(thread.id, initial: thread) }
        case .thread(let id):
            DriverThreadView(model: proposals.thread(id), onBack: back)
        }
    }

    private func openForm() { path.append(.profileForm) }
    private func openDocuments() { path.append(.documents) }

    private func menuAction(_ action: DriverProfileMenu.Action) {
        switch action {
        case .form: openForm()
        case .documents: openDocuments()
        case .notifications: path.append(.notifications)
        case .help: path.append(.support)
        case .threads: path.append(.supportThreads)
        case .safety: path.append(.safetyCenter)
        case .settings: path.append(.settings)
        case .logout: confirmLogout = true
        }
    }

    /// A driver's notification (already marked read by the list): an operator chat opens; bookings, listings and trips
    /// have no driver screen yet (Stage 08+), so those stay on the list.
    private func openTarget(_ target: InboxTarget) {
        if case .supportThread(let id) = target { path.append(.supportThread(id)) }
    }

    private func takeLinks() {
        let links = container.links
        if links.takeReferralArrival() {
            confirmLogout = false
            tab = .home
            path = []
        }
        if case .open(.supportThread(let id))? = links.takePending(for: .driver) {
            confirmLogout = false
            path = [.supportThread(id)]
        }
    }

    /// The kept link code, as the driver's (`audience: driver`). Accepted -> "Taklif kodi qabul qilindi" and the code
    /// goes; programme off -> that sentence and the code stays; invalid / not eligible -> the server's sentence and
    /// the code goes; offline or a 5xx -> the error, the code stays (the same key on the next tap).
    private func applyReferral() async {
        let links = container.links
        let banners = container.banners
        guard let code = links.referralCode, !applyingReferral else { return }
        applyingReferral = true
        defer { applyingReferral = false }
        let action = "attribute:driver:\(code)"
        do {
            _ = try await container.api.attribute(body: AttributionRequest(audience: "driver", code: code),
                                                  idempotencyKey: driver.keys.key(action))
            driver.keys.settle(action)
            links.forgetReferral()
            banners.ok("link.referralApplied")
        } catch {
            driver.keys.settle(action, after: error)
            if PromoLogic.isProgramOff(error) {
                banners.show(.key("promoScreen.programOff"), tone: .warn)
            } else {
                banners.error(error)
            }
            if ReferralOutcome.decision(error) == .forget { links.forgetReferral() }
        }
    }

    private func logout() {
        confirmLogout = false
        Task { await container.signOut() }
    }
}

// MARK: - Tab bar

/// The bottom navigation: five equal items, the current one in brand colour (icon) and azure-ink label.
struct DriverTabBar: View {
    let selected: DriverTab
    let onSelect: (DriverTab) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        HStack(spacing: 0) {
            ForEach(DriverTab.allCases, id: \.self) { tab in
                let active = tab == selected
                Button { onSelect(tab) } label: {
                    VStack(spacing: 4) {
                        tab.icon.image(size: 22).foregroundStyle(active ? c.brand : c.placeholder)
                        Text(strings.t(tab.labelKey)).font(ElchiFont.poppins(10, active ? .semibold : .medium))
                            .foregroundStyle(active ? c.accentText : c.placeholder)
                            .lineLimit(1).minimumScaleFactor(0.8)
                    }
                    .frame(maxWidth: .infinity, minHeight: 56)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(strings.t(tab.labelKey))
                .accessibilityAddTraits(active ? [.isButton, .isSelected] : .isButton)
                .accessibilityIdentifier("elchi.tab.\(tab.rawValue)")
            }
        }
        .padding(.horizontal, 6)
        .frame(height: 70)
        .background {
            UnevenRoundedRectangle(topLeadingRadius: 24, topTrailingRadius: 24)
                .fill(c.card)
                .shadow(color: c.shadow, radius: 12, y: -6)
                .ignoresSafeArea(edges: .bottom)
        }
    }
}
