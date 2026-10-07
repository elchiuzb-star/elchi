import Foundation

// MARK: - What a v1 order still allows

/// What the client may still do with a v1 order (Q4: its remaining life cycle, never create/edit/publish). Pure: the
/// status the server sent and whether the driver was rated in this session. Mirrors the v1 server's own gates, so no
/// button is offered that the server would refuse.
public struct LegacyActions: Equatable, Sendable {
    /// "Takliflarni ko'rish": while drivers can still bid.
    public let viewBids: Bool
    /// "Yetkazilganini tasdiqlash".
    public let confirm: Bool
    /// "Haydovchini baholang": once confirmed, until rated.
    public let rate: Bool
    /// "Buyurtmani bekor qilish": until pickup (v1 refuses after it).
    public let cancel: Bool
    /// "Muammo haqida xabar berish" (opens a Yordam ticket about the order): from the driver's choice until the
    /// delivery is confirmed.
    public let report: Bool
    /// The confirm sheet's text for cancelling: a chosen driver gets its own warning.
    public let cancelTextKey: String

    public static let bidding: Set<String> = ["published", "bidding"]
    static let cancellable: Set<String> = ["draft", "published", "bidding", "accepted"]
    static let reportable: Set<String> = ["accepted", "picked_up", "in_transit", "delivered"]

    public static func of(_ status: String, rated: Bool = false) -> LegacyActions {
        LegacyActions(viewBids: bidding.contains(status), confirm: status == "delivered", rate: status == "confirmed" && !rated,
                      cancel: cancellable.contains(status), report: reportable.contains(status),
                      cancelTextKey: status == "accepted" ? "confirmDialog.cancelOrder.acceptedText" : "confirmDialog.cancelOrder.text")
    }

    /// Bids can still be chosen from (the bids screen says "closed" otherwise).
    public static func bidsOpen(_ status: String) -> Bool { bidding.contains(status) }
}

/// The driver's phone on a v1 order: the old app's rule, kept - from the choice of driver onwards (v1 has no chat).
/// Before `accepted` there is no driver at all; a cancelled order does not keep one reachable.
public enum LegacyPhone {
    static let visibleFrom: Set<String> = ["accepted", "picked_up", "in_transit", "delivered", "confirmed", "completed", "disputed"]

    public static func visible(_ status: String) -> Bool { visibleFrom.contains(status) }

    /// `tel:+998931112233`, digits and the leading plus only.
    public static func dialURL(_ phone: String) -> URL? {
        let digits = phone.filter { $0.isNumber || $0 == "+" }
        return digits.count >= 9 ? URL(string: "tel:\(digits)") : nil
    }
}

// MARK: - Eski buyurtmalar (archive list)

/// The archive list's chips (BOSQICH 10): "Hammasi", "Yakunlangan" (delivered or confirmed), "Bekor qilingan",
/// "Nizoli". `GET /client/orders` takes one status only, so the list filters the loaded pages on the device.
public enum LegacyFilter: String, CaseIterable, Sendable {
    case all, completed, cancelled, disputed

    public var labelKey: String {
        switch self {
        case .all: "client.v3archive.filterAll"
        case .completed: "status.completed"
        case .cancelled: "status.cancelled"
        case .disputed: "client.v3archive.filterDisputed"
        }
    }

    public func matches(_ status: String) -> Bool {
        switch self {
        case .all: true
        case .completed: ["delivered", "confirmed", "completed"].contains(status)
        case .cancelled: status == "cancelled"
        case .disputed: status == "disputed"
        }
    }

    public func apply(_ orders: [LegacyOrder]) -> [LegacyOrder] {
        self == .all ? orders : orders.filter { matches($0.status) }
    }

    /// Rows a filtered list wants on screen before it stops asking for older pages (v1 history is small).
    public static let screenful = 8

    /// Ask for the next page: more exist and the filtered list is still shorter than a screen.
    public static func wantsMore(filtered: Int, hasMore: Bool) -> Bool { hasMore && filtered < screenful }
}

/// A v1 order's card meta on the archive list: `EL-10422 · 04.08.2026` (no "arxiv" suffix on its own screen).
public enum LegacyListMeta {
    public static func line(orderNumber: String?, createdAt: String?) -> String? {
        let date = ServerTime.parse(createdAt).map(Self.day)
        let parts = [orderNumber?.trimmingCharacters(in: .whitespaces), date].compactMap { $0 }.filter { !$0.isEmpty }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// `04.08.2026` in Tashkent time.
    public static func day(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = DepartureWindow.timeZone
        formatter.dateFormat = "dd.MM.yyyy"
        return formatter.string(from: date)
    }
}

/// "Muammo haqida xabar" on a v1 order (USER DECISION, Q141): no dispute form; the Yordam ticket form opens with the
/// order number already written, so the operator knows which order it is about.
public enum LegacySupport {
    public static func prefill(orderNumber: String?, id: Int) -> String {
        let number = orderNumber?.trimmingCharacters(in: .whitespaces)
        return "\((number?.isEmpty == false ? number : nil) ?? "#\(id)"): "
    }
}

// MARK: - Map points and Yandex links

public enum LegacyMapPoints {
    /// The sheet's tabs: the ends that exist, pickup first.
    public enum End: String, CaseIterable, Sendable { case pickup, dropoff }

    public static func ends(pickup: GeoPoint?, dropoff: GeoPoint?) -> [End] {
        [pickup != nil ? End.pickup : nil, dropoff != nil ? End.dropoff : nil].compactMap { $0 }
    }

    /// `41.31108, 69.27974`: five decimals, a dot, latitude first.
    public static func coordinates(_ p: GeoPoint) -> String {
        String(format: "%.5f, %.5f", p.lat, p.lng)
    }

    /// A coordinate pair from v1 DECIMAL values (a number or a string); nil when either is missing or not a place.
    public static func point(_ lat: JSONValue?, _ lng: JSONValue?) -> GeoPoint? {
        guard let lat = LegacyNumber.double(lat), let lng = LegacyNumber.double(lng),
              (-90...90).contains(lat), (-180...180).contains(lng), !(lat == 0 && lng == 0) else { return nil }
        return GeoPoint(lat: lat, lng: lng)
    }
}

/// The two "open in Yandex" links of the map sheet (the web client's, unchanged).
public enum YandexMapLinks {
    /// One point: `pt` is **longitude first**.
    public static func point(_ p: GeoPoint) -> URL {
        URL(string: "https://yandex.uz/maps/?pt=\(coordinate(p.lng)),\(coordinate(p.lat))&z=16&l=map")!
    }

    /// Directions from wherever the person is to `p` (`rtext=~lat,lng`: an empty start is "my location").
    public static func route(to p: GeoPoint) -> URL {
        URL(string: "https://yandex.uz/maps/?rtext=~\(coordinate(p.lat)),\(coordinate(p.lng))&rtt=auto")!
    }

    /// Six decimals (about 10 cm), no exponent, no trailing zeros.
    static func coordinate(_ value: Double) -> String {
        var text = String(format: "%.6f", value)
        while text.hasSuffix("0") { text.removeLast() }
        if text.hasSuffix(".") { text.removeLast() }
        return text
    }
}

// MARK: - Numbers, money, rating

/// A v1 DECIMAL read either way it arrives: `4.6` or `"4.60"`.
public enum LegacyNumber {
    public static func double(_ value: JSONValue?) -> Double? {
        switch value {
        case .number(let number)?: return number.isFinite ? number : nil
        case .string(let text)?: return Double(text.trimmingCharacters(in: .whitespaces))
        default: return nil
        }
    }
}

extension LegacyMoney {
    /// What the order costs: the agreed price, else the client's own price, else the tariff's suggestion.
    public static func price(final: JSONValue?, client: JSONValue?, suggested: JSONValue?) -> Int? {
        minor(final) ?? minor(client) ?? minor(suggested)
    }
}

public enum LegacyRating {
    /// `4,6` in both languages (one decimal, comma), or nil for a driver without ratings - never an invented number (§8.2).
    public static func text(_ value: JSONValue?) -> String? {
        guard let rating = LegacyNumber.double(value), rating > 0 else { return nil }
        return String(format: "%.1f", min(rating, 5)).replacingOccurrences(of: ".", with: ",")
    }
}

// MARK: - Time

/// v1 timestamps: naive ones are UTC (Q9), aware ones carry their offset; both are shown in Tashkent time.
public enum LegacyTime {
    public static func display(_ text: String?) -> String? {
        ServerTime.parse(text).map(DepartureWindow.text)
    }
}

// MARK: - Refusals

/// Which command a refusal belongs to: the same code means different things on different screens.
public enum LegacyCommand: Equatable, Sendable {
    case select, confirm, rate, cancel
}

public enum LegacyErrors {
    /// The dictionary key for a v1 refusal, said for the client; nil = the generic mapping (`errorText`: offline,
    /// rate limit, known codes, the server's message).
    public static func key(_ error: Error, for command: LegacyCommand) -> String? {
        guard let error = error as? APIError else { return nil }
        if error.status == 429 { return "error.RATE_LIMITED" }
        switch (command, error.code) {
        // The driver took the bid back or it closed: the list is reloaded and the person picks again.
        case (.select, "BID_NOT_ACTIVE"): return "client.legacy.error.bidGone"
        // The driver's own standing (approval, block, availability) is not the client's business: said neutrally.
        case (.select, "DRIVER_NOT_APPROVED"), (.select, "DRIVER_BLOCKED"), (.select, "DRIVER_NOT_AVAILABLE"):
            return "client.legacy.error.driverUnavailable"
        // The order moved on meanwhile (chosen elsewhere, picked up...): the screen reloads it.
        case (_, "ORDER_INVALID_STATUS"): return "client.legacy.error.orderChanged"
        default: return nil
        }
    }

    /// A repeated rating is not a failure: the driver is rated (the server keeps the first).
    public static func alreadyRated(_ error: Error) -> Bool {
        (error as? APIError)?.code == "ALREADY_EXISTS"
    }

    /// 404 or 403 on the order itself: someone else's, or gone - the not-found state, not an error with retry.
    public static func notFound(_ error: Error) -> Bool {
        guard let error = error as? APIError else { return false }
        return error.status == 404 || error.status == 403
    }
}
