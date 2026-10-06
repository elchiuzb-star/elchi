import SwiftUI

// MARK: - Buyurtmalar

/// The client's orders: bookings, its own listings (with views and live-offer counts), legacy v1 orders. Pull to
/// refresh; a section that fails says so without blanking the others. A section of the app (menu, not back); the bar's
/// bell (with the unread count) pushes the notifications. "Takliflarim" lives in the drawer (BOSQICH 03).
struct OrdersView: View {
    let model: ClientOrdersModel
    let inbox: InboxModel
    let onMenu: () -> Void
    let onNotifications: () -> Void
    let onNewOrder: () -> Void
    let onOpenListing: (String) -> Void
    let onOpenBooking: (String) -> Void
    /// A v1 order's archive detail (Stage 06).
    let onOpenLegacy: (Int) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        ScreenScaffold(title: strings.t("orders.title"), leading: .menu, backLabel: strings.t("nav.menu"), onBack: onMenu,
                       showsFooter: model.isEmpty, banner: model.banner.map { ($0, Tone.ok) }, actions: [bell], largeTitle: true) {
            if model.isEmpty {
                EmptyState(icon: .pkg, title: strings.t("orders.empty"), description: strings.t("client.orders.emptyText"))
            } else if model.bookings.value == nil && model.listings.value == nil && model.legacy.value == nil && !anyFailed {
                SkeletonCards(count: 3)
            } else {
                if anyFailed { Note(strings.t("client.orders.partialFailed"), tone: .err) }
                bookings
                listings
                legacy
                if model.hasMore {
                    // Asks again after every page (the marker changes) while pages remain.
                    ProgressView().frame(maxWidth: .infinity).padding(.vertical, 8)
                        .task(id: model.pageMarker) { await model.loadMore() }
                }
            }
        } footer: {
            if model.isEmpty { ElchiButton(strings.t("nav.homeHint"), action: onNewOrder) }
        }
        .refreshable {
            async let unread: Void = inbox.refreshUnread()
            await model.refresh()
            await unread
        }
        .task { await model.refresh() }
        .task { await inbox.refreshUnread() }
        .onDisappear { model.banner = nil }
    }

    private var bell: BarAction {
        let count = inbox.unread > 0 ? (inbox.unreadMore ? "\(inbox.unread)+" : "\(inbox.unread)") : nil
        return BarAction(id: "notifications", icon: .bell, label: strings.t("notifications.title"), badge: count, action: onNotifications)
    }

    private var anyFailed: Bool {
        if model.stale { return true }
        if case .failed = model.bookings { return true }
        if case .failed = model.listings { return true }
        if case .failed = model.legacy { return true }
        return false
    }

    @ViewBuilder
    private var bookings: some View {
        if let items = model.bookings.value, !items.isEmpty {
            SectionTitle(strings.t("client.orders.bookings"))
            ForEach(items) { booking in
                let status = strings.status(.clientBooking(booking.serviceType, booking.serviceStatus))
                // "29 sen, 10:00–12:00": the agreed pickup window.
                let meta = strings.dayWindow(booking.pickup.windowStart, booking.pickup.windowEnd)
                    ?? ServerTime.parse(booking.createdAt).map(strings.dayMonth)
                ItemCard(title: strings.route(booking), icon: .pin, badge: status, meta: meta,
                         right: strings.bookingPrice(booking)) { onOpenBooking(booking.id) }
            }
        }
    }

    @ViewBuilder
    private var listings: some View {
        if let items = model.listings.value, !items.isEmpty {
            SectionTitle(strings.t("client.orders.listings"))
            ForEach(items, id: \.id) { listing in
                ListingSummaryCard(listing: listing, stats: model.stats[listing.id]) { onOpenListing(listing.id) }
            }
        }
    }

    @ViewBuilder
    private var legacy: some View {
        if let items = model.legacy.value, !items.isEmpty {
            SectionTitle(strings.t("orders.legacy"))
            ForEach(items) { order in
                // Bids matter only while the order still takes them.
                let bids = LegacyActions.bidsOpen(order.status) ? order.bidsCount ?? 0 : 0
                ItemCard(title: strings.route(order), badge: strings.status(.legacy(order.status)),
                         lines: bids > 0 ? [ItemLine(strings.t("app.orderCard.bids", ("count", bids)))] : [],
                         meta: ServerTime.parse(order.createdAt).map { "\(strings.dayMonth($0)) · \(strings.t("client.listing.legacyArchive"))" },
                         right: order.priceMinor.map(strings.money),
                         action: { onOpenLegacy(order.id) })
                .accessibilityIdentifier("elchi.legacy.\(order.id)")
            }
        }
    }
}

/// A listing as the list shows it: route, status, "date · views · offers", then "Yangi taklif: …" (blue while an
/// open offer waits) / "Haydovchi tanlandi" / "E'lon amal qiladi: … gacha", and the price.
struct ListingSummaryCard: View {
    let listing: ListingDTO
    let stats: OfferStats?
    var action: (() -> Void)?
    @Environment(LocaleStore.self) private var strings

    var body: some View {
        let meta = ListingMeta.of(listing, stats: stats)
        ItemCard(title: strings.route(listing), badge: strings.status(.listing(listing.status)),
                 lines: [ItemLine(line)] + (strings.peopleLine(listing).map { [ItemLine($0)] } ?? []),
                 meta: meta.map(strings.listingMeta), right: strings.money(listing.totalMinor), metaAccent: meta?.highlighted == true,
                 action: action)
    }

    /// Offers exist only on a published or paused listing; a closed one shows no counts.
    private var live: Bool { listing.status == .published || listing.status == .paused }

    private var line: String {
        var parts: [String] = []
        if let start = ServerTime.parse(listing.departureWindowStart) { parts.append(strings.dayMonth(start)) }
        parts.append(strings.views(listing.viewCount))
        if let stats, live {
            parts.append(strings.t("app.orderCard.bids", ("count", stats.open)))
        }
        return parts.joined(separator: " · ")
    }
}

// MARK: - Takliflarim

/// Every negotiation the client is part of, as the same offer cards as a listing's (route first), with the bar's
/// refresh icon. No sort chips: live negotiations first, in the server's order.
struct ProposalsView: View {
    let model: ProposalsModel
    let onBack: () -> Void
    let onAccepted: (String, ClientBookingDTO) -> Void
    @Environment(LocaleStore.self) private var strings
    @State private var counterFor: String?
    @State private var accepting: ProposalThreadDTO?
    @State private var now = Date()

    var body: some View {
        ScreenScaffold(title: strings.t("proposals.title"), backLabel: strings.t("common.back"), onBack: onBack,
                       actions: [BarAction(id: "refresh", icon: .refresh, label: strings.t("proposal.refresh")) { Task { await model.load() } }]) {
            switch model.offers.threads {
            case .loading:
                SkeletonCards(count: 3)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err)
                ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.load() } }
            case .loaded(let threads):
                if threads.isEmpty {
                    EmptyState(icon: .tag, title: strings.t("client.proposals.emptyTitle"), description: strings.t("client.proposals.emptyText"))
                } else {
                    // The server's order (newest first), live negotiations before closed ones.
                    let live = threads.filter { NegotiationActions.of($0, now: now).open }
                    ForEach(live + threads.filter { t in !live.contains { $0.id == t.id } }, id: \.id) { thread in
                        OfferCard(thread: thread, listing: model.listings[thread.listingId], style: .proposals, offers: model.offers, now: now,
                                  badge: thread.driverCountered(now: now) ? .counter : nil, counterOpen: counterFor == thread.id,
                                  onCounter: { counterFor = $0 ? thread.id : nil }, onAccept: { accepting = thread })
                    }
                    Note(strings.t("listingBids.identityHidden"))
                }
            }
        } footer: {
            EmptyView()
        }
        .refreshable { await model.load() }
        .task { await model.load() }
        .task { await tick() }
        .overlay {
            if let thread = accepting {
                AcceptDialog(thread: thread, listing: model.listings[thread.listingId], offers: model.offers, onClose: { accepting = nil }) { onAccepted(thread.listingId, $0) }
            }
        }
    }

    private func tick() async {
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(1))
            now = Date()
        }
    }
}
