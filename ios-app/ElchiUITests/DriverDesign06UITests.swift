import XCTest

/// DESIGN06 (driver registration) screenshots against the development backend, in phases a shell script drives
/// (moving the driver's state with `driver_ops.py` between them). Phones come from `TEST_RUNNER_D06_*` (throwaway
/// `+99890000 36xx` numbers) and `TEST_RUNNER_D06_APPROVED` (a demo driver, only looked at, never changed).
///
/// a1 (A, new) home "To'ldirilmagan" + checklist, the gates, Orders open, the profile, the form's errors, the lock
///    dialog, the locked save back on home, the locked form, the documents; a2 (A) all five sent -> "Ko'rib chiqilmoqda";
/// b (A, after `doc` edits) approved row without re-upload, rejected row; c (A) dark; d (A) Russian;
/// e (A, rejected) home / docs / gate in light, dark, Russian; f (approved demo) home / orders / profile;
/// g (B, new, dark) and h (C, new, Russian) the first form and the lock dialog.
final class DriverDesign06UITests: ClientUITestCase {
    private func phone(_ name: String) -> String {
        let phone = ProcessInfo.processInfo.environment[name] ?? ""
        XCTAssertEqual(phone.count, 9, "\(name) not passed (TEST_RUNNER_\(name))")
        return phone
    }

    private func signIn(_ phone: String, ru: Bool = false) {
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
        let item = app.buttons["elchi.tab.\(name)"]
        XCTAssertTrue(item.waitForExistence(timeout: 15), "no tab \(name)")
        item.tap()
    }

    private func back(_ ru: Bool = false) { tap(ru ? "Назад" : "Orqaga") }

    private func byId(_ id: String, timeout: TimeInterval = 15) -> XCUIElement {
        let element = app.descendants(matching: .any)[id].firstMatch
        XCTAssertTrue(element.waitForExistence(timeout: timeout), "no element '\(id)'")
        return element
    }

    private func scrollTo(_ element: XCUIElement, maxSwipes: Int = 8) {
        var swipes = 0
        while !(element.exists && element.isHittable) && swipes < maxSwipes {
            app.swipeUp()
            swipes += 1
        }
    }

    private func upload(_ type: String, done: String, ru: Bool = false) {
        let row = byId("elchi.driver.docs.\(type)")
        scrollTo(row)
        waitEnabled(row, type, timeout: 30)
        row.tap()
        tap(ru ? "Выбрать из галереи" : "Galereyadan tanlash")
        waitFor(done, timeout: 30)
    }

    private func fill(plate: String, name: String, ru: Bool = false) {
        type(name, into: ru ? "Имя и фамилия" : "Ism familiya")
        type("Cobalt", into: ru ? "Модель автомобиля" : "Avtomobil modeli")
        type(ru ? "Белый" : "Oq", into: ru ? "Цвет автомобиля" : "Avtomobil rangi")
        type(plate, into: ru ? "Госномер" : "Davlat raqami")
        type("4", into: ru ? "Пассажирские места" : "Yo'lovchi o'rinlari")
        type("0", into: ru ? "Место для груза (кг)" : "Yuk uchun joy (kg)")
        type("100", into: ru ? "Объём груза (л)" : "Yuk hajmi (litr)")
    }

    private func save() { byId("elchi.driver.form.save").tap() }

    // MARK: A - the new driver, light, Uzbek

    func test_a1_NewDriver() {
        launch(theme: "light")
        signIn(phone("D06_A"))
        waitFor("To'ldirilmagan", timeout: 20)
        waitFor("Profil va avtomobil")
        snap("a01-home-incomplete")
        tab("routes")
        waitFor("Tasdiqlanmaguncha buyurtma qabul qila olmaysiz")
        snap("a02-gate-routes")
        tab("matches")
        waitFor("Holat: To'ldirilmagan")
        snap("a03-gate-matches-incomplete")
        tab("orders")
        waitFor("Mijoz taklifingizni qabul qilgach", timeout: 20)
        snap("a04-orders-open-empty")
        tab("profile")
        waitFor("Ism va avtomobil ma'lumotlarini kiriting", timeout: 20)
        snap("a05-profile-tab")
        tab("home")
        byId("elchi.driver.checklist.1").tap()
        waitFor("saqlangach qulflanadi")
        snap("a06-form-first")
        save()
        waitFor("Ism familiyani kiriting.")
        snap("a07-form-errors")
        app.swipeUp()
        snap("a07b-form-errors-bottom")
        app.swipeDown()
        let digits = phone("D06_A").suffix(4)
        fill(plate: "95 x \(digits) xa", name: "Jasur Toshmatov")
        save()
        waitFor("Avtomobil ma'lumotlari qulflanadi")
        snap("a08-lock-dialog")
        tap("Tekshirib chiqaman")
        waitGone("Ha, saqlash")
        save()
        tap("Ha, saqlash")
        waitFor("avtomobil ma'lumotlari qulflandi", timeout: 25)
        waitFor("Profilni ko'rish")
        snap("a09-home-after-lock")
        tap("Profilni ko'rish")
        waitFor("Avtomobil ma'lumotlari qulflangan", timeout: 20)
        snap("a10-form-locked")
        scrollTo(byId("elchi.driver.form.askOperator"))
        snap("a11-form-locked-bottom")
        back()
        tap("Hujjatlarni yuklash")
        waitFor("0 / 5 hujjat yuborilgan", timeout: 20)
        snap("a12-docs-empty")
        upload("passport", done: "Pasport ko'rib chiqishga yuborildi")
        upload("selfie", done: "Selfi ko'rib chiqishga yuborildi")
        app.swipeDown()
        snap("a13-docs-two")
        back()
        waitFor("2 / 5 yuklangan", timeout: 20)
        snap("a14-home-two-docs")
    }

    func test_a2_AllSent() {
        launch(theme: "light", reset: false, extra: ["-uiTestDriverScreen", "documents"])
        waitFor("2 / 5 hujjat yuborilgan", timeout: 20)
        upload("license", done: "Haydovchilik guvohnomasi ko'rib chiqishga yuborildi")
        upload("car_document", done: "Avtomobil hujjati ko'rib chiqishga yuborildi")
        upload("car_photo", done: "Avtomobil rasmi ko'rib chiqishga yuborildi")
        app.swipeDown()
        waitFor("5 / 5 hujjat yuborilgan")
        snap("a15-docs-all-pending")
        back()
        waitFor("Ko'rib chiqilmoqda", timeout: 20)
        waitFor("Operator hujjatlaringizni tekshirmoqda.")
        snap("a16-home-review")
        tab("matches")
        waitFor("Holat: Ko'rib chiqilmoqda")
        snap("a17-gate-review")
    }

    // MARK: B - one approved, one rejected document

    func test_b_MixedDocuments() {
        launch(theme: "light", reset: false, extra: ["-uiTestDriverScreen", "documents"])
        waitFor("Sabab:", timeout: 20)
        snap("b01-docs-approved-and-rejected")
        app.swipeUp()
        snap("b02-docs-mixed-bottom")
        back()
        waitFor("1 ta hujjat rad etildi", timeout: 20)
        snap("b03-home-doc-rejected")
    }

    // MARK: C / D - the same driver in dark and in Russian

    func test_c_Dark() {
        launch(theme: "dark", reset: false)
        waitFor("To'ldirilmagan", timeout: 20)
        snap("c01-home-dark")
        tap("Profilni ko'rish")
        waitFor("Avtomobil ma'lumotlari qulflangan", timeout: 20)
        snap("c02-form-locked-dark")
        back()
        tap("Hujjatlarni yuklash")
        waitFor("Sabab:", timeout: 20)
        snap("c03-docs-dark")
        back()
        tab("matches")
        waitFor("Holat: To'ldirilmagan")
        snap("c04-gate-dark")
        tab("orders")
        waitFor("Mijoz taklifingizni qabul qilgach", timeout: 20)
        snap("c05-orders-dark")
    }

    func test_d_Russian() {
        launch(locale: "ru", theme: "light", reset: false)
        waitFor("Не заполнено", timeout: 20)
        snap("d01-home-ru")
        tap("Открыть профиль")
        waitFor("Данные автомобиля заблокированы", timeout: 20)
        snap("d02-form-locked-ru")
        back(true)
        tap("Загрузить документы")
        waitFor("Отправлено документов: 5 / 5", timeout: 20)
        snap("d03-docs-ru")
        back(true)
        tab("matches")
        waitFor("Не заполнено")
        snap("d04-gate-ru")
        tab("orders")
        waitFor("Когда клиент примет ваше предложение", timeout: 20)
        snap("d05-orders-ru")
        tab("profile")
        waitFor("Профиль и автомобиль", timeout: 20)
        snap("d06-profile-ru")
    }

    // MARK: E - rejected account

    func test_e_Rejected() {
        launch(theme: "light", reset: false)
        waitFor("Rad etilgan", timeout: 20)
        snap("e01-home-rejected")
        tap("Hujjatlarni yuklash")
        waitFor("5 / 5 hujjat yuborilgan", timeout: 20)
        XCTAssertFalse(app.buttons["elchi.driver.docs.passport"].exists, "no uploads once rejected")
        snap("e02-docs-rejected-no-upload")
        back()
        tab("matches")
        waitFor("Holat: Rad etilgan")
        snap("e03-gate-rejected")

        launch(theme: "dark", reset: false)
        waitFor("Rad etilgan", timeout: 20)
        snap("e04-home-rejected-dark")

        launch(locale: "ru", theme: "light", reset: false)
        waitFor("Отклонено", timeout: 20)
        snap("e05-home-rejected-ru")
        tap("Загрузить документы")
        waitFor("Отправлено документов: 5 / 5", timeout: 20)
        snap("e06-docs-rejected-ru")
    }

    // MARK: F - approved (demo driver, read-only)

    func test_f_Approved() {
        launch(theme: "light")
        signIn(phone("D06_APPROVED"))
        waitFor("Tasdiqlangan", timeout: 20)
        snap("f01-home-approved")
        tab("orders")
        waitFor("Takliflarim", timeout: 20)
        snap("f02-orders-approved")
        tab("profile")
        waitFor("Ism; avtomobil qulflangan", timeout: 20)
        snap("f03-profile-approved")
        byId("elchi.driver.menu.documents").tap()
        waitFor("hujjat yuborilgan", timeout: 20)
        snap("f04-docs-approved-no-reupload")
        back()
        byId("elchi.driver.menu.form").tap()
        waitFor("Avtomobil ma'lumotlari qulflangan", timeout: 20)
        snap("f05-form-approved")

        launch(theme: "dark", reset: false)
        waitFor("Tasdiqlangan", timeout: 20)
        snap("f06-home-approved-dark")

        launch(locale: "ru", theme: "light", reset: false)
        waitFor("Подтверждено", timeout: 20)
        snap("f07-home-approved-ru")
    }

    // MARK: G / H - first form and the lock dialog in dark and in Russian

    func test_g_NewDark() {
        launch(theme: "dark")
        signIn(phone("D06_B"))
        waitFor("To'ldirilmagan", timeout: 20)
        snap("g01-home-incomplete-dark")
        tap("Profilni to'ldirish")
        save()
        waitFor("Ism familiyani kiriting.")
        snap("g02-form-errors-dark")
        let digits = phone("D06_B").suffix(4)
        fill(plate: "95 x \(digits) xb", name: "Bobur Aliyev")
        save()
        waitFor("Avtomobil ma'lumotlari qulflanadi")
        snap("g03-lock-dialog-dark")
        tap("Ha, saqlash")
        waitFor("Profilni ko'rish", timeout: 25)
        snap("g04-home-after-lock-dark")
        tab("matches")
        snap("g05-gate-dark-locked-tabs")
    }

    func test_h_NewRussian() {
        launch(locale: "ru", theme: "light")
        signIn(phone("D06_C"), ru: true)
        waitFor("Не заполнено", timeout: 20)
        snap("h01-home-incomplete-ru")
        tap("Заполнить профиль")
        save()
        waitFor("Введите имя и фамилию.")
        snap("h02-form-errors-ru")
        app.swipeUp()
        snap("h02b-form-errors-bottom-ru")
        app.swipeDown()
        let digits = phone("D06_C").suffix(4)
        fill(plate: "95 x \(digits) xc", name: "Rustam Karimov", ru: true)
        save()
        waitFor("Данные автомобиля будут заблокированы")
        snap("h03-lock-dialog-ru")
        tap("Да, сохранить")
        waitFor("Открыть профиль", timeout: 25)
        snap("h04-home-after-lock-ru")
    }
}
