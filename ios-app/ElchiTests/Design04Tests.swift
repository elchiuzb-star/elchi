import Foundation
import Testing
@testable import Elchi

/// BOSQICH 04 ("Elchi Bron"): the redesigned booking detail's rules - badge words and tones, the five dots, the
/// notices per status, share availability, the phone and call refusals (Q44/Q142), the unseen chat count, the rating
/// card (completed only) and its words, the amendment form's tap-to-validate, the tracking window card and the
/// freshness notes, the cancelled ladder, and every new sentence in both languages.
struct Design04BadgeTests {
    @Test func clientBadgeFollowsTheDesign() {
        #expect(StatusLabel.clientBooking(.parcel, "confirmed") == StatusLabel(key: "status.confirmed", raw: "confirmed", tone: .warn))
        #expect(StatusLabel.clientBooking(.parcel, "awaiting_pickup").key == "parcel.progress.tripPreparing")
        #expect(StatusLabel.clientBooking(.passenger, "awaiting_pickup").key == "status.awaiting_pickup")
        #expect(StatusLabel.clientBooking(.parcel, "completed") == StatusLabel(key: "app.progress.completed", raw: "completed", tone: .ok))
        #expect(StatusLabel.clientBooking(.passenger, "arrived").tone == .ok)
        #expect(StatusLabel.clientBooking(.parcel, "in_transit").key == "parcel.status.driverDeparted")
        #expect(StatusLabel.clientBooking(.parcel, "cancelled").tone == .err)
    }

    @Test func theDriversBadgeIsUnchanged() {
        #expect(StatusLabel.booking(.parcel, "completed").key == "status.completed")
        #expect(StatusLabel.booking(.parcel, "awaiting_pickup").key == "status.awaiting_pickup")
    }

    @Test func taxiLadderSaysTheStatusNotTheStop() {
        #expect(PassengerStatus.ladder[1] == "status.awaiting_pickup")
        #expect(StatusLadder.steps(status: "awaiting_pickup", createdAt: nil, service: .passenger).map(\.key)
            == ["status.confirmed", "status.awaiting_pickup", "status.onboard", "status.arrived", "app.progress.completed"])
    }
}

struct Design04TrackerTests {
    @Test func dotsFollowTheLadder() {
        #expect(BookingDetailRules.tracker("confirmed", service: .parcel) == .init(current: 0, cancelled: false))
        #expect(BookingDetailRules.tracker("in_transit", service: .parcel) == .init(current: 2, cancelled: false))
        #expect(BookingDetailRules.tracker("onboard", service: .passenger) == .init(current: 2, cancelled: false))
        #expect(BookingDetailRules.tracker("completed", service: .passenger) == .init(current: 4, cancelled: false))
    }

    @Test func cancelledIsAllGreyWithTheCross() {
        #expect(BookingDetailRules.tracker("cancelled", service: .parcel) == .init(current: nil, cancelled: true))
        #expect(BookingDetailRules.tracker("no_show", service: .passenger)?.cancelled == true)
    }

    @Test func custodyStatesShowNoDots() {
        for status in ["return_required", "returned", "delivery_failed"] {
            #expect(BookingDetailRules.tracker(status, service: .parcel) == nil)
        }
    }

    @Test func cancelledLadderHasTwoSteps() {
        let created = Date(timeIntervalSince1970: 1_000), cancelled = Date(timeIntervalSince1970: 2_000)
        let steps = StatusLadder.cancelledSteps(status: "cancelled", createdAt: created, cancelledAt: cancelled)
        #expect(steps?.map(\.state) == [.done, .failed])
        #expect(steps?.map(\.key) == ["status.confirmed", "bookingCancel.cancelledBy"])
        #expect(steps?.map(\.at) == [created, cancelled])
        #expect(StatusLadder.cancelledSteps(status: "confirmed", createdAt: created, cancelledAt: nil) == nil)
    }
}

struct Design04NoticeTests {
    @Test func parcelNoticesByStatus() {
        #expect(BookingDetailRules.notices(BookingFixture.booking(status: "confirmed"), blocked: false).isEmpty)
        #expect(BookingDetailRules.notices(BookingFixture.booking(status: "in_transit"), blocked: false) == [.onTheWay])
        #expect(BookingDetailRules.notices(BookingFixture.booking(status: "delivered"), blocked: false) == [.delivered])
        #expect(BookingDetailRules.notices(BookingFixture.booking(status: "completed"), blocked: false).isEmpty)
    }

    @Test func cancelledSaysWhoAndBlockedComesLast() {
        let booking = BookingFixture.booking(status: "cancelled",
                                             cancelled: #"{"by_side":"client","reason_code":"plans_changed","fault_side":null,"at":"2026-09-29T13:00:00Z"}"#)
        let notices = BookingDetailRules.notices(booking, blocked: true)
        #expect(notices.count == 2)
        if case .cancelled(let info)? = notices.first { #expect(info.bySide == "client") } else { Issue.record("no cancelled notice") }
        #expect(notices.last == .blocked)
        #expect(notices.map(\.tone) == [.err, .warn])
    }

    @Test func taxiArrivedAndNoShow() {
        #expect(BookingDetailRules.notices(TaxiFixture.client(status: "arrived"), blocked: false) == [.arrived])
        #expect(BookingDetailRules.notices(TaxiFixture.client(status: "awaiting_pickup", noShow: "pending"), blocked: false) == [.noShowPending])
        // A parcel's "delivered" words never appear on a passenger booking and vice versa.
        #expect(BookingDetailRules.notices(TaxiFixture.client(status: "onboard"), blocked: false).isEmpty)
    }
}

struct Design04ShareAndPhoneTests {
    @Test func shareUntilDeliveredOrArrived() {
        for status in ["confirmed", "awaiting_pickup", "in_transit"] { #expect(BookingDetailRules.canShare(status, service: .parcel)) }
        for status in ["delivered", "completed", "cancelled", "return_required"] { #expect(!BookingDetailRules.canShare(status, service: .parcel)) }
        for status in ["confirmed", "awaiting_pickup", "onboard"] { #expect(BookingDetailRules.canShare(status, service: .passenger)) }
        for status in ["arrived", "completed", "no_show"] { #expect(!BookingDetailRules.canShare(status, service: .passenger)) }
    }

    @Test func liveDotOnlyWhileTheServiceRuns() {
        #expect(BookingDetailRules.liveDot("in_transit") && BookingDetailRules.liveDot("onboard"))
        #expect(!BookingDetailRules.liveDot("confirmed") && !BookingDetailRules.liveDot("delivered") && !BookingDetailRules.liveDot("arrived"))
    }

    @Test func phoneOpensOnlyWhenTheServerShowsIt() {
        #expect(BookingDetailRules.phone(BookingFixture.booking(status: "in_transit", phonesVisible: true, phone: "+998901112233"))
            == .visible("+998901112233"))
        #expect(BookingDetailRules.phone(BookingFixture.booking(status: "confirmed")) == .locked)
        // Q44: kept 24 h after the end while the server still shows it; then closed.
        #expect(BookingDetailRules.phone(BookingFixture.booking(status: "completed", phonesVisible: true, phone: "+998901112233"))
            == .visible("+998901112233"))
        #expect(BookingDetailRules.phone(BookingFixture.booking(status: "completed")) == .closed)
        #expect(BookingDetailRules.phone(BookingFixture.booking(status: "cancelled")) == .closed)
    }

    @Test func callRefusalSaysWhenItOpens() {
        // Q142: a parcel's phones open when the trip departs (not "posilka olib ketilganda").
        #expect(BookingDetailRules.callRefusalKey(.locked, service: .parcel) == "client.booking.callLockedParcel")
        #expect(BookingDetailRules.callRefusalKey(.locked, service: .passenger) == "client.booking.callLockedTaxi")
        #expect(BookingDetailRules.callRefusalKey(.closed, service: .parcel) == "client.booking.callClosed")
        #expect(BookingDetailRules.callRefusalKey(.visible("+998"), service: .parcel) == nil)
    }
}

struct Design04ChatAndRatingTests {
    @Test func unreadIsCountedMinusSeenNeverNegative() {
        #expect(BookingDetailRules.unread(messageCount: 5, seen: 3) == 2)
        #expect(BookingDetailRules.unread(messageCount: 2, seen: 4) == 0)
        #expect(BookingDetailRules.unread(messageCount: nil, seen: 0) == 0)
    }

    @Test func seenOnlyGrows() throws {
        let defaults = try #require(UserDefaults(suiteName: "design04.\(UUID().uuidString)"))
        ChatSeen.mark("bkg_x", count: 4, defaults: defaults)
        ChatSeen.mark("bkg_x", count: 2, defaults: defaults)
        #expect(ChatSeen.count("bkg_x", defaults: defaults) == 4)
        #expect(ChatSeen.count("bkg_y", defaults: defaults) == 0)
    }

    @Test func initialsFromTheFirstName() {
        #expect(BookingDetailRules.initials("Jasur Toshmatov") == "JT")
        #expect(BookingDetailRules.initials("demo") == "D")
        #expect(BookingDetailRules.initials("  ") == "?")
    }

    @Test func ratingCardOnlyWhenCompletedAndNotRated() {
        #expect(BookingDetailRules.showsRatingCard("completed", rated: false))
        #expect(!BookingDetailRules.showsRatingCard("completed", rated: true))
        // RULE: no rating before completed (the design shows it at delivered / arrived with the cash block).
        for status in ["delivered", "arrived", "onboard", "cancelled"] { #expect(!BookingDetailRules.showsRatingCard(status, rated: false)) }
    }

    @Test func starWordsAndText() {
        #expect(BookingDetailRules.starLabelKey(0) == "client.booking.rateTapStar")
        #expect(BookingDetailRules.starLabelKey(1) == "client.booking.rateLabel1")
        #expect(BookingDetailRules.starLabelKey(5) == "client.booking.rateLabel5")
        #expect(BookingDetailRules.starsText(4) == "★★★★ (4 / 5)")
    }

    @Test func weightInKilograms() {
        #expect(BookingDetailRules.weightText(grams: 5000) == "5")
        #expect(BookingDetailRules.weightText(grams: 2500) == "2,5")
    }
}

struct Design04AmendmentTests {
    @Test func tapToValidateSaysWhatIsMissing() {
        #expect(AmendmentForm.validate(priceMinor: 0, currentUnitMinor: 100, reason: "Yuk og'ir") == .priceMissing)
        #expect(AmendmentForm.validate(priceMinor: 100, currentUnitMinor: 100, reason: "Yuk og'ir") == .noChange)
        #expect(AmendmentForm.validate(priceMinor: 120, currentUnitMinor: 100, reason: " ab ") == .reasonShort)
        #expect(AmendmentForm.validate(priceMinor: 120, currentUnitMinor: 100, reason: "Yuk") == nil)
        #expect(AmendmentForm.Problem.noChange.key == "client.amendment.noChange")
        #expect(AmendmentForm.Problem.priceMissing.key == "listingOwner.invalid.price")
    }

    @Test func historyBadgesInThePastTense() {
        let now = ServerTime.parse("2026-09-29T11:00:00Z")!
        #expect(AmendmentActions.status(BookingFixture.amendment(status: "accepted"), bookingStatus: "confirmed", now: now).key
            == "client.booking.amendStatusAccepted")
        #expect(AmendmentActions.status(BookingFixture.amendment(status: "rejected"), bookingStatus: "confirmed", now: now).key == "amendment.rejected")
        #expect(AmendmentActions.status(BookingFixture.amendment(status: "withdrawn"), bookingStatus: "confirmed", now: now).key
            == "client.offers.closed.withdrawn")
        #expect(AmendmentActions.status(BookingFixture.amendment(), bookingStatus: "confirmed", now: now).key == "status.proposed")
    }
}

struct Design04TrackingTests {
    @Test func closedCardTitleFromTheServersReason() {
        #expect(TrackingCard.closedTitleKey(reason: "parcel_not_picked_up", bookingStatus: "awaiting_pickup") == "client.tracking.notStarted")
        #expect(TrackingCard.closedTitleKey(reason: "not_yet_open", bookingStatus: "confirmed") == "client.tracking.notStarted")
        #expect(TrackingCard.closedTitleKey(reason: "booking_finished", bookingStatus: "completed") == "client.tracking.liveClosed")
        #expect(TrackingCard.closedTitleKey(reason: "trip_finished", bookingStatus: "delivered") == "client.tracking.liveClosed")
        #expect(TrackingCard.closedTitleKey(reason: "booking_finished", bookingStatus: "cancelled") == "client.tracking.bookingCancelled")
    }

    @Test func freshnessNotesCarryTheRealAge() {
        let now = Date(timeIntervalSince1970: 10_000)
        #expect(TrackingCard.note(.fresh, capturedAt: now, now: now) == .none)
        #expect(TrackingCard.note(.delayed, capturedAt: now.addingTimeInterval(-45), now: now) == .delayed(minutes: 1))
        #expect(TrackingCard.note(.delayed, capturedAt: now.addingTimeInterval(-119), now: now) == .delayed(minutes: 1))
        #expect(TrackingCard.note(.lost, capturedAt: now.addingTimeInterval(-600), now: now) == .lost)
        #expect(TrackingCard.note(.noData, capturedAt: nil, now: now) == .noData)
    }
}

struct Design04WordingTests {
    @MainActor @Test func everyNewSentenceExistsInBothLanguages() {
        let store = LocaleStore()
        defer { store.set(.uz) }
        let keys = ["client.booking.createdAt", "client.booking.plannedArrival", "client.booking.finalPrice", "client.booking.weight",
                    "client.booking.weightUpTo", "client.booking.noticeOnTheWay", "client.booking.noticeDelivered", "client.booking.noticeArrived",
                    "client.booking.driverBlocked", "client.booking.phoneClosed", "client.booking.callLockedTaxi", "client.booking.callLockedParcel",
                    "client.booking.callClosed", "client.booking.openTracking", "client.booking.shareTracking", "client.booking.shareSheetTitle",
                    "client.booking.trackingLinkCopied", "client.booking.cancelledToast", "client.booking.refreshed", "client.booking.ratedStars",
                    "client.booking.cashConfirmTitle", "client.booking.cashConfirmed", "client.booking.cashContestSent",
                    "client.booking.amendReasonPlaceholder", "client.booking.amendReasonRequired", "client.booking.amendStatusAccepted",
                    "client.booking.amendWithdraw", "client.booking.amendAcceptedPrice", "client.booking.rateTapStar",
                    "client.booking.rateCommentOptional", "client.booking.rateCommentPlaceholder", "client.booking.ratePickStars",
                    "client.booking.rateThanks", "client.booking.reportSentShort", "client.booking.blockConfirmName",
                    "client.booking.blockKeepsBooking", "client.booking.blockedName", "client.chat.masked", "client.chat.openUntil",
                    "client.chat.closedCancelled", "client.tracking.notStarted", "client.tracking.liveClosed", "client.tracking.bookingCancelled",
                    "client.tracking.delayedNote", "client.tracking.lostNote", "publicTracking.fresh", "publicTracking.delayed",
                    "publicTracking.lost", "publicTracking.noData", "routeSummary.pricePerPerson", "client.offers.closed.withdrawn",
                    "proposal.rejected", "safety.section", "support.threadTitle", "app.progress.completed", "parcel.progress.tripPreparing"]
            + (1...5).map { "client.booking.rateLabel\($0)" }
        for locale in AppLocale.allCases {
            store.set(locale)
            for key in keys { #expect(store.tOrNil(key) != nil, "missing \(key)") }
            for step in PassengerStatus.ladder { #expect(store.tOrNil(step) != nil) }
        }
    }

    @MainActor @Test func namedSentencesFillTheName() {
        let store = LocaleStore()
        defer { store.set(.uz) }
        store.set(.uz)
        #expect(store.t("client.booking.blockConfirmName", ("name", "Jasur")) == "Jasur bloklansinmi?")
        #expect(store.t("client.booking.ratedStars", ("stars", BookingDetailRules.starsText(4))).hasPrefix("Baho berildi: ★★★★ (4 / 5)."))
    }
}
