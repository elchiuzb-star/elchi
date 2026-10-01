import Foundation

// MARK: - What the client may do with a booking

/// The booking DTO has no actions field: what the client may do follows from `service_status` alone (parcel:
/// confirmed -> awaiting_pickup -> in_transit -> delivered -> completed; cancelled and the custody states off the line).
public struct BookingActions: Equatable, Sendable {
    /// Before the parcel leaves with the driver (after that the server wants the return flow: `CUSTODY_REQUIRES_RETURN_FLOW`).
    public let canCancel: Bool
    /// Only while nothing has started: the server never accepts an amendment on a boarding trip (the web offers it in
    /// awaiting_pickup too - not copied).
    public let canAmend: Bool
    /// The operator has completed the booking (Q139/Q144).
    public let canRate: Bool
    /// A recipient link makes sense while the parcel is still on its way (hidden once delivered or finished).
    public let canShareTracking: Bool
    /// Nothing will change any more (the chat still reads, support still works).
    public let terminal: Bool

    static let terminalStatuses: Set<String> = ["completed", "cancelled", "no_show", "returned", "delivery_failed"]

    public static func of(_ status: String) -> BookingActions {
        let terminal = terminalStatuses.contains(status)
        return BookingActions(canCancel: status == "confirmed" || status == "awaiting_pickup", canAmend: status == "confirmed",
                              canRate: status == "completed",
                              canShareTracking: !terminal && status != "delivered" && status != "return_required",
                              terminal: terminal)
    }
}

// MARK: - Status ladder

/// One step of "Holat kuzatuvi": the dictionary key, whether it is behind, current or ahead, and the time when the
/// booking says it (only `confirmed` = created and `cancelled` carry one - nothing is invented).
public struct LadderStep: Equatable, Sendable {
    public enum State: Equatable, Sendable { case done, current, ahead }
    public let key: String
    public let state: State
    public let at: Date?
}

public enum StatusLadder {
    /// The parcel's path. `picked_up` (legacy) sits with in_transit: for a parcel "yo'lga chiqdi" is the trip leaving.
    static let keys = ["status.confirmed", "parcel.progress.tripPreparing", "parcel.status.driverDeparted",
                       "parcel.progress.deliveredByOperator", "app.progress.completed"]

    /// Where a status sits on the ladder, or nil when it is off it (cancelled, return and custody states).
    public static func position(_ status: String) -> Int? {
        switch status {
        case "confirmed": 0
        case "awaiting_pickup": 1
        case "picked_up", "in_transit": 2
        case "delivered": 3
        case "completed": 4
        default: nil
        }
    }

    /// The steps for a booking on the ladder; an off-ladder status gets none (the screen says the status instead).
    public static func steps(status: String, createdAt: Date?) -> [LadderStep] {
        guard let position = position(status) else { return [] }
        return keys.enumerated().map { index, key in
            let state: LadderStep.State = index < position || (index == position && index == keys.count - 1) ? .done
                : index == position ? .current : .ahead
            return LadderStep(key: key, state: state, at: index == 0 ? createdAt : nil)
        }
    }
}

// MARK: - Live location freshness

/// The server buckets a point by age when it answers; the answer then ages on the phone. The device re-ages
/// `captured_at` on its own clock and only ever makes the bucket worse - never "fresh" when the server did not say
/// so, never "live" for an old point (§10.5: no false "GPS faol").
public enum LiveFreshness {
    public static let freshSeconds: TimeInterval = 30
    public static let delayedSeconds: TimeInterval = 120

    static func rank(_ freshness: TrackingFreshness) -> Int {
        switch freshness {
        case .fresh: 0
        case .delayed: 1
        case .lost: 2
        default: 3 // no_data, and anything this version does not know
        }
    }

    /// The bucket for a point captured at `capturedAt`, on this device's clock.
    public static func bucket(capturedAt: Date?, now: Date) -> TrackingFreshness {
        guard let capturedAt else { return .noData }
        let age = now.timeIntervalSince(capturedAt)
        return age <= freshSeconds ? .fresh : age <= delayedSeconds ? .delayed : .lost
    }

    /// The worse of the server's bucket and the re-aged one.
    public static func effective(server: TrackingFreshness, capturedAt: Date?, now: Date) -> TrackingFreshness {
        let device = bucket(capturedAt: capturedAt, now: now)
        return rank(device) > rank(server) ? device : server
    }
}

// MARK: - Plate and phone

/// How the driver card shows the plate and the phone (Q43/Q44/Q64): nothing the server did not disclose.
public struct DriverReveal: Equatable, Sendable {
    public let plate: String
    /// The full plate is shown; otherwise the masked one with "To'liq raqam ... ochiladi".
    public let plateFull: Bool
    /// The driver's phone, only when the server says phones are visible and sent one.
    public let phone: String?

    public static func of(_ booking: ClientBookingDTO) -> DriverReveal? {
        guard let driver = booking.driver else { return nil }
        let full = driver.vehicle.plateNumber.flatMap { $0.isEmpty ? nil : $0 }
        let phone = booking.contact?.phonesVisible == true ? driver.contactPhone.flatMap { $0.isEmpty ? nil : $0 } : nil
        return DriverReveal(plate: full ?? driver.vehicle.plateMasked, plateFull: full != nil, phone: phone)
    }

    /// `tel:+998901234567` for the call button.
    public static func dialURL(_ phone: String) -> URL? {
        URL(string: "tel:" + phone.filter { $0.isNumber || $0 == "+" })
    }
}

// MARK: - Reason codes

/// The client's cancel reasons (the server takes any code; these are the design's four).
public enum BookingCancelReason: String, CaseIterable, Sendable {
    case plansChanged = "plans_changed"
    case foundOtherOption = "found_other_option"
    case driverUnreachable = "driver_unreachable"
    case other

    public var key: String { "bookingCancel.reason.\(rawValue)" }

    /// A cancellation said in words: any code the dictionary knows (the driver's and the operator's too).
    public static func key(forCode code: String) -> String { "bookingCancel.reason.\(code)" }

    /// Who cancelled, said from the client's side ("Siz", "Haydovchi", "Operator", "Tizim").
    public static func sideKey(_ side: String) -> String {
        switch side {
        case "client": "client.bookingDetail.bySideClient"
        case "driver": "safety.driverTitle"
        case "operator": "support.operator"
        default: "client.bookingDetail.bySideSystem"
        }
    }
}

// MARK: - Chat

/// The booking chat as the phone holds it: the server pages newest first, the screen reads oldest first. Polling
/// brings the newest page again - merging by id keeps each message once and takes the server's latest state of it
/// (a message the operator hid afterwards turns into the hidden line).
public enum ChatTimeline {
    public static func merge(_ current: [ChatMessageDTO], _ incoming: [ChatMessageDTO]) -> [ChatMessageDTO] {
        var byId: [String: ChatMessageDTO] = [:]
        for message in current { byId[message.id] = message }
        for message in incoming { byId[message.id] = message }
        return byId.values.sorted { a, b in
            let da = ServerTime.parse(a.createdAt) ?? .distantPast, db = ServerTime.parse(b.createdAt) ?? .distantPast
            return da != db ? da < db : a.id < b.id
        }
    }

    /// Messages in `incoming` the phone did not have yet and that the other side wrote ("Yangi xabar").
    public static func newFromOthers(_ current: [ChatMessageDTO], _ incoming: [ChatMessageDTO]) -> Int {
        let known = Set(current.map(\.id))
        return incoming.filter { !known.contains($0.id) && !$0.isMine }.count
    }

    /// The quick replies a client may send (Q100: never `price_agreed` in a booking chat).
    public static let clientQuickReplies: [QuickReplyCode] = [.atStop, .clarifyStop]

    /// Seconds to wait after `RATE_LIMITED`, from `details.retry_after_s`.
    public static func retryAfter(_ error: Error) -> Int? {
        guard let error = error as? APIError, error.code == "RATE_LIMITED" else { return nil }
        if case .number(let seconds)? = error.details?["retry_after_s"] { return max(1, Int(seconds.rounded(.up))) }
        return 60
    }
}

// MARK: - Tracking links

/// Recipient link lifetimes (Q83: 15 minutes to 24 hours), as the design's chips, in minutes.
public enum TrackingTTL {
    public static let minutes = [15, 60, 180, 360, 720, 1440]
    public static let defaultMinutes = 60

    public static func clamp(_ minutes: Int) -> Int { min(max(minutes, 15), 1440) }
}

// MARK: - The tracking socket's address

public enum TrackingSocket {
    /// `ws(s)://<api host>/api/v2/ws` from the API base the app already has: same host and port, http -> ws.
    public static func url(apiBase: URL) -> URL? {
        guard var components = URLComponents(url: apiBase, resolvingAgainstBaseURL: false) else { return nil }
        switch components.scheme?.lowercased() {
        case "https": components.scheme = "wss"
        case "http": components.scheme = "ws"
        default: return nil
        }
        components.path = "/api/v2/ws"
        components.query = nil
        components.fragment = nil
        return components.url
    }

    /// Reconnect delays: 5 s doubling to a minute.
    public static func backoff(attempt: Int) -> TimeInterval {
        min(60, 5 * pow(2, Double(max(0, attempt))))
    }
}

// MARK: - Amendments

/// What the client may do with one amendment: answer the driver's while it is open, take back its own. A proposed
/// amendment stays `proposed` on the server after the booking moves on, but the booking then takes no change
/// (`trip_not_planned`): outside `confirmed` nothing is offered.
public struct AmendmentActions: Equatable, Sendable {
    public let open: Bool
    public let canAccept: Bool
    public let canReject: Bool
    public let canWithdraw: Bool

    public static func of(_ amendment: AmendmentDTO, bookingStatus: String, now: Date = Date()) -> AmendmentActions {
        let expired = ServerTime.parse(amendment.expiresAt).map { now >= $0 } ?? false
        let open = amendment.status == "proposed" && !expired && bookingStatus == "confirmed"
        let theirs = amendment.authorSide != "client"
        return AmendmentActions(open: open, canAccept: open && theirs, canReject: open && theirs, canWithdraw: open && !theirs)
    }

    /// The status badge: key and tone (a proposed one the clock has closed reads as expired).
    public static func status(_ amendment: AmendmentDTO, bookingStatus: String, now: Date = Date()) -> StatusLabel {
        let expired = ServerTime.parse(amendment.expiresAt).map { now >= $0 } ?? false
        let status = amendment.status != "proposed" ? amendment.status : expired ? "expired"
            : bookingStatus != "confirmed" ? "closed" : "proposed"
        switch status {
        case "proposed": return StatusLabel(key: "status.proposed", raw: status, tone: .warn)
        case "accepted": return StatusLabel(key: "client.amendment.statusAccepted", raw: status, tone: .ok)
        case "rejected": return StatusLabel(key: "amendment.rejected", raw: status, tone: .err)
        case "withdrawn": return StatusLabel(key: "status.withdrawn", raw: status, tone: .gray)
        case "closed": return StatusLabel(key: "client.amendment.statusClosed", raw: status, tone: .gray)
        default: return StatusLabel(key: "status.expired", raw: status, tone: .gray)
        }
    }
}

// MARK: - Support chat

public enum SupportStatus {
    /// "Navbatda - operator hali ko'rmadi" and the other three (dictionary `support.status.*`).
    public static func key(_ thread: SupportThreadDTO) -> String {
        thread.status == "closed" ? "support.status.closed" : "support.status.\(thread.staffStatus)"
    }

    public static func isClosed(_ thread: SupportThreadDTO?) -> Bool { thread?.status == "closed" }
}
