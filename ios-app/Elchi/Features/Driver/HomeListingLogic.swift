import Foundation

// Design v3 (Royxat 1.4-1.12, Safar 1.2-1.7): the rules of the driver home's "Mijozlar e'lonlari" list, kept out of
// SwiftUI so they are testable. The list is the DD5 answers (`GET /driver-directions/{id}/requests`) of every active
// direction, merged by listing id - Q151: the driver's feed is per direction, there is no country-wide mixed feed.
// DD5 returns the whole <= 14 day list without paging, so search, chips, sort and the minimum price are honest on the
// client.

/// One request on the home list and the direction whose feed brought it (the offer goes from that direction, Q152).
struct HomeListing: Equatable, Sendable {
    let item: DirectionRequestItemDTO
    let directionId: String

    var listing: ListingPublicDTO { item.listing }
    var id: String { item.listing.id }
}

/// The chips under the search: Hammasi / Pochta / Yo'lovchi / Bugun. "Yo'lovchi" only while `passenger_enabled`.
enum HomeChip: String, CaseIterable, Hashable, Sendable {
    case all, parcel, passenger, today

    static func shown(passengerAllowed: Bool) -> [HomeChip] {
        passengerAllowed ? allCases : allCases.filter { $0 != .passenger }
    }

    var labelKey: String {
        switch self {
        case .all: "driver.v3reg.chipAll"
        case .parcel: "driverFeed.modeParcel"
        case .passenger: "offerCreate.servicePassenger"
        case .today: "driver.feed.dateToday"
        }
    }
}

enum HomeSort: String, CaseIterable, Hashable, Sendable {
    case nearest, cheap, expensive

    var labelKey: String {
        switch self {
        case .nearest: "driver.v3reg.sortNearest"
        case .cheap: "driver.v3reg.sortCheap"
        case .expensive: "driver.v3reg.sortExpensive"
        }
    }
}

/// "Narx": a minimum on the client's total (100 000+ / 150 000+ so'm).
enum HomeMinPrice: String, CaseIterable, Hashable, Sendable {
    case any, from100k, from150k

    var minor: Int {
        switch self {
        case .any: 0
        case .from100k: 10_000_000
        case .from150k: 15_000_000
        }
    }
}

/// The filter sheet. The period is the DD5 range that is read; the rest work on what came back.
struct HomeFilter: Equatable, Sendable {
    var period: DirectionFeedDay = .days14
    var sort: HomeSort = .nearest
    var minPrice: HomeMinPrice = .any
    /// "Faqat aniq yo'nalish" (Q158): `match_type == exact`.
    var exactOnly = false

    /// The count on the filter button: every choice away from the default.
    var activeCount: Int {
        (period != .days14 ? 1 : 0) + (sort != .nearest ? 1 : 0) + (minPrice != .any ? 1 : 0) + (exactOnly ? 1 : 0)
    }
}

/// The greeting's seal (Royxat 1.4): approved green, being completed / in review amber, decided (rejected / blocked) red.
enum HomeSeal: Equatable, Sendable {
    case approved, pending, decided

    static func of(_ state: DriverHomeState) -> HomeSeal {
        switch state {
        case .approved: .approved
        case .incomplete, .review: .pending
        case .rejected, .blocked: .decided
        }
    }

    var tone: Tone {
        switch self {
        case .approved: .ok
        case .pending: .warn
        case .decided: .err
        }
    }

    /// The spoken label of the seal: "Tasdiqlangan" / "Tasdiqlanmagan" (decided: the derived word, set by the view).
    var labelKey: String { self == .approved ? "status.approved" : "driver.v3reg.badgeUnverified" }

    /// The toast on a tap. Decided states say the derived word (not "kutilmoqda"): the view passes it.
    var toastKey: String? {
        switch self {
        case .approved: "driver.v3reg.badgeApproved"
        case .pending: "driver.v3reg.badgePending"
        case .decided: nil
        }
    }
}

enum HomeListingLogic {
    /// How many cards the home shows before "Barchasi".
    static let shownCount = 5

    /// The pages of several directions as one list: the first time a listing appears wins (the direction order is the
    /// driver's own), so a request on two directions shows once.
    static func merge(_ pages: [(directionId: String, items: [DirectionRequestItemDTO])]) -> [HomeListing] {
        var seen = Set<String>()
        var out: [HomeListing] = []
        for page in pages {
            for item in page.items where seen.insert(item.listing.id).inserted {
                out.append(HomeListing(item: item, directionId: page.directionId))
            }
        }
        return out
    }

    /// The directions whose feed the home reads: active ones only (a paused direction shows nothing, `dir.paused`).
    static func readable(_ directions: [DriverDirectionDTO]) -> [DriverDirectionDTO] {
        directions.filter { $0.status == "active" }
    }

    /// The service types read for "Hammasi": parcel, and passenger while the flag allows it (K7 / Q89).
    static func services(passengerAllowed: Bool) -> [ServiceType] {
        passengerAllowed ? [.parcel, .passenger] : [.parcel]
    }

    /// The first word of the name ("Jasur Toshmatov" -> "Jasur"); nil without a name ("Salom!").
    static func firstName(_ fullName: String?) -> String? {
        let word = (fullName ?? "").split(whereSeparator: \.isWhitespace).first.map(String.init)
        return word?.isEmpty == false ? word : nil
    }

    /// True when the request's window starts on the Tashkent day of `now`.
    static func isToday(_ listing: ListingPublicDTO, now: Date) -> Bool {
        guard let start = ServerTime.parse(listing.departureWindowStart) else { return false }
        return tashkentDay(start) == tashkentDay(now)
    }

    private static func tashkentDay(_ date: Date) -> Int {
        Int(((date.timeIntervalSince1970 + DirectionFeed.tashkentOffset) / 86_400).rounded(.down))
    }

    /// Chips, search, the filter's exact / minimum price, then the sort. `text` is what the search looks in (route
    /// names, the parcel / people line) in the screen's language.
    static func apply(_ list: [HomeListing], chip: HomeChip, filter: HomeFilter, query: String, now: Date = Date(),
                      text: (HomeListing) -> String) -> [HomeListing] {
        let filtered = list.filter { entry in
            let listing = entry.listing
            switch chip {
            case .all: break
            case .parcel: if listing.serviceType != .parcel { return false }
            case .passenger: if listing.serviceType != .passenger { return false }
            case .today: if !isToday(listing, now: now) { return false }
            }
            if filter.exactOnly && entry.item.matchType != .exact { return false }
            if listing.totalMinor < filter.minPrice.minor { return false }
            return SearchText.matches(text(entry), query)
        }
        return sorted(filtered, by: filter.sort)
    }

    static func sorted(_ list: [HomeListing], by sort: HomeSort) -> [HomeListing] {
        func start(_ entry: HomeListing) -> Date { ServerTime.parse(entry.listing.departureWindowStart) ?? .distantFuture }
        // Stable: equal keys keep the server's order.
        let indexed = list.enumerated()
        let ordered = indexed.sorted { a, b in
            switch sort {
            case .nearest:
                let (x, y) = (start(a.element), start(b.element))
                return x != y ? x < y : a.offset < b.offset
            case .cheap:
                let (x, y) = (a.element.listing.totalMinor, b.element.listing.totalMinor)
                return x != y ? x < y : a.offset < b.offset
            case .expensive:
                let (x, y) = (a.element.listing.totalMinor, b.element.listing.totalMinor)
                return x != y ? x > y : a.offset < b.offset
            }
        }
        return ordered.map(\.element)
    }

    /// The empty line: search or filters on -> "change the filter"; otherwise nothing in this chip.
    static func emptyKey(query: String, filter: HomeFilter) -> String {
        !query.trimmingCharacters(in: .whitespaces).isEmpty || filter.activeCount > 0 ? "driver.v3reg.emptyFiltered" : "driver.v3reg.emptyCategory"
    }

    /// Per-seat requests show the price per person ("kishi boshiga"), the rest the client's total ("jami").
    static func perPerson(_ listing: ListingPublicDTO) -> Bool { PassengerMoney.perSeat(listing.priceBasis) }

    /// The amount on the card: per person -> the unit price, else the total.
    static func shownPriceMinor(_ listing: ListingPublicDTO) -> Int { perPerson(listing) ? listing.unitPriceMinor : listing.totalMinor }
}

/// The kind icon of a request card (Safar 5.5): person for a passenger, envelope for documents, bag, big box, box.
enum ListingKindIcon {
    static func of(_ listing: ListingPublicDTO) -> ElchiIcon {
        if listing.serviceType == .passenger { return .user }
        switch listing.parcelType {
        case .documents?: return .env
        case .bag?, .clothing?: return .bag
        default: return .pkg
        }
    }
}

// MARK: - Trip detail (Safar v3 4.1, 4.5, 4.6)

/// A stretch of the trip's road as the detail shows it: kilometres along the trip, or the whole road.
struct TripStretchRow: Equatable {
    /// nil = the whole road ("Butun yo'l").
    let fromKm: Int?
    let toKm: Int?
    let stretch: StretchAvailabilityDTO?
}

enum TripDetailRules {
    /// ADR-0028 interim (no place on the stretch yet): consecutive stretches whose rounded kilometres are equal are one
    /// row (the first one's capacity is the tightest the server sent first; the smaller remaining wins), so the detail
    /// never prints "a–a km". One row left = the whole road.
    static func rows(_ stretches: [StretchAvailabilityDTO], startM: Int) -> [TripStretchRow] {
        var merged: [(from: Int, to: Int, stretch: StretchAvailabilityDTO)] = []
        for stretch in stretches.sorted(by: { $0.fromM < $1.fromM }) {
            let from = TripStretch.km(stretch.fromM, startM: startM), to = TripStretch.km(stretch.toM, startM: startM)
            // A stretch under a kilometre (or one before the trip's start) is read together with its neighbour.
            if let last = merged.last, from == to || last.from == last.to {
                merged[merged.count - 1] = (last.from, max(last.to, to), tighter(last.stretch, stretch))
            } else {
                merged.append((from, to, stretch))
            }
        }
        if merged.count <= 1 { return merged.map { TripStretchRow(fromKm: nil, toKm: nil, stretch: $0.stretch) } }
        return merged.map { TripStretchRow(fromKm: $0.from, toKm: $0.to, stretch: $0.stretch) }
    }

    /// The smaller remaining of two stretches read as one (never more room than the tighter part has).
    static func tighter(_ a: StretchAvailabilityDTO, _ b: StretchAvailabilityDTO) -> StretchAvailabilityDTO {
        StretchAvailabilityDTO(baggageRemainingMl: min(a.baggageRemainingMl, b.baggageRemainingMl),
                               cargoRemainingVolumeMl: min(a.cargoRemainingVolumeMl, b.cargoRemainingVolumeMl),
                               cargoRemainingWeightG: min(a.cargoRemainingWeightG, b.cargoRemainingWeightG),
                               fromM: min(a.fromM, b.fromM), seatsRemaining: min(a.seatsRemaining, b.seatsRemaining),
                               toM: max(a.toM, b.toM))
    }

    /// Before any booking (no stretch computed): the trip's own capacity as one "Butun yo'l" row (Safar 4.6).
    static func wholeTrip(_ trip: TripDTO) -> StretchAvailabilityDTO {
        StretchAvailabilityDTO(baggageRemainingMl: trip.baggageCapacityMl, cargoRemainingVolumeMl: trip.cargoCapacityVolumeMl,
                               cargoRemainingWeightG: trip.cargoCapacityWeightG, fromM: trip.routeStartM ?? 0,
                               seatsRemaining: trip.seatCapacity, toM: trip.routeEndM ?? (trip.routeStartM ?? 0))
    }

    /// The trip's title without a direction (Safar 4.1 interim): the first and last place of the manifest, nil when
    /// there is none (then the screen says "Safar tafsilotlari" - never two dates).
    static func placesTitle(_ names: [String]) -> String? {
        let clean = names.filter { !$0.isEmpty }
        guard let first = clean.first, let last = clean.last else { return nil }
        return first == last ? first : "\(first) → \(last)"
    }
}
