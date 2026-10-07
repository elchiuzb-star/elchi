import XCTest

/// Stage 08 (driver: private trip plans, the matching-requests feed, saved routes, the offer, "Takliflarim") against
/// the running development backend, in phases the shell drives (scratchpad `ios-s08/run.sh`), which creates the
/// client's requests and plays the client's counters (`ios_s08.py`, `offers.py`) between them.
///
/// Phones come from the shell (`TEST_RUNNER_*`): `DRIVER` = +998900001011 (approved), `SPARE` = an approved iOS
/// throwaway with no trips (+99895…), `NEWBIE` = an unapproved throwaway (the gate). Listings: `LISTING_A` (offer,
/// counters, accept), `LISTING_B` ("Mijoz narxiga roziman", then withdraw), `THREAD` = the thread on A.
final class DriverMarketUITests: ClientUITestCase {
    private func env(_ name: String) -> String {
        let value = ProcessInfo.processInfo.environment[name] ?? ""
        XCTAssertFalse(value.isEmpty, "\(name) not passed (TEST_RUNNER_\(name))")
        return value
    }

    // MARK: Helpers

    private func signInAsDriver(_ phone: String, locale: String = "uz") {
        let ru = locale == "ru"
        tap(ru ? "Начать" : "Boshlash")
        tap(ru ? "Далее" : "Keyingisi")
        tap(ru ? "Далее" : "Keyingisi")
        tap(ru ? "Начать" : "Boshlash")
        app.buttons.containing(NSPredicate(format: "label CONTAINS %@", ru ? "Я водитель" : "Men haydovchiman")).firstMatch.tap()
        let phoneField = app.textFields.firstMatch
        XCTAssertTrue(phoneField.waitForExistence(timeout: 10))
        phoneField.tap()
        for digit in phone { phoneField.typeText(String(digit)) }
        tap(ru ? "Получить код" : "Kod olish")
        XCTAssertTrue(app.textFields.firstMatch.waitForExistence(timeout: 10))
        app.textFields.firstMatch.typeText("1234")
        XCTAssertTrue(app.buttons["elchi.tab.home"].waitForExistence(timeout: 25), "no driver tabs")
    }

    private func tab(_ name: String) {
        // Design v3: Yo'nalishlar is the second segment of Moslar.
        let item = app.buttons["elchi.tab.\(name == "routes" ? "matches" : name)"]
        XCTAssertTrue(item.waitForExistence(timeout: 15), "no tab \(name)")
        item.tap()
        if name == "routes" {
            let segment = app.buttons["elchi.matches.segment.directions"]
            if segment.waitForExistence(timeout: 10) { segment.tap() }
        }
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
        // The tab bar / footer covers the bottom of the scroll view: lift an element that sits under it.
        var nudges = 0
        while element.exists && element.frame.maxY > app.frame.height - 190 && nudges < 4 {
            let start = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.7))
            start.press(forDuration: 0.05, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.45)))
            nudges += 1
        }
        // A tap during the scroll's momentum only stops it.
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

    /// A `SelectField` (system menu): open it by its label, pick the option.
    private func choose(_ option: String, in label: String) {
        let field = app.buttons[label].firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 15), "no select '\(label)'")
        field.tap()
        let item = app.buttons.containing(NSPredicate(format: "label BEGINSWITH %@", option)).firstMatch
        XCTAssertTrue(item.waitForExistence(timeout: 10), "no option '\(option)'")
        item.tap()
    }

    /// The first trip card (its title; the whole card opens the trip).
    private func openFirstTrip() {
        let title = app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "→")).firstMatch
        XCTAssertTrue(title.waitForExistence(timeout: 15), "no trip card")
        title.tap()
    }

    private func scrollTop() {
        for _ in 0..<4 { app.swipeDown() }
    }

    /// The feed's route: Toshkent shahri -> Samarqand viloyati / Samarqand (only when not remembered yet).
    private func ensureFeedRoute(_ locale: String = "uz") {
        let ru = locale == "ru"
        let from = app.buttons[ru ? "Откуда?" : "Qayerdan?"].firstMatch
        if from.waitForExistence(timeout: 5) {
            from.tap()
            tap(ru ? "Ташкент" : "Toshkent shahri")
            waitFor(ru ? "Куда?" : "Qayerga?")
        }
        let to = app.buttons[ru ? "Куда?" : "Qayerga?"].firstMatch
        if to.waitForExistence(timeout: 3) {
            to.tap()
            tap(ru ? "Самарканд" : "Samarqand viloyati")
            waitFor(ru ? "Выберите район" : "Tumanni tanlang")
            app.buttons.matching(NSPredicate(format: "label == %@", ru ? "Самарканд" : "Samarqand")).firstMatch.tap()
        }
    }

    // MARK: Phases

    /// SPARE: an approved driver without trips sees the empty state (route icon, the private-plan hint, add button).
    func test1_EmptyTrips() {
        launch(theme: "light")
        signInAsDriver(env("SPARE"))
        tab("routes")
        waitFor("Hozircha yo'nalish qo'shilmagan")
        snap("01-trips-empty")
        tab("orders")
        waitFor("Takliflarim")
        snap("01b-orders-tab")
    }

    /// DRIVER: trips list -> add trip (corridor, route, departure - ADR-0028: no stop filter) -> detail -> start boarding too early.
    func test2_AddTrip() {
        launch(theme: "light")
        signInAsDriver(env("DRIVER"))
        snap("02-home-approved")
        tab("routes")
        waitFor("Status:")
        snap("02b-trips-list")
        byId("elchi.driver.plus").tap()
        waitFor("Qayerdan - qayerga")
        snap("03-add-trip")
        choose("Toshkent - Qashqadaryo", in: "Qayerdan - qayerga")
        waitFor(" km · ")
        snap("04-add-trip-filled")
        app.buttons["Jo'nash vaqti"].firstMatch.tap()
        waitFor("Tasdiqlash")
        snap("05-departure-picker")
        tap("Tasdiqlash")
        tap("Saqlash")
        waitFor("Safar tafsilotlari", timeout: 20)
        waitFor("Hisoblangan qoldiq", timeout: 20)
        snap("06-trip-detail")
        scrollTo(byId("elchi.trip.manifest"))
        waitFor("Bu safarda hali bron yo'q")
        snap("07-trip-detail-manifest")
        tapId("elchi.trip.next")
        waitFor("da ochiladi", timeout: 20)
        snap("08-boarding-too-early")
    }

    /// Feed with the route, the date chips and (when the server has any) the alternatives section.
    func test3_Feed() {
        launch(theme: "light", reset: false)
        tab("matches")
        ensureFeedRoute()
        waitFor("Mosliklar tasdiqlangan yo'nalish", timeout: 20)
        tap("Ertaga")
        waitFor("Taklif yuborish", timeout: 20)
        snap("09-feed-tomorrow")
        tap("14 kun")
        waitFor("Taklif yuborish", timeout: 20)
        let alternatives = app.descendants(matching: .any)["elchi.feed.alternatives"]
        scrollTo(alternatives, maxSwipes: 12)
        snap("10-feed-scrolled")
    }

    /// Saved routes: save the feed's route, the list, delete behind a confirmation, save again.
    func test4_Saved() {
        launch(theme: "light", reset: false)
        tab("matches")
        ensureFeedRoute()
        tap("Saqlangan yo'nalishlar")
        waitFor("Hozirgi yo'nalish")
        snap("11-saved")
        tap("Shu yo'nalishni saqlash")
        waitFor("bildirishnoma yoqilgan", timeout: 20)
        snap("12-saved-list")
        app.buttons.matching(NSPredicate(format: "label == %@", "O'chirish")).firstMatch.tap()
        let confirm = byId("elchi.saved.confirmDelete")
        snap("12b-saved-delete-confirm")
        confirm.tap()
        waitFor("O'chirildi", timeout: 20)
        snap("13-saved-deleted")
        tap("Shu yo'nalishni saqlash")
        waitFor("bildirishnoma yoqilgan", timeout: 20)
    }

    /// The offer screen (board, trip, window, commission) -> send a price -> the thread.
    func test5_Offer() {
        launch(theme: "light", reset: false)
        tab("matches")
        ensureFeedRoute()
        waitFor("Taklif yuborish", timeout: 20)
        tapId("elchi.feed.offer.\(env("LISTING_A"))", timeout: 20)
        waitFor("Boshqa haydovchilar takliflari", timeout: 20)
        waitFor("Taxminiy komissiya", timeout: 20)
        snap("14-offer")
        scrollTo(byId("elchi.offer.commission"))
        snap("15-offer-commission")
        replace("Taklif narxi", with: "125000")
        waitFor("125\u{202F}000", timeout: 10)
        tapId("elchi.offer.send")
        waitFor("javob kutilmoqda", timeout: 25)
        snap("16-thread-sent")
    }

    /// After the client's counter (shell): "Takliflarim" -> the thread -> the driver counters.
    func test6_Counter() {
        launch(theme: "light", reset: false)
        tab("orders")
        tapId("elchi.driver.proposals")
        waitFor("Mijoz qarshi taklif yubordi", timeout: 20)
        snap("17-proposals-open")
        tapId("elchi.proposal.\(env("THREAD"))")
        waitFor("Mijoz qarshi taklif yubordi", timeout: 20)
        snap("18-thread-countered")
        tapId("elchi.thread.counter")
        replace("Yangi narx (so'm)", with: "118000")
        tapId("elchi.thread.counterSend")
        waitFor("javob kutilmoqda", timeout: 25)
        snap("19-thread-driver-countered")
    }

    /// After the client's second counter (shell): the driver accepts -> booking.
    func test7_Accept() {
        launch(theme: "light", reset: false, extra: ["-uiTestDriverScreen", "proposals"])
        tapId("elchi.proposal.\(env("THREAD"))")
        waitFor("Mijoz qarshi taklif yubordi", timeout: 20)
        scrollTo(byId("elchi.thread.history"))
        snap("20-thread-history")
        scrollTop()
        tapId("elchi.thread.accept")
        waitFor("Kelishilgan narx")
        snap("21-accept-dialog")
        tapId("elchi.thread.acceptConfirm")
        byId("elchi.thread.booked", timeout: 30)
        snap("22-booked")
    }

    /// "Mijoz narxiga roziman" sends at once -> the thread -> withdraw behind a confirmation.
    func test8_ClientPriceWithdraw() {
        launch(theme: "light", reset: false)
        tab("matches")
        ensureFeedRoute()
        waitFor("Taklif yuborish", timeout: 20)
        tapId("elchi.feed.offer.\(env("LISTING_B"))", timeout: 20)
        waitFor("Taxminiy komissiya", timeout: 20)
        tapId("elchi.offer.acceptClientPrice")
        waitFor("javob kutilmoqda", timeout: 25)
        snap("23-thread-client-price")
        tapId("elchi.thread.withdraw")
        waitFor("Taklif o'rin yoki balansni")
        snap("24-withdraw-confirm")
        tapId("elchi.thread.withdrawConfirm")
        waitFor("qaytarib olingan", timeout: 20)
        snap("25-withdrawn")
    }

    /// SPARE with a trip boardable now (shell): the cancel sheet, start boarding -> pause (reason) -> resume (back on the
    /// road) -> complete.
    func test9_PauseResume() {
        launch(theme: "light")
        signInAsDriver(env("SPARE"))
        tab("routes")
        waitFor("Status:")
        openFirstTrip()
        waitFor("Safar tafsilotlari")
        scrollTap("Safarni bekor qilish")
        waitFor("Sababini qisqa yozing")
        snap("26a-cancel-reason")
        tap("Ortga")
        tapId("elchi.trip.next")
        waitFor("Chiqish boshlandi", timeout: 20)
        snap("26-boarding")
        scrollTap("Safarni to'xtatish")
        type("Shina teshildi", into: "Sabab")
        snap("27-pause-reason")
        tapId("elchi.reason.confirm")
        waitFor("To'xtatilgan", timeout: 20)
        snap("28-interrupted")
        scrollTap("Safarni davom ettirish")
        type("Shina almashtirildi", into: "Sabab")
        tapId("elchi.reason.confirm")
        waitFor("Yo'lda", timeout: 20)
        snap("29-resumed")
        scrollTap("Safarni yakunlash")
        waitFor("Yakunlangan", timeout: 20)
        snap("30-completed")
    }

    /// NEWBIE (unapproved): the Stage 07 gate still covers the three tabs.
    func testG_Gate() {
        launch(theme: "light")
        signInAsDriver(env("NEWBIE"))
        tab("matches")
        byId("elchi.driver.gate")
        snap("32-gate-matches")
        tab("routes")
        byId("elchi.driver.gate")
    }

    // MARK: Other theme and language (DRIVER, still signed in)

    private func tour(_ prefix: String, locale: String) {
        let ru = locale == "ru"
        tab("routes")
        waitFor(ru ? "Статус:" : "Status:", timeout: 20)
        snap("\(prefix)-01-trips")
        openFirstTrip()
        waitFor(ru ? "Расчётный остаток" : "Hisoblangan qoldiq", timeout: 20)
        snap("\(prefix)-02-trip-detail")
        tap(ru ? "Назад" : "Orqaga")
        byId("elchi.driver.plus").tap()
        waitFor(ru ? "Откуда - куда" : "Qayerdan - qayerga")
        snap("\(prefix)-03-add-trip")
        tap(ru ? "Назад" : "Orqaga")
        tab("matches")
        ensureFeedRoute(locale)
        waitFor(ru ? "Отправить предложение" : "Taklif yuborish", timeout: 20)
        snap("\(prefix)-04-feed")
        tap(ru ? "Сохранённые направления" : "Saqlangan yo'nalishlar")
        waitFor(ru ? "Текущее направление" : "Hozirgi yo'nalish")
        snap("\(prefix)-05-saved")
        tap(ru ? "Назад" : "Orqaga")
        tapId("elchi.feed.offer.\(env("LISTING_C"))", timeout: 20)
        waitFor(ru ? "Ориентировочная комиссия" : "Taxminiy komissiya", timeout: 20)
        snap("\(prefix)-06-offer")
        tap(ru ? "Назад" : "Orqaga")
        tab("orders")
        tapId("elchi.driver.proposals")
        waitFor(ru ? "Закрыто" : "Yopilgan")
        tap(ru ? "Принято" : "Qabul qilingan")
        byId("elchi.proposal.\(env("THREAD"))", timeout: 20)
        snap("\(prefix)-07-proposals")
        byId("elchi.proposal.\(env("THREAD"))", timeout: 20)
        tapId("elchi.proposal.\(env("THREAD"))")
        byId("elchi.thread.booked", timeout: 20)
        snap("\(prefix)-08-thread-booked")
    }

    func testL_Light() {
        launch(theme: "light")
        signInAsDriver(env("DRIVER"))
        tour("l", locale: "uz")
    }

    func testD_Dark() {
        launch(theme: "dark", reset: false)
        tour("d", locale: "uz")
    }

    func testR_Russian() {
        launch(locale: "ru", theme: "light", reset: false)
        tour("r", locale: "ru")
    }
}
