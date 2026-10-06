import SwiftUI

// MARK: - Moslar (feed)

/// The requests that match the driver's route (`side=requests`, alternatives always asked for, Q97): the route filter
/// (region -> district per end), the date chips, the notes, then the primary matches and, under their own heading,
/// the dashed alternatives with their reason.
struct FeedTabView: View {
    let feed: FeedModel
    /// DESIGN07: the driver's offers (the bar's "Takliflarim" count, "you already offered" on the cards).
    let proposals: DriverProposalsModel
    /// DESIGN07 5.4: "Saqlangan yo'nalishlar ({count})".
    let saved: SavedRoutesModel
    let onPickEnd: (Bool) -> Void
    let onSaved: () -> Void
    /// The bar's "Takliflarim" pill.
    var onProposals: () -> Void = {}
    /// "Taklifni ko'rish": the driver's thread on that request.
    var onThread: (String) -> Void = { _ in }
    /// ADR-0027: the direction feed - the main answer, above the district search (which stays as "all requests").
    var directions: AnyView?
    /// Pull-to-refresh also reads the direction feed again.
    var onRefresh: (() async -> Void)?
    let onOffer: (FeedItemDTO) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        @Bindable var feed = feed
        let countered = (proposals.lists[.open]?.value ?? []).filter { ProposalBadge.of($0) == .countered }.count
        DriverTabScreen(title: strings.t("driverFeed.title"),
                        trailing: AnyView(TabPill(icon: .tag, title: strings.t("proposals.title"), badge: countered > 0 ? "\(countered)" : nil,
                                                  action: onProposals)
                            .accessibilityIdentifier("elchi.feed.proposals"))) {
            if feed.passengerAllowed {
                Segmented([(false, strings.t("driverFeed.modeParcel")), (true, strings.t("driverFeed.modeTaxi"))],
                          selected: feed.filter.passenger) { feed.filter.passenger = $0 }
            }
            if let directions {
                directions
                SectionTitle(strings.t("dir.districtSearch")).padding(.top, 6)
                    .accessibilityIdentifier("elchi.feed.districtSearch")
            }
            RouteCard(from: end(feed.filter.origin, question: "driverFeed.from", origin: true),
                      to: end(feed.filter.destination, question: "driverFeed.to", origin: false))
                .accessibilityIdentifier("elchi.feed.route")
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(FeedDateChip.allCases, id: \.self) { chip in
                        Chip(strings.t(chip.labelKey), selected: feed.filter.chip == chip, filled: true) { feed.filter.chip = chip }
                    }
                }
            }
            Text(strings.t("driverFeed.districtHint")).font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
            ElchiButton(saved.list.value.map { strings.t("driver.feed.savedCount", ("count", $0.count)) } ?? strings.t("driverFeed.savedSearches"),
                        variant: .outline, size: .medium, icon: .route, action: onSaved)
                .accessibilityIdentifier("elchi.feed.saved")
            results
        }
        .refreshable {
            async let list: Void = self.feed.load()
            async let offers: Void = loadOffers()
            await onRefresh?()
            _ = await (list, offers)
        }
        .task {
            async let offers: Void = loadOffers()
            async let routes: Void = saved.load()
            await feed.loadFlags()
            await feed.load()
            _ = await (offers, routes)
        }
        .onChange(of: feed.filter) { _, _ in Task { await feed.load() } }
    }

    /// The open and accepted offers, for the cards' "already offered" mark and the bar's count.
    private func loadOffers() async {
        async let open: Void = proposals.load(.open)
        async let accepted: Void = proposals.load(.accepted)
        _ = await (open, accepted)
    }

    private func mark(_ item: FeedItemDTO) -> FeedOfferMark {
        FeedOfferMark.of(listingId: item.listing.id, open: proposals.lists[.open]?.value, accepted: proposals.lists[.accepted]?.value,
                         versions: { proposals.versions($0) })
    }

    private func end(_ end: FeedEnd?, question: String, origin: Bool) -> RouteCard.End {
        guard let end else {
            return RouteCard.End(title: strings.t(question), detail: nil, isSet: false, label: strings.t(question)) { onPickEnd(origin) }
        }
        let region = strings.locale == .ru ? end.regionNameRu ?? end.regionName : end.regionName
        let district = end.districtName.map { strings.locale == .ru ? end.districtNameRu ?? $0 : $0 }
        return RouteCard.End(title: region, detail: district, isSet: true, label: strings.t(question)) { onPickEnd(origin) }
    }

    @ViewBuilder
    private var results: some View {
        switch feed.items {
        case nil:
            EmptyState(icon: .radar, title: strings.t("driverFeed.emptyTitle"), description: strings.t("driverFeed.emptyPickFirst"))
        case .loading?:
            SkeletonCards(count: 3)
        case .failed(let error)?:
            Note(strings.errorText(error), tone: .err)
            ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await feed.load() } }
        case .loaded(let items)?:
            Note(strings.t("match.confirmedStopsNote"), tone: .warn)
            ForEach(feed.degraded, id: \.self) { code in
                Text(strings.tOrNil("warning.\(code)") ?? code).font(ElchiFont.caption).foregroundStyle(c.muted)
            }
            let groups = FeedGroups.split(items)
            if items.isEmpty {
                EmptyState(icon: .radar, title: strings.t("driverFeed.emptyTitle"), description: strings.t("driver.feed.emptyHint"))
            }
            ForEach(groups.primary, id: \.listing.id) { FeedCard(item: $0, alternative: false, mark: mark($0), onOffer: onOffer, onThread: onThread) }
            if !groups.alternative.isEmpty {
                SectionTitle(strings.t("match.alternativesTitle"), description: strings.t("match.alternativesNote"))
                    .accessibilityIdentifier("elchi.feed.alternatives")
                ForEach(groups.alternative, id: \.listing.id) { FeedCard(item: $0, alternative: true, mark: mark($0), onOffer: onOffer, onThread: onThread) }
            }
            if feed.nextCursor != nil {
                ElchiButton(strings.t("blockReport.loadMore"), variant: .ghost, size: .medium, loading: feed.loadingMore) {
                    Task { await feed.loadMore() }
                }
            }
        }
    }
}

/// One request: route (stop or district names, never a street address), the match badge (or the alternative's
/// reason), the window, the parcel category and its limits, the client's total, "Taklif yuborish".
struct FeedCard: View {
    let item: FeedItemDTO
    let alternative: Bool
    /// DESIGN07 5.7: the driver's own offer on this request, if any.
    var mark: FeedOfferMark = .none
    let onOffer: (FeedItemDTO) -> Void
    var onThread: (String) -> Void = { _ in }
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        let listing = item.listing
        // Meta left (my offer / accepted), the client's price right, then one full-width button.
        let card = ItemCard(title: strings.route(listing), icon: .pin, badge: badge, lines: lines, meta: meta,
                            right: strings.money(listing.totalMinor), metaAccent: mark != .none) {
            if let threadId = mark.threadId {
                ElchiButton(strings.t("driver.feed.viewOffer"), variant: .neutral, size: .medium) { onThread(threadId) }
                    .padding(.top, 6)
                    .accessibilityIdentifier("elchi.feed.viewOffer.\(listing.id)")
            } else {
                ElchiButton(strings.t("driverFeed.sendOffer"), variant: alternative ? .outline : .primary, size: .medium) { onOffer(item) }
                    .padding(.top, 6)
                    .accessibilityIdentifier("elchi.feed.offer.\(listing.id)")
            }
        }
        if alternative {
            card.overlay {
                RoundedRectangle(cornerRadius: ElchiShape.card).strokeBorder(c.outline, style: StrokeStyle(lineWidth: 1.5, dash: [6, 4]))
            }
        } else {
            card
        }
    }

    private var meta: String? {
        switch mark {
        case .none: nil
        case .offered(_, let total): strings.t("driver.feed.myOffer", ("price", strings.money(total)))
        case .countered: strings.t("negotiation.clientCountered")
        case .accepted: strings.t("driver.feed.clientAccepted")
        }
    }

    private var badge: (text: String, tone: Tone)? {
        if alternative {
            guard let reason = FeedGroups.alternativeReason(item.match.reasons) else { return (strings.t("match.alternative"), .warn) }
            return (strings.t("match.reason.\(reason.rawValue)"), .warn)
        }
        switch item.match.matchType {
        case .exact: return (strings.t("match.exact"), .ok)
        case .onRoute: return (strings.t("match.on_route"), .blue)
        default: return nil
        }
    }

    private var lines: [ItemLine] {
        let listing = item.listing
        return [ItemLine(strings.span(listing.departureWindowStart, listing.departureWindowEnd)), strings.parcelLine(listing).map { ItemLine($0) }]
            .compactMap { $0 }
    }
}

// MARK: - Choosing an end

/// Region, then district (required where the region asks for one; Tashkent city is a unit of its own).
struct FeedEndPickerView: View {
    let feed: FeedModel
    let origin: Bool
    let onDone: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var region: RegionDTO?
    @State private var query = ""

    var body: some View {
        ScreenScaffold(title: region.map { strings.name($0) } ?? strings.t(origin ? "driverFeed.from" : "driverFeed.to"),
                       right: region == nil ? nil : strings.t("location.pickDistrict"), backLabel: strings.t("common.back"),
                       onBack: { if region != nil { region = nil; query = "" } else { onDone() } }) {
            ElchiField(text: $query, placeholder: strings.t("location.search"), icon: .search)
            if let region { districts(region) } else { regions }
        } footer: {
            EmptyView()
        }
        .task { await feed.loadRegions() }
    }

    @ViewBuilder
    private var regions: some View {
        switch feed.regions {
        case .loading:
            SkeletonCards(count: 2)
        case .failed(let error):
            Note(strings.errorText(error), tone: .err, title: strings.t("location.regionsLoadFailed"))
            ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await feed.loadRegions() } }
        case .loaded(let list):
            let shown = list.filter { SearchText.matches(strings.name($0), query) || SearchText.matches($0.nameUz, query) }
            ElchiList {
                ForEach(Array(shown.enumerated()), id: \.element.id) { index, region in
                    ListRow(icon: .pin, title: strings.name(region),
                            description: strings.t(region.requiresDistrict == false ? "location.noDistrict" : "location.districtRequired"),
                            first: index == 0) { pick(region) }
                }
            }
        }
    }

    @ViewBuilder
    private func districts(_ region: RegionDTO) -> some View {
        switch feed.districts[region.id] ?? .loading {
        case .loading:
            SkeletonCards(count: 2)
        case .failed(let error):
            Note(strings.errorText(error), tone: .err, title: strings.t("location.districtsLoadFailed"))
        case .loaded(let list):
            let shown = list.filter { $0.isActive != false && (SearchText.matches(strings.name($0), query) || SearchText.matches($0.nameUz, query)) }
            ElchiList {
                ForEach(Array(shown.enumerated()), id: \.element.id) { index, district in
                    ListRow(title: strings.name(district), first: index == 0) {
                        feed.setEnd(FeedEnd(regionId: region.id, regionName: region.nameUz, regionNameRu: region.nameRu, districtId: district.id,
                                            districtName: district.nameUz, districtNameRu: district.nameRu), origin: origin)
                        onDone()
                    }
                }
            }
        }
    }

    private func pick(_ picked: RegionDTO) {
        if picked.requiresDistrict == false {
            feed.setEnd(FeedEnd(regionId: picked.id, regionName: picked.nameUz, regionNameRu: picked.nameRu), origin: origin)
            onDone()
        } else {
            query = ""
            region = picked
            Task { await feed.loadDistricts(picked) }
        }
    }
}

// MARK: - Saqlangan yo'nalishlar

/// Saved routes: a new request on one of them sends an in-app notification (always on; no toggle).
struct SavedRoutesView: View {
    let model: SavedRoutesModel
    let feed: FeedModel
    let onBack: () -> Void
    /// DESIGN07 6.5: "Lentada ochish" set the feed's ends; back to the feed.
    var onOpenInFeed: () -> Void = {}
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(BannerCenter.self) private var banners: BannerCenter?
    @State private var confirming: SavedSearchDTO?

    var body: some View {
        ScreenScaffold(title: strings.t("savedSearches.title"), backLabel: strings.t("common.back"), onBack: onBack) {
            Text(strings.t("savedSearches.intro")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
            ElchiCard {
                CardRow(strings.t("savedSearches.currentDirection"), current ?? strings.t("savedSearches.pickEndsFirst"), first: true,
                        placeholder: current == nil)
            }
            let state = SavedRoute.state(feed.filter, passengerAllowed: feed.passengerAllowed, saved: model.list.value)
            ElchiButton(strings.t(state == .alreadySaved ? "driver.routes.alreadySaved" : "savedSearches.save"), loading: model.saving) {
                Task { await model.save(feed.filter, passengerAllowed: feed.passengerAllowed) }
            }
            .disabled(state != .canSave || model.list.value == nil)
            .accessibilityIdentifier("elchi.saved.save")
            if let error = model.error { Note(strings.marketErrorText(error), tone: .err).accessibilityIdentifier("elchi.saved.error") }
            switch model.list {
            case .loading:
                SkeletonCards(count: 2)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err)
            case .loaded(let list) where list.isEmpty:
                EmptyState(icon: .route, title: strings.t("savedSearches.emptyTitle"), description: strings.t("savedSearches.emptySubtitle"))
            case .loaded(let list):
                ForEach(list, id: \.id) { saved in
                    ItemCard(title: name(saved), icon: .route,
                             sub: "\(strings.windowDays(saved.timeWindowStart, saved.timeWindowEnd)) · \(strings.t("savedSearches.notifyOn"))") {
                        let target = SavedRoute.feedFilter(from: saved, current: feed.filter, regions: feed.regions.value ?? [],
                                                           districts: feed.districtNames)
                        HStack(spacing: 8) {
                            ElchiButton(strings.t("driver.routes.openInFeed"), variant: .soft, size: .pair) {
                                guard let target else { return }
                                feed.filter = target
                                banners?.show(.template("driver.routes.openedInFeed", values: ["name": endName(target.destination)]), tone: .ok)
                                onOpenInFeed()
                            }
                            .disabled(target == nil)
                            .accessibilityIdentifier("elchi.saved.open.\(saved.id)")
                            ElchiButton(strings.t("common.delete"), variant: .dangerSoft, size: .pair, loading: model.deleting == saved.id) {
                                confirming = saved
                            }
                        }
                        .padding(.top, 6)
                    }
                    .accessibilityIdentifier("elchi.saved.\(saved.id)")
                }
            }
            Text(strings.t("driver.saved.notifyNote")).font(ElchiFont.caption).foregroundStyle(c.muted)
            Text(model.list.value.map { strings.t("driver.routes.limitCount", ("limit", SavedRoute.limit), ("count", $0.count)) }
                    ?? strings.t("driver.saved.limitHint", ("limit", SavedRoute.limit)))
                .font(ElchiFont.caption).foregroundStyle(c.muted)
                .accessibilityIdentifier("elchi.saved.limit")
        } footer: {
            EmptyView()
        }
        .refreshable { await model.load() }
        .task {
            await model.load()
            await feed.loadRegions()
            await feed.loadAllDistricts()
        }
        .overlay {
            if let saved = confirming {
                DialogOverlay(dismissLabel: strings.t("confirmDialog.back"), onDismiss: { confirming = nil }) {
                    Text(name(saved)).font(ElchiFont.poppins(18, .medium)).foregroundStyle(c.text)
                    ElchiButton(strings.t("common.delete"), variant: .danger) {
                        confirming = nil
                        Task { await model.delete(saved.id) }
                    }
                    .accessibilityIdentifier("elchi.saved.confirmDelete")
                    ElchiButton(strings.t("confirmDialog.back"), variant: .neutral, size: .medium) { confirming = nil }
                }
            }
        }
    }

    private func endName(_ end: FeedEnd?) -> String {
        guard let end else { return "…" }
        if let district = end.districtName { return strings.locale == .ru ? end.districtNameRu ?? district : district }
        return strings.locale == .ru ? end.regionNameRu ?? end.regionName : end.regionName
    }

    private var current: String? {
        guard let origin = feed.filter.origin, let destination = feed.filter.destination else { return nil }
        return "\(origin.districtName ?? origin.regionName) → \(destination.districtName ?? destination.regionName)"
    }

    /// `Chilonzor → Samarqand shahri` from the saved ids (district names, else region names).
    private func name(_ saved: SavedSearchDTO) -> String {
        let regions = Dictionary((feed.regions.value ?? []).map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        func end(_ district: String?, _ region: String?) -> String {
            if let district, let found = feed.districtNames[district] { return strings.name(found) }
            if let region, let found = regions[region] { return strings.name(found) }
            return "…"
        }
        return "\(end(saved.originDistrictId, saved.originRegionId)) → \(end(saved.destinationDistrictId, saved.destinationRegionId))"
    }
}

// MARK: - Narx taklif qiling

/// Pricing one request: the summary, the anonymous rival board, the trip, the pickup window, the price (or the
/// client's price in one tap), the commission estimate (never blocking), and the no-hold note.
struct OfferView: View {
    let model: OfferModel
    let trips: TripsModel
    let onBack: () -> Void
    let onAddTrip: () -> Void
    let onThread: (ProposalThreadDTO?, String, [ApiWarning]) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var priceText = ""
    @State private var message = ""
    @State private var editingWindow: Edge?
    /// "Taklif yuborish" was tapped with no price (DESIGN07 7.11).
    @State private var priceMissing = false

    enum Edge: String, Identifiable {
        case start, end
        var id: String { rawValue }
    }

    var body: some View {
        let listing = model.listing
        let perSeat = PassengerMoney.perSeat(listing.priceBasis)
        // Taksi: the client's price is per seat; it reads "2 × 150 000 so'm", the total is the hint under the field.
        let clientPrice = perSeat ? strings.seatsTotal(max(listing.quantity, 1), unitMinor: listing.unitPriceMinor) : strings.money(listing.totalMinor)
        ScreenScaffold(title: strings.t("driverBid.title"), backLabel: strings.t("common.back"), onBack: onBack) {
            ElchiCard(tint: .field) {
                CardRow(strings.route(listing), strings.t("driverBid.clientPrice", ("price", clientPrice)), first: true,
                        detail: [perSeat ? strings.t("seatPicker.peopleCount", ("count", max(listing.quantity, 1))) : strings.parcelLine(listing),
                                 strings.t("driverBid.departure", ("start", time(listing.departureWindowStart)), ("end", time(listing.departureWindowEnd)))]
                            .compactMap { $0 }.joined(separator: " · "), strong: true)
            }
            board
            tripField
            if let window = model.window {
                ElchiCard(tint: .blue) {
                    CardRow(strings.t("driverBid.pickupWindow"), strings.span(window.start, window.end), first: true,
                            trailing: strings.t("app.route.change")) { editingWindow = .start }
                }
                .accessibilityIdentifier("elchi.offer.window")
            }
            ElchiField(text: $priceText, label: strings.t("driverBid.priceLabel") + (perSeat ? strings.t("listingEdit.perSeatSuffix") : ""),
                       placeholder: strings.t("driverBid.pricePlaceholder"),
                       hint: listing.priceBasis == .perSeat ? "\(strings.t("common.total")): \(strings.money(model.totalMinor))" : nil,
                       error: priceMissing && model.priceMinor <= 0 ? strings.t("driver.offer.priceRequired") : nil,
                       keyboard: .numberPad, suffix: strings.t("common.soum"))
                .onChange(of: priceText) { _, typed in
                    model.priceDigits = Money.soumDigits(typed)
                    let formatted = Money.grouped(model.priceDigits)
                    if priceText != formatted { priceText = formatted }
                }
            ElchiButton(strings.t("driver.bid.acceptClientPrice", ("price", clientPrice)), variant: .soft,
                        loading: model.sending && model.priceMinor == listing.unitPriceMinor) {
                Task { await send(listing.unitPriceMinor) }
            }
            .disabled(!canSend)
            .accessibilityIdentifier("elchi.offer.acceptClientPrice")
            commission
            ElchiField(text: $message, label: strings.t("listingOwner.commentLabel"), multiline: true)
            if let error = model.error { Note(strings.marketErrorText(error, seats: max(listing.quantity, 1)), tone: .err).accessibilityIdentifier("elchi.offer.error") }
            Text(strings.t("driverBid.noHoldNote")).font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
        } footer: {
            // Grey while the price is empty; a tap then marks the field (DESIGN07 7.11).
            ElchiButton(strings.t("driverBid.send"), loading: model.sending && model.priceMinor != listing.unitPriceMinor,
                        dimmed: model.priceMinor <= 0) {
                guard model.priceMinor > 0 else { priceMissing = true; return }
                Task { await send(model.priceMinor) }
            }
            .disabled(!canSend)
            .accessibilityIdentifier("elchi.offer.send")
        }
        .task {
            priceText = Money.grouped(model.priceDigits)
            async let board: Void = model.loadBoard()
            async let list = trips.offerable()
            model.setTrips(await list)
            _ = await board
        }
        .task(id: model.totalMinor) {
            try? await Task.sleep(for: .milliseconds(400))
            if !Task.isCancelled { await model.loadQuote(totalMinor: model.totalMinor) }
        }
        .sheet(item: $editingWindow) { edge in
            WindowPickerSheet(title: strings.t("driverBid.pickupWindow"),
                              initial: (edge == .start ? model.window?.start : model.window?.end) ?? Date()) { date in
                adjust(edge, to: date)
            }
        }
    }

    private var canSend: Bool { model.tripId != nil && model.window != nil && !model.sending }

    private func send(_ unitPriceMinor: Int) async {
        switch await model.send(unitPriceMinor: unitPriceMinor, message: message) {
        case .sent(let thread, let warnings)?: onThread(thread, thread.id, warnings)
        case .existing(let id)?: onThread(nil, id, [])
        case nil: break
        }
    }

    /// The driver may move the window, but only inside the request's own window (start first, then end).
    private func adjust(_ edge: Edge, to date: Date) {
        guard let bounds = model.requestWindow, var window = model.window else { editingWindow = nil; return }
        let clamped = min(max(date, bounds.start), bounds.end)
        if edge == .start {
            window.start = clamped
            if window.end <= window.start { window.end = min(bounds.end, window.start.addingTimeInterval(3600)) }
            model.window = window
            editingWindow = nil
            Task { @MainActor in
                try? await Task.sleep(for: .milliseconds(450))
                editingWindow = .end
            }
        } else {
            window.end = max(clamped, window.start.addingTimeInterval(60))
            model.window = window
            editingWindow = nil
        }
    }

    // MARK: Blocks

    private var board: some View { RivalBoardCard(board: model.board) }

    @ViewBuilder
    private var tripField: some View {
        switch model.trips {
        case .loading:
            SkeletonCards(count: 1)
        case .failed(let error):
            Note(strings.errorText(error), tone: .err)
        case .loaded(let list) where list.isEmpty:
            SelectField(label: strings.t("driverBid.trip"), options: [(String, String)](), selected: nil, placeholder: strings.t("driverBid.noPlannedTrips")) { _ in }
            Note(strings.t("driverBid.planTripFirst"), tone: .err).accessibilityIdentifier("elchi.offer.planTripFirst")
            ElchiButton(strings.t("driver.offer.planTrip"), variant: .soft, size: .medium, icon: .plus, action: onAddTrip)
        case .loaded(let list):
            SelectField(label: strings.t("driverBid.trip"), options: list.map { ($0.id, "\(strings.route($0)) · \(strings.tripMeta($0))") },
                        selected: model.tripId, placeholder: strings.t("driverBid.tripPlaceholder")) { model.choose($0) }
            if model.tripId != nil && model.window == nil {
                Note(strings.t("driverBid.tripWindowMismatch"), tone: .err)
            }
        }
    }

    private var commission: some View { CommissionCard(quote: model.quote, totalMinor: model.totalMinor) }

    private func time(_ text: String) -> String { ServerTime.parse(text).map(DepartureWindow.shortText) ?? "?" }
}


// MARK: - Shared offer-screen blocks (the trip offer and the ADR-0027 direction offer)

/// The anonymous rival board (Q40 / Q95): hidden when the endpoint is closed (nil).
struct RivalBoardCard: View {
    let board: Loadable<RivalBoard>?
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        if let board {
            ElchiCard {
                switch board {
                case .loading:
                    CardTitle(strings.t("app.rivalBoard.title"))
                    SkeletonCards(count: 1).padding(.bottom, 8)
                case .failed(let error):
                    CardTitle(strings.t("app.rivalBoard.title"))
                    Text(strings.errorText(error)).font(ElchiFont.caption).foregroundStyle(c.muted).padding(.bottom, 10)
                case .loaded(let board):
                    CardTitle(strings.t("app.rivalBoard.title"), badge: (strings.t("app.rivalBoard.count", ("count", board.count)), .blue))
                    if board.count == 0 {
                        Text(strings.t("app.rivalBoard.empty")).font(ElchiFont.caption).foregroundStyle(c.muted).padding(.bottom, 10)
                    } else {
                        if let cheapest = board.cheapestMinor {
                            CardRow(strings.t("app.rivalBoard.cheapest"), strings.money(cheapest), strong: true)
                        }
                        ForEach(board.rivals, id: \.label) { offer in
                            CardRow(offer.label, rivalLine(offer), detail: reputation(offer), trailing: strings.money(offer.totalMinor))
                        }
                        if let mine = board.mine {
                            CardRow(strings.t("app.rivalBoard.mine", ("price", strings.money(mine.totalMinor))), rivalLine(mine),
                                    detail: mine.responsePending == true ? strings.t("app.rivalBoard.countered") : nil, strong: true)
                        }
                    }
                }
            }
            .accessibilityIdentifier("elchi.offer.board")
        }
    }

    private func rivalLine(_ offer: ListingOfferDTO) -> String {
        let vehicle = strings.tOrNil("vehicleClass.\(offer.vehicleClass)") ?? offer.vehicleClass
        let line = "\(strings.t("app.rivalBoard.vehicleSeats", ("vehicle", vehicle), ("seats", offer.seatCapacity))) · \(strings.windowDays(offer.pickupWindowStart, offer.pickupWindowEnd))"
        // Taksi: the rivals' price per seat, comparable for the same people.
        guard PassengerMoney.perSeat(offer.priceBasis) else { return line }
        return "\(line) · \(strings.seatsTotal(max(offer.quantity, 1), unitMinor: offer.unitPriceMinor))"
    }

    /// `Yaxshi baholangan · 12 ta baho`, or "Yangi haydovchi" (never an invented score, Q40).
    private func reputation(_ offer: ListingOfferDTO) -> String {
        guard let bucket = offer.ratingBucket, let text = strings.tOrNil("ratingBucket.\(bucket.rawValue)") else {
            return strings.t("ratingBucket.new_verified")
        }
        guard let count = offer.ratingCount, count > 0 else { return text }
        return strings.t("app.rivalBoard.ratings", ("bucket", text), ("count", count))
    }
}

/// The commission estimate for the typed total (W11): a prompt before a price, never blocking when unavailable.
struct CommissionCard: View {
    let quote: Loadable<app__modules__wallet__schemas__FeeQuoteDTO>?
    let totalMinor: Int
    @Environment(LocaleStore.self) private var strings

    var body: some View {
        switch quote {
        case nil:
            // DESIGN07 7.8: before a price, what the card will show.
            ElchiCard { CardRow(strings.t("commissionPreview.title"), strings.t("driver.offer.commissionPrompt"), first: true, placeholder: true) }
                .accessibilityIdentifier("elchi.offer.commissionPrompt")
        case .loading?:
            ElchiCard { CardRow(strings.t("commissionPreview.title"), strings.t("common.loading"), first: true) }
        case .failed?:
            Note(strings.t("commissionPreview.unavailable"), tone: .gray)
        case .loaded(let quote)?:
            ElchiCard {
                CardRow(strings.t("commissionPreview.title"),
                        strings.t("commissionPreview.line", ("amount", strings.money(quote.commissionMinor)), ("percent", OfferBody.percent(bps: quote.feeBps)),
                                  ("total", strings.money(totalMinor))),
                        first: true, detail: strings.t("commissionPreview.note"))
            }
            .accessibilityIdentifier("elchi.offer.commission")
        }
    }
}

/// A bar pill with an icon, a word and a red count (DESIGN07 0.2: "Takliflarim" on the Moslar bar).
struct TabPill: View {
    let icon: ElchiIcon
    let title: String
    let badge: String?
    let action: () -> Void
    @Environment(\.elchi) private var c

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                icon.image(size: 16)
                Text(title).font(ElchiFont.poppins(13, .semibold)).lineLimit(1)
                if let badge {
                    Text(badge).font(ElchiFont.poppins(11, .bold)).foregroundStyle(.white)
                        .padding(.horizontal, 5)
                        .frame(minWidth: 18, minHeight: 18)
                        .background(Color(hex: 0xE0413A), in: Capsule())
                }
            }
            .foregroundStyle(c.text)
            .padding(.horizontal, 14)
            .frame(height: 40)
            .background(c.card, in: Capsule())
            .shadow(color: c.shadow, radius: 12, y: 6)
            .frame(minHeight: 44)
            .contentShape(Rectangle())
        }
        .buttonStyle(PressFade())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(title)
        .accessibilityValue(badge ?? "")
        .accessibilityAddTraits(.isButton)
    }
}
