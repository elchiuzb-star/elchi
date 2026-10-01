import Foundation
import Testing
@testable import Elchi

/// Stage 03 pure logic: negotiation actions (with the fixes and the clock), the listing edit plan (Q20), share TTL,
/// status labels, legacy prices, offer sorting, and the client's booking out of the untyped union.
enum Fixture {
    static func date(_ text: String) -> Date { ISO8601DateFormatter().date(from: text)! }

    static func decode<T: Decodable>(_ type: T.Type, _ json: String) -> T {
        try! JSONDecoder().decode(T.self, from: Data(json.utf8))
    }

    /// A thread with one current version; everything a test does not name is a plain open driver offer.
    static func thread(id: String = "prt_1", state: String = "open", author: String = "driver", status: String = "active",
                       clientLeft: Int = 3, total: Int = 14_000_000, expires: String = "2026-09-29T12:00:00Z",
                       pickupStart: String = "2026-09-30T05:00:00Z", bucket: String? = "good", ratings: Int = 12,
                       label: String = "Haydovchi #3") -> ProposalThreadDTO {
        let bucketJSON = bucket.map { "\"\($0)\"" } ?? "null"
        return decode(ProposalThreadDTO.self, """
            {"id":"\(id)","listing_id":"lst_1","listing_terms_version":2,"state":"\(state)","booking_id":null,
             "client":{"side":"client","label":"Mijoz"},"driver":{"side":"driver","label":"\(label)"},
             "driver_summary":{"vehicle_class":"car","seat_capacity":4,"rating_bucket":\(bucketJSON),"rating_count":\(ratings),"completed_bookings":3},
             "current_version":{"id":"prv_\(id)","revision":1,"author_side":"\(author)","status":"\(status)","created_at":"2026-09-29T09:00:00Z",
               "listing_terms_version":2,"currency":"UZS","demand":{"baggage_ml":0,"cargo_volume_ml":12000,"cargo_weight_g":5000},
               "expires_at":"\(expires)","pickup_window_start":"\(pickupStart)","pickup_window_end":"2026-09-30T07:00:00Z",
               "price_basis":"total","price_revisions_left":{"client":\(clientLeft),"driver":2},"quantity":1,
               "total_minor":\(total),"unit_price_minor":\(total)}}
            """)
    }

    static func listing(status: String = "published", kind: String = "request", comment: String? = "Mo'rt",
                        start: String = "2026-09-30T04:00:00Z", end: String = "2026-09-30T13:00:00Z", price: Int = 15_000_000) -> ListingDTO {
        let commentJSON = comment.map { "\"\($0)\"" } ?? "null"
        return decode(ListingDTO.self, """
            {"id":"lst_1","kind":"\(kind)","service_type":"parcel","status":"\(status)","version":4,"corridor_id":"cor_1",
             "created_at":"2026-09-28T08:00:00Z","currency":"UZS","departure_window_start":"\(start)",
             "departure_window_end":"\(end)","expires_at":"2026-10-02T13:00:00Z","owner":{"id":"usr_1","display_name":"A"},
             "payment_method":"cash","price_basis":"total","quantity":1,"terms_version":2,"timezone":"Asia/Tashkent",
             "total_minor":\(price),"unit_price_minor":\(price),"comment":\(commentJSON),"view_count":14}
            """)
    }
}

struct NegotiationActionsTests {
    let now = Fixture.date("2026-09-29T10:00:00Z")

    @Test func driversOfferIsTheClientsTurn() {
        let actions = NegotiationActions.of(Fixture.thread(), now: now)
        #expect(actions.open && actions.theirTurn)
        #expect(actions.canAccept && actions.canReject && actions.canCounter)
        #expect(!actions.canWithdraw)
        #expect(actions.revisionsLeft == 3)
    }

    @Test func ownCounterCanOnlyBeWithdrawn() {
        let actions = NegotiationActions.of(Fixture.thread(author: "client"), now: now)
        #expect(actions.open && !actions.theirTurn)
        // AC05: never accept or reject your own price.
        #expect(!actions.canAccept && !actions.canReject && !actions.canCounter)
        #expect(actions.canWithdraw)
    }

    @Test func noCounterWithoutRevisionsLeft() {
        // Fix over the web client: "Boshqa narx" is not offered when the server would refuse it.
        let actions = NegotiationActions.of(Fixture.thread(clientLeft: 0), now: now)
        #expect(actions.canAccept && actions.canReject)
        #expect(!actions.canCounter)
    }

    @Test func theClockClosesAnOfferAtOnce() {
        let thread = Fixture.thread(expires: "2026-09-29T10:00:00Z")
        let before = NegotiationActions.of(thread, now: now.addingTimeInterval(-1))
        #expect(before.open && before.canAccept)
        let at = NegotiationActions.of(thread, now: now)
        #expect(!at.open && !at.canAccept && !at.canReject && !at.canCounter && !at.canWithdraw)
        #expect(at.expiredByClock)
        #expect(thread.closedStatusKey(now: now) == "proposalStatus.expired")
    }

    @Test func closedThreadsOfferNothing() {
        let rejected = Fixture.thread(state: "closed", status: "rejected")
        #expect(NegotiationActions.of(rejected, now: now) == .closed)
        #expect(rejected.closedStatusKey(now: now) == "proposalStatus.rejected")
        let superseded = Fixture.thread(status: "superseded")
        #expect(!NegotiationActions.of(superseded, now: now).open)
        let accepted = Fixture.thread(state: "accepted", status: "accepted")
        #expect(accepted.closedStatusKey(now: now) == "proposalStatus.accepted")
    }

    @Test func driverNumberFromTheAnonymousLabel() {
        #expect(Fixture.thread(label: "Haydovchi #12").driverNumber == 12)
        #expect(Fixture.thread(label: "Haydovchi").driverNumber == nil)
    }

    @Test func countdownRoundsUpAndStops() {
        let expires = Fixture.date("2026-09-29T11:40:00Z")
        #expect(Countdown.left(until: expires, now: now)! == (1, 40))
        #expect(Countdown.left(until: expires, now: expires.addingTimeInterval(-30))! == (0, 1))
        #expect(Countdown.left(until: expires, now: expires) == nil)
        #expect(Countdown.minutesAgo(now.addingTimeInterval(-20), now: now) == 1)
        #expect(Countdown.minutesAgo(now.addingTimeInterval(-12 * 60), now: now) == 12)
    }
}

struct OfferSortTests {
    let now = Fixture.date("2026-09-29T10:00:00Z")

    @Test func sortsLiveOffersFirstByTheChosenOrder() {
        let cheap = Fixture.thread(id: "a", total: 13_000_000, pickupStart: "2026-09-30T09:00:00Z", bucket: nil, ratings: 0)
        let early = Fixture.thread(id: "b", total: 15_000_000, pickupStart: "2026-09-30T04:00:00Z", bucket: "mixed", ratings: 5)
        let rated = Fixture.thread(id: "c", total: 16_000_000, pickupStart: "2026-09-30T06:00:00Z", bucket: "good", ratings: 30)
        let closed = Fixture.thread(id: "d", state: "closed", status: "expired", total: 1_000_000)
        let all = [rated, closed, early, cheap]
        #expect(OfferSort.cheapest.sorted(all, now: now).map(\.id) == ["a", "b", "c", "d"])
        #expect(OfferSort.fastest.sorted(all, now: now).map(\.id) == ["b", "c", "a", "d"])
        #expect(OfferSort.bestRated.sorted(all, now: now).map(\.id) == ["c", "b", "a", "d"])
    }

    @Test func cheapestBadgeNeedsSomethingToCompare() {
        let a = Fixture.thread(id: "a", total: 13_000_000), b = Fixture.thread(id: "b", total: 12_000_000)
        let closed = Fixture.thread(id: "c", state: "closed", status: "rejected", total: 1_000)
        #expect(OfferSort.cheapestOpenId([a, b, closed], now: now) == "b")
        #expect(OfferSort.cheapestOpenId([a, closed], now: now) == nil)
    }
}

struct ListingEditPlanTests {
    let now = Fixture.date("2026-09-29T10:00:00Z")

    @Test func priceAndCommentAreNotMaterial() {
        let listing = Fixture.listing()
        var form = ListingEditForm(listing: listing)
        #expect(ListingPatchPlan.plan(listing, form, now: now).empty)
        form.priceDigits = "140000"
        form.comment = "  Ehtiyot bo'ling "
        let plan = ListingPatchPlan.plan(listing, form, now: now)
        #expect(plan.unitPriceMinor == 14_000_000)
        #expect(plan.comment == "Ehtiyot bo'ling")
        #expect(!plan.material && plan.invalid == nil && !plan.empty)
        #expect(plan.windowStart == nil)
    }

    @Test func movingTheWindowOfALiveListingIsMaterial() {
        let listing = Fixture.listing(status: "paused")
        var form = ListingEditForm(listing: listing)
        form.windowEnd = Fixture.date("2026-09-30T14:00:00Z")
        let plan = ListingPatchPlan.plan(listing, form, now: now)
        #expect(plan.material)
        // Both ends travel together, with the Tashkent offset.
        let body = plan.body(expectedVersion: 4)
        #expect(body.departureWindowStart == "2026-09-30T09:00:00+05:00")
        #expect(body.departureWindowEnd == "2026-09-30T19:00:00+05:00")
        #expect(body.expectedVersion == 4 && body.unitPriceMinor == nil && body.comment == nil)
        // A draft has no offers to close.
        #expect(!ListingPatchPlan.plan(Fixture.listing(status: "draft"), form, now: now).material)
    }

    @Test func clearingTheCommentSendsAnEmptyString() {
        let listing = Fixture.listing()
        var form = ListingEditForm(listing: listing)
        form.comment = ""
        let body = ListingPatchPlan.plan(listing, form, now: now).body(expectedVersion: 4)
        #expect(body.comment == "")
    }

    @Test func refusesWhatTheServerWouldRefuse() {
        let listing = Fixture.listing()
        var form = ListingEditForm(listing: listing)
        form.priceDigits = "0"
        #expect(ListingPatchPlan.plan(listing, form, now: now).invalid == "price")
        form = ListingEditForm(listing: listing)
        form.windowEnd = form.windowStart
        #expect(ListingPatchPlan.plan(listing, form, now: now).invalid == "window_order")
        form = ListingEditForm(listing: listing)
        form.windowStart = Fixture.date("2026-09-28T04:00:00Z")
        form.windowEnd = Fixture.date("2026-09-29T09:00:00Z")
        #expect(ListingPatchPlan.plan(listing, form, now: now).invalid == "window_past")
        form.windowEnd = nil
        #expect(ListingPatchPlan.plan(listing, form, now: now).invalid == "window_incomplete")
    }

    @Test func ownerActionsFollowTheStatus() {
        #expect(OwnerListingActions.of(.published) == OwnerListingActions(canPause: true, canResume: false, canEdit: true, canCancel: true, canShare: true))
        #expect(OwnerListingActions.of(.paused) == OwnerListingActions(canPause: false, canResume: true, canEdit: true, canCancel: true, canShare: true))
        #expect(OwnerListingActions.of(.draft) == OwnerListingActions(canPause: false, canResume: false, canEdit: true, canCancel: true, canShare: false))
        for status in [ListingStatus.fulfilled, .expired, .cancelled] {
            #expect(OwnerListingActions.of(status) == OwnerListingActions(canPause: false, canResume: false, canEdit: false, canCancel: false, canShare: false))
        }
    }
}

struct ShareAndStatusTests {
    @Test func ttlDaysBecomeHours() {
        #expect(ShareTTL.days.map(ShareTTL.hours) == [24, 48, 72, 168, 336])
        #expect(ShareTTL.hours(days: 30) == 336)
        #expect(ShareTTL.hours(days: 0) == 1)
        #expect(ShareTTL.days.contains(ShareTTL.defaultDays))
    }

    @Test func listingStatusLabels() {
        #expect(StatusLabel.listing(.published) == StatusLabel(key: "status.published", raw: "published", tone: .blue))
        #expect(StatusLabel.listing(.paused).tone == .gray)
        #expect(StatusLabel.listing(.expired).tone == .gray)
        #expect(StatusLabel.listing(.fulfilled).tone == .ok)
        #expect(StatusLabel.listing(.cancelled).tone == .err)
        #expect(StatusLabel.listing(.unknown("archived")).key == "status.archived")
    }

    @Test func bookingStatusLabels() {
        // Parcel in_transit is set by the system when the trip departs: "Haydovchi yo'lga chiqdi".
        #expect(StatusLabel.booking(.parcel, "in_transit") == StatusLabel(key: "parcel.status.driverDeparted", raw: "in_transit", tone: .blue))
        #expect(StatusLabel.booking(.parcel, "delivered").key == "parcel.progress.deliveredByOperator")
        #expect(StatusLabel.booking(.parcel, "confirmed").tone == .ok)
        #expect(StatusLabel.booking(.parcel, "awaiting_pickup").tone == .warn)
        #expect(StatusLabel.booking(.parcel, "cancelled").tone == .err)
        #expect(StatusLabel.booking(.parcel, "return_required").key == "tripDetail.service.return_required")
        #expect(StatusLabel.booking(.passenger, "in_transit").key == "status.in_transit")
        #expect(StatusLabel.booking(.passenger, "onboard").tone == .blue)
    }

    @Test func legacyStatusLabels() {
        #expect(StatusLabel.legacy("confirmed") == StatusLabel(key: "status.confirmed", raw: "confirmed", tone: .ok))
        #expect(StatusLabel.legacy("bidding").tone == .blue)
        #expect(StatusLabel.legacy("disputed").tone == .err)
        #expect(StatusLabel.legacy("draft").tone == .gray)
    }
}

struct LegacyAndBookingTests {
    @Test func legacyPricesAreSoumNotMinor() {
        #expect(LegacyMoney.minor(.number(70000)) == 7_000_000)
        #expect(LegacyMoney.minor(.string("70000.00")) == 7_000_000)
        #expect(LegacyMoney.minor(.string("1250.5")) == 125_050)
        #expect(LegacyMoney.minor(.string("abc")) == nil)
        #expect(LegacyMoney.minor(.number(-1)) == nil)
        #expect(LegacyMoney.minor(.null) == nil)
        #expect(LegacyMoney.minor(nil) == nil)
    }

    @Test func legacyOrderPriceIsFinalElseSuggested() {
        let agreed = Fixture.decode(LegacyOrder.self, #"{"id":1,"status":"confirmed","from_city":"Toshkent","to_city":"Namangan","suggested_price":"80000.00","final_price":70000,"created_at":"2026-08-04T10:15:00"}"#)
        #expect(agreed.priceMinor == 7_000_000)
        let asked = Fixture.decode(LegacyOrder.self, #"{"id":2,"status":"published","suggested_price":"80000.00","final_price":null}"#)
        #expect(asked.priceMinor == 8_000_000)
        #expect(ServerTime.parse(agreed.createdAt) == Fixture.date("2026-08-04T10:15:00Z"))
    }

    @Test func clientBookingOutOfTheUnion() throws {
        let json = Fixture.decode(JSONValue.self, """
            {"id":"bkg_1","viewer_side":"client","service_type":"parcel","service_status":"confirmed","cash_status":"pending",
             "pickup":{"point":{"lat":41.3,"lng":69.2,"address":"Chilonzor","district":{"id":"dst_1","name_uz":"Chilonzor"}},
                       "occurrence_seq":1,"window_start":"2026-09-30T05:00:00.123456Z","window_end":"2026-09-30T07:00:00Z"},
             "dropoff":{"stop":{"id":"stp_1","name_uz":"Registon","name_ru":"Регистан"},"occurrence_seq":3},
             "quantity":1,"unit_price_minor":14000000,"total_minor":14000000,"currency":"UZS",
             "promo":{"view":"client","fare_minor":14000000,"passenger_discount_minor":1000000,"cash_due_minor":13000000,"currency":"UZS"},
             "created_at":"2026-09-29T10:00:00Z","listing_ids":{"request":"lst_1","supply":null},"version":1}
            """)
        let booking = try #require(ClientBookingDTO.from(json))
        #expect(booking.serviceStatus == "confirmed")
        #expect(booking.pickup.point?.district?.nameUz == "Chilonzor")
        #expect(booking.dropoff.stop?.nameUz == "Registon")
        // With a bonus the client hands over the discounted amount, not the total.
        #expect(booking.cashDueMinor == 13_000_000)
        #expect(ServerTime.parse(booking.pickup.windowStart) != nil)
        let driverView = Fixture.decode(JSONValue.self, #"{"id":"bkg_2","viewer_side":"driver"}"#)
        #expect(ClientBookingDTO.from(driverView) == nil)
    }

    @Test func actionKeysAreReusedUntilADefiniteAnswer() async {
        await MainActor.run {
            let keys = ActionKeys()
            let first = keys.key("accept:prt_1:prv_1")
            #expect(keys.key("accept:prt_1:prv_1") == first)
            keys.settle("accept:prt_1:prv_1", after: APIError(status: 0, code: APIError.network, message: "", details: nil))
            #expect(keys.key("accept:prt_1:prv_1") == first)
            keys.settle("accept:prt_1:prv_1", after: APIError(status: 409, code: "PROPOSAL_CHANGED", message: "", details: nil))
            #expect(keys.key("accept:prt_1:prv_1") != first)
        }
    }
}
