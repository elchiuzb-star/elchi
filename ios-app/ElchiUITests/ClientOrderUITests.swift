import XCTest

/// BOSQICH 02 design ("Elchi Buyurtma Yaratish") end to end against the running development backend, in phases the
/// shell drives (`elchi-dev/ios-design02/run.sh`): `test00_SignIn` signs the client in once (dev OTP); the other
/// phases reuse that session in `LOCALE` / `THEME` and write their screenshots to `SHOTS` as PNGs.
/// Pochta: home -> route (1/3) -> contact (2/3) -> review (3/3) -> edit from the review -> published -> "Yangi buyurtma".
/// Taksi: home with its block -> review -> edit back on the home -> published. Locate: the button fills "Qayerdan".
/// `-uiTestFakePhoto` swaps the system photo picker for a generated photo; the upload itself is real.
final class ClientOrderUITests: ClientUITestCase {
    private var locale: String { ProcessInfo.processInfo.environment["LOCALE"].flatMap { $0.isEmpty ? nil : $0 } ?? "uz" }
    private var theme: String { ProcessInfo.processInfo.environment["THEME"].flatMap { $0.isEmpty ? nil : $0 } ?? "light" }
    private var ru: Bool { locale == "ru" }
    private var prefix: String { "\(locale)-\(theme)" }
    private var publish: Bool { ProcessInfo.processInfo.environment["PUBLISH"] != "0" }

    private func L(_ uz: String, _ ruText: String) -> String { ru ? ruText : uz }

    private func shot(_ name: String) { snap("\(prefix)-\(name)") }

    private func openHome() {
        launch(locale: locale, theme: theme, reset: false)
        XCTAssertTrue(element("elchi.home.go", timeout: 30).exists, "not on the client home (run test00_SignIn first)")
        waitMapDrawn()
    }

    private func tapId(_ id: String) {
        let target = element(id)
        if !target.isEnabled, let folder = ProcessInfo.processInfo.environment["SHOTS"] {
            try? app.debugDescription.write(toFile: folder + "/_tree-\(id).txt", atomically: true, encoding: .utf8)
        }
        waitEnabled(target, id)
        target.tap()
    }

    private func dismissKeyboard() {
        let done = app.descendants(matching: .any)["elchi.keyboard.done"].firstMatch
        if done.waitForExistence(timeout: 2) { done.tap() }
    }

    /// Region -> (district) -> point with a small nudge (a new point: the server refuses an identical open request).
    private func pick(_ question: String, region: String, district: String?, shots: Bool = false) {
        tap(question)
        waitFor(L("Avval hududni tanlang", "Сначала выберите регион"))
        if shots { shot("10-regions") }
        tap(region)
        if let district {
            waitFor(L("Tumanni tanlang", "Выберите район"))
            if shots { shot("11-districts") }
            app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", district)).firstMatch.tap()
        }
        waitFor(L("Tanlangan joy", "Выбранное место"))
        let choose = button(L("Shu joyni tanlash", "Выбрать это место"))
        waitEnabled(choose, "choose")
        let from = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.42))
        from.press(forDuration: 0.1, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.5 + .random(in: -0.06...0.06),
                                                                                                 dy: 0.42 + .random(in: -0.04...0.04))))
        Thread.sleep(forTimeInterval: 1.5)
        waitEnabled(choose, "choose")
        if shots {
            waitMapDrawn()
            shot("12-point")
        }
        choose.tap()
    }

    private func manualContact(card: String, name: String, phone: String) {
        tapId(card)
        tapId("elchi.contact.new")
        let nameField = element("elchi.contact.manualName")
        nameField.tap()
        for ch in name { nameField.typeText(String(ch)) }
        let phoneField = element("elchi.contact.manualPhone")
        phoneField.tap()
        for ch in phone { phoneField.typeText(String(ch)) }
        tapId("elchi.contact.manualPick")
        waitGone(L("+ Yangi raqam", "+ Новый номер"))
    }

    // MARK: Phases

    func test00_SignIn() {
        launch(locale: "uz", theme: "light", reset: true)
        signInAsClient(phone: Self.runPhone)
    }

    func test01_Parcel() {
        openHome()
        shot("01-home-empty")
        // Grey but tappable: says what to choose first.
        tapId("elchi.home.go")
        waitFor(L("Avval qayerdan va qayerga", "Сначала выберите, откуда и куда"))
        shot("02-home-toast")
        pick(L("Qayerdan?", "Откуда?"), region: "Toshkent shahri", district: nil, shots: true)
        waitFor(L("Olib ketish joyi tanlandi", "Место забора выбрано"))
        pick(L("Qayerga?", "Куда?"), region: "Samarqand viloyati", district: "Samarqand")
        waitFor(L("Taxminiy yo'l vaqti", "Примерное время в пути"), timeout: 25)
        waitMapDrawn()
        shot("03-home-ready")
        tapId("elchi.home.go")

        // Route (1/3): the prefilled window, no price -> the red list at the top.
        waitFor(L("Jo'nash oynasi", "Окно отправления"))
        XCTAssertEqual(element("elchi.step").label, "1 / 3")
        tapId("elchi.route.save")
        waitFor(L("Narxni kiriting", "Укажите цену"))
        shot("20-route-errors")
        tapId("elchi.window.end")
        waitFor(L("Kun oxirigacha", "До конца дня"))
        shot("21-window-sheet")
        tap(L("+8 soat", "+8 ч"))
        tapId("elchi.window.done")
        let price = element("elchi.price")
        price.tap()
        for ch in "120000" { price.typeText(String(ch)) }
        dismissKeyboard()
        tapId("elchi.price.inc")
        waitFor("125")
        shot("22-route-filled")
        tapId("elchi.route.save")

        // Contact (2/3): an empty receiver, type, size and photo -> the list; then fill everything.
        waitFor(L("Jo'natma ma'lumotlari", "Данные отправления"))
        XCTAssertEqual(element("elchi.step").label, "2 / 3")
        shot("30-contact-empty")
        tapId("elchi.contact.continue")
        waitFor(L("Qabul qiluvchi ismini kiriting", "Введите имя получателя"))
        shot("31-contact-errors")
        if app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", L("Kontaktdan tanlang", "Выберите из контактов"))).count > 1 {
            manualContact(card: "elchi.contact.sender", name: "Aziza Karimova", phone: "901234567")
        }
        tapId("elchi.contact.receiver")
        waitFor(L("Qabul qiluvchini tanlang", "Выберите получателя"))
        tapId("elchi.contact.new")
        shot("32-contact-sheet")
        let nameField = element("elchi.contact.manualName")
        nameField.tap()
        for ch in "Dilnoza Rahimova" { nameField.typeText(String(ch)) }
        let phoneField = element("elchi.contact.manualPhone")
        phoneField.tap()
        for ch in "915552211" { phoneField.typeText(String(ch)) }
        tapId("elchi.contact.manualPick")
        waitFor(L("Qabul qiluvchi: Dilnoza", "Получатель: Dilnoza"))
        tapId("elchi.parcel.type")
        Thread.sleep(forTimeInterval: 1)
        shot("33-type-sheet")
        tapId("elchi.option.box")
        tapId("elchi.parcel.size")
        let firstSize = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'elchi.option.'")).element(boundBy: 0)
        XCTAssertTrue(firstSize.waitForExistence(timeout: 15), "no size options")
        Thread.sleep(forTimeInterval: 1)
        shot("34-size-sheet")
        firstSize.tap()
        tapId("elchi.photo.add")
        tap(L("Galereyadan tanlash", "Выбрать из галереи"))
        waitFor(L("Rasm tayyor", "Фото готово"), timeout: 25)
        type("Qo'ng'iroq: 901234567", into: L("Izoh (ixtiyoriy)", "Комментарий (необязательно)"))
        dismissKeyboard()
        XCTAssertTrue(element("elchi.note.masked").exists)
        shot("35-contact-filled")
        tapId("elchi.parcel.banLink")
        waitFor(L("Tushunarli", "Понятно"))
        Thread.sleep(forTimeInterval: 1)
        shot("36-ban-sheet")
        tap(L("Tushunarli", "Понятно"))
        tapId("elchi.contact.continue")

        // Review (3/3), then an edit of the receiver: "Saqlash va qaytish" comes back here.
        waitFor(L("Buyurtmani tekshiring", "Проверьте заказ"))
        XCTAssertEqual(element("elchi.step").label, "3 / 3")
        shot("40-review")
        app.swipeUp()
        shot("41-review-bottom")
        let editReceiver = element("elchi.review.edit.orderForm.review.receiver")
        editReceiver.tap()
        waitFor(L("Saqlash va qaytish", "Сохранить и вернуться"))
        shot("42-edit-contact")
        tapId("elchi.contact.continue")
        waitFor(L("Buyurtmani tekshiring", "Проверьте заказ"))
        // "Tahrirlash" opens the route step in edit mode.
        tap(L("Tahrirlash", "Изменить"))
        waitFor(L("Saqlash va qaytish", "Сохранить и вернуться"))
        tapId("elchi.route.save")
        waitFor(L("Buyurtmani tekshiring", "Проверьте заказ"))
        guard publish else { return }
        tapId("elchi.review.publish")
        waitFor(L("Haydovchilardan takliflar kutilmoqda", "Ждём предложений от водителей"), timeout: 30)
        shot("50-success")
        tap(L("Yangi buyurtma", "Новый заказ"))
        XCTAssertTrue(element("elchi.home.go").waitForExistence(timeout: 10))
        shot("51-new-order-home")
    }

    func test02_Taxi() {
        openHome()
        let taxi = app.buttons[L("Taksi", "Такси")].firstMatch
        XCTAssertTrue(taxi.waitForExistence(timeout: 20), "no Taksi segment (passenger_enabled off?)")
        taxi.tap()
        shot("60-taxi-home-empty")
        pick(L("Qayerdan?", "Откуда?"), region: "Toshkent shahri", district: nil)
        pick(L("Qayerga?", "Куда?"), region: "Samarqand viloyati", district: "Samarqand")
        waitFor(L("Taxminiy yo'l vaqti", "Примерное время в пути"), timeout: 25)
        waitMapDrawn()
        shot("61-taxi-home-block")
        // Nothing chosen yet: "Davom etish" lists the people and the price.
        tapId("elchi.home.go")
        waitFor(L("Necha kishi ekanini tanlang", "Выберите, сколько человек"))
        shot("62-taxi-home-errors")
        tapId("elchi.window.start")
        waitFor(L("Suring", "Листайте"))
        shot("63-taxi-window-sheet")
        tapId("elchi.window.done")
        tapId("elchi.seats.2")
        let price = element("elchi.price")
        price.tap()
        for ch in "150000" { price.typeText(String(ch)) }
        dismissKeyboard()
        waitFor("300")
        shot("64-taxi-home-filled")
        tapId("elchi.home.go")
        waitFor(L("Buyurtmani tekshiring", "Проверьте заказ"))
        XCTAssertEqual(element("elchi.step").label, "1 / 1")
        shot("65-taxi-review")
        // The seats' pencil goes back to the home, which saves and returns.
        element("elchi.review.edit.client.taxi.seats").tap()
        waitFor(L("Saqlash va qaytish", "Сохранить и вернуться"))
        tapId("elchi.seats.4")
        shot("66-taxi-edit-home")
        tapId("elchi.home.go")
        waitFor(L("Butun salon (4 o'rin)", "Весь салон (4 места)"))
        shot("67-taxi-review-whole-cabin")
        guard publish else { return }
        tapId("elchi.review.publish")
        waitFor(L("Haydovchilardan takliflar kutilmoqda", "Ждём предложений от водителей"), timeout: 30)
        shot("68-taxi-success")
    }

    /// The shell granted location and set the simulator to Tashkent: the button centres and fills "Qayerdan".
    func test03_Locate() {
        openHome()
        let myLocation = element("elchi.map.myLocation", timeout: 45)
        myLocation.tap()
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let allow = springboard.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Allow While Using")).firstMatch
        if allow.waitForExistence(timeout: 4) { allow.tap() }
        waitFor(L("Joriy joylashuv", "Текущее местоположение"), timeout: 20)
        shot("70-locate-filled")
        waitGone(L("sifatida belgilandi", "указано как"), timeout: 10)
        Thread.sleep(forTimeInterval: 1)
        shot("71-locate-settled")
    }
}
