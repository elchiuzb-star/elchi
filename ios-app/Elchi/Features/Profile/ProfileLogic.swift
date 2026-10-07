import Foundation

// MARK: - Inbox (port of mobile-app/src/app/inbox.ts)

/// Where a notification leads. The server sends a `link` such as `/bookings/bkg_…` (never text); an item whose link
/// this app has no screen for stays where it is.
public enum InboxTarget: Equatable, Sendable {
    case booking(String, chat: Bool)
    case listing(String)
    case proposal(String)
    case trip(String)
    case supportThread(String)
    /// A driver's top-up was decided (`/wallet`).
    case wallet
}

public enum Inbox {
    nonisolated(unsafe) private static let patterns: [(NSRegularExpression, ([String?]) -> InboxTarget)] = [
        (regex(#"^/bookings/([^/?#]+)(/messages)?/?$"#), { .booking($0[0] ?? "", chat: $0[1] != nil) }),
        (regex(#"^/listings/([^/?#]+)/?$"#), { .listing($0[0] ?? "") }),
        // A proposal's own chat is not opened by this client (Q100): the negotiation is the thread itself.
        (regex(#"^/proposals/([^/?#]+)(/messages)?/?$"#), { .proposal($0[0] ?? "") }),
        (regex(#"^/trips/([^/?#]+)/?$"#), { .trip($0[0] ?? "") }),
        // ADR-0026: an operator answer leads into the person's own support chat.
        (regex(#"^/support-threads/([^/?#]+)/?$"#), { .supportThread($0[0] ?? "") }),
        (regex(#"^/wallet(/[^?#]*)?/?$"#), { _ in .wallet }),
    ]

    private static func regex(_ pattern: String) -> NSRegularExpression {
        try! NSRegularExpression(pattern: pattern) // swiftlint:disable:this force_try
    }

    /// Where an item leads, or nil when it leads nowhere this app has a screen for.
    public static func target(_ link: String?) -> InboxTarget? {
        guard let link else { return nil }
        var path = link.trimmingCharacters(in: .whitespacesAndNewlines)
        path = path.replacingOccurrences(of: #"^https?://[^/]+"#, with: "", options: .regularExpression)
        path = path.replacingOccurrences(of: #"^/api/v2"#, with: "", options: .regularExpression)
        let range = NSRange(path.startIndex..., in: path)
        for (pattern, build) in patterns {
            guard let match = pattern.firstMatch(in: path, range: range) else { continue }
            let groups = (1..<match.numberOfRanges).map { index -> String? in
                Range(match.range(at: index), in: path).map { String(path[$0]) }
            }
            return build(groups)
        }
        return nil
    }

    public static func unreadCount(_ items: [NotificationDTO]) -> Int { items.filter { !$0.isRead }.count }

    /// The title: the server's key when the dictionary knows it, the event's generic key next, "Yangi bildirishnoma"
    /// last - never the raw key, which reads like a bug.
    public static func title(_ item: NotificationDTO, lookup: (String) -> String?) -> String {
        lookup(item.titleKey) ?? lookup("notification.\(item.type).title") ?? lookup("notification.fallback.title") ?? item.type
    }

    /// The body, or "" when neither key is known (the row then shows the title alone).
    public static func body(_ item: NotificationDTO, lookup: (String) -> String?) -> String {
        lookup(item.bodyKey) ?? lookup("notification.\(item.type).body") ?? ""
    }

    /// The item's `params` as `{name}` fillers for the dictionary sentence (strings and numbers only).
    public static func params(_ item: NotificationDTO) -> [(String, Any)] {
        guard case .object(let object) = item.params else { return [] }
        return object.sorted { $0.key < $1.key }.compactMap { key, value in
            switch value {
            case .string(let text): (key, text)
            case .number(let number): (key, number == number.rounded() ? String(Int(number)) : String(number))
            case .bool(let flag): (key, flag ? "true" : "false")
            default: nil
            }
        }
    }
}

/// When a notification came, as the list says it: today `10:24`, yesterday `Kecha, 08:12`, otherwise the date.
public enum InboxTime: Equatable, Sendable {
    case today
    case yesterday
    case earlier(sameYear: Bool)

    public static func of(_ date: Date, now: Date = Date()) -> InboxTime {
        let calendar = DepartureWindow.calendar
        if calendar.isDate(date, inSameDayAs: now) { return .today }
        if let yesterday = calendar.date(byAdding: .day, value: -1, to: now), calendar.isDate(date, inSameDayAs: yesterday) {
            return .yesterday
        }
        return .earlier(sameYear: calendar.component(.year, from: date) == calendar.component(.year, from: now))
    }
}

// MARK: - Profile stats

/// The profile's figures, all derived from v2 (never v1 orders): Jami = the client's parcel requests; Faol = open
/// requests + bookings still under way; Taklif = offers waiting for the client's answer; Yakunlangan = completed
/// bookings; So'nggi = the status of the newest booking or request.
public struct ProfileStats: Equatable, Sendable {
    public let total: Int
    public let active: Int
    public let offers: Int
    public let completed: Int
    public let latest: StatusLabel?

    public static func derive(listings: [ListingDTO], bookings: [ClientBookingDTO], threads: [ProposalThreadDTO],
                              now: Date = Date()) -> ProfileStats {
        let requests = listings.filter { $0.kind == .request && $0.serviceType == .parcel }
        let openRequests = requests.filter { $0.status == .published || $0.status == .paused }.count
        let liveBookings = bookings.filter { !BookingActions.terminalStatuses.contains($0.serviceStatus) }.count
        let waiting = threads.filter { NegotiationActions.of($0, now: now).canAccept }.count
        let completed = bookings.filter { $0.serviceStatus == "completed" }.count

        let newestBooking = bookings.max { (ServerTime.parse($0.createdAt) ?? .distantPast) < (ServerTime.parse($1.createdAt) ?? .distantPast) }
        let newestRequest = requests.max { (ServerTime.parse($0.createdAt) ?? .distantPast) < (ServerTime.parse($1.createdAt) ?? .distantPast) }
        let bookingDate = ServerTime.parse(newestBooking?.createdAt) ?? .distantPast
        let requestDate = ServerTime.parse(newestRequest?.createdAt) ?? .distantPast
        let latest: StatusLabel? = if let newestBooking, bookingDate >= requestDate {
            StatusLabel.booking(newestBooking.serviceType, newestBooking.serviceStatus)
        } else if let newestRequest {
            StatusLabel.listing(newestRequest.status)
        } else {
            nil
        }
        return ProfileStats(total: requests.count, active: openRequests + liveBookings, offers: waiting, completed: completed, latest: latest)
    }
}

extension ProfileStats {
    /// "So'nggi buyurtma" in colour (BOSQICH 05 `lastC`): blue while under way, green once done; other states plain.
    public static func latestTone(_ label: StatusLabel) -> Tone? {
        label.tone == .blue || label.tone == .ok ? label.tone : nil
    }
}

/// "Ism familiya" (BOSQICH 05): at least two letters after trimming, cut at 120 characters while typing (the server
/// takes 255; Android keeps 120). Blank never goes to the server.
public enum NameRule {
    public static let minLetters = 2
    public static let maxLength = 120

    public static func typed(_ raw: String) -> String { String(raw.prefix(maxLength)) }

    public static func isValid(_ name: String) -> Bool {
        name.trimmingCharacters(in: .whitespacesAndNewlines).filter(\.isLetter).count >= minLetters
    }
}

/// Two letters for the avatar: first letters of the first two words of the name, else nothing (the icon is shown).
public enum Initials {
    public static func of(_ name: String?) -> String? {
        let words = (name ?? "").split(whereSeparator: \.isWhitespace).prefix(2)
        let letters = words.compactMap(\.first).map { String($0).uppercased() }.joined()
        return letters.isEmpty ? nil : letters
    }
}

// MARK: - Bonus (port of mobile-app/src/app/promo.ts, the parts the client screen needs)

/// One line of a bonus card: a dictionary key, the amount in minor units, and the hint shown under it when non-zero.
public struct BucketRow: Equatable, Sendable {
    public let key: String
    public let minor: Int
    public let hintKey: String?
}

public enum PromoLogic {
    /// The five states of a discount right, in the order a person reads them. None of them is withdrawable money
    /// (Q102/Q103): "expired" counts reversed rights too.
    public static func rows(_ bucket: PromoBucketDTO) -> [BucketRow] {
        [
            BucketRow(key: "promo.bucket.available", minor: bucket.availableMinor, hintKey: nil),
            BucketRow(key: "promo.bucket.reserved", minor: bucket.reservedMinor, hintKey: "promo.bucket.reservedHint"),
            BucketRow(key: "docState.pending", minor: bucket.underReviewMinor, hintKey: "promo.bucket.underReviewHint"),
            BucketRow(key: "promo.bucket.consumed", minor: bucket.consumedMinor, hintKey: nil),
            BucketRow(key: "promo.bucket.expired", minor: bucket.expiredMinor + bucket.reversedMinor, hintKey: nil),
        ]
    }

    /// The client's own buckets (the passenger bonus); a driver credit never shows on the client's screen.
    public static func clientBuckets(_ balance: PromoBalanceDTO) -> [PromoBucketDTO] {
        balance.buckets.filter { $0.instrument == .passengerBonus }
    }

    /// The audience's own buckets: the client's passenger bonus, the driver's credit (never each other's).
    public static func buckets(_ balance: PromoBalanceDTO, audience: String) -> [PromoBucketDTO] {
        audience == "driver" ? balance.buckets.filter { $0.instrument == .driverCredit } : clientBuckets(balance)
    }

    /// `403 FEATURE_DISABLED` (flag `promotions_enabled`): the referral programme is off.
    public static func isProgramOff(_ error: Error?) -> Bool {
        guard let error = error as? APIError, error.code == "FEATURE_DISABLED" else { return false }
        if case .string(let flag)? = error.details?["flag"] { return flag == "promotions_enabled" }
        return true
    }

    /// Which "programme off" sentence: the balance above still counts when there is one.
    public static func programOffKey(hasBuckets: Bool) -> String {
        hasBuckets ? "promoScreen.programOffWithBalance" : "promoScreen.programOff"
    }

    /// What the client's bonus screen shows. With the programme off and nothing on the balance, only the centred
    /// "Taklif dasturi hozircha ishlamayapti." state (BOSQICH 05); off with a balance, the note and that balance.
    public enum ScreenState: Equatable, Sendable { case loading, offOnly, offWithBalance, on }

    public static func screenState(programOff: Bool, balanceLoaded: Bool, hasBuckets: Bool) -> ScreenState {
        guard programOff else { return .on }
        if hasBuckets { return .offWithBalance }
        return balanceLoaded ? .offOnly : .loading
    }

    /// What "Kodni nusxalash" puts on the clipboard: the code only.
    public static func copyText(_ code: ReferralCodeDTO) -> String { code.code }

    /// What "Havolani ulashish" shares: the link once configured, else the code itself.
    public static func shareText(_ code: ReferralCodeDTO) -> String {
        showsLink(code) ? (code.shareUrl ?? code.code) : code.code
    }

    /// A campaign card's badge tone: qualified / granted green, waiting for or under review amber, refused or released grey, the rest
    /// (promised) blue.
    public static func enrollmentTone(_ enrollment: EnrollmentDTO) -> Tone {
        let status = enrollment.qualificationStatus ?? enrollment.status
        switch status {
        case "qualified", "granted": return .ok
        case "review", "waiting": return .warn
        case "rejected", "released": return .gray
        default: return .blue
        }
    }

    /// The referee's own progress on a campaign card (DESIGN09 3.9): the line key by unit, the bar's fraction and
    /// whether "still being checked" applies. Nil on the inviter's side (ADR-0023: the referrer never sees the other
    /// person's activity) or when the server sent no progress. Services in review never count as done.
    public struct Progress: Equatable, Sendable {
        public let key: String
        public let done: Int
        public let required: Int
        public let fraction: Double
        public let inReview: Bool
    }

    public static func progress(_ enrollment: EnrollmentDTO) -> Progress? {
        guard enrollment.side == "referee", let p = enrollment.progress, p.required > 0 else { return nil }
        let done = max(0, min(p.done, p.required))
        return Progress(key: p.unit == "distinct_trip" ? "promo.progress.doneTrips" : "promo.progress.doneServices",
                        done: done, required: p.required, fraction: Double(done) / Double(p.required), inReview: p.inReview > 0)
    }

    /// The share link is shown only once the server says it is configured (it may still be unverified).
    public static func showsLink(_ code: ReferralCodeDTO) -> Bool {
        code.shareUrl != nil && code.linkStatus == "configured_unverified"
    }
}

/// Referral codes: 8 characters from an alphabet without look-alikes (no 0/1/I/L/O).
public enum ReferralCode {
    public static let alphabet = Set("23456789ABCDEFGHJKMNPQRSTUVWXYZ")
    public static let length = 8

    /// What the field keeps while typing: upper-case, no spaces or dashes, at most 8 characters.
    public static func typed(_ raw: String) -> String {
        String(raw.uppercased().filter { !$0.isWhitespace && $0 != "-" }.prefix(length))
    }

    /// Same normalisation as the server; nil when it cannot be a code.
    public static func normalize(_ raw: String?) -> String? {
        guard let raw else { return nil }
        let value = raw.uppercased().filter { !$0.isWhitespace && $0 != "-" }
        return value.count == length && value.allSatisfy(alphabet.contains) ? value : nil
    }
}

extension ReferralCode {
    /// The entry field's error key, or nil: a full-length value outside the alphabet is "Kod 8 ta harf va raqamdan
    /// iborat"; the client's own code (BOSQICH 05) is "O'z kodingizni kiritib bo'lmaydi.".
    public static func entryErrorKey(_ entered: String, own: String?) -> String? {
        guard entered.count == length else { return nil }
        guard let code = normalize(entered) else { return "promoScreen.codeFormat" }
        if let own, code == own.uppercased() { return "client.bonus.ownCode" }
        return nil
    }
}

// MARK: - Safety centre

public enum ReportTone {
    /// open / under review = warn, dismissed = neutral, actioned = ok.
    public static func of(_ status: ReportStatus) -> Tone {
        switch status {
        case .open, .underReview: .warn
        case .actioned: .ok
        default: .gray
        }
    }
}

// MARK: - Support

public enum SupportText {
    /// A ticket row's title: the first line of what the person wrote.
    public static func firstLine(_ message: String?) -> String {
        let line = (message ?? "").split(whereSeparator: \.isNewline).first.map(String.init) ?? ""
        return line.trimmingCharacters(in: .whitespaces)
    }

    public static let minTicketLength = 5
    /// The design's textarea cap.
    public static let maxTicketLength = 1000

    public static func typed(_ raw: String) -> String { String(raw.prefix(maxTicketLength)) }

    /// The FAQ answer key. The client's first and fourth answers are Profil v3's: the first no longer tells clients to
    /// bid on drivers' listings (Q138: drivers publish none), the fourth keeps Q142 (phones open when the service starts).
    public static func faqAnswerKey(prefix: String, index: Int) -> String {
        guard prefix == "support.faq" else { return "\(prefix)\(index)Answer" }
        switch index {
        case 1: return "client.v3.faq1Answer"
        case 4: return "client.v3.faq4Answer"
        default: return "\(prefix)\(index)Answer"
        }
    }

    /// "Kamida 5 ta belgi yozing" under the field while something, but too little, is written.
    public static func showsMinHint(_ draft: String) -> Bool {
        let count = draft.trimmingCharacters(in: .whitespacesAndNewlines).count
        return count > 0 && count < minTicketLength
    }

    public static func canSend(_ draft: String) -> Bool {
        draft.trimmingCharacters(in: .whitespacesAndNewlines).count >= minTicketLength
    }

    /// Badge tone of a thread's staff status: answered = info, assigned = warn, waiting / closed = grey.
    public static func threadTone(_ thread: SupportThreadDTO) -> Tone {
        if thread.status == "closed" { return .gray }
        switch thread.staffStatus {
        case "answered": return .blue
        case "assigned": return .warn
        default: return .gray
        }
    }

    public static func ticketTone(_ status: SupportTicketStatus) -> Tone {
        switch status {
        case .open: .warn
        case .acknowledged: .blue
        case .resolved: .ok
        default: .gray
        }
    }
}

// MARK: - Account deletion

/// One line of "Hozircha o'chirib bo'lmaydi": a counter the dictionary names, or "something else" once.
public enum DeletionBlocker: Equatable, Sendable {
    case known(key: String, count: Int)
    case other

    static let named = ["active_bookings", "active_orders", "open_disputes", "open_sos_tickets", "pending_no_show_reviews"]
    /// Breakdowns of a named counter (`active_bookings` = as client + as driver): already said, not "something else".
    static let parts: Set = ["active_bookings_as_client", "active_bookings_as_driver"]

    /// Every non-zero counter of `409 ACCOUNT_DELETION_BLOCKED` details, named ones first in a fixed order; all the
    /// others (wallet, custody, receipts, held commission…) collapse into one "other" line.
    public static func lines(_ details: JSONValue?) -> [DeletionBlocker] {
        guard case .object(let object)? = details else { return [.other] }
        let counts: [String: Int] = object.compactMapValues {
            switch $0 {
            case .number(let value): Int(value)
            case .bool(let flag): flag ? 1 : 0
            default: nil
            }
        }
        var out = named.compactMap { key -> DeletionBlocker? in
            guard let count = counts[key], count > 0 else { return nil }
            return .known(key: "client.accountDelete.blocked.\(key)", count: count)
        }
        if counts.contains(where: { !named.contains($0.key) && !parts.contains($0.key) && $0.value > 0 }) { out.append(.other) }
        return out.isEmpty ? [.other] : out
    }

    /// "Buyurtmalarga o'tish" in the refusal: something open the client's orders list shows.
    public static func leadsToOrders(_ lines: [DeletionBlocker]) -> Bool {
        lines.contains {
            if case .known(let key, let count) = $0 {
                return count > 0 && (key.hasSuffix(".active_bookings") || key.hasSuffix(".active_orders"))
            }
            return false
        }
    }
}

// MARK: - Session expiry

/// What a refused token refresh means. A 4xx answer (401 `INVALID_TOKEN` / `REFRESH_TOKEN_REVOKED` /
/// `TOKEN_EXPIRED` / `UNAUTHORIZED`, 403 `USER_BLOCKED` / `USER_INACTIVE`, a malformed token) = the session is over:
/// sign in again. No connection, a 5xx, a timeout or a rate limit say nothing about the session: keep it quietly.
public enum SessionExpiryPolicy {
    public enum Decision: Equatable, Sendable { case relogin, keep }

    public static func decision(_ error: APIError) -> Decision {
        if error.code == APIError.network { return .keep }
        switch error.status {
        case 408, 429: return .keep
        case 400..<500: return .relogin
        default: return .keep
        }
    }
}
