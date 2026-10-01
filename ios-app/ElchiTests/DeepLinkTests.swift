import Foundation
import Testing
@testable import Elchi

/// Deep links / Universal Links: the URL -> target rules, what each audience does with a target, the kept referral
/// code (first wins, forgotten after a final answer) and the decision after an attribution attempt.
struct DeepLinkRulesTests {
    func target(_ raw: String) -> DeepLinkTarget { DeepLinkRules.target(URL(string: raw)!) }

    @Test func schemeLinksNameInAppScreens() {
        #expect(target("elchi://bookings/bkg_abc") == .booking("bkg_abc"))
        #expect(target("elchi://bookings/bkg_abc/") == .booking("bkg_abc"))
        #expect(target("elchi://bookings/bkg_abc/messages") == .bookingChat("bkg_abc"))
        #expect(target("elchi://listings/lst_1") == .listing("lst_1"))
        #expect(target("elchi://proposals/prp_1") == .proposal("prp_1"))
        #expect(target("elchi://support-threads/sth_1") == .supportThread("sth_1"))
        // The empty-host spelling and a query string (e.g. a push's tracking id) work the same.
        #expect(target("elchi:///bookings/bkg_abc/messages") == .bookingChat("bkg_abc"))
        #expect(target("elchi://support-threads/sth_1?from=push") == .supportThread("sth_1"))
        #expect(target("ELCHI://listings/lst_1") == .listing("lst_1"))
    }

    @Test func schemeReferralIsNormalised() {
        #expect(target("elchi://r/AB2CD3EF") == .referral("AB2CD3EF"))
        #expect(target("elchi://r/ab2cd3ef") == .referral("AB2CD3EF"))
        #expect(target("elchi://r/AB2C-D3EF/") == .referral("AB2CD3EF"))
        #expect(target("elchi://r/AB2C%20D3EF") == .referral("AB2CD3EF"))
    }

    @Test func badReferralCodesAreUnsupported() {
        #expect(target("elchi://r/AB2CD3E") == .unsupported)       // 7 characters
        #expect(target("elchi://r/AB2CD3EF9") == .unsupported)     // 9 characters
        #expect(target("elchi://r/AB0CD1EO") == .unsupported)      // 0 / 1 / O are not in the alphabet
        #expect(target("elchi://r/") == .unsupported)
        #expect(target("elchi://r/AB2CD3EF/extra") == .unsupported)
    }

    @Test func universalLinksClaimOnlyTheReferralPage() {
        #expect(target("https://www.elchigo.uz/r/AB2CD3EF") == .referral("AB2CD3EF"))
        #expect(target("https://elchigo.uz/r/ab2cd3ef/") == .referral("AB2CD3EF"))
        #expect(target("https://ELCHIGO.UZ/r/AB2CD3EF?utm_source=tg") == .referral("AB2CD3EF"))
        // Tracking (/t/) and evidence (/e/) pages stay in the browser until Stage 10; in-app paths are not web links.
        #expect(target("https://www.elchigo.uz/t/abc") == .unsupported)
        #expect(target("https://www.elchigo.uz/e/abc") == .unsupported)
        #expect(target("https://www.elchigo.uz/bookings/bkg_1") == .unsupported)
        #expect(target("https://www.elchigo.uz/") == .unsupported)
        #expect(target("https://www.elchigo.uz/r/BAD") == .unsupported)
    }

    @Test func otherHostsAndSchemesAreUnsupported() {
        #expect(target("https://evil.example/r/AB2CD3EF") == .unsupported)
        #expect(target("https://elchigo.uz.evil.example/r/AB2CD3EF") == .unsupported)
        #expect(target("http://www.elchigo.uz/r/AB2CD3EF") == .unsupported)
        #expect(target("tel:+998901234567") == .unsupported)
        #expect(target("elchi://") == .unsupported)
        #expect(target("elchi://garbage/x") == .unsupported)
        #expect(target("elchi://trips/trp_1") == .unsupported)        // no client screen for a trip
        #expect(target("elchi://bookings") == .unsupported)
        #expect(target("elchi://bookings/bkg_1/receipt") == .unsupported)
    }

    @Test func audienceDecidesWhatOpens() {
        let all: [DeepLinkTarget] = [.booking("b"), .bookingChat("b"), .listing("l"), .proposal("p"), .supportThread("s")]
        for target in all {
            #expect(DeepLinkRules.action(target, audience: .client) == .open(target))
            #expect(DeepLinkRules.action(target, audience: .signedOut) == .holdForSignIn)
        }
        #expect(DeepLinkRules.action(.supportThread("s"), audience: .driver) == .open(.supportThread("s")))
        for target in all.dropLast() {
            #expect(DeepLinkRules.action(target, audience: .driver) == .unsupported)
        }
        #expect(DeepLinkRules.action(.unsupported, audience: .client) == .unsupported)
    }

    @Test func clientTargetsAreTheInboxScreens() {
        #expect(DeepLinkRules.inboxTarget(.booking("b")) == .booking("b", chat: false))
        #expect(DeepLinkRules.inboxTarget(.bookingChat("b")) == .booking("b", chat: true))
        #expect(DeepLinkRules.inboxTarget(.listing("l")) == .listing("l"))
        #expect(DeepLinkRules.inboxTarget(.proposal("p")) == .proposal("p"))
        #expect(DeepLinkRules.inboxTarget(.supportThread("s")) == .supportThread("s"))
        #expect(DeepLinkRules.inboxTarget(.referral("AB2CD3EF")) == nil)
    }
}

struct ReferralStoreTests {
    @Test func firstCodeWinsUntilForgotten() {
        let suite = "elchi.tests.referral.\(UUID().uuidString)"
        defer { UserDefaults().removePersistentDomain(forName: suite) }
        let store = ReferralStore(suite: suite)
        #expect(store.code == nil)
        #expect(store.remember("AB2CD3EF") == "AB2CD3EF")
        #expect(store.remember("ZZ2CD3EF") == "AB2CD3EF")
        #expect(store.code == "AB2CD3EF")
        store.forget()
        #expect(store.code == nil)
        #expect(store.remember("ZZ2CD3EF") == "ZZ2CD3EF")
    }

    @Test func aCorruptStoredValueIsNoCode() {
        let suite = "elchi.tests.referral.\(UUID().uuidString)"
        defer { UserDefaults().removePersistentDomain(forName: suite) }
        UserDefaults(suiteName: suite)!.set("not a code", forKey: ReferralStore.key)
        let store = ReferralStore(suite: suite)
        #expect(store.code == nil)
        #expect(store.remember("AB2CD3EF") == "AB2CD3EF")
    }
}

struct ReferralOutcomeTests {
    func error(_ status: Int, _ code: String, flag: String? = nil) -> APIError {
        APIError(status: status, code: code, message: "", details: flag.map { .object(["flag": .string($0)]) })
    }

    @Test func finalAnswersForgetTheCode() {
        #expect(ReferralOutcome.decision(nil) == .forget)
        #expect(ReferralOutcome.decision(error(422, "REFERRAL_CODE_INVALID")) == .forget)
        #expect(ReferralOutcome.decision(error(409, "REFERRAL_ALREADY_ATTRIBUTED")) == .forget)
        #expect(ReferralOutcome.decision(error(403, "REFERRAL_NOT_ELIGIBLE")) == .forget)
        #expect(ReferralOutcome.decision(error(400, "VALIDATION_ERROR")) == .forget)
    }

    @Test func undecidedAnswersKeepTheCode() {
        #expect(ReferralOutcome.decision(error(403, "FEATURE_DISABLED", flag: "promotions_enabled")) == .keep)
        #expect(ReferralOutcome.decision(error(0, APIError.network)) == .keep)
        #expect(ReferralOutcome.decision(error(429, "RATE_LIMITED")) == .keep)
        #expect(ReferralOutcome.decision(error(503, "SERVER_ERROR")) == .keep)
        #expect(ReferralOutcome.decision(error(401, "INVALID_TOKEN")) == .keep)
        #expect(ReferralOutcome.decision(CancellationError()) == .keep)
    }
}

@MainActor
struct DeepLinkCenterTests {
    func center() -> (DeepLinkCenter, BannerCenter, ReferralStore, String) {
        let suite = "elchi.tests.links.\(UUID().uuidString)"
        let banners = BannerCenter()
        let store = ReferralStore(suite: suite)
        return (DeepLinkCenter(banners: banners, store: store), banners, store, suite)
    }

    @Test func referralLinkIsKeptAndAnnounced() {
        let (links, banners, store, suite) = center()
        defer { UserDefaults().removePersistentDomain(forName: suite) }
        links.handle(URL(string: "elchi://r/ab2cd3ef")!)
        links.handle(URL(string: "https://www.elchigo.uz/r/ZZ2CD3EF")!)
        #expect(store.code == "AB2CD3EF")
        #expect(links.referralCode == "AB2CD3EF")
        guard case .template(let key, let values, _)? = banners.current?.message else { Issue.record("no banner"); return }
        #expect(key == "link.referralSaved")
        #expect(values["code"] == "AB2CD3EF")
        #expect(links.takeReferralArrival())
        #expect(!links.takeReferralArrival())
        links.forgetReferral()
        #expect(links.referralCode == nil && store.code == nil)
    }

    @Test func pendingTargetWaitsForSignIn() {
        let (links, banners, _, suite) = center()
        defer { UserDefaults().removePersistentDomain(forName: suite) }
        links.handle(URL(string: "elchi://bookings/bkg_1/messages")!)
        #expect(links.takePending(for: .signedOut) == .holdForSignIn)
        #expect(links.takePending(for: .client) == .open(.bookingChat("bkg_1")))
        #expect(links.takePending(for: .client) == nil)
        #expect(banners.current == nil)
    }

    @Test func driverCannotOpenABooking() {
        let (links, banners, _, suite) = center()
        defer { UserDefaults().removePersistentDomain(forName: suite) }
        links.handle(URL(string: "elchi://bookings/bkg_1")!)
        #expect(links.takePending(for: .driver) == .unsupported)
        guard case .key(let key)? = banners.current?.message else { Issue.record("no banner"); return }
        #expect(key == "link.unsupported")
        #expect(links.takePending(for: .driver) == nil)
    }

    @Test func garbageSaysUnsupportedAndKeepsNothing() {
        let (links, banners, _, suite) = center()
        defer { UserDefaults().removePersistentDomain(forName: suite) }
        links.handle(URL(string: "elchi://nonsense/123")!)
        guard case .key(let key)? = banners.current?.message else { Issue.record("no banner"); return }
        #expect(key == "link.unsupported")
        #expect(links.takePending(for: .client) == nil)
        #expect(links.serial == 0)
    }

    @Test func universalLinkActivityUsesTheSameRules() {
        let (links, _, _, suite) = center()
        defer { UserDefaults().removePersistentDomain(forName: suite) }
        let activity = NSUserActivity(activityType: NSUserActivityTypeBrowsingWeb)
        activity.webpageURL = URL(string: "https://elchigo.uz/r/AB2CD3EF")
        links.handle(activity: activity)
        #expect(links.referralCode == "AB2CD3EF")
    }
}
