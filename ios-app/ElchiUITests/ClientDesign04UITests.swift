import XCTest

/// BOSQICH 04 ("Elchi Bron") on the running development backend, driven by `elchi-dev/ios-design04/run.sh`: the shell
/// moves the booking (`booking.py`, `taxi.py`) between runs; each run opens one booking (`-uiTestOpenBooking`) and does
/// the steps named in `STEPS` (comma separated), saving PNGs as `<TAG>-<step>-…` into `SHOTS`. The client keeps the
/// session the app stored on the first run (`FIRST=1` signs in with `-uiTestSession`, later runs reuse it).
///
/// Steps: `detail` (top, middle, bottom), `call` (the call button: dial or "when it opens"), `chat`, `chatSend`,
/// `track`, `share` (system share sheet or the refusal toast, then the link row), `amend` (tap-to-validate, send,
/// withdraw), `amendAccept` (the driver's proposal), `cancelSheet` (chips, kept), `cancelDo` (a real cancel), `safety`
/// (radio list, block confirmation - never confirmed: unblock does not exist), `safetySend`, `support`, `supportSend`,
/// `rate` (the star card, then send), `rateLater` (the screen with a preselected star, "Keyinroq"), `cash` (Taksi:
/// decide card, contest form, then confirm), `complete` (Taksi "Manzilga yetib keldim"), `code` (Taksi boarding code).
final class ClientDesign04UITests: ClientUITestCase {
    private var env: [String: String] { ProcessInfo.processInfo.environment }
    private var ru: Bool { env["LOCALE"] == "ru" }
    private func L(_ uz: String, _ ru: String) -> String { self.ru ? ru : uz }
    private var tag: String { env["TAG"] ?? "x" }

    private func shot(_ name: String) { snap("\(tag)-\(name)") }

    private func byId(_ id: String, timeout: TimeInterval = 15) -> XCUIElement {
        let element = app.descendants(matching: .any)[id].firstMatch
        XCTAssertTrue(element.waitForExistence(timeout: timeout), "no element '\(id)'")
        return element
    }

    private func scrollTo(_ element: XCUIElement, maxSwipes: Int = 10) {
        var swipes = 0
        while !(element.exists && element.isHittable) && swipes < maxSwipes {
            app.swipeUp()
            swipes += 1
        }
    }

    private func scrollTop() {
        for _ in 0..<4 { app.swipeDown() }
    }

    private func tapId(_ id: String, timeout: TimeInterval = 15) {
        let element = byId(id, timeout: timeout)
        scrollTo(element)
        waitEnabled(element, id)
        element.tap()
    }

    private func back() {
        let button = app.buttons[L("Orqaga", "Назад")].firstMatch
        XCTAssertTrue(button.waitForExistence(timeout: 10), "no back button")
        button.tap()
    }

    /// Back on the detail (its sheet card is the marker).
    private func onDetail() {
        if !app.descendants(matching: .any)["elchi.booking.status"].waitForExistence(timeout: 25) { snap("\(tag)-debug-nodetail") }
        _ = byId("elchi.booking.status", timeout: 2)
        Thread.sleep(forTimeInterval: 1)
    }

    func testTour() {
        var extra = ["-uiTestOpenBooking", env["BOOKING"] ?? ""]
        if env["FIRST"] == "1" { extra += ["-uiTestSession", env["SESSION"] ?? ""] }
        launch(locale: env["LOCALE"] ?? "uz", theme: env["THEME"] ?? "light", reset: env["FIRST"] == "1", extra: extra)
        onDetail()
        // Let the reputation, the receiver, the chat count and the photo arrive.
        Thread.sleep(forTimeInterval: 2.5)
        let steps = (env["STEPS"] ?? "detail").split(separator: ",").map { String($0).trimmingCharacters(in: .whitespaces) }
        for step in steps {
            run(step)
            if app.buttons[L("Orqaga", "Назад")].exists && !app.descendants(matching: .any)["elchi.booking.status"].exists { back() }
            onDetail()
            scrollTop()
        }
    }

    private func run(_ step: String) {
        switch step {
        case "detail": detail()
        case "call": call()
        case "chat": chat(send: false)
        case "chatSend": chat(send: true)
        case "track": track()
        case "share": share()
        case "amend": amend()
        case "amendAccept": amendAccept()
        case "cancelSheet": cancel(confirm: false)
        case "cancelDo": cancel(confirm: true)
        case "safety": safety(send: false)
        case "safetySend": safety(send: true)
        case "support": support(send: false)
        case "supportSend": support(send: true)
        case "rate": rate(send: true)
        case "rateLater": rate(send: false)
        case "cash": cash()
        case "complete": complete()
        default: XCTFail("unknown step \(step)")
        }
    }

    // MARK: Steps

    private func detail() {
        waitMapDrawn()
        shot("detail-1")
        app.swipeUp()
        shot("detail-2")
        app.swipeUp()
        app.swipeUp()
        shot("detail-3")
    }

    private func call() {
        tapId("elchi.booking.call")
        Thread.sleep(forTimeInterval: 0.8)
        shot("call")
        // A dial prompt (phones open) is dismissed; a toast goes by itself.
        let cancel = XCUIApplication(bundleIdentifier: "com.apple.springboard").buttons["Cancel"].firstMatch
        if cancel.waitForExistence(timeout: 2) { cancel.tap() }
    }

    private func chat(send: Bool) {
        tapId("elchi.booking.chat")
        _ = byId("elchi.bar.subtitle", timeout: 15)
        Thread.sleep(forTimeInterval: 2)
        shot("chat")
        if send {
            let field = app.textFields[L("Xabar yozing", "Напишите сообщение")].firstMatch.exists
                ? app.textFields[L("Xabar yozing", "Напишите сообщение")].firstMatch
                : app.textViews.firstMatch
            if field.waitForExistence(timeout: 5) {
                field.tap()
                for character in L("Salom, posilka tayyor. Telefonim 90 123 45 67", "Здравствуйте, мой номер 90 123 45 67") { field.typeText(String(character)) }
                tap(L("Yuborish", "Отправить"))
                Thread.sleep(forTimeInterval: 2.5)
                shot("chat-sent")
            }
        }
        back()
    }

    private func track() {
        tapId("elchi.booking.mapHero")
        _ = waitFor(L("Holat kuzatuvi", "Ход выполнения"), timeout: 15)
        Thread.sleep(forTimeInterval: 4)
        waitMapDrawn(timeout: 10)
        shot("track")
        app.swipeUp()
        shot("track-2")
        if env["TRACK_WAIT"] == "1" {
            // GPS stopped in the shell: the point ages on the phone - delayed, then lost.
            waitFor(L("Joylashuv kechikmoqda", "Геопозиция запаздывает"), timeout: 120)
            shot("track-delayed")
            waitFor(L("aloqa uzilgan", "потеряна"), timeout: 150)
            shot("track-lost")
        }
        tapId("elchi.bar.refresh")
        Thread.sleep(forTimeInterval: 0.6)
        shot("track-refreshed")
        back()
    }

    private func share() {
        tapId("elchi.bar.share")
        let sheet = app.otherElements["ActivityListView"].firstMatch
        if sheet.waitForExistence(timeout: 12) {
            Thread.sleep(forTimeInterval: 1.5)
            shot("share-sheet")
            let close = sheet.buttons["Close"].firstMatch
            if close.exists { close.tap() } else { app.swipeDown(velocity: .fast) }
            let link = byId("elchi.booking.link", timeout: 10)
            scrollTo(link)
            shot("share-link-row")
        } else {
            shot("share-refused")
        }
    }

    private func amend() {
        tapId("elchi.booking.amend")
        _ = waitFor(L("Hozirgi kelishuv", "Текущая договорённость"), timeout: 15)
        Thread.sleep(forTimeInterval: 1.5)
        shot("amend")
        tapId("elchi.amend.submit")
        shot("amend-error-price")
        let price = app.textFields.element(boundBy: 0)
        price.tap()
        for character in "125000" { price.typeText(String(character)) }
        let reason = app.textFields.element(boundBy: 1)
        reason.tap()
        reason.typeText("ab")
        tapId("elchi.amend.submit")
        shot("amend-error-reason")
        reason.tap()
        for character in L(" - yuk og'irroq", " - груз тяжелее") { reason.typeText(String(character)) }
        tapId("elchi.amend.submit")
        let withdraw = byId("elchi.amend.withdraw", timeout: 20)
        scrollTop()
        shot("amend-sent")
        scrollTo(withdraw)
        withdraw.tap()
        Thread.sleep(forTimeInterval: 2)
        shot("amend-withdrawn")
        back()
    }

    private func amendAccept() {
        tapId("elchi.booking.amend")
        let accept = byId("elchi.amend.accept", timeout: 20)
        scrollTo(accept)
        shot("amend-driver")
        accept.tap()
        Thread.sleep(forTimeInterval: 2)
        scrollTop()
        shot("amend-accepted")
        back()
    }

    private func cancel(confirm: Bool) {
        tapId("elchi.booking.cancel")
        _ = byId("elchi.cancel.reason.plans_changed", timeout: 10)
        Thread.sleep(forTimeInterval: 0.8)
        shot("cancel-sheet")
        tapId(confirm ? "elchi.cancel.reason.plans_changed" : "elchi.cancel.reason.found_other_option")
        shot("cancel-chip")
        if confirm {
            tapId("elchi.cancel.confirm")
            _ = byId("elchi.booking.notice", timeout: 20)
            Thread.sleep(forTimeInterval: 0.5)
            shot("cancelled")
        } else {
            tapId("elchi.cancel.keep")
        }
    }

    private func safety(send: Bool) {
        tapId("elchi.booking.safety")
        _ = byId("elchi.safety.reason.off_platform_contact", timeout: 10)
        shot("safety")
        tapId("elchi.safety.reason.price_pressure")
        if send {
            tapId("elchi.safety.send")
            Thread.sleep(forTimeInterval: 2)
            shot("safety-sent")
        }
        tapId("elchi.safety.block")
        _ = byId("elchi.safety.blockBack", timeout: 5)
        shot("safety-block")
        tapId("elchi.safety.blockBack")
        back()
    }

    private func support(send: Bool) {
        tapId("elchi.bar.support")
        _ = waitFor(L("Operator bilan yozishma", "Переписка с оператором"), timeout: 15)
        Thread.sleep(forTimeInterval: 2)
        shot("support")
        if send {
            let field = app.textFields.firstMatch.exists ? app.textFields.firstMatch : app.textViews.firstMatch
            field.tap()
            for character in L("Bekatni aniqlashtirishda yordam kerak", "Нужна помощь с остановкой") { field.typeText(String(character)) }
            tap(L("Yuborish", "Отправить"))
            Thread.sleep(forTimeInterval: 3)
            shot("support-sent")
        }
        back()
    }

    private func rate(send: Bool) {
        let card = byId("elchi.booking.rateCard", timeout: 15)
        scrollTo(card)
        shot("rate-card")
        app.buttons[L("4 yulduz", "Звёзд: 4")].firstMatch.tap()
        _ = byId("elchi.rating.submit", timeout: 10)
        Thread.sleep(forTimeInterval: 0.6)
        shot("rate")
        if send {
            tapId("elchi.rating.submit")
            onDetail()
            Thread.sleep(forTimeInterval: 0.5)
            shot("rated-toast")
            app.swipeUp()
            app.swipeUp()
            shot("rated")
        } else {
            back()
        }
    }

    private func cash() {
        let ack = byId("elchi.cash.acknowledge", timeout: 20)
        scrollTo(ack)
        shot("cash-decide")
        tapId("elchi.cash.contest")
        _ = byId("elchi.cash.contestSend", timeout: 5)
        shot("cash-contest-form")
        tap(L("Bekor qilish", "Отмена"))
        tapId("elchi.cash.acknowledge")
        Thread.sleep(forTimeInterval: 2)
        shot("cash-confirmed")
    }

    private func complete() {
        tapId("elchi.taxi.complete")
        _ = byId("elchi.taxi.completeConfirm", timeout: 5)
        shot("complete-dialog")
        tapId("elchi.taxi.completeConfirm")
        Thread.sleep(forTimeInterval: 2.5)
        scrollTop()
        shot("completed")
    }
}
