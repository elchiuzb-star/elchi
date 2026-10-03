import Foundation

// BOSQICH 02 design ("Elchi Buyurtma Yaratish"): the pure rules behind the redesigned request flow - the steps and
// their counter, tap-to-validate lists, the taxi block on the home sheet, the price stepper, the departure-window
// sheet, the comment warning and "locate -> Qayerdan". No views, no network.

// MARK: - Steps

/// Which end of the departure window a tile or the sheet is about.
public enum WindowEdge: String, Identifiable, Sendable {
    case start, end
    public var id: String { rawValue }
}

/// Where the request flow is. Taksi: home -> review (1 / 1). Pochta: home -> route (1 / 3) -> contact (2 / 3) ->
/// review (3 / 3). The place pickers sit outside the count.
public enum OrderStep: Sendable {
    case route, contact, review

    /// `(n, total)` for the bar's "n / total", nil when the step is not part of that service's flow.
    public static func position(_ step: OrderStep, mode: ServiceType) -> (index: Int, total: Int)? {
        let flow: [OrderStep] = mode == .passenger ? [.review] : [.route, .contact, .review]
        return flow.firstIndex(of: step).map { ($0 + 1, flow.count) }
    }
}

// MARK: - Taksi seats

/// The home sheet's "Necha kishi": 1, 2, 3 or the whole cabin (4 seats). Nothing is chosen at first.
public enum TaxiSeats {
    public static let options = [1, 2, 3, 4]
    public static let wholeCabin = 4

    public static func isWholeCabin(_ count: Int?) -> Bool { count == wholeCabin }
}

// MARK: - What is missing (tap-to-validate)

extension RouteBlocker {
    /// The taxi block on the home sheet (the direction is already ready there): the window, the people, the price -
    /// the design's order.
    public static func taxiHome(start: Date?, end: Date?, priceMinor: Int, seatCount: Int?, now: Date = Date()) -> [RouteBlocker] {
        var problems = check(directionReady: true, start: start, end: end, priceMinor: priceMinor, now: now).filter { $0 != .price }
        if seatCount == nil { problems.append(.seats) }
        if priceMinor <= 0 { problems.append(.price) }
        return problems
    }

    /// Whether this problem marks the start tile, the end tile, the seats or the price (red borders).
    public var marksStart: Bool { self == .windowStart }
    public var marksEnd: Bool { self == .windowEnd || self == .endAfterStart || self == .windowPast }
}

/// Why "Davom etish" on the contact step cannot go on yet (`errsFor('contact')`), one sentence each.
public enum ContactBlocker: String, CaseIterable, Sendable {
    case senderName, senderPhone, receiverName, receiverPhone, type, size, photo

    public var key: String {
        switch self {
        case .senderName: "client.order.err.senderName"
        case .senderPhone: "client.order.err.phone9"
        case .receiverName: "client.order.err.receiverName"
        case .receiverPhone: "client.order.err.receiverPhone"
        case .type: "client.order.err.type"
        case .size: "client.order.err.size"
        case .photo: "orderForm.photoRequired"
        }
    }

    /// A person's name: at least two letters after trimming.
    public static func validName(_ name: String) -> Bool { name.trimmingCharacters(in: .whitespacesAndNewlines).count >= 2 }

    public static func check(contacts: ContactsForm, parcelType: ParcelType?, hasCategory: Bool, photoUploaded: Bool) -> [ContactBlocker] {
        var problems: [ContactBlocker] = []
        if !validName(contacts.senderName) { problems.append(.senderName) }
        if !UzPhone.isValid(contacts.senderPhone) { problems.append(.senderPhone) }
        if !validName(contacts.receiverName) { problems.append(.receiverName) }
        if !UzPhone.isValid(contacts.receiverPhone) { problems.append(.receiverPhone) }
        if parcelType == nil { problems.append(.type) }
        if !hasCategory { problems.append(.size) }
        if !photoUploaded { problems.append(.photo) }
        return problems
    }
}

// MARK: - Price stepper

/// "−" / "+" move the price by 5 000 so'm, never below 0; typing keeps at most 8 digits (99 999 999 so'm).
public enum PriceStep {
    public static let step = 5_000
    public static let maxDigits = 8
    public static let maxSoum = 99_999_999

    /// Digits of a typed price for the stepper's field (no grouping, no leading zeros, 8 digits at most).
    public static func digits(_ typed: String) -> String { String(Money.soumDigits(typed).prefix(maxDigits)) }

    /// The price after one tap: `delta` is +1 or -1 steps. Empty stays empty only when it would go below zero.
    public static func apply(_ digits: String, delta: Int) -> String {
        let current = Int(digits) ?? 0
        let next = min(max(current + delta * step, 0), maxSoum)
        return next == 0 ? "" : String(next)
    }
}

// MARK: - The comment

/// The comment is masked by the server when it carries a phone number or a link; the app warns while typing.
public enum NoteText {
    public static let maxLength = 300

    private static let contactPattern = #"\d{7,}|\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}|https?:|www\.|t\.me|@\w"#

    public static func limited(_ text: String) -> String { String(text.prefix(maxLength)) }

    public static func carriesContact(_ text: String) -> Bool {
        text.range(of: contactPattern, options: .regularExpression) != nil
    }

    /// What the review shows: numbers and links as `•••` (the server's own masking decides what is published).
    public static func masked(_ text: String) -> String {
        text.replacingOccurrences(of: #"\d{7,}|\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}"#, with: "•••", options: .regularExpression)
            .replacingOccurrences(of: #"https?://\S+|www\.\S+|t\.me/\S+|@\w+"#, with: "•••", options: .regularExpression)
    }
}

// MARK: - Departure window sheet

/// The bottom sheet's rules: a 21-day strip from today (Tashkent), hours 00-23, minutes on a quarter-hour grid, the
/// end edge's quick lengths, and what cannot be chosen.
public enum WindowPicker {
    public static let dayCount = 21
    public static let minutes = [0, 15, 30, 45]
    public static let quickHours = [2, 4, 8]

    static var calendar: Calendar { DepartureWindow.calendar }

    /// Midnight (Tashkent) of today and the next 20 days.
    public static func days(now: Date = Date()) -> [Date] {
        let today = calendar.startOfDay(for: now)
        return (0..<dayCount).compactMap { calendar.date(byAdding: .day, value: $0, to: today) }
    }

    /// `(day index, hour, minute)` of a value on the strip; a day outside the strip clamps to its ends.
    public static func parts(_ date: Date, days: [Date]) -> (day: Int, hour: Int, minute: Int) {
        let day = calendar.startOfDay(for: date)
        let index = days.firstIndex(of: day) ?? (day < (days.first ?? day) ? 0 : max(days.count - 1, 0))
        let c = calendar.dateComponents([.hour, .minute], from: date)
        return (index, c.hour ?? 0, c.minute ?? 0)
    }

    public static func compose(day: Date, hour: Int, minute: Int) -> Date {
        calendar.date(bySettingHour: hour, minute: minute, second: 0, of: day) ?? day
    }

    /// The minute wheel: the quarter hours, plus a value already chosen off the grid (a prefilled "now + 5 min").
    public static func minuteOptions(including minute: Int) -> [Int] {
        minutes.contains(minute) ? minutes : (minutes + [minute]).sorted()
    }

    /// "+2 / +4 / +8 soat" from the start; "Kun oxirigacha" = 23:45 of the start's day.
    public static func quick(hours: Int?, from start: Date) -> Date {
        guard let hours else { return compose(day: calendar.startOfDay(for: start), hour: 23, minute: 45) }
        return start.addingTimeInterval(TimeInterval(hours * 3600))
    }

    /// The sentence under the wheels, or nil when the value can be taken.
    public static func problemKey(edge: WindowEdge, value: Date, start: Date?, now: Date = Date()) -> String? {
        if value <= now { return "client.order.picker.past" }
        if edge == .end, let start, value <= start { return "client.order.err.endAfterStart" }
        return nil
    }

    /// Whole minutes between start and end (0 when the order is wrong).
    public static func lengthMinutes(start: Date, end: Date) -> Int { max(0, Int((end.timeIntervalSince(start) / 60).rounded())) }
}

// MARK: - Locate -> "Qayerdan"

/// The locate button fills an empty "Qayerdan" from the phone's position: the nearest active district centre (the
/// server's own `nearest_district` rule), only inside Uzbekistan and only within 50 km of a centre. The reverse
/// geocoder's v1 ids are not v2 district ids, so the district comes from `/api/v2/districts` instead.
public enum LocateRules {
    public static let maxDistanceM = 50_000.0

    public static func district(near point: GeoPoint, in districts: [DistrictDTO]) -> DistrictDTO? {
        guard MyLocationLogic.insideUzbekistan(point) else { return nil }
        let candidates = districts.filter { $0.isActive != false }
        guard let nearest = nearestDistrict(candidates, to: point), let lat = nearest.centerLat, let lng = nearest.centerLng,
              GeoPoint(lat: lat, lng: lng).distance(to: point) <= maxDistanceM else { return nil }
        return nearest
    }

    /// The region a district belongs to: the catalogue's entry, or one made from the district's own reference.
    public static func region(of district: DistrictDTO, in regions: [RegionDTO]) -> RegionDTO {
        regions.first { $0.id == district.region.id }
            ?? RegionDTO(code: district.region.code, id: district.region.id, nameUz: district.region.nameUz)
    }
}
