import Foundation
import Testing
@testable import Elchi

/// Stage 05 pure logic: the inbox (key fallbacks, links, time labels, unread), profile figures from v2, the bonus
/// card and programme-off decision, referral codes, report tones, account-deletion blockers and the session-expiry
/// decision (which refused refreshes end the session, which keep it quietly).
enum ProfileFixture {
    static func notification(id: String = "ntf_1", type: String = "proposal.created", titleKey: String? = nil, bodyKey: String? = nil,
                             read: Bool = false, link: String? = nil, params: String = "{}", at: String = "2026-09-30T05:24:00Z") -> NotificationDTO {
        let linkJSON = link.map { "\"\($0)\"" } ?? "null"
        return Fixture.decode(NotificationDTO.self, """
            {"id":"\(id)","type":"\(type)","title_key":"\(titleKey ?? "notification.\(type).title")",
             "body_key":"\(bodyKey ?? "notification.\(type).body")","is_read":\(read),"link":\(linkJSON),"params":\(params),
             "created_at":"\(at)"}
            """)
    }

    static func bucket(available: Int = 1_000_000, reserved: Int = 0, review: Int = 500_000, consumed: Int = 2_000_000,
                       expired: Int = 100, reversed: Int = 200, instrument: String = "passenger_bonus") -> PromoBucketDTO {
        Fixture.decode(PromoBucketDTO.self, """
            {"instrument":"\(instrument)","service_type":"parcel","available_minor":\(available),"reserved_minor":\(reserved),
             "under_review_minor":\(review),"consumed_minor":\(consumed),"expired_minor":\(expired),"reversed_minor":\(reversed),
             "currency":"UZS","next_expiry_at":"2026-10-15T00:00:00Z"}
            """)
    }
}

struct InboxTests {
    let dictionary = [
        "notification.proposal.created.title": "Yangi taklif",
        "notification.fallback.title": "Yangi bildirishnoma",
        "notification.booking.accepted.body": "Bron yaratildi — {route}",
    ]

    func lookup(_ key: String) -> String? { dictionary[key] }

    @Test func titleFallsBackFromServerKeyToTypeToGeneric() {
        let known = ProfileFixture.notification(titleKey: "notification.proposal.created.title")
        #expect(Inbox.title(known, lookup: lookup) == "Yangi taklif")
        // The server's key is unknown here, the type's generic key is known.
        let byType = ProfileFixture.notification(titleKey: "n.v2.proposal.created")
        #expect(Inbox.title(byType, lookup: lookup) == "Yangi taklif")
        // Neither: the generic "new notification" - never the raw key.
        let unknown = ProfileFixture.notification(type: "future.thing", titleKey: "n.future")
        #expect(Inbox.title(unknown, lookup: lookup) == "Yangi bildirishnoma")
    }

    @Test func bodyFallsBackToTypeThenEmpty() {
        let accepted = ProfileFixture.notification(type: "booking.accepted", bodyKey: "n.unknown")
        #expect(Inbox.body(accepted, lookup: lookup) == "Bron yaratildi — {route}")
        #expect(Inbox.body(ProfileFixture.notification(), lookup: lookup) == "")
    }

    @Test func paramsBecomeFillers() {
        let item = ProfileFixture.notification(params: #"{"route":"Toshkent → Buxoro","count":2,"nested":{"x":1}}"#)
        let params = Inbox.params(item)
        #expect(params.map(\.0) == ["count", "route"])
        #expect(params.first?.1 as? String == "2")
    }

    @Test func linksLeadToTheirScreens() {
        #expect(Inbox.target("/bookings/bkg_1") == .booking("bkg_1", chat: false))
        #expect(Inbox.target("/bookings/bkg_1/messages") == .booking("bkg_1", chat: true))
        #expect(Inbox.target("https://api.elchigo.uz/api/v2/bookings/bkg_2/") == .booking("bkg_2", chat: false))
        #expect(Inbox.target("/listings/lst_9") == .listing("lst_9"))
        #expect(Inbox.target("/proposals/prt_3/messages") == .proposal("prt_3"))
        #expect(Inbox.target("/support-threads/sth_4") == .supportThread("sth_4"))
        #expect(Inbox.target("/trips/trp_5") == .trip("trp_5"))
        #expect(Inbox.target("/wallet") == .wallet) // Stage 09: the driver's top-up decision opens the wallet
        #expect(Inbox.target("/settings") == nil)
        #expect(Inbox.target(nil) == nil)
        #expect(Inbox.target("") == nil)
    }

    @Test func unreadCountsOnlyUnread() {
        let items = [ProfileFixture.notification(id: "a"), ProfileFixture.notification(id: "b", read: true), ProfileFixture.notification(id: "c")]
        #expect(Inbox.unreadCount(items) == 2)
        #expect(Inbox.unreadCount([]) == 0)
    }

    @Test func timeLabelIsTodayYesterdayOrDateInTashkent() {
        // 30.09 10:00 in Tashkent.
        let now = Fixture.date("2026-09-30T05:00:00Z")
        #expect(InboxTime.of(Fixture.date("2026-09-30T00:30:00Z"), now: now) == .today)
        // 29.09 23:30 Tashkent is yesterday there, although it is the 29th in UTC too.
        #expect(InboxTime.of(Fixture.date("2026-09-29T18:30:00Z"), now: now) == .yesterday)
        // 29.09 18:59 UTC = 30.09 00:59 Tashkent: today.
        #expect(InboxTime.of(Fixture.date("2026-09-29T19:59:00Z"), now: now) == .today)
        #expect(InboxTime.of(Fixture.date("2026-09-12T08:00:00Z"), now: now) == .earlier(sameYear: true))
        #expect(InboxTime.of(Fixture.date("2025-12-31T08:00:00Z"), now: now) == .earlier(sameYear: false))
    }

    @MainActor @Test func timeLabelWording() {
        let strings = LocaleStore()
        strings.set(.uz)
        let now = Fixture.date("2026-09-30T05:00:00Z")
        #expect(strings.inboxTime("2026-09-30T05:24:00Z", now: now) == "10:24")
        #expect(strings.inboxTime("2026-09-29T03:12:00Z", now: now).hasSuffix("08:12"))
        #expect(strings.inboxTime("2026-09-29T03:12:00Z", now: now).hasPrefix("Kecha"))
        #expect(strings.inboxTime("2025-09-12T03:12:00Z", now: now) == "12.09.2025")
    }
}

struct ProfileStatsTests {
    @Test func figuresComeFromListingsBookingsAndThreads() {
        let now = Fixture.date("2026-09-29T10:00:00Z")
        let listings = [Fixture.listing(status: "published"), Fixture.listing(status: "paused"), Fixture.listing(status: "fulfilled"),
                        Fixture.listing(status: "cancelled"), Fixture.listing(status: "published", kind: "trip_offer")]
        let bookings = [BookingFixture.booking(status: "confirmed"), BookingFixture.booking(status: "in_transit"),
                        BookingFixture.booking(status: "completed"), BookingFixture.booking(status: "cancelled")]
        let threads = [Fixture.thread(id: "a"), Fixture.thread(id: "b", author: "client"), Fixture.thread(id: "c", expires: "2026-09-29T09:00:00Z")]
        let stats = ProfileStats.derive(listings: listings, bookings: bookings, threads: threads, now: now)
        #expect(stats.total == 4) // parcel requests only
        #expect(stats.active == 2 + 2) // published + paused, confirmed + in transit
        #expect(stats.offers == 1) // only the driver's live offer waits for the client
        #expect(stats.completed == 1)
    }

    @Test func latestIsTheNewestOfBookingsAndRequests() {
        // The booking (29.09) is newer than the request (28.09).
        let stats = ProfileStats.derive(listings: [Fixture.listing()], bookings: [BookingFixture.booking(status: "in_transit")], threads: [])
        #expect(stats.latest?.key == "parcel.status.driverDeparted")
        let onlyRequest = ProfileStats.derive(listings: [Fixture.listing(status: "published")], bookings: [], threads: [])
        #expect(onlyRequest.latest?.key == "status.published")
        let none = ProfileStats.derive(listings: [], bookings: [], threads: [])
        #expect(none.latest == nil && none.total == 0)
    }

    @Test func initialsFromTheName() {
        #expect(Initials.of("Aziza Karimova") == "AK")
        #expect(Initials.of("  ali ") == "A")
        #expect(Initials.of("Aziza Karimova Olimovna") == "AK")
        #expect(Initials.of("") == nil)
        #expect(Initials.of(nil) == nil)
    }
}

struct PromoLogicTests {
    @Test func bucketRowsInReadingOrderWithExpiredAndReversedTogether() {
        let rows = PromoLogic.rows(ProfileFixture.bucket())
        #expect(rows.map(\.key) == ["promo.bucket.available", "promo.bucket.reserved", "docState.pending", "promo.bucket.consumed",
                                    "promo.bucket.expired"])
        #expect(rows.map(\.minor) == [1_000_000, 0, 500_000, 2_000_000, 300])
        #expect(rows[1].hintKey == "promo.bucket.reservedHint")
        #expect(rows[2].hintKey == "promo.bucket.underReviewHint")
    }

    @Test func clientSeesOnlyItsBonus() {
        let balance = PromoBalanceDTO(buckets: [ProfileFixture.bucket(), ProfileFixture.bucket(instrument: "driver_credit")], lots: [])
        #expect(PromoLogic.clientBuckets(balance).count == 1)
    }

    @Test func programOffOnlyForTheFeatureFlag() {
        let off = APIError(status: 403, code: "FEATURE_DISABLED", message: "", details: .object(["flag": .string("promotions_enabled")]))
        let otherFlag = APIError(status: 403, code: "FEATURE_DISABLED", message: "", details: .object(["flag": .string("parcel_enabled")]))
        let limited = APIError(status: 429, code: "RATE_LIMITED", message: "", details: nil)
        #expect(PromoLogic.isProgramOff(off))
        #expect(!PromoLogic.isProgramOff(otherFlag))
        #expect(!PromoLogic.isProgramOff(limited))
        #expect(!PromoLogic.isProgramOff(nil))
        #expect(PromoLogic.programOffKey(hasBuckets: true) == "promoScreen.programOffWithBalance")
        #expect(PromoLogic.programOffKey(hasBuckets: false) == "promoScreen.programOff")
    }

    @Test func linkShownOnlyWhenConfigured() {
        #expect(PromoLogic.showsLink(ReferralCodeDTO(code: "AB2CD3EF", linkStatus: "configured_unverified", shareUrl: "https://elchigo.uz/r/AB2CD3EF")))
        #expect(!PromoLogic.showsLink(ReferralCodeDTO(code: "AB2CD3EF", linkStatus: "not_configured", shareUrl: nil)))
        #expect(!PromoLogic.showsLink(ReferralCodeDTO(code: "AB2CD3EF", linkStatus: "configured_unverified", shareUrl: nil)))
    }

    @Test func codeIsTypedUpperCaseAndValidatedAgainstTheAlphabet() {
        #expect(ReferralCode.typed("ab2c-d3 ef99") == "AB2CD3EF")
        #expect(ReferralCode.normalize("ab2c d3ef") == "AB2CD3EF")
        #expect(ReferralCode.normalize("AB2CD3E") == nil) // 7 characters
        #expect(ReferralCode.normalize("AB2CD3E0") == nil) // 0 is not in the alphabet
        #expect(ReferralCode.normalize("ABICD3EF") == nil) // neither is I
        #expect(ReferralCode.normalize(nil) == nil)
    }
}

struct SafetySupportTests {
    @Test func reportTones() {
        #expect(ReportTone.of(.open) == .warn)
        #expect(ReportTone.of(.underReview) == .warn)
        #expect(ReportTone.of(.dismissed) == .gray)
        #expect(ReportTone.of(.actioned) == .ok)
        #expect(ReportTone.of(.unknown("x")) == .gray)
    }

    @Test func ticketTitleAndMinimumLength() {
        #expect(SupportText.firstLine("Posilka kechikmoqda\nBron B-2041") == "Posilka kechikmoqda")
        #expect(SupportText.firstLine(nil) == "")
        #expect(!SupportText.canSend(" abc  "))
        #expect(SupportText.canSend("Salom!"))
    }
}

struct AccountDeletionTests {
    @Test func namedCountersFirstThenOneOtherLine() {
        let details: JSONValue = .object(["reason": .string("blocked"), "active_bookings": .number(2), "active_orders": .number(0),
                                          "open_sos_tickets": .number(1), "wallet_balance_minor": .number(5000), "custody_cases": .number(1)])
        #expect(DeletionBlocker.lines(details) == [.known(key: "client.accountDelete.blocked.active_bookings", count: 2),
                                                   .known(key: "client.accountDelete.blocked.open_sos_tickets", count: 1), .other])
    }

    @Test func onlyNamedCountersNoOther() {
        let details: JSONValue = .object(["open_disputes": .number(1), "pending_no_show_reviews": .number(3), "held": .number(0)])
        #expect(DeletionBlocker.lines(details) == [.known(key: "client.accountDelete.blocked.open_disputes", count: 1),
                                                   .known(key: "client.accountDelete.blocked.pending_no_show_reviews", count: 3)])
    }

    @Test func bookingBreakdownIsNotSomethingElse() {
        let details: JSONValue = .object(["active_bookings": .number(1), "active_bookings_as_client": .number(1),
                                          "active_bookings_as_driver": .number(0)])
        #expect(DeletionBlocker.lines(details) == [.known(key: "client.accountDelete.blocked.active_bookings", count: 1)])
    }

    @Test func nothingReadableStillSaysSomething() {
        #expect(DeletionBlocker.lines(nil) == [.other])
        #expect(DeletionBlocker.lines(.object(["active_bookings": .number(0)])) == [.other])
    }
}

struct SessionExpiryTests {
    func error(_ status: Int, _ code: String) -> APIError { APIError(status: status, code: code, message: "", details: nil) }

    @Test func refusedRefreshTokenEndsTheSession() {
        for code in ["INVALID_TOKEN", "REFRESH_TOKEN_REVOKED", "TOKEN_EXPIRED", "UNAUTHORIZED"] {
            #expect(SessionExpiryPolicy.decision(error(401, code)) == .relogin)
        }
        #expect(SessionExpiryPolicy.decision(error(403, "USER_BLOCKED")) == .relogin)
        #expect(SessionExpiryPolicy.decision(error(403, "USER_INACTIVE")) == .relogin)
        #expect(SessionExpiryPolicy.decision(error(422, "VALIDATION_ERROR")) == .relogin)
    }

    @Test func networkServerAndRateLimitKeepItQuietly() {
        #expect(SessionExpiryPolicy.decision(error(0, APIError.network)) == .keep)
        #expect(SessionExpiryPolicy.decision(error(500, APIError.server)) == .keep)
        #expect(SessionExpiryPolicy.decision(error(503, "SERVICE_UNAVAILABLE")) == .keep)
        #expect(SessionExpiryPolicy.decision(error(429, "RATE_LIMITED")) == .keep)
        #expect(SessionExpiryPolicy.decision(error(408, "TIMEOUT")) == .keep)
    }

    @Test func expiryIsReportedOnceAndNotDuringASignOut() async {
        let events = SessionEvents()
        let seen = Seen()
        events.onEvent { seen.add($0) }
        let session = Session(accessToken: "a", refreshToken: "r",
                              user: AuthUser(id: 1, phone: "+998901112233", fullName: nil, role: "client", status: "active"))
        await events.deliberately { events.refreshRejected(session) }
        #expect(seen.all.isEmpty)
        events.refreshRejected(session)
        #expect(seen.all == [.expired(phone: "+998901112233", role: .client)])
    }
}

private final class Seen: @unchecked Sendable {
    private var events: [SessionEvent] = []
    private let lock = NSLock()
    func add(_ event: SessionEvent) { lock.withLock { events.append(event) } }
    var all: [SessionEvent] { lock.withLock { events } }
}
