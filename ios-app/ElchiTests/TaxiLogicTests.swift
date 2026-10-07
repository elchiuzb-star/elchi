import Foundation
import Testing
@testable import Elchi

/// Taksi (passenger): the rollout gate, the seat picker, the request body and its total, the seat-count edit (Q145),
/// the passenger booking's states on both sides, the boarding code reissue wait (Q75), board refusals, the no-show
/// gate, body and reasons (Q7), the cash record rules (Q78) and the client's completion.
enum TaxiFixture {
    static func flags(passenger: Bool, parcel: Bool = true) -> EffectiveFlagValuesDTO {
        EffectiveFlagValuesDTO(driverListingEnabled: false, parcelEnabled: parcel, passengerEnabled: passenger, trackingEnabled: true)
    }

    static func receipt(side: String = "driver", status: String = "reported_paid", amount: Int = 30_000_000, version: Int = 1) -> String {
        """
        {"id":"crc_1","booking_id":"bkg_p","booking_version":7,"reported_by_side":"\(side)","amount_minor":\(amount),"currency":"UZS",
         "status":"\(status)","reported_at":"2026-09-30T09:20:00Z","decided_at":null,"dispute_id":null,"version":\(version)}
        """
    }

    /// A passenger booking (2 seats x 150 000 so'm) as `viewer` sees it.
    static func json(status: String = "confirmed", viewer: String = "client", cash: String = "unpaid", receipt: String? = nil,
                     noShow: String? = nil, phonesVisible: Bool = false) -> JSONValue {
        let review = noShow.map { #"{"status":"\#($0)","reported_at":"2026-09-30T05:20:00Z","decided_at":null}"# } ?? "null"
        let driverOnly = viewer == "driver" ? """
            "client":{"id":"usr_c","display_name":"Aziza","contact_phone":\(phonesVisible ? "\"+998901112233\"" : "null")},
            "commission_status":"held","fee":{"policy_id":"pol_1","policy_kind":"standard","fee_bps":1000,"commission_minor":3000000,"net_minor":27000000},
            """ : ""
        return Fixture.decode(JSONValue.self, """
            {"id":"bkg_p","viewer_side":"\(viewer)","service_type":"passenger","service_status":"\(status)","cash_status":"\(cash)",
             "quantity_amendable":false,"version":7,"trip_id":"trp_p","listing_ids":{"request":"lst_p","supply":null},
             "accepted_proposal_version_id":"prv_p","quantity":2,"price_basis":"per_seat","unit_price_minor":15000000,"total_minor":30000000,
             "currency":"UZS","payment_method":"cash",
             "pickup":{"point":{"lat":41.31,"lng":69.27,"district":{"id":"dst_1","name_uz":"Chilonzor"}},
                       "window_start":"2026-09-30T05:00:00Z","window_end":"2026-09-30T07:00:00Z"},
             "dropoff":{"point":{"lat":39.65,"lng":66.97,"address":"Registon","district":{"id":"dst_2","name_uz":"Samarqand"}},"planned_arrival_at":"2026-09-30T10:00:00Z"},
             "driver":{"id":"usr_d","display_name":"Jasur","vehicle":{"vehicle_class":"car","seat_capacity":4,"make_model":"Cobalt",
               "color":"oq","plate_masked":"01 A ••• KA","plate_number":null},"contact_phone":null},
             \(driverOnly)
             "contact":{"phones_visible":\(phonesVisible),"visible_from":null,"visible_until":null,"chat_thread_id":null,"support_available":true},
             "no_show_review":\(review),"cash_receipt":\(receipt ?? "null"),
             "policy_versions":{"listing_version":1,"listing_terms_version":1,"cancellation_policy":"standard"},
             "cancellation_policy_summary":"-","cancelled":null,"promo":null,
             "created_at":"2026-09-29T12:00:00Z","updated_at":"2026-09-30T05:00:00Z"}
            """)
    }

    static func client(status: String = "confirmed", cash: String = "unpaid", receipt: String? = nil, noShow: String? = nil) -> ClientBookingDTO {
        ClientBookingDTO.from(json(status: status, cash: cash, receipt: receipt, noShow: noShow))!
    }

    static func driver(status: String = "awaiting_pickup", cash: String = "unpaid", receipt: String? = nil, noShow: String? = nil,
                       phonesVisible: Bool = false) -> DriverBookingDTO {
        DriverBookingDTO.from(json(status: status, viewer: "driver", cash: cash, receipt: receipt, noShow: noShow, phonesVisible: phonesVisible))!
    }

    static func listing(status: String = "published", seats: Int = 2, children: Int? = nil) -> ListingDTO {
        Fixture.decode(ListingDTO.self, """
            {"id":"lst_p","kind":"request","service_type":"passenger","status":"\(status)","version":5,"corridor_id":"cor_1",
             "created_at":"2026-09-28T08:00:00Z","currency":"UZS","departure_window_start":"2026-09-30T04:00:00Z",
             "departure_window_end":"2026-09-30T13:00:00Z","expires_at":"2026-10-02T13:00:00Z","owner":{"id":"usr_1","display_name":"A"},
             "payment_method":"cash","price_basis":"per_seat","quantity":\(seats),"terms_version":2,"timezone":"Asia/Tashkent",
             "total_minor":\(seats * 15_000_000),"unit_price_minor":15000000,"comment":null,"view_count":3,
             "passenger":{"seat_count":\(seats),"adults":\(seats - (children ?? 0)),"children":\(children.map(String.init) ?? "null")}}
            """)
    }

    static func apiError(_ code: String, _ details: String = "null") -> APIError {
        APIError(status: 409, code: code, message: "", details: Fixture.decode(JSONValue.self, details))
    }
}

struct PassengerGateTests {
    @Test func segmentOnlyWhenPassengerIsOn() {
        #expect(PassengerGate.modeVisible(TaxiFixture.flags(passenger: true)))
        #expect(!PassengerGate.modeVisible(TaxiFixture.flags(passenger: false)))
        #expect(!PassengerGate.modeVisible(nil))
    }

    @Test func viewRouteNeedsTheChosenServiceOpen() {
        let on = TaxiFixture.flags(passenger: true), off = TaxiFixture.flags(passenger: false)
        #expect(PassengerGate.canViewRoute(directionReady: true, flags: on, mode: .passenger))
        #expect(!PassengerGate.canViewRoute(directionReady: true, flags: off, mode: .passenger))
        #expect(PassengerGate.canViewRoute(directionReady: true, flags: off, mode: .parcel))
        #expect(!PassengerGate.canViewRoute(directionReady: false, flags: on, mode: .passenger))
        // Unknown flags: nothing opens yet.
        #expect(!PassengerGate.canViewRoute(directionReady: true, flags: nil, mode: .passenger))
    }

    @Test func closedCorridorSaysWhich() {
        #expect(PassengerGate.closedKey(TaxiFixture.flags(passenger: false), mode: .passenger) == "home.passengerClosed")
        #expect(PassengerGate.closedKey(TaxiFixture.flags(passenger: true, parcel: false), mode: .parcel) == "home.parcelClosed")
        #expect(PassengerGate.closedKey(TaxiFixture.flags(passenger: true), mode: .passenger) == nil)
        #expect(PassengerGate.closedKey(nil, mode: .passenger) == nil)
    }

    @Test func aFailedReadClosesEverything() {
        #expect(PassengerGate.open(PassengerGate.closed, mode: .passenger) == false)
        #expect(PassengerGate.open(PassengerGate.closed, mode: .parcel) == false)
        #expect(PassengerGate.closedKey(PassengerGate.closed, mode: .passenger) == "home.passengerClosed")
    }
}

struct SeatPickerTests {
    @Test func togglesKeepOrderAndNeverEmpty() {
        var seats = SeatPicker.defaultSeats
        #expect(seats == [.rearRight])
        seats = SeatPicker.toggle(.front, in: seats)
        #expect(seats == [.rearRight, .front])
        #expect(SeatPicker.order(of: .front, in: seats) == 2)
        #expect(SeatPicker.order(of: .rearLeft, in: seats) == nil)
        seats = SeatPicker.toggle(.rearRight, in: seats)
        #expect(seats == [.front])
        // The last seat stays: a request for nobody is not a request.
        #expect(SeatPicker.toggle(.front, in: seats) == [.front])
        #expect(SeatPicker.maxSeats == 4)
        #expect(SeatPicker.seats(count: 3).count == 3)
        #expect(SeatPicker.seats(count: 9).count == 4)
        #expect(SeatPicker.seats(count: 0).count == 1)
    }

    @Test func totalIsSeatsTimesUnit() {
        #expect(PassengerMoney.total(seats: 2, unitMinor: 15_000_000) == 30_000_000)
        #expect(PassengerMoney.total(seats: 3, unitMinor: 0) == 0)
        #expect(PassengerMoney.perSeat(.perSeat) && !PassengerMoney.perSeat(.total) && !PassengerMoney.perSeat(nil))
    }
}

struct PassengerRequestBodyTests {
    @Test func buildsThePassengerRequest() throws {
        let start = ISO8601DateFormatter().date(from: "2026-09-29T04:00:00Z")!
        let draft = PassengerRequestDraft(
            pickup: PlaceEnd(region: RequestBodyTests.region, district: RequestBodyTests.district, point: GeoPoint(lat: 41.2856, lng: 69.2044),
                             address: "Chilonzor"),
            dropoff: PlaceEnd(region: RequestBodyTests.region, district: RequestBodyTests.sam, point: GeoPoint(lat: 39.6547, lng: 66.9758), address: nil),
            windowStart: start, windowEnd: start.addingTimeInterval(9 * 3600), seats: 2, unitPriceMinor: 15_000_000)
        #expect(draft.totalMinor == 30_000_000)
        let json = try #require(try JSONSerialization.jsonObject(with: JSONEncoder().encode(draft.listingCreate())) as? [String: Any])
        #expect(json["kind"] as? String == "request")
        #expect(json["service_type"] as? String == "passenger")
        #expect(json["price_basis"] as? String == "per_seat")
        #expect(json["unit_price_minor"] as? Int == 15_000_000)
        #expect(json["payment_method"] as? String == "cash")
        #expect(json["departure_window_start"] as? String == "2026-09-29T09:00:00+05:00")
        #expect(json["parcel"] == nil)
        #expect(json["comment"] == nil)
        let passenger = try #require(json["passenger"] as? [String: Any])
        #expect(passenger["seat_count"] as? Int == 2)
        #expect(passenger["adults"] as? Int == 2)
        // No children, baggage or amenities in this version.
        #expect(passenger["children"] == nil && passenger["baggage"] == nil && passenger["amenities"] == nil)
        let origin = try #require(json["origin_point"] as? [String: Any])
        #expect(origin["district_id"] as? String == "dst_tk")
    }
}

struct SeatEditTests {
    let now = Fixture.date("2026-09-29T10:00:00Z")

    @Test func formStartsWithTheCount() {
        let form = ListingEditForm(listing: TaxiFixture.listing(seats: 3))
        #expect(form.seats == "3")
        #expect(ListingEditForm(listing: Fixture.listing()).seats == "")
    }

    @Test func newCountSendsTheWholeBlockAndClosesOffers() throws {
        let listing = TaxiFixture.listing(seats: 2)
        var form = ListingEditForm(listing: listing)
        form.seats = "3"
        let plan = ListingPatchPlan.plan(listing, form, now: now)
        #expect(plan.invalid == nil && !plan.empty)
        #expect(plan.material) // Q20: a new count expires the open offers
        #expect(plan.passenger?.seatCount == 3 && plan.passenger?.adults == 3)
        #expect(plan.unitPriceMinor == nil && plan.windowStart == nil)
        let json = try #require(try JSONSerialization.jsonObject(with: JSONEncoder().encode(plan.body(expectedVersion: 5))) as? [String: Any])
        #expect(json["expected_version"] as? Int == 5)
        let passenger = try #require(json["passenger"] as? [String: Any])
        #expect(passenger["seat_count"] as? Int == 3 && passenger["adults"] as? Int == 3)
    }

    @Test func childrenStayAndAdultsAreTheRest() {
        let listing = TaxiFixture.listing(seats: 3, children: 1)
        var form = ListingEditForm(listing: listing)
        form.seats = "4"
        #expect(ListingPatchPlan.plan(listing, form, now: now).passenger?.adults == 3)
        form.seats = "1"
        #expect(ListingPatchPlan.plan(listing, form, now: now).invalid == "seats") // not fewer people than children
    }

    @Test func outOfRangeIsRefusedBeforeSending() {
        let listing = TaxiFixture.listing()
        var form = ListingEditForm(listing: listing)
        for bad in ["0", "9", "", "x"] {
            form.seats = bad
            #expect(ListingPatchPlan.plan(listing, form, now: now).invalid == "seats")
        }
        form.seats = "2"
        #expect(ListingPatchPlan.plan(listing, form, now: now).empty)
    }

    @Test func pricePerSeatAloneIsNotMaterial() {
        let listing = TaxiFixture.listing()
        var form = ListingEditForm(listing: listing)
        form.priceDigits = "160000"
        let plan = ListingPatchPlan.plan(listing, form, now: now)
        #expect(plan.unitPriceMinor == 16_000_000 && plan.passenger == nil && !plan.material)
    }

    @Test func onlyAPassengerRequestEditsSeats() {
        #expect(SeatEdit.editable(TaxiFixture.listing()))
        #expect(!SeatEdit.editable(Fixture.listing()))
    }
}

struct PassengerBookingTests {
    @Test func decodesThePassengerFields() throws {
        let booking = TaxiFixture.client(status: "onboard", cash: "reported_paid", receipt: TaxiFixture.receipt(), noShow: "pending")
        #expect(booking.priceBasis == .perSeat && booking.quantity == 2 && booking.unitPriceMinor == 15_000_000)
        #expect(booking.quantityAmendable == false)
        #expect(booking.cashReceipt?.id == "crc_1" && booking.cashReceipt?.reportedBySide == "driver")
        #expect(booking.noShowReview?.status == "pending")
        let driver = TaxiFixture.driver(phonesVisible: true)
        #expect(driver.base.priceBasis == .perSeat && driver.client?.contactPhone == "+998901112233")
    }

    @Test func badgesSayThePassengerStates() {
        #expect(StatusLabel.booking(.passenger, "onboard").key == "status.onboard")
        #expect(StatusLabel.booking(.passenger, "onboard").tone == .blue)
        #expect(StatusLabel.booking(.passenger, "arrived").key == "status.arrived")
        #expect(StatusLabel.booking(.passenger, "no_show").key == "status.no_show")
        #expect(StatusLabel.booking(.passenger, "no_show").tone == .err)
        #expect(StatusLabel.booking(.passenger, "awaiting_pickup").key == "status.awaiting_pickup")
        #expect(StatusLabel.booking(.passenger, "completed").tone == .ok)
    }

    @Test func passengerLadder() {
        let steps = StatusLadder.steps(status: "onboard", createdAt: nil, service: .passenger)
        #expect(steps.map(\.key) == PassengerStatus.ladder)
        #expect(steps[2].state == .current && steps[1].state == .done && steps[3].state == .ahead)
        #expect(StatusLadder.steps(status: "no_show", createdAt: nil, service: .passenger).isEmpty)
    }

    @Test func clientActionsByStatus() {
        let confirmed = ClientTaxiActions.of(TaxiFixture.client(status: "confirmed"))
        #expect(confirmed.showCode && !confirmed.cash && !confirmed.canComplete)
        let waiting = ClientTaxiActions.of(TaxiFixture.client(status: "awaiting_pickup", noShow: "pending"))
        #expect(waiting.showCode && waiting.noShowPending)
        let aboard = ClientTaxiActions.of(TaxiFixture.client(status: "onboard"))
        #expect(!aboard.showCode && aboard.cash && !aboard.canComplete)
        // "Manzilga yetib keldim" only once the driver dropped the passenger off.
        let arrived = ClientTaxiActions.of(TaxiFixture.client(status: "arrived"))
        #expect(arrived.canComplete && arrived.cash)
        let done = ClientTaxiActions.of(TaxiFixture.client(status: "completed"))
        #expect(!done.canComplete && done.cash && !done.showCode)
        #expect(BookingActions.of("completed").canRate)
        // A rejected review is no longer pending.
        #expect(!ClientTaxiActions.of(TaxiFixture.client(status: "awaiting_pickup", noShow: "rejected")).noShowPending)
        // A parcel booking has none of it.
        let parcel = ClientTaxiActions.of(BookingFixture.booking(status: "confirmed"))
        #expect(!parcel.showCode && !parcel.cash && !parcel.canComplete)
    }

    @Test func driverActionsByStatus() {
        let confirmed = DriverTaxiActions.of("confirmed", arrivedSent: false, noShowReview: nil)
        #expect(confirmed.canArrive && !confirmed.canBoard && !confirmed.showNoShow && !confirmed.cash)
        // "Keldim" stays offered in awaiting_pickup until it was sent (the web hides it there).
        let waiting = DriverTaxiActions.of("awaiting_pickup", arrivedSent: false, noShowReview: nil)
        #expect(waiting.canArrive && waiting.canBoard && waiting.showNoShow && !waiting.canDropOff)
        #expect(!DriverTaxiActions.of("awaiting_pickup", arrivedSent: true, noShowReview: nil).canArrive)
        let pending = DriverTaxiActions.of("awaiting_pickup", arrivedSent: true, noShowReview: "pending")
        #expect(pending.noShowPending && !pending.showNoShow && pending.canBoard) // a successful board closes the review
        let aboard = DriverTaxiActions.of("onboard", arrivedSent: true, noShowReview: nil)
        #expect(aboard.canDropOff && aboard.cash && !aboard.canBoard && !aboard.canArrive)
        let arrived = DriverTaxiActions.of("arrived", arrivedSent: true, noShowReview: nil)
        #expect(arrived.cash && !arrived.canDropOff)
        #expect(!DriverTaxiActions.of("no_show", arrivedSent: true, noShowReview: "confirmed").cash)
    }
}

struct BoardingCodeTests {
    let now = Fixture.date("2026-09-30T05:00:00Z")

    @Test func findsTheBoardingCode() {
        let codes = Fixture.decode(BookingCodesDTO.self, """
            {"booking_id":"bkg_p","codes":[{"kind":"boarding_code","code":"482916","valid_until":null}]}
            """)
        #expect(CodeReissue.boarding(codes)?.code == "482916")
        #expect(CodeReissue.boarding(Fixture.decode(BookingCodesDTO.self, #"{"booking_id":"bkg_p","codes":[]}"#)) == nil)
        #expect(CodeReissue.spaced("482916") == "482 916")
    }

    @Test func shortWaitInMinutesAndSeconds() throws {
        let wait = try #require(CodeReissue.wait(TaxiFixture.apiError("PROOF_REISSUE_LIMITED", #"{"retry_after_s":100,"reissues_left":2}"#), now: now))
        #expect(!wait.dailyLimit)
        let text = try #require(CodeReissue.waitText(wait, now: now))
        #expect(text.key == "reissue.waitMinutes")
        #expect(text.values.map(\.1) == [1, 40])
        // Once the time passed, the button works again.
        #expect(CodeReissue.waitText(wait, now: now.addingTimeInterval(101)) == nil)
    }

    @Test func dailyLimitInHoursAndMinutes() throws {
        let wait = try #require(CodeReissue.wait(TaxiFixture.apiError("PROOF_REISSUE_LIMITED", #"{"retry_after_s":7500,"reissues_left":0}"#), now: now))
        #expect(wait.dailyLimit)
        let text = try #require(CodeReissue.waitText(wait, now: now))
        #expect(text.key == "reissue.waitHours")
        #expect(text.values.map(\.1) == [2, 5])
        #expect(CodeReissue.wait(TaxiFixture.apiError("VERSION_CONFLICT"), now: now) == nil)
    }

    @MainActor @Test func waitSentenceIsFilled() throws {
        let strings = LocaleStore()
        strings.set(.uz)
        let wait = try #require(CodeReissue.wait(TaxiFixture.apiError("PROOF_REISSUE_LIMITED", #"{"retry_after_s":100,"reissues_left":2}"#), now: now))
        #expect(strings.reissueWaitText(wait, now: now) == "Yangi kodni 1 daqiqa 40 soniyadan keyin olish mumkin.")
    }
}

struct BoardRefusalTests {
    @Test func mapsTheBoardRefusals() {
        #expect(BoardRefusal.of(TaxiFixture.apiError("PROOF_INVALID", #"{"proof_kind":"boarding_code","attempts_left":3}"#)) == .attemptsLeft(3))
        #expect(BoardRefusal.of(TaxiFixture.apiError("PROOF_ATTEMPTS_EXCEEDED", #"{"limit":5}"#)) == .attemptsExceeded)
        #expect(BoardRefusal.of(TaxiFixture.apiError("TRIP_NOT_STARTED", #"{"trip_status":"planned"}"#)) == .tripNotStarted)
        #expect(BoardRefusal.of(TaxiFixture.apiError("VERSION_CONFLICT")) == .other)
    }

    @Test func codeIsSixDigits() {
        #expect(BoardRefusal.validCode("482916"))
        #expect(!BoardRefusal.validCode("48291") && !BoardRefusal.validCode("48291a"))
        #expect(BoardRefusal.digits("48 29-16 7") == "482916")
    }

    @MainActor @Test func attemptsLeftSentence() {
        let strings = LocaleStore()
        strings.set(.uz)
        #expect(strings.boardErrorText(TaxiFixture.apiError("PROOF_INVALID", #"{"attempts_left":2}"#)) == "Kod noto'g'ri. Yana 2 ta urinish qoldi.")
        #expect(strings.boardErrorText(TaxiFixture.apiError("TRIP_NOT_STARTED")) == strings.t("error.TRIP_NOT_STARTED"))
    }
}

struct NoShowTests {
    let windowStart = Fixture.date("2026-09-30T05:00:00Z")

    @Test func unlocksTenMinutesAfterTheLaterOfArrivalAndWindow() {
        // Arrived before the window: the wait counts from the window's start.
        let early = Fixture.date("2026-09-30T04:50:00Z")
        #expect(NoShowGate.unlocksAt(arrivedAt: early, windowStart: windowStart) == Fixture.date("2026-09-30T05:10:00Z"))
        // Arrived inside the window: from the arrival.
        let late = Fixture.date("2026-09-30T05:30:00Z")
        #expect(NoShowGate.unlocksAt(arrivedAt: late, windowStart: windowStart) == Fixture.date("2026-09-30T05:40:00Z"))
        // The trip's own wait.
        #expect(NoShowGate.unlocksAt(arrivedAt: late, windowStart: windowStart, waitMinutes: 15) == Fixture.date("2026-09-30T05:45:00Z"))
        // No "Keldim": never.
        #expect(NoShowGate.unlocksAt(arrivedAt: nil, windowStart: windowStart) == nil)
        #expect(!NoShowGate.available(arrivedAt: nil, windowStart: windowStart, now: late))
        #expect(!NoShowGate.available(arrivedAt: late, windowStart: windowStart, now: Fixture.date("2026-09-30T05:39:59Z")))
        #expect(NoShowGate.available(arrivedAt: late, windowStart: windowStart, now: Fixture.date("2026-09-30T05:40:00Z")))
    }

    @Test func bodyCarriesTheContactAttempts() throws {
        let now = Fixture.date("2026-09-30T05:45:00Z")
        #expect(NoShowReport.body(version: 7, channels: [], now: now) == nil)
        let body = try #require(NoShowReport.body(version: 7, channels: [.call, .chat], now: now))
        let json = try #require(try JSONSerialization.jsonObject(with: JSONEncoder().encode(body)) as? [String: Any])
        #expect(json["expected_version"] as? Int == 7)
        #expect(json["observed_at"] as? String == "2026-09-30T10:45:00+05:00")
        let attempts = try #require(json["contact_attempts"] as? [[String: String]])
        // The contract's channels: chat | quick_reply | arrived_signal | other - a call travels as "other".
        #expect(attempts.map { $0["channel"] } == ["chat", "other"])
        #expect(attempts.allSatisfy { $0["at"] == "2026-09-30T10:45:00+05:00" })
        #expect(json["code"] == nil)
    }

    @Test func reasonsMapToTheirSentences() {
        let known: (String) -> Bool = { $0 != "driver.noShow.reason.something_new" }
        for reason in ["not_awaiting_pickup", "arrival_not_recorded", "driver_arrived_late", "wait_time_not_elapsed", "no_contact_attempt"] {
            #expect(NoShowReport.refusalKey(TaxiFixture.apiError("NO_SHOW_NOT_ALLOWED", #"{"reason":"\#(reason)"}"#), known: known)
                    == "driver.noShow.reason.\(reason)")
        }
        #expect(NoShowReport.refusalKey(TaxiFixture.apiError("NO_SHOW_NOT_ALLOWED", #"{"reason":"something_new"}"#), known: known)
                == "error.NO_SHOW_NOT_ALLOWED")
        #expect(NoShowReport.refusalKey(TaxiFixture.apiError("NO_SHOW_REVIEW_PENDING"), known: known) == "driver.noShow.pending")
        #expect(NoShowReport.refusalKey(TaxiFixture.apiError("VERSION_CONFLICT"), known: known) == nil)
    }

    @MainActor @Test func reasonSentencesExistAndNameTheTime() {
        let strings = LocaleStore()
        defer { strings.set(.uz) }
        for locale in AppLocale.allCases {
            strings.set(locale)
            for reason in ["not_awaiting_pickup", "arrival_not_recorded", "driver_arrived_late", "wait_time_not_elapsed", "no_contact_attempt"] {
                #expect(strings.tOrNil("driver.noShow.reason.\(reason)") != nil)
            }
            for channel in NoShowChannel.allCases { #expect(strings.tOrNil(channel.labelKey) != nil) }
        }
        strings.set(.uz)
        let at = Date().addingTimeInterval(300)
        let text = strings.noShowErrorText(TaxiFixture.apiError("NO_SHOW_NOT_ALLOWED", #"{"reason":"wait_time_not_elapsed"}"#), unlocksAt: at)
        #expect(text.contains(strings.clock(at)))
    }
}

struct CashRecordTests {
    @Test func stateBySide() {
        let mine = TaxiFixture.client(status: "onboard", cash: "reported_paid", receipt: TaxiFixture.receipt(side: "client"))
        if case .reportedByMe = CashState.of(cashStatus: mine.cashStatus, receipt: mine.cashReceipt, side: "client") {} else { Issue.record("mine") }
        let theirs = TaxiFixture.client(status: "onboard", cash: "reported_paid", receipt: TaxiFixture.receipt(side: "driver"))
        if case .reportedByOther(let receipt) = CashState.of(cashStatus: theirs.cashStatus, receipt: theirs.cashReceipt, side: "client") {
            #expect(receipt.amountMinor == 30_000_000)
        } else {
            Issue.record("theirs")
        }
        #expect(CashState.of(cashStatus: "unpaid", receipt: nil, side: "driver") == .unpaid)
        #expect(CashState.of(cashStatus: "acknowledged", receipt: nil, side: "driver") == .acknowledged)
        #expect(CashState.of(cashStatus: "contested", receipt: nil, side: "client") == .contested)
    }

    @Test func noteOnlyWhenTheAmountDiffers() {
        #expect(!CashRecord.noteRequired(amountMinor: 30_000_000, dueMinor: 30_000_000))
        #expect(CashRecord.noteRequired(amountMinor: 25_000_000, dueMinor: 30_000_000))
        #expect(CashRecord.canReport(amountMinor: 30_000_000, dueMinor: 30_000_000, note: ""))
        #expect(!CashRecord.canReport(amountMinor: 25_000_000, dueMinor: 30_000_000, note: "  "))
        #expect(CashRecord.canReport(amountMinor: 25_000_000, dueMinor: 30_000_000, note: "Qolgani ertaga"))
        #expect(!CashRecord.canReport(amountMinor: 0, dueMinor: 30_000_000, note: "x"))
    }

    @Test func reportBody() throws {
        let now = Fixture.date("2026-09-30T09:20:00Z")
        let body = try #require(CashRecord.report(version: 7, amountMinor: 30_000_000, dueMinor: 30_000_000, note: " ", now: now))
        let json = try #require(try JSONSerialization.jsonObject(with: JSONEncoder().encode(body)) as? [String: Any])
        #expect(json["expected_version"] as? Int == 7)
        #expect(json["amount_minor"] as? Int == 30_000_000)
        #expect(json["reported_at"] as? String == "2026-09-30T14:20:00+05:00")
        #expect(json["note"] == nil)
        #expect(CashRecord.report(version: 7, amountMinor: 1, dueMinor: 30_000_000, note: "", now: now) == nil)
    }

    @Test func answersCarryTheReceiptVersion() throws {
        let receipt = try #require(TaxiFixture.client(cash: "reported_paid", receipt: TaxiFixture.receipt(version: 2)).cashReceipt)
        #expect(CashRecord.acknowledge(receipt).expectedVersion == 2)
        #expect(CashRecord.acknowledge(receipt).comment == nil)
        #expect(CashRecord.contest(receipt, comment: "  ") == nil) // the operator needs a reason
        #expect(CashRecord.contest(receipt, comment: " 200 000 berdim ")?.comment == "200 000 berdim")
        #expect(CashRecord.contest(receipt, comment: "x")?.expectedVersion == 2)
    }

    @Test func cashOpensOnceTheServiceStarted() {
        #expect(PassengerStatus.cashRecordable == ["onboard", "arrived", "completed"])
    }
}

@MainActor
struct TaxiStringsTests {
    @Test func everyTaxiKeyExistsInBothLanguages() {
        let strings = LocaleStore()
        defer { strings.set(.uz) }
        let keys = ["status.onboard", "status.arrived", "status.no_show", "client.taxi.complete", "client.taxi.completeHint",
                    "client.taxi.completeConfirmTitle", "client.taxi.completed", "client.taxi.seatsTotal", "driver.noShow.button",
                    "driver.noShow.hint", "driver.noShow.contactTitle", "driver.noShow.confirm", "driver.noShow.sent", "driver.noShow.pending",
                    "driver.board.attemptsLeft", "home.modeTaxi", "home.passengerClosed", "driverFeed.modeTaxi", "seatPicker.howMany",
                    "seatPicker.peopleCount", "seatPicker.driver", "seatPicker.bookedIs", "seatPicker.seatCount", "seatPicker.seatNotReserved",
                    "routeSummary.pricePerPerson", "orderForm.review.passengers", "orderForm.review.peopleCount", "orderForm.review.perPersonDetail",
                    "orderForm.review.seatNegotiated", "orderForm.review.incompletePassenger", "listingEdit.seats", "listingEdit.seatsHint",
                    "listingOwner.invalid.seats", "amendment.seatsFixed", "amendment.seatPriceLabel", "proofCode.boarding_code", "proofHint.boarding",
                    "reissue.button", "reissue.hint", "reissue.done", "reissue.waitMinutes", "reissue.waitHours", "driverBooking.boardingCode",
                    "driverBooking.codePlaceholder", "driverBooking.codeFromPassenger", "driverBooking.action.board", "driverBooking.action.dropOff",
                    "driverBooking.phoneHidden", "app.cash.title", "app.cash.explainer", "app.cash.markGiven", "app.cash.markReceived",
                    "app.cash.acknowledge", "app.cash.contest", "app.cash.bothConfirmed", "app.cash.contested", "app.cash.reportedByMe",
                    "app.cash.reportedByOther", "app.cash.awaitingOther", "bookingCancel.reviewPending", "bookingCancel.refused.noShowPending",
                    "app.progress.driverArrived"] + CabinSeat.allCases.map(\.labelKey) + PassengerStatus.ladder
        for locale in AppLocale.allCases {
            strings.set(locale)
            for key in keys { #expect(strings.tOrNil(key) != nil, "\(key) (\(locale))") }
        }
    }

    @Test func offerRefusalsForPassengers() {
        let strings = LocaleStore()
        strings.set(.uz)
        #expect(MarketErrorText.sentence(TaxiFixture.apiError("CAPACITY_UNAVAILABLE", #"{"reason":"trip_has_no_remaining_capacity"}"#))
                == .key("driverBid.capacityUnavailable", [:]))
        #expect(strings.marketErrorText(TaxiFixture.apiError("CAPACITY_UNAVAILABLE"), seats: 3).contains("3 kishiga"))
        #expect(MarketErrorText.sentence(TaxiFixture.apiError("QUANTITY_MISMATCH")) == .key("error.QUANTITY_MISMATCH", [:]))
        #expect(strings.cashErrorText(TaxiFixture.apiError("VALIDATION_ERROR", #"{"field":"note"}"#)) == strings.t("app.cash.noteRequired"))
    }

    @Test func peopleAndPerSeatLines() {
        let strings = LocaleStore()
        strings.set(.uz)
        #expect(strings.seatsTotal(2, unitMinor: 15_000_000) == "2 × 150\u{202F}000\u{00A0}so'm")
        #expect(strings.peopleLine(2, unitMinor: 15_000_000) == "2 kishi · 2 × 150\u{202F}000\u{00A0}so'm")
        #expect(strings.bookingPrice(TaxiFixture.client()) == "2 × 150\u{202F}000\u{00A0}so'm")
        #expect(strings.peopleLine(TaxiFixture.listing(seats: 3)) == "3 kishi · 3 × 150\u{202F}000\u{00A0}so'm")
        #expect(strings.peopleLine(Fixture.listing()) == nil)
    }
}
