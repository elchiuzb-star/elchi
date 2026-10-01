import Foundation
import Testing
@testable import Elchi

/// Stage 06 pure logic: what a v1 order still allows by status, when the driver's phone shows, the dispute codes,
/// the Yandex links (longitude first for a point), money from DECIMAL so'm, naive timestamps in Tashkent time, the
/// refusal sentences, v1 paging, and the banner's auto-hide policy.
struct LegacyActionsTests {
    @Test func statusToActionsMatrix() {
        // status: (bids, confirm, rate, cancel, report)
        let expected: [String: (Bool, Bool, Bool, Bool, Bool)] = [
            "draft": (false, false, false, true, false),
            "published": (true, false, false, true, false),
            "bidding": (true, false, false, true, false),
            "accepted": (false, false, false, true, true),
            "picked_up": (false, false, false, false, true),
            "in_transit": (false, false, false, false, true),
            "delivered": (false, true, false, false, true),
            "confirmed": (false, false, true, false, false),
            "cancelled": (false, false, false, false, false),
            "disputed": (false, false, false, false, false),
            "completed": (false, false, false, false, false),
        ]
        for (status, want) in expected {
            let a = LegacyActions.of(status)
            #expect((a.viewBids, a.confirm, a.rate, a.cancel, a.report) == want, "\(status)")
        }
    }

    @Test func ratedThisSessionHidesTheEntry() {
        #expect(LegacyActions.of("confirmed", rated: false).rate)
        #expect(!LegacyActions.of("confirmed", rated: true).rate)
    }

    @Test func cancelTextWarnsOnceADriverIsChosen() {
        #expect(LegacyActions.of("accepted").cancelTextKey == "confirmDialog.cancelOrder.acceptedText")
        for status in ["draft", "published", "bidding"] {
            #expect(LegacyActions.of(status).cancelTextKey == "confirmDialog.cancelOrder.text")
        }
    }

    @Test func bidsOpenOnlyWhileBidding() {
        #expect(LegacyActions.bidsOpen("published"))
        #expect(LegacyActions.bidsOpen("bidding"))
        for status in ["draft", "accepted", "in_transit", "delivered", "confirmed", "cancelled", "disputed"] {
            #expect(!LegacyActions.bidsOpen(status), "\(status)")
        }
    }

    @Test func phoneFromAcceptedOnwards() {
        for status in ["draft", "published", "bidding", "cancelled"] { #expect(!LegacyPhone.visible(status), "\(status)") }
        for status in ["accepted", "picked_up", "in_transit", "delivered", "confirmed", "disputed"] {
            #expect(LegacyPhone.visible(status), "\(status)")
        }
    }

    @Test func dialURLKeepsDigitsAndPlus() {
        #expect(LegacyPhone.dialURL("+998 90 001-10-10")?.absoluteString == "tel:+998900011010")
        #expect(LegacyPhone.dialURL("12") == nil)
    }
}

struct LegacyDisputeTests {
    @Test func reasonsAreTheServerEnumCodes() {
        #expect(LegacyDisputeReason.allCases.map(\.rawValue) == [
            "delayed", "lost", "damaged", "receiver_denied", "wrong_address", "payment_issue", "prohibited_item", "other",
        ])
        #expect(LegacyDisputeReason.default == .delayed)
        #expect(LegacyDisputeReason.receiverDenied.key == "client.legacy.dispute.reason.receiver_denied")
    }

    @Test func everyReasonHasALabel() {
        let uz = Bundle.main.path(forResource: "uz", ofType: "lproj").flatMap(Bundle.init(path:))
        for reason in LegacyDisputeReason.allCases {
            let text = uz?.localizedString(forKey: reason.key, value: "\u{0}", table: nil)
            #expect(text != nil && text != "\u{0}", "\(reason.key)")
        }
    }
}

struct YandexLinkTests {
    @Test func pointIsLongitudeFirst() {
        let url = YandexMapLinks.point(GeoPoint(lat: 41.2995, lng: 69.2401))
        #expect(url.absoluteString == "https://yandex.uz/maps/?pt=69.2401,41.2995&z=16&l=map")
    }

    @Test func routeIsLatitudeFirstFromHere() {
        let url = YandexMapLinks.route(to: GeoPoint(lat: 39.6542, lng: 66.9597))
        #expect(url.absoluteString == "https://yandex.uz/maps/?rtext=~39.6542,66.9597&rtt=auto")
    }

    @Test func coordinatesHaveNoExponentOrTrailingZeros() {
        #expect(YandexMapLinks.coordinate(41.0) == "41")
        #expect(YandexMapLinks.coordinate(0.0000123) == "0.000012")
        #expect(YandexMapLinks.coordinate(-12.5) == "-12.5")
    }

    @Test func mapPointsFromDecimalValues() {
        #expect(LegacyMapPoints.point(.number(41.2995), .string("69.2401")) == GeoPoint(lat: 41.2995, lng: 69.2401))
        #expect(LegacyMapPoints.point(.number(41.2), nil) == nil)
        #expect(LegacyMapPoints.point(.number(0), .number(0)) == nil)
        #expect(LegacyMapPoints.point(.number(141), .number(69)) == nil)
    }
}

struct LegacyMoneyTimeTests {
    @Test func priceIsFinalElseClientElseSuggested() {
        #expect(LegacyMoney.price(final: .number(68000), client: .number(63000), suggested: .number(60000)) == 6_800_000)
        #expect(LegacyMoney.price(final: nil, client: .string("63000.00"), suggested: .number(60000)) == 6_300_000)
        #expect(LegacyMoney.price(final: .null, client: .null, suggested: .number(60000.0)) == 6_000_000)
        #expect(LegacyMoney.price(final: nil, client: nil, suggested: nil) == nil)
    }

    @Test func decimalSoumFormatsAsWholeSoum() {
        let minor = LegacyMoney.minor(.string("70000.00"))!
        #expect(Money.format(minor: minor, currencyWord: "so'm") == "70\u{202F}000\u{00A0}so'm")
        #expect(Money.format(minor: LegacyMoney.minor(.number(1_250_000))!, currencyWord: "сум") == "1\u{202F}250\u{202F}000\u{00A0}сум")
    }

    @Test func naiveTimestampIsUTCShownInTashkent() {
        // v1 `published_at` is naive UTC; Tashkent is UTC+5 all year.
        #expect(LegacyTime.display("2026-09-30T10:32:54.030541") == "30.09.2026, 15:32")
        #expect(LegacyTime.display("2026-09-30T19:05:00") == "01.10.2026, 00:05")
        // An aware one keeps its own offset.
        #expect(LegacyTime.display("2026-09-30T15:32:53.989260+05:00") == "30.09.2026, 15:32")
        #expect(LegacyTime.display(nil) == nil)
    }

    @Test func ratingOneDecimalCommaAndNoneForUnrated() {
        #expect(LegacyRating.text(.number(4.6)) == "4,6")
        #expect(LegacyRating.text(.string("4.95")) == "5,0")
        #expect(LegacyRating.text(.number(0)) == nil)
        #expect(LegacyRating.text(nil) == nil)
    }
}

struct LegacyErrorTests {
    func error(_ code: String, _ status: Int = 400) -> APIError { APIError(status: status, code: code, message: "raw", details: nil) }

    @Test func selectRefusalsAreSaidForTheClient() {
        #expect(LegacyErrors.key(error("ORDER_INVALID_STATUS"), for: .select) == "client.legacy.error.orderChanged")
        #expect(LegacyErrors.key(error("BID_NOT_ACTIVE", 409), for: .select) == "client.legacy.error.bidGone")
        for code in ["DRIVER_NOT_APPROVED", "DRIVER_BLOCKED", "DRIVER_NOT_AVAILABLE"] {
            #expect(LegacyErrors.key(error(code), for: .select) == "client.legacy.error.driverUnavailable", "\(code)")
        }
    }

    @Test func disputeExistsAndStatusRefusals() {
        #expect(LegacyErrors.key(error("ALREADY_EXISTS", 409), for: .dispute) == "client.legacy.dispute.exists")
        #expect(LegacyErrors.key(error("ORDER_INVALID_STATUS"), for: .cancel) == "client.legacy.error.orderChanged")
        #expect(LegacyErrors.key(error("VALIDATION_ERROR"), for: .rate) == nil)
        #expect(LegacyErrors.key(error("ANY", 429), for: .confirm) == "error.RATE_LIMITED")
        #expect(LegacyErrors.key(error(APIError.network, 0), for: .confirm) == nil) // the generic offline sentence
    }

    @Test func repeatedRatingCountsAsDone() {
        #expect(LegacyErrors.alreadyRated(error("ALREADY_EXISTS", 409)))
        #expect(!LegacyErrors.alreadyRated(error("ORDER_INVALID_STATUS")))
    }

    @Test func notFoundIs404Or403() {
        #expect(LegacyErrors.notFound(error("NOT_FOUND", 404)))
        #expect(LegacyErrors.notFound(error("FORBIDDEN", 403)))
        #expect(!LegacyErrors.notFound(error(APIError.network, 0)))
        #expect(!LegacyErrors.notFound(error("SERVER_ERROR", 500)))
    }
}

struct LegacyPagingTests {
    @Test func moreWhileShortOfTotalPages() {
        let first = Fixture.decode(LegacyOrderPage.self, #"{"items":[],"pagination":{"page":1,"limit":20,"total":41,"total_pages":3}}"#)
        #expect(first.hasMore)
        let last = Fixture.decode(LegacyOrderPage.self, #"{"items":[],"pagination":{"page":3,"limit":20,"total":41,"total_pages":3}}"#)
        #expect(!last.hasMore)
        let none = Fixture.decode(LegacyOrderPage.self, #"{"items":[]}"#)
        #expect(!none.hasMore)
    }

    @MainActor @Test func nextPageSkipsRowsAlreadyShown() {
        let a = Fixture.decode(LegacyOrder.self, #"{"id":1,"status":"bidding"}"#)
        let b = Fixture.decode(LegacyOrder.self, #"{"id":2,"status":"published"}"#)
        let c = Fixture.decode(LegacyOrder.self, #"{"id":3,"status":"confirmed"}"#)
        #expect(ClientOrdersModel.appending([b, c], to: [a, b]).map(\.id) == [1, 2, 3])
    }

    @Test func detailDecodesTheServersShape() {
        let detail = Fixture.decode(LegacyOrderDetail.self, """
            {"id":7,"order_number":"ORD-1","status":"accepted","from_city":{"id":1,"name_uz":"Toshkent shahri"},
             "to_city":{"id":3,"name_uz":"Samarqand viloyati"},"from_district":{"id":4,"name_uz":"Mirobod","name_ru":"Мирабад"},
             "pickup_address":"Amir Temur 1","dropoff_address":null,"pickup_lat":41.2995,"pickup_lng":"69.2401","dropoff_lat":null,
             "dropoff_lng":null,"sender_phone":"+998930746792","receiver_phone":"+998901112233","cargo_photo_url":null,"comment":"x",
             "suggested_price":60000.0,"client_price":62000.0,"final_price":"62000.00",
             "assigned_driver":{"id":2,"full_name":"Demo Haydovchi","phone":"+998900001010","car_model":"Nexia 3","plate_number":"10 C 207 TA",
                                "rating":"4.60","completed_orders":3},
             "accepted_bid_id":11,"bids_count":1,"created_at":"2026-09-30T15:32:53.989260+05:00"}
            """)
        #expect(detail.priceMinor == 6_200_000)
        #expect(detail.pickup == GeoPoint(lat: 41.2995, lng: 69.2401))
        #expect(detail.dropoff == nil)
        #expect(LegacyRating.text(detail.assignedDriver?.rating) == "4,6")
        #expect(detail.fromCity?.nameUz == "Toshkent shahri")
    }
}

struct BannerPolicyTests {
    @Test func successInfoWarnHideAfterFourSecondsErrorsStay() {
        #expect(BannerPolicy.autoHide(.ok) == .seconds(4))
        #expect(BannerPolicy.autoHide(.info) == .seconds(4))
        #expect(BannerPolicy.autoHide(.warn) == .seconds(4))
        #expect(BannerPolicy.autoHide(.err) == nil)
    }

    @MainActor @Test func nextActionClearsAStandingErrorButNotSuccess() {
        let center = BannerCenter()
        center.show(.key("error.offline"), tone: .err)
        center.clearError()
        #expect(center.current == nil)
        center.ok("legacyOrder.confirmed")
        center.clearError()
        #expect(center.current?.tone == .ok)
    }

    @MainActor @Test func mappedSentences() {
        let strings = LocaleStore()
        strings.set(.uz)
        #expect(strings.bannerErrorText(APIError(status: 0, code: APIError.network, message: "", details: nil)) == "Internet aloqasi yo'q")
        #expect(strings.bannerErrorText(APIError(status: 429, code: "TOO_MANY_REQUESTS", message: "", details: nil))
                == "Juda tez-tez urinyapsiz, biroz kuting")
        let masked = Fixture.decode(ApiWarning.self, #"{"code":"CONTACT_INFO_MASKED","message":"masked"}"#)
        #expect(strings.bannerText(.warning(masked)) == "Aloqa ma'lumotlari yashirildi — kelishuv ilova ichida bo'ladi")
    }

    @MainActor @Test func loadingLineCountsWork() async {
        let center = BannerCenter()
        #expect(!center.loading)
        let seen = await center.whileLoading { center.loading }
        #expect(seen)
        #expect(!center.loading)
    }
}
