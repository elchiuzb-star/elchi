import XCTest

/// The contract follow-up (generated `bookingAction`, accept at the thread's `listing_terms_version`) against the
/// running development backend. From the shell (`TEST_RUNNER_*`): `DRIVER` (9 digits), `BOOKING` (confirmed),
/// `THREAD` (open, the client's counter on top).
final class DriverFollowUpUITests: ClientUITestCase {
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

    private func tapId(_ id: String, timeout: TimeInterval = 15) {
        let element = byId(id, timeout: timeout)
        waitEnabled(element, id)
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

    /// Sign in, the confirmed booking, "Keldim" -> sent.
    func test1_Arrive() {
        launch(theme: "light")
        signInAsDriver(env("DRIVER"))
        app.buttons["elchi.tab.orders"].tap()
        tapId("elchi.driver.booking.\(env("BOOKING"))", timeout: 20)
        byId("elchi.driver.booking.card", timeout: 20)
        tapId("elchi.driver.booking.arrive")
        waitFor("Keldim — mijozga xabar yuborildi", timeout: 20)
        snap("f1-keldim-sent")
    }

    /// The client's counter accepted on the first confirm: booked, no "terms changed, confirm again".
    func test2_Accept() {
        launch(theme: "light", reset: false, extra: ["-uiTestDriverScreen", "proposals"])
        tapId("elchi.proposal.\(env("THREAD"))", timeout: 20)
        waitFor("Mijoz qarshi taklif yubordi", timeout: 20)
        tapId("elchi.thread.accept")
        tapId("elchi.thread.acceptConfirm")
        byId("elchi.thread.booked", timeout: 30)
        XCTAssertFalse(app.descendants(matching: .any)["elchi.thread.error"].exists, "accept refused first")
        snap("f2-booked")
    }
}
