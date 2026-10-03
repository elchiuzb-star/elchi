import Foundation

// MARK: - Server time

/// The API writes instants as ISO 8601 in UTC (`Z`, sometimes with fractions); v1 legacy rows carry naive
/// timestamps, read here as UTC.
public enum ServerTime {
    public static func parse(_ text: String?) -> Date? {
        guard var text, !text.isEmpty else { return nil }
        if let date = withFractions.date(from: text) ?? plain.date(from: text) { return date }
        // Legacy naive `2026-08-04T10:15:00(.123456)`: no zone at all.
        if !text.hasSuffix("Z") && !text.contains("+") && text.count >= 19 { text += "Z" }
        return withFractions.date(from: text) ?? plain.date(from: text)
    }

    nonisolated(unsafe) private static let withFractions: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    nonisolated(unsafe) private static let plain: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()
}

// MARK: - Negotiation (port of mobile-app/src/app/auction.ts, with the Stage 03 fixes)

/// What the client may do with one negotiation thread right now. Pure: the thread the server sent plus the clock.
///
/// Fixes over the web module: an offer whose `expires_at` has passed is closed here at once (the server would refuse
/// it anyway), and "Boshqa narx" is offered only while the client still has a price revision left (the web showed it
/// and let the server refuse).
public struct NegotiationActions: Equatable, Sendable {
    /// The thread is live and its current version can still be answered.
    public let open: Bool
    /// The driver spoke last, so the answer is the client's.
    public let theirTurn: Bool
    /// AC05: only a version the other side wrote.
    public let canAccept: Bool
    public let canReject: Bool
    public let canCounter: Bool
    /// The client can take back what it wrote, never what the driver wrote.
    public let canWithdraw: Bool
    /// Price revisions this side still has (`price_revisions_left.client`).
    public let revisionsLeft: Int
    /// The server still says open, but the offer's time is over (`now >= expires_at`).
    public let expiredByClock: Bool

    static let closed = NegotiationActions(open: false, theirTurn: false, canAccept: false, canReject: false, canCounter: false,
                                           canWithdraw: false, revisionsLeft: 0, expiredByClock: false)

    public static func of(_ thread: ProposalThreadDTO, now: Date = Date()) -> NegotiationActions {
        guard let version = thread.currentVersion, thread.state == "open", version.status == .active else { return .closed }
        if let expires = ServerTime.parse(version.expiresAt), now >= expires {
            return NegotiationActions(open: false, theirTurn: false, canAccept: false, canReject: false, canCounter: false,
                                      canWithdraw: false, revisionsLeft: 0, expiredByClock: true)
        }
        let theirTurn = version.authorSide != .client
        let left = version.priceRevisionsLeft.client
        return NegotiationActions(open: true, theirTurn: theirTurn, canAccept: theirTurn, canReject: theirTurn,
                                  canCounter: theirTurn && left > 0, canWithdraw: !theirTurn, revisionsLeft: left,
                                  expiredByClock: false)
    }
}

extension ProposalThreadDTO {
    /// The dictionary key for why a closed offer is closed (`proposalStatus.*`): the version's own status, or
    /// "expired" when only the clock closed it.
    func closedStatusKey(now: Date = Date()) -> String {
        let actions = NegotiationActions.of(self, now: now)
        if actions.expiredByClock { return "proposalStatus.expired" }
        if state == "accepted" { return "proposalStatus.accepted" }
        return "proposalStatus.\(currentVersion?.status.rawValue ?? "expired")"
    }

    /// `3` from the server's stable anonymous label "Haydovchi #3" (Q40), so the app can say it in the active
    /// language; nil when the label has another shape.
    var driverNumber: Int? {
        guard let hash = driver.label.lastIndex(of: "#") else { return nil }
        return Int(driver.label[driver.label.index(after: hash)...].trimmingCharacters(in: .whitespaces))
    }
}

/// Time left on an offer, rounded up to the minute (a live countdown never says "0 minutes" while it is still open).
public enum Countdown {
    public static func left(until expires: Date, now: Date = Date()) -> (hours: Int, minutes: Int)? {
        let seconds = expires.timeIntervalSince(now)
        guard seconds > 0 else { return nil }
        let minutes = Int((seconds / 60).rounded(.up))
        return (minutes / 60, minutes % 60)
    }

    /// Whole minutes since an instant (at least 1), for "Eng yangi taklif 12 daqiqa oldin".
    public static func minutesAgo(_ date: Date, now: Date = Date()) -> Int {
        max(1, Int(now.timeIntervalSince(date) / 60))
    }
}

// MARK: - Sorting the offers

public enum OfferSort: String, CaseIterable, Hashable, Sendable {
    case cheapest, fastest, bestRated

    /// Live offers first (they can still be answered), closed ones after; inside each group by the chosen order. Ties
    /// fall back to price, then to the thread id so the order never jumps between refreshes.
    public func sorted(_ threads: [ProposalThreadDTO], now: Date = Date()) -> [ProposalThreadDTO] {
        threads.sorted { a, b in
            let openA = NegotiationActions.of(a, now: now).open, openB = NegotiationActions.of(b, now: now).open
            if openA != openB { return openA }
            switch self {
            case .cheapest:
                break
            case .fastest:
                let startA = ServerTime.parse(a.currentVersion?.pickupWindowStart) ?? .distantFuture
                let startB = ServerTime.parse(b.currentVersion?.pickupWindowStart) ?? .distantFuture
                if startA != startB { return startA < startB }
            case .bestRated:
                let rankA = Self.ratingRank(a.driverSummary), rankB = Self.ratingRank(b.driverSummary)
                if rankA != rankB { return rankA < rankB }
                let countA = a.driverSummary?.ratingCount ?? 0, countB = b.driverSummary?.ratingCount ?? 0
                if countA != countB { return countA > countB }
            }
            let priceA = a.currentVersion?.totalMinor ?? .max, priceB = b.currentVersion?.totalMinor ?? .max
            if priceA != priceB { return priceA < priceB }
            return a.id < b.id
        }
    }

    /// good < new_verified < mixed < low < unknown (the server gives buckets, never a score - never invented).
    static func ratingRank(_ summary: ProposalDriverSummaryDTO?) -> Int {
        switch summary?.ratingBucket {
        case .good: 0
        case .newVerified: 1
        case .mixed: 2
        case .low: 3
        default: 4
        }
    }

    /// The live offer with the lowest total, badged "Eng arzon" - only when there is something to compare it with.
    public static func cheapestOpenId(_ threads: [ProposalThreadDTO], now: Date = Date()) -> String? {
        let open = threads.filter { NegotiationActions.of($0, now: now).open }
        guard open.count >= 2 else { return nil }
        return open.min { ($0.currentVersion?.totalMinor ?? .max, $0.id) < ($1.currentVersion?.totalMinor ?? .max, $1.id) }?.id
    }
}

// MARK: - Owner's listing controls (port of mobile-app/src/app/listingEdit.ts)

public struct OwnerListingActions: Equatable, Sendable {
    public let canPause: Bool
    public let canResume: Bool
    public let canEdit: Bool
    public let canCancel: Bool
    /// Share links exist only for a listing people can still answer (`LISTING_NOT_OPEN` otherwise).
    public let canShare: Bool

    public static func of(_ status: ListingStatus) -> OwnerListingActions {
        let editable = [ListingStatus.draft, .published, .paused].contains(status)
        return OwnerListingActions(canPause: status == .published, canResume: status == .paused, canEdit: editable,
                                   canCancel: editable, canShare: status == .published || status == .paused)
    }
}

/// What the edit form holds: whole so'm as typed, the comment, the window (Tashkent wall clock, as `Date`) and - on a
/// passenger request - the number of people (Q145; empty for anything else).
public struct ListingEditForm: Equatable, Sendable {
    public var priceDigits: String
    public var comment: String
    public var windowStart: Date?
    public var windowEnd: Date?
    public var seats: String

    public init(priceDigits: String, comment: String, windowStart: Date?, windowEnd: Date?, seats: String = "") {
        self.priceDigits = priceDigits
        self.comment = comment
        self.windowStart = windowStart
        self.windowEnd = windowEnd
        self.seats = seats
    }

    /// The form as the listing is now: nothing changed yet.
    public init(listing: ListingDTO) {
        priceDigits = String(listing.unitPriceMinor / 100)
        comment = listing.comment ?? ""
        windowStart = ServerTime.parse(listing.departureWindowStart)
        windowEnd = ServerTime.parse(listing.departureWindowEnd)
        seats = SeatEdit.editable(listing) ? listing.passenger.map { String($0.seatCount) } ?? "" : ""
    }
}

/// The PATCH an edit would send, and what it means. Q20: on a live listing a moved window closes every open offer;
/// price and comment do not. The owner is told before sending, so the diff is computed here the way the server
/// classifies it.
public struct ListingPatchPlan: Equatable, Sendable {
    public var unitPriceMinor: Int?
    /// `""` clears the comment (a nil field is simply not sent).
    public var comment: String?
    public var windowStart: Date?
    public var windowEnd: Date?
    /// Q145: the whole passenger block with the new number of people (the server replaces the block).
    public var passenger: PassengerDetails?
    /// This edit closes the open offers of a published or paused listing.
    public var material = false
    /// Why it cannot be sent as it is: `listingOwner.invalid.<reason>` (price, window_incomplete, window_order,
    /// window_past, seats).
    public var invalid: String?

    public var empty: Bool { unitPriceMinor == nil && comment == nil && windowStart == nil && passenger == nil }

    /// Live listings: where open offers exist that an edit could close (`marketplace.service.LIVE_STATUSES`).
    static let live: [ListingStatus] = [.published, .paused]

    public static func plan(_ listing: ListingDTO, _ form: ListingEditForm, now: Date = Date()) -> ListingPatchPlan {
        var plan = ListingPatchPlan()
        let price = Money.minor(fromSoum: form.priceDigits)
        if price <= 0 {
            plan.invalid = "price"
        } else if price != listing.unitPriceMinor {
            plan.unitPriceMinor = price
        }

        let comment = form.comment.trimmingCharacters(in: .whitespacesAndNewlines)
        if comment != (listing.comment ?? "").trimmingCharacters(in: .whitespacesAndNewlines) { plan.comment = comment }

        // A client request owns its window (a trip offer's comes from the trip - not a client screen).
        if listing.kind == .request {
            if let start = form.windowStart, let end = form.windowEnd {
                if end <= start {
                    plan.invalid = plan.invalid ?? "window_order"
                } else if end <= now {
                    plan.invalid = plan.invalid ?? "window_past"
                } else if start != ServerTime.parse(listing.departureWindowStart) || end != ServerTime.parse(listing.departureWindowEnd) {
                    // The server validates the pair, so both ends travel together.
                    plan.windowStart = start
                    plan.windowEnd = end
                    plan.material = live.contains(listing.status)
                }
            } else {
                plan.invalid = plan.invalid ?? "window_incomplete"
            }
        }

        // Q145 (port of `listingEdit.ts`): a passenger request's people, 1 to 8, until a booking exists. Q20: a new count
        // closes the open offers - no offer is silently stretched to more people.
        if SeatEdit.editable(listing), let current = listing.passenger {
            let seats = Int(form.seats.trimmingCharacters(in: .whitespaces))
            if let seats, SeatEdit.range.contains(seats), seats > (current.children ?? 0) {
                if seats != current.seatCount {
                    plan.passenger = SeatEdit.block(current, seats: seats)
                    plan.material = plan.material || live.contains(listing.status)
                }
            } else {
                plan.invalid = plan.invalid ?? "seats"
            }
        }
        return plan
    }

    /// `PATCH /listings/{id}` body (not idempotent: `expected_version` guards it).
    public func body(expectedVersion: Int) -> ListingPatch {
        ListingPatch(comment: comment, departureWindowEnd: windowEnd.map(DepartureWindow.iso),
                     departureWindowStart: windowStart.map(DepartureWindow.iso), expectedVersion: expectedVersion,
                     passenger: passenger, unitPriceMinor: unitPriceMinor)
    }
}

// MARK: - Share links

/// The design's TTL chips are days; the API takes hours (1...336).
public enum ShareTTL {
    public static let days = [1, 2, 3, 7, 14]
    public static let defaultDays = 2

    public static func hours(days: Int) -> Int { min(max(days * 24, 1), 336) }
}

// MARK: - Status labels and tones

/// A status as the person reads it: a dictionary key, the raw value to show when the key is missing, and the tone
/// of its badge (the badge also carries a dot, so the meaning is not colour-only).
public struct StatusLabel: Equatable, Sendable {
    public let key: String
    public let raw: String
    public let tone: Tone

    /// A listing of the client's (`ListingStatus`).
    public static func listing(_ status: ListingStatus) -> StatusLabel {
        let tone: Tone = switch status {
        case .published: .blue
        case .fulfilled: .ok
        case .cancelled: .err
        default: .gray
        }
        // The client's side of `fulfilled`: its request became a booking ("Bron qilindi", not "Bajarilgan").
        let key = status == .fulfilled ? "client.listing.statusFulfilled" : "status.\(status.rawValue)"
        return StatusLabel(key: key, raw: status.rawValue, tone: tone)
    }

    /// A booking's `service_status`. Parcel `in_transit` is set by the system when the trip departs: "Haydovchi yo'lga
    /// chiqdi"; `delivered` and `completed` are the operator's (Q139/Q144).
    public static func booking(_ service: ServiceType, _ status: String) -> StatusLabel {
        switch (service, status) {
        case (.parcel, "in_transit"), (.parcel, "picked_up"):
            return StatusLabel(key: "parcel.status.driverDeparted", raw: status, tone: .blue)
        case (.parcel, "delivered"):
            return StatusLabel(key: "parcel.progress.deliveredByOperator", raw: status, tone: .ok)
        case (_, "confirmed"), (_, "completed"):
            return StatusLabel(key: "status.\(status)", raw: status, tone: .ok)
        case (_, "awaiting_pickup"):
            return StatusLabel(key: "status.awaiting_pickup", raw: status, tone: .warn)
        case (_, "cancelled"), (_, "no_show"):
            return StatusLabel(key: "status.\(status)", raw: status, tone: .err)
        case (_, "onboard"):
            // Passenger aboard: "Mashinada" (never the raw `onboard`).
            return StatusLabel(key: "status.onboard", raw: status, tone: .blue)
        case (_, "arrived"):
            // Dropped off at the destination: "Yetib keldi" - the passenger completes it (or an operator does).
            return StatusLabel(key: "status.arrived", raw: status, tone: .ok)
        case (_, "return_required"), (_, "returned"), (_, "delivery_failed"):
            let tone: Tone = status == "returned" ? .gray : status == "delivery_failed" ? .err : .warn
            return StatusLabel(key: "tripDetail.service.\(status)", raw: status, tone: tone)
        default:
            return StatusLabel(key: "status.\(status)", raw: status, tone: .gray)
        }
    }

    /// A v1 order status (read-only history).
    public static func legacy(_ status: String) -> StatusLabel {
        let tone: Tone = switch status {
        case "published", "bidding", "in_transit": .blue
        case "accepted", "picked_up": .warn
        case "delivered", "confirmed", "completed": .ok
        case "cancelled", "disputed": .err
        default: .gray
        }
        return StatusLabel(key: "status.\(status)", raw: status, tone: tone)
    }
}

// MARK: - Legacy money

/// v1 prices are DECIMAL so'm (not minor units) and come as a JSON number or a string: `70000`, `"70000.00"`.
public enum LegacyMoney {
    public static func minor(_ value: JSONValue?) -> Int? {
        switch value {
        case .number(let soum)?:
            return soum.isFinite && soum >= 0 ? Int((soum * 100).rounded()) : nil
        case .string(let text)?:
            let trimmed = text.trimmingCharacters(in: .whitespaces)
            guard let soum = Decimal(string: trimmed, locale: Locale(identifier: "en_US_POSIX")), soum >= 0 else { return nil }
            return NSDecimalNumber(decimal: soum * 100).rounding(accordingToBehavior: nil).intValue
        default:
            return nil
        }
    }
}

// MARK: - One Idempotency-Key per action

/// One key per user action (ADR-0005), reused while that same action is retried without a definite answer (no
/// connection, a 5xx) and dropped once the server has decided - success or a business refusal.
@MainActor
final class ActionKeys {
    private var keys: [String: String] = [:]

    func key(_ action: String) -> String {
        if let key = keys[action] { return key }
        let key = UUID().uuidString
        keys[action] = key
        return key
    }

    /// The server answered for sure: the next attempt of this action is a new action.
    func settle(_ action: String, after error: Error? = nil) {
        if let error = error as? APIError, error.code == APIError.network || error.status >= 500 { return }
        keys[action] = nil
    }
}

// MARK: - BOSQICH 03 design: what the listing and offer cards say

/// Line 3 of a listing card: "Yangi taklif: 12 daqiqa oldin" (blue while an open offer exists), "Haydovchi tanlandi",
/// or "E'lon amal qiladi: 02.10 gacha". A closed listing (expired, cancelled) says nothing: its expiry is no news.
enum ListingMeta: Equatable, Sendable {
    case newOffer(Date)
    case driverChosen
    case validUntil(Date)

    static func of(_ listing: ListingDTO, stats: OfferStats?) -> ListingMeta? {
        switch listing.status {
        case .published, .paused:
            if listing.status == .published, let stats, stats.open > 0, let newest = stats.newest { return .newOffer(newest) }
            return ServerTime.parse(listing.expiresAt).map(ListingMeta.validUntil)
        case .fulfilled:
            return .driverChosen
        default:
            return nil
        }
    }

    /// The accent colour: an open offer is waiting for the client.
    var highlighted: Bool {
        if case .newOffer = self { return true }
        return false
    }
}

/// The detail's five-step tracker: "E'lon qilindi · Takliflar · Haydovchi tanlandi · Yo'lda · Yakunlandi". Steps 0-2
/// come from the listing and its threads, 3-4 from the booking made from it (when the orders list has it). An expired
/// or cancelled listing is `dead`: every step grey and the second one a red cross.
struct ListingProgress: Equatable, Sendable {
    static let stepKeys = ["app.orderStatus.published", "client.listing.stepOffers", "listingBids.driverChosen", "status.in_transit",
                           "app.progress.completed"]

    let current: Int
    let dead: Bool

    static func of(_ listing: ListingDTO, hasThreads: Bool, bookingStatus: String?) -> ListingProgress {
        switch listing.status {
        case .expired, .cancelled:
            return ListingProgress(current: 0, dead: true)
        case .fulfilled:
            switch bookingStatus {
            case "completed"?: return ListingProgress(current: 4, dead: false)
            case "in_transit"?, "picked_up"?, "delivered"?, "onboard"?, "arrived"?: return ListingProgress(current: 3, dead: false)
            default: return ListingProgress(current: 2, dead: false)
            }
        default:
            return ListingProgress(current: hasThreads ? 1 : 0, dead: false)
        }
    }
}

/// The one badge an offer card carries. The driver's answer to the client's counter wins; then the badge of the chosen
/// sort ("Eng arzon" also draws the brand border); then "Yangi" for an offer this phone has not shown before.
enum OfferBadge: Equatable, Sendable {
    case cheapest, fastest, bestRated, counter, new

    var key: String {
        switch self {
        case .cheapest: "client.listingBids.cheapest"
        case .fastest: "client.offers.badgeFastest"
        case .bestRated: "ratingBucket.good"
        case .counter: "client.offers.badgeCounter"
        case .new: "client.notifications.new"
        }
    }

    var tone: Tone {
        switch self {
        case .cheapest: .ok
        case .fastest, .bestRated: .blue
        case .counter: .warn
        case .new: .err
        }
    }

    /// Badges for every thread of one board. Sort badges compare live offers only, and only when there are two or more
    /// (a lone offer is not "the cheapest" of anything); "Yaxshi baholangan" is the server's `good` bucket, never a score.
    static func badges(_ threads: [ProposalThreadDTO], sort: OfferSort, unseen: Set<String>, now: Date = Date()) -> [String: OfferBadge] {
        let open = threads.filter { NegotiationActions.of($0, now: now).open }
        var sortTargets: Set<String> = []
        switch sort {
        case .cheapest:
            if let id = OfferSort.cheapestOpenId(threads, now: now) { sortTargets = [id] }
        case .fastest:
            if open.count >= 2, let first = OfferSort.fastest.sorted(open, now: now).first,
               ServerTime.parse(first.currentVersion?.pickupWindowStart) != nil {
                sortTargets = [first.id]
            }
        case .bestRated:
            sortTargets = Set(open.filter { $0.driverSummary?.ratingBucket == .good }.map(\.id))
        }
        var out: [String: OfferBadge] = [:]
        for thread in open {
            if thread.driverCountered(now: now) {
                out[thread.id] = .counter
            } else if sortTargets.contains(thread.id) {
                out[thread.id] = sort == .cheapest ? .cheapest : sort == .fastest ? .fastest : .bestRated
            } else if unseen.contains(thread.id) && NegotiationActions.of(thread, now: now).theirTurn {
                out[thread.id] = .new
            }
        }
        return out
    }
}

extension ProposalThreadDTO {
    /// The driver answered the client's counter with a price of its own (revision 1 is the driver's first offer).
    func driverCountered(now: Date = Date()) -> Bool {
        guard let version = currentVersion else { return false }
        return NegotiationActions.of(self, now: now).theirTurn && version.revision > 1
    }

    /// Why a closed offer is closed, in the design's words (`status_reason` first, then the version's status).
    /// `accepted` is not "closed" but the agreed one.
    func closedReasonKey(now: Date = Date()) -> String {
        if state == "accepted" || currentVersion?.status == .accepted { return "client.amendment.statusAccepted" }
        if NegotiationActions.of(self, now: now).expiredByClock { return "status.expired" }
        switch currentVersion?.statusReason {
        case "ttl_expired"?: return "status.expired"
        case "rejected"?: return "amendment.rejected"
        case "withdrawn"?: return "client.offers.closed.withdrawn"
        case "demand_fulfilled"?: return "client.offers.closed.demandFulfilled"
        case "listing_closed"?: return "notification.listing.cancelled.title"
        case "listing_changed"?: return "client.offers.closed.listingChanged"
        default: break
        }
        switch currentVersion?.status {
        case .rejected?: return "amendment.rejected"
        case .withdrawn?: return "client.offers.closed.withdrawn"
        default: return "status.expired"
        }
    }

    /// Identifies one driver-written version: a new revision from the same driver is news again.
    var seenKey: String? {
        guard let version = currentVersion, version.authorSide != .client else { return nil }
        return "\(id):\(version.revision)"
    }
}

/// "Yangi" on an offer card: the live driver versions this phone has not shown before. Remembered per listing in the
/// app's defaults (a handful of short strings); a listing opened afresh from the list shows its news once.
enum OfferSeen {
    static let limit = 200

    /// Thread ids whose current driver version is not in `seen`.
    static func fresh(_ threads: [ProposalThreadDTO], seen: Set<String>, now: Date = Date()) -> Set<String> {
        Set(threads.filter { thread in
            guard NegotiationActions.of(thread, now: now).open, let key = thread.seenKey else { return false }
            return !seen.contains(key)
        }.map(\.id))
    }

    private static func defaultsKey(_ listingId: String) -> String { "elchi.offers.seen.\(listingId)" }

    @MainActor static func load(_ listingId: String) -> Set<String> {
        Set(UserDefaults.standard.stringArray(forKey: defaultsKey(listingId)) ?? [])
    }

    @MainActor static func remember(_ threads: [ProposalThreadDTO], listingId: String) {
        let known = UserDefaults.standard.stringArray(forKey: defaultsKey(listingId)) ?? []
        let added = threads.compactMap(\.seenKey).filter { !known.contains($0) }
        guard !added.isEmpty else { return }
        UserDefaults.standard.set(Array((known + added).suffix(limit)), forKey: defaultsKey(listingId))
    }
}

/// The client's counter as typed: tap-to-validate ("Narxni kiriting.", "Haydovchi narxidan farqli narx kiriting.").
/// The counter is a unit price (per seat for a passenger request), compared with the driver's unit price.
enum CounterCheck {
    static func error(priceMinor: Int, driverUnitMinor: Int) -> String? {
        if priceMinor <= 0 { return "listingOwner.invalid.price" }
        if priceMinor == driverUnitMinor { return "client.offers.counterSame" }
        return nil
    }
}

/// `Jo'nash` / `Oxirgi muddat` places: the first part of the address ("Chilonzor, 9-kvartal" -> "Chilonzor").
enum PlaceShort {
    static func of(_ text: String) -> String {
        let first = text.split(separator: ",", maxSplits: 1).first.map { $0.trimmingCharacters(in: .whitespaces) } ?? text
        return first.isEmpty ? text : first
    }
}
