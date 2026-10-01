import XCTest

/// Stage 03 end to end against the running development backend, in phases the shell drives (run each with
/// `-only-testing:ElchiUITests/ClientOffersUITests/<phase>`, the same `TEST_RUNNER_ELCHI_PHONE` for all):
///
/// 1. `test1_PublishManageShare` - a new client: empty orders, posts a request, orders -> detail, edits price
///    (not material) and window (material, no offers yet), pauses and resumes, creates a share link.
///    Shell: `offers.py latest --client +998<phone>` then `offers.py offer <listing>` (two demo drivers answer).
/// 2. `test2_OffersCounterReject` - orders show the offers; offers screen (sorts), the material-edit warning with
///    the open-offer count (not saved), the cancel sheet (not confirmed), a counter to the cheapest driver, a
///    reject of the other, Takliflarim. `test2b_*` / `test2c_*`: the same screens in Russian + dark and Uzbek + dark.
///    Shell: `offers.py list <listing>` then `offers.py counter <thread> --price <som> --driver 1011`.
/// 3. `test3_Accept` - the driver's counter, the accept dialog, the booking at the top of the orders list.
/// 4. `test4_CancelListing` - the listing cancelled through the confirmation sheet (`test3x_AcceptRefused`: an accept
///    the server refuses because of the driver's wallet, said neutrally).
///
/// Phases 2-4 do not sign in again: the client of phase 1 is still signed in (one OTP per phone per minute).
final class ClientOffersUITests: ClientUITestCase {
    private func openOrders() {
        let menu = app.buttons["Menyu"].firstMatch
        XCTAssertTrue(menu.waitForExistence(timeout: 20), "no menu button")
        menu.tap()
        waitFor("ELCHI")
        tap("Buyurtmalar")
        waitFor("E'lonlarim", timeout: 20)
    }

    /// The newest listing card (the list is newest first; booking rows are not buttons).
    private func openNewestListing(status: String = "E'lon qilingan") {
        let card = app.buttons.containing(NSPredicate(format: "label CONTAINS %@ AND label CONTAINS %@", "→", status)).firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 20), "no listing card '\(status)'")
        card.tap()
        waitFor("Buyurtma tafsilotlari")
        waitFor("Olib ketish joyi")
    }

    /// The departure window's end on the date picker sheet: moves the hour to `hour` and confirms.
    private func moveWindowEnd(toHour hour: String) {
        tap("Jo'nash oynasi tugashi")
        waitFor("Tasdiqlash")
        let wheels = app.pickerWheels
        if !wheels.firstMatch.exists {
            // The graphical picker shows the time as a button; tapping it opens the wheels.
            let time = app.buttons.matching(NSPredicate(format: "label MATCHES %@", "^[0-9]{1,2}:[0-9]{2}$")).firstMatch
            if time.waitForExistence(timeout: 5) { time.tap() }
        }
        XCTAssertTrue(wheels.firstMatch.waitForExistence(timeout: 5), "no time wheels")
        wheels.element(boundBy: 0).adjust(toPickerWheelValue: hour)
        // Close the wheels, then confirm the sheet.
        app.otherElements.firstMatch.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.1)).tap()
        tap("Tasdiqlash")
    }

    func test1_PublishManageShare() {
        launch()
        signInAsClient(phone: Self.runPhone)

        // A new client: nothing yet.
        openOrdersFromHome(empty: true)
        snap("40-orders-empty")
        tap("Yangi buyurtma")
        waitFor("Qayerdan?")

        postParcelRequest(price: "120000")
        snap("41-success")
        tap("Buyurtmalarimga o'tish")
        waitFor("E'lonlarim", timeout: 20)
        waitFor("E'lon qilingan")
        snap("42-orders-listing")

        openNewestListing()
        waitFor("E'lon amal qiladi")
        snap("43-detail-top")
        app.swipeUp()
        waitFor("Boshqaruv")
        snap("44-detail-manage")

        // Price only: not material, nothing to warn about.
        tap("Tahrirlash")
        waitFor("E'lonni tahrirlash")
        waitFor("Narx va izohni o'zgartirish ochiq takliflarni yopmaydi")
        snap("45-edit")
        replace("Narx (so'm)", with: "130000")
        tap("Saqlash")
        waitFor("E'lon yangilandi", timeout: 20)
        waitFor("130")
        snap("46-detail-saved")

        // The window (material) with no offers yet: saved without the warning.
        tap("Tahrirlash")
        waitFor("E'lonni tahrirlash")
        moveWindowEnd(toHour: "19")
        waitFor("19:00")
        XCTAssertFalse(app.buttons["Tushundim, saqlash"].exists)
        snap("47-edit-window")
        tap("Saqlash")
        waitFor("E'lon yangilandi", timeout: 20)
        waitFor("19:00")

        // Pause, then resume.
        app.swipeUp()
        tap("Vaqtincha to'xtatish")
        waitFor("E'lon to'xtatildi", timeout: 20)
        waitFor("To'xtatilgan")
        app.swipeDown()
        snap("48-detail-paused")
        app.swipeUp()
        tap("Qayta ochish")
        waitFor("E'lon qayta ochildi", timeout: 20)

        // Share link: 7 days, Telegram text.
        app.swipeUp()
        tap("7 kun")
        tap("Telegram")
        snap("49-share-options")
        tap("Havola yaratish")
        waitFor("Nusxa olish", timeout: 20)
        app.swipeUp()
        snap("49-share-link")
    }

    /// Home -> drawer -> Buyurtmalar (and, for a new client, its empty state).
    private func openOrdersFromHome(empty: Bool) {
        let menu = app.buttons["Menyu"].firstMatch
        XCTAssertTrue(menu.waitForExistence(timeout: 20))
        menu.tap()
        waitFor("ELCHI")
        snap("39-drawer")
        tap("Buyurtmalar")
        waitFor(empty ? "Hozircha buyurtmalar yo'q" : "E'lonlarim", timeout: 20)
    }

    func test2_OffersCounterReject() {
        launch(reset: false)
        openOrders()
        waitFor("2 ta taklif", timeout: 20)
        waitFor("Eng yangi taklif")
        snap("50-orders-offers")

        openNewestListing()
        tap("Takliflarni ko'rish (2)")
        waitFor("Haydovchi takliflari")
        waitFor("Shu haydovchini tanlash")
        waitFor("amal qiladi")
        snap("51-bids-cheapest")
        tap("Eng tez")
        snap("52-bids-fastest")
        tap("Eng arzon")
        app.swipeUp()
        snap("51-bids-bottom")

        // The material-edit warning with the open-offer count - not saved.
        tap("Orqaga")
        tap("Tahrirlash")
        waitFor("E'lonni tahrirlash")
        moveWindowEnd(toHour: "20")
        waitFor("Ochiq takliflar: 2 ta")
        XCTAssertTrue(button("Tushundim, saqlash").exists)
        snap("53-edit-material-warning")
        tap("Orqaga")

        // The cancel sheet counts the open offers - not confirmed.
        app.swipeUp()
        tap("Buyurtmani bekor qilish")
        waitFor("2 ta ochiq taklif rad etiladi")
        snap("54-cancel-sheet")
        tap("Ortga")
        waitGone("2 ta ochiq taklif rad etiladi")

        // Another price to the cheapest driver (first card), then refuse the other one.
        app.swipeDown()
        tap("Takliflarni ko'rish (2)")
        waitFor("Shu haydovchini tanlash")
        tap("Boshqa narx (3 marta qoldi)")
        waitFor("Sizning narxingiz (so'm)")
        snap("55-counter-form")
        replace("Sizning narxingiz (so'm)", with: "115000")
        tap("Yuborish")
        waitFor("haydovchining javobi kutilmoqda", timeout: 20)
        waitFor("Taklifni qaytarib olish")
        snap("56-counter-waiting")
        tap("Rad etish")
        waitFor("rad etilgan", timeout: 20)
        snap("57-rejected")

        tap("Orqaga")
        tap("Orqaga")
        tap("Takliflarim")
        waitFor("Takliflarim")
        waitFor("javob kutilmoqda", timeout: 20)
        snap("58-proposals")
    }

    /// Russian + dark: orders, detail, the offers screen, Takliflarim (run between phases 2 and 3, read-only).
    func test2b_RussianDark() {
        launch(locale: "ru", theme: "dark", reset: false)
        let menu = app.buttons["Меню"].firstMatch
        XCTAssertTrue(menu.waitForExistence(timeout: 20))
        menu.tap()
        tap("Заказы")
        waitFor("Мои объявления", timeout: 20)
        snap("70-ru-dark-orders")
        app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "→")).firstMatch.tap()
        waitFor("Детали заказа")
        snap("71-ru-dark-detail")
        app.swipeUp()
        snap("72-ru-dark-detail-manage")
        app.swipeDown()
        tap("Посмотреть предложения")
        waitFor("Предложения водителей")
        snap("73-ru-dark-bids")
        tap("Назад")
        tap("Назад")
        tap("Мои предложения")
        waitFor("Мои предложения")
        snap("74-ru-dark-proposals")
    }

    /// Uzbek + dark: the offers screen and the counter form.
    func test2c_UzbekDark() {
        launch(theme: "dark", reset: false)
        openOrders()
        snap("75-uz-dark-orders")
        openNewestListing()
        tap("Takliflarni ko'rish")
        waitFor("Haydovchi takliflari")
        snap("76-uz-dark-bids")
    }

    func test3_Accept() {
        launch(reset: false)
        openOrders()
        openNewestListing()
        tap("Takliflarni ko'rish")
        waitFor("Shu haydovchini tanlash", timeout: 20)
        snap("60-bids-driver-countered")
        tap("Shu haydovchini tanlash")
        waitFor("ni tanlaysizmi?")
        waitFor("Kelishilgan narx")
        snap("61-accept-dialog")
        tap("Ha, tanlayman")
        waitFor("Haydovchi tanlandi", timeout: 30)
        waitFor("Bronlar", timeout: 20)
        snap("62-orders-booking")
        app.swipeUp()
        snap("63-orders-booking-bottom")
        app.swipeDown()
        tap("Takliflarim")
        waitFor("qabul qilingan", timeout: 20)
        snap("64-proposals-after-accept")
    }

    /// The driver cannot take the booking (its commission wallet): the client is told neutrally, the offer stays.
    func test3x_AcceptRefused() {
        launch(reset: false)
        openOrders()
        openNewestListing()
        tap("Takliflarni ko'rish")
        tap("Shu haydovchini tanlash")
        tap("Ha, tanlayman")
        waitFor("Bu haydovchi hozir buyurtmani ola olmaydi", timeout: 30)
        snap("68-accept-refused")
    }

    /// Cancels the published listing (open offers are refused with it) through the confirmation sheet.
    func test4_CancelListing() {
        launch(reset: false)
        openOrders()
        openNewestListing()
        app.swipeUp()
        tap("Buyurtmani bekor qilish")
        waitFor("Buyurtmani bekor qilasizmi?")
        snap("65-cancel-sheet")
        tap("Ha, bekor qilish")
        waitFor("Buyurtma bekor qilindi", timeout: 20)
        waitFor("Bekor qilingan")
        snap("66-cancelled")
        tap("Orqaga")
        waitFor("Bekor qilingan")
        snap("67-orders-final")
        tap("Takliflarim")
        waitFor("Yopilgan", timeout: 20)
        snap("69-proposals-after-cancel")
    }
}
