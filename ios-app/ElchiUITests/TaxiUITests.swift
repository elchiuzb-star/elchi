import XCTest

/// Taksi (passenger), client and driver, against the running development backend, in phases the shell drives
/// (`elchi-dev/ios-taxi/run.sh`): between phases it plans the driver's trip, opens boarding, reads the boarding code,
/// prepares the no-show booking and the seat-edit request (`ios-taxi/itaxi.py`, `taxi.py`).
///
/// From the shell (`TEST_RUNNER_*`): `CLIENT` / `DRIVER` (9 digits), `LISTING` (the request made in T1), `BOOKING`
/// (made in T3), `CODE` (the passenger's current boarding code), `LISTING2` (a request with an open offer: seat edit),
/// `BOOKING3` (the no-show booking), `THEME` / `LOCALE` for the tour phases.
final class TaxiUITests: ClientUITestCase {
    private func env(_ name: String) -> String {
        let value = ProcessInfo.processInfo.environment[name] ?? ""
        XCTAssertFalse(value.isEmpty, "\(name) not passed (TEST_RUNNER_\(name))")
        return value
    }

    private func envOr(_ name: String, _ fallback: String) -> String {
        let value = ProcessInfo.processInfo.environment[name] ?? ""
        return value.isEmpty ? fallback : value
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

    /// Clears a field found by its label and types (the field is scrolled into view first).
    private func typeInto(_ label: String, _ text: String) {
        let field = self.field(label)
        scrollTo(field)
        field.tap()
        let current = field.value as? String ?? ""
        for _ in 0..<(current.count + 1) { field.typeText(XCUIKeyboardKey.delete.rawValue) }
        for character in text { field.typeText(String(character)) }
    }

    /// "Keldim" unless it was already sent.
    private func arriveIfOffered() {
        let arrive = app.descendants(matching: .any)["elchi.driver.booking.arrive"].firstMatch
        if arrive.waitForExistence(timeout: 5) {
            scrollTo(arrive)
            arrive.tap()
        }
        waitFor("Keldim", timeout: 20)
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

    /// Home in Taksi mode -> both places -> the home's Taksi block (BOSQICH 02): 2 people, 150 000 per person.
    private func taxiRouteStep(prefix: String, locale: String = "uz") {
        let ru = locale == "ru"
        let taxi = app.buttons[ru ? "Такси" : "Taksi"].firstMatch
        XCTAssertTrue(taxi.waitForExistence(timeout: 20), "no Taksi segment")
        taxi.tap()
        if ru {
            pickPlaceRu("Откуда?", region: "Toshkent shahri", district: nil)
            pickPlaceRu("Куда?", region: "Samarqand viloyati", district: "Samarqand")
        } else {
            snap("\(prefix)-01-home-taxi")
            pickPlace("Qayerdan?", region: "Toshkent shahri", district: nil)
            pickPlace("Qayerga?", region: "Samarqand viloyati", district: "Samarqand")
        }
        waitFor(ru ? "Примерное время в пути" : "Taxminiy yo'l vaqti", timeout: 25)
        snap("\(prefix)-02-home-direction")
        waitFor(ru ? "Сколько человек" : "Necha kishi")
        tapId("elchi.seats.2")
        waitFor(ru ? "2 чел." : "2 kishi")
        type("150000", into: ru ? "Цена за одного человека (сум)" : "Bir kishi uchun narx (so'm)")
        let total = byId("elchi.taxi.total")
        scrollTo(total)
        snap("\(prefix)-03-seat-picker")
    }

    private func pickPlaceRu(_ question: String, region: String, district: String?) {
        tap(question)
        waitFor("Сначала выберите регион")
        tap(region)
        if let district {
            waitFor("Выберите район")
            tap(district)
        }
        waitFor("Выбранное место")
        let choose = button("Выбрать это место")
        waitEnabled(choose, "Выбрать это место")
        choose.tap()
    }

    // MARK: Client: the request (T1)

    func testT1_ClientRequest() {
        launch(theme: "light", reset: true, extra: ["-uiTestWindowFromNow", "5"])
        signInAsClient(phone: env("CLIENT"))
        taxiRouteStep(prefix: "t1")
        byId("elchi.keyboard.done").tap()
        tap("Davom etish")
        waitFor("Buyurtmani tekshiring")
        waitFor("O'rinlar")
        snap("t1-04-review")
        tap("Buyurtmani e'lon qilish")
        waitFor("Haydovchilardan takliflar kutilmoqda", timeout: 25)
        snap("t1-05-success")
        tap("Buyurtmalarimga o'tish")
        waitFor("2 kishi", timeout: 20)
        snap("t1-06-orders")
    }

    // MARK: Driver: the feed in Taksi mode, the offer (T2)

    func testT2_DriverOffer() {
        launch(theme: "light", reset: true)
        signInAsDriver(env("DRIVER"))
        tab("matches")
        let taxi = app.buttons["Taksi"].firstMatch
        XCTAssertTrue(taxi.waitForExistence(timeout: 20), "no Taksi toggle")
        taxi.tap()
        ensureFeedRoute()
        let card = byId("elchi.feed.offer.\(env("LISTING"))", timeout: 25)
        scrollTo(card)
        snap("t2-01-feed-taxi")
        card.tap()
        waitFor("Mijoz narxi", timeout: 20)
        waitFor("Boshqa haydovchilar takliflari", timeout: 20)
        snap("t2-02-offer")
        tapId("elchi.offer.acceptClientPrice", timeout: 25)
        waitFor("javob kutilmoqda", timeout: 25)
        snap("t2-03-thread")
    }

    // MARK: Client: the offer, accept, the booking (T3)

    func testT3_ClientAccept() {
        launch(theme: "light", reset: true, extra: ["-uiTestSession", env("SESSION"), "-uiTestOpenListing", env("LISTING")])
        waitFor("2 kishi", timeout: 20)
        snap("t3-01-listing")
        // BOSQICH 03: the offers are inline on the listing's detail.
        scrollTap("Tanlash")
        waitFor("Ha, tanlayman")
        tap("Ortga")
        snap("t3-02-bids")
        tap("Tanlash")
        waitFor("Ha, tanlayman")
        snap("t3-03-accept")
        tap("Ha, tanlayman")
        // Q100: the booking's chat opens; back is the booking.
        let back = app.buttons["Orqaga"].firstMatch
        XCTAssertTrue(back.waitForExistence(timeout: 25))
        back.tap()
        waitFor("Haydovchi va avtomobil", timeout: 20)
        snap("t3-04-booking-confirmed")
    }

    // MARK: Driver: Keldim, boarding, drop-off, cash (T5)

    func testT5_DriverBoard() {
        launch(theme: "light", reset: true, extra: ["-uiTestSession", env("SESSION"), "-uiTestDriverBooking", env("BOOKING")])
        waitFor("Olib ketish kutilmoqda", timeout: 25)
        snap("t5-01-driver-awaiting")
        arriveIfOffered()
        // Q163: no boarding code - "Yo'lovchini chiqardim" is one tap.
        tapId("elchi.driver.taxi.board")
        waitFor("Mashinada", timeout: 25)
        scrollTop()
        snap("t5-03-onboard")
        tapId("elchi.driver.taxi.dropOff", timeout: 20)
        waitFor("Yetib keldi", timeout: 25)
        scrollTop()
        snap("t5-04-arrived")
        tapId("elchi.cash.report", timeout: 20)
        waitFor("Siz qayd qildingiz", timeout: 25)
        scrollTo(byId("elchi.cash.card"))
        snap("t5-05-cash-recorded")
    }

    // MARK: Client: confirms the cash, completes, rates (T6)

    func testT6_ClientFinish() {
        launch(theme: "light", reset: true, extra: ["-uiTestSession", env("SESSION"), "-uiTestOpenBooking", env("BOOKING")])
        waitFor("Yetib keldi", timeout: 25)
        snap("t6-01-arrived")
        let ack = byId("elchi.cash.acknowledge", timeout: 20)
        scrollTo(ack)
        snap("t6-02-cash-to-confirm")
        ack.tap()
        waitFor("Ikkala tomon tasdiqladi", timeout: 25)
        snap("t6-03-cash-confirmed")
        tapId("elchi.taxi.complete")
        waitFor("Manzilga yetib keldingizmi?")
        snap("t6-04-complete-confirm")
        tapId("elchi.taxi.completeConfirm")
        waitFor("Safar yakunlandi", timeout: 25)
        scrollTop()
        snap("t6-05-completed")
        // BOSQICH 04: the star card - a star opens the rating screen with it chosen.
        scrollTap("5 yulduz")
        waitFor("Bahoni yuborish", timeout: 15)
        waitFor("A'lo")
        snap("t6-06-rating")
        tap("Bahoni yuborish")
        waitFor("Baho", timeout: 20)
        snap("t6-07-rated")
    }

    // MARK: Client: seat count edit with an open offer (T7)

    func testT7_SeatEdit() {
        launch(theme: "light", reset: true, extra: ["-uiTestSession", env("SESSION"), "-uiTestOpenListing", env("LISTING2")])
        waitFor("2 kishi", timeout: 20)
        snap("t7-01-listing")
        scrollTap("Tahrirlash")
        typeInto("Odamlar soni", "3")
        waitFor("Ochiq takliflar: 1 ta", timeout: 15)
        snap("t7-02-edit-warning")
        tap("Tushundim, saqlash")
        waitFor("3 kishi", timeout: 25)
        snap("t7-03-saved")
    }

    // MARK: Driver: Keldim, then (after the wait) "Mijoz kelmadi" (T8a / T8b), the client's note (T8c)

    func testT8a_DriverArrive() {
        launch(theme: "light", reset: true, extra: ["-uiTestSession", env("SESSION"), "-uiTestDriverBooking", env("BOOKING3")])
        waitFor("Olib ketish kutilmoqda", timeout: 25)
        arriveIfOffered()
        let noShow = byId("elchi.driver.taxi.noShow")
        scrollTo(noShow)
        XCTAssertFalse(noShow.isEnabled, "no-show must wait")
        snap("t8-01-noshow-locked")
    }

    func testT8b_DriverNoShow() {
        launch(theme: "light", reset: true, extra: ["-uiTestSession", env("SESSION"), "-uiTestDriverBooking", env("BOOKING3")])
        waitFor("Olib ketish kutilmoqda", timeout: 25)
        let noShow = byId("elchi.driver.taxi.noShow", timeout: 20)
        scrollTo(noShow)
        waitEnabled(noShow, "Mijoz kelmadi", timeout: 120)
        snap("t8-02-noshow-open")
        noShow.tap()
        waitFor("Mijoz bilan qanday bog'lanishga urindingiz?")
        app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "Telefon orqali")).firstMatch.tap()
        snap("t8-03-noshow-sheet")
        tapId("elchi.noShow.send")
        waitFor("operator ko'rib chiqishini kutmoqda", timeout: 25)
        snap("t8-04-noshow-pending")
    }

    func testT8c_ClientNoShowNote() {
        launch(theme: "light", reset: true, extra: ["-uiTestSession", env("SESSION"), "-uiTestOpenBooking", env("BOOKING3")])
        waitFor("kelmadi", timeout: 25)
        snap("t8-05-client-noshow-note")
    }

    // MARK: Tours: dark and Russian (the session of the account the shell left signed in)

    /// Client screens in `THEME` / `LOCALE`: the seat picker, then the passenger booking.
    func testTourClient() {
        let theme = envOr("THEME", "light"), locale = envOr("LOCALE", "uz")
        let prefix = "tour-\(locale)-\(theme)"
        launch(locale: locale, theme: theme, reset: true, extra: ["-uiTestWindowFromNow", "5"])
        if locale == "ru" {
            signInAsClient(phone: env("CLIENT"), start: "Начать", next: "Далее", client: "Я клиент", getCode: "Получить код",
                           home: "Перейти к оформлению")
        } else {
            signInAsClient(phone: env("CLIENT"))
        }
        taxiRouteStep(prefix: prefix, locale: locale)
        app.terminate()
        launch(locale: locale, theme: theme, reset: false, extra: ["-uiTestOpenBooking", env("BOOKING")])
        let driverCard = byId("elchi.booking.driverCard", timeout: 25)
        scrollTo(driverCard)
        snap("\(prefix)-04-booking-driver")
        scrollTop()
        snap("\(prefix)-05-booking-top")
    }

    /// The route step with the price being typed in `LOCALE`: the seat names under the seats, the "Jami" card kept
    /// above the number pad (refocusing from the top scrolls it back into view), the keyboard's close button.
    func testPolishRouteKeyboard() {
        let locale = envOr("LOCALE", "uz"), ru = locale == "ru"
        let prefix = "polish-\(locale)"
        launch(locale: locale, theme: "light", reset: true, extra: ["-uiTestWindowFromNow", "5"])
        if ru {
            signInAsClient(phone: env("CLIENT"), start: "Начать", next: "Далее", client: "Я клиент", getCode: "Получить код",
                           home: "Перейти к оформлению")
        } else {
            signInAsClient(phone: env("CLIENT"))
        }
        taxiRouteStep(prefix: prefix, locale: locale)
        let done = byId("elchi.keyboard.done")
        done.tap()
        scrollTop()
        Thread.sleep(forTimeInterval: 1)
        snap("\(prefix)-04-seats-top")
        let price = field(ru ? "Цена за одного человека (сум)" : "Bir kishi uchun narx (so'm)")
        price.tap()
        Thread.sleep(forTimeInterval: 1.5)
        let total = byId("elchi.taxi.total")
        XCTAssertTrue(app.keyboards.firstMatch.exists, "no keyboard")
        XCTAssertLessThanOrEqual(total.frame.maxY, app.keyboards.firstMatch.frame.minY, "total under the keyboard")
        XCTAssertTrue(byId("elchi.keyboard.done").exists)
        snap("\(prefix)-05-price-focused")
        byId("elchi.keyboard.done").tap()
        Thread.sleep(forTimeInterval: 1)
        XCTAssertFalse(app.keyboards.firstMatch.exists, "keyboard still up")
        snap("\(prefix)-06-keyboard-closed")
    }

    /// Driver screens in `THEME` / `LOCALE`: the feed in Taksi mode and the passenger booking.
    func testTourDriver() {
        let theme = envOr("THEME", "light"), locale = envOr("LOCALE", "uz")
        let prefix = "tour-\(locale)-\(theme)-driver"
        launch(locale: locale, theme: theme, reset: true, extra: ["-uiTestSession", env("SESSION"), "-uiTestDriverBooking", env("BOOKING")])
        let board = byId("elchi.driver.taxi.board", timeout: 25)
        snap("\(prefix)-01-booking")
        scrollTo(board)
        snap("\(prefix)-02-board-action")
    }
}
