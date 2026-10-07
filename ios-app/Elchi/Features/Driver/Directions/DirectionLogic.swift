import Foundation

// ADR-0027 (Q150-Q158): the rules of the driver's direction screens, kept out of SwiftUI so they are testable - a port
// of the web's `mobile-app/src/app/directionFeed.ts` (same names where it helps reading both side by side).
//
// The driver names two ends only ("where from -> where to"). Trips, internal route nodes, the departure time and the
// corridor are the server's: the first offer from a direction plans the trip around the client's pickup time, later
// offers ride on it, an empty trip follows the next client, and a trip already on the road still takes pickups ahead.

// MARK: - The feed: days, groups, times

/// The feed's day chips (Safar v3 5.3): Bugun · Ertaga · 3 kun · 14 kun (DD5 takes at most 14 days). 14 kun is the
/// default on the feed and the home filter.
enum DirectionFeedDay: String, CaseIterable, Hashable, Sendable {
    case today, tomorrow, days3, days14

    var labelKey: String {
        switch self {
        case .today: "dir.day.today"
        case .tomorrow: "dir.day.tomorrow"
        case .days3: "driver.feed.date3"
        case .days14: "driver.feed.date14"
        }
    }
}

enum DirectionFeed {
    /// Tashkent is UTC+5 with no daylight saving.
    static let tashkentOffset: TimeInterval = 5 * 3600

    /// The three answers the screen draws apart; the server's order is kept inside each (it sorts by time already).
    struct Groups: Equatable {
        var fits: [DirectionRequestItemDTO]
        var fresh: [DirectionRequestItemDTO]
        var otherTime: [DirectionRequestItemDTO]

        var isEmpty: Bool { fits.isEmpty && fresh.isEmpty && otherTime.isEmpty }
    }

    static func groups(_ items: [DirectionRequestItemDTO]) -> Groups {
        Groups(fits: items.filter { $0.fit == "fits_trip" },
               fresh: items.filter { $0.fit == "no_trip" },
               otherTime: items.filter { $0.fit == "time_differs" })
    }

    /// The Tashkent calendar day(s) a chip means, as the ISO range the API accepts (`date_from`, `date_to`).
    static func range(_ day: DirectionFeedDay, now: Date = Date()) -> (from: String, to: String) {
        let nowSeconds = now.timeIntervalSince1970
        let local = nowSeconds + tashkentOffset
        let midnight = (local / 86_400).rounded(.down) * 86_400 - tashkentOffset
        let dayLength: TimeInterval = 86_400
        let start: TimeInterval = day == .tomorrow ? midnight + dayLength : nowSeconds
        let end: TimeInterval = switch day {
        case .today: midnight + dayLength
        case .tomorrow: midnight + 2 * dayLength
        // Today and the next two calendar days.
        case .days3: midnight + 3 * dayLength
        // Exactly 14 days from now: the server refuses a longer range.
        case .days14: nowSeconds + 14 * dayLength
        }
        return (iso(Date(timeIntervalSince1970: start)), iso(Date(timeIntervalSince1970: end)))
    }

    /// `2026-10-06T08:30:00.000Z` (what the web's `toISOString()` sends).
    static func iso(_ date: Date) -> String { isoFormatter.string(from: date) }

    nonisolated(unsafe) private static let isoFormatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        formatter.timeZone = TimeZone(identifier: "UTC")
        return formatter
    }()

    private static func local(_ text: String?) -> DateComponents? {
        guard let date = ServerTime.parse(text) else { return nil }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: Int(tashkentOffset)) ?? .current
        return calendar.dateComponents([.day, .month, .hour, .minute], from: date)
    }

    private static func two(_ value: Int?) -> String { String(format: "%02d", value ?? 0) }

    /// `22:04` in Tashkent; `-` without a time.
    static func clock(_ text: String?) -> String {
        guard let parts = local(text) else { return "-" }
        return "\(two(parts.hour)):\(two(parts.minute))"
    }

    /// `06.10 22:04` in Tashkent - when the time of day is the point (an ETA, a departure, a time proposal).
    static func dayClock(_ text: String?) -> String {
        guard let parts = local(text) else { return "-" }
        return "\(two(parts.day)).\(two(parts.month)) \(two(parts.hour)):\(two(parts.minute))"
    }

    /// The direction the feed opens on: the one already chosen while it is still live, else the first active one,
    /// else any not archived; nil when there is none.
    static func pick(_ list: [DriverDirectionDTO], current: String?) -> String? {
        if let current, list.contains(where: { $0.id == current && $0.status != "archived" }) { return current }
        return list.first { $0.status == "active" }?.id ?? list.first { $0.status != "archived" }?.id
    }

    /// The directions a driver still has (the list hides archived ones; the server may send them on request).
    static func live(_ list: [DriverDirectionDTO]) -> [DriverDirectionDTO] { list.filter { $0.status != "archived" } }

    /// The `service_type` the feed asks for: passenger only while the flag allows it and the toggle says so.
    static func service(passengerAllowed: Bool, passenger: Bool) -> ServiceType {
        passengerAllowed && passenger ? .passenger : .parcel
    }
}

// MARK: - Names

enum DirectionEndName {
    /// An end's name for a card: the district when there is one, else the region (a city without districts).
    static func of(_ end: DirectionEndDTO, ru: Bool) -> String {
        if end.districtId != nil { return (ru ? end.districtNameRu : nil) ?? end.districtNameUz ?? "-" }
        return (ru ? end.regionNameRu : nil) ?? end.regionNameUz
    }

    /// `Toshkent shahri → Qarshi`.
    static func route(_ direction: DriverDirectionDTO, ru: Bool) -> String {
        "\(of(direction.origin, ru: ru)) → \(of(direction.destination, ru: ru))"
    }
}

// MARK: - Server answers the screens act on

enum DirectionAnswer {
    private static func details(_ error: Error, code: String) -> JSONValue?? {
        guard let error = error as? APIError, error.code == code else { return nil }
        return .some(error.details)
    }

    private static func string(_ value: JSONValue?) -> String? {
        if case .string(let text)? = value { return text }
        return nil
    }

    private static func proposalImpossible(_ details: JSONValue?) -> Bool {
        if case .bool(false)? = details?["time_proposal_possible"] { return true }
        return string(details?["reason"]) == "time_proposal_too_far"
    }

    /// `409 TIME_WINDOW_CONFLICT` with the car's real ETA: the screen offers to send exactly that time instead - unless
    /// the server says no time proposal can work (Q157: more than 3 h earlier or 12 h later than the client asked).
    static func timeProposalEta(_ error: Error) -> String? {
        guard let details = details(error, code: "TIME_WINDOW_CONFLICT") else { return nil }
        if proposalImpossible(details) { return nil }
        return string(details?["eta"])
    }

    /// Q157: the server's limits (hours) when the car's time is too far from the client's - for an honest sentence.
    static func timeProposalTooFar(_ error: Error) -> (early: Int, late: Int)? {
        guard let details = details(error, code: "TIME_WINDOW_CONFLICT"), proposalImpossible(details) else { return nil }
        func hours(_ key: String, _ fallback: Int) -> Int {
            if case .number(let minutes)? = details?[key] { return Int((minutes / 60).rounded()) }
            return fallback
        }
        return (hours("max_early_minutes", 3), hours("max_late_minutes", 12))
    }

    /// `409 ROUTE_MISMATCH` on create: no ELCHI road serves these two ends yet - a product answer, said as such.
    static func isNoRoad(_ error: Error) -> Bool { (error as? APIError)?.code == "ROUTE_MISMATCH" }

    /// `400 VALIDATION_ERROR` with `direction_exists`: the same two ends are already one of the driver's directions.
    static func isDuplicate(_ error: Error) -> Bool {
        guard let details = details(error, code: "VALIDATION_ERROR") else { return false }
        return string(details?["reason"]) == "direction_exists"
    }

    /// `409 BOOKING_CUTOFF_PASSED` / `pickup_passed`: the car is already past this pickup (Q154).
    static func isPickupPassed(_ error: Error) -> Bool {
        guard let details = details(error, code: "BOOKING_CUTOFF_PASSED") else { return false }
        return string(details?["reason"]) == "pickup_passed"
    }
}

// MARK: - The add form

/// One end being chosen: a region (required) and a district (required where the region has districts; a city
/// without districts is the whole city).
struct DirectionFormEnd: Equatable {
    var region: RegionDTO?
    var district: DistrictDTO?

    /// `requires_district` unknown counts as required (the server's default).
    static func needsDistrict(_ region: RegionDTO?) -> Bool { region?.requiresDistrict != false }

    var ready: Bool { region != nil && (!Self.needsDistrict(region) || district != nil) }

    var input: DirectionEndInput? {
        guard let region, ready else { return nil }
        return DirectionEndInput(districtId: district?.id, regionId: region.id)
    }
}

struct DirectionForm: Equatable {
    var origin = DirectionFormEnd()
    var destination = DirectionFormEnd()

    var ready: Bool { origin.ready && destination.ready }

    /// `POST /driver-directions` - two ends and nothing else: no vehicle (the server takes the one approved car),
    /// no time, no corridor, no stop.
    var body: DriverDirectionCreate? {
        guard let origin = origin.input, let destination = destination.input else { return nil }
        return DriverDirectionCreate(destination: destination, origin: origin)
    }

    /// The Idempotency-Key action: the same two ends are the same request (a retry after a lost answer).
    var action: String? {
        guard let body else { return nil }
        let ends = [body.origin.regionId, body.origin.districtId, body.destination.regionId, body.destination.districtId].map { $0 ?? "-" }
        return "direction.create:\(ends.joined(separator: ":"))"
    }
}

/// What saving the form came to.
enum DirectionCreateOutcome: Equatable {
    case added
    /// `dir.noRoad` / `dir.exists`: a product answer said in place, not a failure banner.
    case notice(String)
    case failed
}

// MARK: - The offer from a direction

enum DirectionOffer {
    /// `POST /driver-directions/{id}/offers`: price, optional message and - for a time proposal - the car's own ETA.
    static func body(listingId: String, unitPriceMinor: Int, message: String?, pickupAt: String?) -> DirectionOfferCreate {
        let text = message?.trimmingCharacters(in: .whitespacesAndNewlines)
        return DirectionOfferCreate(listingId: listingId, message: text?.isEmpty == false ? text : nil, pickupAt: pickupAt,
                                    unitPriceMinor: unitPriceMinor)
    }

    /// The Idempotency-Key action: the same request (direction, listing, price, time) reuses its key on a retry; a time
    /// proposal after a conflict is a different request and gets its own.
    static func action(directionId: String, body: DirectionOfferCreate) -> String {
        "direction.offer:\(directionId):\(body.listingId):\(body.unitPriceMinor):\(body.pickupAt ?? "-")"
    }

    /// The time the offer proposes before it is sent: the car's ETA from a conflict, else (a request at another time)
    /// the feed's ETA; nil for an ordinary offer.
    static func proposeAt(item: DirectionRequestItemDTO, conflictEta: String?) -> String? {
        conflictEta ?? (item.fit == "time_differs" ? item.pickupEta : nil)
    }

    /// The toast after a sent offer: the trip the system planned or moved, with its departure.
    static func sentMessage(_ result: DirectionOfferDTO) -> (key: String, time: String?) {
        if result.tripCreated { return ("dir.bid.tripCreated", DirectionFeed.dayClock(result.trip.plannedStartAt)) }
        if result.tripRetimed { return ("dir.bid.tripRetimed", DirectionFeed.dayClock(result.trip.plannedStartAt)) }
        return ("driverBid.sent", nil)
    }
}

/// Why an offer from a direction was not sent, as the screen says it.
enum DirectionOfferRefusal {
    /// The car reaches the client at `eta`, outside the asked window: "propose this time" is offered.
    case proposeTime(eta: String)
    /// Q157: no time proposal can work.
    case tooFar(early: Int, late: Int)
    /// Q154: the car is already past this pickup.
    case passed
    /// Anything else: the shared `error.*` sentence.
    case other(Error)

    /// `hadPickupAt`: the refused request already was a time proposal (a second conflict is then an ordinary error).
    static func of(_ error: Error, hadPickupAt: Bool) -> DirectionOfferRefusal {
        if !hadPickupAt, let eta = DirectionAnswer.timeProposalEta(error) { return .proposeTime(eta: eta) }
        if DirectionAnswer.isPickupPassed(error) { return .passed }
        if let far = DirectionAnswer.timeProposalTooFar(error) { return .tooFar(early: far.early, late: far.late) }
        return .other(error)
    }
}

// MARK: - The client's side (Q153)

enum TimeProposalLine {
    /// `offer.timeProposal` values when the driver proposes a pickup outside the client's window: the proposed time
    /// (the version's pickup window start) and the window the client asked for. nil for an ordinary offer.
    static func values(_ version: ProposalVersionDTO, listingStart: String?, listingEnd: String?) -> [(String, Any)]? {
        guard version.outsideRequestWindow == true else { return nil }
        return [("time", DirectionFeed.dayClock(version.pickupWindowStart)),
                ("start", listingStart.map { DirectionFeed.dayClock($0) } ?? "-"),
                ("end", DirectionFeed.clock(listingEnd))]
    }
}

// MARK: - The driver's trip read by districts (Q158)

enum TripPlaces {
    struct Place<Item> {
        let name: String
        let stop: Item
    }

    /// The trip's internal route nodes as places along the road: consecutive nodes in one district are one place (the
    /// first of the run keeps its time), the way the web's `DriverTripDetail` reads them.
    static func alongTheRoad<Item>(_ sorted: [Item], name: (Item) -> String) -> [Place<Item>] {
        var out: [Place<Item>] = []
        for item in sorted {
            let place = name(item)
            if out.last?.name == place { continue }
            out.append(Place(name: place, stop: item))
        }
        return out
    }
}
