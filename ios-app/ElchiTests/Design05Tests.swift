import Foundation
import Testing
@testable import Elchi

/// BOSQICH 05 ("Elchi Profil") rules: the name's two letters, the bonus screen's programme-off state, copy vs share,
/// the own-code check, campaign badge tones, the help screen's hint / cap / corrected FAQ answer, the account-deletion
/// link into the orders and the latest order's tint.
struct Design05Tests {
    // MARK: Profile

    @Test func nameNeedsTwoLetters() {
        #expect(!NameRule.isValid(""))
        #expect(!NameRule.isValid("  A  "))
        #expect(!NameRule.isValid("1 2 3"))
        #expect(!NameRule.isValid("A1"))
        #expect(NameRule.isValid("Al"))
        #expect(NameRule.isValid(" Aziza Karimova "))
        #expect(NameRule.isValid("Ли"))
    }

    @Test func nameIsCutAt120() {
        #expect(NameRule.typed(String(repeating: "a", count: 130)).count == 120)
        #expect(NameRule.typed("Aziza") == "Aziza")
    }

    @Test func latestOrderTint() {
        #expect(ProfileStats.latestTone(StatusLabel.booking(.parcel, "in_transit")) == .blue)
        #expect(ProfileStats.latestTone(StatusLabel.booking(.parcel, "completed")) == .ok)
        #expect(ProfileStats.latestTone(StatusLabel.booking(.parcel, "cancelled")) == nil)
        #expect(ProfileStats.latestTone(StatusLabel.booking(.parcel, "awaiting_pickup")) == nil)
    }

    // MARK: Bonus

    @Test func programOffWithoutBalanceShowsOnlyTheEmptyState() {
        #expect(PromoLogic.screenState(programOff: true, balanceLoaded: true, hasBuckets: false) == .offOnly)
        #expect(PromoLogic.screenState(programOff: true, balanceLoaded: false, hasBuckets: false) == .loading)
        #expect(PromoLogic.screenState(programOff: true, balanceLoaded: true, hasBuckets: true) == .offWithBalance)
        #expect(PromoLogic.screenState(programOff: false, balanceLoaded: true, hasBuckets: false) == .on)
        #expect(PromoLogic.screenState(programOff: false, balanceLoaded: false, hasBuckets: false) == .on)
    }

    @Test func copyIsTheCodeShareIsTheLinkWhenConfigured() {
        let linked = ReferralCodeDTO(code: "AB2CD3EF", linkStatus: "configured_unverified", shareUrl: "https://elchigo.uz/r/AB2CD3EF")
        #expect(PromoLogic.copyText(linked) == "AB2CD3EF")
        #expect(PromoLogic.shareText(linked) == "https://elchigo.uz/r/AB2CD3EF")
        let unlinked = ReferralCodeDTO(code: "AB2CD3EF", linkStatus: "not_configured", shareUrl: nil)
        #expect(PromoLogic.copyText(unlinked) == "AB2CD3EF")
        #expect(PromoLogic.shareText(unlinked) == "AB2CD3EF")
        // A URL the server has not configured yet is not shared.
        let pending = ReferralCodeDTO(code: "AB2CD3EF", linkStatus: "not_configured", shareUrl: "https://elchigo.uz/r/AB2CD3EF")
        #expect(PromoLogic.shareText(pending) == "AB2CD3EF")
    }

    @Test func entryErrorFormatAndOwnCode() {
        #expect(ReferralCode.entryErrorKey("", own: "AB2CD3EF") == nil)
        #expect(ReferralCode.entryErrorKey("AB2C", own: "AB2CD3EF") == nil)
        #expect(ReferralCode.entryErrorKey("AB0CD1EF", own: "AB2CD3EF") == "promoScreen.codeFormat")
        #expect(ReferralCode.entryErrorKey("AB2CD3EF", own: "AB2CD3EF") == "client.bonus.ownCode")
        #expect(ReferralCode.entryErrorKey("AB2CD3EF", own: "ab2cd3ef") == "client.bonus.ownCode")
        #expect(ReferralCode.entryErrorKey("ZZ2CD3EF", own: "AB2CD3EF") == nil)
        #expect(ReferralCode.entryErrorKey("ZZ2CD3EF", own: nil) == nil)
    }

    private func enrollment(status: String, qualification: String? = nil) -> EnrollmentDTO {
        EnrollmentDTO(campaignId: "cmp_1", campaignName: "Do'stingizni taklif qiling", enrolledAt: "2026-09-01T00:00:00Z", id: "enr_1",
                      qualificationDeadline: "2026-10-31T00:00:00Z", qualificationStatus: qualification, serviceType: .parcel,
                      side: "referrer", status: status)
    }

    @Test func campaignBadgeTones() {
        #expect(PromoLogic.enrollmentTone(enrollment(status: "promised")) == .blue)
        #expect(PromoLogic.enrollmentTone(enrollment(status: "promised", qualification: "waiting")) == .warn)
        #expect(PromoLogic.enrollmentTone(enrollment(status: "promised", qualification: "review")) == .warn)
        #expect(PromoLogic.enrollmentTone(enrollment(status: "promised", qualification: "qualified")) == .ok)
        #expect(PromoLogic.enrollmentTone(enrollment(status: "granted")) == .ok)
        #expect(PromoLogic.enrollmentTone(enrollment(status: "released")) == .gray)
        #expect(PromoLogic.enrollmentTone(enrollment(status: "promised", qualification: "rejected")) == .gray)
    }

    // MARK: Help

    @Test func ticketHintCapAndFaq() {
        #expect(!SupportText.showsMinHint(""))
        #expect(!SupportText.showsMinHint("   "))
        #expect(SupportText.showsMinHint("abcd"))
        #expect(!SupportText.showsMinHint("abcde"))
        #expect(SupportText.typed(String(repeating: "x", count: 1200)).count == 1000)
        // Profil v3 6.2 / 6.4: the client's FAQ1 (Q138: no bidding on drivers' listings) and FAQ4 (Q142).
        #expect(SupportText.faqAnswerKey(prefix: "support.faq", index: 4) == "client.v3.faq4Answer")
        #expect(SupportText.faqAnswerKey(prefix: "support.faq", index: 1) == "client.v3.faq1Answer")
        #expect(SupportText.faqAnswerKey(prefix: "support.faq", index: 2) == "support.faq2Answer")
        #expect(SupportText.faqAnswerKey(prefix: "driver.faq", index: 1) == "driver.faq1Answer")
        #expect(SupportText.faqAnswerKey(prefix: "driver.faq", index: 4) == "driver.faq4Answer")
    }

    // MARK: Account deletion

    @Test func ordersLinkOnlyForBookingsOrOrders() {
        let bookings = DeletionBlocker.lines(.object(["active_bookings": .number(1), "wallet_balance": .number(5)]))
        #expect(DeletionBlocker.leadsToOrders(bookings))
        #expect(DeletionBlocker.leadsToOrders(DeletionBlocker.lines(.object(["active_orders": .number(2)]))))
        #expect(!DeletionBlocker.leadsToOrders(DeletionBlocker.lines(.object(["open_disputes": .number(1)]))))
        #expect(!DeletionBlocker.leadsToOrders(DeletionBlocker.lines(nil)))
    }

    // MARK: Dictionary

    @MainActor @Test func design05KeysResolveInBothLanguages() {
        let store = LocaleStore()
        let keys = ["client.bonus.programOffHint", "client.bonus.codeLabel", "client.bonus.copyCode", "client.bonus.shareLink",
                    "client.bonus.codeCopied", "client.bonus.ownCode", "client.bonus.codeAcceptedValue", "client.profile.unblockTitle",
                    "client.profile.unblockText", "client.profile.unblocked", "client.help.minChars", "client.help.allThreads",
                    "client.help.ticketsTitle", "client.help.faq4Answer", "client.settings.themeChanged",
                    "client.settings.languageChanged", "client.settings.deleteConfirmTitle", "client.settings.deleteConfirmYes",
                    "client.settings.goToOrders", "client.settings.loggedOutTitle", "client.settings.loggedOutText"]
        for locale in [AppLocale.uz, .ru] {
            store.set(locale)
            for key in keys { #expect(store.tOrNil(key) != nil, "\(key) missing in \(locale)") }
        }
        store.set(.uz)
        #expect(store.t("client.bonus.codeCopied", ("code", "AB2CD3EF")) == "Kod nusxalandi: AB2CD3EF")
        #expect(store.t("client.help.allThreads", ("count", 3)) == "Hammasi (3)")
        // Q142: the corrected answer says parcel phones open at departure, not at pick-up.
        #expect(store.t("client.help.faq4Answer").contains("safar jo'naganda"))
    }
}
