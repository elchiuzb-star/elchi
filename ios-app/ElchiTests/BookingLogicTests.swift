import Foundation
import Testing
@testable import Elchi

/// Stage 04 pure logic: what a booking allows by status, the status ladder, live-location freshness (re-aged,
/// only ever worse), plate / phone reveal, reason and side wording, chat merging with polling, tracking link
/// lifetimes, the socket address, amendment answers, and the booking / tracking DTOs as the server sends them.
enum BookingFixture {
    /// A client booking; `status`, the vehicle's full plate and the contact rule are what the tests vary.
    static func booking(status: String = "confirmed", plate: String? = nil, phonesVisible: Bool = false, phone: String? = nil,
                        cancelled: String? = nil) -> ClientBookingDTO {
        let plateJSON = plate.map { "\"\($0)\"" } ?? "null"
        let phoneJSON = phone.map { "\"\($0)\"" } ?? "null"
        let json = Fixture.decode(JSONValue.self, """
            {"id":"bkg_1","viewer_side":"client","service_type":"parcel","service_status":"\(status)","cash_status":"unpaid",
             "parcel_category":{"id":"pct_1","code":"small_box","name_uz":"Kichik quti","name_ru":"Маленькая коробка","icon_key":"box_small",
               "max_length_cm":30,"max_width_cm":20,"max_height_cm":20,"max_weight_g":5000,"max_volume_ml":12000},
             "quantity_amendable":false,"version":3,"trip_id":"trp_1","listing_ids":{"request":"lst_1","supply":null},
             "accepted_proposal_version_id":"prv_1","quantity":1,"price_basis":"total","unit_price_minor":11500000,"total_minor":11500000,
             "currency":"UZS","payment_method":"cash",
             "pickup":{"stop":null,"point":{"lat":41.31,"lng":69.27,"district":{"id":"dst_1","name_uz":"Toshkent shahri"},"address":"Sayilgoh 35/2"},
                       "occurrence_seq":1,"window_start":"2026-09-30T04:31:00Z","window_end":"2026-09-30T06:01:00Z"},
             "dropoff":{"stop":null,"point":{"lat":39.65,"lng":66.95,"district":{"id":"dst_2","name_uz":"Samarqand"}},"occurrence_seq":3},
             "driver":{"id":"usr_d","display_name":"Demo","vehicle":{"vehicle_class":"car","seat_capacity":4,"make_model":"Chevrolet Lacetti",
               "color":"kulrang","plate_masked":"90****BB","plate_number":\(plateJSON),"plate_number_visible_from":"2026-09-30T04:01:00Z"},
               "contact_phone":\(phoneJSON)},
             "parcel_photo":{"file_id":"cargo_photo/x.jpg","url":"/api/v1/files/cargo_photo/x.jpg?exp=1&sig=s","expires_at":"2026-09-29T12:55:00Z",
               "content_type":"image/jpeg"},
             "contact":{"phones_visible":\(phonesVisible),"visible_from":null,"visible_until":null,"chat_thread_id":null,"support_available":true},
             "cancellation_policy_summary":"Pilotda bekor qilish uchun jarima yo'q.",
             "cancelled":\(cancelled ?? "null"),"promo":null,"created_at":"2026-09-29T12:13:41.026091Z","updated_at":"2026-09-29T12:13:41.026091Z"}
            """)
        return ClientBookingDTO.from(json)!
    }

    static func message(_ id: String, at: String, mine: Bool = false, text: String? = "Salom", hidden: Bool = false) -> ChatMessageDTO {
        Fixture.decode(ChatMessageDTO.self, """
            {"id":"\(id)","author_side":"\(mine ? "client" : "driver")","is_mine":\(mine),"text":\(text.map { "\"\($0)\"" } ?? "null"),
             "quick_reply_code":null,"moderation_status":"\(hidden ? "hidden_by_staff" : "visible")","created_at":"\(at)"}
            """)
    }

    static func amendment(status: String = "proposed", author: String = "driver", expires: String = "2026-09-29T12:00:00Z") -> AmendmentDTO {
        Fixture.decode(AmendmentDTO.self, """
            {"id":"amd_1","booking_id":"bkg_1","status":"\(status)","author_side":"\(author)","changes":{"unit_price_minor":12500000},
             "new_quantity":1,"new_unit_price_minor":12500000,"new_total_minor":12500000,"expires_at":"\(expires)","version":1}
            """)
    }
}

struct BookingActionsTests {
    @Test func confirmedAllowsCancelAmendShare() {
        let actions = BookingActions.of("confirmed")
        #expect(actions.canCancel && actions.canAmend && actions.canShareTracking)
        #expect(!actions.canRate && !actions.terminal)
    }

    @Test func awaitingPickupCancelsButNeverAmends() {
        // The server never accepts an amendment on a boarding trip (the web offers it here - not copied).
        let actions = BookingActions.of("awaiting_pickup")
        #expect(actions.canCancel && !actions.canAmend)
    }

    @Test func inTransitNeitherCancelsNorAmends() {
        let actions = BookingActions.of("in_transit")
        #expect(!actions.canCancel && !actions.canAmend && actions.canShareTracking && !actions.canRate)
    }

    @Test func deliveredHidesTheRecipientLink() {
        #expect(!BookingActions.of("delivered").canShareTracking)
        #expect(!BookingActions.of("delivered").canRate)
    }

    @Test func onlyCompletedRates() {
        let actions = BookingActions.of("completed")
        #expect(actions.canRate && actions.terminal && !actions.canShareTracking && !actions.canCancel)
        #expect(!BookingActions.of("cancelled").canRate)
        #expect(BookingActions.of("cancelled").terminal)
    }
}

struct StatusLadderTests {
    let created = Fixture.date("2026-09-29T08:12:00Z")

    @Test func departedIsCurrentAfterTwoDoneSteps() {
        let steps = StatusLadder.steps(status: "in_transit", createdAt: created)
        #expect(steps.map(\.state) == [.done, .done, .current, .ahead, .ahead])
        #expect(steps[2].key == "parcel.status.driverDeparted")
        // Only "Tasdiqlandi" has a time the booking really carries.
        #expect(steps[0].at == created && steps[1].at == nil && steps[2].at == nil)
    }

    @Test func completedIsAllDone() {
        #expect(StatusLadder.steps(status: "completed", createdAt: created).allSatisfy { $0.state == .done })
    }

    @Test func confirmedIsTheFirstCurrentStep() {
        #expect(StatusLadder.steps(status: "confirmed", createdAt: created).map(\.state) == [.current, .ahead, .ahead, .ahead, .ahead])
        #expect(StatusLadder.position("picked_up") == 2)
    }

    @Test func cancelledAndCustodyAreOffTheLadder() {
        for status in ["cancelled", "return_required", "returned", "delivery_failed"] {
            #expect(StatusLadder.steps(status: status, createdAt: created).isEmpty)
        }
    }
}

struct LiveFreshnessTests {
    let now = Fixture.date("2026-09-29T10:00:00Z")

    @Test func bucketsByAgeOnThePhone() {
        #expect(LiveFreshness.bucket(capturedAt: now.addingTimeInterval(-10), now: now) == .fresh)
        #expect(LiveFreshness.bucket(capturedAt: now.addingTimeInterval(-30), now: now) == .fresh)
        #expect(LiveFreshness.bucket(capturedAt: now.addingTimeInterval(-31), now: now) == .delayed)
        #expect(LiveFreshness.bucket(capturedAt: now.addingTimeInterval(-120), now: now) == .delayed)
        #expect(LiveFreshness.bucket(capturedAt: now.addingTimeInterval(-121), now: now) == .lost)
        #expect(LiveFreshness.bucket(capturedAt: nil, now: now) == .noData)
    }

    @Test func aFreshAnswerAgesOnTheDevice() {
        // The server said fresh 50 s ago: now it is delayed, never still "live".
        #expect(LiveFreshness.effective(server: .fresh, capturedAt: now.addingTimeInterval(-50), now: now) == .delayed)
        #expect(LiveFreshness.effective(server: .fresh, capturedAt: now.addingTimeInterval(-300), now: now) == .lost)
    }

    @Test func theDeviceNeverUpgradesTheServer() {
        // A young point the server calls lost (its clock, its rules) stays lost.
        #expect(LiveFreshness.effective(server: .lost, capturedAt: now.addingTimeInterval(-5), now: now) == .lost)
        #expect(LiveFreshness.effective(server: .delayed, capturedAt: now.addingTimeInterval(-5), now: now) == .delayed)
        #expect(LiveFreshness.effective(server: .noData, capturedAt: now.addingTimeInterval(-5), now: now) == .noData)
    }
}

struct DriverRevealTests {
    @Test func maskedPlateAndNoPhoneBeforeTheTripLeaves() throws {
        let reveal = try #require(DriverReveal.of(BookingFixture.booking()))
        #expect(reveal.plate == "90****BB" && !reveal.plateFull)
        #expect(reveal.phone == nil)
    }

    @Test func fullPlateOnceTheServerDisclosesIt() throws {
        let reveal = try #require(DriverReveal.of(BookingFixture.booking(status: "awaiting_pickup", plate: "90 A 123 BB")))
        #expect(reveal.plate == "90 A 123 BB" && reveal.plateFull)
    }

    @Test func phoneOnlyWhenPhonesAreVisible() throws {
        // A phone in the DTO without the visibility flag is not shown (the flag is the rule, Q44/Q142).
        #expect(try #require(DriverReveal.of(BookingFixture.booking(phone: "+998901112233"))).phone == nil)
        let open = try #require(DriverReveal.of(BookingFixture.booking(status: "in_transit", phonesVisible: true, phone: "+998901112233")))
        #expect(open.phone == "+998901112233")
        #expect(DriverReveal.dialURL("+998 90 111 22 33")?.absoluteString == "tel:+998901112233")
    }
}

struct BookingWordingTests {
    @Test func cancelReasonsAreTheDesignsFour() {
        #expect(BookingCancelReason.allCases.map(\.rawValue) == ["plans_changed", "found_other_option", "driver_unreachable", "other"])
        #expect(BookingCancelReason.key(forCode: "vehicle_problem") == "bookingCancel.reason.vehicle_problem")
        #expect(BookingCancelReason.sideKey("client") == "client.bookingDetail.bySideClient")
        #expect(BookingCancelReason.sideKey("driver") == "safety.driverTitle")
        #expect(BookingCancelReason.sideKey("operator") == "support.operator")
    }

    @MainActor @Test func sentencesExistInBothLanguages() {
        let store = LocaleStore()
        defer { store.set(.uz) }
        for locale in AppLocale.allCases {
            store.set(locale)
            for reason in BookingCancelReason.allCases { #expect(store.tOrNil(reason.key) != nil) }
            for code in ReportReasonCode.allCases { #expect(store.tOrNil("blockReport.reason.\(code.rawValue)") != nil) }
            for status in ["waiting", "assigned", "answered", "closed"] { #expect(store.tOrNil("support.status.\(status)") != nil) }
            for reason in ["parcel_not_picked_up", "booking_finished", "trip_finished", "not_yet_open"] {
                #expect(store.tOrNil("trackingWindow.\(reason)") != nil)
            }
            for code in ChatTimeline.clientQuickReplies + [.arrivingIn5Min] { #expect(store.tOrNil("quickReply.\(code.rawValue)") != nil) }
            for step in StatusLadder.keys { #expect(store.tOrNil(step) != nil) }
        }
    }

    @MainActor @Test func unratedDriverIsNeverZeroRatings() {
        let store = LocaleStore()
        store.set(.uz)
        let unrated = Fixture.decode(ReputationDTO.self, """
            {"user_id":"usr_d","service_type":"parcel","rating_count":0,"average_rating":null,"label":"new_verified","completed_bookings":0,"completed_trips":0}
            """)
        #expect(store.reputationLine(unrated) == "Yangi haydovchi · Hali baholanmagan")
        let rated = Fixture.decode(ReputationDTO.self, """
            {"user_id":"usr_d","service_type":"parcel","rating_count":38,"average_rating":4.66,"label":"rated","completed_bookings":112,"completed_trips":64}
            """)
        #expect(store.reputationLine(rated) == "★ 4,7 · 38 ta baho · 112 ta bajarilgan bron")
        // The offer card's anonymous summary says the same for an unrated driver (Stage 03 alignment with Android).
        let summary = Fixture.thread(bucket: "new_verified", ratings: 0).driverSummary!
        #expect(store.driverSummary(summary) == "Yengil avtomobil · 4 o'rin · Yangi haydovchi · Hali baholanmagan")
    }
}

struct ChatTimelineTests {
    @Test func mergeKeepsEachMessageOnceOldestFirst() {
        let a = BookingFixture.message("msg_a", at: "2026-09-29T08:15:00Z")
        let b = BookingFixture.message("msg_b", at: "2026-09-29T08:16:00Z", mine: true)
        let c = BookingFixture.message("msg_c", at: "2026-09-29T09:02:00Z")
        // The server pages newest first; a poll brings the same page again plus one new message.
        let first = ChatTimeline.merge([], [b, a])
        #expect(first.map(\.id) == ["msg_a", "msg_b"])
        let polled = ChatTimeline.merge(first, [c, b, a])
        #expect(polled.map(\.id) == ["msg_a", "msg_b", "msg_c"])
    }

    @Test func aPollTakesTheServersLatestStateOfAMessage() {
        let visible = BookingFixture.message("msg_a", at: "2026-09-29T08:15:00Z")
        let hidden = BookingFixture.message("msg_a", at: "2026-09-29T08:15:00Z", text: nil, hidden: true)
        let merged = ChatTimeline.merge([visible], [hidden])
        #expect(merged.count == 1 && merged[0].moderationStatus == .hiddenByStaff)
    }

    @Test func sameInstantOrdersById() {
        let x = BookingFixture.message("msg_x", at: "2026-09-29T08:15:00Z")
        let w = BookingFixture.message("msg_w", at: "2026-09-29T08:15:00Z")
        #expect(ChatTimeline.merge([], [x, w]).map(\.id) == ["msg_w", "msg_x"])
    }

    @Test func onlyTheDriversNewMessagesCountAsNews() {
        let old = BookingFixture.message("msg_a", at: "2026-09-29T08:15:00Z")
        let mine = BookingFixture.message("msg_b", at: "2026-09-29T08:16:00Z", mine: true)
        let theirs = BookingFixture.message("msg_c", at: "2026-09-29T08:17:00Z")
        #expect(ChatTimeline.newFromOthers([old], [old, mine, theirs]) == 1)
        #expect(ChatTimeline.newFromOthers([old, theirs], [old, theirs]) == 0)
    }

    @Test func clientQuickRepliesNeverAgreeAPrice() {
        #expect(ChatTimeline.clientQuickReplies == [.atStop, .clarifyStop])
    }

    @Test func rateLimitWaitComesFromTheServer() {
        let limited = APIError(status: 429, code: "RATE_LIMITED", message: "", details: .object(["limit": .number(20), "retry_after_s": .number(41.2)]))
        #expect(ChatTimeline.retryAfter(limited) == 42)
        #expect(ChatTimeline.retryAfter(APIError(status: 409, code: "CHAT_CLOSED", message: "", details: nil)) == nil)
    }
}

struct TrackingLinkAndSocketTests {
    @Test func lifetimesAreTheDesignsChipsInMinutes() {
        #expect(TrackingTTL.minutes == [15, 60, 180, 360, 720, 1440])
        #expect(TrackingTTL.clamp(5) == 15 && TrackingTTL.clamp(5000) == 1440 && TrackingTTL.clamp(180) == 180)
    }

    @Test func socketAddressFollowsTheAPIBase() {
        #expect(TrackingSocket.url(apiBase: URL(string: "http://127.0.0.1:8000/api/v1")!)?.absoluteString == "ws://127.0.0.1:8000/api/v2/ws")
        #expect(TrackingSocket.url(apiBase: URL(string: "https://api.elchigo.uz/api/v1")!)?.absoluteString == "wss://api.elchigo.uz/api/v2/ws")
        #expect(TrackingSocket.url(apiBase: URL(string: "ftp://x/api/v1")!) == nil)
    }

    @Test func reconnectBacksOffFiveToSixty() {
        #expect((0...5).map(TrackingSocket.backoff) == [5, 10, 20, 40, 60, 60])
    }

    @Test func socketFramesDecode() {
        let point = TrackingStream.decode(Data("""
            {"type":"tracking.point","booking_id":"bkg_1","data":{"booking_id":"bkg_1","window":{"is_open":true,"reason":"open","opens_at":null},
             "freshness":"fresh","last_point":{"lat":41.3,"lng":69.2,"accuracy_m":12,"low_accuracy":false,
             "captured_at":"2026-09-29T10:00:00Z","received_at":"2026-09-29T10:00:01Z"},"driver_arrived_at":null,
             "eta_window_start":null,"eta_window_end":null,"subject_label":null}}
            """.utf8))
        guard case .point(let dto)? = point else { Issue.record("no point"); return }
        #expect(dto.freshness == .fresh && dto.lastPoint?.accuracyM == 12)
        guard case .stale(let freshness)? = TrackingStream.decode(Data(#"{"type":"tracking.stale","data":{"freshness":"lost"}}"#.utf8)) else {
            Issue.record("no stale"); return
        }
        #expect(freshness == .lost)
        #expect(TrackingStream.decode(Data(#"{"type":"hello"}"#.utf8)) == nil)
    }
}

struct AmendmentActionsTests {
    let now = Fixture.date("2026-09-29T10:00:00Z")

    @Test func theDriversOpenProposalIsTheClientsToAnswer() {
        let actions = AmendmentActions.of(BookingFixture.amendment(), bookingStatus: "confirmed", now: now)
        #expect(actions.open && actions.canAccept && actions.canReject && !actions.canWithdraw)
    }

    @Test func theClientsOwnCanOnlyBeWithdrawn() {
        let actions = AmendmentActions.of(BookingFixture.amendment(author: "client"), bookingStatus: "confirmed", now: now)
        #expect(!actions.canAccept && !actions.canReject && actions.canWithdraw)
    }

    @Test func expiredOrMovedOnOffersNothing() {
        let expired = BookingFixture.amendment(expires: "2026-09-29T09:00:00Z")
        #expect(!AmendmentActions.of(expired, bookingStatus: "confirmed", now: now).open)
        #expect(AmendmentActions.status(expired, bookingStatus: "confirmed", now: now).key == "status.expired")
        // Still `proposed` on the server, but the booking has left `confirmed`: closed, not answerable.
        let stale = BookingFixture.amendment()
        #expect(!AmendmentActions.of(stale, bookingStatus: "awaiting_pickup", now: now).open)
        #expect(AmendmentActions.status(stale, bookingStatus: "awaiting_pickup", now: now).key == "client.amendment.statusClosed")
        #expect(AmendmentActions.status(BookingFixture.amendment(status: "accepted"), bookingStatus: "confirmed", now: now).tone == .ok)
    }
}

struct BookingDTOTests {
    @Test func detailFieldsDecode() throws {
        let booking = BookingFixture.booking()
        #expect(booking.version == 3)
        #expect(booking.driver?.vehicle.makeModel == "Chevrolet Lacetti")
        #expect(booking.parcelCategory?.code == "small_box")
        #expect(booking.parcelPhoto?.url.hasPrefix("/api/v1/files/") == true)
        #expect(booking.contact?.phonesVisible == false)
    }

    @Test func cancellationDecodes() throws {
        let booking = BookingFixture.booking(status: "cancelled", cancelled: """
            {"by_side":"driver","reason_code":"vehicle_problem","fault_side":null,"at":"2026-09-25T13:40:00Z"}
            """)
        #expect(booking.cancelled?.bySide == "driver" && booking.cancelled?.reasonCode == "vehicle_problem")
    }

    @Test func supportTimesWithAnOffsetParse() {
        // Support threads come with +05:00 offsets, bookings with Z: both are the same instant.
        #expect(ServerTime.parse("2026-09-29T17:13:41.123456+05:00") == ServerTime.parse("2026-09-29T12:13:41.123456Z"))
        #expect(ServerTime.parse("2026-09-29T17:13:41+05:00") == Fixture.date("2026-09-29T12:13:41Z"))
    }
}
