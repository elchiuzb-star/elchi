import Foundation

// Stage 08 pure logic: the driver's private trip plans (Q138), the matching-requests feed, the offer and the
// negotiation from the driver's side. No views, no network - each rule is testable on its own (like `auction.ts`).

// MARK: - Trip commands

/// What a driver can tell a trip (`POST /trips/{id}/actions/{action}`).
public enum TripCommand: String, CaseIterable, Hashable, Sendable {
    case startBoarding = "start_boarding"
    case depart
    case complete
    case interrupt
    case resume
    case cancel

    /// The button's words: the three steps forward use the web's `tripAction.*`; pause / resume / cancel are native.
    public var labelKey: String {
        switch self {
        case .startBoarding, .depart, .complete: "tripAction.\(rawValue)"
        case .interrupt: "driver.trip.pause"
        case .resume: "driver.trip.resume"
        case .cancel: "driver.trip.cancel"
        }
    }

    /// Pause, resume and cancel go to an operator with a reason (the server refuses them without one).
    public var needsReason: Bool { self == .interrupt || self == .resume || self == .cancel }
}

/// Which commands a trip in a status offers (web `tripNextAction`, plus the controls the server already had).
public struct TripActions: Equatable, Sendable {
    /// planned -> start boarding, boarding -> depart, in progress -> complete.
    public let next: TripCommand?
    /// "Safarni to'xtatish" (`interrupt`): only while the trip runs (boarding, in progress).
    public let canPause: Bool
    /// "Safarni davom ettirish" (`resume`): only an interrupted trip.
    public let canResume: Bool
    /// planned, boarding or interrupted (a trip on the road is completed, not cancelled).
    public let canCancel: Bool

    public static func of(_ status: TripStatus) -> TripActions {
        switch status {
        case .planned: TripActions(next: .startBoarding, canPause: false, canResume: false, canCancel: true)
        case .boarding: TripActions(next: .depart, canPause: true, canResume: false, canCancel: true)
        case .inProgress: TripActions(next: .complete, canPause: true, canResume: false, canCancel: false)
        case .interrupted: TripActions(next: nil, canPause: false, canResume: true, canCancel: true)
        default: TripActions(next: nil, canPause: false, canResume: false, canCancel: false)
        }
    }
}

public enum TripStatusStyle {
    /// planned / boarding ok-green, on the road blue, finished grey, interrupted warn (the state is also in the words).
    public static func tone(_ status: TripStatus) -> Tone {
        switch status {
        case .planned, .boarding: .ok
        case .inProgress: .blue
        case .interrupted: .warn
        default: .gray
        }
    }

    public static func key(_ status: TripStatus) -> String { "tripStatus.\(status.rawValue)" }

    /// Still the driver's business (listed first): everything that is not finished.
    public static func isActive(_ status: TripStatus) -> Bool {
        switch status {
        case .planned, .boarding, .inProgress, .interrupted: true
        default: false
        }
    }
}

public enum TripList {
    /// Active trips first, soonest first; then the history, newest first. Ties by id so the order never jumps.
    public static func sections(_ trips: [TripDTO]) -> (active: [TripDTO], history: [TripDTO]) {
        let start = { (trip: TripDTO) in ServerTime.parse(trip.plannedStartAt) ?? .distantPast }
        let active = trips.filter { TripStatusStyle.isActive($0.status) }
            .sorted { start($0) != start($1) ? start($0) < start($1) : $0.id < $1.id }
        let history = trips.filter { !TripStatusStyle.isActive($0.status) }
            .sorted { start($0) != start($1) ? start($0) > start($1) : $0.id < $1.id }
        return (active, history)
    }

    /// The trips an offer can be made from: planned, and still taking bookings (cutoff in the future).
    public static func offerable(_ trips: [TripDTO], now: Date = Date()) -> [TripDTO] {
        trips.filter { trip in
            trip.status == .planned && (ServerTime.parse(trip.bookingCutoffAt).map { $0 > now } ?? false)
        }
        .sorted { (ServerTime.parse($0.plannedStartAt) ?? .distantPast) < (ServerTime.parse($1.plannedStartAt) ?? .distantPast) }
    }
}

/// Why the server refused a trip command, in the terms the screen acts on.
public enum TripRefusal: Equatable, Sendable {
    /// `INVALID_STATE_TRANSITION {reason: boarding_window_not_open, opens_at}`: "Chiqish oynasi 09:30 da ochiladi."
    case windowOpensAt(Date)
    /// `TRIP_HAS_UNRESOLVED_BOOKINGS`: a sentence, then the trip is read again.
    case unresolvedBookings
    /// `VERSION_CONFLICT`: someone (an operator, another device) changed the trip; read it again.
    case versionConflict
    /// Anything else: the shared `error.<CODE>` sentence.
    case other

    public static func of(_ error: Error) -> TripRefusal {
        guard let error = error as? APIError else { return .other }
        switch error.code {
        case "INVALID_STATE_TRANSITION":
            if error.details?["reason"] == .string("boarding_window_not_open"),
               case .string(let text)? = error.details?["opens_at"], let date = ServerTime.parse(text) {
                return .windowOpensAt(date)
            }
            return .other
        case "TRIP_HAS_UNRESOLVED_BOOKINGS": return .unresolvedBookings
        case "VERSION_CONFLICT": return .versionConflict
        default: return .other
        }
    }

    /// After this refusal the screen reads the trip again (its state moved on under the driver).
    public var refreshes: Bool { self == .unresolvedBookings || self == .versionConflict }
}

// MARK: - Planning a trip

/// "Yo'nalish qo'shish" as typed. Numbers stay text until sent (the fields are free typing).
public struct TripPlanForm: Equatable, Sendable {
    public var vehicleId: String?
    public var corridorId: String?
    public var routeId: String?
    public var start: Date?
    public var seats = ""
    public var cargoKg = ""
    public var cargoLitres = ""

    public init(vehicleId: String? = nil, corridorId: String? = nil, routeId: String? = nil, start: Date? = nil, seats: String = "",
                cargoKg: String = "", cargoLitres: String = "") {
        self.vehicleId = vehicleId
        self.corridorId = corridorId
        self.routeId = routeId
        self.start = start
        self.seats = seats
        self.cargoKg = cargoKg
        self.cargoLitres = cargoLitres
    }
}

public enum TripPlanField: String, Hashable, Sendable, CaseIterable {
    case vehicle, corridor, route, start, seats, cargoKg, cargoLitres
}

public enum TripPlanProblem: Hashable, Sendable {
    case required
    /// The departure must be in the future.
    case past
    /// More than the vehicle carries (`vehicle_limit` in the vehicle's units: seats, kg or litres).
    case overLimit(Int)
    /// Not a whole number (0 is allowed: no parcels / no passengers).
    case notNumber
    /// Seats, kg and litres are all 0: the trip would offer nothing.
    case nothingOffered
}

public enum TripPlan {
    /// Defaults from the chosen vehicle: all its seats, its cargo limits in kg and litres (0 when it has none).
    public static func prefill(_ vehicle: VehicleDTO) -> (seats: String, cargoKg: String, cargoLitres: String) {
        (String(vehicle.seatCapacity), String((vehicle.cargoMaxWeightG ?? 0) / 1000), String((vehicle.cargoMaxVolumeMl ?? 0) / 1000))
    }

    /// A whole number >= 0, or nil.
    public static func count(_ text: String) -> Int? {
        let trimmed = text.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty, trimmed.allSatisfy({ $0.isASCII && $0.isNumber }) else { return nil }
        return Int(trimmed)
    }

    /// What stops "Saqlash": nothing chosen, a past departure, numbers over the vehicle's limits, an empty offer.
    public static func problems(_ form: TripPlanForm, vehicle: VehicleDTO?, now: Date = Date()) -> [TripPlanField: TripPlanProblem] {
        var out: [TripPlanField: TripPlanProblem] = [:]
        if form.vehicleId == nil || vehicle == nil { out[.vehicle] = .required }
        if form.corridorId == nil { out[.corridor] = .required }
        if form.routeId == nil { out[.route] = .required }
        if let start = form.start {
            if start <= now { out[.start] = .past }
        } else {
            out[.start] = .required
        }
        let seats = count(form.seats), kg = count(form.cargoKg), litres = count(form.cargoLitres)
        if seats == nil { out[.seats] = .notNumber }
        if kg == nil { out[.cargoKg] = .notNumber }
        if litres == nil { out[.cargoLitres] = .notNumber }
        if let vehicle {
            if let seats, seats > vehicle.seatCapacity { out[.seats] = .overLimit(vehicle.seatCapacity) }
            let maxKg = (vehicle.cargoMaxWeightG ?? 0) / 1000, maxLitres = (vehicle.cargoMaxVolumeMl ?? 0) / 1000
            if let kg, kg > maxKg { out[.cargoKg] = .overLimit(maxKg) }
            if let litres, litres > maxLitres { out[.cargoLitres] = .overLimit(maxLitres) }
        }
        if seats == 0 && kg == 0 && litres == 0 { out[.seats] = .nothingOffered }
        return out
    }

    /// The `POST /trips` body (web ConnectedApp.tsx:6362): the route's own stops with `seq` = index + 1 and the planned
    /// arrival = start + cumulative duration; end = start + the route's duration; dwell 5, detour 15 min / 5 km, pickup
    /// wait 10, cutoff omitted (= start), kg and litres as grams and millilitres. nil while anything is missing.
    public static func body(_ form: TripPlanForm, route: RouteVersionDTO) -> TripCreate? {
        guard let vehicleId = form.vehicleId, let start = form.start, route.id == form.routeId,
              let seats = count(form.seats), let kg = count(form.cargoKg), let litres = count(form.cargoLitres) else { return nil }
        let stops = route.stops.sorted { $0.seq < $1.seq }.enumerated().map { index, stop in
            TripStopInput(dwellMinutes: 5, plannedArrivalAt: DepartureWindow.iso(start.addingTimeInterval(TimeInterval(stop.cumulativeDurationS))),
                          seq: index + 1, stopId: stop.stopId)
        }
        return TripCreate(cargoCapacityVolumeMl: litres * 1000, cargoCapacityWeightG: kg * 1000, maxDetourM: 5000, maxDetourMinutes: 15,
                          pickupWaitMinutes: 10, plannedEndAt: DepartureWindow.iso(start.addingTimeInterval(TimeInterval(route.durationS))),
                          plannedStartAt: DepartureWindow.iso(start), routeVersionId: route.id, seatCapacity: seats, stops: stops,
                          vehicleId: vehicleId)
    }

    /// The corridor's routes that pass a stop (the stop-name filter when a corridor has more than one route).
    public static func routesThrough(_ routes: [RouteVersionDTO], stopId: String?) -> [RouteVersionDTO] {
        guard let stopId else { return routes }
        return routes.filter { $0.stops.contains { $0.stopId == stopId } }
    }

    /// `{stops} bekat · {km} km · {hours} soat` (rounded like the web).
    public static func figures(_ route: RouteVersionDTO) -> (stops: Int, km: Int, hours: Int) {
        (route.stops.count, Int((Double(route.distanceM) / 1000).rounded()), Int((Double(route.durationS) / 3600).rounded()))
    }

    /// `VEHICLE_NOT_ELIGIBLE {field, requested, vehicle_limit}` -> the form field to mark and its limit in the form's
    /// units (seats, kg, litres); nil when the refusal is about the vehicle itself (not approved).
    public static func refusedField(_ error: Error) -> (field: TripPlanField, limit: Int)? {
        guard let error = error as? APIError, error.code == "VEHICLE_NOT_ELIGIBLE",
              case .string(let field)? = error.details?["field"] else { return nil }
        let limit: Int = if case .number(let value)? = error.details?["vehicle_limit"] { Int(value) } else { 0 }
        switch field {
        case "seat_capacity": return (.seats, limit)
        case "cargo_capacity_weight_g": return (.cargoKg, limit / 1000)
        case "cargo_capacity_volume_ml": return (.cargoLitres, limit / 1000)
        default: return nil
        }
    }
}

// MARK: - Feed query

/// The date chips: today, tomorrow, 3 days, 14 days (the default), as Tashkent calendar days.
public enum FeedDateChip: String, CaseIterable, Codable, Hashable, Sendable {
    case today, tomorrow, three, fourteen

    public var labelKey: String {
        switch self {
        case .today: "driver.feed.dateToday"
        case .tomorrow: "driver.feed.dateTomorrow"
        case .three: "driver.feed.date3"
        case .fourteen: "driver.feed.date14"
        }
    }

    /// `[from, to)` on Tashkent day boundaries: today = today 00:00 - tomorrow 00:00; tomorrow = the next day; 3 and 14
    /// days start today.
    public func range(now: Date = Date()) -> (from: Date, to: Date) {
        let calendar = DepartureWindow.calendar
        let today = calendar.startOfDay(for: now)
        let day = { (offset: Int) in calendar.date(byAdding: .day, value: offset, to: today)! }
        switch self {
        case .today: return (today, day(1))
        case .tomorrow: return (day(1), day(2))
        case .three: return (today, day(3))
        case .fourteen: return (today, day(14))
        }
    }
}

/// One end of the feed's route: a region and, where the region asks for one (or the driver picked one), a district.
public struct FeedEnd: Codable, Hashable, Sendable {
    public var regionId: String
    public var regionName: String
    public var regionNameRu: String?
    public var districtId: String?
    public var districtName: String?
    public var districtNameRu: String?

    public init(regionId: String, regionName: String, regionNameRu: String? = nil, districtId: String? = nil, districtName: String? = nil,
                districtNameRu: String? = nil) {
        self.regionId = regionId
        self.regionName = regionName
        self.regionNameRu = regionNameRu
        self.districtId = districtId
        self.districtName = districtName
        self.districtNameRu = districtNameRu
    }

    /// Exactly one id per side: the district when there is one, else the region.
    public var queryIds: (regionId: String?, districtId: String?) {
        districtId != nil ? (nil, districtId) : (regionId, nil)
    }
}

/// The feed's filter, remembered per driver.
public struct FeedFilter: Codable, Equatable, Sendable {
    public var passenger = false
    public var origin: FeedEnd?
    public var destination: FeedEnd?
    public var chip: FeedDateChip = .fourteen

    public init(passenger: Bool = false, origin: FeedEnd? = nil, destination: FeedEnd? = nil, chip: FeedDateChip = .fourteen) {
        self.passenger = passenger
        self.origin = origin
        self.destination = destination
        self.chip = chip
    }

    public var hasRoute: Bool { origin != nil && destination != nil }
}

/// The `GET /feed` question. Always `side=requests` (Q138), `include_alternatives=true` (Q97), `sort=recommended`.
public struct FeedQuery: Equatable, Sendable {
    public let serviceType: ServiceType
    public let dateFrom: String
    public let dateTo: String
    public let originRegionId: String?
    public let originDistrictId: String?
    public let destinationRegionId: String?
    public let destinationDistrictId: String?

    /// nil until both ends are chosen. `passengerAllowed` = the `passenger_enabled` flag (otherwise parcel only).
    public static func make(_ filter: FeedFilter, passengerAllowed: Bool, now: Date = Date()) -> FeedQuery? {
        guard let origin = filter.origin, let destination = filter.destination else { return nil }
        let range = filter.chip.range(now: now)
        return FeedQuery(serviceType: filter.passenger && passengerAllowed ? .passenger : .parcel,
                         dateFrom: DepartureWindow.iso(range.from), dateTo: DepartureWindow.iso(range.to),
                         originRegionId: origin.queryIds.regionId, originDistrictId: origin.queryIds.districtId,
                         destinationRegionId: destination.queryIds.regionId, destinationDistrictId: destination.queryIds.districtId)
    }
}

// MARK: - Feed groups (port of mobile-app/src/app/feedGroups.ts)

public enum FeedGroups {
    /// Primary (what was asked) and alternatives (close, shown under their own heading - never mixed in, Q97).
    /// Anything the server did not call an alternative is primary.
    public static func split(_ items: [FeedItemDTO]) -> (primary: [FeedItemDTO], alternative: [FeedItemDTO]) {
        (items.filter { $0.group != .alternative }, items.filter { $0.group == .alternative })
    }

    /// Why an alternative is one: `time_differs` wins (it decides whether the trip works at all), then
    /// `nearby_stop`; nil when the server gave nothing we can say.
    public static func alternativeReason(_ reasons: [MatchReason]) -> MatchReason? {
        if reasons.contains(.timeDiffers) { return .timeDiffers }
        if reasons.contains(.nearbyStop) { return .nearbyStop }
        return nil
    }

    /// Appends a further page, dropping listings already shown (a cursor page can overlap after a refresh).
    public static func appending(_ page: [FeedItemDTO], to current: [FeedItemDTO]) -> [FeedItemDTO] {
        let seen = Set(current.map(\.listing.id))
        return current + page.filter { !seen.contains($0.listing.id) }
    }
}

// MARK: - Saved routes

public enum SavedRoute {
    public static let limit = 10

    /// The body for "Shu yo'nalishni saqlash": the feed's ends, requests side, the next 14 days, one unit, notify on.
    public static func body(_ filter: FeedFilter, passengerAllowed: Bool, now: Date = Date()) -> SavedSearchCreate? {
        guard let origin = filter.origin, let destination = filter.destination else { return nil }
        return SavedSearchCreate(destinationDistrictId: destination.queryIds.districtId, destinationRegionId: destination.queryIds.regionId,
                                 notify: true, originDistrictId: origin.queryIds.districtId, originRegionId: origin.queryIds.regionId,
                                 quantity: 1, serviceType: filter.passenger && passengerAllowed ? .passenger : .parcel, side: .requests,
                                 timeWindowEnd: DepartureWindow.iso(now.addingTimeInterval(14 * 86_400)), timeWindowStart: DepartureWindow.iso(now))
    }
}

// MARK: - The offer

public enum PickupWindow {
    /// When this trip can be at the request's pickup (web `proposalPickupWindow`): the trip's arrival at the origin stop
    /// (ETA when known) +-30 min, clipped to the request's window; nil when the trip does not pass that stop or the two
    /// do not meet. A point-ended request has no stop to anchor on: the client's own window (the server checks it).
    public static func of(trip: TripDTO, listing: ListingPublicDTO) -> (start: Date, end: Date)? {
        guard let askedFrom = ServerTime.parse(listing.departureWindowStart), let askedTo = ServerTime.parse(listing.departureWindowEnd) else {
            return nil
        }
        guard let originStop = listing.originStop else { return (askedFrom, askedTo) }
        guard let at = trip.stops.first(where: { $0.stop.id == originStop.id }),
              let arrival = ServerTime.parse(at.etaArrivalAt ?? at.plannedArrivalAt) else { return nil }
        let start = max(askedFrom, arrival.addingTimeInterval(-30 * 60))
        let end = min(askedTo, arrival.addingTimeInterval(30 * 60))
        return end > start ? (start, end) : nil
    }

    /// The trip to preselect: the first offerable trip whose window meets the request (a stop-ended request: its pickup
    /// window exists; a point-ended one: the trip's run overlaps the request's window); else nil (the driver chooses).
    public static func preselect(_ trips: [TripDTO], listing: ListingPublicDTO) -> TripDTO? {
        guard let askedFrom = ServerTime.parse(listing.departureWindowStart), let askedTo = ServerTime.parse(listing.departureWindowEnd) else {
            return nil
        }
        return trips.first { trip in
            if listing.originStop != nil { return of(trip: trip, listing: listing) != nil }
            guard let start = ServerTime.parse(trip.plannedStartAt), let end = ServerTime.parse(trip.plannedEndAt) else { return false }
            return start <= askedTo && end >= askedFrom
        }
    }
}

public enum OfferBody {
    /// `POST /listings/{id}/proposals`: the trip, the pickup window, the listing's own quantity and price basis, the
    /// price; pickup/dropoff stops only for a stop-ended request (both or neither); a message only when typed.
    public static func make(listing: ListingPublicDTO, tripId: String, window: (start: Date, end: Date), unitPriceMinor: Int,
                            message: String? = nil) -> ProposalCreate {
        let stops = listing.originStop.flatMap { origin in listing.destinationStop.map { (origin.id, $0.id) } }
        let text = message?.trimmingCharacters(in: .whitespacesAndNewlines)
        return ProposalCreate(dropoffStopId: stops?.1, message: text?.isEmpty == false ? text : nil, pickupStopId: stops?.0,
                              pickupWindowEnd: DepartureWindow.iso(window.end), pickupWindowStart: DepartureWindow.iso(window.start),
                              priceBasis: listing.priceBasis, quantity: listing.serviceType == .parcel ? 1 : max(listing.quantity, 1),
                              tripId: tripId, unitPriceMinor: unitPriceMinor)
    }

    /// The total the server would put on the offer (`per_seat` x quantity, `total` as is) - the commission quote's base.
    public static func totalMinor(listing: ListingPublicDTO, unitPriceMinor: Int) -> Int {
        guard unitPriceMinor > 0 else { return 0 }
        return listing.priceBasis == .perSeat ? unitPriceMinor * max(listing.quantity, 1) : unitPriceMinor
    }

    /// Basis points as a percent for a sentence: 1500 -> "15", 750 -> "7.5".
    public static func percent(bps: Int) -> String {
        bps % 100 == 0 ? String(bps / 100) : String(format: "%.2f", Double(bps) / 100)
            .replacingOccurrences(of: #"\.?0+$"#, with: "", options: .regularExpression)
    }
}

/// The anonymous rival board (Q40/Q95): how many, the cheapest, and the driver's own current offer.
public struct RivalBoard: Equatable, Sendable {
    public let count: Int
    public let cheapestMinor: Int?
    public let mine: ListingOfferDTO?
    /// Everyone else's offers, cheapest first (ties by label so the rows never jump).
    public let rivals: [ListingOfferDTO]

    public static func of(_ offers: [ListingOfferDTO]) -> RivalBoard {
        RivalBoard(count: offers.count, cheapestMinor: offers.map(\.totalMinor).min(), mine: offers.first(where: \.isMine),
                   rivals: offers.filter { !$0.isMine }.sorted { ($0.totalMinor, $0.label) < ($1.totalMinor, $1.label) })
    }
}

// MARK: - The negotiation, from the driver's side

/// What the driver may do with one thread right now (web `auction.ts:49` with mySide = driver), closed by the clock
/// as soon as `expires_at` passes.
public struct DriverNegotiation: Equatable, Sendable {
    public let open: Bool
    /// The client spoke last (a counter): the answer is the driver's.
    public let driversTurn: Bool
    public let canAccept: Bool
    public let canReject: Bool
    /// Only while `price_revisions_left.driver` > 0.
    public let canCounter: Bool
    /// The driver's own version is pending: it can be taken back.
    public let canWithdraw: Bool
    public let revisionsLeft: Int
    public let expiredByClock: Bool

    static let closed = DriverNegotiation(open: false, driversTurn: false, canAccept: false, canReject: false, canCounter: false,
                                          canWithdraw: false, revisionsLeft: 0, expiredByClock: false)

    public static func of(_ thread: ProposalThreadDTO, now: Date = Date()) -> DriverNegotiation {
        guard let version = thread.currentVersion, thread.state == "open", version.status == .active else { return .closed }
        if let expires = ServerTime.parse(version.expiresAt), now >= expires {
            return DriverNegotiation(open: false, driversTurn: false, canAccept: false, canReject: false, canCounter: false,
                                     canWithdraw: false, revisionsLeft: 0, expiredByClock: true)
        }
        let driversTurn = version.authorSide != .driver
        let left = version.priceRevisionsLeft.driver
        return DriverNegotiation(open: true, driversTurn: driversTurn, canAccept: driversTurn, canReject: driversTurn,
                                 canCounter: driversTurn && left > 0, canWithdraw: !driversTurn, revisionsLeft: left, expiredByClock: false)
    }
}

/// The "Takliflarim" filter tabs (`GET /me/proposals?state=`).
public enum ProposalTab: String, CaseIterable, Hashable, Sendable {
    case open, accepted, closed

    public var labelKey: String {
        switch self {
        case .open: "publicShare.open"
        case .accepted: "client.amendment.statusAccepted"
        case .closed: "client.amendment.statusClosed"
        }
    }
}

/// The status line under a thread: the latest version's story, in a tone.
public enum ProposalStatusLine {
    public static func of(_ thread: ProposalThreadDTO, now: Date = Date()) -> (key: String, tone: Tone?) {
        if thread.state == "accepted" || thread.bookingId != nil { return ("client.amendment.statusAccepted", .ok) }
        let actions = DriverNegotiation.of(thread, now: now)
        if actions.expiredByClock { return ("proposalStatus.expired", nil) }
        if actions.open { return actions.driversTurn ? ("negotiation.clientCountered", .warn) : ("negotiation.waitingForAnswer", nil) }
        return ("proposalStatus.\(thread.currentVersion?.status.rawValue ?? "expired")", nil)
    }
}

/// The accept's `expected_listing_terms_version` (Q54) is `ProposalThreadDTO.listing_terms_version` - the listing's
/// current terms version as the thread reports it. Should the listing change between the read and the accept, the
/// server answers `PROPOSAL_CHANGED {current_listing_terms_version}`: the thread is read again (bringing the new
/// version) and the driver confirms once more.
public enum ListingTerms {
    /// `PROPOSAL_CHANGED {reason: listing_terms_version_mismatch, current_listing_terms_version}` -> that version.
    public static func current(from error: Error) -> Int? {
        guard let error = error as? APIError, error.code == "PROPOSAL_CHANGED",
              case .number(let value)? = error.details?["current_listing_terms_version"] else { return nil }
        return Int(value)
    }
}

// MARK: - Errors -> sentences

/// The offer and negotiation refusals the driver gets their own sentence for; the rest use `error.<CODE>`.
public enum MarketErrorText {
    public enum Sentence: Equatable, Sendable {
        case key(String, [String: String])
        case generic
    }

    /// `INVALID_STATE_TRANSITION {reason: open_thread_exists, thread_id}`: the driver already has an open offer on this
    /// request - that thread opens instead.
    public static func openThread(_ error: Error) -> String? {
        guard let error = error as? APIError, error.code == "INVALID_STATE_TRANSITION",
              error.details?["reason"] == .string("open_thread_exists"), case .string(let id)? = error.details?["thread_id"] else { return nil }
        return id
    }

    public static func sentence(_ error: Error) -> Sentence {
        guard let error = error as? APIError else { return .generic }
        switch error.code {
        case "TIME_WINDOW_CONFLICT": return .key("driverBid.tripWindowMismatch", [:])
        case "SAVED_SEARCH_LIMIT_REACHED": return .key("error.SAVED_SEARCH_LIMIT_REACHED", [:])
        case "PROPOSAL_CHANGED" where error.details?["reason"] == .string("listing_terms_version_mismatch")
            || error.details?["reason"] == .string("listing_terms_changed"):
            return .key("client.listingBids.termsChanged", [:])
        case "PROPOSAL_CHANGED" where error.details?["reason"] == .string("demand_already_booked"):
            return .key("client.listingBids.alreadyBooked", [:])
        default: return .generic
        }
    }
}
