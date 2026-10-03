import XCTest

/// BOSQICH 05 ("Elchi Profil") on the running development backend, driven by `elchi-dev/ios-design05/run.sh`: each run
/// does the steps named in `STEPS` (comma separated) and saves PNGs as `<TAG>-<step>-…` into `SHOTS`. `FIRST=1` starts
/// from a fresh install signed in with `-uiTestSession` (`SESSION`); later runs reuse the stored session.
///
/// Steps: `profile` (top, the 2-letter error, quick actions), `bonus`, `safety` (unblock when a row exists),
/// `support` (hint, threads section, "Hammasi", refresh toast, a thread), `notifications`, `settings` (theme toast,
/// delete confirm dialog - always "Ortga"), `logout` (the signed-out notice), `deleteBlocked` (409 card + "Buyurtmalarga
/// o'tish"), `deleteDone` (a throwaway only).
final class ClientDesign05UITests: ClientUITestCase {
    private var env: [String: String] { ProcessInfo.processInfo.environment }
    private var ru: Bool { env["LOCALE"] == "ru" }
    private func L(_ uz: String, _ ru: String) -> String { self.ru ? ru : uz }
    private var tag: String { env["TAG"] ?? "x" }

    private func shot(_ name: String) { snap("\(tag)-\(name)") }

    private func scrollTo(_ element: XCUIElement, maxSwipes: Int = 10) {
        var swipes = 0
        while !(element.exists && element.isHittable) && swipes < maxSwipes {
            app.swipeUp()
            swipes += 1
        }
    }

    private func scrollTop() { for _ in 0..<4 { app.swipeDown() } }

    private func drawer(_ section: String) {
        let menu = app.buttons[L("Menyu", "Меню")].firstMatch
        XCTAssertTrue(menu.waitForExistence(timeout: 25), "no menu button")
        menu.tap()
        let row = app.buttons["elchi.drawer.\(section)"]
        XCTAssertTrue(row.waitForExistence(timeout: 10), "no drawer row '\(section)'")
        row.tap()
    }

    private func back() {
        let button = app.buttons[L("Orqaga", "Назад")].firstMatch
        XCTAssertTrue(button.waitForExistence(timeout: 10), "no back button")
        button.tap()
    }

    private func settle(_ seconds: TimeInterval = 1.2) { Thread.sleep(forTimeInterval: seconds) }

    func testTour() {
        var extra: [String] = []
        if env["FIRST"] == "1" { extra += ["-uiTestSession", env["SESSION"] ?? ""] }
        launch(locale: env["LOCALE"] ?? "uz", theme: env["THEME"] ?? "light", reset: env["FIRST"] == "1", extra: extra)
        for step in (env["STEPS"] ?? "").split(separator: ",").map(String.init) {
            switch step {
            case "profile": profile()
            case "bonus": bonus()
            case "safety": safety()
            case "support": support()
            case "notifications": notifications()
            case "settings": settings()
            case "logout": logout()
            case "deleteBlocked": deleteBlocked()
            case "deleteDone": deleteDone()
            default: XCTFail("unknown step \(step)")
            }
        }
    }

    private func profile() {
        drawer("profile")
        waitFor(L("Mijoz akkaunti", "Аккаунт клиента"), timeout: 20)
        waitGone("—", timeout: 20)
        settle()
        shot("profile-top")
        if env["INTERACT"] == "1" {
            let name = app.textFields.firstMatch
            XCTAssertTrue(name.waitForExistence(timeout: 10))
            name.tap()
            name.coordinate(withNormalizedOffset: CGVector(dx: 0.95, dy: 0.5)).tap()
            let current = name.value as? String ?? ""
            for _ in 0..<(current.count + 2) { name.typeText(XCUIKeyboardKey.delete.rawValue) }
            name.typeText("A")
            tap(L("Saqlash", "Сохранить"))
            waitFor(L("Kamida 2 ta harf", "не менее 2"), timeout: 10)
            shot("profile-name-error")
            // Back to the stored name (never saved): type it again so the form is clean.
            name.typeText(XCUIKeyboardKey.delete.rawValue)
            for character in current { name.typeText(String(character)) }
            app.swipeDown()
        }
        app.swipeUp()
        settle()
        shot("profile-actions")
        app.swipeUp()
        settle()
        shot("profile-actions-bottom")
        scrollTop()
    }

    private func openFromProfile(_ label: String) {
        drawer("profile")
        waitFor(L("Mijoz akkaunti", "Аккаунт клиента"), timeout: 20)
        let row = button(label)
        scrollTo(row)
        row.tap()
    }

    private func bonus() {
        openFromProfile(L("Bonuslar va taklif kodi", "Бонусы и код приглашения"))
        // Off (centred sentence) or on (balance, navy code card, entry, campaigns): whichever dev is in.
        let off = app.descendants(matching: .any)["elchi.bonus.off"]
        let on = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", L("Mening bonuslarim", "Мои бонусы"))).firstMatch
        XCTAssertTrue(off.waitForExistence(timeout: 20) || on.exists, "bonus screen not loaded")
        settle(2)
        shot("bonus")
        if !off.exists {
            app.swipeUp()
            settle()
            shot("bonus-code")
            if env["INTERACT"] == "1" {
                let copy = app.buttons["elchi.bonus.copy"]
                if copy.exists && copy.isHittable {
                    copy.tap()
                    waitFor(L("Kod nusxalandi", "Код скопирован"), timeout: 5)
                    shot("bonus-copied")
                }
            }
            app.swipeUp()
            settle()
            shot("bonus-bottom")
        }
        back()
    }

    private func safety() {
        openFromProfile(L("Bloklanganlar va shikoyatlarim", "Блокировки и мои жалобы"))
        waitFor(L("Mening shikoyatlarim", "Мои жалобы"), timeout: 20)
        settle(2)
        shot("safety")
        let unblock = app.buttons[L("Chiqarish", "Разблокировать")].firstMatch
        if env["INTERACT"] == "1", unblock.waitForExistence(timeout: 3) {
            unblock.tap()
            let confirm = app.buttons["elchi.unblock.confirm"]
            XCTAssertTrue(confirm.waitForExistence(timeout: 5))
            settle(0.6)
            shot("safety-unblock-confirm")
            confirm.tap()
            waitFor(L("Blokdan chiqarildi", "Пользователь разблокирован"), timeout: 20)
            shot("safety-unblocked")
        }
        back()
    }

    private func support() {
        drawer("support")
        waitFor(L("Hozircha telefon liniyasi yo'q", "Телефонной линии пока нет"), timeout: 20)
        settle(2)
        shot("support-top")
        if env["INTERACT"] == "1" {
            let field = app.textViews.firstMatch.exists ? app.textViews.firstMatch : app.textFields.firstMatch
            XCTAssertTrue(field.waitForExistence(timeout: 10))
            field.tap()
            field.typeText("abc")
            waitFor(L("Kamida 5 ta belgi", "не менее 5"), timeout: 5)
            shot("support-min-hint")
            for _ in 0..<3 { field.typeText(XCUIKeyboardKey.delete.rawValue) }
            app.swipeDown()
        }
        let all = app.buttons.containing(NSPredicate(format: "label BEGINSWITH %@", L("Hammasi (", "Все ("))).firstMatch
        scrollTo(all, maxSwipes: 4)
        settle()
        shot("support-threads")
        app.swipeUp()
        app.swipeUp()
        settle()
        shot("support-faq")
        guard all.exists else { return }
        scrollTo(all)
        all.tap()
        waitFor(L("Bron sahifasidagi", "на странице брони"), timeout: 20)
        settle()
        shot("threads")
        app.buttons["elchi.bar.refresh"].tap()
        waitFor(L("Yangilandi", "Обновлено"), timeout: 10)
        shot("threads-refreshed")
        app.buttons.containing(NSPredicate(format: "label CONTAINS %@", L("Operator bilan yozishma", "Переписка с оператором"))).firstMatch.tap()
        waitFor(L("Holat", "Статус"), timeout: 20)
        settle()
        shot("thread")
        back()
        back()
    }

    private func notifications() {
        drawer("notifications")
        waitFor(L("Bildirishnomalar", "Уведомления"), timeout: 20)
        settle(2)
        shot("notifications")
    }

    private func settings() {
        drawer("settings")
        waitFor(L("Ilova tilini tanlang", "Выберите язык приложения"), timeout: 20)
        settle()
        shot("settings")
        if env["INTERACT"] == "1" {
            tap(L("Qorong'i", "Тёмная"))
            waitFor(L("Mavzu:", "Тема:"), timeout: 5)
            shot("settings-theme-toast")
            tap(env["THEME"] == "dark" ? L("Qorong'i", "Тёмная") : L("Yorug'", "Светлая"))
            settle(2.5)
        }
        app.swipeUp()
        tap(L("Akkauntni o'chirish", "Удалить аккаунт"))
        waitFor(L("Nima o'chiriladi", "Что удаляется"), timeout: 20)
        settle()
        shot("delete")
        tap(L("Tushundim", "Понимаю"))
        let submit = app.buttons["elchi.accountDelete.submit"]
        waitEnabled(submit, "submit")
        submit.tap()
        XCTAssertTrue(app.buttons["elchi.accountDelete.confirm"].waitForExistence(timeout: 5), "no confirm dialog")
        settle(0.6)
        shot("delete-confirm")
        // Never on a demo account: "Ortga" closes the dialog.
        let dismiss = app.buttons.matching(identifier: L("Ortga", "Назад"))
        dismiss.element(boundBy: dismiss.count - 1).tap()
        XCTAssertTrue(app.buttons["elchi.accountDelete.confirm"].waitForNonExistence(timeout: 5))
        back()
    }

    private func logout() {
        drawer("settings")
        waitFor(L("Ilova tilini tanlang", "Выберите язык приложения"), timeout: 20)
        app.swipeUp()
        let rows = app.buttons.matching(NSPredicate(format: "label == %@", L("Chiqish", "Выйти")))
        rows.element(boundBy: 0).tap()
        app.buttons["elchi.logout.confirm"].tap()
        waitFor(L("Men mijozman", "Я клиент"), timeout: 20)
        shot("logged-out")
    }

    private func deleteFlow() {
        drawer("settings")
        waitFor(L("Ilova tilini tanlang", "Выберите язык приложения"), timeout: 20)
        app.swipeUp()
        tap(L("Akkauntni o'chirish", "Удалить аккаунт"))
        waitFor(L("Nima o'chiriladi", "Что удаляется"), timeout: 20)
        tap(L("Tushundim", "Понимаю"))
        let submit = app.buttons["elchi.accountDelete.submit"]
        waitEnabled(submit, "submit")
        submit.tap()
        let confirm = app.buttons["elchi.accountDelete.confirm"]
        XCTAssertTrue(confirm.waitForExistence(timeout: 5))
        confirm.tap()
    }

    private func deleteBlocked() {
        deleteFlow()
        waitFor(L("Hozircha o'chirib bo'lmaydi", "Пока удалить нельзя"), timeout: 20)
        let link = app.buttons["elchi.accountDelete.orders"]
        XCTAssertTrue(link.waitForExistence(timeout: 5), "no orders link")
        settle()
        shot("delete-blocked")
        link.tap()
        waitFor(L("Buyurtmalar", "Заказы"), timeout: 20)
        settle(2)
        shot("delete-blocked-orders")
    }

    private func deleteDone() {
        deleteFlow()
        waitFor(L("Akkaunt o'chirildi", "Аккаунт удалён"), timeout: 20)
        shot("delete-done")
    }
}
