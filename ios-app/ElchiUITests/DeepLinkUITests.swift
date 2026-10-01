import XCTest

/// Deep links against the running development backend. The links are opened the way the system opens them
/// (`XCUIDevice.system.open` + the simulator's "Open in "Elchi"?" prompt, the same path as `xcrun simctl openurl`); the shell (scratchpad
/// `ios-links/run.sh`) covers the plain `simctl openurl` cold / warm checks between these phases.
///
/// - `test1_SignedOutThenClient`: signed out, a support-thread link waits; after the client signs in it opens.
/// - `test2_ClientReferral`: a referral link -> "Taklif kodi saqlandi", the bonus screen (programme off in dev: the
///   code is kept).
/// - `test3_SignedOutReferralThenClient`: the code kept on the sign-in screens, the bonus screen after sign-in.
/// - `test4_Driver`: the driver's pending-referral row -> tap -> programme off (kept); a booking link is unsupported;
///   a support-thread link opens the operator chat; garbage is unsupported.
final class DeepLinkUITests: ClientUITestCase {
    private var thread: String { ProcessInfo.processInfo.environment["ELCHI_THREAD"] ?? "sth_missing" }
    private var driverPhone: String { ProcessInfo.processInfo.environment["ELCHI_DRIVER_PHONE"] ?? "900001011" }

    private let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")

    /// Opens the link through the system; the simulator may ask "Open in "Elchi"?" first.
    private func open(_ link: String) {
        // Through the system (as `simctl openurl` / another app would): `XCUIApplication.open` relaunches the app with
        // this test's launch arguments (`-uiTestReset` signs it out), which is not what a link does.
        XCUIDevice.shared.system.open(URL(string: link)!)
        let confirm = springboard.buttons["Open"]
        if confirm.waitForExistence(timeout: 3) { confirm.tap() }
    }

    /// Opens the link and checks the short-lived banner (4 s): polled without waits, confirming the prompt if the
    /// simulator shows one (it does not always when the app is in front).
    private func open(_ link: String, banner: String) {
        XCUIDevice.shared.system.open(URL(string: link)!)
        let confirm = springboard.buttons["Open"]
        let text = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", banner)).firstMatch
        let deadline = Date().addingTimeInterval(10)
        var seen = false
        while Date() < deadline {
            if text.exists { seen = true; break }
            if confirm.exists { confirm.tap() }
            Thread.sleep(forTimeInterval: 0.2)
        }
        XCTAssertTrue(seen, "no banner '\(banner)' after \(link)")
    }

    /// Splash -> onboarding -> role -> phone -> dev OTP, without waiting for home (a link may open another screen).
    private func signIn(_ phone: String, role: String) {
        tap("Boshlash")
        tap("Keyingisi")
        tap("Keyingisi")
        tap("Boshlash")
        app.buttons.containing(NSPredicate(format: "label CONTAINS %@", role)).firstMatch.tap()
        let phoneField = app.textFields.firstMatch
        XCTAssertTrue(phoneField.waitForExistence(timeout: 10))
        phoneField.tap()
        for digit in phone { phoneField.typeText(String(digit)) }
        tap("Kod olish")
        XCTAssertTrue(app.textFields.firstMatch.waitForExistence(timeout: 10))
        app.textFields.firstMatch.typeText("1234")
    }

    func test1_SignedOutThenClient() {
        launch()
        _ = button("Boshlash")
        open("elchi://support-threads/\(thread)")
        snap("10-signed-out-link-held")
        signIn(ClientUITestCase.runPhone, role: "Men mijozman")
        waitFor("Operator bilan yozishma", timeout: 25)
        sleep(2)
        snap("11-after-sign-in-support-thread")
        tap("Orqaga")
        XCTAssertTrue(app.buttons["Yo'nalishni ko'rish"].firstMatch.waitForExistence(timeout: 15))
    }

    func test2_ClientReferral() {
        launch(reset: false)
        XCTAssertTrue(app.buttons["Yo'nalishni ko'rish"].firstMatch.waitForExistence(timeout: 25))
        open("elchi://r/ab2cd3ef", banner: "Taklif kodi saqlandi: AB2CD3EF")
        waitFor("Bonuslar va taklif kodi")
        snap("20-client-referral-saved-bonus")
        waitFor("Taklif dasturi hozircha ishlamayapti", timeout: 20)
        sleep(1)
        snap("21-client-bonus-program-off")
        // First code wins: a second link does not replace the kept one.
        open("elchi://r/ZZ2CD3EF", banner: "Taklif kodi saqlandi: AB2CD3EF")
        snap("22-client-second-code-first-wins")
        open("elchi://nonsense/42", banner: "Bu havolani ilovada ochib bo'lmaydi")
        snap("23-client-garbage-link")
    }

    func test3_SignedOutReferralThenClient() {
        launch()
        _ = button("Boshlash")
        open("elchi://r/AB2CD3EF", banner: "Taklif kodi saqlandi: AB2CD3EF")
        snap("30-signed-out-referral-saved")
        // A throwaway client (`ELCHI_NEW_PHONE`), so the Stage 05 client's OTP budget is not spent twice.
        signIn(ProcessInfo.processInfo.environment["ELCHI_NEW_PHONE"] ?? ClientUITestCase.runPhone, role: "Men mijozman")
        waitFor("Bonuslar va taklif kodi", timeout: 25)
        waitFor("Taklif dasturi hozircha ishlamayapti", timeout: 20)
        sleep(1)
        snap("31-after-sign-in-bonus")
        // Signed in now: the kept code stays first, and garbage says so.
        open("elchi://r/ZZ2CD3EF", banner: "Taklif kodi saqlandi: AB2CD3EF")
        snap("32-client-second-code-first-wins")
        open("elchi://nonsense/42", banner: "Bu havolani ilovada ochib bo'lmaydi")
        snap("33-client-garbage-link")
    }

    /// Runs beside the shell's `xcrun simctl openurl` checks: it only confirms the simulator's "Open in "Elchi"?"
    /// prompt (nothing else is touched) until the shell creates `<ELCHI_CMD_DIR>/stop`.
    func test5_ConfirmSystemPrompts() {
        let dir = ProcessInfo.processInfo.environment["ELCHI_CMD_DIR"] ?? "/tmp"
        let deadline = Date().addingTimeInterval(900)
        while Date() < deadline && !FileManager.default.fileExists(atPath: dir + "/stop") {
            let confirm = springboard.buttons["Open"]
            if confirm.exists { confirm.tap() }
            Thread.sleep(forTimeInterval: 0.4)
        }
    }

    /// Stage 10 (`elchi://listings/{id}`): signs in as `ELCHI_LINK_PHONE` (`ELCHI_LINK_ROLE` = driver | client), then
    /// only confirms the system's "Open in "Elchi"?" prompt while the shell runs `xcrun simctl openurl` and takes
    /// screenshots, until it creates `<ELCHI_CMD_DIR>/stop`.
    func test6_SignInThenHoldForLinks() {
        let env = ProcessInfo.processInfo.environment
        let driver = env["ELCHI_LINK_ROLE"] == "driver"
        launch()
        _ = button("Boshlash")
        signIn(env["ELCHI_LINK_PHONE"] ?? driverPhone, role: driver ? "Men haydovchiman" : "Men mijozman")
        if driver {
            XCTAssertTrue(app.buttons["elchi.tab.home"].waitForExistence(timeout: 25), "no driver tabs")
        } else {
            XCTAssertTrue(app.buttons["Yo'nalishni ko'rish"].firstMatch.waitForExistence(timeout: 25), "no client home")
        }
        let dir = env["ELCHI_CMD_DIR"] ?? "/tmp"
        FileManager.default.createFile(atPath: dir + "/ready", contents: Data())
        test5_ConfirmSystemPrompts()
    }

    func test4_Driver() {
        launch()
        _ = button("Boshlash")
        signIn(driverPhone, role: "Men haydovchiman")
        XCTAssertTrue(app.buttons["elchi.tab.home"].waitForExistence(timeout: 25), "no driver tabs")
        open("elchi://r/AB2CD3EF")
        let row = app.descendants(matching: .any)["elchi.driver.pendingReferral"].firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 15), "no pending-referral row")
        waitFor("Taklif kodi saqlandi: AB2CD3EF — tasdiqlash uchun bosing")
        sleep(4) // the "saqlandi" banner goes by itself
        snap("40-driver-pending-referral-row")
        app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "tasdiqlash uchun bosing")).firstMatch.tap()
        waitFor("Taklif dasturi hozircha ishlamayapti", timeout: 20)
        snap("41-driver-referral-program-off-kept")
        XCTAssertTrue(row.exists, "the code must stay while the programme is off")
        open("elchi://bookings/bkg_hjoxmd75svahvm262fn2grhfze", banner: "Bu havolani ilovada ochib bo'lmaydi")
        snap("42-driver-booking-link-unsupported")
        open("elchi://support-threads/\(thread)")
        waitFor("Operator bilan yozishma", timeout: 20)
        sleep(2)
        snap("43-driver-support-thread-link")
    }
}
