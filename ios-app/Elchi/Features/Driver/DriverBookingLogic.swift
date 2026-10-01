import Foundation

// MARK: - The driver's booking (v2)

/// `BookingDTO` (driver view): everything the client view has (kept as `base`, so the shared booking screens -
/// amendments, tracking, route and status lines - read the same type), plus the client's first name, the receiver
/// (only after departure, Q44/Q142), the commission snapshot (Q103: the driver may see it) and the driver's money
/// block on a discounted booking.
public struct DriverBookingDTO: Hashable, Sendable, Identifiable {
    public struct Party: Codable, Hashable, Sendable {
        public let id: String
        public let displayName: String
        public let contactPhone: String?

        enum CodingKeys: String, CodingKey {
            case id
            case displayName = "display_name"
            case contactPhone = "contact_phone"
        }
    }

    public struct ParcelContacts: Codable, Hashable, Sendable {
        public let receiverName: String?
        public let receiverPhone: String?

        enum CodingKeys: String, CodingKey {
            case receiverName = "receiver_name"
            case receiverPhone = "receiver_phone"
        }
    }

    public struct Fee: Codable, Hashable, Sendable {
        public let feeBps: Int
        public let commissionMinor: Int
        public let netMinor: Int

        enum CodingKeys: String, CodingKey {
            case feeBps = "fee_bps"
            case commissionMinor = "commission_minor"
            case netMinor = "net_minor"
        }
    }

    private struct Extra: Decodable {
        let tripId: String
        let client: Party?
        let parcelContacts: ParcelContacts?
        let fee: Fee?
        let promo: BookingPromoDriverDTO?
        let commissionStatus: String?

        enum CodingKeys: String, CodingKey {
            case client, fee, promo
            case tripId = "trip_id"
            case parcelContacts = "parcel_contacts"
            case commissionStatus = "commission_status"
        }
    }

    public let base: ClientBookingDTO
    public let tripId: String
    public let client: Party?
    public let parcelContacts: ParcelContacts?
    public let fee: Fee?
    public let promo: BookingPromoDriverDTO?
    public let commissionStatus: String?

    public var id: String { base.id }
    public var status: String { base.serviceStatus }

    public init(base: ClientBookingDTO, tripId: String, client: Party? = nil, parcelContacts: ParcelContacts? = nil, fee: Fee? = nil,
                promo: BookingPromoDriverDTO? = nil, commissionStatus: String? = nil) {
        self.base = base
        self.tripId = tripId
        self.client = client
        self.parcelContacts = parcelContacts
        self.fee = fee
        self.promo = promo
        self.commissionStatus = commissionStatus
    }

    /// The driver side of the union (`viewer_side == "driver"`), or nil for anything else. The shared part decodes
    /// without the driver's `promo` (its shape is the driver's, not the client's).
    public static func from(_ json: JSONValue) -> DriverBookingDTO? {
        guard json["viewer_side"] == .string("driver"), case .object(var object) = json else { return nil }
        object["promo"] = nil
        guard let base = try? JSONValue.object(object).decode(ClientBookingDTO.self),
              let extra = try? json.decode(Extra.self) else { return nil }
        return DriverBookingDTO(base: base, tripId: extra.tripId, client: extra.client, parcelContacts: extra.parcelContacts, fee: extra.fee,
                                promo: extra.promo, commissionStatus: extra.commissionStatus)
    }
}

// MARK: - What the driver may do (parcel, Q139/Q142/Q143/Q144)

/// A parcel booking has no codes, no cash receipt and no driver delivery command: `in_transit` comes from the trip's
/// departure, `delivered`/`completed` from an operator. Before departure the driver may say "Keldim" (a signal,
/// once) and cancel; change the price by agreement while `confirmed` (see `AmendmentActions.amendable`); after
/// completion rate the client (7 days).
public struct DriverBookingActions: Equatable, Sendable {
    public let canArrive: Bool
    public let canAmend: Bool
    public let canCancel: Bool
    public let canRate: Bool
    /// The trip left with the parcel: the "operator records the delivery" note.
    public let inTransit: Bool
    public let terminal: Bool

    public static let preService: Set<String> = ["confirmed", "awaiting_pickup"]
    public static let ratingDays = 7

    public static func of(_ status: String, arrivedSent: Bool = false, updatedAt: Date? = nil, now: Date = Date()) -> DriverBookingActions {
        let before = preService.contains(status)
        let completed = status == "completed"
        let ratingOpen = completed && (updatedAt.map { now.timeIntervalSince($0) <= TimeInterval(ratingDays * 86_400) } ?? true)
        return DriverBookingActions(canArrive: before && !arrivedSent, canAmend: AmendmentActions.amendable(status, side: "driver"),
                                    canCancel: before, canRate: ratingOpen,
                                    inTransit: status == "in_transit" || status == "picked_up",
                                    terminal: BookingActions.terminalStatuses.contains(status))
    }
}

public enum DriverBookingMoney {
    /// The cash the driver collects: the discounted amount on a promo booking, else the agreed total.
    public static func cashToCollect(_ booking: DriverBookingDTO) -> Int {
        booking.promo?.cashToCollectMinor ?? booking.base.totalMinor
    }

    /// The commission this booking costs the driver (`commission_charged_minor` on a promo booking), and the rate.
    public static func commission(_ booking: DriverBookingDTO) -> (minor: Int, percent: String)? {
        guard let fee = booking.fee else { return nil }
        let minor = booking.promo?.commissionChargedMinor ?? fee.commissionMinor
        let percent = fee.feeBps % 100 == 0 ? "\(fee.feeBps / 100)" : String(format: "%.2f", Double(fee.feeBps) / 100)
        return (minor, percent)
    }
}

public enum ReceiverReveal {
    /// The receiver's name and phone only when the server sent the phone (after the trip departed, Q44/Q142); the
    /// sender's phone is never shown.
    public static func of(_ booking: DriverBookingDTO) -> (name: String?, phone: String)? {
        guard let phone = booking.parcelContacts?.receiverPhone, !phone.isEmpty else { return nil }
        let name = booking.parcelContacts?.receiverName.flatMap { $0.isEmpty ? nil : $0 }
        return (name, phone)
    }
}

/// The driver's cancel reasons (design: trip changed, vehicle problem, client unreachable, other).
public enum DriverCancelReason: String, CaseIterable, Sendable {
    case tripChanged = "trip_changed"
    case vehicleProblem = "vehicle_problem"
    case clientUnreachable = "client_unreachable"
    case other

    public var key: String { "bookingCancel.reason.\(rawValue)" }

    /// The refusal said for this booking (`bookingCancel.refused.*`), or nil for the generic error sentence.
    public static func refusalKey(_ error: Error) -> String? {
        switch (error as? APIError)?.code {
        case "VERSION_CONFLICT"?: "bookingCancel.refused.changed"
        case "CUSTODY_REQUIRES_RETURN_FLOW"?: "bookingCancel.refused.custody"
        case "NO_SHOW_REVIEW_PENDING"?: "bookingCancel.refused.noShowPending"
        case "INVALID_STATE_TRANSITION"?: "bookingCancel.refused.tooLate"
        default: nil
        }
    }
}

/// "Faol" (still to do or on its way) and "Tarix" (finished, cancelled, returned).
public enum DriverBookingFilter: String, CaseIterable, Sendable {
    case active, history

    public func includes(_ status: String) -> Bool {
        let done = BookingActions.terminalStatuses.contains(status)
        return self == .active ? !done : done
    }

    public var labelKey: String { self == .active ? "driver.orders.filterActive" : "driver.orders.filterHistory" }
}

/// "Keldim" is a signal the server keeps once; the booking does not say it was sent, so this phone remembers.
enum ArrivedSignals {
    private static func key(_ id: String) -> String { "elchi.arrived.\(id)" }
    static func sent(_ id: String) -> Bool { UserDefaults.standard.bool(forKey: key(id)) }
    static func mark(_ id: String) { UserDefaults.standard.set(true, forKey: key(id)) }
}

/// The client's reputation as the driver reads it: the score only when someone rated (never an invented one).
public enum ClientReputation {
    public static func line(_ reputation: ReputationDTO) -> (score: String?, ratingCount: Int, completed: Int) {
        guard reputation.ratingCount > 0, let average = reputation.averageRating else { return (nil, 0, reputation.completedBookings) }
        return (String(format: "%.1f", average).replacingOccurrences(of: ".", with: ","), reputation.ratingCount, reputation.completedBookings)
    }
}
