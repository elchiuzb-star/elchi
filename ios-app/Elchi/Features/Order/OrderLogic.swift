import Foundation

/// A place on the map (WGS84).
public struct GeoPoint: Hashable, Sendable {
    public var lat: Double
    public var lng: Double

    public init(lat: Double, lng: Double) {
        self.lat = lat
        self.lng = lng
    }

    /// `39.65480, 66.97560` - what the screen shows when there is no street address.
    public var text: String { String(format: "%.5f, %.5f", lat, lng) }

    /// Great-circle distance in metres (for "nearest district", never for anything shown as a road distance).
    public func distance(to other: GeoPoint) -> Double {
        let r = 6_371_000.0
        let dLat = (other.lat - lat) * .pi / 180, dLng = (other.lng - lng) * .pi / 180
        let a = sin(dLat / 2) * sin(dLat / 2) + cos(lat * .pi / 180) * cos(other.lat * .pi / 180) * sin(dLng / 2) * sin(dLng / 2)
        return 2 * r * atan2(sqrt(a), sqrt(1 - a))
    }
}

/// One end of the request: region -> district -> a marked place (Q88). The server projects the place onto a
/// confirmed route; the app never calls it "exact".
public struct PlaceEnd: Hashable, Sendable {
    public var region: RegionDTO
    public var district: DistrictDTO
    public var point: GeoPoint
    /// Reverse-geocoded street address; nil when the geocoder had none (the screen shows coordinates instead).
    public var address: String?
    /// Set by the home's locate button: the card says "Joriy joylashuv" instead of the street.
    public var currentLocation: Bool

    public init(region: RegionDTO, district: DistrictDTO, point: GeoPoint, address: String?, currentLocation: Bool = false) {
        self.region = region
        self.district = district
        self.point = point
        self.address = address
        self.currentLocation = currentLocation
    }
}

extension PlaceEnd {
    /// `POST /listings` end (ADR-0028, Q160): always the marked place - never a stop id.
    var pointInput: PointEndInput {
        PointEndInput(address: address, districtId: district.id, lat: point.lat, lng: point.lng)
    }
}

public enum EndSide: String, Hashable, Sendable { case pickup, dropoff }

// MARK: - Money

/// Money is integer minor units on the wire (1 so'm = 100 tiyin); the person types whole so'm.
public enum Money {
    /// Whole so'm the person may type: 12 digits keeps `* 100` far inside Int64.
    public static let maxSoumDigits = 12

    /// Digits of a typed price, without grouping, capped.
    public static func soumDigits(_ typed: String) -> String {
        String(typed.filter(\.isASCIIDigitCharacter).drop(while: { $0 == "0" }).prefix(maxSoumDigits))
    }

    /// `"120 000"` -> 12_000_000 minor units; 0 when nothing (or only zeros) was typed.
    public static func minor(fromSoum typed: String) -> Int {
        (Int(soumDigits(typed)) ?? 0) * 100
    }

    /// Thousands grouped with a narrow no-break space, as the design writes money: `120 000`.
    public static func grouped(_ digits: String) -> String {
        var out = ""
        for (i, ch) in digits.enumerated() {
            if i > 0 && (digits.count - i) % 3 == 0 { out.append("\u{202F}") }
            out.append(ch)
        }
        return out
    }

    /// `12_000_000` minor -> `120 000 so'm` (the currency word comes from the dictionary). Whole so'm only: UZS
    /// prices here are always whole.
    public static func format(minor: Int, currencyWord: String) -> String {
        let soum = minor / 100
        return "\(soum < 0 ? "-" : "")\(grouped(String(abs(soum))))\u{00A0}\(currencyWord)"
    }
}

extension Character {
    fileprivate var isASCIIDigitCharacter: Bool { isASCII && isNumber }
}

// MARK: - Phone

/// Uzbek mobile numbers as the sign-in screen types them: 9 local digits after the fixed +998.
public enum UzPhone {
    public static func localDigits(_ typed: String) -> String {
        var digits = typed.filter(\.isASCIIDigitCharacter)
        if digits.count > 9 && digits.hasPrefix("998") { digits.removeFirst(3) }
        return String(digits.prefix(9))
    }

    /// `+998901234567` -> `901234567`; anything else -> its last 9 digits.
    public static func localDigits(fromE164 phone: String) -> String {
        let digits = phone.filter(\.isASCIIDigitCharacter)
        return String(digits.hasPrefix("998") ? digits.dropFirst(3).prefix(9) : digits.suffix(9))
    }

    /// `901234567` shown as `90 123 45 67`.
    public static func formatLocal(_ digits: String) -> String {
        var out = ""
        for (i, ch) in digits.enumerated() {
            if [2, 5, 7].contains(i) { out.append(" ") }
            out.append(ch)
        }
        return out
    }

    public static func e164(_ local: String) -> String { "+998\(local)" }
    public static func isValid(_ local: String) -> Bool { local.count == 9 }

    /// `+998901234567` -> `+998 90 123 45 67`.
    public static func display(_ phone: String) -> String {
        let local = localDigits(fromE164: phone)
        return local.count == 9 ? "+998 \(formatLocal(local))" : phone
    }
}

// MARK: - Departure window

/// The departure window is chosen and shown in Asia/Tashkent and sent as ISO 8601 with the offset.
public enum DepartureWindow {
    public static let timeZone = TimeZone(identifier: "Asia/Tashkent")!

    static var calendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        return calendar
    }

    /// What the route screen offers the first time: tomorrow, 09:00 - 18:00 Tashkent time.
    public static func suggested(now: Date = Date()) -> (start: Date, end: Date) {
        let calendar = calendar
        let tomorrow = calendar.date(byAdding: .day, value: 1, to: calendar.startOfDay(for: now))!
        return (calendar.date(bySettingHour: 9, minute: 0, second: 0, of: tomorrow)!,
                calendar.date(bySettingHour: 18, minute: 0, second: 0, of: tomorrow)!)
    }

    /// `27.09.2026, 09:00`.
    public static func text(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = timeZone
        formatter.dateFormat = "dd.MM.yyyy, HH:mm"
        return formatter.string(from: date)
    }

    /// `27.09, 09:00` (the review screen's short form).
    public static func shortText(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = timeZone
        formatter.dateFormat = "dd.MM, HH:mm"
        return formatter.string(from: date)
    }

    /// `2026-09-27T09:00:00+05:00` - the API requires the offset.
    public static func iso(_ date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.timeZone = timeZone
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.string(from: date)
    }
}

// MARK: - What is missing on the route step

/// Why "Saqlash" is not available yet - the server's own rules (end > start, end > now, price > 0), said before
/// anything is sent. Each case is one dictionary sentence.
public enum RouteBlocker: String, CaseIterable, Sendable {
    case bothPoints, windowStart, windowEnd, endAfterStart, windowPast, seats, price

    public var key: String {
        switch self {
        case .bothPoints: "app.validation.bothPoints"
        case .windowStart: "app.validation.windowStart"
        case .windowEnd: "client.order.err.windowEnd"
        case .endAfterStart: "client.order.err.endAfterStart"
        case .windowPast: "app.validation.windowPast"
        case .seats: "client.taxi.err.seats"
        case .price: "listingOwner.invalid.price"
        }
    }

    public static func check(directionReady: Bool, start: Date?, end: Date?, priceMinor: Int, now: Date = Date()) -> [RouteBlocker] {
        var problems: [RouteBlocker] = []
        if !directionReady { problems.append(.bothPoints) }
        if start == nil { problems.append(.windowStart) }
        if end == nil { problems.append(.windowEnd) }
        if let start, let end, end <= start { problems.append(.endAfterStart) }
        if let end, end <= now { problems.append(.windowPast) }
        if priceMinor <= 0 { problems.append(.price) }
        return problems
    }
}

// MARK: - Contacts step

public struct ContactsForm: Hashable, Sendable {
    public var senderName = ""
    /// 9 local digits.
    public var senderPhone = ""
    public var receiverName = ""
    public var receiverPhone = ""
    public var comment = ""

    public init() {}

    /// Both names (two letters at least, the design's rule) and both 9-digit phones.
    public var isComplete: Bool {
        ContactBlocker.validName(senderName) && ContactBlocker.validName(receiverName)
            && UzPhone.isValid(senderPhone) && UzPhone.isValid(receiverPhone)
    }
}

// MARK: - Request body

/// Everything the create call needs, gathered from the five steps.
public struct ParcelRequestDraft: Sendable {
    public var pickup: PlaceEnd
    public var dropoff: PlaceEnd
    public var windowStart: Date
    public var windowEnd: Date
    public var priceMinor: Int
    public var contacts: ContactsForm
    public var parcelType: ParcelType
    public var categoryId: String
    public var photoFileId: String

    public init(pickup: PlaceEnd, dropoff: PlaceEnd, windowStart: Date, windowEnd: Date, priceMinor: Int, contacts: ContactsForm,
                parcelType: ParcelType, categoryId: String, photoFileId: String) {
        self.pickup = pickup
        self.dropoff = dropoff
        self.windowStart = windowStart
        self.windowEnd = windowEnd
        self.priceMinor = priceMinor
        self.contacts = contacts
        self.parcelType = parcelType
        self.categoryId = categoryId
        self.photoFileId = photoFileId
    }

    /// `POST /listings` body: a parcel request between two marked places (Q88), total price in minor units, cash.
    /// The sender pays (`payer=sender`); phones are E.164 and are hidden from drivers until acceptance (Q43).
    public func listingCreate() -> ListingCreate {
        let comment = contacts.comment.trimmingCharacters(in: .whitespacesAndNewlines)
        return ListingCreate(
            comment: comment.isEmpty ? nil : comment,
            currency: .uzs,
            departureWindowEnd: DepartureWindow.iso(windowEnd),
            departureWindowStart: DepartureWindow.iso(windowStart),
            destinationPoint: dropoff.pointInput,
            kind: .request,
            originPoint: pickup.pointInput,
            parcel: ParcelDetails(
                categoryId: categoryId,
                parcelType: parcelType,
                payer: .sender,
                photoFileId: photoFileId,
                receiver: ContactDetails(name: contacts.receiverName.trimmingCharacters(in: .whitespacesAndNewlines),
                                         phone: UzPhone.e164(contacts.receiverPhone)),
                sender: ContactDetails(name: contacts.senderName.trimmingCharacters(in: .whitespacesAndNewlines),
                                       phone: UzPhone.e164(contacts.senderPhone))),
            paymentMethod: .cash,
            priceBasis: .total,
            serviceType: .parcel,
            timezone: DepartureWindow.timeZone.identifier,
            unitPriceMinor: priceMinor)
    }
}

// MARK: - Route geometry and figures

public enum Polyline {
    /// Google encoded-polyline decoder (the format `DirectionPreviewDTO.route_polyline` uses, precision 5) - the
    /// same algorithm as the web client's `utils/polyline.ts`. Stops at the first malformed chunk.
    public static func decode(_ encoded: String, precision: Int = 5) -> [GeoPoint] {
        let bytes = Array(encoded.utf8)
        let factor = pow(10.0, Double(precision))
        var points: [GeoPoint] = []
        var index = 0, lat = 0, lng = 0

        func next() -> Int? {
            var result = 0, shift = 0
            while index < bytes.count {
                let byte = Int(bytes[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20 { return (result & 1) != 0 ? ~(result >> 1) : result >> 1 }
            }
            return nil
        }

        while index < bytes.count {
            guard let dLat = next(), let dLng = next() else { break }
            lat += dLat
            lng += dLng
            points.append(GeoPoint(lat: Double(lat) / factor, lng: Double(lng) / factor))
        }
        return points
    }

    /// The part of a route between two places, for drawing. The preview's `route_polyline` is the WHOLE corridor
    /// route (e.g. Toshkent → … → Termiz); a request only travels the leg between its two ends. Each end is projected
    /// onto the nearest segment and the vertices between the two projections are kept, in travel order.
    public static func leg(_ line: [GeoPoint], from origin: GeoPoint, to destination: GeoPoint) -> [GeoPoint] {
        guard line.count > 1 else { return line }
        let a = project(origin, on: line)
        let b = project(destination, on: line)
        let (start, end, reversed) = a.position <= b.position ? (a, b, false) : (b, a, true)
        var points = [start.point]
        if end.segment > start.segment {
            points += line[(start.segment + 1)...end.segment]
        }
        points.append(end.point)
        return reversed ? points.reversed() : points
    }

    /// Nearest point on the line: its segment index, the point, and a monotonic position along the line.
    private static func project(_ p: GeoPoint, on line: [GeoPoint]) -> (segment: Int, point: GeoPoint, position: Double) {
        // Equirectangular approximation around the point: good enough to pick the nearest segment at route scale.
        let k = cos(p.lat * .pi / 180)
        var best = (segment: 0, point: line[0], position: 0.0, distance: Double.infinity)
        for i in 0..<(line.count - 1) {
            let (s, e) = (line[i], line[i + 1])
            let (ax, ay) = ((s.lng - p.lng) * k, s.lat - p.lat)
            let (bx, by) = ((e.lng - p.lng) * k, e.lat - p.lat)
            let (dx, dy) = (bx - ax, by - ay)
            let lengthSquared = dx * dx + dy * dy
            let t = lengthSquared == 0 ? 0 : max(0, min(1, -(ax * dx + ay * dy) / lengthSquared))
            let (x, y) = (ax + t * dx, ay + t * dy)
            let distance = x * x + y * y
            if distance < best.distance {
                let point = GeoPoint(lat: s.lat + t * (e.lat - s.lat), lng: s.lng + t * (e.lng - s.lng))
                best = (i, point, Double(i) + t, distance)
            }
        }
        return (best.segment, best.point, best.position)
    }
}

public enum RouteFigures {
    /// Whole kilometres, at least 1 for any non-zero leg.
    public static func kilometres(_ metres: Int) -> Int { metres <= 0 ? 0 : max(1, Int((Double(metres) / 1000).rounded())) }

    /// Hours and minutes, rounded to the minute.
    public static func duration(_ seconds: Int) -> (hours: Int, minutes: Int) {
        let minutes = Int((Double(max(seconds, 0)) / 60).rounded())
        return (minutes / 60, minutes % 60)
    }

    /// The worse end's distance from the confirmed road, when it is worth saying (>= 5 km).
    public static func offRouteKilometres(_ preview: DirectionPreviewDTO) -> Int? {
        let worst = max(preview.origin.routeOffsetM ?? 0, preview.destination.routeOffsetM ?? 0)
        return worst >= 5000 ? Int((Double(worst) / 1000).rounded()) : nil
    }

    /// `0,5` / `5` / `1,25` - the catalogue's weight limit in kg, written the Uzbek/Russian way.
    public static func kilograms(_ grams: Int) -> String {
        if grams % 1000 == 0 { return String(grams / 1000) }
        var text = String(format: "%.2f", Double(grams) / 1000)
        while text.hasSuffix("0") { text.removeLast() }
        return text.replacingOccurrences(of: ".", with: ",")
    }
}

/// The nearest catalogue district to a marked place: how a region without districts (Tashkent city) still gets
/// the district id the preview needs. Nil when no district has a centre.
public func nearestDistrict(_ districts: [DistrictDTO], to point: GeoPoint) -> DistrictDTO? {
    districts
        .compactMap { d -> (DistrictDTO, Double)? in
            guard let lat = d.centerLat, let lng = d.centerLng else { return nil }
            return (d, GeoPoint(lat: lat, lng: lng).distance(to: point))
        }
        .min { $0.1 < $1.1 }?.0
}
