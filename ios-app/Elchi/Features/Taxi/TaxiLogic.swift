import Foundation

// Taksi (passenger) pure logic: the rollout gate (K7/Q5/Q89/Q91), the seat picker, the request body, the seat-count
// edit (Q145), the booking's passenger states on both sides - boarding code and its reissue (Q75), "Keldim", board,
// drop-off, the no-show report (Q7), the cash record (Q78) and the client's own completion. No views, no network.

// MARK: - The rollout gate

/// Everything new about passenger is behind the effective `passenger_enabled` flag (production keeps it off until the
/// legal review, K7/Q5). A failed read counts as closed (Q26). Bookings that already exist stay visible and operable
/// whatever the flag says (Q91: the flag closes only the way *into* a new request).
public enum PassengerGate {
    /// The Taksi / Pochta segment on the client home and the Taksi toggle in the driver feed.
    public static func modeVisible(_ flags: EffectiveFlagValuesDTO?) -> Bool { flags?.passengerEnabled == true }

    /// Whether the chosen service is open where the person is going (nil while the flags are unknown).
    public static func open(_ flags: EffectiveFlagValuesDTO?, mode: ServiceType) -> Bool? {
        guard let flags else { return nil }
        return mode == .passenger ? flags.passengerEnabled : flags.parcelEnabled
    }

    /// "Yo'nalishni ko'rish": a direction the server found AND the chosen service open on its corridor.
    public static func canViewRoute(directionReady: Bool, flags: EffectiveFlagValuesDTO?, mode: ServiceType) -> Bool {
        directionReady && open(flags, mode: mode) == true
    }

    /// The red line under the button: the chosen service is closed here (known, not merely unknown).
    public static func closedKey(_ flags: EffectiveFlagValuesDTO?, mode: ServiceType) -> String? {
        guard open(flags, mode: mode) == false else { return nil }
        return mode == .passenger ? "home.passengerClosed" : "home.parcelClosed"
    }

    /// Flags as read: a failed read closes everything.
    public static let closed = EffectiveFlagValuesDTO(driverListingEnabled: false, parcelEnabled: false, passengerEnabled: false,
                                                      trackingEnabled: false)
}

// MARK: - The seat picker

/// A passenger seat in a normal sedan, in reading order. The *count* is what the request carries (`seat_count`): there
/// is no seat map in the contract, so the picture never reserves a seat (`seatPicker.seatNotReserved`).
public enum CabinSeat: String, CaseIterable, Hashable, Sendable {
    case front, rearLeft, rearMiddle, rearRight

    public var labelKey: String { "seatPicker.\(rawValue)" }
}

public enum SeatPicker {
    /// The cabin's passenger seats (the picture's cap; the edit form allows up to 8 for a minibus).
    public static let maxSeats = CabinSeat.allCases.count
    /// One person, on the rear right (the design's and the web's starting picture).
    public static let defaultSeats: [CabinSeat] = [.rearRight]

    /// Toggles a seat, keeping the order they were marked in; the last one cannot be taken away (a request for nobody
    /// is not a request).
    public static func toggle(_ seat: CabinSeat, in selected: [CabinSeat]) -> [CabinSeat] {
        if let index = selected.firstIndex(of: seat) {
            guard selected.count > 1 else { return selected }
            var next = selected
            next.remove(at: index)
            return next
        }
        return selected + [seat]
    }

    /// The small number on a marked seat (1-based), nil for an unmarked one.
    public static func order(of seat: CabinSeat, in selected: [CabinSeat]) -> Int? {
        selected.firstIndex(of: seat).map { $0 + 1 }
    }

    /// The first seats in reading order: how a count turns back into a picture (a draft restored, a default of 1).
    public static func seats(count: Int) -> [CabinSeat] {
        Array(CabinSeat.allCases.prefix(min(max(count, 1), maxSeats)))
    }
}

// MARK: - Money

public enum PassengerMoney {
    /// The total a per-seat price makes for `seats` people (the server's `per_seat` x quantity).
    public static func total(seats: Int, unitMinor: Int) -> Int { max(seats, 0) * max(unitMinor, 0) }

    /// Whether a listing, offer or booking is priced per seat for more than one person (worth the "n × unit" line).
    public static func perSeat(_ basis: PriceBasis?) -> Bool { basis == .perSeat }
}

// MARK: - The request

/// Everything a passenger request needs: both ends (Q88), the window, the number of people and the price per person.
/// Contacts, parcel and photo steps do not exist for a passenger.
public struct PassengerRequestDraft: Sendable {
    public var pickup: PlaceEnd
    public var dropoff: PlaceEnd
    public var windowStart: Date
    public var windowEnd: Date
    public var seats: Int
    public var unitPriceMinor: Int
    public var comment: String

    public init(pickup: PlaceEnd, dropoff: PlaceEnd, windowStart: Date, windowEnd: Date, seats: Int, unitPriceMinor: Int, comment: String = "") {
        self.pickup = pickup
        self.dropoff = dropoff
        self.windowStart = windowStart
        self.windowEnd = windowEnd
        self.seats = seats
        self.unitPriceMinor = unitPriceMinor
        self.comment = comment
    }

    public var totalMinor: Int { PassengerMoney.total(seats: seats, unitMinor: unitPriceMinor) }

    /// `POST /listings`: a passenger request between two marked places, priced per seat, cash. Only the counts in this
    /// version (no children, baggage or amenities): `seat_count == adults`.
    public func listingCreate() -> ListingCreate {
        let text = comment.trimmingCharacters(in: .whitespacesAndNewlines)
        return ListingCreate(
            comment: text.isEmpty ? nil : text,
            currency: .uzs,
            departureWindowEnd: DepartureWindow.iso(windowEnd),
            departureWindowStart: DepartureWindow.iso(windowStart),
            destinationPoint: Self.point(dropoff),
            kind: .request,
            originPoint: Self.point(pickup),
            passenger: PassengerDetails(adults: seats, seatCount: seats),
            paymentMethod: .cash,
            priceBasis: .perSeat,
            serviceType: .passenger,
            timezone: DepartureWindow.timeZone.identifier,
            unitPriceMinor: unitPriceMinor)
    }

    private static func point(_ end: PlaceEnd) -> PointEndInput {
        PointEndInput(address: end.address, districtId: end.district.id, lat: end.point.lat, lng: end.point.lng)
    }
}

// MARK: - Seat count edit (Q145)

public enum SeatEdit {
    /// A passenger request's people: 1 to 8 (`listingOwner.invalid.seats`).
    public static let range = 1...8

    /// Only the client's own passenger request, and only while it has no booking (an editable status).
    public static func editable(_ listing: ListingDTO) -> Bool {
        listing.kind == .request && listing.serviceType == .passenger && listing.passenger != nil
    }

    /// The whole passenger block with the new count (a PATCH replaces the block, so it travels complete). Children
    /// stay as they were; the adults are the rest.
    public static func block(_ current: PassengerDetails, seats: Int) -> PassengerDetails {
        var next = current
        next.seatCount = seats
        next.adults = max(seats - (current.children ?? 0), 0)
        return next
    }
}

// MARK: - Booking status (both sides)

public enum PassengerStatus {
    /// confirmed -> awaiting_pickup -> onboard -> arrived -> completed (no_show / cancelled off the line).
    public static let ladder = ["status.confirmed", "app.progress.driverAtStop", "status.onboard", "status.arrived", "app.progress.completed"]

    public static func position(_ status: String) -> Int? {
        switch status {
        case "confirmed": 0
        case "awaiting_pickup": 1
        case "onboard": 2
        case "arrived": 3
        case "completed": 4
        default: nil
        }
    }

    /// `bookings.rules.STARTED_STATUSES` for a passenger: the fare is due, the cash record opens (web `CASH_RECORDABLE`).
    public static let cashRecordable: Set<String> = ["onboard", "arrived", "completed"]
}

// MARK: - The client's passenger booking

/// What the client's passenger booking shows and allows beyond the shared (parcel) actions.
public struct ClientTaxiActions: Equatable, Sendable {
    /// The boarding code is shown (and may be reissued) until the passenger is aboard.
    public let showCode: Bool
    /// "Naqd to'lov qaydi" (onboard, arrived, completed).
    public let cash: Bool
    /// "Manzilga yetib keldim": only once the driver dropped the passenger off.
    public let canComplete: Bool
    /// The driver reported a no-show; an operator decides (Q7). Only an operator cancels meanwhile.
    public let noShowPending: Bool

    public static func of(_ booking: ClientBookingDTO) -> ClientTaxiActions {
        guard booking.serviceType == .passenger else {
            return ClientTaxiActions(showCode: false, cash: false, canComplete: false, noShowPending: false)
        }
        let status = booking.serviceStatus
        return ClientTaxiActions(showCode: status == "confirmed" || status == "awaiting_pickup",
                                 cash: PassengerStatus.cashRecordable.contains(status),
                                 canComplete: status == "arrived",
                                 noShowPending: booking.noShowReview?.status == "pending")
    }
}

// MARK: - Boarding code reissue (Q75: 2 minutes apart, 3 per 24 hours)

public enum CodeReissue {
    /// The boarding code among the booking's codes (the endpoint is empty once the passenger is aboard or it ended).
    public static func boarding(_ codes: BookingCodesDTO?) -> BookingCodeDTO? {
        codes?.codes.first { $0.kind == .boardingCode }
    }

    /// `482916` -> `482 916` (read aloud in two halves).
    public static func spaced(_ code: String) -> String {
        guard code.count == 6 else { return code }
        return "\(code.prefix(3)) \(code.suffix(3))"
    }

    /// When the next reissue is allowed, from `PROOF_REISSUE_LIMITED {retry_after_s, reissues_left}`.
    public struct Wait: Equatable, Sendable {
        public let until: Date
        /// No reissues left today: the long wait ("Bugungi chegara tugadi").
        public let dailyLimit: Bool
    }

    public static func wait(_ error: Error, now: Date = Date()) -> Wait? {
        guard let error = error as? APIError, error.code == "PROOF_REISSUE_LIMITED" else { return nil }
        let seconds: Double = if case .number(let value)? = error.details?["retry_after_s"] { value } else { 120 }
        let left: Int? = if case .number(let value)? = error.details?["reissues_left"] { Int(value) } else { nil }
        return Wait(until: now.addingTimeInterval(max(1, seconds)), dailyLimit: left == 0)
    }

    /// The wait sentence for the time still left: `reissue.waitHours` on the daily limit, else `reissue.waitMinutes`;
    /// nil once the time has passed (the button works again).
    public static func waitText(_ wait: Wait, now: Date = Date()) -> (key: String, values: [(String, Int)])? {
        let left = Int(wait.until.timeIntervalSince(now).rounded(.up))
        guard left > 0 else { return nil }
        if wait.dailyLimit {
            let minutes = (left + 59) / 60
            return ("reissue.waitHours", [("hours", minutes / 60), ("minutes", minutes % 60)])
        }
        return ("reissue.waitMinutes", [("minutes", left / 60), ("seconds", left % 60)])
    }
}

// MARK: - The driver's passenger booking

/// What the driver may do with a passenger booking: "Keldim" until it was sent (allowed in confirmed and
/// awaiting_pickup - the web hides it in awaiting_pickup), the boarding code + "Yo'lovchini chiqardim" while the
/// passenger is awaited, "Mijoz kelmadi" (see `NoShowGate`), "Yo'lovchini tushirdim" once aboard, and the cash record.
public struct DriverTaxiActions: Equatable, Sendable {
    public let canArrive: Bool
    public let canBoard: Bool
    public let canDropOff: Bool
    /// "Mijoz kelmadi" is shown (enabled or not - see `NoShowGate`).
    public let showNoShow: Bool
    public let noShowPending: Bool
    public let cash: Bool

    public static func of(_ status: String, arrivedSent: Bool, noShowReview: String?) -> DriverTaxiActions {
        let pending = noShowReview == "pending"
        return DriverTaxiActions(canArrive: DriverBookingActions.preService.contains(status) && !arrivedSent,
                                 canBoard: status == "awaiting_pickup",
                                 canDropOff: status == "onboard",
                                 showNoShow: status == "awaiting_pickup" && !pending,
                                 noShowPending: status == "awaiting_pickup" && pending,
                                 cash: PassengerStatus.cashRecordable.contains(status))
    }
}

/// "Yo'lovchini chiqardim" refusals, in the terms the screen acts on.
public enum BoardRefusal: Equatable, Sendable {
    /// `PROOF_INVALID {attempts_left}`: "Kod noto'g'ri. Yana N ta urinish qoldi."
    case attemptsLeft(Int)
    /// `PROOF_ATTEMPTS_EXCEEDED`: an operator reissues the code.
    case attemptsExceeded
    /// `TRIP_NOT_STARTED`: start boarding on the trip first (a link to it).
    case tripNotStarted
    case other

    public static func of(_ error: Error) -> BoardRefusal {
        guard let error = error as? APIError else { return .other }
        switch error.code {
        case "PROOF_INVALID":
            if case .number(let left)? = error.details?["attempts_left"] { return .attemptsLeft(Int(left)) }
            return .attemptsLeft(0)
        case "PROOF_ATTEMPTS_EXCEEDED": return .attemptsExceeded
        case "TRIP_NOT_STARTED": return .tripNotStarted
        default: return .other
        }
    }

    /// A code the driver can send: six digits.
    public static func validCode(_ text: String) -> Bool { text.count == 6 && text.allSatisfy { $0.isASCII && $0.isNumber } }

    /// What is typed, kept to six digits.
    public static func digits(_ typed: String) -> String { String(typed.filter { $0.isASCII && $0.isNumber }.prefix(6)) }
}

// MARK: - No-show (Q7)

/// "Mijoz kelmadi" opens only after the driver said "Keldim" and waited: from the later of the arrival and the
/// pickup window's start, plus the trip's announced wait (10 minutes unless the trip says otherwise) - the server's
/// `check_no_show_report`. The button shows from when it unlocks.
public enum NoShowGate {
    public static let defaultWaitMinutes = 10

    public static func unlocksAt(arrivedAt: Date?, windowStart: Date?, waitMinutes: Int = defaultWaitMinutes) -> Date? {
        guard let arrivedAt else { return nil }
        let from = max(arrivedAt, windowStart ?? arrivedAt)
        return from.addingTimeInterval(TimeInterval(max(0, waitMinutes) * 60))
    }

    public static func available(arrivedAt: Date?, windowStart: Date?, waitMinutes: Int = defaultWaitMinutes, now: Date = Date()) -> Bool {
        guard let at = unlocksAt(arrivedAt: arrivedAt, windowStart: windowStart, waitMinutes: waitMinutes) else { return false }
        return now >= at
    }
}

/// How the driver tried to reach the client. The contract's channel is free text documented as
/// `chat | quick_reply | arrived_signal | other`: a phone call is not one of them, so it travels as `other`.
public enum NoShowChannel: String, CaseIterable, Hashable, Sendable {
    case chat, call

    public var wire: String { self == .chat ? "chat" : "other" }
    public var labelKey: String { "driver.noShow.channel.\(rawValue)" }
}

public enum NoShowReport {
    /// `report_no_show {expected_version, contact_attempts:[{at, channel}], observed_at}`; nil without a channel (the
    /// server needs at least one attempt).
    public static func body(version: Int, channels: Set<NoShowChannel>, now: Date = Date()) -> BookingActionRequest? {
        guard !channels.isEmpty else { return nil }
        let at = DepartureWindow.iso(now)
        let attempts = NoShowChannel.allCases.filter(channels.contains).map { ContactAttemptInput(at: at, channel: $0.wire) }
        return BookingActionRequest(contactAttempts: attempts, expectedVersion: version, observedAt: at)
    }

    /// The sentence for a refusal: `NO_SHOW_NOT_ALLOWED {reason}` -> `driver.noShow.reason.<reason>` (the generic one
    /// for a reason the dictionary lacks), `NO_SHOW_REVIEW_PENDING` -> the pending text; nil for anything else.
    public static func refusalKey(_ error: Error, known: (String) -> Bool) -> String? {
        guard let error = error as? APIError else { return nil }
        switch error.code {
        case "NO_SHOW_NOT_ALLOWED":
            if case .string(let reason)? = error.details?["reason"], known("driver.noShow.reason.\(reason)") {
                return "driver.noShow.reason.\(reason)"
            }
            return "error.NO_SHOW_NOT_ALLOWED"
        case "NO_SHOW_REVIEW_PENDING":
            return "driver.noShow.pending"
        default:
            return nil
        }
    }
}

// MARK: - Cash record (B10, Q78)

/// The cash record as one side sees it. The fare is cash between two people (§9): nothing here moves money; one side
/// records the handover, the other confirms or contests it, a contested one goes to the operator.
public enum CashState: Equatable, Sendable {
    /// Nothing recorded yet: this side may record it.
    case unpaid
    /// This side recorded it; the other side has not answered.
    case reportedByMe(CashReceiptDTO)
    /// The other side recorded it: confirm or contest.
    case reportedByOther(CashReceiptDTO)
    case acknowledged
    case contested

    public static func of(cashStatus: String?, receipt: CashReceiptDTO?, side: String) -> CashState {
        switch cashStatus {
        case "reported_paid":
            guard let receipt else { return .unpaid }
            return receipt.reportedBySide == side ? .reportedByMe(receipt) : .reportedByOther(receipt)
        case "acknowledged": return .acknowledged
        case "contested": return .contested
        default: return .unpaid
        }
    }
}

public enum CashRecord {
    /// A note is required when the amount differs from what is due (`VALIDATION_ERROR {field: note}` otherwise).
    public static func noteRequired(amountMinor: Int, dueMinor: Int) -> Bool { amountMinor > 0 && amountMinor != dueMinor }

    public static func canReport(amountMinor: Int, dueMinor: Int, note: String) -> Bool {
        amountMinor > 0 && (!noteRequired(amountMinor: amountMinor, dueMinor: dueMinor)
                            || !note.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
    }

    public static func report(version: Int, amountMinor: Int, dueMinor: Int, note: String, now: Date = Date()) -> CashReceiptReport? {
        guard canReport(amountMinor: amountMinor, dueMinor: dueMinor, note: note) else { return nil }
        let text = note.trimmingCharacters(in: .whitespacesAndNewlines)
        return CashReceiptReport(amountMinor: amountMinor, expectedVersion: version, note: text.isEmpty ? nil : text,
                                 reportedAt: DepartureWindow.iso(now))
    }

    /// Contesting needs a comment (the operator reads it); acknowledging does not.
    public static func contest(_ receipt: CashReceiptDTO, comment: String) -> CashReceiptDecision? {
        let text = comment.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        return CashReceiptDecision(comment: text, expectedVersion: receipt.version)
    }

    public static func acknowledge(_ receipt: CashReceiptDTO) -> CashReceiptDecision {
        CashReceiptDecision(expectedVersion: receipt.version)
    }
}
