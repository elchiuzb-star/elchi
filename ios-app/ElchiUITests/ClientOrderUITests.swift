import XCTest

/// Stage 02 end to end against the running development backend (dev OTP, seeded regions, corridors and parcel
/// catalogue): sign in as a new client -> both places -> the five steps -> published. One screenshot per screen.
/// `-uiTestFakePhoto` swaps the system photo picker (which UI tests cannot drive reliably) for a generated photo;
/// the upload itself is real.
final class ClientOrderUITests: ClientUITestCase {
    private func pickPlace(_ question: String, region: String, district: String?, shot: String) {
        pickPlace(question, region: region, district: district, shots: shot)
    }

    func testPostParcelRequestEndToEnd() {
        launch()
        signInAsClient(phone: Self.runPhone)

        // Home, empty: the button waits for a direction.
        waitFor("Pochta")
        waitMapDrawn()
        snap("10-home-empty")
        XCTAssertFalse(button("Yo'nalishni ko'rish").isEnabled)

        // Drawer: Xabarlar and Profil arrive in later stages and say so.
        app.buttons["Menyu"].tap()
        waitFor("ELCHI")
        waitFor("Keyingi bosqichda")
        snap("14-drawer")
        tap("Bosh sahifa")

        pickPlace("Qayerdan?", region: "Toshkent shahri", district: nil, shot: "pickup")
        pickPlace("Qayerga?", region: "Samarqand viloyati", district: "Samarqand", shot: "dropoff")

        // Direction ready: the server found a route; the leg and corridor are shown.
        waitFor("Taxminiy yo'l vaqti", timeout: 20)
        waitMapDrawn()
        snap("15-home-direction-ready")
        // The same map on the night palette: markers and the road take the dark theme's colours.
        tap("Qorong'i rejim")
        Thread.sleep(forTimeInterval: 1.5)
        snap("15-home-direction-ready-dark")
        tap("Yorug' rejim")
        tap("Yo'nalishni ko'rish")

        // Step 1: the window is prefilled (tomorrow 09:00-18:00); without a price "Saqlash" says what is missing.
        waitFor("Jo'nash oynasi boshlanishi")
        waitFor("Narxni kiriting")
        snap("20-route-summary-incomplete")
        type("120000", into: "Narx (so'm)")
        snap("21-route-summary")
        XCTAssertTrue((app.textFields["Narx (so'm)"].value as? String ?? "").hasPrefix("120"), "price not typed")
        tap("Saqlash")

        // Step 2: a new account has no name; the receiver is typed. The comment carries a phone to be masked (Q43).
        waitFor("Telefon raqamlar taklif qabul qilinmaguncha")
        type("Aziza Karimova", into: "Yuboruvchi ismi")
        type("Dilnoza Rahimova", into: "Qabul qiluvchi ismi")
        type("915552211", into: "Qabul qiluvchi telefon raqami")
        type("Qo'ng'iroq: 901234567", into: "Izoh")
        snap("22-contacts")
        tap("Davom etish")

        // Step 3: type + a size from the server catalogue (dev: synthetic).
        waitFor("Posilka turi")
        tap("Quti")
        tap("Kichik quti")
        snap("23-parcel")
        app.swipeUp()
        snap("23-parcel-policy")
        tap("Davom etish")

        // Step 4: photo (generated in UI tests) uploaded for real.
        waitFor("Posilkani haydovchi ko'rishi uchun")
        snap("24-photo-empty")
        tap("Rasm yuklash")
        tap("Galereyadan tanlash")
        waitFor("Rasm tayyor", timeout: 20)
        snap("25-photo-ready")
        tap("Buyurtmani ko'rib chiqish")

        // Step 5: review and publish.
        waitFor("Buyurtmani tekshiring")
        snap("26-review")
        app.swipeUp()
        snap("26-review-bottom")
        tap("Buyurtmani e'lon qilish")

        waitFor("Haydovchilardan takliflar kutilmoqda", timeout: 25)
        snap("27-success")
        // Stage 03: the orders list, with the new request under "E'lonlarim".
        tap("Buyurtmalarimga o'tish")
        waitFor("E'lonlarim")
        snap("28-orders-after-publish")
    }

    /// Russian + dark theme: the longer language and the other palette on the home, drawer and region screens.
    func testHomeInRussianDarkTheme() {
        launch(locale: "ru", theme: "dark")
        let start = app.buttons.element(boundBy: 0)
        XCTAssertTrue(start.waitForExistence(timeout: 10))
        signInAsClient(phone: Self.runPhone, start: "Начать", next: "Далее", client: "клиент", getCode: "Получить код",
                       home: "Посмотреть направление")
        waitFor("Посылки")
        waitMapDrawn()
        snap("30-ru-dark-home")
        app.buttons["Меню"].tap()
        waitFor("На следующем этапе")
        snap("31-ru-dark-drawer")
        tap("Главная")
        tap("Откуда?")
        waitFor("Сначала выберите регион")
        snap("32-ru-dark-regions")
        tap("Toshkent shahri")
        waitFor("Выбранное место")
        let choose = button("Выбрать это место")
        waitEnabled(choose, "Выбрать это место")
        waitMapDrawn()
        snap("33-ru-dark-point-picker")
    }
}
