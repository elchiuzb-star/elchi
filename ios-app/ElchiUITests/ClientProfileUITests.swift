import XCTest

/// Stage 05 against the running development backend, in phases the shell drives (scratchpad `ios-s05/run_all.sh`):
///
/// 0. `test0_SignIn` - the Stage 04 client (`TEST_RUNNER_ELCHI_PHONE`; it has notifications, a support thread with
///    operator replies, a report and a block) signs in.
/// 1. `test1_Notifications` - unread dot on the menu, the drawer, the inbox, a tap marks an item read and opens its
///    booking.
/// 2. `test2_Profile` - figures, rename, the drawer shows the new name.
/// 3. `test3_Bonus` - whatever state the programme is in (dev: off).
/// 4. `test4_Safety` - blocks and reports; "Chiqarish" shows the backend's refusal and keeps the row.
/// 5. `test5_Support` - a ticket sent and listed; "Murojaatlarim" -> the thread with the operator's reply.
/// 6. `test6_Settings` - three appearance modes, the language switch, the logout confirm ("Qolish").
/// 7. `test7_RussianDark`, `test7b_UzbekDark` - the screens in the other language and theme.
/// 8. `test8_SessionExpired` - both tokens garbage: "Sessiya tugadi" -> "Qayta kirish" -> phone pre-filled -> signed in.
/// 9. `test9_Logout` - the confirm, then signed out.
/// A. `testA_DeleteBlocked` (a throwaway client with a booking made by the shell) and `testB_DeleteDone` (a clean
///    throwaway): both sign in first (`ELCHI_DELETE_PHONE`).
final class ClientProfileUITests: ClientUITestCase {
    // MARK: Helpers

    private func menu(_ locale: String = "uz") {
        let button = app.buttons[locale == "ru" ? "Меню" : "Menyu"].firstMatch
        XCTAssertTrue(button.waitForExistence(timeout: 20), "no menu button")
        button.tap()
    }

    /// Opens a drawer section by its row id (`elchi.drawer.<section>`): the labels overlap ("Profil" says "Sozlamalar va
    /// hisob" under its title).
    private func drawer(_ section: String, locale: String = "uz") {
        menu(locale)
        let row = app.buttons["elchi.drawer.\(section)"]
        XCTAssertTrue(row.waitForExistence(timeout: 10), "no drawer row '\(section)'")
        row.tap()
    }

    private func back() { tap("Orqaga") }

    /// Scrolls until the button is hittable, then taps it.
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

    private func card(containing text: String) -> XCUIElement {
        let card = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", text)).firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 20), "no card '\(text)'")
        return card
    }

    // MARK: Phases

    func test0_SignIn() {
        launch()
        signInAsClient(phone: Self.runPhone)
    }

    func test1_Notifications() {
        launch(theme: "light", reset: false)
        let menuButton = app.buttons["Menyu"].firstMatch
        XCTAssertTrue(menuButton.waitForExistence(timeout: 20))
        // The dot comes with the unread page.
        let dotted = expectation(for: NSPredicate(format: "value == %@", "Bildirishnomalar"), evaluatedWith: menuButton)
        XCTAssertEqual(XCTWaiter().wait(for: [dotted], timeout: 20), .completed, "no unread dot on the menu")
        waitMapDrawn()
        snap("01-home-unread-dot")
        menuButton.tap()
        waitFor("Bosh sahifa")
        snap("02-drawer")
        app.buttons["elchi.drawer.notifications"].tap()
        waitFor("Yangi", timeout: 20)
        snap("03-notifications")
        // An unread "Kelishuv tuzildi" (a booking): tapping it marks it read and opens the booking.
        let unreadAccepted = NSPredicate(format: "label CONTAINS %@ AND label CONTAINS %@", "Kelishuv tuzildi", "Yangi")
        let before = app.buttons.matching(unreadAccepted).count
        XCTAssertGreaterThan(before, 0, "no unread booking notification left")
        app.buttons.matching(unreadAccepted).firstMatch.tap()
        waitFor("Haydovchi va avtomobil", timeout: 20)
        snap("04-notification-opened-booking")
        back()
        waitFor("Bildirishnomalar")
        XCTAssertEqual(app.buttons.matching(unreadAccepted).count, before - 1, "the tapped item is still unread")
        snap("05-notifications-after-read")
        // A support reply opens the operator chat.
        app.swipeUp()
        let reply = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "Operator javob berdi")).firstMatch
        if reply.waitForExistence(timeout: 5) {
            reply.tap()
            waitFor("Operator bilan yozishma", timeout: 20)
            snap("06-notification-opened-support")
            back()
        }
    }

    func test2_Profile() {
        launch(theme: "light", reset: false)
        drawer("profile")
        waitFor("Mijoz akkaunti", timeout: 20)
        waitFor("Buyurtmalar holati")
        waitGone("—", timeout: 20)
        snap("10-profile")
        // Two saves, so the run works whatever name the account had: another name, then the design's.
        for value in ["Dilnoza Karimova", "Aziza Karimova"] {
            let name = field("Ism familiya")
            name.tap()
            let current = name.value as? String ?? ""
            name.coordinate(withNormalizedOffset: CGVector(dx: 0.95, dy: 0.5)).tap()
            for _ in 0..<(current.count + 2) { name.typeText(XCUIKeyboardKey.delete.rawValue) }
            for character in value { name.typeText(String(character)) }
            tap("Saqlash")
            waitFor("Profil yangilandi", timeout: 20)
        }
        sleep(1)
        snap("11-profile-saved")
        app.swipeUp()
        app.swipeUp()
        snap("12-profile-actions")
        menu()
        waitFor("Aziza Karimova")
        snap("13-drawer-new-name")
    }

    func test3_Bonus() {
        launch(theme: "light", reset: false)
        drawer("profile")
        scrollTap("Bonuslar va taklif kodi")
        waitFor("Mening bonuslarim", timeout: 20)
        // Dev: promotions off -> the one sentence, no code, no entry, no campaigns.
        waitFor("Taklif dasturi hozircha ishlamayapti", timeout: 20)
        snap("20-bonus")
    }

    func test4_Safety() {
        launch(theme: "light", reset: false)
        drawer("profile")
        scrollTap("Bloklanganlar va shikoyatlarim")
        waitFor("Mening shikoyatlarim", timeout: 20)
        waitFor("Bloklangan:")
        snap("30-safety-center")
        tap("Chiqarish")
        waitFor("Blokdan chiqarish")
        snap("31-unblock-confirm")
        let confirm = app.buttons["elchi.unblock.confirm"]
        XCTAssertTrue(confirm.waitForExistence(timeout: 5))
        confirm.tap()
        waitFor("Blokdan chiqarib bo'lmadi", timeout: 20)
        waitFor("Bloklangan:")
        snap("32-unblock-failed")
    }

    func test5_Support() {
        launch(theme: "light", reset: false)
        drawer("support")
        waitFor("Hozircha telefon liniyasi yo'q", timeout: 20)
        snap("40-support")
        let text = "Posilka kechikmoqda, bron B-\(Int(Date().timeIntervalSince1970) % 10000)"
        let field = app.textViews.firstMatch.exists ? app.textViews.firstMatch : app.textFields.firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        field.tap()
        for character in text { field.typeText(String(character)) }
        tap("Yuborish")
        waitFor("Murojaat yuborildi", timeout: 20)
        waitFor(text)
        snap("41-support-ticket-sent")
        app.swipeUp()
        snap("42-support-faq")
        let threadsRow = app.buttons["elchi.support.threads"]
        var swipes = 0
        while !threadsRow.isHittable && swipes < 6 { app.swipeUp(); swipes += 1 }
        threadsRow.tap()
        waitFor("Operator bilan yozishma", timeout: 20)
        snap("43-support-threads")
        card(containing: "Operator bilan yozishma").tap()
        waitFor("Operator", timeout: 20)
        waitFor("Salom!", timeout: 20)
        snap("44-support-thread")
    }

    func test6_Settings() {
        launch(theme: "light", reset: false)
        menu()
        waitFor("Bosh sahifa")
        snap("49-drawer-name")
        app.buttons["elchi.drawer.settings"].tap()
        waitFor("Ilova tilini tanlang", timeout: 20)
        snap("50-settings-light")
        tap("Qorong'i")
        sleep(1)
        snap("51-settings-dark")
        tap("Tizim")
        sleep(1)
        snap("52-settings-system")
        tap("Yorug'")
        tap("Русский")
        waitFor("Настройки")
        snap("53-settings-ru")
        tap("O'zbekcha")
        waitFor("Sozlamalar")
        scrollTap("Chiqish")
        waitFor("Chiqasizmi?")
        snap("54-logout-confirm")
        tap("Qolish")
        waitGone("Chiqasizmi?")
        waitFor("Sozlamalar")
    }

    func test7_RussianDark() {
        launch(locale: "ru", theme: "dark", reset: false)
        drawer("notifications", locale: "ru")
        waitFor("Уведомления", timeout: 20)
        snap("60-ru-dark-notifications")
        drawer("profile", locale: "ru")
        waitFor("Аккаунт клиента", timeout: 20)
        waitGone("—", timeout: 20)
        snap("61-ru-dark-profile")
        scrollTap("Бонусы и код приглашения")
        waitFor("Мои бонусы", timeout: 20)
        snap("62-ru-dark-bonus")
        tap("Назад")
        scrollTap("Блокировки и мои жалобы")
        waitFor("Мои жалобы", timeout: 20)
        snap("63-ru-dark-safety")
        tap("Назад")
        drawer("support", locale: "ru")
        waitFor("Телефонной линии пока нет", timeout: 20)
        snap("64-ru-dark-support")
        drawer("settings", locale: "ru")
        waitFor("Выберите язык приложения", timeout: 20)
        snap("65-ru-dark-settings")
        tap("Удалить аккаунт")
        waitFor("Что удаляется", timeout: 20)
        snap("66-ru-dark-account-delete")
    }

    func test7b_UzbekDark() {
        launch(theme: "dark", reset: false)
        drawer("notifications")
        waitFor("Bildirishnomalar", timeout: 20)
        snap("70-uz-dark-notifications")
        drawer("profile")
        waitFor("Mijoz akkaunti", timeout: 20)
        waitGone("—", timeout: 20)
        snap("71-uz-dark-profile")
        drawer("settings")
        waitFor("Ilova tilini tanlang", timeout: 20)
        snap("72-uz-dark-settings")
        tap("Akkauntni o'chirish")
        waitFor("Nima o'chiriladi", timeout: 20)
        snap("73-uz-dark-account-delete")
        back()
        scrollTap("Chiqish")
        waitFor("Chiqasizmi?")
        snap("74-uz-dark-logout-confirm")
        tap("Qolish")
    }

    func test8_SessionExpired() {
        launch(theme: "light", reset: false, extra: ["-uiTestExpireSession"])
        waitFor("Sessiya tugadi", timeout: 30)
        snap("80-session-expired")
        tap("Qayta kirish")
        let phone = app.textFields.firstMatch
        XCTAssertTrue(phone.waitForExistence(timeout: 10), "no phone field")
        let digits = (phone.value as? String ?? "").filter(\.isNumber)
        XCTAssertEqual(digits, Self.runPhone, "the phone is not pre-filled")
        snap("81-relogin-phone-prefilled")
        tap("Kod olish")
        XCTAssertTrue(app.textFields.firstMatch.waitForExistence(timeout: 10))
        app.textFields.firstMatch.typeText("1234")
        let home = app.buttons["Menyu"].firstMatch.waitForExistence(timeout: 20)
        if !home { snap("81b-relogin-stuck") }
        XCTAssertTrue(home, "not signed in again")
        snap("82-relogin-home")
    }

    func test9_Logout() {
        launch(theme: "light", reset: false)
        menu()
        scrollTap("Chiqish")
        waitFor("Chiqasizmi?")
        snap("90-drawer-logout-confirm")
        app.buttons["elchi.logout.confirm"].tap()
        waitFor("Men mijozman", timeout: 20)
        snap("91-signed-out")
    }

    // MARK: Account deletion (throwaway clients only)

    private var deletePhone: String {
        ProcessInfo.processInfo.environment["ELCHI_DELETE_PHONE"] ?? Self.runPhone
    }

    func testA0_SignInThrowaway() {
        launch()
        signInAsClient(phone: deletePhone)
    }

    func testA_DeleteBlocked() {
        launch(theme: "light", reset: false)
        drawer("settings")
        waitFor("Ilova tilini tanlang", timeout: 20)
        tap("Akkauntni o'chirish")
        waitFor("Nima o'chiriladi", timeout: 20)
        let submit = app.buttons["elchi.accountDelete.submit"]
        XCTAssertTrue(submit.waitForExistence(timeout: 10))
        XCTAssertFalse(submit.isEnabled, "the danger button is enabled before the tick")
        snap("A0-delete-unticked")
        tap("Tushundim")
        waitEnabled(submit, "Akkauntni o'chirish")
        snap("A1-delete-ticked")
        submit.tap()
        waitFor("Hozircha o'chirib bo'lmaydi", timeout: 20)
        waitFor("Faol bronlar")
        snap("A2-delete-blocked")
    }

    func testB_DeleteDone() {
        launch(theme: "light", reset: false)
        drawer("settings")
        waitFor("Ilova tilini tanlang", timeout: 20)
        tap("Akkauntni o'chirish")
        waitFor("Nima o'chiriladi", timeout: 20)
        tap("Tushundim")
        let submit = app.buttons["elchi.accountDelete.submit"]
        waitEnabled(submit, "Akkauntni o'chirish")
        submit.tap()
        waitFor("Akkaunt o'chirildi", timeout: 20)
        waitFor("Men mijozman")
        snap("B0-deleted-signed-out")
    }
}
