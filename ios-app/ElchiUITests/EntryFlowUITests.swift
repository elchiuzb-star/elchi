import XCTest

/// Stage 01 end to end against a running development backend (dev OTP, `ELCHI_SMS_ENABLED=false`).
/// Each step attaches a screenshot to the test result for design review.
@MainActor
final class EntryFlowUITests: XCTestCase {
    private lazy var app = XCUIApplication()

    private func launch() {
        continueAfterFailure = false
        app.launchArguments = ["-uiTestReset", "-elchi.locale", "uz"]
        app.launch()
    }

    private func snap(_ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func tap(_ label: String, timeout: TimeInterval = 10) {
        let button = app.buttons[label].firstMatch
        XCTAssertTrue(button.waitForExistence(timeout: timeout), "no button '\(label)'")
        button.tap()
    }

    private func waitFor(_ text: String, timeout: TimeInterval = 10) {
        XCTAssertTrue(app.staticTexts[text].firstMatch.waitForExistence(timeout: timeout), "no text '\(text)'")
    }

    func testSignInAsDriverThenRoleIsPermanent() {
        // A phone number unique to this run, so the account is always new.
        launch()
        let phone = "93" + String(format: "%07d", Int(Date().timeIntervalSince1970) % 10_000_000)

        waitFor("Shaharlararo posilka xizmati")
        snap("01-splash")
        tap("Boshlash")

        waitFor("Posilkangizni shahardan shaharga yuboring")
        snap("02-onboarding-1")
        tap("Keyingisi")
        tap("Keyingisi")
        waitFor("Yetkazilganini operator qayd etadi")
        snap("02-onboarding-3")
        tap("Boshlash")

        waitFor("Qanday davom etamiz?")
        waitFor("Rol telefon raqamingizga bog'lanadi. Boshqa rol uchun chiqib, qayta kirasiz.")
        snap("03-role")
        app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "Men haydovchiman")).firstMatch.tap()

        waitFor("Telefon raqamingiz")
        for digit in phone { app.textFields.firstMatch.typeText(String(digit)) } // the field reformats as it goes
        snap("04-phone")
        tap("Kod olish")

        waitFor("Kodni kiriting")
        waitFor("Kod yuborildi")
        snap("05-otp")
        app.textFields.firstMatch.typeText("1111")
        waitFor("Kod noto'g'ri")
        snap("05-otp-error")
        app.textFields.firstMatch.typeText("1234")

        // Stage 07: a new driver lands on the driver home ("Profilni to'ldiring" until approved).
        waitFor("Profilni to'ldiring", timeout: 15)
        snap("06-home")

        // Role is permanent: the same phone as a client is refused with a sentence, not a code.
        let profileTab = app.buttons["elchi.tab.profile"]
        XCTAssertTrue(profileTab.waitForExistence(timeout: 10))
        profileTab.tap()
        let logout = app.buttons["elchi.driver.menu.logout"]
        XCTAssertTrue(logout.waitForExistence(timeout: 10))
        for _ in 0..<6 where !logout.isHittable { app.swipeUp() }
        logout.tap()
        tap("elchi.logout.confirm")
        waitFor("Qanday davom etamiz?")
        app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "Men mijozman")).firstMatch.tap()
        waitFor("Telefon raqamingiz")
        for digit in phone { app.textFields.firstMatch.typeText(String(digit)) } // the field reformats as it goes
        tap("Kod olish")
        waitFor("Bu telefon raqam boshqa rolda ro'yxatdan o'tgan")
        snap("07-role-mismatch")
    }
}
