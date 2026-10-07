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
    /// DESIGN07 2.2: planned blue, boarding / on the road green, interrupted warn (an incident, not a pause), completed
    /// grey, cancelled red (the state is also in the words).
    public static func tone(_ status: TripStatus) -> Tone {
        switch status {
        case .planned: .blue
        case .boarding, .inProgress: .ok
        case .interrupted: .warn
        case .cancelled: .err
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

    /// The `POST /trips` body (ADR-0028, Q160): the confirmed road by `route_version_id` - the whole road, so no
    /// `route_start_m`/`route_end_m` and never `stops`; end = start + the route's duration; detour 15 min / 5 km, pickup
    /// wait 10, cutoff omitted (= start), kg and litres as grams and millilitres. nil while anything is missing.
    public static func body(_ form: TripPlanForm, route: RouteVersionDTO) -> TripCreate? {
        guard let vehicleId = form.vehicleId, let start = form.start, route.id == form.routeId,
              let seats = count(form.seats), let kg = count(form.cargoKg), let litres = count(form.cargoLitres) else { return nil }
        return TripCreate(cargoCapacityVolumeMl: litres * 1000, cargoCapacityWeightG: kg * 1000, maxDetourM: 5000, maxDetourMinutes: 15,
                          pickupWaitMinutes: 10, plannedEndAt: DepartureWindow.iso(start.addingTimeInterval(TimeInterval(route.durationS))),
                          plannedStartAt: DepartureWindow.iso(start), routeVersionId: route.id, seatCapacity: seats,
                          vehicleId: vehicleId)
    }

    /// `{km} km · {hours} soat` (rounded like the web).
    public static func figures(_ route: RouteVersionDTO) -> (km: Int, hours: Int) {
        (Int((Double(route.distanceM) / 1000).rounded()), Int((Double(route.durationS) / 3600).rounded()))
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

    /// Why an alternative is one: `time_differs` (ADR-0028 removed the stop-based `nearby_stop`); nil when the
    /// server gave nothing we can say.
    public static func alternativeReason(_ reasons: [MatchReason]) -> MatchReason? {
        reasons.contains(.timeDiffers) ? .timeDiffers : nil
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
    /// The pickup window the offer carries (web `proposalPickupWindow`, ADR-0028): a request is two marked places, so
    /// there is nothing on the trip to anchor a narrower window on - the client's own window; the server derives the
    /// real pickup ETA from the place's projection onto the trip's road and refuses a window the trip cannot keep.
    public static func of(trip: TripDTO, listing: ListingPublicDTO) -> (start: Date, end: Date)? {
        guard let askedFrom = ServerTime.parse(listing.departureWindowStart), let askedTo = ServerTime.parse(listing.departureWindowEnd) else {
            return nil
        }
        return (askedFrom, askedTo)
    }

    /// The trip to preselect: the first offerable trip whose run overlaps the request's window; else nil (the driver
    /// chooses).
    public static func preselect(_ trips: [TripDTO], listing: ListingPublicDTO) -> TripDTO? {
        guard let askedFrom = ServerTime.parse(listing.departureWindowStart), let askedTo = ServerTime.parse(listing.departureWindowEnd) else {
            return nil
        }
        return trips.first { trip in
            guard let start = ServerTime.parse(trip.plannedStartAt), let end = ServerTime.parse(trip.plannedEndAt) else { return false }
            return start <= askedTo && end >= askedFrom
        }
    }
}

public enum OfferBody {
    /// `POST /listings/{id}/proposals`: the trip, the pickup window, the listing's own quantity and price basis, the
    /// price; never a stop id (ADR-0028: the places come from the listing); a message only when typed.
    public static func make(listing: ListingPublicDTO, tripId: String, window: (start: Date, end: Date), unitPriceMinor: Int,
                            message: String? = nil) -> ProposalCreate {
        let text = message?.trimmingCharacters(in: .whitespacesAndNewlines)
        return ProposalCreate(message: text?.isEmpty == false ? text : nil,
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
        // Taksi: the trip has fewer free seats than the request's people - another trip, or a new one.
        case "CAPACITY_UNAVAILABLE": return .key("driverBid.capacityUnavailable", [:])
        // The offer's seats must be the request's own count (the app sends it; a changed request says so).
        case "QUANTITY_MISMATCH": return .key("error.QUANTITY_MISMATCH", [:])
        default: return .generic
        }
    }
}

// MARK: - DESIGN07 (BOSQICH 07: trips, feed, saved routes, offers, negotiation)

/// One live trip at a time (DESIGN07 2.6): the phone runs one GPS session, so boarding a second trip waits until the
/// running one (boarding, on the road or interrupted) is finished.
public enum LiveTrip {
    public static func isLive(_ status: TripStatus) -> Bool {
        switch status {
        case .boarding, .inProgress, .interrupted: true
        default: false
        }
    }

    /// `start_boarding` on `trip` while another trip is live.
    public static func blocksStart(_ trip: TripDTO, among trips: [TripDTO]) -> Bool {
        trips.contains { $0.id != trip.id && isLive($0.status) }
    }

    /// The banner after a command the server took (2.5 / 4.7): departure says the clients were told (in-app, Q82),
    /// cancel says the open offers were closed (the server expires them); the rest the shared "Safar holati yangilandi".
    public static func bannerKey(_ command: TripCommand) -> String {
        switch command {
        case .depart: "driver.trip.departed"
        case .cancel: "driver.trip.cancelled"
        default: "driverRoutes.tripStatusUpdated"
        }
    }
}

/// ADR-0028: a road position as whole kilometres from the start of the trip's stretch (web `kmAlong`).
public enum TripStretch {
    public static func km(_ positionM: Int, startM: Int) -> Int { max(0, Int((Double(positionM - startM) / 1000).rounded())) }
}

/// The places' dots from the trip status (DESIGN07 4.2; real per-stop passage is not on the DTO): completed -> all
/// done; on the road -> first done, second current; boarding -> first current; otherwise all ahead.
public enum TripStopDot: Equatable, Sendable {
    case done, current, ahead

    public static func of(index: Int, status: TripStatus) -> TripStopDot {
        switch status {
        case .completed: .done
        case .inProgress: index == 0 ? .done : (index == 1 ? .current : .ahead)
        case .boarding: index == 0 ? .current : .ahead
        default: .ahead
        }
    }
}

extension TripPlan {
    /// The departure's sentence under the field (DESIGN07 3.4): empty -> "Jo'nash vaqtini kiriting.", past ->
    /// "Jo'nash vaqti kelajakda bo'lishi kerak."; nil when it is fine.
    public static func departureKey(_ problem: TripPlanProblem?) -> String? {
        switch problem {
        case .required: "driver.trip.departureRequired"
        case .past: "driver.trip.departurePast"
        default: nil
        }
    }
}

/// The three home tiles (DESIGN07 1.2), counted on the client (there is no stats endpoint): trips not finished,
/// offers still open (waiting or countered, not run out), bookings not terminal. nil = not known (shown as "—").
public struct DriverHomeStats: Equatable, Sendable {
    public let trips: Int?
    public let offers: Int?
    public let bookings: Int?

    public static func of(trips: [TripDTO]?, openProposals: [ProposalThreadDTO]?, bookingStatuses: [String]?,
                          now: Date = Date()) -> DriverHomeStats {
        DriverHomeStats(trips: trips.map { $0.filter { TripStatusStyle.isActive($0.status) }.count },
                        offers: openProposals.map { $0.filter { DriverNegotiation.of($0, now: now).open }.count },
                        bookings: bookingStatuses.map { $0.filter(DriverBookingFilter.active.includes).count })
    }

    public static func text(_ count: Int?) -> String { count.map(String.init) ?? "—" }
}

/// "You already offered" on a feed card (DESIGN07 5.7), joined on the client from `/me/proposals` by listing.
public enum FeedOfferMark: Equatable, Sendable {
    case none
    /// "Siz taklif yubordingiz: {price}" (the driver's own latest price) + "Taklifni ko'rish".
    case offered(threadId: String, totalMinor: Int)
    /// The client answered with a counter and the driver's own price is not known here: "Mijoz qarshi taklif yubordi".
    case countered(threadId: String)
    /// "Mijoz qabul qildi" + "Taklifni ko'rish".
    case accepted(threadId: String)

    /// `versions`: a thread's known history (the list has none) - the driver's price under the client's counter.
    public static func of(listingId: String, open: [ProposalThreadDTO]?, accepted: [ProposalThreadDTO]?,
                          versions: (String) -> [ProposalVersionDTO]? = { _ in nil }, now: Date = Date()) -> FeedOfferMark {
        if let thread = accepted?.first(where: { $0.listingId == listingId && ($0.state == "accepted" || $0.bookingId != nil) }) {
            return .accepted(threadId: thread.id)
        }
        guard let thread = open?.first(where: { $0.listingId == listingId && $0.state == "open" }), let version = thread.currentVersion,
              !DriverNegotiation.of(thread, now: now).expiredByClock else { return .none }
        if version.authorSide == .driver { return .offered(threadId: thread.id, totalMinor: version.totalMinor) }
        let mine = (versions(thread.id) ?? thread.versions ?? [])
            .filter { $0.authorSide == .driver && $0.revision < version.revision }.max { $0.revision < $1.revision }
        return mine.map { .offered(threadId: thread.id, totalMinor: $0.totalMinor) } ?? .countered(threadId: thread.id)
    }

    public var threadId: String? {
        switch self {
        case .none: nil
        case .offered(let id, _), .countered(let id), .accepted(let id): id
        }
    }
}

/// A negotiation card's badge and line (DESIGN07 8.1 / 8.2).
public enum ProposalBadge: Equatable, Sendable {
    case waiting, countered, myCounter, accepted, rejected, withdrawn, expired

    public static func of(_ thread: ProposalThreadDTO, now: Date = Date()) -> ProposalBadge {
        if thread.state == "accepted" || thread.bookingId != nil { return .accepted }
        let actions = DriverNegotiation.of(thread, now: now)
        if actions.expiredByClock { return .expired }
        if actions.open, let version = thread.currentVersion {
            if actions.driversTurn { return .countered }
            // The driver's own version after the first one: a counter to the client's counter.
            return version.authorSide == .driver && version.revision > 1 ? .myCounter : .waiting
        }
        switch thread.currentVersion?.status {
        case .rejected?: return .rejected
        case .withdrawn?: return .withdrawn
        case .accepted?: return .accepted
        default: return .expired
        }
    }

    public var key: String {
        switch self {
        case .waiting: "status.proposed"
        case .countered: "driver.offer.badgeCountered"
        case .myCounter: "driver.offer.badgeMyCounter"
        case .accepted: "client.booking.amendStatusAccepted"
        case .rejected: "status.rejected"
        case .withdrawn: "status.withdrawn"
        case .expired: "status.expired"
        }
    }

    public var tone: Tone {
        switch self {
        case .waiting, .withdrawn, .expired: .gray
        case .countered: .warn
        case .myCounter: .blue
        case .accepted: .ok
        case .rejected: .err
        }
    }

    /// The client countered: the card is outlined (the driver's turn).
    public var outlined: Bool { self == .countered }
    /// Withdrawn and run-out offers are faded.
    public var faded: Bool { self == .withdrawn || self == .expired }
}

/// The status sentence under a negotiation card.
public enum ProposalLine: Equatable, Sendable {
    case key(String)
    /// "Mijoz qarshi taklif yubordi: {price} (siz {mine} taklif qilgansiz)".
    case clientCounter(priceMinor: Int, mineMinor: Int)
    /// "Qarshi taklifingiz ({price}) yuborildi — mijoz javobi kutilmoqda."
    case myCounter(priceMinor: Int)

    /// `versions`: the thread's history when known (the list DTO has none; then the countered line has no prices).
    public static func of(_ thread: ProposalThreadDTO, versions: [ProposalVersionDTO]? = nil, now: Date = Date()) -> ProposalLine? {
        let current = thread.currentVersion
        switch ProposalBadge.of(thread, now: now) {
        case .countered:
            guard let current else { return .key("negotiation.clientCountered") }
            let history = versions ?? thread.versions ?? []
            let mine = history.filter { $0.authorSide == .driver && $0.revision < current.revision }.max { $0.revision < $1.revision }
            guard let mine else { return .key("negotiation.clientCountered") }
            return .clientCounter(priceMinor: current.totalMinor, mineMinor: mine.totalMinor)
        case .waiting: return .key("negotiation.waitingForAnswer")
        case .myCounter: return current.map { .myCounter(priceMinor: $0.totalMinor) } ?? .key("negotiation.waitingForAnswer")
        case .accepted: return .key("driver.offer.acceptedLine")
        case .rejected, .withdrawn, .expired: return nil
        }
    }
}

/// The counter's new price (DESIGN07 8.5): required, and different from the client's price (the same price would
/// only spend a revision).
public enum DriverCounterCheck {
    public static func problemKey(priceMinor: Int, clientUnitMinor: Int) -> String? {
        if priceMinor <= 0 { return "driver.offer.priceRequired" }
        if priceMinor == clientUnitMinor { return "driver.offer.counterSame" }
        return nil
    }
}

/// After the driver accepts the client's price (Q100): the booking's chat opens, straight away.
public enum AcceptNext: Equatable, Sendable {
    case bookingChat(String)
    /// No booking id came back (a refusal): the thread stays and says why.
    case stay

    public static func after(bookingId: String?) -> AcceptNext {
        guard let bookingId, !bookingId.isEmpty else { return .stay }
        return .bookingChat(bookingId)
    }
}

/// "Shu yo'nalishni saqlash" (DESIGN07 6.2 / 6.3): no route yet, already saved (grey "Allaqachon saqlangan"), the
/// limit reached, or free to save.
public enum SavedRouteState: Equatable, Sendable {
    case noRoute, canSave, alreadySaved, limitReached
}

extension SavedRoute {
    /// The same ends (district, else region, each side) and the same service as one already saved.
    public static func isSaved(_ body: SavedSearchCreate, in list: [SavedSearchDTO]) -> Bool {
        list.contains { saved in
            saved.serviceType == body.serviceType && saved.side == body.side
                && (saved.originDistrictId ?? saved.originRegionId) == (body.originDistrictId ?? body.originRegionId)
                && (saved.destinationDistrictId ?? saved.destinationRegionId) == (body.destinationDistrictId ?? body.destinationRegionId)
        }
    }

    public static func state(_ filter: FeedFilter, passengerAllowed: Bool, saved: [SavedSearchDTO]?) -> SavedRouteState {
        guard let body = body(filter, passengerAllowed: passengerAllowed) else { return .noRoute }
        let list = saved ?? []
        if isSaved(body, in: list) { return .alreadySaved }
        if list.count >= limit { return .limitReached }
        return .canSave
    }

    /// "Lentada ochish" (DESIGN07 6.5): the feed filter from a saved route's ids (a district brings its region), its
    /// service, the current date chip kept. nil when an end cannot be named yet (the lists are still loading).
    public static func feedFilter(from saved: SavedSearchDTO, current: FeedFilter, regions: [RegionDTO],
                                  districts: [String: DistrictDTO]) -> FeedFilter? {
        let byId = Dictionary(regions.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        func end(_ regionId: String?, _ districtId: String?) -> FeedEnd? {
            if let districtId, let district = districts[districtId] {
                let region = byId[district.region.id]
                return FeedEnd(regionId: district.region.id, regionName: region?.nameUz ?? district.region.nameUz, regionNameRu: region?.nameRu,
                               districtId: district.id, districtName: district.nameUz, districtNameRu: district.nameRu)
            }
            if let regionId, let region = byId[regionId] {
                return FeedEnd(regionId: region.id, regionName: region.nameUz, regionNameRu: region.nameRu)
            }
            return nil
        }
        guard let origin = end(saved.originRegionId, saved.originDistrictId),
              let destination = end(saved.destinationRegionId, saved.destinationDistrictId) else { return nil }
        return FeedFilter(passenger: saved.serviceType == .passenger, origin: origin, destination: destination, chip: current.chip)
    }
}
