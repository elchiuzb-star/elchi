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
        // Stage 09: the driver has booking, chat, offer-thread and operator-chat screens; Stage 10: a client's listing
        // too (which screen it becomes is `ListingLinkRules`).
        for target in all {
            #expect(DeepLinkRules.action(target, audience: .driver) == .open(target))
        }
        #expect(DeepLinkRules.action(.unsupported, audience: .client) == .unsupported)
        #expect(DeepLinkRules.action(.unsupported, audience: .driver) == .unsupported)
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

    @Test func driverOpensABookingAndAListing() {
        let (links, banners, _, suite) = center()
        defer { UserDefaults().removePersistentDomain(forName: suite) }
        links.handle(URL(string: "elchi://bookings/bkg_1")!)
        #expect(links.takePending(for: .driver) == .open(.booking("bkg_1")))
        #expect(links.takePending(for: .driver) == nil)
        links.handle(URL(string: "elchi://listings/lst_1")!)
        #expect(links.takePending(for: .driver) == .open(.listing("lst_1")))
        #expect(links.takePending(for: .driver) == nil)
        #expect(banners.current == nil)
    }

    @Test func signedOutListingLinkWaitsThenGoesToTheSignedInRole() {
        let (links, _, _, suite) = center()
        defer { UserDefaults().removePersistentDomain(forName: suite) }
        links.handle(URL(string: "elchi://listings/lst_9")!)
        #expect(links.takePending(for: .signedOut) == .holdForSignIn)
        #expect(links.takePending(for: .driver) == .open(.listing("lst_9")))
        #expect(links.takePending(for: .client) == nil)
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

/// Stage 10: `elchi://listings/{id}` (the share page's "Ilovani ochish") by role.
struct ListingLinkRulesTests {
    func listing(_ status: ListingStatus) -> ListingPublicDTO {
        var dto = MarketFixture.listing(id: "lst_7")
        dto.status = status
        return dto
    }

    @Test func approvedDriverGetsTheOfferScreenForAnOpenRequest() {
        let open = listing(.published)
        #expect(ListingLinkRules.driver(approved: true, listing: open) == .offer(open))
        #expect(ListingLinkRules.messageKey(.offer(open)) == nil)
    }

    @Test func unapprovedDriverGetsTheGateWhateverTheListing() {
        #expect(ListingLinkRules.driver(approved: false, listing: listing(.published)) == .gate)
        #expect(ListingLinkRules.driver(approved: false, listing: listing(.cancelled)) == .gate)
        #expect(ListingLinkRules.driver(approved: false, listing: nil) == .gate)
        #expect(ListingLinkRules.messageKey(.gate) == nil)
    }

    @Test func aListingThatTakesNoOffersIsASentence() {
        for status: ListingStatus in [.paused, .fulfilled, .expired, .cancelled, .draft, .unknown("archived")] {
            #expect(ListingLinkRules.driver(approved: true, listing: listing(status)) == .notOpen)
        }
        #expect(ListingLinkRules.messageKey(.notOpen) == "link.listingNotOpen")
        #expect(ListingLinkRules.driver(approved: true, listing: nil) == .missing)
        #expect(ListingLinkRules.messageKey(.missing) == "link.listingMissing")
    }

    @Test func theOwnerGetsTheDetailAnotherClientASentence() throws {
        // The owner's answer is the full ListingDTO (owner, version, terms_version) ...
        let owner = Fixture.decode(JSONValue.self, """
            {"id":"lst_1","kind":"request","service_type":"parcel","status":"paused","version":4,"corridor_id":"cor_1",
             "created_at":"2026-09-28T08:00:00Z","currency":"UZS","departure_window_start":"2026-09-30T04:00:00Z",
             "departure_window_end":"2026-09-30T13:00:00Z","expires_at":"2026-10-02T13:00:00Z","owner":{"id":"usr_1","display_name":"A"},
             "payment_method":"cash","price_basis":"total","quantity":1,"terms_version":2,"timezone":"Asia/Tashkent",
             "total_minor":15000000,"unit_price_minor":15000000}
            """)
        #expect(ListingLinkRules.client(owner) == .ownListing)
        // ... anybody else's the public DTO, without them.
        let data = try JSONEncoder().encode(MarketFixture.listing(id: "lst_7"))
        let other = try JSONDecoder().decode(JSONValue.self, from: data)
        #expect(ListingLinkRules.client(other) == .notOwn)
        #expect(ListingLinkRules.messageKey(.notOwn) == "link.listingNotOwn")
        #expect(ListingLinkRules.client(nil) == .missing)
        // A driver reads the public DTO out of either shape.
        #expect(ListingLinkRules.publicListing(other)?.id == "lst_7")
        #expect(ListingLinkRules.publicListing(owner)?.id == "lst_1")
    }

    @Test func onlyA404IsAMissingListing() {
        #expect(ListingLinkRules.isMissing(APIError(status: 404, code: "NOT_FOUND", message: "", details: nil)))
        #expect(!ListingLinkRules.isMissing(APIError(status: 0, code: APIError.network, message: "", details: nil)))
        #expect(!ListingLinkRules.isMissing(APIError(status: 500, code: "SERVER_ERROR", message: "", details: nil)))
        #expect(!ListingLinkRules.isMissing(CancellationError()))
    }
}
