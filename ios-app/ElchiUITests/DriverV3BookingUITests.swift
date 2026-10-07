import XCTest

/// Design v3 screenshots (BOSQICH 08 "Haydovchi Bron" + 09 "Haydovchi Hamyon") against the running development backend.
/// From the shell (`TEST_RUNNER_*`): `DRIVER` (9 digits), `PAX` (a passenger booking), `PARCEL` (a parcel booking),
/// `DONE` (a completed booking), `SHOTS` (folder for the PNGs). Phases: 1 signs in (uz, light), the rest reuse the session.
final class DriverV3BookingUITests: ClientUITestCase {
    private func env(_ name: String) -> String {
        let value = ProcessInfo.processInfo.environment[name] ?? ""
        XCTAssertFalse(value.isEmpty, "\(name) not passed (TEST_RUNNER_\(name))")
        return value
    }

    private func byId(_ id: String, timeout: TimeInterval = 15) -> XCUIElement {
        let element = app.descendants(matching: .any)[id].firstMatch
        XCTAssertTrue(element.waitForExistence(timeout: timeout), "no element '\(id)'")
        return element
    }

    private func scrollTo(_ element: XCUIElement, maxSwipes: Int = 10) {
        var swipes = 0
        while !(element.exists && element.isHittable) && swipes < maxSwipes {
            app.swipeUp()
            swipes += 1
        }
        if swipes > 0 { Thread.sleep(forTimeInterval: 1.0) }
    }

    private func tapId(_ id: String, timeout: TimeInterval = 15) {
        let element = byId(id, timeout: timeout)
        scrollTo(element)
        element.tap()
    }

    private func signInAsDriver(_ phone: String) {
        tap("Boshlash")
        tap("Keyingisi")
        tap("Keyingisi")
        tap("Boshlash")
        app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "Men haydovchiman")).firstMatch.tap()
        let phoneField = app.textFields.firstMatch
        XCTAssertTrue(phoneField.waitForExistence(timeout: 10))
        phoneField.tap()
        for digit in phone { phoneField.typeText(String(digit)) }
        tap("Kod olish")
        XCTAssertTrue(app.textFields.firstMatch.waitForExistence(timeout: 10))
        app.textFields.firstMatch.typeText("1234")
        XCTAssertTrue(app.buttons["elchi.tab.home"].waitForExistence(timeout: 25), "no driver tabs")
    }

    private func openBooking(_ id: String, locale: String = "uz", theme: String = "light", screen: String? = nil) {
        launch(locale: locale, theme: theme, reset: false,
               extra: ["-uiTestDriverBooking", id] + (screen.map { ["-uiTestDriverBookingScreen", $0] } ?? []))
        byId("elchi.driver.booking.card", timeout: 25)
        Thread.sleep(forTimeInterval: 2.5)
    }

    /// uz light: the list, the passenger detail (top, notes, bottom), the cancel chips, tracking, the parcel detail.
    func test01_Bookings() {
        launch(theme: "light")
        signInAsDriver(env("DRIVER"))
        app.buttons["elchi.tab.orders"].tap()
        byId("elchi.driver.booking.\(env("PAX"))", timeout: 25)
        Thread.sleep(forTimeInterval: 1.5)
        snap("01-orders-list")
        openBooking(env("PAX"))
        snap("02-pax-detail-top")
        app.swipeUp()
        Thread.sleep(forTimeInterval: 1)
        snap("03-pax-detail-mid")
        app.swipeUp()
        app.swipeUp()
        Thread.sleep(forTimeInterval: 1)
        snap("04-pax-detail-bottom")
        if app.descendants(matching: .any)["elchi.driver.booking.cancel"].exists {
            tapId("elchi.driver.booking.cancel")
            byId("elchi.driver.cancel.reason.trip_changed", timeout: 10)
            Thread.sleep(forTimeInterval: 1)
            snap("05-cancel-chips")
        }
        openBooking(env("PAX"))
        tapId("elchi.driver.booking.hero")
        Thread.sleep(forTimeInterval: 3)
        snap("06-tracking")
        openBooking(env("PARCEL"))
        snap("07-parcel-detail")
        app.swipeUp()
        Thread.sleep(forTimeInterval: 1)
        snap("08-parcel-detail-bottom")
        openBooking(env("DONE"))
        app.swipeUp()
        Thread.sleep(forTimeInterval: 1)
        snap("09-completed-bottom")
    }

    /// uz light: wallet (period toggle, presets, large amount, confirm dialog), profile rows, logout dialog.
    func test02_WalletProfile() {
        launch(theme: "light", reset: false, extra: ["-uiTestDriverScreen", "wallet"])
        byId("elchi.wallet.chart", timeout: 25)
        Thread.sleep(forTimeInterval: 2)
        snap("10-wallet-top")
        app.buttons["6 oy"].firstMatch.tap()
        Thread.sleep(forTimeInterval: 1)
        snap("11-wallet-6oy")
        let amount = byId("elchi.wallet.amount")
        scrollTo(amount)
        app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "500")).firstMatch.tap()
        Thread.sleep(forTimeInterval: 0.5)
        snap("12-wallet-preset")
        let field = app.textFields.firstMatch
        field.tap()
        for _ in 0..<8 { field.typeText(XCUIKeyboardKey.delete.rawValue) }
        for digit in "1500000" { field.typeText(String(digit)) }
        Thread.sleep(forTimeInterval: 0.5)
        snap("13-wallet-large")
        app.swipeUp()
        tapId("elchi.wallet.submit")
        byId("elchi.wallet.confirm", timeout: 10)
        snap("14-wallet-confirm")
        app.buttons["Ortga"].firstMatch.tap()

        launch(theme: "light", reset: false, extra: ["-uiTestDriverTab", "profile"])
        byId("elchi.driver.profile.header", timeout: 25)
        app.swipeUp()
        Thread.sleep(forTimeInterval: 1)
        snap("15-profile-rows")
        app.swipeUp()
        Thread.sleep(forTimeInterval: 1)
        snap("16-profile-rows-end")
        tapId("elchi.driver.menu.logout")
        byId("elchi.logout.confirm", timeout: 10)
        snap("17-logout-dialog")
        app.buttons["Qolish"].firstMatch.tap()
    }

    /// One dark and one Russian pass of the passenger detail and the wallet.
    func test03_DarkAndRu() {
        openBooking(env("PAX"), theme: "dark")
        snap("20-dark-pax-detail")
        app.swipeUp()
        Thread.sleep(forTimeInterval: 1)
        snap("21-dark-pax-detail-mid")
        launch(theme: "dark", reset: false, extra: ["-uiTestDriverScreen", "wallet"])
        byId("elchi.wallet.chart", timeout: 25)
        Thread.sleep(forTimeInterval: 2)
        snap("22-dark-wallet")
        openBooking(env("PAX"), locale: "ru")
        snap("30-ru-pax-detail")
        app.swipeUp()
        Thread.sleep(forTimeInterval: 1)
        snap("31-ru-pax-detail-mid")
        openBooking(env("PARCEL"), locale: "ru")
        snap("32-ru-parcel-detail")
        launch(locale: "ru", theme: "light", reset: false, extra: ["-uiTestDriverScreen", "wallet"])
        byId("elchi.wallet.chart", timeout: 25)
        Thread.sleep(forTimeInterval: 2)
        snap("33-ru-wallet")
        launch(locale: "ru", theme: "light", reset: false, extra: ["-uiTestDriverTab", "profile"])
        byId("elchi.driver.profile.header", timeout: 25)
        app.swipeUp()
        Thread.sleep(forTimeInterval: 1)
        snap("34-ru-profile-rows")
    }

    /// The passenger booking in a later state (`TAG` names the shots): top and the notes under the sheet.
    func test04_State() {
        let tag = env("TAG")
        openBooking(env("PAX"))
        snap("\(tag)-top")
        app.swipeUp()
        Thread.sleep(forTimeInterval: 1)
        snap("\(tag)-mid")
        app.swipeUp()
        Thread.sleep(forTimeInterval: 1)
        snap("\(tag)-bottom")
    }
}
