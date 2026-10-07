import SwiftUI

// MARK: - Yo'nalishlarim (the second segment of Moslar, design v3)

/// ADR-0027 (Q150): the driver keeps directions only - "where from -> where to". Each card: the two ends, an on/off
/// switch (pause / resume), the state dot, capacity, the active trip line, "Mos buyurtmalar" and delete with an inline
/// confirm. Under them the trips the system made ("Safarlarim"): the trip operation screens are the same as before
/// (Q148). The manual trip form has no entry here any more (Safar 2.9 / 3.9).
struct DirectionsListSection: View {
    let model: DirectionsModel
    let trips: TripsModel
    let onAdd: () -> Void
    let onOpenRequests: (String) -> Void
    let onOpenTrip: (String) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    /// The card whose inline "Yo'nalish o'chirilsinmi?" row is open.
    @State private var deleting: String?

    var body: some View {
        directions
        if model.list.value.map({ !DirectionFeed.live($0).isEmpty }) == true || trips.trips.value?.isEmpty == false {
            SectionTitle(strings.t("dir.tripsTitle"), description: strings.t("dir.tripsHint"))
                .padding(.top, 8)
                .accessibilityIdentifier("elchi.directions.tripsTitle")
            tripList
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
                                  confirming: deleting == direction.id,
                                  onOpen: { onOpenRequests(direction.id) },
                                  onToggle: { Task { await model.setStatus(direction, to: direction.status == "active" ? "paused" : "active") } },
                                  onAskDelete: { deleting = direction.id },
                                  onCancelDelete: { deleting = nil },
                                  onDelete: {
                                      deleting = nil
                                      Task { await model.setStatus(direction, to: "archived") }
                                  })
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
            EmptyView()
        case .loaded(let list):
            let sections = TripList.sections(list)
            ForEach(sections.active, id: \.id) { TripCard(trip: $0, trips: trips) { onOpenTrip($0) } }
            ForEach(sections.history, id: \.id) { TripCard(trip: $0, trips: trips) { onOpenTrip($0) }.opacity(0.7) }
        }
    }
}

/// "Hozircha yo'nalish qo'shilmagan": what a direction does, and the add button (one pair on both apps, Safar 2.8).
struct NoDirectionsCard: View {
    let onAdd: () -> Void
    @Environment(LocaleStore.self) private var strings

    var body: some View {
        EmptyState(icon: .route, title: strings.t("driverRoutes.empty"), description: strings.t("dir.noDirectionsHint"))
            .accessibilityIdentifier("elchi.directions.empty")
        ElchiButton(strings.t("driverRoutes.addRoute"), variant: .soft, icon: .plus, action: onAdd)
            .accessibilityIdentifier("elchi.directions.add")
    }
}

/// One direction (Safar 2.2 / 2.3): ends, capacity, an on/off switch with the state dot, the via / trip lines,
/// "Mos buyurtmalar" and a trash button that opens an inline confirm. A paused card is faded.
struct DirectionCard: View {
    let direction: DriverDirectionDTO
    let running: Bool
    let locked: Bool
    var confirming = false
    let onOpen: () -> Void
    let onToggle: () -> Void
    var onAskDelete: () -> Void = {}
    var onCancelDelete: () -> Void = {}
    var onDelete: () -> Void = {}
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        let active = direction.status == "active"
        let route = DirectionEndName.route(direction, ru: strings.locale == .ru)
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(route).font(ElchiFont.poppins(15, .semibold)).foregroundStyle(c.text).lineLimit(2)
                    Text(strings.t("dir.capacity", ("seats", direction.seatCapacity), ("kg", Int((Double(direction.cargoCapacityWeightG) / 1000).rounded()))))
                        .font(ElchiFont.poppins(12.5)).foregroundStyle(c.muted)
                }
                .opacity(active ? 1 : 0.55)
                Spacer(minLength: 0)
                if running {
                    ProgressView().frame(width: 56, height: 32)
                } else {
                    Toggle("", isOn: Binding(get: { active }, set: { _ in onToggle() }))
                        .labelsHidden()
                        .tint(c.brand)
                        .disabled(locked)
                        .accessibilityLabel(strings.t(active ? "dir.pause" : "dir.resume"))
                        .accessibilityIdentifier("elchi.direction.toggle.\(direction.id)")
                }
            }
            HStack(spacing: 6) {
                Circle().fill(active ? c.tone(.ok).fg : c.placeholder).frame(width: 7, height: 7)
                Text(strings.t(active ? "dir.statusActive" : "dir.statusPaused")).font(ElchiFont.poppins(12, .semibold))
                    .foregroundStyle(active ? c.tone(.ok).fg : c.placeholder)
            }
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("elchi.direction.state.\(direction.id)")
            ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                // The via line can name dozens of districts: two lines, the rest elided.
                Text(line.text).font(ElchiFont.poppins(12.5)).foregroundStyle(line.blue ? c.accentText : c.muted)
                    .lineLimit(line.blue ? nil : 2)
            }
            .opacity(active ? 1 : 0.55)
            if confirming {
                HStack(spacing: 8) {
                    Text(strings.t("dir.archiveConfirm", ("title", route))).font(ElchiFont.poppins(13, .medium)).foregroundStyle(c.tone(.err).noteText)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("elchi.directions.archiveConfirmText")
                    pill(strings.t("common.none"), bg: c.card, fg: c.text, action: onCancelDelete)
                    pill(strings.t("common.delete"), bg: c.danger, fg: .white, action: onDelete)
                        .accessibilityIdentifier("elchi.directions.confirmArchive")
                }
                .padding(.leading, 14).padding(.trailing, 8).padding(.vertical, 8)
                .background(c.tone(.err).bg, in: RoundedRectangle(cornerRadius: 16))
            } else {
                HStack(spacing: 8) {
                    Button(action: onOpen) {
                        Text(strings.t("dir.openRequests")).font(ElchiFont.poppins(14, .medium)).foregroundStyle(c.softText).lineLimit(1)
                            .frame(maxWidth: .infinity).frame(height: 42)
                            .background(c.soft, in: Capsule())
                    }
                    .buttonStyle(PressFade())
                    .disabled(!active)
                    .opacity(active ? 1 : 0.55)
                    .accessibilityIdentifier("elchi.direction.open.\(direction.id)")
                    Button(action: onAskDelete) {
                        ElchiIcon.trash.image(size: 17).foregroundStyle(c.tone(.err).fg)
                            .frame(width: 42, height: 42)
                            .background(c.tone(.err).bg, in: Circle())
                            .frame(width: 44, height: 44)
                    }
                    .buttonStyle(PressFade())
                    .disabled(locked)
                    .accessibilityLabel(strings.t("common.delete"))
                    .accessibilityIdentifier("elchi.direction.archive.\(direction.id)")
                }
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 14)
        .background(c.card, in: RoundedRectangle(cornerRadius: ElchiShape.cardV3))
        .shadow(color: c.softShadow, radius: 12, y: 6)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("elchi.direction.\(direction.id)")
    }

    private func pill(_ title: String, bg: Color, fg: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(ElchiFont.poppins(12.5, .semibold)).foregroundStyle(fg)
                .padding(.horizontal, 12).frame(height: 34)
                .background(bg, in: Capsule())
                .frame(minHeight: 44)
        }
        .buttonStyle(PressFade())
    }

    private var lines: [(text: String, blue: Bool)] {
        var out: [(String, Bool)] = []
        if let via = direction.viaDistrictNames, !via.isEmpty { out.append((strings.t("dir.via", ("names", via.joined(separator: ", "))), false)) }
        if let trip = direction.activeTrip {
            out.append((strings.t("dir.trip", ("date", DirectionFeed.dayClock(trip.plannedStartAt)), ("status", strings.tripStatus(trip.status)),
                                  ("seats", trip.seatsBooked)), true))
        } else {
            out.append((strings.t("dir.noTrip"), false))
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

// MARK: - The direction feed (the first segment of Moslar, design v3)

/// Q151: the requests along the chosen direction - one flat list of those the trip reaches on time or a first offer
/// plans a trip for (Safar 5.4), then, under their own heading, those where the car is there at another time (a time
/// proposal, Q153/Q157). Chips Bugun / Ertaga / 3 kun / 14 kun. A card opens the listing detail.
struct DirectionFeedSection: View {
    let model: DirectionsModel
    let service: ServiceType
    /// The driver's offers: "Siz taklif yubordingiz: {price}" / "Mijoz qabul qildi" (Safar 5.7).
    let proposals: DriverProposalsModel
    let onAdd: () -> Void
    let onOpen: (DirectionRequestItemDTO) -> Void
    let onOffer: (DirectionRequestItemDTO) -> Void
    let onThread: (String) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
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
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(DirectionFeedDay.allCases, id: \.self) { day in
                    V3Chip(title: strings.t(day.labelKey), selected: model.day == day, height: 36) { model.day = day }
                        .accessibilityIdentifier("elchi.dirFeed.day.\(day.rawValue)")
                }
            }
            .padding(.horizontal, 16)
        }
        .padding(.horizontal, -16)
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
            ForEach(groups.fits + groups.fresh, id: \.listing.id) { card($0) }
            if !groups.otherTime.isEmpty {
                SectionTitle(strings.t("dir.group.time"), description: strings.t("dir.group.timeNote"))
                    .accessibilityIdentifier("elchi.dirFeed.group.time")
                ForEach(groups.otherTime, id: \.listing.id) { card($0) }
            }
            if page.items.isEmpty {
                EmptyState(icon: .radar, title: strings.t("driverFeed.emptyTitle"), description: strings.t("driver.v3trip.feedEmptyHint"))
                    .accessibilityIdentifier("elchi.dirFeed.empty")
            }
        }
    }

    private func card(_ item: DirectionRequestItemDTO) -> some View {
        DirectionRequestCard(item: item, mark: FeedOfferMark.of(listingId: item.listing.id, open: proposals.lists[.open]?.value,
                                                                accepted: proposals.lists[.accepted]?.value,
                                                                versions: { proposals.versions($0) }),
                             onOpen: { onOpen(item) }, onOffer: onOffer, onThread: onThread)
    }
}

/// One request along the direction (Safar 5.5): the kind icon, the places (address or district - never a stop, Q158),
/// the match badge, the client's window, the car's ETA (warn colour for another time), the planned departure for a new
/// trip, the parcel / people line, then "Siz taklif yubordingiz: {price}" / "Mijoz qabul qildi" (Safar 5.7) and the
/// price, and one full-width button. The card opens the listing detail.
struct DirectionRequestCard: View {
    let item: DirectionRequestItemDTO
    var mark: FeedOfferMark = .none
    var onOpen: () -> Void = {}
    let onOffer: (DirectionRequestItemDTO) -> Void
    let onThread: (String) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        let listing = item.listing
        let otherTime = item.fit == "time_differs"
        let thread = mark.threadId ?? item.myThreadId
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top, spacing: 10) {
                ListingKindIcon.of(listing).image(size: 18).foregroundStyle(c.accentText)
                    .frame(width: 36, height: 36)
                    .background(c.iconTint, in: Circle())
                Text(strings.route(listing)).font(ElchiFont.poppins(15, .semibold)).foregroundStyle(c.text)
                    .frame(maxWidth: .infinity, alignment: .leading).padding(.top, 7)
                if let tag = strings.matchTag(item) {
                    Badge(tag.text, tone: tag.tone)
                }
            }
            ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                Text(line.text).font(ElchiFont.poppins(12.5)).foregroundStyle(line.warn ? c.tone(.warn).fg : c.tone(.gray).noteText)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(meta ?? "").font(ElchiFont.poppins(12, meta == nil ? .regular : .semibold)).foregroundStyle(c.accentText)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Text(strings.money(listing.totalMinor)).font(ElchiFont.poppins(16, .semibold)).foregroundStyle(c.text)
            }
            .padding(.top, 2)
            if let thread {
                ElchiButton(strings.t("driver.feed.viewOffer"), variant: .neutral, size: .medium) { onThread(thread) }
                    .padding(.top, 4)
                    .accessibilityIdentifier("elchi.dirFeed.viewOffer.\(listing.id)")
            } else {
                // The design's feed button is the brand one (azure, navy text); another time: outlined.
                Button { onOffer(item) } label: {
                    Text(strings.t("driverFeed.sendOffer")).font(ElchiFont.buttonSmall).lineLimit(1)
                        .foregroundStyle(otherTime ? c.text : c.onBrand)
                        .frame(maxWidth: .infinity).frame(height: 44)
                        .background(otherTime ? Color.clear : c.brand, in: Capsule())
                        .overlay { if otherTime { Capsule().strokeBorder(c.outline, lineWidth: 1.5) } }
                        .contentShape(Capsule())
                }
                .buttonStyle(PressFade())
                .padding(.top, 4)
                .accessibilityIdentifier("elchi.dirFeed.offer.\(listing.id)")
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 14)
        .background(c.card, in: RoundedRectangle(cornerRadius: ElchiShape.cardV3))
        .overlay {
            if otherTime {
                RoundedRectangle(cornerRadius: ElchiShape.cardV3).strokeBorder(c.tone(.warn).fg.opacity(0.5), style: StrokeStyle(lineWidth: 1.5, dash: [6, 4]))
            }
        }
        .shadow(color: c.softShadow, radius: 12, y: 6)
        .contentShape(RoundedRectangle(cornerRadius: ElchiShape.cardV3))
        .onTapGesture(perform: onOpen)
        .accessibilityElement(children: .contain)
        .accessibilityAction(named: Text(strings.t("driver.v3trip.openListing")), onOpen)
        .accessibilityIdentifier("elchi.dirFeed.card.\(listing.id)")
    }

    /// The driver's own offer (Safar 5.7), the same join as Android: price, the client's counter, or accepted.
    private var meta: String? {
        switch mark {
        case .offered(_, let total): strings.t("driver.feed.myOffer", ("price", strings.money(total)))
        case .countered: strings.t("negotiation.clientCountered")
        case .accepted: strings.t("driver.feed.clientAccepted")
        case .none: item.myThreadId == nil ? nil : strings.t("dir.card.myOffer")
        }
    }

    private var lines: [(text: String, warn: Bool)] {
        let listing = item.listing
        var out: [(String, Bool)] = [(strings.t("dir.card.asked", ("start", DirectionFeed.dayClock(listing.departureWindowStart)),
                                              ("end", DirectionFeed.clock(listing.departureWindowEnd))), false)]
        if let eta = item.pickupEta {
            out.append((strings.t("dir.card.eta", ("time", DirectionFeed.dayClock(eta))), item.fit == "time_differs"))
        }
        if item.fit == "no_trip", let departure = item.suggestedDepartureAt {
            out.append((strings.t("dir.card.departure", ("time", DirectionFeed.dayClock(departure))), false))
        }
        if let parcel = strings.parcelLine(listing) { out.append((parcel, false)) }
        return out
    }
}

// MARK: - Narx taklif qiling (from a direction)

/// Pricing one request from a direction: no trip picker (the server takes, re-times or plans the trip). The summary,
/// the car's time, the time-proposal sentence when the car is there at another time, the rival board, the price (or
/// the client's price in one tap), the commission estimate, the no-hold note.
struct DirectionOfferView: View {
    let model: DirectionOfferModel
    let onBack: () -> Void
    let onSent: (DirectionOfferDTO) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var priceText = ""
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
        // Safar 7.11: no message field (the design and Android have none; chat opens with the booking, Q100).
        if let result = await model.send(unitPriceMinor: unitPriceMinor, message: nil) { onSent(result) }
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
