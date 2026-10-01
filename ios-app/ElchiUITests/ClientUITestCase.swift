import XCTest

/// What the client flows' UI tests share: launching with the test switches, screenshots, waiting for labels,
/// signing in a client and posting one parcel request through the app (Stage 02), against the running development
/// backend (dev OTP, seeded regions, corridors and parcel catalogue).
@MainActor
class ClientUITestCase: XCTestCase {
    lazy var app = XCUIApplication()

    /// `reset` starts from a first install (no session); without it the previous test's client is still signed in.
    /// `extra` = more switches (`-uiTestExpireSession`).
    func launch(locale: String = "uz", theme: String? = nil, reset: Bool = true, extra: [String] = []) {
        continueAfterFailure = false
        app.launchArguments = (reset ? ["-uiTestReset"] : []) + ["-uiTestFakePhoto", "-elchi.locale", locale]
            + (theme.map { ["-elchi.theme", $0] } ?? []) + extra
        app.launch()
    }

    func snap(_ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    /// Lets the map finish drawing before a screenshot: its loading spinner goes once the tiles are in (the picker's
    /// centre pin appears with them). Not an assertion - after 30 s without tiles the placeholder takes over.
    func waitMapDrawn(timeout: TimeInterval = 35) {
        let loading = app.descendants(matching: .any)["elchi.map.loading"]
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: loading)
        _ = XCTWaiter().wait(for: [gone], timeout: timeout)
    }

    func button(_ label: String, timeout: TimeInterval = 15) -> XCUIElement {
        let exact = app.buttons[label].firstMatch
        if exact.waitForExistence(timeout: 2) { return exact }
        let partial = app.buttons.containing(NSPredicate(format: "label BEGINSWITH %@", label)).firstMatch
        XCTAssertTrue(partial.waitForExistence(timeout: timeout), "no button '\(label)'")
        return partial
    }

    func tap(_ label: String, timeout: TimeInterval = 15) {
        let element = button(label, timeout: timeout)
        waitEnabled(element, label)
        element.tap()
    }

    func waitEnabled(_ element: XCUIElement, _ label: String, timeout: TimeInterval = 20) {
        let enabled = expectation(for: NSPredicate(format: "enabled == true"), evaluatedWith: element)
        XCTAssertEqual(XCTWaiter().wait(for: [enabled], timeout: timeout), .completed, "'\(label)' stays disabled")
    }

    @discardableResult
    func waitFor(_ text: String, timeout: TimeInterval = 15) -> XCUIElement {
        let match = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", text)).firstMatch
        XCTAssertTrue(match.waitForExistence(timeout: timeout), "no text '\(text)'")
        return match
    }

    func waitGone(_ text: String, timeout: TimeInterval = 15) {
        let match = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", text)).firstMatch
        let gone = expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: match)
        XCTAssertEqual(XCTWaiter().wait(for: [gone], timeout: timeout), .completed, "'\(text)' is still shown")
    }

    func field(_ label: String) -> XCUIElement {
        let field = app.textFields[label].firstMatch.exists ? app.textFields[label].firstMatch : app.textViews[label].firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 10), "no field '\(label)'")
        return field
    }

    func type(_ text: String, into label: String) {
        let field = field(label)
        field.tap()
        for character in text { field.typeText(String(character)) }
    }

    /// Clears a field that the app formats as it is typed, then types. The cursor goes to the end first, and each
    /// backspace is its own keystroke: the field rewrites itself after every one, and a burst can lose keys.
    func replace(_ label: String, with text: String) {
        let field = field(label)
        field.coordinate(withNormalizedOffset: CGVector(dx: 0.95, dy: 0.5)).tap()
        let current = field.value as? String ?? ""
        for _ in 0..<(current.count + 1) { field.typeText(XCUIKeyboardKey.delete.rawValue) }
        XCTAssertTrue((field.value as? String ?? "").filter(\.isNumber).isEmpty, "field '\(label)' not cleared")
        for character in text { field.typeText(String(character)) }
    }

    /// A phone unique to this run (`93` + 7 digits) unless the shell passed one (`TEST_RUNNER_ELCHI_PHONE`), so a
    /// helper script can find the same client between test phases.
    static var runPhone: String {
        if let phone = ProcessInfo.processInfo.environment["ELCHI_PHONE"], phone.count == 9 { return phone }
        return "93" + String(format: "%07d", Int(Date().timeIntervalSince1970 * 10) % 10_000_000)
    }

    /// Splash -> onboarding -> client -> phone -> dev OTP.
    func signInAsClient(phone: String, start: String = "Boshlash", next: String = "Keyingisi", client: String = "Men mijozman",
                        getCode: String = "Kod olish", home: String = "Yo'nalishni ko'rish") {
        tap(start)
        tap(next)
        tap(next)
        tap(start)
        app.buttons.containing(NSPredicate(format: "label CONTAINS %@", client)).firstMatch.tap()
        let phoneField = app.textFields.firstMatch
        XCTAssertTrue(phoneField.waitForExistence(timeout: 10))
        phoneField.tap()
        // One digit at a time: the field reformats as it goes and a fast burst can drop a keystroke.
        for digit in phone { phoneField.typeText(String(digit)) }
        tap(getCode)
        XCTAssertTrue(app.textFields.firstMatch.waitForExistence(timeout: 10))
        app.textFields.firstMatch.typeText("1234")
        XCTAssertTrue(app.buttons[home].firstMatch.waitForExistence(timeout: 20) || app.staticTexts[home].firstMatch.waitForExistence(timeout: 5))
    }

    /// Region -> (district) -> point, accepting the district centre (or the map centre when a map is shown).
    func pickPlace(_ question: String, region: String, district: String?, shots: String? = nil) {
        tap(question)
        waitFor("Avval hududni tanlang")
        if shots == "pickup" { snap("11-location-regions") }
        tap(region)
        if let district {
            waitFor("Tumanni tanlang")
            if shots != nil { snap("12-location-districts") }
            tap(district)
        }
        waitFor("Tanlangan joy")
        let choose = button("Shu joyni tanlash")
        waitEnabled(choose, "Shu joyni tanlash")
        if let shots {
            waitMapDrawn()
            snap("13-point-picker-\(shots)")
        }
        choose.tap()
    }

    /// Home -> both places -> the five steps -> published (Tashkent city -> Samarqand, tomorrow 09:00-18:00).
    func postParcelRequest(price: String) {
        pickPlace("Qayerdan?", region: "Toshkent shahri", district: nil)
        pickPlace("Qayerga?", region: "Samarqand viloyati", district: "Samarqand")
        waitFor("Taxminiy yo'l vaqti", timeout: 20)
        tap("Yo'nalishni ko'rish")
        waitFor("Jo'nash oynasi boshlanishi")
        type(price, into: "Narx (so'm)")
        tap("Saqlash")
        waitFor("Telefon raqamlar taklif qabul qilinmaguncha")
        type("Aziza Karimova", into: "Yuboruvchi ismi")
        type("Dilnoza Rahimova", into: "Qabul qiluvchi ismi")
        type("915552211", into: "Qabul qiluvchi telefon raqami")
        type("Mo'rt narsa", into: "Izoh")
        tap("Davom etish")
        waitFor("Posilka turi")
        tap("Quti")
        tap("Kichik quti")
        tap("Davom etish")
        tap("Rasm yuklash")
        tap("Galereyadan tanlash")
        waitFor("Rasm tayyor", timeout: 20)
        tap("Buyurtmani ko'rib chiqish")
        waitFor("Buyurtmani tekshiring")
        tap("Buyurtmani e'lon qilish")
        waitFor("Haydovchilardan takliflar kutilmoqda", timeout: 25)
    }
}
