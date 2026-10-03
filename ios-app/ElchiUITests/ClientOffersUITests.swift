import XCTest

/// Stage 03 end to end against the running development backend, in phases the shell drives (run each with
/// `-only-testing:ElchiUITests/ClientOffersUITests/<phase>`, the same `TEST_RUNNER_ELCHI_PHONE` for all):
///
/// BOSQICH 03 design: the offers are inline on the listing's detail; edit (pencil) and share are bar icons; the
/// orders bar has the notifications bell; "Takliflarim" is in the drawer.
///
/// 1. `test1_PublishManageShare` - a new client: empty orders, posts a request, orders -> detail, edits price
///    (not material) and window (material, no offers yet), pauses and resumes, shares (system sheet) and revokes.
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
        waitFor("Holat")
    }

    /// Scrolls the body until the button can be tapped.
    private func scrollTap(_ label: String, maxSwipes: Int = 6) {
        let element = button(label)
        var swipes = 0
        while !element.isHittable && swipes < maxSwipes {
            app.swipeUp()
            swipes += 1
        }
        waitEnabled(element, label)
        element.tap()
    }

    /// Back to the orders list, then the drawer's "Takliflarim".
    private func openProposalsFromDrawer(menu: String = "Menyu", row: String = "Takliflarim") {
        let menuButton = app.buttons[menu].firstMatch
        XCTAssertTrue(menuButton.waitForExistence(timeout: 20), "no menu button")
        menuButton.tap()
        tap(row)
        waitFor(row)
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

    /// Closes the system share sheet (its own close button, else a swipe down).
    private func closeShareSheet() {
        let close = app.otherElements["ActivityListView"].buttons["Close"].firstMatch
        if close.waitForExistence(timeout: 5) {
            close.tap()
        } else {
            app.swipeDown(velocity: .fast)
        }
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
        waitFor("E'lon amal qiladi")
        snap("42-orders-listing")

        openNewestListing()
        waitFor("Jo'nash, ")
        waitFor("Hozircha taklif yo'q")
        snap("43-detail-top")
        app.swipeUp()
        waitFor("Haydovchi javob berganda shu yerda ko'rinadi")
        waitFor("Vaqtincha to'xtatish")
        snap("44-detail-manage")

        // Price only: not material, nothing to warn about (the pencil in the bar).
        tap("Tahrirlash")
        waitFor("E'lonni tahrirlash")
        waitFor("Narx va izohni o'zgartirish ochiq takliflarni yopmaydi")
        snap("45-edit")
        // Tap-to-validate: an empty price says so on "Saqlash".
        replace("Narx (so'm)", with: "")
        tap("Saqlash")
        waitFor("Narxni kiriting.")
        snap("45-edit-error")
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
        scrollTap("Vaqtincha to'xtatish")
        waitFor("E'lon to'xtatildi", timeout: 20)
        waitFor("E'lon lentadan yashirilgan.")
        app.swipeDown()
        snap("48-detail-paused")
        scrollTap("Qayta ochish")
        waitFor("E'lon qayta ochildi", timeout: 20)
        app.swipeDown()

        // Share: the bar icon makes the link and opens the system sheet with the server's text.
        tap("Ulashish")
        let sheet = app.otherElements["ActivityListView"].firstMatch
        XCTAssertTrue(sheet.waitForExistence(timeout: 20), "no share sheet")
        snap("49-share-sheet")
        closeShareSheet()
        app.swipeUp()
        waitFor("Havolani bekor qilish")
        snap("49-share-link")
        // The same link is shared again (the five-link limit is not spent).
        app.swipeDown()
        tap("Ulashish")
        XCTAssertTrue(sheet.waitForExistence(timeout: 20), "no share sheet the second time")
        closeShareSheet()
        scrollTap("Havolani bekor qilish")
        waitFor("Havola bekor qilindi", timeout: 20)
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
        waitFor("Yangi taklif:")
        snap("50-orders-offers")

        openNewestListing()
        waitFor("2 ta ochiq taklif")
        snap("51-detail-offers-top")
        app.swipeUp()
        waitFor("Tanlash")
        waitFor("qoldi")
        snap("51-bids-cheapest")
        tap("Eng tez")
        snap("52-bids-fastest")
        tap("Eng arzon")
        app.swipeUp()
        snap("51-bids-bottom")

        // The material-edit warning with the open-offer count - not saved.
        app.swipeDown()
        app.swipeDown()
        tap("Tahrirlash")
        waitFor("E'lonni tahrirlash")
        moveWindowEnd(toHour: "20")
        waitFor("2 ta ochiq taklif yopiladi")
        XCTAssertTrue(button("Tushundim, saqlash").exists)
        snap("53-edit-material-warning")
        tap("Orqaga")

        // The cancel sheet counts the open offers - not confirmed.
        scrollTap("Buyurtmani bekor qilish")
        waitFor("2 ta ochiq taklif rad etiladi")
        snap("54-cancel-sheet")
        tap("Ortga")
        waitGone("2 ta ochiq taklif rad etiladi")

        // Another price to the cheapest driver (first card), then refuse the other one.
        let counter = app.buttons.containing(NSPredicate(format: "label BEGINSWITH %@", "Boshqa narx")).firstMatch
        XCTAssertTrue(counter.waitForExistence(timeout: 15))
        app.swipeDown()
        scrollTap("Boshqa narx")
        waitFor("Sizning narxingiz (so'm)")
        // The driver's own price is refused on tap.
        tap("Yuborish")
        waitFor("Haydovchi narxidan farqli narx kiriting.")
        snap("55-counter-form")
        replace("Sizning narxingiz (so'm)", with: "115000")
        tap("Yuborish")
        waitFor("javob kutilmoqda", timeout: 20)
        waitFor("Taklifni qaytarib olish")
        snap("56-counter-waiting")
        scrollTap("Rad etish")
        waitFor("taklifi rad etildi", timeout: 20)
        snap("57-rejected")

        tap("Orqaga")
        openProposalsFromDrawer()
        waitFor("javob kutilmoqda", timeout: 20)
        snap("58-proposals")
    }

    /// Russian + dark: orders, detail, the inline offers, Takliflarim (run between phases 2 and 3, read-only).
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
        snap("72-ru-dark-detail-offers")
        app.swipeUp()
        snap("73-ru-dark-bids")
        tap("Назад")
        openProposalsFromDrawer(menu: "Меню", row: "Мои предложения")
        snap("74-ru-dark-proposals")
    }

    /// Uzbek + dark: the detail, the inline offers and the notifications from the bell.
    func test2c_UzbekDark() {
        launch(theme: "dark", reset: false)
        openOrders()
        snap("75-uz-dark-orders")
        openNewestListing()
        snap("76-uz-dark-detail")
        app.swipeUp()
        snap("76-uz-dark-bids")
        tap("Orqaga")
        tap("Bildirishnomalar")
        waitFor("Bildirishnomalar")
        snap("77-uz-dark-notifications")
    }

    /// The bell on the orders bar: notifications pushed with a back button, "Hammasini o'qilgan deb belgilash".
    func test2d_Notifications() {
        launch(reset: false)
        openOrders()
        snap("78-orders-bell")
        tap("Bildirishnomalar")
        waitFor("Bildirishnomalar")
        snap("79-notifications")
        let readAll = app.buttons["elchi.inbox.readAll"].firstMatch
        if readAll.waitForExistence(timeout: 5) {
            readAll.tap()
            waitGone("Hammasini o'qilgan deb belgilash")
            snap("79-notifications-read")
        }
        tap("Orqaga")
        waitFor("E'lonlarim")
    }

    func test3_Accept() {
        launch(reset: false)
        openOrders()
        openNewestListing()
        // The driver answered the client's counter: "Qarshi taklif" and "Qabul qilish".
        waitFor("Qarshi taklif", timeout: 20)
        app.swipeUp()
        snap("60-bids-driver-countered")
        scrollTap("Qabul qilish")
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
        openProposalsFromDrawer()
        waitFor("Qabul qilingan", timeout: 20)
        snap("64-proposals-after-accept")
    }

    /// The driver cannot take the booking (its commission wallet): the client is told neutrally, the offer stays.
    func test3x_AcceptRefused() {
        launch(reset: false)
        openOrders()
        openNewestListing()
        scrollTap("Tanlash")
        tap("Ha, tanlayman")
        waitFor("Bu haydovchi hozir buyurtmani ola olmaydi", timeout: 30)
        snap("68-accept-refused")
    }

    /// Cancels the published listing (open offers are refused with it) through the confirmation sheet.
    func test4_CancelListing() {
        launch(reset: false)
        openOrders()
        openNewestListing()
        scrollTap("Buyurtmani bekor qilish")
        waitFor("Buyurtmani bekor qilasizmi?")
        snap("65-cancel-sheet")
        tap("Ha, bekor qilish")
        waitFor("Buyurtma bekor qilindi", timeout: 20)
        waitFor("E'lon bekor qilindi, ochiq takliflar rad etildi.")
        app.swipeDown()
        snap("66-cancelled")
        tap("Orqaga")
        waitFor("Bekor qilingan")
        snap("67-orders-final")
        openProposalsFromDrawer()
        waitFor("E'lon bekor qilindi", timeout: 20)
        snap("69-proposals-after-cancel")
    }
}
