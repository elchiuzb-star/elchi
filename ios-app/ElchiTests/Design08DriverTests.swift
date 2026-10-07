import Foundation
import Testing
@testable import Elchi

/// BOSQICH 08 v3 ("Elchi Haydovchi Bron") and BOSQICH 09 v3 ("Elchi Haydovchi Hamyon"), driver side: the list badge
/// (short words, the pending no-show review), the detail's map chip and GPS warning from the local tracker, the
/// ladder, the open amendment, the contact bar's phone and refusal, the tracking note; the wallet's 6-month chart,
/// the two-person hint, presets and the payment purpose; the profile rows.
enum Design08Fixture {
    /// The parcel fixture, turned into a passenger booking or given a no-show review / phones on request.
    static func booking(status: String = "confirmed", passenger: Bool = false, noShow: String? = nil, phonesVisible: Bool = false,
                        clientPhone: String? = nil, receiverPhone: String? = nil, priceBasis: String? = nil) -> DriverBookingDTO {
        guard case .object(var object) = DriverBookingFixture.json(status: status, receiverPhone: receiverPhone) else { fatalError() }
        if passenger {
            object["service_type"] = .string("passenger")
            object["parcel_category"] = .null
            object["parcel_contacts"] = .null
            object["quantity"] = .number(2)
            object["price_basis"] = .string(priceBasis ?? "per_seat")
            object["unit_price_minor"] = .number(15_000_000)
            object["total_minor"] = .number(30_000_000)
        }
        if let noShow {
            object["no_show_review"] = .object(["status": .string(noShow), "reported_at": .string("2026-09-30T05:20:00Z"), "decided_at": .null])
        }
        if phonesVisible, case .object(var contact)? = object["contact"] {
            contact["phones_visible"] = .bool(true)
            object["contact"] = .object(contact)
        }
        if let clientPhone {
            object["client"] = .object(["id": .string("usr_c"), "display_name": .string("Aziza"), "contact_phone": .string(clientPhone)])
        }
        return DriverBookingDTO.from(.object(object))!
    }

    static func amendment(_ status: String, author: String = "driver", reason: String? = "yuk og'irroq", id: String = "amd_1") -> AmendmentDTO {
        AmendmentDTO(authorSide: author, bookingId: "bkg_1", changes: .object(reason.map { ["reason": .string($0)] } ?? [:]),
                     expiresAt: "2026-09-30T06:00:00Z", id: id, newQuantity: 2, newTotalMinor: 32_000_000, newUnitPriceMinor: 16_000_000,
                     status: status, version: 1)
    }
}

struct Design08BadgeTests {
    @Test func listUsesTheShortParcelWordsDetailTheLongOnes() {
        #expect(DriverBookingBadge.label(.parcel, "in_transit", noShowPending: false, short: true).key == "status.in_transit")
        #expect(DriverBookingBadge.label(.parcel, "delivered", noShowPending: false, short: true).key == "status.delivered")
        #expect(DriverBookingBadge.label(.parcel, "in_transit", noShowPending: false, short: false).key == "parcel.status.driverDeparted")
        #expect(DriverBookingBadge.label(.parcel, "delivered", noShowPending: false, short: false).key == "parcel.progress.deliveredByOperator")
        #expect(DriverBookingBadge.label(.passenger, "onboard", noShowPending: false, short: true).key == "status.onboard")
    }

    @Test func pendingNoShowReviewIsNeverABareKelmadi() {
        let pending = Design08Fixture.booking(status: "awaiting_pickup", passenger: true, noShow: "pending")
        for short in [true, false] {
            let label = DriverBookingBadge.of(pending.base, short: short)
            #expect(label.key == "driver.v3bkg.noShowReviewBadge")
            #expect(label.tone == .err)
        }
        // a rejected report: back to the status itself
        let rejected = Design08Fixture.booking(status: "awaiting_pickup", passenger: true, noShow: "rejected")
        #expect(DriverBookingBadge.of(rejected.base, short: true).key == "status.awaiting_pickup")
    }

    @Test func seatPriceOnlyForPerSeatPassengerWithoutPromo() {
        #expect(DriverBookingLayout.showsSeatPrice(Design08Fixture.booking(passenger: true)))
        #expect(!DriverBookingLayout.showsSeatPrice(Design08Fixture.booking(passenger: true, priceBasis: "total")))
        #expect(!DriverBookingLayout.showsSeatPrice(Design08Fixture.booking()))
        #expect(!DriverBookingLayout.showsSeatPrice(DriverBookingFixture.booking(promo: true)))
    }
}

struct Design08DetailTests {
    @Test func chipFollowsTheLocalTrackerNotTheServer() {
        #expect(DriverBookingLayout.chip(status: "onboard", sending: true) == .live)
        #expect(DriverBookingLayout.chip(status: "in_transit", sending: false) == .gpsOff)
        #expect(DriverBookingLayout.chip(status: "awaiting_pickup", sending: true) == .tracking)
        #expect(DriverBookingLayout.chip(status: "completed", sending: false) == .tracking)
        #expect(DriverBookingLayout.Chip.tracking.key == "bookingDetail.tracking")
        #expect(DriverBookingLayout.gpsOffWarning(status: "onboard", sending: false))
        #expect(!DriverBookingLayout.gpsOffWarning(status: "onboard", sending: true))
        #expect(!DriverBookingLayout.gpsOffWarning(status: "awaiting_pickup", sending: false))
    }

    @Test func arrivedNoteIsPassengerOnly() {
        #expect(DriverBookingLayout.arrivedNote(.passenger, "arrived"))
        #expect(!DriverBookingLayout.arrivedNote(.parcel, "delivered"))
        #expect(!DriverBookingLayout.arrivedNote(.passenger, "onboard"))
    }

    @Test func ladderStopsWithACrossOnPickup() {
        #expect(DriverBookingLayout.ladder(Design08Fixture.booking(status: "onboard", passenger: true).base) == .init(current: 2, cross: nil))
        #expect(DriverBookingLayout.ladder(Design08Fixture.booking(status: "cancelled").base) == .init(current: nil, cross: 1))
        let pending = Design08Fixture.booking(status: "awaiting_pickup", passenger: true, noShow: "pending")
        #expect(DriverBookingLayout.ladder(pending.base) == .init(current: 0, cross: 1))
    }

    @Test func amendNoticeIsTheDriversNewestProposal() {
        #expect(DriverBookingLayout.amendNotice(nil) == nil)
        #expect(DriverBookingLayout.amendNotice([Design08Fixture.amendment("proposed", author: "client")]) == nil)
        let pending = Design08Fixture.amendment("proposed")
        #expect(DriverBookingLayout.amendNotice([pending]) == .pending(pending, reason: "yuk og'irroq"))
        let accepted = Design08Fixture.amendment("accepted", id: "amd_2")
        #expect(DriverBookingLayout.amendNotice([accepted, pending]) == .accepted(accepted))
        #expect(DriverBookingLayout.amendNotice([Design08Fixture.amendment("rejected")]) == nil)
        let noReason = Design08Fixture.amendment("proposed", reason: nil)
        #expect(DriverBookingLayout.amendNotice([noReason]) == .pending(noReason, reason: nil))
    }

    @Test func passengerPhoneOpensAtBoardingOnly() {
        let before = Design08Fixture.booking(status: "awaiting_pickup", passenger: true, clientPhone: "+998901234567")
        #expect(DriverBookingLayout.phone(before) == .locked)
        #expect(DriverBookingLayout.callRefusalKey(.locked, service: .passenger) == "driver.trip.phoneAfterBoard")
        let aboard = Design08Fixture.booking(status: "onboard", passenger: true, phonesVisible: true, clientPhone: "+998901234567")
        #expect(DriverBookingLayout.phone(aboard) == .visible("+998901234567"))
        #expect(DriverBookingLayout.phone(Design08Fixture.booking(status: "completed", passenger: true)) == .closed)
        #expect(DriverBookingLayout.callRefusalKey(.closed, service: .passenger) == "client.booking.callClosed")
    }

    @Test func parcelCallsTheReceiverAfterDepartureNeverTheSender() {
        #expect(DriverBookingLayout.phone(Design08Fixture.booking(status: "awaiting_pickup")) == .locked)
        #expect(DriverBookingLayout.callRefusalKey(.locked, service: .parcel) == "client.booking.callLockedParcel")
        let departed = Design08Fixture.booking(status: "in_transit", receiverPhone: "+998911112233")
        #expect(DriverBookingLayout.phone(departed) == .visible("+998911112233"))
        // the client's (sender's) phone is ignored for a parcel even when sent
        let sender = Design08Fixture.booking(status: "in_transit", phonesVisible: true, clientPhone: "+998901234567")
        #expect(DriverBookingLayout.phone(sender) == .locked)
    }

    @Test func trackingNoteSaysBackgroundOnlyWhenItRuns() {
        #expect(DriverBookingLayout.trackingNoteKeys(backgroundUpdates: true) == ["driver.v3bkg.trackingNote", "driver.gps.backgroundOn"])
        #expect(DriverBookingLayout.trackingNoteKeys(backgroundUpdates: false) == ["driver.v3bkg.trackingNote", "driverTracking.foregroundOnly"])
    }
}

struct Design09WalletTests {
    @Test func sixMonthsFromTheLoadedPages() {
        let now = Fixture.date("2026-10-07T09:00:00Z")
        let lines = [
            WalletFixture.line("commission_capture", "debit", 1_000_000, at: "2026-10-01T09:00:00Z"),
            WalletFixture.line("commission_capture", "debit", 500_000, at: "2026-10-05T09:00:00Z"),
            WalletFixture.line("commission_capture", "debit", 700_000, at: "2026-05-20T09:00:00Z"),
            WalletFixture.line("commission_capture", "debit", 900_000, at: "2026-04-20T09:00:00Z"), // 7th month back: out
            WalletFixture.line("topup", "credit", 9_000_000, at: "2026-10-02T09:00:00Z"),
        ]
        let bars = WalletLogic.chart(lines, period: .monthly, now: now)
        #expect(bars.count == 6)
        #expect(bars.last?.minor == 1_500_000)
        #expect(bars.first?.minor == 700_000)
        #expect(bars.map(\.minor).reduce(0, +) == 2_200_000)
        #expect(WalletLogic.chart(lines, period: .daily, now: now).count == 7)
        #expect(WalletLogic.Period.monthly.labelKey == "income.period.monthly")
    }

    @Test func largeAmountAboveTheTwoPersonThreshold() {
        #expect(WalletLogic.twoPersonThresholdMinor == 100_000_000)
        #expect(!WalletLogic.largeAmount("1000000"))
        #expect(WalletLogic.largeAmount("1000001"))
        #expect(!WalletLogic.largeAmount(""))
    }

    @Test func paymentPurposeIsTheDriversOwnPhone() {
        #expect(WalletLogic.paymentPurposePhone("+998907771122") == "90 777 11 22")
        #expect(WalletLogic.paymentPurposePhone(nil) == nil)
        #expect(WalletLogic.paymentPurposePhone("123") == nil)
        #expect(WalletLogic.presetsSoum == [50_000, 100_000, 200_000, 500_000])
    }
}

struct Design09ProfileTests {
    @Test func walletRowAfterBonusAndSafetyHint() {
        let order = DriverProfileAction.allCases
        #expect(order.count == 12)
        #expect(order.firstIndex(of: .wallet) == order.firstIndex(of: .bonus).map { $0 + 1 })
        #expect(DriverProfileAction.wallet.titleKey == "income.title")
        #expect(DriverProfileAction.wallet.hintKey == "income.topupTitle")
        #expect(DriverProfileAction.wallet.icon == .wallet)
        #expect(DriverProfileAction.bonus.icon == .gift)
        #expect(DriverProfileAction.safety.hintKey == "safety.centerDescription")
    }
}
