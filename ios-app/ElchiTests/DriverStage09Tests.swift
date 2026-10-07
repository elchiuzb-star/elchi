import Foundation
import Testing
@testable import Elchi

/// Stage 09 driver logic: the driver view of a booking (decoding, actions by status for a parcel, cash to collect,
/// commission, receiver visibility, cancel reasons and refusals, rating window, the list filter, amendments from the
/// driver's side), the wallet (tiles, the 7-day chart, the top-up body, status badges), the profile figures (never an
/// invented rating) and the driver's notification targets.
enum DriverBookingFixture {
    static func json(status: String = "confirmed", receiverPhone: String? = nil, promo: Bool = false, client: Bool = true,
                     updatedAt: String = "2026-09-29T12:13:41Z", viewer: String = "driver") -> JSONValue {
        let phoneJSON = receiverPhone.map { "\"\($0)\"" } ?? "null"
        let promoJSON = promo ? """
            {"view":"driver","fare_minor":12000000,"passenger_discount_minor":1000000,"cash_to_collect_minor":11000000,
             "base_commission_minor":1800000,"passenger_discount_covered_minor":1000000,"driver_credit_minor":200000,
             "commission_charged_minor":600000,"driver_keeps_minor":10400000,"currency":"UZS"}
            """ : "null"
        return Fixture.decode(JSONValue.self, """
            {"id":"bkg_1","viewer_side":"\(viewer)","service_type":"parcel","service_status":"\(status)","cash_status":"unpaid",
             "parcel_category":{"id":"pct_1","code":"small_box","name_uz":"Kichik quti","name_ru":"Маленькая коробка","icon_key":"box_small",
               "max_length_cm":30,"max_width_cm":20,"max_height_cm":20,"max_weight_g":5000,"max_volume_ml":12000},
             "quantity_amendable":false,"version":3,"trip_id":"trp_9","listing_ids":{"request":"lst_1","supply":null},
             "accepted_proposal_version_id":"prv_1","quantity":1,"price_basis":"total","unit_price_minor":12000000,"total_minor":12000000,
             "currency":"UZS","payment_method":"cash",
             "pickup":{"point":{"lat":41.31,"lng":69.27,"district":{"id":"dst_1","name_uz":"Chilonzor"}},
                       "window_start":"2026-09-30T04:31:00Z","window_end":"2026-09-30T06:01:00Z"},
             "dropoff":{"point":{"lat":39.65,"lng":66.97,"address":"Registon","district":{"id":"dst_2","name_uz":"Samarqand"}},"planned_arrival_at":"2026-09-30T10:00:00Z"},
             "driver":{"id":"usr_d","display_name":"Demo","vehicle":{"vehicle_class":"car","seat_capacity":4,"make_model":"Lacetti",
               "color":"kulrang","plate_masked":"90****BB","plate_number":null}},
             "client":\(client ? #"{"id":"usr_c","display_name":"Aziza"}"# : "null"),
             "parcel_contacts":{"receiver_name":"Dilnoza","receiver_phone":\(phoneJSON)},
             "contact":{"phones_visible":false,"visible_from":"2026-09-30T04:00:00Z","visible_until":null,"chat_thread_id":null,"support_available":true},
             "policy_versions":{"listing_version":1,"listing_terms_version":1,"cancellation_policy":"standard"},
             "cancellation_policy_summary":"Pilotda jarima yo'q.","cancelled":null,"promo":\(promoJSON),
             "commission_status":"held","fee":{"policy_id":"pol_1","policy_kind":"standard","fee_bps":1500,"commission_minor":1800000,"net_minor":10200000},
             "created_at":"2026-09-29T12:13:41Z","updated_at":"\(updatedAt)"}
            """)
    }

    static func booking(status: String = "confirmed", receiverPhone: String? = nil, promo: Bool = false, client: Bool = true,
                        updatedAt: String = "2026-09-29T12:13:41Z") -> DriverBookingDTO {
        DriverBookingDTO.from(json(status: status, receiverPhone: receiverPhone, promo: promo, client: client, updatedAt: updatedAt))!
    }
}

struct DriverBookingTests {
    @Test func decodesTheDriverViewOnly() throws {
        let booking = DriverBookingFixture.booking(promo: true)
        #expect(booking.id == "bkg_1" && booking.tripId == "trp_9")
        #expect(booking.client?.displayName == "Aziza")
        #expect(booking.fee?.feeBps == 1500)
        #expect(booking.promo?.cashToCollectMinor == 11_000_000)
        #expect(booking.base.totalMinor == 12_000_000)
        #expect(DriverBookingDTO.from(DriverBookingFixture.json(viewer: "client")) == nil)
        // and the client's own decoder never takes the driver's view
        #expect(ClientBookingDTO.from(DriverBookingFixture.json()) == nil)
    }

    @Test func confirmedArrivesAmendsCancels() {
        let actions = DriverBookingActions.of("confirmed")
        #expect(actions.canArrive && actions.canAmend && actions.canCancel)
        #expect(!actions.canRate && !actions.inTransit && !actions.terminal)
        #expect(!DriverBookingActions.of("confirmed", arrivedSent: true).canArrive) // "Keldim" once
    }

    @Test func boardingArrivesAndCancelsButAmendmentsWait() {
        let actions = DriverBookingActions.of("awaiting_pickup")
        #expect(actions.canArrive && actions.canCancel)
        #expect(!actions.canAmend) // the server's accept refuses once the trip left `planned`
    }

    @Test func departedIsTheOperatorsToRecord() {
        for status in ["in_transit", "picked_up"] {
            let actions = DriverBookingActions.of(status)
            #expect(actions.inTransit && !actions.canArrive && !actions.canCancel && !actions.canAmend && !actions.canRate)
        }
        let delivered = DriverBookingActions.of("delivered")
        #expect(!delivered.inTransit && !delivered.canRate && !delivered.terminal)
    }

    @Test func ratingTheClientIsOpenSevenDaysAfterCompletion() {
        let done = ServerTime.parse("2026-09-29T12:00:00Z")!
        #expect(DriverBookingActions.of("completed", updatedAt: done, now: done.addingTimeInterval(6 * 86_400)).canRate)
        #expect(!DriverBookingActions.of("completed", updatedAt: done, now: done.addingTimeInterval(8 * 86_400)).canRate)
        #expect(DriverBookingActions.of("completed").terminal)
        #expect(!DriverBookingActions.of("cancelled").canRate)
    }

    @Test func cashToCollectIsTheDiscountedAmountWhenThereIsOne() {
        #expect(DriverBookingMoney.cashToCollect(DriverBookingFixture.booking()) == 12_000_000)
        #expect(DriverBookingMoney.cashToCollect(DriverBookingFixture.booking(promo: true)) == 11_000_000)
    }

    @Test func commissionIsTheDriversToSee() throws {
        let plain = try #require(DriverBookingMoney.commission(DriverBookingFixture.booking()))
        #expect(plain.minor == 1_800_000 && plain.percent == "15")
        let promo = try #require(DriverBookingMoney.commission(DriverBookingFixture.booking(promo: true)))
        #expect(promo.minor == 600_000) // what the balance is actually charged
    }

    @Test func receiverPhoneOnlyWhenTheServerSentIt() throws {
        #expect(ReceiverReveal.of(DriverBookingFixture.booking()) == nil)
        #expect(ReceiverReveal.of(DriverBookingFixture.booking(receiverPhone: "")) == nil)
        let shown = try #require(ReceiverReveal.of(DriverBookingFixture.booking(status: "in_transit", receiverPhone: "+998915552211")))
        #expect(shown.name == "Dilnoza" && shown.phone == "+998915552211")
    }

    @Test func theFourDriverReasonsAndTheRefusals() {
        #expect(DriverCancelReason.allCases.map(\.rawValue) == ["trip_changed", "vehicle_problem", "client_unreachable", "other"])
        #expect(DriverCancelReason.tripChanged.key == "bookingCancel.reason.trip_changed")
        func refusal(_ code: String) -> String? { DriverCancelReason.refusalKey(APIError(status: 409, code: code, message: "", details: nil)) }
        #expect(refusal("VERSION_CONFLICT") == "bookingCancel.refused.changed")
        #expect(refusal("CUSTODY_REQUIRES_RETURN_FLOW") == "bookingCancel.refused.custody")
        #expect(refusal("NO_SHOW_REVIEW_PENDING") == "bookingCancel.refused.noShowPending")
        #expect(refusal("INVALID_STATE_TRANSITION") == "bookingCancel.refused.tooLate")
        #expect(refusal("RATE_LIMITED") == nil)
    }

    @Test func filterSplitsActiveAndHistory() {
        #expect(DriverBookingFilter.active.includes("confirmed") && DriverBookingFilter.active.includes("delivered"))
        #expect(DriverBookingFilter.history.includes("completed") && DriverBookingFilter.history.includes("cancelled"))
        #expect(!DriverBookingFilter.history.includes("in_transit"))
    }

    @Test func listBadgeUsesParcelWording() {
        #expect(StatusLabel.booking(.parcel, "in_transit").key == "parcel.status.driverDeparted")
        #expect(StatusLabel.booking(.parcel, "delivered").key == "parcel.progress.deliveredByOperator")
        #expect(StatusLabel.booking(.parcel, "awaiting_pickup").tone == .warn)
    }

    @Test func amendmentsFromTheDriversSide() {
        let now = ServerTime.parse("2026-09-29T10:00:00Z")!
        let clients = BookingFixture.amendment(author: "client")
        let mine = BookingFixture.amendment(author: "driver")
        let answer = AmendmentActions.of(clients, bookingStatus: "confirmed", now: now, side: "driver")
        #expect(answer.canAccept && answer.canReject && !answer.canWithdraw)
        let own = AmendmentActions.of(mine, bookingStatus: "confirmed", now: now, side: "driver")
        #expect(own.canWithdraw && !own.canAccept)
        #expect(!AmendmentActions.of(mine, bookingStatus: "awaiting_pickup", now: now, side: "driver").open)
    }

    @Test func clientReputationNeverInventsAScore() {
        let fresh = ReputationDTO(completedBookings: 2, completedTrips: 0, label: .newVerified, ratingCount: 0, serviceType: .parcel, userId: "usr_c")
        let line = ClientReputation.line(fresh)
        #expect(line.score == nil && line.completed == 2)
        let rated = ReputationDTO(averageRating: 4.75, completedBookings: 9, completedTrips: 0, label: .rated, ratingCount: 4, serviceType: .parcel,
                                  userId: "usr_c")
        #expect(ClientReputation.line(rated).score == "4,8")
    }

    @Test func driverQuickRepliesNeverAgreePrice() {
        #expect(ChatTimeline.driverQuickReplies == [.arrivingIn5Min, .atStop, .clarifyStop])
        #expect(!ChatTimeline.driverQuickReplies.contains(.priceAgreed))
    }
}

// MARK: - Wallet

enum WalletFixture {
    static let wallet = WalletDTO(asOf: "2026-10-01T09:00:00Z", availableMinor: 51_680_000, currency: .uzs, heldMinor: 13_320_000, id: "wal_1",
                                  pendingTopupsMinor: 2_000_000, postedBalanceMinor: 65_000_000)

    static func line(_ kind: String, _ direction: String, _ minor: Int, at: String) -> LedgerLineDTO {
        LedgerLineDTO(amountMinor: minor, balanceAfterMinor: 0, direction: direction, kind: kind, occurredAt: at,
                      reference: LedgerReferenceDTO(id: "x", type: kind), transactionId: UUID().uuidString)
    }
}

struct WalletLogicTests {
    @Test func tilesComeFromTheWalletAndTheLedger() {
        let lines = [WalletFixture.line("topup", "credit", 20_000_000, at: "2026-09-30T08:00:00Z"),
                     WalletFixture.line("topup", "credit", 30_000_000, at: "2026-09-29T08:00:00Z"),
                     WalletFixture.line("reversal", "credit", 480_000, at: "2026-09-29T09:00:00Z"),
                     WalletFixture.line("commission_capture", "debit", 1_920_000, at: "2026-09-30T10:00:00Z"),
                     WalletFixture.line("adjustment", "debit", 100_000, at: "2026-09-30T10:00:00Z")]
        let tiles = WalletLogic.tiles(wallet: WalletFixture.wallet, lines: lines)
        #expect(tiles.heldMinor == 13_320_000 && tiles.pendingTopupsMinor == 2_000_000)
        #expect(tiles.topupsMinor == 50_000_000)
        #expect(tiles.reversedMinor == 480_000)
        #expect(tiles.capturedMinor == 1_920_000)
    }

    @Test func chartIsSevenTashkentDaysOfCaptures() {
        let now = ServerTime.parse("2026-10-01T10:00:00Z")! // 15:00 in Tashkent
        let lines = [WalletFixture.line("commission_capture", "debit", 1_000_000, at: "2026-09-30T20:30:00Z"), // 01:30 Oct 1 Tashkent
                     WalletFixture.line("commission_capture", "debit", 500_000, at: "2026-09-25T10:00:00Z"),
                     WalletFixture.line("commission_capture", "debit", 700_000, at: "2026-09-20T10:00:00Z"), // too old
                     WalletFixture.line("topup", "credit", 9_000_000, at: "2026-10-01T09:00:00Z")]
        let bars = WalletLogic.chart(lines, now: now)
        #expect(bars.count == 7)
        #expect(bars.last?.minor == 1_000_000)
        #expect(bars.first?.minor == 500_000)
        #expect(bars.map(\.minor).reduce(0, +) == 1_500_000)
        #expect(WalletLogic.chartIsEmpty(WalletLogic.chart([], now: now)))
    }

    @Test func topupBodyIsWholeSoumWithOptionalFields() throws {
        let body = try #require(WalletLogic.topupBody(amountText: "100 000", method: "bank_transfer", payerReference: "  +998 90 123 ", note: ""))
        #expect(body.amountMinor == 10_000_000 && body.method == "bank_transfer")
        #expect(body.payerReference == "+998 90 123" && body.note == nil && body.evidenceFileId == nil)
        #expect(WalletLogic.topupBody(amountText: "0", method: "bank_transfer", payerReference: "", note: "") == nil)
        #expect(WalletLogic.topupBody(amountText: "500", method: "card", payerReference: "", note: "") == nil)
        let long = try #require(WalletLogic.topupBody(amountText: "1", method: "cash_desk", payerReference: String(repeating: "x", count: 200), note: ""))
        #expect(long.payerReference?.count == 128)
    }

    @Test func requestBadges() {
        #expect(WalletLogic.status(.pending).key == "status.pending")
        #expect(WalletLogic.status(.awaitingSecondApproval).key == "status.awaiting_second_approval")
        #expect(WalletLogic.status(.awaitingSecondApproval).tone == .warn)
        #expect(WalletLogic.status(.approved).tone == .ok)
        #expect(WalletLogic.status(.rejected).tone == .err)
    }

    @Test func transactionSignAndKind() {
        #expect(WalletLogic.sign(WalletFixture.line("topup", "credit", 1, at: "2026-10-01T00:00:00Z")) == "+")
        #expect(WalletLogic.sign(WalletFixture.line("commission_capture", "debit", 1, at: "2026-10-01T00:00:00Z")) == "−")
        #expect(WalletLogic.kindKey(WalletFixture.line("reversal", "credit", 1, at: "2026-10-01T00:00:00Z")) == "driver.wallet.kind.reversal")
    }
}

// MARK: - Profile, notifications, strings

struct DriverProfileStage09Tests {
    @Test func statsNeverInventARating() {
        let fresh = ReputationDTO(completedBookings: 0, completedTrips: 0, label: .newVerified, ratingCount: 0, serviceType: .parcel, userId: "u")
        let values = DriverProfileStats.make(reputation: fresh, profile: DriverFixture.profile(status: "approved"))
        #expect(values.rating == nil) // "Yangi"
        #expect(values.completed == 0)
        let unknown = DriverProfileStats.make(reputation: nil, profile: nil)
        #expect(unknown.rating == nil && unknown.completed == nil && unknown.legacyTotal == nil) // "—", not 0
        let rated = ReputationDTO(averageRating: 4.8, completedBookings: 112, completedTrips: 40, label: .rated, ratingCount: 30,
                                  serviceType: .parcel, userId: "u")
        #expect(DriverProfileStats.make(reputation: rated, profile: nil).rating == "4,8")
    }

    @Test func routesCountIsWhatIsAheadOrRunning() {
        let trips = [MarketFixture.trip(id: "a", status: .planned), MarketFixture.trip(id: "b", status: .inProgress),
                     MarketFixture.trip(id: "c", status: .completed), MarketFixture.trip(id: "d", status: .cancelled)]
        #expect(DriverProfileStats.routesCount(trips) == 2)
    }

    @Test func quickActionsInTheDesignsOrder() {
        #expect(DriverProfileAction.allCases == [.form, .documents, .routes, .proposals, .bonus, .orders, .threads, .safety, .help, .settings, .logout])
        #expect(DriverProfileAction.form.hintKey == "driver.profile.editHint")
        #expect(DriverProfileAction.settings.hintKey == "driver.profile.settingsHint")
    }

    @Test func driverCreditIsTheDriversBucket() {
        let balance = Fixture.decode(PromoBalanceDTO.self, """
            {"buckets":[{"instrument":"driver_credit","service_type":"parcel","available_minor":200000,"reserved_minor":0,"under_review_minor":0,
              "consumed_minor":0,"expired_minor":0,"reversed_minor":0,"next_expiry_at":null},
             {"instrument":"passenger_bonus","service_type":"parcel","available_minor":100000,"reserved_minor":0,"under_review_minor":0,
              "consumed_minor":0,"expired_minor":0,"reversed_minor":0,"next_expiry_at":null}],"lots":[]}
            """)
        #expect(PromoLogic.buckets(balance, audience: "driver").map(\.instrument) == [.driverCredit])
        #expect(PromoLogic.buckets(balance, audience: "client").map(\.instrument) == [.passengerBonus])
    }

    @Test func driverNotificationTargets() {
        #expect(Inbox.target("/wallet") == .wallet)
        #expect(Inbox.target("/api/v2/wallet") == .wallet)
        #expect(Inbox.target("/bookings/bkg_1/messages") == .booking("bkg_1", chat: true))
        #expect(Inbox.target("/proposals/prt_1") == .proposal("prt_1"))
        #expect(Inbox.target("/trips/trp_1") == .trip("trp_1"))
    }

    @MainActor @Test func stage09KeysAreInTheDictionary() {
        let strings = LocaleStore()
        let keys = ["driver.wallet.method.bank_transfer", "driver.wallet.method.cash_desk", "driver.wallet.methodLabel", "driver.wallet.noteLabel",
                    "driver.wallet.transactionsTitle", "driver.wallet.transactionsEmpty", "driver.wallet.balanceAfter",
                    "driver.wallet.kind.topup", "driver.wallet.kind.commission_capture", "driver.wallet.kind.reversal",
                    "driver.wallet.kind.adjustment", "driver.wallet.chartTitle", "driver.wallet.amountInvalid", "driver.booking.arrivedSent",
                    "driver.booking.commission", "driver.booking.commissionValue", "driver.booking.inTransitNote",
                    "driver.booking.clientFallback", "driver.booking.clientTitle", "driver.booking.rateNote", "driver.orders.filterActive",
                    "driver.orders.filterHistory", "driver.profile.totalLegacy", "driver.safety.blocked", "driver.safety.blockConfirmTitle",
                    "driver.proposals.bookingReady", "driver.bonus.noCreditTitle", "driver.bonus.noCreditSubtitle"]
        for key in keys { #expect(strings.tOrNil(key) != nil, "missing \(key)") }
    }
}
