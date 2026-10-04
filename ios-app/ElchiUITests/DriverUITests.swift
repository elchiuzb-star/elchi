import XCTest

/// Stage 07 (driver shell, profile + vehicle locked once, documents, verification gate) against the running
/// development backend, in phases the shell drives (scratchpad `ios-s07/run_all.sh`), which moves the drivers'
/// states with `driver_ops.py` between them. Phones come from the shell (`TEST_RUNNER_*`): all `+99895…` throwaways.
///
/// 0. `test0_RoleMismatch` - a client's phone chooses "Men haydovchiman": ROLE_MISMATCH as a sentence.
/// 1. `test1_NewDriver` (A) - role screen -> sign-in -> unapproved home, the gate on each tab, the menu, the empty
///    documents, the first-time form -> saved -> locked (vehicle status card).
/// 2. `test2_Upload` (A) - all five uploaded (one as a PDF) -> all pending; home says "Ko'rib chiqilmoqda".
/// 3. `test3_Mixed` (A, after `doc` edits) - approved / pending / rejected with its reason; the rejected one re-sent.
/// 4. `test4_Approved` (A, after `approve`) - approved home, availability on then off, a tab's "next stage", the form.
/// 5. `test5_Rejected` (B, rejected) - home and the support-only gate -> Yordam; `test5b_Blocked` (C) - a blocked
///    driver's sign-in is refused; `test5c_V2Failure` (E) - v1 saved, the v2 vehicle refused, the vehicle-only retry.
/// 6. `test6_Menu` (A) - the profile menu, a reused Stage 05 screen, settings, the logout confirm.
/// 7. `test7_Dark` (A + D, a fresh driver) and `test8_Russian` (A + D) - the screens in the other theme and language;
///    D also tries a plate that is already taken.
final class DriverUITests: ClientUITestCase {
    // MARK: Phones

    private func phone(_ name: String) -> String {
        let phone = ProcessInfo.processInfo.environment[name] ?? ""
        XCTAssertEqual(phone.count, 9, "\(name) not passed (TEST_RUNNER_\(name))")
        return phone
    }

    // MARK: Helpers

    /// Splash -> onboarding -> role -> phone -> dev OTP -> the driver's tabs.
    private func signInAsDriver(_ phone: String, locale: String = "uz", shots: Bool = false) {
        let ru = locale == "ru"
        tap(ru ? "Начать" : "Boshlash")
        tap(ru ? "Далее" : "Keyingisi")
        tap(ru ? "Далее" : "Keyingisi")
        tap(ru ? "Начать" : "Boshlash")
        if shots {
            waitFor("Qanday davom etamiz?")
            snap("01-role")
        }
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

    private func back(_ locale: String = "uz") { tap(locale == "ru" ? "Назад" : "Orqaga") }

    private func scrollTo(_ element: XCUIElement, maxSwipes: Int = 8) {
        var swipes = 0
        while !(element.exists && element.isHittable) && swipes < maxSwipes {
            app.swipeUp()
            swipes += 1
        }
    }

    private func scrollTap(_ label: String) {
        let element = button(label)
        scrollTo(element)
        waitEnabled(element, label)
        element.tap()
    }

    private func byId(_ id: String, timeout: TimeInterval = 15) -> XCUIElement {
        let element = app.descendants(matching: .any)[id].firstMatch
        XCTAssertTrue(element.waitForExistence(timeout: timeout), "no element '\(id)'")
        return element
    }

    /// One document: its row's button -> the source -> "… ko'rib chiqishga yuborildi".
    private func upload(_ type: String, source: String = "Galereyadan tanlash", done: String) {
        let row = byId("elchi.driver.docs.\(type)")
        scrollTo(row)
        waitEnabled(row, type, timeout: 30)
        row.tap()
        tap(source)
        waitFor(done, timeout: 30)
    }

    /// A profile menu row: scrolled into view first (the list runs under the tab bar).
    private func menu(_ action: String) {
        let row = byId("elchi.driver.menu.\(action)")
        scrollTo(row)
        row.tap()
    }

    private func toggleAvailability() {
        let toggle = app.switches.firstMatch
        XCTAssertTrue(toggle.waitForExistence(timeout: 15))
        waitEnabled(toggle, "availability")
        toggle.coordinate(withNormalizedOffset: CGVector(dx: 0.93, dy: 0.5)).tap()
    }

    private func fillFirstTimeForm(plate: String, name: String = "Jasur Toshmatov") {
        type(name, into: "Ism familiya")
        type("Cobalt", into: "Avtomobil modeli")
        type("Oq", into: "Avtomobil rangi")
        type(plate, into: "Davlat raqami")
        type("4", into: "Yo'lovchi o'rinlari")
        type("20", into: "Yuk uchun joy (kg)")
        type("100", into: "Yuk hajmi (litr)")
    }

    // MARK: Phases

    func test0_RoleMismatch() {
        launch(theme: "light")
        tap("Boshlash")
        tap("Keyingisi")
        tap("Keyingisi")
        tap("Boshlash")
        waitFor("Qanday davom etamiz?")
        app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "Men haydovchiman")).firstMatch.tap()
        let phoneField = app.textFields.firstMatch
        XCTAssertTrue(phoneField.waitForExistence(timeout: 10))
        phoneField.tap()
        for digit in phone("CLIENT_PHONE") { phoneField.typeText(String(digit)) }
        tap("Kod olish")
        waitFor("Bu telefon raqam boshqa rolda ro'yxatdan o'tgan", timeout: 20)
        snap("02-role-mismatch")
    }

    func test1_NewDriver() {
        launch(theme: "light")
        signInAsDriver(phone("DRIVER_A"), shots: true)
        waitFor("Profilni to'ldiring")
        // DESIGN06 1.5 / 1.7: the derived word, not the server's "Yangi", and the three-step checklist.
        waitFor("To'ldirilmagan")
        waitFor("Profil va avtomobil")
        snap("03-home-new")
        XCTAssertTrue(app.switches.firstMatch.exists && !app.switches.firstMatch.isEnabled, "availability must be locked")

        tab("routes")
        waitFor("Tasdiqlanmaguncha buyurtma qabul qila olmaysiz")
        snap("04-gate-routes-new")
        tab("matches")
        waitFor("Mos buyurtmalar")
        snap("05-gate-matches-new")
        tab("orders")
        // DESIGN06 0.3 / D16: Buyurtmalar is never gated - the empty history with its hint.
        waitFor("Mijoz taklifingizni qabul qilgach", timeout: 20)
        snap("06-orders-open-new")
        tab("profile")
        waitFor("Hujjatlar")
        snap("07-profile-menu-new")

        tab("home")
        tap("Hujjatlarni yuklash")
        waitFor("0 / 5 hujjat yuborilgan")
        snap("08-docs-empty")
        back()

        tap("Profilni to'ldirish")
        waitFor("Haydovchi profili")
        waitFor("Avtomobil modeli")
        snap("09-form-first")
        let digits = phone("DRIVER_A").suffix(4)
        fillFirstTimeForm(plate: "95 a \(digits) ka")
        app.swipeUp()
        waitFor("saqlangach qulflanadi")
        snap("10-form-filled")
        tap("Saqlash")
        // Q94 / DESIGN06 2.2: the first save asks before locking; then back on home with the locked banner.
        waitFor("Avtomobil ma'lumotlari qulflanadi")
        snap("10b-lock-dialog")
        tap("Ha, saqlash")
        waitFor("avtomobil ma'lumotlari qulflandi", timeout: 25)
        tap("Profilni ko'rish")
        waitFor("Avtomobil ma'lumotlari qulflangan", timeout: 20)
        snap("11-form-locked")
        app.swipeUp()
        waitFor("Avtomobil holati")
        waitFor("Tekshiruvda")
        snap("12-form-locked-status")
    }

    func test2_Upload() {
        launch(theme: "light", reset: false, extra: ["-uiTestDriverScreen", "documents"])
        waitFor("0 / 5 hujjat yuborilgan", timeout: 20)
        upload("passport", source: "PDF fayl", done: "Pasport ko'rib chiqishga yuborildi")
        snap("13-docs-first-uploaded")
        upload("selfie", done: "Selfi ko'rib chiqishga yuborildi")
        upload("license", done: "Haydovchilik guvohnomasi ko'rib chiqishga yuborildi")
        upload("car_document", done: "Avtomobil hujjati ko'rib chiqishga yuborildi")
        upload("car_photo", done: "Avtomobil rasmi ko'rib chiqishga yuborildi")
        waitFor("5 / 5 hujjat yuborilgan")
        app.swipeDown()
        snap("14-docs-all-pending")
        back()
        waitFor("Ko'rib chiqilmoqda", timeout: 20)
        snap("15-home-pending")
        tab("matches")
        waitFor("Holat: Ko'rib chiqilmoqda")
        snap("16-gate-matches-pending")
    }

    func test3_Mixed() {
        launch(theme: "light", reset: false, extra: ["-uiTestDriverScreen", "documents"])
        waitFor("Sabab: rasm xira, matn o'qilmaydi", timeout: 20)
        snap("17-docs-mixed")
        app.swipeUp()
        snap("17b-docs-mixed-bottom")
        upload("license", done: "Haydovchilik guvohnomasi ko'rib chiqishga yuborildi")
        snap("18-docs-license-resent")
    }

    func test4_Approved() {
        launch(theme: "light", reset: false)
        waitFor("Bosh sahifa", timeout: 20)
        waitFor("Tasdiqlangan")
        snap("19-home-approved")
        toggleAvailability()
        waitFor("Faolman — buyurtma qabul qilishga tayyor", timeout: 20)
        snap("20-available-on")
        toggleAvailability()
        // DESIGN06 1.8 / 1.10: the off subtitle and its own toast.
        waitFor("Faol emasman — yangi buyurtmalar ko'rsatilmaydi", timeout: 20)
        waitFor("Faollik o'chirildi")
        snap("21-available-off")
        tap("Mos buyurtmalarni ko'rish")
        waitFor("Mos buyurtmalar")
        snap("22-matches-approved")
        tab("profile")
        byId("elchi.driver.menu.form").tap()
        waitFor("Avtomobil ma'lumotlari qulflangan", timeout: 20)
        snap("23-form-approved")
        app.swipeUp()
        snap("23b-form-approved-bottom")
    }

    func test5_Rejected() {
        launch(theme: "light")
        signInAsDriver(phone("DRIVER_B"))
        waitFor("Rad etilgan", timeout: 20)
        snap("24-home-rejected")
        tab("matches")
        waitFor("Hisobingiz bo'yicha qaror qabul qilingan")
        snap("25-gate-rejected")
        tap("Qo'llab-quvvatlashga yozish")
        waitFor("Murojaat yuborish")
        snap("26-support-from-gate")
    }

    /// A blocked driver cannot sign in at all (`USER_BLOCKED` at the OTP request; a signed-in one loses the session
    /// when the refresh token is revoked), so the blocked gate is covered by unit tests; here, the sign-in refusal.
    func test5b_Blocked() {
        launch(theme: "light")
        tap("Boshlash")
        tap("Keyingisi")
        tap("Keyingisi")
        tap("Boshlash")
        app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "Men haydovchiman")).firstMatch.tap()
        let phoneField = app.textFields.firstMatch
        XCTAssertTrue(phoneField.waitForExistence(timeout: 10))
        phoneField.tap()
        for digit in phone("DRIVER_C") { phoneField.typeText(String(digit)) }
        tap("Kod olish")
        waitFor("Foydalanuvchi bloklangan", timeout: 20)
        snap("28-blocked-signin")
    }

    /// v1 took the car, v2 refused the plate (another driver's v2 vehicle has it): the form is locked, seats and cargo
    /// stay editable, and "Saqlash" retries the vehicle only.
    func test5c_V2Failure() {
        launch(theme: "light")
        signInAsDriver(phone("DRIVER_E"))
        tap("Profilni to'ldirish")
        // A plate another driver holds on v2 only (`TEST_RUNNER_V2_ONLY_PLATE`): v1 takes it, v2 refuses it.
        fillFirstTimeForm(plate: ProcessInfo.processInfo.environment["V2_ONLY_PLATE"] ?? "95 V 7203 VV", name: "Eldor Nazarov")
        tap("Saqlash")
        tap("Ha, saqlash")
        waitFor("Avtomobil ma'lumotlari qulflangan", timeout: 25)
        waitFor("Bu davlat raqami boshqa haydovchiga biriktirilgan")
        snap("12c-form-v2-failed")
        app.swipeUp()
        snap("12d-form-v2-failed-bottom")
    }

    /// The retry state after a fresh start: model / colour / plate locked, seats and cargo editable (no v2 vehicle
    /// yet); "Saqlash" sends the vehicle alone and the server's refusal shows again.
    func test5d_V2Retry() {
        launch(theme: "light")
        signInAsDriver(phone("DRIVER_E"))
        tap("Profilni ko'rish") // DESIGN06 1.11: the car is locked
        waitFor("Avtomobil ma'lumotlari qulflangan", timeout: 20)
        type("4", into: "Yo'lovchi o'rinlari")
        type("20", into: "Yuk uchun joy (kg)")
        type("100", into: "Yuk hajmi (litr)")
        tap("Saqlash")
        // Seats and cargo lock with the v2 vehicle: the retry asks too.
        tap("Ha, saqlash")
        waitFor("Bu davlat raqami boshqa haydovchiga biriktirilgan", timeout: 20)
        snap("12e-form-v2-retry")
    }

    func test6_Menu() {
        launch(theme: "light")
        signInAsDriver(phone("DRIVER_A"))
        tab("profile")
        waitFor("Tasdiqlangan", timeout: 20)
        snap("29-profile-menu")
        menu("threads")
        waitFor("Murojaatlarim")
        snap("30-threads-reused")
        back()
        menu("help")
        waitFor("Murojaat yuborish")
        app.swipeUp()
        app.swipeUp()
        waitFor("Buyurtmalarni qanday olaman?")
        snap("30b-help-driver-faq")
        back()
        menu("settings")
        waitFor("Ko'rinish")
        snap("31-settings-reused")
        back()
        let logout = byId("elchi.driver.menu.logout")
        // The last row starts under the tab bar (still "hittable" to XCTest): scroll to the end first.
        app.swipeUp()
        app.swipeUp()
        logout.tap()
        waitFor("Qolish")
        snap("32-logout-confirm")
        tap("Qolish")
    }

    func test7_Dark() {
        launch(theme: "dark", reset: false)
        waitFor("Bosh sahifa", timeout: 20)
        snap("D1-home-approved-dark")
        tab("profile")
        waitFor("Tasdiqlangan")
        snap("D2-profile-menu-dark")
        byId("elchi.driver.menu.documents").tap()
        waitFor("5 / 5 hujjat yuborilgan", timeout: 20)
        snap("D3-docs-dark")
        back()
        byId("elchi.driver.menu.form").tap()
        waitFor("Avtomobil ma'lumotlari qulflangan", timeout: 20)
        snap("D4-form-locked-dark")

        // D: a fresh driver - the unapproved home, the pending gate, the first-time form and a plate already taken.
        launch(theme: "dark")
        signInAsDriver(phone("DRIVER_D"))
        waitFor("Profilni to'ldiring")
        snap("D5-home-new-dark")
        tab("matches")
        waitFor("Tasdiqlanmaguncha buyurtma qabul qila olmaysiz")
        snap("D6-gate-new-dark")
        tab("home")
        tap("Hujjatlarni yuklash")
        waitFor("0 / 5 hujjat yuborilgan")
        snap("D7-docs-empty-dark")
        back()
        tap("Profilni to'ldirish")
        fillFirstTimeForm(plate: "90 D 002 BB", name: "Dilshod Karimov")
        tap("Saqlash")
        tap("Ha, saqlash")
        waitFor("Bu davlat raqami boshqa haydovchiga biriktirilgan", timeout: 25)
        snap("D8-form-plate-taken-dark")
    }

    func test8_Russian() {
        launch(locale: "ru", theme: "light")
        signInAsDriver(phone("DRIVER_D"), locale: "ru")
        waitFor("Заполните профиль", timeout: 20)
        snap("R1-home-new-ru")
        tab("matches")
        waitFor("Подходящие заказы")
        snap("R2-gate-new-ru")
        tab("home")
        tap("Загрузить документы")
        waitFor("Отправлено документов: 0 / 5")
        snap("R3-docs-empty-ru")
        back("ru")
        tap("Заполнить профиль")
        waitFor("Профиль водителя")
        snap("R4-form-first-ru")
        back("ru")
        tab("profile")
        snap("R5-profile-menu-ru")

        launch(locale: "ru", theme: "light")
        signInAsDriver(phone("DRIVER_A"), locale: "ru")
        waitFor("Главная", timeout: 20)
        waitFor("Подтверждено")
        snap("R6-home-approved-ru")
        tab("profile")
        byId("elchi.driver.menu.documents").tap()
        waitFor("Отправлено документов: 5 / 5", timeout: 20)
        snap("R7-docs-ru")
        back("ru")
        byId("elchi.driver.menu.form").tap()
        waitFor("Данные автомобиля заблокированы", timeout: 20)
        snap("R8-form-locked-ru")

        launch(locale: "ru", theme: "light")
        signInAsDriver(phone("DRIVER_B"), locale: "ru")
        tab("matches")
        waitFor("Написать в поддержку", timeout: 20)
        snap("R9-gate-rejected-ru")
    }

    /// The first-time form again after moving the lock warning under the plate (D is still a new driver).
    func test9_FirstFormLight() {
        launch(theme: "light")
        signInAsDriver(phone("DRIVER_D"))
        tap("Profilni to'ldirish")
        waitFor("saqlangach qulflanadi")
        snap("09b-form-first-warning")
        tap("Saqlash")
        waitFor("Ism familiyani kiriting.")
        snap("09c-form-required")
    }
}
