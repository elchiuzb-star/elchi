import Foundation
import Observation

// MARK: - Rules (pure)

/// Where an opened link leads. `elchi://…` links (and later push taps) name an in-app screen; the web's
/// `https://(www.)elchigo.uz/r/<code>` Universal Link carries a referral code (Q107).
public enum DeepLinkTarget: Equatable, Sendable {
    case referral(String)
    case booking(String)
    case bookingChat(String)
    case listing(String)
    case proposal(String)
    case supportThread(String)
    case unsupported
}

/// Who is looking at the app when a link arrives.
public enum LinkAudience: Equatable, Sendable {
    case signedOut, client, driver
}

/// What the app does with a (non-referral) target for that audience.
public enum LinkAction: Equatable, Sendable {
    case open(DeepLinkTarget)
    /// Signed out: the target waits (in memory) and opens after sign-in, if the signed-in role has that screen.
    case holdForSignIn
    case unsupported
}

public enum DeepLinkRules {
    public static let scheme = "elchi"
    /// The Universal Link hosts (Associated Domains `applinks:`); only `/r/*` is claimed there. `/t/` and `/e/`
    /// (tracking and evidence pages) stay in the browser until Stage 10.
    public static let webHosts: Set<String> = ["www.elchigo.uz", "elchigo.uz"]

    /// Parses a link. `elchi://bookings/{id}[/messages]`, `listings/{id}`, `proposals/{id}`, `support-threads/{id}`,
    /// `r/{code}`; `https://(www.)elchigo.uz/r/{code}`. Anything else (another host, a trip, a malformed code, a
    /// path this app has no screen for) is `.unsupported`.
    public static func target(_ url: URL) -> DeepLinkTarget {
        guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              let scheme = components.scheme?.lowercased() else { return .unsupported }
        let path: String
        switch scheme {
        case Self.scheme:
            // `elchi://bookings/bkg_1` has the first segment as its host; `elchi:///bookings/bkg_1` has none.
            let host = components.percentEncodedHost ?? ""
            path = host.isEmpty ? components.percentEncodedPath : "/" + host + components.percentEncodedPath
        case "https":
            guard let host = components.host?.lowercased(), webHosts.contains(host) else { return .unsupported }
            // Only the referral page is the app's on the web domain.
            guard let code = referralCode(components.percentEncodedPath) else { return .unsupported }
            return .referral(code)
        default:
            return .unsupported
        }
        if path.hasPrefix("/r/") || path == "/r" {
            return referralCode(path).map(DeepLinkTarget.referral) ?? .unsupported
        }
        // The same paths the inbox reads (`/bookings/{id}/messages`, …); a trip has no client screen.
        switch Inbox.target(path) {
        case .booking(let id, let chat)?: return id.isEmpty ? .unsupported : chat ? .bookingChat(id) : .booking(id)
        case .listing(let id)?: return .listing(id)
        case .proposal(let id)?: return .proposal(id)
        case .supportThread(let id)?: return .supportThread(id)
        case .trip?, .wallet?, nil: return .unsupported
        }
    }

    /// `/r/<code>` (one segment, an optional trailing slash) -> the normalised code, else nil.
    static func referralCode(_ percentEncodedPath: String) -> String? {
        let segments = percentEncodedPath.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
        // "/r/CODE" -> ["", "r", "CODE"], "/r/CODE/" -> ["", "r", "CODE", ""]
        guard segments.count == 3 || (segments.count == 4 && segments[3].isEmpty),
              segments[0].isEmpty, segments[1] == "r" else { return nil }
        return ReferralCode.normalize(segments[2].removingPercentEncoding)
    }

    /// A client has every in-app screen the links name; a driver (Stage 09) its bookings and their chat, its offer
    /// threads and the operator chat - never a client's listing; signed out, the target waits for sign-in.
    public static func action(_ target: DeepLinkTarget, audience: LinkAudience) -> LinkAction {
        switch target {
        case .unsupported, .referral: return .unsupported
        default: break
        }
        switch audience {
        case .signedOut: return .holdForSignIn
        case .client: return .open(target)
        case .driver:
            if case .listing = target { return .unsupported }
            return .open(target)
        }
    }

    /// The inbox target the client flow already routes (the same screens as a tapped notification).
    public static func inboxTarget(_ target: DeepLinkTarget) -> InboxTarget? {
        switch target {
        case .booking(let id): .booking(id, chat: false)
        case .bookingChat(let id): .booking(id, chat: true)
        case .listing(let id): .listing(id)
        case .proposal(let id): .proposal(id)
        case .supportThread(let id): .supportThread(id)
        case .referral, .unsupported: nil
        }
    }
}

// MARK: - The referral code from a link (port of mobile-app/src/app/promo.ts rememberCode / pendingCode / forgetCode)

/// Keeps a code from a link through sign-in and restarts until the server gives a final answer. The *first* code
/// wins: a later link does not replace it (the server keeps the first attribution anyway, Q117).
public struct ReferralStore: Sendable {
    public static let key = "elchi.pendingReferralCode"
    private let suite: String?

    /// `suite` = a separate UserDefaults domain (tests); nil = the app's standard defaults.
    public init(suite: String? = nil) { self.suite = suite }

    private var defaults: UserDefaults { suite.flatMap(UserDefaults.init(suiteName:)) ?? .standard }

    public var code: String? { ReferralCode.normalize(defaults.string(forKey: Self.key)) }

    /// Stores `code` unless one is already kept; returns the code that is kept now.
    @discardableResult
    public func remember(_ code: String) -> String {
        if let kept = self.code { return kept }
        defaults.set(code, forKey: Self.key)
        return code
    }

    public func forget() { defaults.removeObject(forKey: Self.key) }
}

/// After an attribution attempt with the kept code: forget it on a final server answer (accepted, already attributed,
/// invalid, not eligible), keep it when nothing was decided (programme off, no connection, a 5xx, a rate limit).
public enum ReferralOutcome {
    public enum Decision: Equatable, Sendable { case forget, keep }

    public static func decision(_ error: Error?) -> Decision {
        guard let error else { return .forget }
        if PromoLogic.isProgramOff(error) { return .keep }
        guard let error = error as? APIError, error.code != APIError.network else { return .keep }
        switch error.status {
        case 401, 408, 429: return .keep
        case 400..<500: return .forget
        default: return .keep
        }
    }
}

// MARK: - The app's link inbox

/// Links opened while the app runs or that launched it (`onOpenURL`, a Universal Link, later a push tap). The
/// signed-in flow takes what it can open; a referral code is kept in `ReferralStore` whatever the state.
@MainActor @Observable
public final class DeepLinkCenter {
    private let banners: BannerCenter
    private let store: ReferralStore

    /// The kept referral code (the driver home's row and the client's bonus field read it).
    public private(set) var referralCode: String?
    /// A screen target waiting for a flow (or for sign-in).
    public private(set) var pending: DeepLinkTarget?
    /// A referral link arrived and no flow has acted on it yet (the client opens the bonus screen).
    public private(set) var referralArrived = false
    /// Bumps on every link, so a flow notices the same target twice.
    public private(set) var serial = 0

    public init(banners: BannerCenter, store: ReferralStore = ReferralStore()) {
        self.banners = banners
        self.store = store
        referralCode = store.code
    }

    /// `elchi://…` (and, through `handle(activity:)`, a Universal Link).
    public func handle(_ url: URL) {
        let target = DeepLinkRules.target(url)
        switch target {
        case .unsupported:
            banners.show(.key("link.unsupported"), tone: .warn)
            return
        case .referral(let code):
            let kept = store.remember(code)
            referralCode = kept
            referralArrived = true
            banners.show(.template("link.referralSaved", values: ["code": kept]), tone: .ok)
        default:
            pending = target
        }
        serial += 1
    }

    /// A Universal Link (`NSUserActivityTypeBrowsingWeb`): its `webpageURL` goes through the same rules.
    public func handle(activity: NSUserActivity) {
        guard activity.activityType == NSUserActivityTypeBrowsingWeb, let url = activity.webpageURL else { return }
        handle(url)
    }

    /// The flow takes the waiting target and routes it (or says it cannot).
    public func takePending(for audience: LinkAudience) -> LinkAction? {
        guard let target = pending else { return nil }
        let action = DeepLinkRules.action(target, audience: audience)
        if action != .holdForSignIn { pending = nil }
        if action == .unsupported { banners.show(.key("link.unsupported"), tone: .warn) }
        return action
    }

    /// True once per referral link, for a signed-in flow.
    public func takeReferralArrival() -> Bool {
        defer { referralArrived = false }
        return referralArrived
    }

    /// A final server answer about the kept code.
    public func forgetReferral() {
        store.forget()
        referralCode = nil
    }
}
