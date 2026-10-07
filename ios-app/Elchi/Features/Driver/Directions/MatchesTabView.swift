import SwiftUI

/// The two segments of the Moslar tab (Safar v3 0.1): the direction feed and the driver's directions.
enum MatchesSegment: String, Hashable, Sendable {
    case requests, directions
}

/// Moslar (design v3): title "Mos buyurtmalar" on both segments; the "Takliflarim" pill on the feed, "+" on the
/// directions; the segmented control "Buyurtmalar (n) | Yo'nalishlarim (n)". The corridor district search and the
/// saved-routes entry are gone (Safar 5.1): the feed is "everything for my directions".
struct MatchesTabView: View {
    let directions: DirectionsModel
    let trips: TripsModel
    /// The flags (`passenger_enabled`: the Pochta / Taksi switch, K7) and the catalogue.
    let feed: FeedModel
    let proposals: DriverProposalsModel
    @Binding var segment: MatchesSegment
    let onAdd: () -> Void
    let onProposals: () -> Void
    let onOpenListing: (DirectionRequestItemDTO) -> Void
    let onOffer: (DirectionRequestItemDTO) -> Void
    let onThread: (String) -> Void
    let onOpenTrip: (String) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    private var service: ServiceType { DirectionFeed.service(passengerAllowed: feed.passengerAllowed, passenger: feed.filter.passenger) }

    var body: some View {
        @Bindable var feed = feed
        let countered = (proposals.lists[.open]?.value ?? []).filter { ProposalBadge.of($0) == .countered }.count
        DriverTabScreen(title: strings.t("driverFeed.title"),
                        plus: segment == .directions ? (strings.t("driverRoutes.addRoute"), onAdd) : nil,
                        trailing: segment == .requests
                            ? AnyView(TabPill(icon: .tag, title: strings.t("proposals.title"), badge: countered > 0 ? "\(countered)" : nil,
                                              action: onProposals)
                                .accessibilityIdentifier("elchi.feed.proposals"))
                            : nil) {
            SegmentBar(segment: $segment, requests: requestCount, directions: directionCount)
            switch segment {
            case .requests:
                if feed.passengerAllowed {
                    Segmented([(false, strings.t("driverFeed.modeParcel")), (true, strings.t("driverFeed.modeTaxi"))],
                              selected: feed.filter.passenger) { feed.filter.passenger = $0 }
                }
                DirectionFeedSection(model: directions, service: service, proposals: proposals, onAdd: onAdd, onOpen: onOpenListing,
                                     onOffer: onOffer, onThread: onThread)
            case .directions:
                DirectionsListSection(model: directions, trips: trips, onAdd: onAdd,
                                      onOpenRequests: { id in
                                          directions.activeId = id
                                          segment = .requests
                                      },
                                      onOpenTrip: onOpenTrip)
            }
        }
        .refreshable { await refresh() }
        .task {
            await feed.loadFlags()
            async let list: Void = directions.load()
            async let trips: Void = self.trips.load()
            async let open: Void = proposals.load(.open)
            async let accepted: Void = proposals.load(.accepted)
            _ = await (list, trips, open, accepted)
        }
    }

    private func refresh() async {
        async let list: Void = directions.load()
        async let trips: Void = self.trips.load()
        async let open: Void = proposals.load(.open)
        async let accepted: Void = proposals.load(.accepted)
        _ = await (list, trips, open, accepted)
        await directions.loadFeed(service: service)
    }

    /// Safar 0.2: the main cards of the loaded feed (fits + new trip) and the active directions; hidden at 0.
    private var requestCount: Int {
        guard let page = directions.feed?.value else { return 0 }
        let groups = DirectionFeed.groups(page.items)
        return groups.fits.count + groups.fresh.count
    }

    private var directionCount: Int { directions.directions.filter { $0.status == "active" }.count }
}

/// "Buyurtmalar (n) | Yo'nalishlarim (n)": the pill track, the chosen segment raised, a count badge (navy on the
/// chosen one).
struct SegmentBar: View {
    @Binding var segment: MatchesSegment
    let requests: Int
    let directions: Int
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        HStack(spacing: 4) {
            item(.requests, strings.t("app.nav.orders"), requests)
            item(.directions, strings.t("driverRoutes.title"), directions)
        }
        .padding(4)
        .background(c.track, in: Capsule())
        .accessibilityIdentifier("elchi.matches.segments")
    }

    private func item(_ value: MatchesSegment, _ title: String, _ count: Int) -> some View {
        let on = segment == value
        return Button { segment = value } label: {
            HStack(spacing: 6) {
                Text(title).font(ElchiFont.poppins(14, on ? .semibold : .medium)).lineLimit(1).minimumScaleFactor(0.8)
                if count > 0 {
                    Text("\(count)").font(ElchiFont.poppins(11, .bold))
                        .foregroundStyle(on ? Color.white : c.tone(.gray).noteText)
                        .padding(.horizontal, 6)
                        .frame(minWidth: 20, minHeight: 20)
                        .background(on ? c.primaryV3 : c.outline, in: Capsule())
                }
            }
            .foregroundStyle(on ? c.text : c.muted)
            .frame(maxWidth: .infinity, minHeight: 40)
            .background(on ? c.card : .clear, in: Capsule())
            .shadow(color: on ? c.softShadow : .clear, radius: 2, y: 1)
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(count > 0 ? "\(title), \(count)" : title)
        .accessibilityAddTraits(on ? [.isButton, .isSelected] : .isButton)
        .accessibilityIdentifier("elchi.matches.segment.\(value.rawValue)")
    }
}
