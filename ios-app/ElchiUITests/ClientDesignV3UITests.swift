import XCTest

/// Design v3 on the client (Profil v3, BOSQICH 10 "Arxiv va Holatlar") against the running development backend, driven
/// by `elchi-dev/ios-v3-client/run.sh`: each run does the steps in `STEPS` (comma separated) and saves PNGs as
/// `<TAG>-<step>-…` into `SHOTS`. `FIRST=1` starts from a fresh install signed in with `-uiTestSession` (`SESSION`).
/// The client's v1 orders come from `legacy.py` (ids in `LEGACY_*`).
final class ClientDesignV3UITests: ClientUITestCase {
    private var env: [String: String] { ProcessInfo.processInfo.environment }
    private var ru: Bool { env["LOCALE"] == "ru" }
    private func L(_ uz: String, _ ru: String) -> String { self.ru ? ru : uz }
    private var tag: String { env["TAG"] ?? "x" }
    private func shot(_ name: String) { snap("\(tag)-\(name)") }
    private func id(_ name: String) -> String { env["LEGACY_\(name)"] ?? "0" }

    private func scrollTo(_ element: XCUIElement, maxSwipes: Int = 10) {
        var swipes = 0
        while !(element.exists && element.isHittable) && swipes < maxSwipes {
            app.swipeUp()
            swipes += 1
        }
    }

    private func drawer(_ section: String) {
        let menu = app.buttons[L("Menyu", "Меню")].firstMatch
        XCTAssertTrue(menu.waitForExistence(timeout: 25), "no menu button")
        menu.tap()
        let row = app.buttons["elchi.drawer.\(section)"]
        XCTAssertTrue(row.waitForExistence(timeout: 10), "no drawer row '\(section)'")
        settle(0.6)
        if section == "archive" { shot("drawer") }
        row.tap()
    }

    private func back() {
        let button = app.buttons[L("Orqaga", "Назад")].firstMatch
        XCTAssertTrue(button.waitForExistence(timeout: 10), "no back button")
        button.tap()
    }

    private func settle(_ seconds: TimeInterval = 1.2) { Thread.sleep(forTimeInterval: seconds) }

    private func detail(_ key: String) {
        launch(locale: env["LOCALE"] ?? "uz", theme: env["THEME"] ?? "light", reset: false, extra: ["-uiTestOpenLegacy", id(key)])
        waitFor(L("Arxiv", "Архив"), timeout: 25)
        settle(1.5)
    }

    func testTour() {
        var extra: [String] = []
        if env["FIRST"] == "1" { extra += ["-uiTestSession", env["SESSION"] ?? ""] }
        launch(locale: env["LOCALE"] ?? "uz", theme: env["THEME"] ?? "light", reset: env["FIRST"] == "1", extra: extra)
        for step in (env["STEPS"] ?? "").split(separator: ",").map(String.init) {
            switch step {
            case "profile": profile()
            case "bonus": bonus()
            case "support": support()
            case "threads": threads()
            case "delete": deleteCheck()
            case "archive": archive()
            case "orders": ordersRow()
            case "details": details()
            case "map": mapSheet()
            case "bids": bids()
            case "sheets": sheets()
            case "rate": rate()
            case "report": report()
            case "notFound": notFound()
            default: XCTFail("unknown step \(step)")
            }
        }
    }

    // MARK: Profil v3

    private func profile() {
        drawer("profile")
        waitFor(L("Mijoz akkaunti", "Аккаунт клиента"), timeout: 20)
        app.swipeUp()
        settle()
        shot("profile-actions")
        XCTAssertFalse(app.buttons[L("Buyurtmalarim", "Мои заказы")].exists, "Buyurtmalarim is still a profile row")
    }

    private func bonus() {
        drawer("profile")
        let row = button(L("Bonuslar va taklif kodi", "Бонусы и код приглашения"))
        scrollTo(row)
        row.tap()
        settle(2.5)
        shot("bonus")
        app.swipeUp()
        settle()
        shot("bonus-bottom")
        back()
    }

    private func support() {
        drawer("support")
        waitFor(L("Operator ilova ichida javob beradi", "Оператор ответит прямо в приложении"), timeout: 20)
        settle(2)
        shot("support-top")
        app.swipeUp()
        app.swipeUp()
        settle()
        shot("support-faq")
    }

    private func threads() {
        drawer("profile")
        let row = button(L("Murojaatlarim", "Мои обращения"))
        scrollTo(row)
        row.tap()
        settle(2.5)
        shot("threads")
        let thread = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", L("Operator bilan yozishma", "Переписка с оператором"))).firstMatch
        if thread.waitForExistence(timeout: 5) {
            thread.tap()
            waitFor(L("Holat", "Статус"), timeout: 20)
            settle(1.5)
            shot("thread")
            back()
        }
        back()
    }

    private func deleteCheck() {
        drawer("settings")
        let row = button(L("Akkauntni o'chirish", "Удалить аккаунт"))
        scrollTo(row)
        row.tap()
        waitFor(L("Akkauntim o'chirilsin", "Удалить мой аккаунт"), timeout: 15)
        settle()
        shot("delete-check")
        back()
    }

    // MARK: Arxiv (BOSQICH 10)

    private func archive() {
        drawer("archive")
        waitFor(L("boshlanganlarini shu yerda yakunlash mumkin", "начатые можно завершить здесь"), timeout: 20)
        settle(2)
        shot("archive-list")
        app.buttons["elchi.legacy.filter.completed"].tap()
        settle(1.5)
        shot("archive-filter-completed")
        app.buttons["elchi.legacy.filter.cancelled"].tap()
        settle(1)
        shot("archive-filter-cancelled")
        app.buttons["elchi.legacy.filter.disputed"].tap()
        settle(1)
        shot("archive-filter-disputed-empty")
        app.buttons["elchi.legacy.filter.all"].tap()
    }

    private func ordersRow() {
        drawer("orders")
        let row = app.buttons["elchi.orders.legacyRow"]
        scrollTo(row, maxSwipes: 15)
        XCTAssertTrue(row.exists, "no 'Eski buyurtmalar' row")
        settle()
        shot("orders-legacy-row")
        row.tap()
        waitFor(L("Eski buyurtmalar", "Старые заказы"), timeout: 15)
        settle(1.5)
        shot("archive-from-orders")
        back()
    }

    private func details() {
        for key in ["BIDDING", "ACCEPTED", "TRANSIT", "DELIVERED", "CONFIRMED", "CANCELLED"] {
            detail(key)
            shot("detail-\(key.lowercased())")
            app.swipeUp()
            settle()
            shot("detail-\(key.lowercased())-actions")
        }
    }

    private func mapSheet() {
        detail("ACCEPTED")
        let pill = app.buttons["elchi.legacy.mapPoints"]
        scrollTo(pill)
        pill.tap()
        waitFor(L("Olib ketish joyini Yandex Xaritada ochish", "Открыть место посадки в Яндекс Картах"), timeout: 15)
        waitMapDrawn()
        shot("map-pickup")
        app.buttons[L("Yetkazish", "Куда")].firstMatch.tap()
        waitFor(L("Yetkazish joyini Yandex Xaritada ochish", "Открыть место доставки в Яндекс Картах"), timeout: 10)
        settle()
        shot("map-dropoff")
        app.buttons["elchi.legacy.mapClose"].tap()
        settle()
    }

    private func bids() {
        detail("BIDDING")
        tap(L("Takliflarni ko'rish", "Посмотреть предложения"))
        waitFor(L("so'm", "сум"), timeout: 20)
        settle()
        shot("bids")
        app.buttons.matching(NSPredicate(format: "label == %@", L("Tanlash", "Выбрать"))).firstMatch.tap()
        waitFor(L("Ha, tanlayman", "Да, выбираю"), timeout: 10)
        settle()
        shot("select-sheet")
        app.buttons["elchi.sheet.back"].tap()
    }

    private func sheets() {
        detail("DELIVERED")
        let confirm = button(L("Yetkazilganini tasdiqlash", "Подтвердить доставку"))
        scrollTo(confirm)
        confirm.tap()
        waitFor(L("Posilka yetib keldimi?", "Посылка доставлена?"), timeout: 10)
        settle()
        shot("confirm-sheet")
        app.buttons["elchi.sheet.back"].tap()
        detail("ACCEPTED")
        let cancel = app.buttons[L("Buyurtmani bekor qilish", "Отменить заказ")].firstMatch
        scrollTo(cancel)
        cancel.tap()
        waitFor(L("Ha, bekor qilish", "Да, отменить"), timeout: 10)
        settle()
        shot("cancel-sheet")
        app.buttons["elchi.sheet.back"].tap()
    }

    private func rate() {
        detail("CONFIRMED")
        let rate = button(L("Haydovchini baholash", "Оценить водителя"))
        scrollTo(rate)
        settle()
        shot("detail-confirmed-rate")
        rate.tap()
        waitFor(L("1 dan 5 gacha", "от 1 до 5"), timeout: 10)
        settle()
        shot("rating")
        if env["INTERACT"] == "1" {
            app.buttons[L("4 yulduz", "4 звезды")].firstMatch.tap()
            tap(L("Bahoni yuborish", "Отправить оценку"))
            waitFor(L("Baho berildi", "Оценка поставлена"), timeout: 20)
            settle()
            shot("detail-rated-note")
        } else {
            back()
        }
    }

    private func report() {
        detail("TRANSIT")
        let report = button(L("Muammo haqida xabar berish", "Сообщить о проблеме"))
        scrollTo(report)
        report.tap()
        waitFor(L("Qo'llab-quvvatlash", "Поддержка"), timeout: 15)
        settle(1.5)
        shot("report-opens-support")
        let prefilled = app.descendants(matching: .any).matching(NSPredicate(format: "value BEGINSWITH %@", env["LEGACY_TRANSIT_NUMBER"] ?? "ORD")).firstMatch
        XCTAssertTrue(prefilled.waitForExistence(timeout: 5), "the ticket is not prefilled with the order number")
    }

    private func notFound() {
        launch(locale: env["LOCALE"] ?? "uz", theme: env["THEME"] ?? "light", reset: false, extra: ["-uiTestOpenLegacy", "1"])
        waitFor(L("Ma'lumot topilmadi", "Данные не найдены"), timeout: 25)
        waitFor(L("Havola eskirgan", "Ссылка устарела"), timeout: 5)
        settle()
        shot("not-found")
    }
}
