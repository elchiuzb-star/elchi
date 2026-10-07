import XCTest

/// Stage 06 against the running development backend, in phases the shell drives (scratchpad `ios-s06/phase.sh`). The
/// shell makes the client's v1 orders with `legacy.py` first and passes their ids (`TEST_RUNNER_LEGACY_*`), the client's
/// phone and a fresh access token for the one race the app cannot make by itself.
///
/// 0. `test0_SignIn` - the Stage 04/05 client signs in.
/// 1. `test1_ListAndSelect` - the list pages 3 v1 rows at a time; a bidding order -> bids -> "Tanlash" -> the driver
///    and the phone.
/// 2. `test2_PublishedCancel` - no bids yet; cancel through the confirm sheet -> the list with the banner.
/// 3. `test3_AcceptedMap` - the driver card with the phone, the map sheet, "open in Yandex" leaves for Safari.
/// 4. `test4_TransitReport` - "Muammo haqida xabar berish" opens Yordam with a ticket naming the order (Q141; the v1
///    dispute form is gone, BOSQICH 10).
/// 5. `test5_DeliveredConfirmRate` - confirm sheet -> rating -> sent -> confirmed.
/// 6. `test6_NotFound` - someone else's order.
/// 7. `test7_ErrorBanner` - the driver is chosen behind the app's back; "Tanlash" then says the bids are closed.
/// 8. `test8_Offline` - no connection: the banner and the detail's failed state.
/// 9. `test9_UzbekDark`, `testA_RussianLight` - the screens in the other theme and language.
final class ClientLegacyUITests: ClientUITestCase {
    private var env: [String: String] { ProcessInfo.processInfo.environment }

    private func id(_ name: String) -> Int {
        guard let value = env["LEGACY_\(name)"].flatMap(Int.init) else {
            XCTFail("LEGACY_\(name) not set")
            return 0
        }
        return value
    }

    // MARK: Helpers

    private func menu(_ locale: String = "uz") {
        let button = app.buttons[locale == "ru" ? "Меню" : "Menyu"].firstMatch
        XCTAssertTrue(button.waitForExistence(timeout: 20), "no menu button")
        button.tap()
    }

    private func openOrders(_ locale: String = "uz") {
        menu(locale)
        let row = app.buttons["elchi.drawer.orders"]
        XCTAssertTrue(row.waitForExistence(timeout: 10), "no orders row")
        row.tap()
    }

    /// Buyurtmalar -> "Eski buyurtmalar (N)" -> the archive list, scrolled to a v1 row (the next page loads as the end
    /// comes on screen), opened.
    private func openLegacy(_ orderId: Int, snapAs: String? = nil) {
        let archive = app.buttons["elchi.orders.legacyRow"]
        var down = 0
        while !(archive.exists && archive.isHittable) && down < 30 {
            app.swipeUp()
            down += 1
        }
        if archive.exists { archive.tap() }
        let row = app.buttons["elchi.legacy.\(orderId)"]
        var swipes = 0
        while !(row.exists && row.isHittable) && swipes < 30 {
            app.swipeUp()
            swipes += 1
        }
        XCTAssertTrue(row.exists, "no v1 row \(orderId)")
        if let snapAs { snap(snapAs) }
        row.tap()
    }

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

    private func sheetConfirm() {
        let confirm = app.buttons["elchi.sheet.confirm"]
        XCTAssertTrue(confirm.waitForExistence(timeout: 10), "no confirm sheet")
        confirm.tap()
    }

    private func banner(_ text: String, timeout: TimeInterval = 15) {
        let strip = app.descendants(matching: .any)["elchi.banner"]
        XCTAssertTrue(strip.waitForExistence(timeout: timeout), "no banner")
        XCTAssertTrue((strip.label).contains(text), "banner says '\(strip.label)', not '\(text)'")
    }

    private func detail(_ orderId: Int, locale: String = "uz", theme: String = "light") {
        launch(locale: locale, theme: theme, reset: false, extra: ["-uiTestOpenLegacy", "\(orderId)"])
        waitFor(locale == "ru" ? "Архив" : "Arxiv", timeout: 25)
    }

    // MARK: Phases

    func test0_SignIn() {
        launch()
        signInAsClient(phone: Self.runPhone)
    }

    func test1_ListAndSelect() {
        launch(theme: "light", reset: false, extra: ["-uiTestLegacyPage", "3"])
        openOrders()
        waitFor("Buyurtmalar", timeout: 20)
        openLegacy(id("BIDDING"), snapAs: "01-orders-legacy")
        waitFor("Arxiv: bu buyurtma eski tizimda yaratilgan.", timeout: 20)
        waitFor("Takliflar bor")
        snap("02-detail-bidding")
        tap("Takliflarni ko'rish")
        waitFor("Haydovchi takliflari")
        waitFor("so'm", timeout: 20)
        snap("03-bids")
        app.buttons.matching(NSPredicate(format: "label == %@", "Tanlash")).firstMatch.tap()
        waitFor("Haydovchini tanlaysizmi?")
        snap("04-select-confirm")
        sheetConfirm()
        banner("Haydovchi tanlandi")
        waitFor("Haydovchi tanlangan", timeout: 20)
        waitFor("Qo'ng'iroq qilish")
        snap("05-detail-accepted-after-select")
        // The oldest of this client's v1 orders sits on a later page: reaching it means the list paged.
        tap("Orqaga")
        openLegacy(id("OLDEST"), snapAs: "06-orders-paged-to-oldest")
        waitFor("Arxiv", timeout: 20)
    }

    func test2_PublishedCancel() {
        detail(id("PUBLISHED"))
        waitFor("E'lon qilingan")
        snap("10-detail-published")
        tap("Takliflarni ko'rish")
        waitFor("Hozircha takliflar yo'q", timeout: 20)
        snap("11-bids-empty")
        tap("Orqaga")
        scrollTap("Buyurtmani bekor qilish")
        waitFor("Buyurtmani bekor qilasizmi?")
        snap("12-cancel-confirm")
        sheetConfirm()
        banner("Buyurtma bekor qilindi")
        waitFor("Eski buyurtmalar", timeout: 20)
        snap("13-list-after-cancel")
        detail(id("PUBLISHED"))
        waitFor("Bekor qilingan", timeout: 20)
        snap("14-detail-cancelled")
    }

    func test3_AcceptedMap() {
        detail(id("ACCEPTED"))
        waitFor("Haydovchi tanlangan")
        waitFor("Qo'ng'iroq qilish")
        snap("20-detail-accepted")
        app.swipeUp()
        snap("21-detail-accepted-actions")
        scrollTap("Xarita nuqtalari")
        waitFor("Olib ketish joyini Yandex Xaritada ochish")
        waitMapDrawn()
        snap("22-map-sheet")
        tap("Olib ketish joyini Yandex Xaritada ochish")
        let safari = XCUIApplication(bundleIdentifier: "com.apple.mobilesafari")
        XCTAssertTrue(safari.wait(for: .runningForeground, timeout: 20), "the Yandex link did not open outside the app")
        sleep(3)
        let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        shot.name = "23-yandex-opened"
        shot.lifetime = .keepAlways
        add(shot)
        let address = safari.textFields.firstMatch.exists ? safari.textFields.firstMatch : safari.buttons["Address"]
        let note = XCTAttachment(string: "Safari address: \(address.value as? String ?? address.label)")
        note.name = "yandex-url"
        note.lifetime = .keepAlways
        add(note)
    }

    func test4_TransitReport() {
        detail(id("TRANSIT"))
        waitFor("Yo'lda")
        snap("30-detail-in-transit")
        scrollTap("Muammo haqida xabar berish")
        waitFor("Qo'llab-quvvatlash", timeout: 15)
        snap("31-report-opens-support")
    }

    func test5_DeliveredConfirmRate() {
        detail(id("DELIVERED"))
        waitFor("Yetkazildi")
        snap("40-detail-delivered")
        scrollTap("Yetkazilganini tasdiqlash")
        waitFor("Posilka yetib keldimi?")
        snap("41-confirm-delivery")
        sheetConfirm()
        banner("Buyurtma tasdiqlandi")
        waitFor("1 dan 5 gacha baho bering", timeout: 20)
        snap("42-rating-after-confirm")
        app.buttons["5 yulduz"].firstMatch.tap()
        type("Rahmat, o'z vaqtida", into: "Izoh qoldiring")
        app.swipeDown()
        snap("43-rating-filled")
        tap("Bahoni yuborish")
        banner("Baho yuborildi")
        waitFor("Tasdiqlandi", timeout: 20)
        snap("44-detail-confirmed-rated")
    }

    func test6_NotFound() {
        launch(theme: "light", reset: false, extra: ["-uiTestOpenLegacy", "1"])
        waitFor("Ma'lumot topilmadi", timeout: 25)
        snap("50-not-found")
    }

    /// The driver is chosen through the API while the bids screen is open; the app's own "Tanlash" is then refused
    /// (`ORDER_INVALID_STATUS`) and says the order changed in a standing error banner.
    func test7_ErrorBanner() async throws {
        let orderId = id("RACE")
        detail(orderId)
        tap("Takliflarni ko'rish")
        waitFor("so'm", timeout: 20)
        try await selectBehindTheApp(orderId)
        app.buttons.matching(NSPredicate(format: "label == %@", "Tanlash")).element(boundBy: 1).tap()
        sheetConfirm()
        banner("holati shu orada")
        snap("60-banner-error")
        sleep(5) // an error stays past the 4 s that success lasts
        banner("holati shu orada")
        snap("61-banner-error-stays")
    }

    func test8_Offline() {
        launch(theme: "light", reset: false, extra: ["-uiTestOffline"])
        openOrders()
        banner("Internet aloqasi yo'q", timeout: 30)
        snap("70-banner-offline-list")
        launch(theme: "light", reset: false, extra: ["-uiTestOffline", "-uiTestOpenLegacy", "\(id("ACCEPTED"))"])
        banner("Internet aloqasi yo'q", timeout: 30)
        snap("71-banner-offline-detail")
    }

    func test9_UzbekDark() { themed(locale: "uz", theme: "dark", prefix: "8") }

    func testA_RussianLight() { themed(locale: "ru", theme: "light", prefix: "9") }

    private func themed(locale: String, theme: String, prefix: String) {
        let ru = locale == "ru"
        launch(locale: locale, theme: theme, reset: false)
        openOrders(locale)
        openLegacy(id("BIDDING2"), snapAs: "\(prefix)0-\(locale)-\(theme)-orders")
        waitFor(ru ? "Архив" : "Arxiv", timeout: 20)
        snap("\(prefix)1-\(locale)-\(theme)-detail-bidding")
        tap(ru ? "Посмотреть предложения" : "Takliflarni ko'rish")
        waitFor(ru ? "сум" : "so'm", timeout: 20)
        snap("\(prefix)2-\(locale)-\(theme)-bids")
        for (key, name) in [("ACCEPTED2", "accepted"), ("TRANSIT2", "in-transit"), ("DELIVERED2", "delivered"),
                            ("CONFIRMED", "confirmed"), ("CANCELLED", "cancelled"), ("DISPUTED", "disputed")] {
            detail(id(key), locale: locale, theme: theme)
            sleep(1)
            snap("\(prefix)3-\(locale)-\(theme)-detail-\(name)")
        }
        detail(id("ACCEPTED2"), locale: locale, theme: theme)
        scrollTap(ru ? "Точки на карте" : "Xarita nuqtalari")
        waitMapDrawn()
        snap("\(prefix)4-\(locale)-\(theme)-map-sheet")
        detail(id("TRANSIT2"), locale: locale, theme: theme)
        scrollTap(ru ? "Сообщить о проблеме" : "Muammo haqida xabar berish")
        sleep(1)
        snap("\(prefix)5-\(locale)-\(theme)-report-support")
        detail(id("DELIVERED2"), locale: locale, theme: theme)
        scrollTap(ru ? "Подтвердить доставку" : "Yetkazilganini tasdiqlash")
        sleep(1)
        snap("\(prefix)6-\(locale)-\(theme)-confirm-sheet")
        detail(id("CONFIRMED"), locale: locale, theme: theme)
        scrollTap(ru ? "Оценить водителя" : "Haydovchini baholash")
        sleep(1)
        snap("\(prefix)7-\(locale)-\(theme)-rating")
        launch(locale: locale, theme: theme, reset: false, extra: ["-uiTestOpenLegacy", "1"])
        waitFor(ru ? "Данные не найдены" : "Ma'lumot topilmadi", timeout: 25)
        snap("\(prefix)8-\(locale)-\(theme)-not-found")
    }

    // MARK: Backend (the one race)

    private func selectBehindTheApp(_ orderId: Int) async throws {
        let token = try XCTUnwrap(env["LEGACY_TOKEN"], "LEGACY_TOKEN not set")
        let base = "http://127.0.0.1:8000/api/v1/client/orders/\(orderId)"
        var list = URLRequest(url: URL(string: "\(base)/bids")!)
        list.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (data, _) = try await URLSession.shared.data(for: list)
        let json = try XCTUnwrap(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        let bids = try XCTUnwrap(json["data"] as? [[String: Any]])
        let bidId = try XCTUnwrap(bids.first?["id"] as? Int)
        var select = URLRequest(url: URL(string: "\(base)/select-driver")!)
        select.httpMethod = "POST"
        select.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        select.setValue("application/json", forHTTPHeaderField: "Content-Type")
        select.httpBody = Data("{\"bid_id\":\(bidId)}".utf8)
        let (_, response) = try await URLSession.shared.data(for: select)
        XCTAssertEqual((response as? HTTPURLResponse)?.statusCode, 200, "select-driver behind the app failed")
    }
}
