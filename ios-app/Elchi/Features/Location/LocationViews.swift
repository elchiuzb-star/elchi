import SwiftUI

// MARK: - Region

/// Step 1 of a place (Q88): the region. Regions without districts (Tashkent city) go straight to the map.
struct RegionPickerView: View {
    let model: ParcelRequestModel
    let side: EndSide
    let onBack: () -> Void
    let onPick: (RegionDTO) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var query = ""

    var body: some View {
        ScreenScaffold(title: strings.t(side == .pickup ? "direction.from" : "direction.to"), backLabel: strings.t("common.back"), onBack: onBack) {
            ElchiField(text: $query, placeholder: strings.t("location.search"), icon: .search)
            Text(strings.t("client.location.pickRegionSubtitle")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
            switch model.regions {
            case .loading:
                Text(strings.t("location.regionsLoading")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
                SkeletonCards(count: 2)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err, title: strings.t("location.regionsLoadFailed"))
                ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.loadRegions() } }
            case .loaded(let regions):
                let shown = regions.filter { SearchText.matches(strings.name($0), query) || SearchText.matches($0.nameUz, query) }
                if shown.isEmpty {
                    Text(strings.t("client.order.listEmpty")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
                        .frame(maxWidth: .infinity).padding(.vertical, 24)
                } else {
                    ElchiList {
                        ForEach(Array(shown.enumerated()), id: \.element.id) { index, region in
                            ListRow(icon: .pin, title: strings.name(region),
                                    description: strings.t(region.requiresDistrict == false ? "location.noDistrict" : "location.districtRequired"),
                                    first: index == 0) { onPick(region) }
                        }
                    }
                }
            }
        } footer: {
            EmptyView()
        }
        .task { await model.loadRegions() }
    }
}

// MARK: - District

struct DistrictPickerView: View {
    let model: ParcelRequestModel
    let region: RegionDTO
    let side: EndSide
    let onBack: () -> Void
    let onPick: (DistrictDTO) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var query = ""

    var body: some View {
        ScreenScaffold(title: strings.t("location.pickDistrict"), right: strings.name(region), backLabel: strings.t("common.back"), onBack: onBack) {
            ElchiField(text: $query, placeholder: strings.t("location.search"), icon: .search)
            switch model.districts[region.id] ?? .loading {
            case .loading:
                Text(strings.t("location.districtsLoading")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
                SkeletonCards(count: 2)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err, title: strings.t("location.districtsLoadFailed"))
                ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) {
                    Task { await model.loadDistricts(region: region) }
                }
            case .loaded(let districts):
                let shown = districts.filter { $0.isActive != false && (SearchText.matches(strings.name($0), query) || SearchText.matches($0.nameUz, query)) }
                if shown.isEmpty {
                    Text(strings.t("client.order.listEmpty")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
                        .frame(maxWidth: .infinity).padding(.vertical, 24)
                } else {
                    ElchiList {
                        ForEach(Array(shown.enumerated()), id: \.element.id) { index, district in
                            ListRow(icon: .pin, title: strings.name(district), description: strings.name(region), first: index == 0) { onPick(district) }
                        }
                    }
                }
            }
        } footer: {
            EmptyView()
        }
        .task { await model.loadDistricts(region: region) }
    }
}

// MARK: - Point

/// Step 3 of a place: the point itself. With a map: a fixed centre pin, the camera moves, the address follows.
/// Without one: search (suggest -> resolve) or the district centre. Never blocked on the map.
struct PointPickerView: View {
    let model: ParcelRequestModel
    let side: EndSide
    let region: RegionDTO
    let district: DistrictDTO?
    let onBack: () -> Void
    let onChosen: (PlaceEnd) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var picker: PointPickerModel
    @State private var availability = MapAvailability.shared
    @State private var queryText = ""
    @FocusState private var searching: Bool

    init(model: ParcelRequestModel, side: EndSide, region: RegionDTO, district: DistrictDTO?, locale: AppLocale, onBack: @escaping () -> Void,
         onChosen: @escaping (PlaceEnd) -> Void) {
        self.model = model
        self.side = side
        self.region = region
        self.district = district
        self.onBack = onBack
        self.onChosen = onChosen
        _picker = State(initialValue: PointPickerModel(region: region, district: district, current: model.end(side), geo: model.geo, locale: locale))
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                RoundIconButton(.back, label: strings.t("common.back"), action: onBack)
                // Design: "Qayerdan: Samarqand, Samarqand viloyati" in a pill next to the back button.
                Text(strings.t(side == .pickup ? "client.order.pointTitleFrom" : "client.order.pointTitleTo", ("area", area)))
                    .font(ElchiFont.poppins(15, .medium, relativeTo: .headline)).foregroundStyle(c.text).lineLimit(1)
                    .padding(.horizontal, 16)
                    .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                    .background(c.card, in: Capsule())
                    .shadow(color: c.shadow, radius: 12, y: 6)
                    .accessibilityAddTraits(.isHeader)
            }
            .frame(height: 64)
            .padding(.horizontal, 16)
            ZStack(alignment: .top) {
                ElchiMap(focus: picker.focus, zoom: 14, centrePin: true, placeholder: strings.t("client.map.unavailable")) { picker.cameraIdle($0) }
                search.padding(.horizontal, 16).padding(.top, 8)
            }
            sheet
        }
        .background(c.page.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
        .task {
            if district == nil { await model.loadDistricts(region: region) }
            await loadStops()
        }
    }

    private var area: String {
        district.map { "\(strings.name($0)), \(strings.name(region))" } ?? strings.name(region)
    }

    /// Verified stops of this district (or of the region's districts where it has none to choose), as chips. Only
    /// districts whose `stops_count` says there is something are looked up.
    private func loadStops() async {
        let candidates = district.map { [$0] } ?? model.districtList(region)
        let ids = Set(candidates.filter { $0.stopsCount > 0 }.map(\.id))
        guard !ids.isEmpty else { return }
        picker.setStops(await model.stops(inDistricts: ids))
    }

    private var search: some View {
        VStack(spacing: 8) {
            HStack(spacing: 10) {
                ElchiIcon.search.image(size: 18).foregroundStyle(c.muted)
                // SwiftUI's TextField does not follow a binding the model rewrites (it clears the query after a pick),
                // so the field keeps its own text and is re-synced from the model.
                TextField("", text: $queryText, prompt: Text(strings.t("location.searchPlaceholder")).foregroundStyle(c.placeholder))
                    .onChange(of: queryText) { _, typed in picker.query = typed }
                    .onChange(of: picker.query) { _, value in if queryText != value { queryText = value } }
                    .font(ElchiFont.poppins(14))
                    .foregroundStyle(c.text)
                    .focused($searching)
                    .submitLabel(.search)
                    .accessibilityLabel(strings.t("location.searchPlaceholder"))
                if picker.resolving { ProgressView() }
            }
            .padding(.horizontal, 18)
            .frame(height: 50)
            .background(c.card, in: Capsule())
            .shadow(color: c.shadow, radius: 12, y: 6)
            if !picker.suggestions.isEmpty {
                ElchiList {
                    ForEach(Array(picker.suggestions.prefix(6).enumerated()), id: \.element.id) { index, item in
                        ListRow(icon: .pin, title: item.title ?? item.formattedAddress ?? "", description: item.subtitle ?? item.formattedAddress,
                                chevron: false, first: index == 0) {
                            searching = false
                            Task { await picker.pick(item) }
                        }
                    }
                }
            } else if picker.searchMiss {
                Note(strings.t(availability.isAvailable ? "location.searchMiss" : "client.pointPicker.searchMissNoMap"), tone: .gray)
            } else if let error = picker.searchError {
                Note(strings.errorText(error), tone: .err)
            } else if !availability.isAvailable && !searching {
                Note(strings.t("client.map.unavailableHint"), tone: .gray)
            }
        }
    }

    private var sheet: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(area).font(ElchiFont.poppins(14, .semibold)).foregroundStyle(c.text)
            if !picker.stops.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(picker.stops, id: \.id) { stop in
                            Chip(strings.locale == .ru ? stop.nameRu ?? stop.nameUz : stop.nameUz, selected: picker.chosenStop?.id == stop.id,
                                 icon: .pin, filled: true) { picker.pickStop(stop) }
                        }
                    }
                    .padding(.vertical, 2)
                }
                .accessibilityIdentifier("elchi.point.stops")
            }
            ElchiCard {
                CardRow(strings.t("location.chosenPlace"), placeValue, first: true, detail: picker.centre.text, placeholder: picker.address == .resolving)
            }
            Text(radiusHint).font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
            if !availability.isAvailable {
                ElchiButton(strings.t("client.pointPicker.useDistrictCentre"), variant: .ghost, size: .medium, icon: .locate) {
                    picker.useDistrictCentre()
                }
            }
            ElchiButton(strings.t("location.pickThisPlace")) {
                if let end = picker.makeEnd(regionDistricts: model.districtList(region)) { onChosen(end) }
            }
            .disabled(picker.address == .resolving || (district == nil && model.districtList(region).isEmpty))
        }
        .padding(EdgeInsets(top: 20, leading: 16, bottom: 12, trailing: 16))
        .background {
            UnevenRoundedRectangle(topLeadingRadius: ElchiShape.sheet, topTrailingRadius: ElchiShape.sheet)
                .fill(c.card)
                .shadow(color: c.shadow, radius: 12, y: -6)
                .ignoresSafeArea(edges: .bottom)
        }
    }

    private var placeValue: String {
        switch picker.address {
        case .resolving: strings.t("location.addressResolving")
        case .found(let text): text
        case .unavailable: strings.t("app.endLabel.mapPlace")
        }
    }

    /// The server's own tolerance once a direction was checked; otherwise the general rule (no invented number).
    private var radiusHint: String {
        if let preview = model.preview {
            return strings.t("location.radiusHintKm", ("km", RouteFigures.kilometres(preview.maxPointOffsetM)))
        }
        return strings.t("location.radiusHintGeneric")
    }
}
