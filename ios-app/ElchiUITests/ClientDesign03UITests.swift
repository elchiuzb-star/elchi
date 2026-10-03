import XCTest

/// BOSQICH 03 ("Elchi Takliflar") on the running development backend, in phases a shell script drives
/// (`elchi-dev/ios-design03/run.sh`). The client signs in with `-uiTestSession` (no OTP); `LOCALE` / `THEME` pick the
/// language and palette, `LISTING` the listing a phase works on, `SHOTS` the folder the PNGs go to.
///
/// - `testA_PostParcel`: home -> a parcel request (the drivers answer it from the shell).
/// - `testB_Tour`: orders (bell, meta line), the detail (map, tracker, facts, offers inline), sorts, the edit warning,
///   share (system sheet, then revoke), notifications from the bell. Read-only apart from the share link.
/// - `testC_CounterReject`: tap-to-validate, a counter to the cheapest offer, a reject of the other.
/// - `testD_Countered`: the driver's answer to the counter ("Qarshi taklif", "(sizniki …)", "Qabul qilish"), Takliflarim.
/// - `testE_Accept`: accept -> the booking's chat (Q100), back to the booking and the orders.
/// - `testF_Taxi`: a passenger request's detail (people, per-seat price), the counter per seat, then accept.
final class ClientDesign03UITests: ClientUITestCase {
    private var env: [String: String] { ProcessInfo.processInfo.environment }
    private var ru: Bool { env["LOCALE"] == "ru" }
    private func L(_ uz: String, _ ru: String) -> String { self.ru ? ru : uz }

    private func start(openListing: Bool = false) {
        var extra = ["-uiTestSession", env["SESSION"] ?? ""]
        if openListing, let listing = env["LISTING"], !listing.isEmpty { extra += ["-uiTestOpenListing", listing] }
        launch(locale: env["LOCALE"] ?? "uz", theme: env["THEME"] ?? "light", reset: true, extra: extra)
    }

    private func scrollTap(_ label: String, maxSwipes: Int = 8) {
        let element = button(label)
        var swipes = 0
        while !element.isHittable && swipes < maxSwipes {
            app.swipeUp()
            swipes += 1
        }
        waitEnabled(element, label)
        element.tap()
    }

    private func scrollTo(_ text: String, maxSwipes: Int = 8) {
        let element = waitFor(text)
        var swipes = 0
        while !element.isHittable && swipes < maxSwipes {
            app.swipeUp()
            swipes += 1
        }
    }

    private func openDrawerRow(_ row: String) {
        let menu = app.buttons[L("Menyu", "Меню")].firstMatch
        XCTAssertTrue(menu.waitForExistence(timeout: 20), "no menu button")
        menu.tap()
        waitFor("ELCHI")
        tap(row)
    }

    private func openOrders() {
        openDrawerRow(L("Buyurtmalar", "Заказы"))
        waitFor(L("E'lonlarim", "Мои объявления"), timeout: 20)
    }

    private func closeShareSheet() {
        let close = app.otherElements["ActivityListView"].buttons["Close"].firstMatch
        if close.waitForExistence(timeout: 5) { close.tap() } else { app.swipeDown(velocity: .fast) }
    }

    func testA_PostParcel() {
        start()
        waitFor("Qayerdan?", timeout: 20)
        postParcelRequest(price: "150000")
        snap("d3-00-published")
    }

    func testB_Tour() {
        start()
        openOrders()
        waitFor(L("ta taklif", "Предложений"), timeout: 20)
        snap("d3-01-orders")
        if env["DRAWER"] == "1" {
            let menu = app.buttons[L("Menyu", "Меню")].firstMatch
            menu.tap()
            waitFor(L("Narx kelishuvlari", "Согласование цены"))
            snap("d3-02-drawer")
            app.coordinate(withNormalizedOffset: CGVector(dx: 0.95, dy: 0.5)).tap()
        }
        let card = app.buttons.containing(NSPredicate(format: "label CONTAINS %@ AND label CONTAINS %@", "→", L("E'lon qilingan", "Опубликовано"))).firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 20))
        card.tap()
        waitFor(L("Holat", "Статус"))
        waitFor(L("ta ochiq taklif", "Открытых предложений"), timeout: 20)
        Thread.sleep(forTimeInterval: 2)
        snap("d3-03-detail-top")
        app.swipeUp()
        snap("d3-04-detail-offers")
        app.swipeUp()
        snap("d3-05-detail-offers-bottom")
        app.swipeDown()
        app.swipeDown()
        scrollTap(L("Eng tez", "Сначала ранние"))
        app.swipeUp()
        snap("d3-06-sort-fastest")
        tap(L("Yaxshi baholangan", "С лучшими оценками"))
        snap("d3-07-sort-rated")
        tap(L("Eng arzon", "Сначала дешёвые"))

        // The edit warning (window moved with open offers) - not saved.
        app.swipeDown()
        app.swipeDown()
        tap(L("Tahrirlash", "Изменить"))
        waitFor(L("E'lonni tahrirlash", "Изменение объявления"))
        tap(L("Jo'nash oynasi tugashi", "Конец окна отправления"))
        waitFor(L("Tasdiqlash", "Подтвердить"))
        let wheels = app.pickerWheels
        if !wheels.firstMatch.exists {
            let time = app.buttons.matching(NSPredicate(format: "label MATCHES %@", "^[0-9]{1,2}:[0-9]{2}$")).firstMatch
            if time.waitForExistence(timeout: 5) { time.tap() }
        }
        if wheels.firstMatch.waitForExistence(timeout: 5) {
            wheels.element(boundBy: 0).adjust(toPickerWheelValue: "20")
            app.otherElements.firstMatch.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.1)).tap()
        }
        tap(L("Tasdiqlash", "Подтвердить"))
        waitFor(L("ochiq taklif yopiladi", "будут закрыты"))
        snap("d3-08-edit-warning")
        // Tap-to-validate: an empty price.
        replace(L("Narx (so'm)", "Цена (сум)"), with: "")
        tap(L("Tushundim, saqlash", "Понятно, сохранить"))
        waitFor(L("Narxni kiriting.", "Укажите цену."))
        snap("d3-09-edit-error")
        tap(L("Orqaga", "Назад"))

        // Share: the bar icon -> the system sheet with the server's text; the link stays revocable here.
        tap(L("Ulashish", "Поделиться"))
        let sheet = app.otherElements["ActivityListView"].firstMatch
        XCTAssertTrue(sheet.waitForExistence(timeout: 20), "no share sheet")
        Thread.sleep(forTimeInterval: 1)
        snap("d3-10-share-sheet")
        closeShareSheet()
        scrollTo(L("Havolani bekor qilish", "Отозвать ссылку"))
        snap("d3-11-share-row")
        scrollTap(L("Havolani bekor qilish", "Отозвать ссылку"))
        waitFor(L("Havola bekor qilindi", "Ссылка отозвана"), timeout: 20)

        // Notifications from the orders bell (pushed, with a back button).
        tap(L("Orqaga", "Назад"))
        tap(L("Bildirishnomalar", "Уведомления"))
        waitFor(L("Bildirishnomalar", "Уведомления"))
        Thread.sleep(forTimeInterval: 2)
        snap("d3-12-notifications")
        tap(L("Orqaga", "Назад"))
        waitFor(L("E'lonlarim", "Мои объявления"))
    }

    func testC_CounterReject() {
        start(openListing: true)
        waitFor("Holat", timeout: 20)
        waitFor("ta ochiq taklif", timeout: 20)
        scrollTap("Boshqa narx")
        waitFor("Sizning narxingiz (so'm)")
        // The driver's own price is refused on tap.
        tap("Yuborish")
        waitFor("Haydovchi narxidan farqli narx kiriting.")
        snap("d3-20-counter-same")
        replace("Sizning narxingiz (so'm)", with: env["COUNTER"] ?? "135000")
        snap("d3-21-counter-typed")
        tap("Yuborish")
        waitFor("javob kutilmoqda", timeout: 20)
        snap("d3-22-counter-waiting")
        scrollTap("Rad etish")
        waitFor("taklifi rad etildi", timeout: 20)
        snap("d3-23-rejected")
        app.swipeUp()
        snap("d3-24-rejected-bottom")
    }

    func testD_Countered() {
        start(openListing: true)
        waitFor(L("Holat", "Статус"), timeout: 20)
        scrollTo(L("Qabul qilish", "Принять"))
        Thread.sleep(forTimeInterval: 1)
        snap("d3-30-driver-countered")
        tap(L("Orqaga", "Назад"))
        openDrawerRow(L("Takliflarim", "Мои предложения"))
        waitFor(L("Takliflarim", "Мои предложения"))
        Thread.sleep(forTimeInterval: 2)
        snap("d3-31-proposals")
    }

    func testE_Accept() {
        start(openListing: true)
        waitFor("Holat", timeout: 20)
        scrollTap(env["PRIMARY"] ?? "Qabul qilish")
        waitFor("ni tanlaysizmi?")
        snap("d3-40-accept-dialog")
        tap("Ha, tanlayman")
        // Q100: straight into the booking's chat; back is the booking, back again the orders.
        waitFor("Xabar yo'q", timeout: 30)
        snap("d3-41-chat")
        tap("Orqaga")
        waitFor("Haydovchi va avtomobil", timeout: 20)
        tap("Orqaga")
        waitFor("Bronlar", timeout: 20)
        snap("d3-42-orders-after-accept")
        let fulfilled = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "Bron qilindi")).firstMatch
        if fulfilled.waitForExistence(timeout: 10) {
            fulfilled.tap()
            waitFor("Haydovchi tanlandi — bron yaratildi.")
            snap("d3-43-detail-fulfilled")
        }
    }

    func testF_Taxi() {
        start(openListing: true)
        waitFor(L("Yo'lovchilar", "Пассажиры"), timeout: 20)
        Thread.sleep(forTimeInterval: 2)
        snap("d3-50-taxi-detail")
        app.swipeUp()
        snap("d3-51-taxi-offers")
        if env["TAXI_COUNTER"] == "1" {
            scrollTap(L("Boshqa narx", "Другая цена"))
            waitFor(L("Bir o'rin narxi", "Цена за место"), timeout: 10)
            snap("d3-52-taxi-counter")
            tap(L("Bekor qilish", "Отмена"))
        }
        if env["TAXI_ACCEPT"] == "1" {
            scrollTap(L("Tanlash", "Выбрать"))
            waitFor(L("ni tanlaysizmi?", "Выбрать водителя"))
            snap("d3-53-taxi-accept")
            tap(L("Ha, tanlayman", "Да, выбираю"))
            let back = app.buttons[L("Orqaga", "Назад")].firstMatch
            XCTAssertTrue(back.waitForExistence(timeout: 25))
            snap("d3-54-taxi-chat")
        }
    }
}
