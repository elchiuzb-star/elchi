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
    /// `failed`: the design's red cross ("Bekor qilindi" on a cancelled booking's two-step ladder).
    public enum State: Equatable, Sendable { case done, current, ahead, failed }
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
    /// A passenger booking has its own ladder (`PassengerStatus`): confirmed, driver at the stop, aboard, arrived, done.
    public static func steps(status: String, createdAt: Date?, service: ServiceType = .parcel) -> [LadderStep] {
        let passenger = service == .passenger
        guard let position = passenger ? PassengerStatus.position(status) : position(status) else { return [] }
        let keys = passenger ? PassengerStatus.ladder : keys
        return keys.enumerated().map { index, key in
            let state: LadderStep.State = index < position || (index == position && index == keys.count - 1) ? .done
                : index == position ? .current : .ahead
            return LadderStep(key: key, state: state, at: index == 0 ? createdAt : nil)
        }
    }

    /// A cancelled (or no-show) booking: the design's two steps - "Tasdiqlandi" with when it was made, then
    /// "Bekor qilindi" (red cross) with when it was cancelled. Nil for any other status.
    public static func cancelledSteps(status: String, createdAt: Date?, cancelledAt: Date?) -> [LadderStep]? {
        guard status == "cancelled" || status == "no_show" else { return nil }
        return [LadderStep(key: "status.confirmed", state: .done, at: createdAt),
                LadderStep(key: status == "no_show" ? "status.no_show" : "bookingCancel.cancelledBy", state: .failed, at: cancelledAt)]
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
    /// The driver's (§16): on the way, at the stop, which stop.
    public static let driverQuickReplies: [QuickReplyCode] = [.arrivingIn5Min, .atStop, .clarifyStop]

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

    /// Whether the booking still takes a change - for both sides only while `confirmed`: the server creates one in
    /// `awaiting_pickup` too, but its accept refuses every change once the trip left `planned` (`trip_not_planned`),
    /// and awaiting_pickup means the trip is boarding (the web offers it there - not copied).
    public static func amendable(_ bookingStatus: String, side: String = "client") -> Bool {
        bookingStatus == "confirmed"
    }

    public static func of(_ amendment: AmendmentDTO, bookingStatus: String, now: Date = Date(), side: String = "client") -> AmendmentActions {
        let expired = ServerTime.parse(amendment.expiresAt).map { now >= $0 } ?? false
        let open = amendment.status == "proposed" && !expired && amendable(bookingStatus, side: side)
        let theirs = amendment.authorSide != side
        return AmendmentActions(open: open, canAccept: open && theirs, canReject: open && theirs, canWithdraw: open && !theirs)
    }

    /// The status badge: key and tone (a proposed one the clock has closed reads as expired).
    public static func status(_ amendment: AmendmentDTO, bookingStatus: String, now: Date = Date(), side: String = "client") -> StatusLabel {
        let expired = ServerTime.parse(amendment.expiresAt).map { now >= $0 } ?? false
        let status = amendment.status != "proposed" ? amendment.status : expired ? "expired"
            : !amendable(bookingStatus, side: side) ? "closed" : "proposed"
        switch status {
        case "proposed": return StatusLabel(key: "status.proposed", raw: status, tone: .warn)
        // BOSQICH 04: the past tense ("Qabul qilindi", "Rad etildi", "Qaytarib olindi").
        case "accepted": return StatusLabel(key: "client.booking.amendStatusAccepted", raw: status, tone: .ok)
        case "rejected": return StatusLabel(key: "amendment.rejected", raw: status, tone: .err)
        case "withdrawn": return StatusLabel(key: "client.offers.closed.withdrawn", raw: status, tone: .gray)
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

// MARK: - BOSQICH 04 design ("Elchi Bron"): the detail

/// What the redesigned booking detail draws, from the booking alone (no actions field on the DTO).
public enum BookingDetailRules {
    /// Where the status sits on its service's five-step path (nil off it: cancelled, no-show, return and custody).
    static func position(_ status: String, _ service: ServiceType) -> Int? {
        service == .passenger ? PassengerStatus.position(status) : StatusLadder.position(status)
    }

    /// The bar's share icon (design `!cancelled && s < 3`): until the parcel is delivered / the passenger has arrived.
    /// The server still decides (`grant_too_early`, finished) and its refusal is said as a toast.
    public static func canShare(_ status: String, service: ServiceType) -> Bool {
        guard let position = position(status, service) else { return false }
        return position < 3
    }

    /// The map pill's dot is green only while the service runs (the tracking window can be open). It never says a
    /// point is fresh - that is the tracking screen's job (§10.5: no false "GPS faol").
    public static func liveDot(_ status: String) -> Bool {
        ["in_transit", "picked_up", "onboard"].contains(status)
    }

    /// The five dots under the badge: how far the booking got, or the cancelled picture (all grey, a red cross on the
    /// second dot). Nil for the off-path statuses (return, custody), which show only the badge.
    public struct Tracker: Equatable, Sendable {
        public static let count = 5
        public let current: Int?
        public let cancelled: Bool
    }

    public static func tracker(_ status: String, service: ServiceType) -> Tracker? {
        if status == "cancelled" || status == "no_show" { return Tracker(current: nil, cancelled: true) }
        return position(status, service).map { Tracker(current: $0, cancelled: false) }
    }

    /// The coloured boxes under the sheet card, in the design's order.
    public enum Notice: Equatable, Sendable {
        /// Pochta `in_transit`: "Haydovchi yo'lda." (info)
        case onTheWay
        /// Pochta `delivered`: "Posilka yetkazildi." (ok) - the operator's record; nothing for the client to confirm (Q139).
        case delivered
        /// Taksi `arrived`: "Yetib keldingiz." (ok)
        case arrived
        /// "Bekor qilindi: Siz · 27.09, 14:30 · Rejalarim o'zgardi" (err)
        case cancelled(ClientBookingDTO.Cancelled)
        /// Q7: the driver reported a no-show; an operator decides (warn).
        case noShowPending
        /// The client blocked this driver (`GET /blocks`): "Haydovchi bloklangan." (warn) - the booking goes on.
        case blocked

        public var tone: Tone {
            switch self {
            case .onTheWay: .blue
            case .delivered, .arrived: .ok
            case .cancelled: .err
            case .noShowPending, .blocked: .warn
            }
        }
    }

    public static func notices(_ booking: ClientBookingDTO, blocked: Bool) -> [Notice] {
        var out: [Notice] = []
        let status = booking.serviceStatus
        if let cancelled = booking.cancelled, status == "cancelled" || status == "no_show" {
            out.append(.cancelled(cancelled))
        } else if booking.serviceType == .parcel && (status == "in_transit" || status == "picked_up") {
            out.append(.onTheWay)
        } else if booking.serviceType == .parcel && status == "delivered" {
            out.append(.delivered)
        } else if booking.serviceType == .passenger && status == "arrived" {
            out.append(.arrived)
        }
        if booking.noShowReview?.status == "pending" { out.append(.noShowPending) }
        if blocked { out.append(.blocked) }
        return out
    }

    /// The driver's phone as the card and the bar's call button show it (Q44/Q142, 24 h after the end): open, not
    /// yet open, or closed for good (the booking is over and the server hides it again - "Yopilgan").
    public enum Phone: Equatable, Sendable {
        case visible(String)
        case locked
        case closed
    }

    public static func phone(_ booking: ClientBookingDTO) -> Phone {
        if let phone = DriverReveal.of(booking)?.phone { return .visible(phone) }
        return BookingActions.of(booking.serviceStatus).terminal ? .closed : .locked
    }

    /// The toast for a tap on the grey call button: closed for good, or when it opens - a passenger at boarding
    /// (Q44), a parcel when the trip departs (Q142; the design's "posilka olib ketilganda" is not the rule).
    public static func callRefusalKey(_ phone: Phone, service: ServiceType) -> String? {
        switch phone {
        case .visible: nil
        case .closed: "client.booking.callClosed"
        case .locked: service == .passenger ? "client.booking.callLockedTaxi" : "client.booking.callLockedParcel"
        }
    }

    /// The chat button's red count: messages the server counts minus those the phone had when the chat was last
    /// left (no unread count exists on the server - BLOCKED; never negative).
    public static func unread(messageCount: Int?, seen: Int) -> Int {
        max(0, (messageCount ?? 0) - max(0, seen))
    }

    /// `JT` from "Jasur Toshmatov", `J` from "Jasur" (the DTO carries the first name only).
    public static func initials(_ name: String) -> String {
        let words = name.split(whereSeparator: { $0.isWhitespace }).prefix(2)
        let letters = words.compactMap(\.first).map { String($0).uppercased() }.joined()
        return letters.isEmpty ? "?" : letters
    }

    /// "Haydovchini baholang" with five stars: only once the booking is completed and not yet rated (the design ties
    /// it to the cash block before the end - not followed: no rating before `completed`).
    public static func showsRatingCard(_ status: String, rated: Bool) -> Bool {
        BookingActions.of(status).canRate && !rated
    }

    /// `★★★★ (4 / 5)` - the stars just sent.
    public static func starsText(_ stars: Int) -> String {
        let n = min(max(stars, 1), 5)
        return "\(String(repeating: "★", count: n)) (\(n) / 5)"
    }

    /// The word under the rating stars: "Yulduzni bosing" until one is chosen, then Yomon ... A'lo.
    public static func starLabelKey(_ stars: Int) -> String {
        (1...5).contains(stars) ? "client.booking.rateLabel\(stars)" : "client.booking.rateTapStar"
    }

    /// `5 kg gacha` from the category's grams (a whole number when it is one, else one decimal with a comma).
    public static func weightText(grams: Int) -> String {
        let kg = Double(grams) / 1000
        if kg == kg.rounded() { return String(Int(kg)) }
        return String(format: "%.1f", kg).replacingOccurrences(of: ".", with: ",")
    }
}

// MARK: - Chat: what the phone has seen

/// How many messages the booking chat had when this phone last left it (local only: the server has no read marks).
public enum ChatSeen {
    private static func key(_ id: String) -> String { "elchi.chatSeen.\(id)" }

    public static func count(_ bookingId: String, defaults: UserDefaults = .standard) -> Int {
        defaults.integer(forKey: key(bookingId))
    }

    public static func mark(_ bookingId: String, count: Int, defaults: UserDefaults = .standard) {
        guard count > Self.count(bookingId, defaults: defaults) else { return }
        defaults.set(count, forKey: key(bookingId))
    }
}

// MARK: - Amendment form (tap to validate)

/// "Taklif yuborish" is always tappable (design): a tap with a missing price, the current price again, or a reason
/// shorter than three characters says what is wrong on the field instead.
public enum AmendmentForm {
    public enum Problem: Equatable, Sendable {
        case priceMissing, noChange, reasonShort

        /// The sentence under the field (`listingOwner.invalid.price`, `client.amendment.noChange`,
        /// `client.booking.amendReasonRequired`).
        public var key: String {
            switch self {
            case .priceMissing: "listingOwner.invalid.price"
            case .noChange: "client.amendment.noChange"
            case .reasonShort: "client.booking.amendReasonRequired"
            }
        }
    }

    public static let maxPriceDigits = 8
    public static let maxReason = 120

    public static func validate(priceMinor: Int, currentUnitMinor: Int, reason: String) -> Problem? {
        if priceMinor <= 0 { return .priceMissing }
        if priceMinor == currentUnitMinor { return .noChange }
        if reason.trimmingCharacters(in: .whitespacesAndNewlines).count < 3 { return .reasonShort }
        return nil
    }
}

// MARK: - Tracking: the closed window and the freshness notes

public enum TrackingCard {
    /// The closed-window card: its title key and where its text comes from. A cancelled booking says so; a finished
    /// one says live location is closed; anything else has not started. The text is the server's reason
    /// (`trackingWindow.*`) - the window is the server's (Taksi opens 30 min before pickup), never guessed from status.
    public static func closedTitleKey(reason: String, bookingStatus: String?) -> String {
        if bookingStatus == "cancelled" || bookingStatus == "no_show" { return "client.tracking.bookingCancelled" }
        switch reason {
        case "booking_finished", "trip_finished", "feature_off": return "client.tracking.liveClosed"
        default: return "client.tracking.notStarted"
        }
    }

    /// The note under the map: delayed (with the point's real age in minutes, at least one), lost, or no point yet.
    public enum Note: Equatable, Sendable {
        case none
        case delayed(minutes: Int)
        case lost
        case noData
    }

    public static func note(_ freshness: TrackingFreshness, capturedAt: Date?, now: Date) -> Note {
        switch freshness {
        case .fresh: return .none
        case .delayed:
            let age = capturedAt.map { now.timeIntervalSince($0) } ?? 60
            return .delayed(minutes: max(1, Int(age / 60)))
        case .lost: return .lost
        default: return .noData
        }
    }
}
