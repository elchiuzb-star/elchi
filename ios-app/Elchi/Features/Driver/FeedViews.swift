import SwiftUI

// MARK: - Moslar (feed)

/// The requests that match the driver's route (`side=requests`, alternatives always asked for, Q97): the route filter
/// (region -> district per end), the date chips, the notes, then the primary matches and, under their own heading,
/// the dashed alternatives with their reason.
struct FeedTabView: View {
    let feed: FeedModel
    let onPickEnd: (Bool) -> Void
    let onSaved: () -> Void
    let onOffer: (FeedItemDTO) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        @Bindable var feed = feed
        DriverTabScreen(title: strings.t("driverFeed.title")) {
            if feed.passengerAllowed {
                Segmented([(false, strings.t("driverFeed.modeParcel")), (true, strings.t("driverFeed.modeTaxi"))],
                          selected: feed.filter.passenger) { feed.filter.passenger = $0 }
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
            ElchiButton(strings.t("driverFeed.savedSearches"), variant: .outline, size: .medium, icon: .route, action: onSaved)
            results
        }
        .refreshable { await feed.load() }
        .task {
            await feed.loadFlags()
            await feed.load()
        }
        .onChange(of: feed.filter) { _, _ in Task { await feed.load() } }
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
            Note(strings.t("driver.feed.stopsNote"), tone: .warn)
            ForEach(feed.degraded, id: \.self) { code in
                Text(strings.tOrNil("warning.\(code)") ?? code).font(ElchiFont.caption).foregroundStyle(c.muted)
            }
            let groups = FeedGroups.split(items)
            if items.isEmpty {
                EmptyState(icon: .radar, title: strings.t("driverFeed.emptyTitle"), description: strings.t("driverFeed.emptyTryOther"))
            }
            ForEach(groups.primary, id: \.listing.id) { FeedCard(item: $0, alternative: false, onOffer: onOffer) }
            if !groups.alternative.isEmpty {
                SectionTitle(strings.t("match.alternativesTitle"), description: strings.t("match.alternativesNote"))
                    .accessibilityIdentifier("elchi.feed.alternatives")
                ForEach(groups.alternative, id: \.listing.id) { FeedCard(item: $0, alternative: true, onOffer: onOffer) }
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
    let onOffer: (FeedItemDTO) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        let listing = item.listing
        let card = ItemCard(title: strings.route(listing), icon: .pin, badge: badge, lines: lines, right: strings.money(listing.totalMinor)) {
            ElchiButton(strings.t("driverFeed.sendOffer"), variant: alternative ? .outline : .primary, size: .medium) { onOffer(item) }
                .padding(.top, 6)
                .accessibilityIdentifier("elchi.feed.offer.\(listing.id)")
        }
        if alternative {
            card.overlay {
                RoundedRectangle(cornerRadius: ElchiShape.card).strokeBorder(c.outline, style: StrokeStyle(lineWidth: 1.5, dash: [6, 4]))
            }
        } else {
            card
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
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var confirming: SavedSearchDTO?

    var body: some View {
        ScreenScaffold(title: strings.t("savedSearches.title"), backLabel: strings.t("common.back"), onBack: onBack) {
            Text(strings.t("savedSearches.intro")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
            ElchiCard {
                CardRow(strings.t("savedSearches.currentDirection"), current ?? strings.t("savedSearches.pickEndsFirst"), first: true,
                        placeholder: current == nil)
            }
            ElchiButton(strings.t("savedSearches.save"), loading: model.saving) {
                Task { await model.save(feed.filter, passengerAllowed: feed.passengerAllowed) }
            }
            .disabled(!feed.filter.hasRoute || (model.list.value?.count ?? 0) >= SavedRoute.limit)
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
                        ElchiButton(strings.t("common.delete"), variant: .dangerSoft, size: .medium, loading: model.deleting == saved.id) {
                            confirming = saved
                        }
                        .padding(.top, 6)
                    }
                    .accessibilityIdentifier("elchi.saved.\(saved.id)")
                }
            }
            Text(strings.t("driver.saved.notifyNote")).font(ElchiFont.caption).foregroundStyle(c.muted)
            Text(strings.t("driver.saved.limitHint", ("limit", SavedRoute.limit))).font(ElchiFont.caption).foregroundStyle(c.muted)
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

    enum Edge: String, Identifiable {
        case start, end
        var id: String { rawValue }
    }

    var body: some View {
        let listing = model.listing
        ScreenScaffold(title: strings.t("driverBid.title"), backLabel: strings.t("common.back"), onBack: onBack) {
            ElchiCard(tint: .field) {
                CardRow(strings.route(listing), strings.t("driverBid.clientPrice", ("price", strings.money(listing.totalMinor))), first: true,
                        detail: [strings.parcelLine(listing),
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
            ElchiField(text: $priceText, label: strings.t("driverBid.priceLabel"), placeholder: strings.t("driverBid.pricePlaceholder"),
                       hint: listing.priceBasis == .perSeat ? "\(strings.t("common.total")): \(strings.money(model.totalMinor))" : nil,
                       keyboard: .numberPad)
                .onChange(of: priceText) { _, typed in
                    model.priceDigits = Money.soumDigits(typed)
                    let formatted = Money.grouped(model.priceDigits)
                    if priceText != formatted { priceText = formatted }
                }
            ElchiButton(strings.t("driver.bid.acceptClientPrice", ("price", strings.money(listing.totalMinor))), variant: .soft,
                        loading: model.sending && model.priceMinor == listing.unitPriceMinor) {
                Task { await send(listing.unitPriceMinor) }
            }
            .disabled(!canSend)
            .accessibilityIdentifier("elchi.offer.acceptClientPrice")
            commission
            ElchiField(text: $message, label: strings.t("listingOwner.commentLabel"), multiline: true)
            if let error = model.error { Note(strings.marketErrorText(error), tone: .err).accessibilityIdentifier("elchi.offer.error") }
            Text(strings.t("driverBid.noHoldNote")).font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
        } footer: {
            ElchiButton(strings.t("driverBid.send"), loading: model.sending && model.priceMinor != listing.unitPriceMinor) {
                Task { await send(model.priceMinor) }
            }
            .disabled(!canSend || model.priceMinor <= 0)
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

    @ViewBuilder
    private var board: some View {
        if let board = model.board {
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
        return "\(strings.t("app.rivalBoard.vehicleSeats", ("vehicle", vehicle), ("seats", offer.seatCapacity))) · \(strings.windowDays(offer.pickupWindowStart, offer.pickupWindowEnd))"
    }

    /// `Yaxshi baholangan · 12 ta baho`, or "Yangi haydovchi" (never an invented score, Q40).
    private func reputation(_ offer: ListingOfferDTO) -> String {
        guard let bucket = offer.ratingBucket, let text = strings.tOrNil("ratingBucket.\(bucket.rawValue)") else {
            return strings.t("ratingBucket.new_verified")
        }
        guard let count = offer.ratingCount, count > 0 else { return text }
        return strings.t("app.rivalBoard.ratings", ("bucket", text), ("count", count))
    }

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
            ElchiButton(strings.t("driverRoutes.addRoute"), variant: .soft, size: .medium, icon: .plus, action: onAddTrip)
        case .loaded(let list):
            SelectField(label: strings.t("driverBid.trip"), options: list.map { ($0.id, "\(strings.route($0)) · \(strings.tripMeta($0))") },
                        selected: model.tripId, placeholder: strings.t("driverBid.tripPlaceholder")) { model.choose($0) }
            if model.tripId != nil && model.window == nil {
                Note(strings.t("driverBid.tripWindowMismatch"), tone: .err)
            }
        }
    }

    @ViewBuilder
    private var commission: some View {
        switch model.quote {
        case nil:
            EmptyView()
        case .loading?:
            ElchiCard { CardRow(strings.t("commissionPreview.title"), strings.t("common.loading"), first: true) }
        case .failed?:
            Note(strings.t("commissionPreview.unavailable"), tone: .gray)
        case .loaded(let quote)?:
            ElchiCard {
                CardRow(strings.t("commissionPreview.title"),
                        strings.t("commissionPreview.line", ("amount", strings.money(quote.commissionMinor)), ("percent", OfferBody.percent(bps: quote.feeBps)),
                                  ("total", strings.money(model.totalMinor))),
                        first: true, detail: strings.t("commissionPreview.note"))
            }
            .accessibilityIdentifier("elchi.offer.commission")
        }
    }

    private func time(_ text: String) -> String { ServerTime.parse(text).map(DepartureWindow.shortText) ?? "?" }
}
