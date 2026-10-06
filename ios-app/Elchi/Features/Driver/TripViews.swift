import SwiftUI

// MARK: - Yo'nalishlar (my trips)

/// The driver's private trip plans (Q138: a plan, never a listing a client sees): active ones first with their next
/// step, then the history. "+" adds one; a card opens the trip.
struct TripsTabView: View {
    let trips: TripsModel
    let onAdd: () -> Void
    let onOpen: (String) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        DriverTabScreen(title: strings.t("driverRoutes.title"), plus: (strings.t("driverRoutes.addRoute"), onAdd)) {
            switch trips.trips {
            case .loading:
                SkeletonCards(count: 3)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err)
                ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await trips.load() } }
            case .loaded(let list) where list.isEmpty:
                EmptyState(icon: .route, title: strings.t("driverRoutes.empty"), description: strings.t("driver.routes.privateHint"))
                ElchiButton(strings.t("driverRoutes.addRoute"), variant: .soft, icon: .plus, action: onAdd)
            case .loaded(let list):
                let sections = TripList.sections(list)
                Text(strings.t("driver.routes.privateHint")).font(ElchiFont.caption).foregroundStyle(c.muted)
                ForEach(sections.active, id: \.id) { TripCard(trip: $0, trips: trips) { onOpen($0) } }
                // DESIGN07 2.3: the finished ones faded under the live / planned ones.
                ForEach(sections.history, id: \.id) { TripCard(trip: $0, trips: trips) { onOpen($0) }.opacity(0.7) }
            }
        }
        .refreshable { await trips.load() }
        .task { await trips.load() }
    }
}

/// One trip: route, date · stops · seats, the status in its tone, and the next step (the boarding window hint on a
/// planned one; the refusal's sentence when the server said no).
struct TripCard: View {
    let trip: TripDTO
    let trips: TripsModel
    let onOpen: (String) -> Void
    @Environment(LocaleStore.self) private var strings

    var body: some View {
        let actions = TripActions.of(trip.status)
        ItemCard(title: strings.route(trip), icon: .route, badge: (strings.tripStatus(trip.status), TripStatusStyle.tone(trip.status)),
                 sub: strings.tripMeta(trip), lines: lines) {
            if let next = actions.next {
                ElchiButton(strings.t(next.labelKey), size: .medium, loading: trips.running == trip.id) {
                    Task { await trips.run(next, on: trip) }
                }
                .disabled(trips.running != nil && trips.running != trip.id)
                .padding(.top, 6)
                .accessibilityIdentifier("elchi.trip.next.\(trip.id)")
            }
        }
        .contentShape(Rectangle())
        .onTapGesture { onOpen(trip.id) }
        .accessibilityElement(children: .contain)
        .accessibilityAction(named: Text(strings.t("trip.detailsTitle"))) { onOpen(trip.id) }
        .accessibilityIdentifier("elchi.trip.\(trip.id)")
    }

    private var lines: [ItemLine] {
        // DESIGN07 2.1: the status is the badge at the top right; the lines are the next step's hint and any refusal.
        var out: [ItemLine] = []
        if trip.status == .planned { out.append(ItemLine(strings.t("driverRoutes.boardingWindowHint"))) }
        if let error = trips.refusals[trip.id] {
            out.append(ItemLine(strings.tripRefusalText(error), tone: TripRefusal.of(error) == .other ? .err : .warn))
        }
        return out
    }
}

// MARK: - Yo'nalish qo'shish

/// Planning a trip on an operator-approved route (web ConnectedApp.tsx:6246): approved vehicles only, a corridor and
/// its route (found by a stop when there are several), the departure, seats and cargo within the vehicle.
struct AddTripView: View {
    let model: AddTripModel
    let driver: DriverModel
    let onBack: () -> Void
    let onSaved: (TripDTO) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var picking = false
    @State private var stopQuery = ""
    /// "Saqlash" was tapped with something missing: every field says what (DESIGN07 3.7).
    @State private var tried = false
    @State private var scrollTop = 0

    private var approved: [VehicleDTO] { (driver.vehicles ?? []).filter { $0.verificationStatus == "approved" } }
    private var vehicle: VehicleDTO? { approved.first { $0.id == model.form.vehicleId } }

    var body: some View {
        @Bindable var model = model
        let problems = model.problems(vehicle: vehicle)
        let departureKey = TripPlan.departureKey(tried || problems[.start] == .past ? problems[.start] : nil)
        ScreenScaffold(title: strings.t("driverRoutes.addRoute"), backLabel: strings.t("common.back"), onBack: onBack, scrollTop: scrollTop) {
            vehicleField
            if tried, problems[.vehicle] != nil, !approved.isEmpty { fieldError(strings.t("addRoute.vehiclePlaceholder")) }
            corridorField
            if tried, problems[.corridor] != nil { fieldError(strings.t("addRoute.corridorPlaceholder")) }
            if (model.routes?.value?.count ?? 0) > 1 { stopFilter }
            routeField
            if tried, problems[.route] != nil, model.form.corridorId != nil { fieldError(strings.t("addRoute.routePlaceholder")) }
            PickerField(label: strings.t("addRoute.departureTime"), value: model.form.start.map(DepartureWindow.text),
                        placeholder: strings.t("client.routeSummary.windowPlaceholder"), error: departureKey != nil) { picking = true }
            if let departureKey { fieldError(strings.t(departureKey)).accessibilityIdentifier("elchi.addTrip.departureError") }
            numberField($model.form.seats, .seats, label: strings.t("addRoute.freeSeats"), problems)
            HStack(alignment: .top, spacing: 10) {
                numberField($model.form.cargoKg, .cargoKg, label: strings.t("driverProfileForm.cargoKg"), problems)
                numberField($model.form.cargoLitres, .cargoLitres, label: strings.t("driverProfileForm.cargoLitres"), problems)
            }
            // DESIGN07 3.6: the two sentences, then the vehicle's seat ceiling once a vehicle is chosen.
            Text([strings.t("addRoute.plannedOnApprovedRoute"), vehicle.map { strings.t("driver.trip.seatsMaxNote", ("count", $0.seatCapacity)) }]
                    .compactMap { $0 }.joined(separator: " "))
                .font(ElchiFont.caption).foregroundStyle(c.muted)
                .fixedSize(horizontal: false, vertical: true)
            if let error = model.error, model.refused == nil {
                Note(strings.marketErrorText(error), tone: .err).accessibilityIdentifier("elchi.addTrip.error")
            }
        } footer: {
            // Always tappable while there is a vehicle: a tap with gaps marks every field and goes back to the top.
            ElchiButton(strings.t("common.save"), loading: model.saving, dimmed: !problems.isEmpty) {
                guard problems.isEmpty else {
                    tried = true
                    scrollTop += 1
                    return
                }
                Task { if let trip = await model.save(vehicle: vehicle) { onSaved(trip) } }
            }
            .disabled(approved.isEmpty)
            .accessibilityIdentifier("elchi.addTrip.save")
        }
        .sheet(isPresented: $picking) {
            WindowPickerSheet(title: strings.t("addRoute.departureTime"), initial: model.form.start ?? DepartureWindow.suggested().start) { date in
                model.form.start = date
                picking = false
            }
        }
        .task {
            await driver.loadVehicles()
            await model.loadCorridors()
            if model.form.vehicleId == nil, approved.count == 1 { model.chooseVehicle(approved[0]) }
        }
    }

    // MARK: Fields

    @ViewBuilder
    private var vehicleField: some View {
        if approved.count == 1, let only = approved.first {
            // DESIGN07 3.1: the one approved car is read-only here (Q94: changed only through an operator).
            LockedField(label: strings.t("addRoute.vehicle"),
                        value: strings.t("addRoute.vehicleOption", ("model", only.makeModel), ("plate", only.plateMasked), ("seats", only.seatCapacity)),
                        hint: strings.t("driver.trip.vehicleLocked"))
                .accessibilityIdentifier("elchi.addTrip.vehicleLocked")
        } else {
            vehicleSelect
        }
    }

    @ViewBuilder
    private var vehicleSelect: some View {
        SelectField(label: strings.t("addRoute.vehicle"),
                    options: approved.map { ($0.id, strings.t("addRoute.vehicleOption", ("model", $0.makeModel), ("plate", $0.plateMasked),
                                                                 ("seats", $0.seatCapacity))) },
                    selected: model.form.vehicleId,
                    placeholder: strings.t(approved.isEmpty ? "addRoute.noApprovedVehicle" : "addRoute.vehiclePlaceholder")) { id in
            if let picked = approved.first(where: { $0.id == id }) { model.chooseVehicle(picked) }
        }
        if driver.vehicles != nil && approved.isEmpty {
            // Q96-style: say why and what is next, and keep "Saqlash" off.
            let statuses = (driver.vehicles ?? []).map { "\($0.makeModel) · \(strings.tOrNil("vehicleStatus.\($0.verificationStatus)") ?? $0.verificationStatus)" }
            Note(([strings.t("addRoute.vehicleNeedsReview")] + statuses).joined(separator: "\n"), tone: .err, title: strings.t("addRoute.noApprovedVehicle"))
        }
    }

    @ViewBuilder
    private var corridorField: some View {
        switch model.corridors {
        case .failed(let error):
            Note(strings.errorText(error), tone: .err)
            ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.loadCorridors() } }
        default:
            SelectField(label: strings.t("addRoute.corridor"), options: (model.corridors.value ?? []).map { ($0.id, $0.name) },
                        selected: model.form.corridorId, placeholder: strings.t("addRoute.corridorPlaceholder")) { id in
                Task { await model.chooseCorridor(id) }
            }
        }
    }

    /// Several approved routes: a stop name finds the ones that pass it (the stops stay the route's own).
    @ViewBuilder
    private var stopFilter: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let stop = model.stopFilter {
                Text(strings.t("tripPlan.stopFilter", ("name", stop.nameUz))).font(ElchiFont.poppins(13, .medium)).foregroundStyle(c.text)
                if model.shownRoutes.isEmpty {
                    Text(strings.t("tripPlan.stopFilterNone", ("name", stop.nameUz))).font(ElchiFont.caption).foregroundStyle(c.tone(.warn).fg)
                }
                Button(strings.t("tripPlan.stopFilterClear")) {
                    stopQuery = ""
                    model.filter(by: nil)
                }
                .font(ElchiFont.poppins(13, .semibold)).foregroundStyle(c.accentText).frame(minHeight: 44)
            } else {
                ElchiField(text: $stopQuery, placeholder: strings.t("tripPlan.stopSearchLabel"), icon: .search)
                ForEach(model.stopResults, id: \.id) { stop in
                    Button {
                        model.filter(by: stop)
                    } label: {
                        HStack {
                            Text(strings.locale == .ru ? stop.nameRu ?? stop.nameUz : stop.nameUz).font(ElchiFont.poppins(14, .medium)).foregroundStyle(c.text)
                            Spacer(minLength: 0)
                            Text(stop.district.nameUz).font(ElchiFont.caption).foregroundStyle(c.muted)
                        }
                        .frame(minHeight: 44)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay { RoundedRectangle(cornerRadius: 14).strokeBorder(c.line, lineWidth: 1) }
        .task(id: stopQuery) {
            try? await Task.sleep(for: .milliseconds(300))
            if !Task.isCancelled { await model.searchStops(stopQuery) }
        }
    }

    @ViewBuilder
    private var routeField: some View {
        let routes = model.shownRoutes
        SelectField(label: strings.t("addRoute.route"),
                    options: routes.map { route in
                        let figures = TripPlan.figures(route)
                        return (route.id, strings.t("addRoute.routeOption", ("stops", figures.stops), ("km", figures.km), ("hours", figures.hours)))
                    },
                    selected: model.form.routeId,
                    placeholder: strings.t(model.form.corridorId == nil ? "addRoute.pickCorridorFirst" : "addRoute.routePlaceholder")) { id in
            model.form.routeId = id
        }
        .disabled(model.form.corridorId == nil)
        if case .loaded(let all)? = model.routes, all.isEmpty { fieldError(strings.t("addRoute.noApprovedRoute")) }
        if case .failed(let error)? = model.routes { fieldError(strings.errorText(error)) }
    }

    private func numberField(_ text: Binding<String>, _ field: TripPlanField, label: String,
                             _ problems: [TripPlanField: TripPlanProblem]) -> some View {
        ElchiField(text: text, label: label, error: problemText(problems[field]), keyboard: .numberPad)
            .onChange(of: text.wrappedValue) { _, _ in model.clearRefused(field) }
    }

    private func problemText(_ problem: TripPlanProblem?) -> String? {
        switch problem {
        case .overLimit(let limit): strings.t("driver.trip.vehicleLimit", ("limit", limit))
        case .notNumber: strings.t("error.VALIDATION_ERROR")
        case .nothingOffered: strings.t("addRoute.plannedOnApprovedRoute")
        default: nil
        }
    }

    private func fieldError(_ text: String) -> some View {
        Text(text).font(ElchiFont.caption).foregroundStyle(c.tone(.err).fg).fixedSize(horizontal: false, vertical: true)
    }
}

// MARK: - Safar tafsilotlari

/// One trip: header, stops, free capacity per segment (computed, not reserved), the manifest, and the commands
/// (next step, pause / resume with a reason, cancel with a reason behind a danger confirmation, refresh).
struct TripDetailView: View {
    let model: TripDetailModel
    let trips: TripsModel
    let onBack: () -> Void
    /// DESIGN07 4.4: a manifest row's "Chat" opens that booking's chat.
    var onChat: (String) -> Void = { _ in }
    /// DESIGN07 4.7: after a cancel the list shows again.
    var onCancelled: () -> Void = {}
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(BannerCenter.self) private var banners: BannerCenter?
    @State private var asking: TripCommand?
    @State private var refreshing = false

    var body: some View {
        ScreenScaffold(title: strings.t("trip.detailsTitle"), backLabel: strings.t("common.back"), onBack: onBack,
                       actions: [BarAction(id: "refresh", icon: .refresh, label: strings.t("proposal.refresh"), loading: refreshing) {
                           Task {
                               refreshing = true
                               await model.load()
                               refreshing = false
                               banners?.ok("client.booking.refreshed")
                           }
                       }]) {
            switch model.trip {
            case .loading:
                SkeletonCards(count: 3)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err)
                ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.load() } }
            case .loaded(let trip):
                content(trip)
            }
        } footer: {
            EmptyView()
        }
        .refreshable { await model.load() }
        .task { await model.load() }
        .sheet(item: $asking) { command in
            if let trip = model.trip.value {
                ReasonSheet(command: command, working: trips.running == trip.id) { reason in
                    // A refusal closes the sheet too: the detail says why, under the trip.
                    Task {
                        let done = await trips.run(command, on: trip, reason: reason)
                        asking = nil
                        if done && command == .cancel { onCancelled() }
                    }
                } onBack: { asking = nil }
            }
        }
    }

    @ViewBuilder
    private func content(_ trip: TripDTO) -> some View {
        let actions = TripActions.of(trip.status)
        header(trip)
        stops(trip)
        availability
        manifest(trip)
        if let error = trips.refusals[trip.id] {
            Note(strings.tripRefusalText(error), tone: TripRefusal.of(error) == .other ? .err : .warn).accessibilityIdentifier("elchi.trip.refusal")
        }
        if let next = actions.next {
            ElchiButton(strings.t(next.labelKey), loading: trips.running == trip.id && asking == nil) { Task { await trips.run(next, on: trip) } }
                .accessibilityIdentifier("elchi.trip.next")
        }
        if actions.canPause || actions.canResume {
            let command: TripCommand = actions.canPause ? .interrupt : .resume
            ElchiButton(strings.t(command.labelKey), variant: .soft) { trips.clearRefusal(trip.id); asking = command }
        }
        // DESIGN07 0.3: refresh is the bar's icon now; cancel stands alone.
        if actions.canCancel {
            ElchiButton(strings.t("driver.trip.cancel"), variant: .dangerSoft) { trips.clearRefusal(trip.id); asking = .cancel }
                .disabled(trips.running != nil)
                .accessibilityIdentifier("elchi.trip.cancel")
        }
    }

    private func header(_ trip: TripDTO) -> some View {
        ElchiCard {
            CardTitle(strings.route(trip), badge: (strings.tripStatus(trip.status), TripStatusStyle.tone(trip.status)))
            CardRow(strings.t("tripDetail.departure"), time(trip.plannedStartAt))
            CardRow(strings.t("tripDetail.arrival"), time(trip.plannedEndAt))
            CardRow(strings.t("tripDetail.vehicle"), "\(trip.vehicle.makeModel), \(trip.vehicle.color) · \(trip.vehicle.plateMasked)")
            CardRow(strings.t("tripDetail.seatsLabel"), strings.t("tripDetail.seatsValue", ("count", trip.seatCapacity)))
            if let cutoff = ServerTime.parse(trip.bookingCutoffAt) {
                CardRow(strings.t("tripDetail.cutoffLabel"), strings.t("tripDetail.cutoffValue", ("time", DepartureWindow.shortText(cutoff))))
            }
        }
        .accessibilityIdentifier("elchi.trip.header")
    }

    /// Q158 (ADR-0027): the road as districts with the estimated time (the ETA when the server has one, else the
    /// planned one) - never the internal route nodes. Consecutive nodes in one district read as one place.
    @ViewBuilder
    private func stops(_ trip: TripDTO) -> some View {
        let places = TripPlaces.alongTheRoad(trip.stops.sorted { $0.seq < $1.seq }) { strings.placeName($0.stop) }
        SectionTitle(strings.t("tripDetail.alongTheRoad")).accessibilityIdentifier("elchi.trip.alongTheRoad")
        StepLadder(places.enumerated().map { index, place in
            // DESIGN07 4.2: the dots follow the trip status (the DTO has no per-stop passage).
            let state: StepLadder.Step.State = switch TripStopDot.of(index: index, status: trip.status) {
            case .done: .done
            case .current: .current
            case .ahead: .ahead
            }
            let when = ServerTime.parse(place.stop.etaArrivalAt) ?? ServerTime.parse(place.stop.plannedArrivalAt)
            return StepLadder.Step(place.name, detail: when.map(DepartureWindow.shortText) ?? "", state: state)
        }, doneLabel: strings.t("client.tracking.stepDone"), currentLabel: strings.t("client.tracking.stepCurrent"))
    }

    @ViewBuilder
    private var availability: some View {
        let names = Dictionary((model.trip.value?.stops ?? []).map { ($0.stop.id, strings.placeName($0.stop)) }, uniquingKeysWith: { a, _ in a })
        ElchiCard {
            CardTitle(strings.t("tripDetail.availabilityTitle"))
            switch model.availability {
            case .loading:
                SkeletonCards(count: 1).padding(.vertical, 8)
            case .failed(let error):
                Text(strings.errorText(error)).font(ElchiFont.caption).foregroundStyle(c.tone(.err).fg).padding(.vertical, 8)
            case .loaded(let dto) where dto.segments.isEmpty:
                Text(strings.t("tripDetail.availabilityEmpty")).font(ElchiFont.caption).foregroundStyle(c.muted).padding(.vertical, 8)
            case .loaded(let dto):
                let segments = dto.segments.sorted { $0.fromSeq < $1.fromSeq }
                ForEach(Array(segments.enumerated()), id: \.offset) { index, segment in
                    CardRow("\(names[segment.fromStopId] ?? "#\(segment.fromSeq)") → \(names[segment.toStopId] ?? "#\(segment.toSeq)")",
                            strings.segmentLine(segment),
                            detail: index == segments.count - 1
                                ? strings.t("tripDetail.computedNote", ("time", ServerTime.parse(dto.computedAt).map(strings.clock) ?? "?")) : nil)
                }
            }
        }
        .accessibilityIdentifier("elchi.trip.availability")
    }

    /// Pickups and drop-offs per stop. A phone only when the server sends it (Q142: a parcel's receiver once the trip
    /// departs; a passenger once on board); otherwise the grey note. "Chat" opens the booking's chat (Q100).
    @ViewBuilder
    private func manifest(_ trip: TripDTO) -> some View {
        ElchiCard {
            CardTitle(strings.t("tripDetail.manifestTitle"))
            switch model.manifest {
            case .loading:
                SkeletonCards(count: 1).padding(.vertical, 8)
            case .failed(let error):
                Text(strings.errorText(error)).font(ElchiFont.caption).foregroundStyle(c.tone(.err).fg).padding(.vertical, 8)
            case .loaded(let dto):
                let rows = dto.stops.sorted { $0.seq < $1.seq }.flatMap { stop in
                    stop.pickups.map { (stop, $0, true) } + stop.dropoffs.map { (stop, $0, false) }
                }
                if rows.isEmpty {
                    Text(strings.t("driver.trip.manifestEmpty")).font(ElchiFont.caption).foregroundStyle(c.muted).padding(.vertical, 8)
                } else {
                    ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                        let (stop, item, pickup) = row
                        // Q158: the agreed place's address or district, else the node's district.
                        let place = stop.point.map { $0.address?.isEmpty == false ? $0.address! : strings.feedEnd(stop: nil, point: $0) }
                            ?? stop.stop.map(strings.placeName) ?? "#\(stop.seq)"
                        let when = ServerTime.parse(stop.plannedArrivalAt).map(strings.clock) ?? ""
                        let what = item.parcelSummary.map { "\(strings.t("tripDetail.parcel")): \($0)" }
                            ?? item.seats.map { strings.t("tripDetail.seats", ("count", $0)) } ?? ""
                        let status = strings.tOrNil("tripDetail.service.\(item.serviceStatus)")
                        HStack(alignment: .center, spacing: 10) {
                            CardRow("\(place) · \(when) · \(strings.t(pickup ? "tripDetail.pickups" : "tripDetail.dropoffs"))",
                                    "\(item.clientFirstName) — \(what)\(status.map { " · \($0)" } ?? "")",
                                    detail: item.contactPhone.map { UzPhone.display($0) }
                                        ?? strings.t(item.serviceType == .parcel ? "driver.trip.phoneAfterDepart" : "driver.trip.phoneAfterBoard"))
                            Button { onChat(item.bookingId) } label: {
                                HStack(spacing: 6) {
                                    ElchiIcon.chat.image(size: 15)
                                    Text(strings.t("driverBooking.messages")).font(ElchiFont.poppins(13, .semibold)).lineLimit(1)
                                }
                                .foregroundStyle(c.softText)
                                .padding(.horizontal, 12).frame(minHeight: 36)
                                .background(c.soft, in: Capsule())
                                .frame(minHeight: 44)
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(PressFade())
                            .accessibilityIdentifier("elchi.trip.manifestChat.\(item.bookingId)")
                        }
                    }
                }
            }
        }
        .accessibilityIdentifier("elchi.trip.manifest")
    }

    private func time(_ text: String) -> String { ServerTime.parse(text).map(DepartureWindow.shortText) ?? "?" }
}

extension TripCommand: Identifiable {
    public var id: String { rawValue }
}

/// Pause, resume or cancel: the reason (required, the operator reads it), then the command. Cancel is the danger one.
struct ReasonSheet: View {
    let command: TripCommand
    let working: Bool
    let onConfirm: (String) -> Void
    let onBack: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var reason = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(strings.t(command.labelKey)).font(ElchiFont.poppins(20, .medium, relativeTo: .title2)).foregroundStyle(c.text)
                .accessibilityAddTraits(.isHeader)
            ElchiField(text: $reason, label: strings.t("common.reason"), hint: strings.t("driver.trip.reasonHint"), multiline: true)
            ElchiButton(strings.t(command.labelKey), variant: command == .cancel ? .danger : .primary, loading: working) {
                onConfirm(reason)
            }
            .disabled(reason.trimmingCharacters(in: .whitespacesAndNewlines).count < 3)
            .accessibilityIdentifier("elchi.reason.confirm")
            ElchiButton(strings.t("confirmDialog.back"), variant: .neutral, size: .medium, action: onBack).disabled(working)
        }
        .padding(20)
        .frame(maxHeight: .infinity, alignment: .top)
        .background(c.card.ignoresSafeArea())
        .presentationDetents([.medium])
        .presentationCornerRadius(ElchiShape.sheet)
    }
}

// MARK: - Home: the work summary (DESIGN07 1.1-1.3)

/// Under the home's balance / status / availability blocks (DESIGN06 owns those): that an offer holds no money, the
/// three counts (trips not finished, offers still open, bookings not finished - each opens its tab; "—" when a list
/// could not be read) and "Yangi safar rejalashtirish". Approved drivers only (the home decides).
struct DriverWorkSummary: View {
    let trips: TripsModel
    let proposals: DriverProposalsModel
    let bookings: DriverBookingsModel
    let onTab: (DriverTab) -> Void
    let onPlanTrip: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        let stats = DriverHomeStats.of(trips: trips.trips.value, openProposals: proposals.lists[.open]?.value,
                                       bookingStatuses: bookings.items.value?.map(\.status))
        Text(strings.t("driver.dash.balanceNoHold")).font(ElchiFont.caption).foregroundStyle(c.muted)
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityIdentifier("elchi.driver.home.noHold")
        HStack(spacing: 8) {
            tile("driver.dash.statTrips", stats.trips, tab: .routes)
            tile("client.listing.stepOffers", stats.offers, tab: .matches)
            tile("client.orders.bookings", stats.bookings, tab: .orders)
        }
        .accessibilityIdentifier("elchi.driver.home.stats")
        ElchiButton(strings.t("driver.dash.planTrip"), variant: .soft, icon: .plus, action: onPlanTrip)
            .accessibilityIdentifier("elchi.driver.home.planTrip")
            .task {
                async let offers: Void = proposals.load(.open)
                async let list: Void = bookings.load()
                _ = await (offers, list)
            }
    }

    private func tile(_ key: String, _ count: Int?, tab: DriverTab) -> some View {
        Button { onTab(tab) } label: {
            VStack(alignment: .leading, spacing: 2) {
                Text(strings.t(key)).font(ElchiFont.caption).foregroundStyle(c.muted).lineLimit(1).minimumScaleFactor(0.8)
                Text(DriverHomeStats.text(count)).font(ElchiFont.poppins(20, .semibold)).foregroundStyle(c.text).lineLimit(1)
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(c.card, in: RoundedRectangle(cornerRadius: 18))
            .shadow(color: c.shadow.opacity(0.7), radius: 12, y: 6)
            .contentShape(Rectangle())
        }
        .buttonStyle(PressFade())
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
        .accessibilityIdentifier("elchi.driver.home.stat.\(tab.rawValue)")
    }
}
