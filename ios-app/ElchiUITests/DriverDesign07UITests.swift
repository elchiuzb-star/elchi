import XCTest

/// DESIGN07 (driver trips, feed, saved routes, offers, negotiation) against the development backend. The shell makes
/// the data first (scratchpad `d07/setup2.py`): the approved demo driver (+998900001011) has a planned trip with two
/// open offers - A countered by the client, B waiting - and a third request C without an offer, all on the saved route
/// Toshkent shahri -> Samarqand.
///
/// Env (`TEST_RUNNER_*`): `D07_LOCALE` (uz / ru), `D07_THEME` (light / dark), `D07_PREFIX` (file prefix), `D07_TRIP`,
/// `D07_C` (listing C), `D07_THREAD_A`, `D07_ACCEPT` = 1 to finish with the accept -> booking chat step (mutates).
final class DriverDesign07UITests: ClientUITestCase {
    private func env(_ name: String, _ fallback: String = "") -> String {
        let value = ProcessInfo.processInfo.environment[name] ?? ""
        return value.isEmpty ? fallback : value
    }

    private var ru: Bool { env("D07_LOCALE", "uz") == "ru" }
    private var prefix: String { env("D07_PREFIX", "uz") }

    private func t(_ uz: String, _ ruText: String) -> String { ru ? ruText : uz }

    private func signIn(_ phone: String) {
        tap(t("Boshlash", "Начать"))
        tap(t("Keyingisi", "Далее"))
        tap(t("Keyingisi", "Далее"))
        tap(t("Boshlash", "Начать"))
        app.buttons.containing(NSPredicate(format: "label CONTAINS %@", t("Men haydovchiman", "Я водитель"))).firstMatch.tap()
        let phoneField = app.textFields.firstMatch
        XCTAssertTrue(phoneField.waitForExistence(timeout: 10))
        phoneField.tap()
        for digit in phone { phoneField.typeText(String(digit)) }
        tap(t("Kod olish", "Получить код"))
        XCTAssertTrue(app.textFields.firstMatch.waitForExistence(timeout: 10))
        app.textFields.firstMatch.typeText("1234")
        XCTAssertTrue(app.buttons["elchi.tab.home"].waitForExistence(timeout: 25), "no driver tabs")
    }

    private func tab(_ name: String) {
        let item = app.buttons["elchi.tab.\(name)"]
        XCTAssertTrue(item.waitForExistence(timeout: 15), "no tab \(name)")
        item.tap()
    }

    @discardableResult
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
        element.tap()
    }

    private func back() {
        let button = app.buttons[t("Orqaga", "Назад")].firstMatch
        XCTAssertTrue(button.waitForExistence(timeout: 10), "no back")
        button.tap()
    }

    private func scrollTop() {
        for _ in 0..<4 { app.swipeDown() }
    }

    private func settle(_ seconds: TimeInterval = 1.5) { Thread.sleep(forTimeInterval: seconds) }

    /// The previous run's session when there is one (the OTP request is rate limited), else a fresh sign-in.
    private func startSignedIn() {
        launch(locale: env("D07_LOCALE", "uz"), theme: env("D07_THEME", "light"), reset: false)
        if app.buttons["elchi.tab.home"].waitForExistence(timeout: 12) {
            app.buttons["elchi.tab.home"].tap()
            return
        }
        app.terminate()
        launch(locale: env("D07_LOCALE", "uz"), theme: env("D07_THEME", "light"))
        signIn("900001011")
    }

    func testDesign07Tour() {
        startSignedIn()
        let trip = env("D07_TRIP")

        // 1. Home: the 06 blocks, then 07's no-hold line, the three counts and "Yangi safar rejalashtirish".
        let stats = byId("elchi.driver.home.stats", timeout: 25)
        scrollTo(byId("elchi.driver.home.planTrip"))
        XCTAssertTrue(stats.exists)
        settle(2)
        snap("\(prefix)-01-home")

        // 2. Yo'nalishlarim: the badge on each card, primary next step.
        tab("routes")
        byId("elchi.trip.\(trip)", timeout: 20)
        settle()
        snap("\(prefix)-02-trips")

        // 3. Add trip: the locked vehicle, save with gaps -> every field says what. ADR-0027: the bar's "+" adds a
        //    direction now; the manual trip form is the fallback under "Safarlarim".
        tapId("elchi.directions.planTrip")
        byId("elchi.addTrip.vehicleLocked", timeout: 20)
        settle()
        snap("\(prefix)-03-addtrip")
        tapId("elchi.addTrip.save")
        settle()
        snap("\(prefix)-04-addtrip-errors")
        back()

        // 4. Trip detail: header badge, stop dots, capacity, manifest (empty text), refresh icon.
        tapId("elchi.trip.\(trip)")
        byId("elchi.trip.header", timeout: 20)
        byId("elchi.bar.refresh").tap()
        settle(2)
        snap("\(prefix)-05-trip")
        scrollTo(byId("elchi.trip.manifest"))
        settle()
        snap("\(prefix)-06-trip-manifest")
        back()

        // 5. Moslar: the Takliflarim pill with the countered count; saved routes -> "Lentada ochish".
        tab("matches")
        byId("elchi.feed.proposals", timeout: 20)
        tapId("elchi.feed.saved")
        let open = app.buttons[t("Lentada ochish", "Открыть в ленте")].firstMatch
        let found = open.waitForExistence(timeout: 20)
        if !found { snap("\(prefix)-debug-saved"); print(app.debugDescription) }
        XCTAssertTrue(found, "no saved route")
        settle()
        snap("\(prefix)-07-saved")
        let enabled = XCTNSPredicateExpectation(predicate: NSPredicate(format: "enabled == true"), object: open)
        _ = XCTWaiter().wait(for: [enabled], timeout: 15)
        open.tap()
        settle(3)
        snap("\(prefix)-08-feed")
        let viewOffer = app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "elchi.feed.viewOffer.")).firstMatch
        XCTAssertTrue(viewOffer.waitForExistence(timeout: 20), "no 'already offered' card")
        scrollTo(viewOffer)
        settle()
        snap("\(prefix)-09-feed-offered")

        // 6. Back on the saved routes: the same ends are "Allaqachon saqlangan".
        scrollTop()
        tapId("elchi.feed.saved")
        byId("elchi.saved.save", timeout: 15)
        settle()
        snap("\(prefix)-10-saved-already")
        back()

        // 7. The offer screen on C: the commission prompt with no price, the price error on send.
        let listingC = env("D07_C")
        if !listingC.isEmpty {
            tapId("elchi.feed.offer.\(listingC)", timeout: 20)
            let price = app.textFields.firstMatch
            XCTAssertTrue(price.waitForExistence(timeout: 15))
            settle(2)
            snap("\(prefix)-11-offer")
            price.tap()
            price.press(forDuration: 1.2)
            if app.menuItems[t("Hammasini tanlash", "Выбрать все")].waitForExistence(timeout: 2) {
                app.menuItems[t("Hammasini tanlash", "Выбрать все")].tap()
            }
            price.typeText(XCUIKeyboardKey.delete.rawValue)
            for _ in 0..<10 { price.typeText(XCUIKeyboardKey.delete.rawValue) }
            byId("elchi.offer.commissionPrompt", timeout: 10)
            byId("elchi.offer.send").tap()
            settle()
            snap("\(prefix)-12-offer-empty")
            back()
        }

        // 8. Takliflarim: badges and lines (countered with both prices, waiting).
        scrollTop()
        byId("elchi.feed.proposals").tap()
        let threadA = env("D07_THREAD_A")
        byId("elchi.proposal.\(threadA)", timeout: 20)
        settle(2)
        snap("\(prefix)-13-proposals")

        // 9. The countered thread: "Boshqa narx", an empty send -> the inline error.
        byId("elchi.proposal.\(threadA)").tap()
        tapId("elchi.thread.counter", timeout: 20)
        tapId("elchi.thread.counterSend")
        settle()
        snap("\(prefix)-14-thread-counter-error")
        app.buttons[t("Bekor qilish", "Отмена")].firstMatch.tap()

        guard env("D07_ACCEPT") == "1" else { return }
        // 10. Accept the client's price -> the booking chat opens (Q100).
        tapId("elchi.thread.accept")
        tapId("elchi.thread.acceptConfirm")
        XCTAssertTrue(app.staticTexts[t("Xabarlar", "Сообщения")].waitForExistence(timeout: 25)
                      || app.descendants(matching: .any)["elchi.bar.subtitle"].waitForExistence(timeout: 5), "no booking chat after accept")
        settle(2)
        snap("\(prefix)-15-accept-chat")

        // 11. The trip's manifest now has the booking with its phone note and "Chat".
        back()
        back()
        back()
        tab("routes")
        tapId("elchi.trip.\(trip)")
        let chat = app.buttons[t("Xabarlar", "Сообщения")].firstMatch
        XCTAssertTrue(chat.waitForExistence(timeout: 20), "no manifest chat")
        scrollTo(chat)
        settle()
        snap("\(prefix)-16-manifest-row")
        tab("orders")
        settle(2)
        snap("\(prefix)-17-orders")
    }

    /// After the accept: the trip's manifest row (phone note + "Chat") and its chat; the orders tab.
    func testDesign07Manifest() {
        startSignedIn()
        tab("routes")
        tapId("elchi.trip.\(env("D07_TRIP"))", timeout: 20)
        let chat = app.buttons[t("Xabarlar", "Сообщения")].firstMatch
        XCTAssertTrue(chat.waitForExistence(timeout: 20), "no manifest chat")
        scrollTo(chat)
        settle()
        snap("\(prefix)-16-manifest-row")
        chat.tap()
        XCTAssertTrue(app.textFields.firstMatch.waitForExistence(timeout: 20) || app.textViews.firstMatch.waitForExistence(timeout: 5), "no chat")
        settle()
        snap("\(prefix)-17-manifest-chat")
        back()
        back()
        back()
        tab("orders")
        settle(2)
        snap("\(prefix)-18-orders")
    }

    /// Orders title / empty wording only (any locale).
    func testDesign07Orders() {
        startSignedIn()
        tab("orders")
        settle(2)
        snap("\(prefix)-orders")
    }
}
