import XCTest

/// Stage 09 (driver: bookings, chat, GPS publishing, wallet, credit, profile) against the running development backend,
/// in phases the shell drives (scratchpad `ios-s09/run.sh`): it grants location permissions, runs the simulated route,
/// plays the operator (deliver / complete, top-up approval) and reads the server's rows between phases.
///
/// From the shell (`TEST_RUNNER_*`): `DRIVER` (9 digits), `BOOKING_A` (confirmed: Keldim, chat, amendment, cancel
/// sheet), `BOOKING_C` (confirmed: really cancelled), `BOOKING_GPS` + `TRIP` (the trip boarded and departed in the
/// app), `BOOKING_DONE` (completed: rate the client).
final class DriverStage09UITests: ClientUITestCase {
    private func env(_ name: String) -> String {
        let value = ProcessInfo.processInfo.environment[name] ?? ""
        XCTAssertFalse(value.isEmpty, "\(name) not passed (TEST_RUNNER_\(name))")
        return value
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

    private func tab(_ name: String) {
        let item = app.buttons["elchi.tab.\(name)"]
        XCTAssertTrue(item.waitForExistence(timeout: 15), "no tab \(name)")
        item.tap()
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
        var nudges = 0
        while element.exists && element.frame.maxY > app.frame.height - 190 && nudges < 4 {
            let start = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.7))
            start.press(forDuration: 0.05, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.45)))
            nudges += 1
        }
        if swipes > 0 || nudges > 0 { Thread.sleep(forTimeInterval: 1.2) }
    }

    private func tapId(_ id: String, timeout: TimeInterval = 15) {
        let element = byId(id, timeout: timeout)
        scrollTo(element)
        waitEnabled(element, id)
        element.tap()
    }

    private func scrollTap(_ label: String) {
        let element = button(label)
        scrollTo(element)
        waitEnabled(element, label)
        element.tap()
    }

    private func scrollTop() {
        for _ in 0..<4 { app.swipeDown() }
    }

    private func back() {
        app.buttons["Orqaga"].firstMatch.tap()
    }

    /// The system's location question, when it shows: a screenshot of it, then the answer.
    private func answerLocationAlert(_ answer: String, shot: String? = nil, timeout: TimeInterval = 10) {
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let button = springboard.buttons[answer]
        guard button.waitForExistence(timeout: timeout) else { return }
        if let shot {
            let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            attachment.name = shot
            attachment.lifetime = .keepAlways
            add(attachment)
        }
        button.tap()
    }

    /// The GPS bar's title, when it says `text` (waits).
    private func waitBar(_ text: String, timeout: TimeInterval = 40) {
        let title = app.staticTexts.matching(NSPredicate(format: "identifier == %@ AND label CONTAINS %@", "elchi.gps.title", text)).firstMatch
        XCTAssertTrue(title.waitForExistence(timeout: timeout), "GPS bar never said '\(text)'")
    }

    // MARK: Bookings

    /// Sign in, Buyurtmalar (Faol / Tarix), a confirmed booking: Keldim, chat + quick reply, amendment, the cancel
    /// sheet (kept), the safety screen.
    func test01_Bookings() {
        launch(theme: "light")
        signInAsDriver(env("DRIVER"))
        tab("orders")
        waitFor("Takliflarim")
        byId("elchi.driver.booking.\(env("BOOKING_A"))", timeout: 20)
        snap("01-orders-active")
        tap("Tarix")
        waitFor("Yakunlangan", timeout: 10)
        snap("02-orders-history")
        tap("Faol")
        tapId("elchi.driver.booking.\(env("BOOKING_A"))")
        byId("elchi.driver.booking.card", timeout: 20)
        waitFor("mijozdan naqd olinadi")
        snap("03-booking-confirmed")
        scrollTo(byId("elchi.driver.booking.reputation"))
        snap("04-booking-confirmed-bottom")
        scrollTop()
        tapId("elchi.driver.booking.arrive")
        waitFor("Keldim — mijozga xabar yuborildi", timeout: 20)
        snap("05-keldim-sent")
        tapId("elchi.driver.booking.chat")
        waitFor("5 daqiqada yetaman", timeout: 20)
        tap("5 daqiqada yetaman")
        Thread.sleep(forTimeInterval: 2)
        snap("06-chat-quick-reply")
        back()
        tapId("elchi.driver.booking.amend")
        waitFor("Hozirgi kelishuv", timeout: 20)
        type("150000", into: "Narx (so'm)")
        type("Yo'l uzoqroq", into: "Sabab")
        scrollTap("Taklif yuborish")
        waitFor("Taklif yuborildi", timeout: 20)
        snap("07-amendment-sent")
        back()
        tapId("elchi.driver.booking.cancel")
        waitFor("Bronni bekor qilasizmi?")
        snap("08-cancel-sheet")
        tap("Bronni saqlash")
        let safety = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "Xavfsizlik haqida xabar berish")).firstMatch
        scrollTo(safety)
        safety.tap()
        waitFor("Bloklash", timeout: 15)
        snap("09-safety")
    }

    /// Another confirmed booking really cancelled by the driver (reason "Mashinada nosozlik").
    func test02_Cancel() {
        launch(theme: "light", reset: false, extra: ["-uiTestDriverBooking", env("BOOKING_C")])
        byId("elchi.driver.booking.card", timeout: 20)
        tapId("elchi.driver.booking.cancel")
        waitFor("Bronni bekor qilasizmi?")
        app.buttons["Sabab"].firstMatch.tap()
        app.buttons.containing(NSPredicate(format: "label BEGINSWITH %@", "Mashinada nosozlik")).firstMatch.tap()
        tapId("elchi.driver.cancel.confirm")
        waitFor("Bron bekor qilindi", timeout: 20)
        snap("10-cancelled")
    }

    // MARK: Wallet, credit, profile, notifications

    func test03_WalletTopup() {
        launch(theme: "light", reset: false)
        tapId("elchi.driver.balance")
        byId("elchi.wallet.available", timeout: 20)
        snap("11-wallet")
        scrollTo(byId("elchi.wallet.amount"))
        snap("12-wallet-topup-form")
        type("150000", into: "Summa (so'm)")
        type("+998900001011", into: "To'lovchi ma'lumoti (ixtiyoriy)")
        tapId("elchi.wallet.submit")
        waitFor("To'ldirish so'rovi yuborildi", timeout: 20)
        snap("13-wallet-topup-sent")
        scrollTo(app.staticTexts["To'ldirish so'rovlari"].firstMatch)
        snap("14-wallet-requests")
    }

    /// After the helper approved the request: the balance and the approved badge.
    func test04_WalletApproved() {
        launch(theme: "light", reset: false, extra: ["-uiTestDriverScreen", "wallet"])
        byId("elchi.wallet.available", timeout: 20)
        snap("15-wallet-after-approval")
        scrollTo(app.staticTexts["To'ldirish so'rovlari"].firstMatch)
        waitFor("Tasdiqlangan", timeout: 10)
        snap("16-wallet-approved-request")
        app.swipeUp()
        app.swipeUp()
        snap("17-wallet-transactions")
    }

    func test05_ProfileBonusNotifications() {
        launch(theme: "light", reset: false)
        tab("profile")
        byId("elchi.driver.profile.stats", timeout: 20)
        Thread.sleep(forTimeInterval: 2)
        snap("18-profile")
        app.swipeUp()
        snap("19-profile-actions")
        tapId("elchi.driver.menu.bonus")
        waitFor("Kredit faqat komissiyangizni kamaytiradi", timeout: 20)
        Thread.sleep(forTimeInterval: 2)
        snap("20-bonus")
        back()
        tab("home")
        byId("elchi.driver.bell").tap()
        waitFor("Bildirishnomalar", timeout: 15)
        Thread.sleep(forTimeInterval: 2)
        snap("21-notifications")
    }

    /// A top-up notification opens the wallet (driver notification routing).
    func test05b_NotificationRouting() {
        launch(theme: "light", reset: false, extra: ["-uiTestDriverScreen", "notifications"])
        let item = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "To'ldirish tasdiqlandi")).firstMatch
        XCTAssertTrue(item.waitForExistence(timeout: 20))
        item.tap()
        byId("elchi.wallet.available", timeout: 20)
        snap("21b-notification-to-wallet")
    }

    // MARK: GPS

    /// While-using granted by the shell, a simulated route running: start boarding in the app -> the publisher opens a
    /// session (the Always question appears once; kept at While using) -> "Joylashuv yuborilmoqda" -> depart.
    func test06_BoardAndDepart() {
        launch(theme: "light", reset: false, extra: ["-uiTestDriverTrip", env("TRIP")])
        byId("elchi.trip.header", timeout: 20)
        if app.buttons["Chiqishni boshlash"].firstMatch.waitForExistence(timeout: 3) {
            tapId("elchi.trip.next") // Chiqishni boshlash -> the publisher starts
        }
        // The trip is boarding: publishing starts (or resumes on launch, permission already given).
        answerLocationAlert("Keep Only While Using", shot: "22-always-question", timeout: 20)
        waitBar("Joylashuv yuborilmoqda")
        scrollTop()
        snap("23-trip-boarding-sending")
        tapId("elchi.trip.next") // Yo'lga chiqdim
        waitFor("Yo'lda", timeout: 20)
        waitBar("Joylashuv yuborilmoqda")
        scrollTop()
        snap("24-trip-in-progress-sending")
    }

    /// Always granted by the shell (the app restarted): the running trip resumes publishing on start; the bar says
    /// background sending is on; the app goes to the background for 90 s while the route keeps moving.
    func test07_Background() {
        launch(theme: "light", reset: false, extra: ["-uiTestDriverTab", "routes"])
        waitBar("Joylashuv yuborilmoqda", timeout: 60)
        waitFor("Ilova fonda bo'lsa ham joylashuv yuboriladi", timeout: 20)
        snap("25-trips-background-on")
        XCUIDevice.shared.press(.home)
        Thread.sleep(forTimeInterval: 90)
        snap("26-home-screen-background-indicator")
        app.activate()
        waitBar("Joylashuv yuborilmoqda", timeout: 30)
        snap("27-back-from-background")
    }

    /// K2 made to fail (debug switch) -> points queue on the phone.
    func test08_Offline() {
        launch(theme: "light", reset: false, extra: ["-uiTestDriverTab", "routes", "-elchiDebugGpsOffline", "YES"])
        waitFor("Internet yo'q", timeout: 90)
        Thread.sleep(forTimeInterval: 25)
        snap("28-offline-queued")
    }

    /// Back online (a plain launch): the leftovers go out, the queue empties.
    func test09_Online() {
        launch(theme: "light", reset: false, extra: ["-uiTestDriverTab", "routes"])
        waitBar("Joylashuv yuborilmoqda", timeout: 60)
        waitGone("Internet yo'q", timeout: 60)
        snap("29-online-drained")
    }

    /// The departed booking: in-transit note, receiver after departure, the GPS bar; its chat with the bar on top.
    func test10_BookingInTransit() {
        launch(theme: "light", reset: false, extra: ["-uiTestDriverBooking", env("BOOKING_GPS")])
        byId("elchi.driver.booking.card", timeout: 20)
        waitBar("Joylashuv yuborilmoqda")
        waitFor("operator qayd etadi", timeout: 20)
        snap("30-booking-in-transit")
        tapId("elchi.driver.booking.chat")
        waitFor("Bekatdaman", timeout: 20)
        snap("31-chat-with-gps-bar")
    }

    /// Dark and Russian shots of the main Stage 09 screens (while the trip still runs).
    func test11_DarkRu() {
        for (locale, theme, prefix) in [("uz", "dark", "d"), ("ru", "light", "r")] {
            launch(locale: locale, theme: theme, reset: false, extra: ["-uiTestDriverTab", "orders"])
            byId("elchi.driver.booking.\(env("BOOKING_GPS"))", timeout: 20)
            snap("\(prefix)1-orders")
            byId("elchi.driver.booking.\(env("BOOKING_GPS"))").tap()
            byId("elchi.driver.booking.card", timeout: 20)
            Thread.sleep(forTimeInterval: 2)
            snap("\(prefix)2-booking")
            launch(locale: locale, theme: theme, reset: false, extra: ["-uiTestDriverTrip", env("TRIP")])
            byId("elchi.trip.header", timeout: 20)
            byId("elchi.gps.bar", timeout: 30)
            Thread.sleep(forTimeInterval: 3)
            snap("\(prefix)3-trip-gps")
            launch(locale: locale, theme: theme, reset: false, extra: ["-uiTestDriverScreen", "wallet"])
            byId("elchi.wallet.available", timeout: 20)
            Thread.sleep(forTimeInterval: 2)
            snap("\(prefix)4-wallet")
            launch(locale: locale, theme: theme, reset: false, extra: ["-uiTestDriverTab", "profile"])
            byId("elchi.driver.profile.stats", timeout: 20)
            Thread.sleep(forTimeInterval: 2)
            snap("\(prefix)5-profile")
            launch(locale: locale, theme: theme, reset: false, extra: ["-uiTestDriverScreen", "bonus"])
            Thread.sleep(forTimeInterval: 4)
            snap("\(prefix)6-bonus")
            launch(locale: locale, theme: theme, reset: false,
                   extra: ["-uiTestDriverBooking", env("BOOKING_A"), "-uiTestDriverBookingScreen", "chat"])
            Thread.sleep(forTimeInterval: 4)
            snap("\(prefix)7-chat")
        }
    }

    /// After the operator delivered and completed the booking (shell): rate the client.
    func test12_RateClient() {
        launch(theme: "light", reset: false, extra: ["-uiTestDriverBooking", env("BOOKING_GPS")])
        byId("elchi.driver.booking.card", timeout: 20)
        waitFor("Yakunlangan", timeout: 20)
        tapId("elchi.driver.booking.rate")
        waitFor("1 dan 5 gacha baho bering")
        app.buttons["5 yulduz"].firstMatch.tap()
        type("Rahmat, hammasi joyida", into: "Izoh qoldiring")
        snap("32-rate-client")
        tap("Bahoni yuborish")
        waitFor("Baho yuborildi", timeout: 20)
        snap("33-rated")
    }

    /// The trip completed in the app: the queue is flushed first, the publisher ends with the trip.
    func test13_CompleteTrip() {
        launch(theme: "light", reset: false, extra: ["-uiTestDriverTrip", env("TRIP")])
        byId("elchi.trip.header", timeout: 20)
        tapId("elchi.trip.next") // Safarni yakunlash
        waitFor("Yakunlangan", timeout: 20)
        Thread.sleep(forTimeInterval: 2)
        scrollTop()
        snap("34-trip-completed")
    }

    /// Russian wallet scrolled to the transactions (kind labels from the dictionary).
    func test14_WalletTransactionsRu() {
        launch(locale: "ru", theme: "light", reset: false, extra: ["-uiTestDriverScreen", "wallet"])
        byId("elchi.wallet.available", timeout: 20)
        let title = app.staticTexts["История операций"].firstMatch
        XCTAssertTrue(title.waitForExistence(timeout: 20))
        scrollTo(title, maxSwipes: 14)
        app.swipeUp()
        Thread.sleep(forTimeInterval: 1.5)
        snap("35-wallet-transactions-ru")
    }
}
