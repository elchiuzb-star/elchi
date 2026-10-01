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
                ForEach(sections.history, id: \.id) { TripCard(trip: $0, trips: trips) { onOpen($0) } }
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
        ItemCard(title: strings.route(trip), icon: .route, sub: strings.tripMeta(trip), lines: lines) {
            if let next = actions.next {
                ElchiButton(strings.t(next.labelKey), variant: .soft, size: .medium, loading: trips.running == trip.id) {
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
        var out = [ItemLine(strings.t("driverRoutes.status", ("status", strings.tripStatus(trip.status))), tone: TripStatusStyle.tone(trip.status))]
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

    private var approved: [VehicleDTO] { (driver.vehicles ?? []).filter { $0.verificationStatus == "approved" } }
    private var vehicle: VehicleDTO? { approved.first { $0.id == model.form.vehicleId } }

    var body: some View {
        @Bindable var model = model
        let problems = model.problems(vehicle: vehicle)
        ScreenScaffold(title: strings.t("driverRoutes.addRoute"), backLabel: strings.t("common.back"), onBack: onBack) {
            vehicleField
            corridorField
            if (model.routes?.value?.count ?? 0) > 1 { stopFilter }
            routeField
            PickerField(label: strings.t("addRoute.departureTime"), value: model.form.start.map(DepartureWindow.text),
                        placeholder: strings.t("client.routeSummary.windowPlaceholder"), error: problems[.start] == .past) { picking = true }
            if problems[.start] == .past { fieldError(strings.t("app.validation.windowPast")) }
            numberField($model.form.seats, .seats, label: strings.t("addRoute.freeSeats"), problems)
            HStack(alignment: .top, spacing: 10) {
                numberField($model.form.cargoKg, .cargoKg, label: strings.t("driverProfileForm.cargoKg"), problems)
                numberField($model.form.cargoLitres, .cargoLitres, label: strings.t("driverProfileForm.cargoLitres"), problems)
            }
            Text(strings.t("addRoute.plannedOnApprovedRoute")).font(ElchiFont.caption).foregroundStyle(c.muted)
                .fixedSize(horizontal: false, vertical: true)
            if let error = model.error, model.refused == nil {
                Note(strings.marketErrorText(error), tone: .err).accessibilityIdentifier("elchi.addTrip.error")
            }
        } footer: {
            ElchiButton(strings.t("common.save"), loading: model.saving) {
                Task { if let trip = await model.save(vehicle: vehicle) { onSaved(trip) } }
            }
            .disabled(!problems.isEmpty || approved.isEmpty)
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
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var asking: TripCommand?

    var body: some View {
        ScreenScaffold(title: strings.t("trip.detailsTitle"), backLabel: strings.t("common.back"), onBack: onBack) {
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
                        await trips.run(command, on: trip, reason: reason)
                        asking = nil
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
        HStack(spacing: 8) {
            if actions.canCancel {
                ElchiButton(strings.t("driver.trip.cancel"), variant: .dangerSoft, size: .pair) { trips.clearRefusal(trip.id); asking = .cancel }
            }
            ElchiButton(strings.t("tripDetail.refresh"), variant: .neutral, size: .pair, icon: .refresh) { Task { await model.load() } }
        }
        .disabled(trips.running != nil)
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

    /// The stops in order with their planned time (and the ETA when the server has one).
    private func stops(_ trip: TripDTO) -> some View {
        let now = Date()
        let sorted = trip.stops.sorted { $0.seq < $1.seq }
        return StepLadder(sorted.enumerated().map { index, stop in
            let planned = ServerTime.parse(stop.plannedArrivalAt)
            let eta = ServerTime.parse(stop.etaArrivalAt)
            let state: StepLadder.Step.State = switch trip.status {
            case .inProgress: (eta ?? planned).map { $0 < now } == true ? .done : (index == 0 ? .done : .ahead)
            case .completed: .done
            default: index == 0 ? .current : .ahead
            }
            var detail = [strings.t("tripDetail.stopSeq", ("seq", stop.seq)), planned.map(DepartureWindow.shortText)].compactMap { $0 }
            if let eta { detail.append("ETA \(strings.clock(eta))") }
            return StepLadder.Step(strings.stopName(stop.stop), detail: detail.joined(separator: " · "), state: state)
        }, doneLabel: strings.t("client.tracking.stepDone"), currentLabel: strings.t("client.tracking.stepCurrent"))
    }

    @ViewBuilder
    private var availability: some View {
        let names = Dictionary((model.trip.value?.stops ?? []).map { ($0.stop.id, strings.stopName($0.stop)) }, uniquingKeysWith: { a, _ in a })
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

    /// Pickups and drop-offs per stop. A phone only when the server sends it (its rules: a parcel's receiver only after
    /// departure); otherwise the grey note. The chat button waits for the booking screens (Stage 09).
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
                    Text(strings.t("tripDetail.manifestEmpty")).font(ElchiFont.caption).foregroundStyle(c.muted).padding(.vertical, 8)
                } else {
                    ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                        let (stop, item, pickup) = row
                        let place = stop.stop.map(strings.stopName) ?? stop.point.map { strings.feedEnd(stop: nil, point: $0) } ?? "#\(stop.seq)"
                        let when = ServerTime.parse(stop.plannedArrivalAt).map(strings.clock) ?? ""
                        let what = item.parcelSummary.map { "\(strings.t("tripDetail.parcel")): \($0)" }
                            ?? item.seats.map { strings.t("tripDetail.seats", ("count", $0)) } ?? ""
                        let status = strings.tOrNil("tripDetail.service.\(item.serviceStatus)")
                        CardRow("\(place) · \(when) · \(strings.t(pickup ? "tripDetail.pickups" : "tripDetail.dropoffs"))",
                                "\(item.clientFirstName) — \(what)\(status.map { " · \($0)" } ?? "")",
                                detail: item.contactPhone.map { UzPhone.display($0) }
                                    ?? strings.t(item.serviceType == .parcel ? "tripDetail.phoneAfterPickup" : "tripDetail.phoneAfterStart"))
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
