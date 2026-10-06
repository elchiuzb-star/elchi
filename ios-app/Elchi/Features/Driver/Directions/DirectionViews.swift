import SwiftUI

// MARK: - Yo'nalishlarim (the Routes tab)

/// ADR-0027 (Q150): the driver keeps directions only - "where from -> where to". Each card: the two ends, status,
/// capacity, the active trip (or that the first offer plans it), "Mos buyurtmalar", pause / resume, archive. Under them
/// the trips the system made ("Safarlarim"): the trip operation screens are the same as before (Q148), and the manual
/// trip form stays reachable from there as a fallback.
struct DirectionsTabView: View {
    let model: DirectionsModel
    let trips: TripsModel
    let onAdd: () -> Void
    let onOpenRequests: (String) -> Void
    let onOpenTrip: (String) -> Void
    let onPlanTrip: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var archiving: DriverDirectionDTO?

    var body: some View {
        DriverTabScreen(title: strings.t("driverRoutes.title"), plus: (strings.t("driverRoutes.addRoute"), onAdd)) {
            directions
            SectionTitle(strings.t("dir.tripsTitle"), description: strings.t("dir.tripsHint"))
                .padding(.top, 8)
                .accessibilityIdentifier("elchi.directions.tripsTitle")
            tripList
            ElchiButton(strings.t("driver.dash.planTrip"), variant: .outline, size: .medium, icon: .plus, action: onPlanTrip)
                .accessibilityIdentifier("elchi.directions.planTrip")
        }
        .refreshable {
            async let list: Void = model.load()
            async let trips: Void = self.trips.load()
            _ = await (list, trips)
        }
        .task {
            async let list: Void = model.load()
            async let trips: Void = self.trips.load()
            _ = await (list, trips)
        }
        .overlay {
            if let direction = archiving {
                DialogOverlay(dismissLabel: strings.t("confirmDialog.back"), onDismiss: { archiving = nil }) {
                    Text(strings.t("dir.archiveConfirm", ("title", DirectionEndName.route(direction, ru: strings.locale == .ru))))
                        .font(ElchiFont.poppins(18, .medium)).foregroundStyle(c.text)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityAddTraits(.isHeader)
                        .accessibilityIdentifier("elchi.directions.archiveConfirmText")
                    ElchiButton(strings.t("dir.archive"), variant: .danger) {
                        archiving = nil
                        Task { await model.setStatus(direction, to: "archived") }
                    }
                    .accessibilityIdentifier("elchi.directions.confirmArchive")
                    ElchiButton(strings.t("confirmDialog.back"), variant: .neutral, size: .medium) { archiving = nil }
                }
            }
        }
    }

    @ViewBuilder
    private var directions: some View {
        switch model.list {
        case .loading:
            SkeletonCards(count: 2)
        case .failed(let error):
            Note(strings.errorText(error), tone: .err)
            ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.load() } }
        case .loaded:
            if model.directions.isEmpty {
                NoDirectionsCard(onAdd: onAdd)
            } else {
                ForEach(model.directions, id: \.id) { direction in
                    DirectionCard(direction: direction, running: model.running == direction.id, locked: model.running != nil,
                                  onOpen: { onOpenRequests(direction.id) },
                                  onToggle: { Task { await model.setStatus(direction, to: direction.status == "active" ? "paused" : "active") } },
                                  onArchive: { archiving = direction })
                }
            }
        }
    }

    @ViewBuilder
    private var tripList: some View {
        switch trips.trips {
        case .loading:
            SkeletonCards(count: 1)
        case .failed(let error):
            Note(strings.errorText(error), tone: .err)
        case .loaded(let list) where list.isEmpty:
            Text(strings.t("driverRoutes.empty")).font(ElchiFont.caption).foregroundStyle(c.muted)
        case .loaded(let list):
            let sections = TripList.sections(list)
            ForEach(sections.active, id: \.id) { TripCard(trip: $0, trips: trips) { onOpenTrip($0) } }
            ForEach(sections.history, id: \.id) { TripCard(trip: $0, trips: trips) { onOpenTrip($0) }.opacity(0.7) }
        }
    }
}

/// "Avval yo'nalish qo'shing": what a direction does, and the add button.
struct NoDirectionsCard: View {
    let onAdd: () -> Void
    @Environment(LocaleStore.self) private var strings

    var body: some View {
        EmptyState(icon: .route, title: strings.t("dir.noDirections"), description: strings.t("dir.noDirectionsHint"))
            .accessibilityIdentifier("elchi.directions.empty")
        ElchiButton(strings.t("driverRoutes.addRoute"), variant: .soft, icon: .plus, action: onAdd)
            .accessibilityIdentifier("elchi.directions.add")
    }
}

/// One direction: ends, status, capacity, the trip line, and its three actions.
struct DirectionCard: View {
    let direction: DriverDirectionDTO
    let running: Bool
    let locked: Bool
    let onOpen: () -> Void
    let onToggle: () -> Void
    let onArchive: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        let active = direction.status == "active"
        ItemCard(title: DirectionEndName.route(direction, ru: strings.locale == .ru), icon: .route,
                 badge: (strings.t(active ? "dir.statusActive" : "dir.statusPaused"), active ? .ok : .gray),
                 sub: strings.t("dir.capacity", ("seats", direction.seatCapacity), ("kg", Int((Double(direction.cargoCapacityWeightG) / 1000).rounded()))),
                 lines: lines) {
            VStack(spacing: 8) {
                HStack(spacing: 8) {
                    ElchiButton(strings.t("dir.openRequests"), size: .pair, action: onOpen)
                        .disabled(!active)
                        .accessibilityIdentifier("elchi.direction.open.\(direction.id)")
                    ElchiButton(strings.t(active ? "dir.pause" : "dir.resume"), variant: .soft, size: .pair, loading: running, action: onToggle)
                        .disabled(locked && !running)
                        .accessibilityIdentifier("elchi.direction.toggle.\(direction.id)")
                }
                Button(strings.t("dir.archive"), action: onArchive)
                    .font(ElchiFont.poppins(13, .semibold)).foregroundStyle(c.tone(.err).fg)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .frame(minHeight: 44)
                    .disabled(locked)
                    .accessibilityIdentifier("elchi.direction.archive.\(direction.id)")
            }
            .padding(.top, 6)
        }
        .accessibilityIdentifier("elchi.direction.\(direction.id)")
    }

    private var lines: [ItemLine] {
        var out: [ItemLine] = []
        if let via = direction.viaDistrictNames, !via.isEmpty { out.append(ItemLine(strings.t("dir.via", ("names", via.joined(separator: ", "))))) }
        if let trip = direction.activeTrip {
            out.append(ItemLine(strings.t("dir.trip", ("date", DirectionFeed.dayClock(trip.plannedStartAt)), ("status", strings.tripStatus(trip.status)),
                                          ("seats", trip.seatsBooked)), tone: .blue))
        } else {
            out.append(ItemLine(strings.t("dir.noTrip")))
        }
        return out
    }
}

// MARK: - Yo'nalish qo'shish

/// Two ends, each a region (required) and a district (required where the region has districts; a city without
/// districts is the whole city). No time, stop, corridor or route: the server finds the road (Q150).
struct AddDirectionView: View {
    let model: DirectionsModel
    /// The regions / districts catalogue (shared with the feed's filter, cached there).
    let geo: FeedModel
    let onBack: () -> Void
    let onSaved: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(BannerCenter.self) private var banners: BannerCenter?
    @State private var sheet: PlaceSheet?
    @State private var tried = false

    enum PlaceSheet: Identifiable, Hashable {
        case region(origin: Bool), district(origin: Bool)
        var id: String {
            switch self {
            case .region(let origin): "region.\(origin)"
            case .district(let origin): "district.\(origin)"
            }
        }
    }

    var body: some View {
        ScreenScaffold(title: strings.t("driverRoutes.addRoute"), backLabel: strings.t("common.back"), onBack: onBack) {
            Text(strings.t("dir.formHint")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("elchi.addDirection.hint")
            endFields(origin: true)
            endFields(origin: false)
            if let notice = model.formNotice {
                Note(strings.t(notice), tone: .warn).accessibilityIdentifier("elchi.addDirection.notice")
            }
            if let error = model.formError { Note(strings.errorText(error), tone: .err).accessibilityIdentifier("elchi.addDirection.error") }
        } footer: {
            ElchiButton(strings.t("dir.save"), loading: model.saving, dimmed: !model.form.ready) {
                guard model.form.ready else { tried = true; return }
                Task {
                    if await model.create() == .added {
                        banners?.ok("dir.added")
                        onSaved()
                    }
                }
            }
            .accessibilityIdentifier("elchi.addDirection.save")
        }
        .task { await geo.loadRegions() }
        .sheet(item: $sheet) { sheet in
            switch sheet {
            case .region(let origin):
                PlacePickerSheet(title: strings.t("dir.region"), searchPlaceholder: strings.t("location.search"),
                                 rows: regionRows, loading: geo.regions.value == nil) { id in
                    pickRegion(id, origin: origin)
                    self.sheet = nil
                }
            case .district(let origin):
                let end = origin ? model.form.origin : model.form.destination
                PlacePickerSheet(title: end.region.map { strings.name($0) } ?? strings.t("dir.district"),
                                 searchPlaceholder: strings.t("dir.districtSearch"),
                                 rows: districtRows(end), loading: end.region.map { geo.districts[$0.id]?.value == nil } ?? false,
                                 wholeCity: DirectionFormEnd.needsDistrict(end.region) ? nil : strings.t("dir.wholeCity")) { id in
                    pickDistrict(id, origin: origin)
                    self.sheet = nil
                }
                .task { if let region = end.region { await geo.loadDistricts(region) } }
            }
        }
    }

    @ViewBuilder
    private func endFields(origin: Bool) -> some View {
        let end = origin ? model.form.origin : model.form.destination
        let needs = DirectionFormEnd.needsDistrict(end.region)
        SectionTitle(strings.t(origin ? "driverFeed.from" : "driverFeed.to")).padding(.top, origin ? 0 : 6)
        PickerField(label: strings.t("dir.region"), value: end.region.map { strings.name($0) }, placeholder: strings.t("dir.regionPlaceholder"),
                    icon: .chevD, error: tried && end.region == nil) { sheet = .region(origin: origin) }
            .accessibilityIdentifier("elchi.addDirection.\(origin ? "origin" : "destination").region")
        PickerField(label: strings.t("dir.district"),
                    value: end.district.map { strings.name($0) } ?? (end.region != nil && !needs ? strings.t("dir.wholeCity") : nil),
                    placeholder: needs ? strings.t("dir.districtPlaceholder") : strings.t("dir.wholeCity"),
                    icon: .chevD, error: tried && end.region != nil && !end.ready) { sheet = .district(origin: origin) }
            .disabled(end.region == nil)
            .opacity(end.region == nil ? 0.6 : 1)
            .accessibilityIdentifier("elchi.addDirection.\(origin ? "origin" : "destination").district")
    }

    private var regionRows: [(String, String)] { (geo.regions.value ?? []).map { ($0.id, strings.name($0)) } }

    private func districtRows(_ end: DirectionFormEnd) -> [(String, String)] {
        guard let region = end.region else { return [] }
        return (geo.districts[region.id]?.value ?? []).filter { $0.isActive != false }.map { ($0.id, strings.name($0)) }
    }

    private func pickRegion(_ id: String?, origin: Bool) {
        guard let id, let region = geo.regions.value?.first(where: { $0.id == id }) else { return }
        var end = origin ? model.form.origin : model.form.destination
        if end.region?.id != region.id { end = DirectionFormEnd(region: region, district: nil) }
        set(end, origin: origin)
        Task { await geo.loadDistricts(region) }
    }

    private func pickDistrict(_ id: String?, origin: Bool) {
        var end = origin ? model.form.origin : model.form.destination
        guard let region = end.region else { return }
        end.district = id.flatMap { id in geo.districts[region.id]?.value?.first { $0.id == id } }
        set(end, origin: origin)
    }

    private func set(_ end: DirectionFormEnd, origin: Bool) {
        if origin { model.form.origin = end } else { model.form.destination = end }
        model.clearFormAnswer()
    }
}

/// A searchable list in a sheet (regions, or one region's districts). `wholeCity`: a first row that clears the district.
struct PlacePickerSheet: View {
    let title: String
    let searchPlaceholder: String
    let rows: [(String, String)]
    let loading: Bool
    var wholeCity: String?
    let onPick: (String?) -> Void
    @Environment(\.elchi) private var c
    @State private var query = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title).font(ElchiFont.poppins(20, .medium, relativeTo: .title2)).foregroundStyle(c.text)
                .accessibilityAddTraits(.isHeader)
            ElchiField(text: $query, placeholder: searchPlaceholder, icon: .search)
                .accessibilityIdentifier("elchi.placePicker.search")
            ScrollView {
                if loading {
                    SkeletonCards(count: 2)
                } else {
                    let shown = rows.filter { SearchText.matches($0.1, query) }
                    ElchiList {
                        if let wholeCity, query.isEmpty {
                            ListRow(icon: .pin, title: wholeCity, first: true) { onPick(nil) }
                        }
                        ForEach(Array(shown.enumerated()), id: \.element.0) { index, row in
                            ListRow(title: row.1, first: index == 0 && (wholeCity == nil || !query.isEmpty)) { onPick(row.0) }
                                .accessibilityIdentifier("elchi.placePicker.row.\(row.1)")
                        }
                    }
                }
            }
        }
        .padding(20)
        .frame(maxHeight: .infinity, alignment: .top)
        .background(c.page.ignoresSafeArea())
        .presentationDetents([.large])
        .presentationCornerRadius(ElchiShape.sheet)
    }
}

// MARK: - The direction feed (top of Moslar)

/// Q151: the requests along the chosen direction, cut into the three answers the server gave - the trip reaches them on
/// time, a first offer plans a trip around them, or the car is there at another time (a time proposal).
struct DirectionFeedSection: View {
    let model: DirectionsModel
    let service: ServiceType
    let onAdd: () -> Void
    let onOffer: (DirectionRequestItemDTO) -> Void
    let onThread: (String) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            switch model.list {
            case .loading:
                SkeletonCards(count: 1)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err)
            case .loaded:
                if model.directions.isEmpty {
                    NoDirectionsCard(onAdd: onAdd)
                } else {
                    content
                }
            }
        }
        .task { if model.list.value == nil { await model.load() } }
        .task(id: "\(model.activeId ?? "-")|\(service.rawValue)|\(model.day.rawValue)") { await model.loadFeed(service: service) }
    }

    @ViewBuilder
    private var content: some View {
        let live = model.directions
        if live.count > 1 {
            SelectField(label: strings.t("dir.feedPick"), options: live.map { ($0.id, DirectionEndName.route($0, ru: strings.locale == .ru)) },
                        selected: model.activeId, placeholder: strings.t("dir.feedPick")) { model.activeId = $0 }
                .accessibilityIdentifier("elchi.dirFeed.pick")
        } else if let only = live.first {
            Text(DirectionEndName.route(only, ru: strings.locale == .ru)).font(ElchiFont.poppins(15, .semibold)).foregroundStyle(c.text)
                .accessibilityIdentifier("elchi.dirFeed.direction")
        }
        HStack(spacing: 8) {
            ForEach(DirectionFeedDay.allCases, id: \.self) { day in
                Chip(strings.t(day.labelKey), selected: model.day == day, filled: true) { model.day = day }
                    .accessibilityIdentifier("elchi.dirFeed.day.\(day.rawValue)")
            }
        }
        if let active = model.active, active.status != "active" {
            Note(strings.t("dir.paused"), tone: .gray).accessibilityIdentifier("elchi.dirFeed.paused")
        } else {
            results
        }
    }

    @ViewBuilder
    private var results: some View {
        switch model.feed {
        case nil, .loading?:
            SkeletonCards(count: 2)
        case .failed(let error)?:
            Note(strings.errorText(error), tone: .err)
            ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.loadFeed(service: service) } }
        case .loaded(let page)?:
            if let trip = page.activeTrip {
                Note(strings.t("dir.trip", ("date", DirectionFeed.dayClock(trip.plannedStartAt)), ("status", strings.tripStatus(trip.status)),
                               ("seats", trip.seatsBooked)), tone: .blue)
                    .accessibilityIdentifier("elchi.dirFeed.trip")
            }
            let groups = DirectionFeed.groups(page.items)
            group("dir.group.fits", "dir.group.fitsNote", groups.fits, id: "fits")
            group("dir.group.new", "dir.group.newNote", groups.fresh, id: "new")
            group("dir.group.time", "dir.group.timeNote", groups.otherTime, id: "time")
            if page.items.isEmpty {
                Text(strings.t("dir.feedEmpty")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
                    .accessibilityIdentifier("elchi.dirFeed.empty")
            }
        }
    }

    @ViewBuilder
    private func group(_ title: String, _ note: String, _ items: [DirectionRequestItemDTO], id: String) -> some View {
        if !items.isEmpty {
            SectionTitle(strings.t(title), description: strings.t(note)).accessibilityIdentifier("elchi.dirFeed.group.\(id)")
            ForEach(items, id: \.listing.id) { DirectionRequestCard(item: $0, onOffer: onOffer, onThread: onThread) }
        }
    }
}

/// One request along the direction: the places (address or district - never a stop, Q158), the match badge, the
/// client's window, the car's ETA (warn colour for another time), the planned departure for a new trip, the parcel /
/// people line, the price, and "Taklif yuborish" - or, once offered, "Taklifingiz yuborilgan" with the thread.
struct DirectionRequestCard: View {
    let item: DirectionRequestItemDTO
    let onOffer: (DirectionRequestItemDTO) -> Void
    let onThread: (String) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        let listing = item.listing
        let card = ItemCard(title: strings.route(listing), icon: .pin, badge: badge, lines: lines,
                            meta: item.myThreadId == nil ? nil : strings.t("dir.card.myOffer"),
                            right: strings.money(listing.totalMinor), metaAccent: item.myThreadId != nil) {
            if let thread = item.myThreadId {
                ElchiButton(strings.t("driver.feed.viewOffer"), variant: .neutral, size: .medium) { onThread(thread) }
                    .padding(.top, 6)
                    .accessibilityIdentifier("elchi.dirFeed.viewOffer.\(listing.id)")
            } else {
                ElchiButton(strings.t("driverFeed.sendOffer"), variant: item.fit == "time_differs" ? .outline : .primary, size: .medium) { onOffer(item) }
                    .padding(.top, 6)
                    .accessibilityIdentifier("elchi.dirFeed.offer.\(listing.id)")
            }
        }
        if item.fit == "time_differs" {
            card.overlay {
                RoundedRectangle(cornerRadius: ElchiShape.card).strokeBorder(c.tone(.warn).fg.opacity(0.5), style: StrokeStyle(lineWidth: 1.5, dash: [6, 4]))
            }
        } else {
            card
        }
    }

    private var badge: (text: String, tone: Tone)? {
        switch item.matchType {
        case .exact: (strings.t("match.exact"), .ok)
        case .onRoute: (strings.t("match.on_route"), .blue)
        default: nil
        }
    }

    private var lines: [ItemLine] {
        let listing = item.listing
        var out = [ItemLine(strings.t("dir.card.asked", ("start", DirectionFeed.dayClock(listing.departureWindowStart)),
                                      ("end", DirectionFeed.clock(listing.departureWindowEnd))))]
        if let eta = item.pickupEta {
            out.append(ItemLine(strings.t("dir.card.eta", ("time", DirectionFeed.dayClock(eta))), tone: item.fit == "time_differs" ? .warn : nil))
        }
        if item.fit == "no_trip", let departure = item.suggestedDepartureAt {
            out.append(ItemLine(strings.t("dir.card.departure", ("time", DirectionFeed.dayClock(departure)))))
        }
        if let parcel = strings.parcelLine(listing) { out.append(ItemLine(parcel)) }
        return out
    }
}

// MARK: - Narx taklif qiling (from a direction)

/// Pricing one request from a direction: no trip picker (the server takes, re-times or plans the trip). The summary,
/// the car's time, the time-proposal sentence when the car is there at another time, the rival board, the price (or
/// the client's price in one tap), the commission estimate, an optional message, the no-hold note.
struct DirectionOfferView: View {
    let model: DirectionOfferModel
    let onBack: () -> Void
    let onSent: (DirectionOfferDTO) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var priceText = ""
    @State private var message = ""
    /// "Taklif yuborish" was tapped with no price (DESIGN07 7.11).
    @State private var priceMissing = false

    var body: some View {
        let item = model.item
        let listing = model.listing
        let perSeat = PassengerMoney.perSeat(listing.priceBasis)
        let clientPrice = perSeat ? strings.seatsTotal(max(listing.quantity, 1), unitMinor: listing.unitPriceMinor) : strings.money(listing.totalMinor)
        let asked = strings.t("dir.card.asked", ("start", DirectionFeed.dayClock(listing.departureWindowStart)),
                              ("end", DirectionFeed.clock(listing.departureWindowEnd)))
        ScreenScaffold(title: strings.t("driverBid.title"), backLabel: strings.t("common.back"), onBack: onBack) {
            ElchiCard(tint: .field) {
                CardRow(strings.route(listing), strings.t("driverBid.clientPrice", ("price", clientPrice)), first: true,
                        detail: [perSeat ? strings.t("seatPicker.peopleCount", ("count", max(listing.quantity, 1))) : strings.parcelLine(listing), asked]
                            .compactMap { $0 }.joined(separator: " · "), strong: true)
            }
            if let eta = item.pickupEta {
                ElchiCard(tint: .blue) {
                    CardRow(strings.t("driverBid.pickupWindow"), strings.t("dir.card.eta", ("time", DirectionFeed.dayClock(eta))), first: true,
                            detail: item.fit == "no_trip" ? item.suggestedDepartureAt.map { strings.t("dir.bid.planned", ("time", DirectionFeed.dayClock($0))) } : nil)
                }
                .accessibilityIdentifier("elchi.dirOffer.eta")
            }
            if let proposeAt = model.proposeAt {
                Note(strings.t("dir.bid.timeProposal", ("time", DirectionFeed.dayClock(proposeAt)),
                               ("start", DirectionFeed.dayClock(listing.departureWindowStart)), ("end", DirectionFeed.clock(listing.departureWindowEnd))),
                     tone: .warn)
                    .accessibilityIdentifier("elchi.dirOffer.timeProposal")
            }
            RivalBoardCard(board: model.board)
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
                .accessibilityIdentifier("elchi.dirOffer.price")
            ElchiButton(strings.t("driver.bid.acceptClientPrice", ("price", clientPrice)), variant: .soft,
                        loading: model.sending && model.priceMinor == listing.unitPriceMinor) {
                Task { await send(listing.unitPriceMinor) }
            }
            .disabled(model.sending)
            .accessibilityIdentifier("elchi.dirOffer.acceptClientPrice")
            CommissionCard(quote: model.quote, totalMinor: model.totalMinor)
            ElchiField(text: $message, label: strings.t("listingOwner.commentLabel"), multiline: true)
            if let refusal = model.refusal {
                Note(refusalText(refusal, seats: max(listing.quantity, 1)), tone: refusalTone(refusal)).accessibilityIdentifier("elchi.dirOffer.error")
            }
            Text(strings.t("driverBid.noHoldNote")).font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
        } footer: {
            let title = model.proposeAt.map { strings.t("dir.bid.proposeTime", ("time", DirectionFeed.clock($0))) } ?? strings.t("driverBid.send")
            ElchiButton(title, loading: model.sending && model.priceMinor != listing.unitPriceMinor, dimmed: model.priceMinor <= 0) {
                guard model.priceMinor > 0 else { priceMissing = true; return }
                Task { await send(model.priceMinor) }
            }
            .disabled(model.sending)
            .accessibilityIdentifier("elchi.dirOffer.send")
        }
        .task {
            priceText = Money.grouped(model.priceDigits)
            await model.loadBoard()
        }
        .task(id: model.totalMinor) {
            try? await Task.sleep(for: .milliseconds(400))
            if !Task.isCancelled { await model.loadQuote(totalMinor: model.totalMinor) }
        }
    }

    private func send(_ unitPriceMinor: Int) async {
        if let result = await model.send(unitPriceMinor: unitPriceMinor, message: message) { onSent(result) }
    }

    private func refusalText(_ refusal: DirectionOfferRefusal, seats: Int) -> String {
        switch refusal {
        case .passed: strings.t("dir.passed")
        case .tooFar(let early, let late): strings.t("dir.bid.tooFar", ("early", early), ("late", late))
        case .proposeTime(let eta): strings.t("dir.card.eta", ("time", DirectionFeed.dayClock(eta)))
        case .other(let error): strings.marketErrorText(error, seats: seats)
        }
    }

    private func refusalTone(_ refusal: DirectionOfferRefusal) -> Tone {
        if case .other = refusal { return .err }
        return .warn
    }
}
