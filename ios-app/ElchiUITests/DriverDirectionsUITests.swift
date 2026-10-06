import XCTest

/// ADR-0027 (driver directions) against the development backend, in phases the shell drives. The shell first makes
/// three passenger requests for the iOS client (+998930800801) on Toshkent -> Samarqand: R1 and R2 tonight (the
/// first offer plans the trip around R1, R2 then fits it) and R3 earlier (once the trip exists the car is there at
/// another time -> a time proposal).
///
/// Env (`TEST_RUNNER_*`): `DIR_LOCALE` (uz / ru), `DIR_THEME` (light / dark), `DIR_PREFIX` (file prefix), `DIR_R1`,
/// `DIR_R2`, `DIR_R3` (listing ids), `SHOTS` (screenshot folder).
///
/// 1. `test1_DriverDirectionTour` (driver +998900001011, signs in): empty Routes tab, the add form (empty, errors,
///    filled), the saved direction, the no-road answer, the direction feed, an offer with no trip -> "trip planned",
///    a second offer on the same trip, the time proposal on R3, the direction card's trip line and the trip detail.
/// 2. `test2_ClientTimeProposal` (client +998930800801, signs in): R3's offers show the time-proposal line; accept ->
///    the booking chat (Q100).
/// 3. `test3_DriverScreens` (driver still signed in): the Routes tab, the feed and the add form for the locale/theme.
final class DriverDirectionsUITests: ClientUITestCase {
    private func env(_ name: String, _ fallback: String = "") -> String {
        let value = ProcessInfo.processInfo.environment[name] ?? ""
        return value.isEmpty ? fallback : value
    }

    private var ru: Bool { env("DIR_LOCALE", "uz") == "ru" }
    private var prefix: String { env("DIR_PREFIX", "uz") }
    private func t(_ uz: String, _ ruText: String) -> String { ru ? ruText : uz }

    private func signIn(_ phone: String, driver: Bool) {
        tap(t("Boshlash", "Начать"))
        tap(t("Keyingisi", "Далее"))
        tap(t("Keyingisi", "Далее"))
        tap(t("Boshlash", "Начать"))
        let role = driver ? t("Men haydovchiman", "Я водитель") : t("Men mijozman", "Я клиент")
        app.buttons.containing(NSPredicate(format: "label CONTAINS %@", role)).firstMatch.tap()
        let phoneField = app.textFields.firstMatch
        XCTAssertTrue(phoneField.waitForExistence(timeout: 10))
        phoneField.tap()
        for digit in phone { phoneField.typeText(String(digit)) }
        tap(t("Kod olish", "Получить код"))
        XCTAssertTrue(app.textFields.firstMatch.waitForExistence(timeout: 10))
        app.textFields.firstMatch.typeText("1234")
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

    private func scrollTop() { for _ in 0..<4 { app.swipeDown() } }
    private func settle(_ seconds: TimeInterval = 1.5) { Thread.sleep(forTimeInterval: seconds) }

    private func startDriver(reset: Bool) {
        launch(locale: env("DIR_LOCALE", "uz"), theme: env("DIR_THEME", "light"), reset: reset)
        if !reset, app.buttons["elchi.tab.home"].waitForExistence(timeout: 12) { return }
        if !reset {
            app.terminate()
            launch(locale: env("DIR_LOCALE", "uz"), theme: env("DIR_THEME", "light"))
        }
        signIn("900001011", driver: true)
        XCTAssertTrue(app.buttons["elchi.tab.home"].waitForExistence(timeout: 25), "no driver tabs")
    }

    /// Region, then (when asked) district, through the searchable sheet.
    private func pick(_ field: String, search: String, row: String) {
        tapId(field)
        let searchField = app.textFields.firstMatch
        XCTAssertTrue(searchField.waitForExistence(timeout: 10))
        searchField.tap()
        searchField.typeText(search)
        tapId("elchi.placePicker.row.\(row)", timeout: 20)
        settle(1)
    }

    private func toast(_ text: String) {
        waitFor(text, timeout: 20)
    }

    func test1_DriverDirectionTour() {
        startDriver(reset: true)
        let r1 = env("DIR_R1"), r2 = env("DIR_R2"), r3 = env("DIR_R3")

        // 1. Yo'nalishlarim: no direction yet, the trips section under it.
        tab("routes")
        byId("elchi.directions.empty", timeout: 20)
        settle(2)
        snap("\(prefix)-01-routes-empty")

        // 2. The add form: two ends only; "Saqlash" with gaps marks the fields.
        tapId("elchi.driver.plus")
        byId("elchi.addDirection.hint", timeout: 15)
        settle()
        snap("\(prefix)-02-form")
        tapId("elchi.addDirection.save")
        settle()
        snap("\(prefix)-03-form-errors")

        // 3. Toshkent shahri (the whole city) -> Samarqand viloyati / Samarqand.
        pick("elchi.addDirection.origin.region", search: "Toshkent sh", row: "Toshkent shahri")
        pick("elchi.addDirection.destination.region", search: "Samarqand", row: "Samarqand viloyati")
        pick("elchi.addDirection.destination.district", search: "Samar", row: "Samarqand")
        settle()
        snap("\(prefix)-04-form-filled")
        tapId("elchi.addDirection.save")
        let card = app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "elchi.direction.drd_")).firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 25), "no direction card after save")
        settle(1)
        snap("\(prefix)-05-direction-added")

        // 4. A direction with no ELCHI road: the product answer in place.
        tapId("elchi.driver.plus")
        pick("elchi.addDirection.origin.region", search: "Andijon", row: "Andijon viloyati")
        pick("elchi.addDirection.origin.district", search: "Andijon", row: "Andijon")
        pick("elchi.addDirection.destination.region", search: "Surxon", row: "Surxondaryo viloyati")
        pick("elchi.addDirection.destination.district", search: "Angor", row: "Angor")
        tapId("elchi.addDirection.save")
        byId("elchi.addDirection.notice", timeout: 20)
        settle()
        snap("\(prefix)-06-no-road")
        back()

        // 5. Moslar: the direction feed (Taksi, 7 days) above the district search.
        tab("matches")
        if app.buttons[t("Taksi", "Такси")].firstMatch.waitForExistence(timeout: 10) { app.buttons[t("Taksi", "Такси")].firstMatch.tap() }
        tapId("elchi.dirFeed.day.week", timeout: 20)
        byId("elchi.dirFeed.offer.\(r1)", timeout: 25)
        settle(2)
        snap("\(prefix)-07-feed")

        // 6. First offer with no trip: the system plans the trip -> "Safar HH:MM da jo'nashga rejalashtirildi".
        tapId("elchi.dirFeed.offer.\(r1)")
        byId("elchi.dirOffer.send", timeout: 20)
        settle(2)
        snap("\(prefix)-08-offer")
        byId("elchi.dirOffer.send").tap()
        toast(t("rejalashtirildi", "запланирован"))
        settle(1)
        snap("\(prefix)-09-trip-planned")
        back() // the thread opened over the feed (as after a trip offer)

        // 7. Second offer: the same trip takes it.
        byId("elchi.dirFeed.group.fits", timeout: 25)
        tapId("elchi.dirFeed.offer.\(r2)", timeout: 20)
        byId("elchi.dirOffer.send", timeout: 20)
        settle(2)
        snap("\(prefix)-10-offer-fits")
        byId("elchi.dirOffer.send").tap()
        toast(t("Taklif yuborildi", "Предложение отправлено"))
        settle(1)
        snap("\(prefix)-11-second-offer")
        back()

        // 8. R3 at another time: the time-proposal sentence and "HH:MM ni taklif qilish".
        let other = byId("elchi.dirFeed.offer.\(r3)", timeout: 25)
        scrollTo(other)
        settle()
        snap("\(prefix)-12-feed-other-time")
        other.tap()
        byId("elchi.dirOffer.timeProposal", timeout: 20)
        settle(2)
        snap("\(prefix)-13-offer-time-proposal")
        byId("elchi.dirOffer.send").tap()
        toast(t("Taklif yuborildi", "Предложение отправлено"))
        settle(1)
        snap("\(prefix)-14-time-proposal-sent")
        back()

        // 9. Yo'nalishlarim: the trip line on the card; the trip read by districts and estimated times (Q158).
        tab("routes")
        byId("elchi.directions.tripsTitle", timeout: 20)
        settle(2)
        snap("\(prefix)-15-routes-trip")
        let trip = app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "elchi.trip.trp_")).firstMatch
        XCTAssertTrue(trip.waitForExistence(timeout: 20), "no trip card")
        scrollTo(trip)
        trip.tap()
        byId("elchi.trip.alongTheRoad", timeout: 20)
        settle(2)
        snap("\(prefix)-16-trip-detail")
    }

    func test2_ClientTimeProposal() {
        let r3 = env("DIR_R3")
        launch(locale: env("DIR_LOCALE", "uz"), theme: env("DIR_THEME", "light"), extra: ["-uiTestOpenListing", r3])
        signIn("930800801", driver: false)
        waitFor(t("Buyurtma tafsilotlari", "Детали заказа"), timeout: 30)
        let line = waitFor(t("olishni taklif qilmoqda", "предлагает забрать"), timeout: 30)
        scrollTo(line)
        settle(2)
        snap("\(prefix)-20-client-time-proposal")
        tap(t("Tanlash", "Выбрать"))
        byId("elchi.accept.timeProposal", timeout: 15)
        settle(1)
        snap("\(prefix)-21-client-accept-dialog")
        tap(t("Ha, tanlayman", "Да, выбираю"))
        XCTAssertTrue(app.textFields.firstMatch.waitForExistence(timeout: 30) || app.textViews.firstMatch.waitForExistence(timeout: 5),
                      "no booking chat after accept")
        settle(2)
        snap("\(prefix)-22-client-booking-chat")
    }

    func test3_DriverScreens() {
        startDriver(reset: false)
        tab("routes")
        let card = app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "elchi.direction.drd_")).firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 25), "no direction card")
        settle(2)
        snap("\(prefix)-routes")
        let archive = app.buttons[t("O'chirish", "Удалить")].firstMatch
        scrollTo(archive)
        archive.tap()
        byId("elchi.directions.archiveConfirmText", timeout: 10)
        settle(1)
        snap("\(prefix)-archive-confirm")
        app.buttons[t("Ortga", "Назад")].firstMatch.tap()
        scrollTop()
        tab("matches")
        if app.buttons[t("Taksi", "Такси")].firstMatch.waitForExistence(timeout: 10) { app.buttons[t("Taksi", "Такси")].firstMatch.tap() }
        tapId("elchi.dirFeed.day.week", timeout: 20)
        let offered = app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "elchi.dirFeed.")).firstMatch
        XCTAssertTrue(offered.waitForExistence(timeout: 25), "no direction feed")
        settle(3)
        snap("\(prefix)-feed")
        tab("routes")
        tapId("elchi.driver.plus")
        byId("elchi.addDirection.hint", timeout: 15)
        settle()
        snap("\(prefix)-form")
    }

    /// 4. On the existing direction (driver signed in): one more offer from the feed -> the toast and the thread opens
    ///    over the feed (`DIR_R4`), in the run's locale / theme.
    func test4_OfferOpensThread() {
        startDriver(reset: false)
        let r4 = env("DIR_R4")
        tab("matches")
        if app.buttons[t("Taksi", "Такси")].firstMatch.waitForExistence(timeout: 10) { app.buttons[t("Taksi", "Такси")].firstMatch.tap() }
        tapId("elchi.dirFeed.day.week", timeout: 20)
        let offer = byId("elchi.dirFeed.offer.\(r4)", timeout: 25)
        scrollTo(offer)
        settle(2)
        snap("\(prefix)-30-feed")
        offer.tap()
        byId("elchi.dirOffer.send", timeout: 20)
        settle(2)
        snap("\(prefix)-31-offer")
        byId("elchi.dirOffer.send").tap()
        toast(t("Taklif yuborildi", "Предложение отправлено"))
        settle(1)
        snap("\(prefix)-32-sent-thread")
        back()
        byId("elchi.dirFeed.viewOffer.\(r4)", timeout: 25)
        settle(2)
        snap("\(prefix)-33-feed-offered")
    }
}
