import XCTest

/// Stage 04 end to end against the running development backend, in phases the shell drives with `booking.py`
/// (run each with `-only-testing:ElchiUITests/ClientBookingUITests/<phase>`, the same `TEST_RUNNER_ELCHI_PHONE` for
/// all; see scratchpad `ios-s04/run_all.sh`):
///
/// 0. `test0_SignIn` - a new client signs in (the helper then logs in as the same phone).
///    Shell: `booking.py new --driver 1011 --client +998<phone>` (a confirmed booking), `board` is not run yet.
/// 1. `test1_Confirmed` - orders -> booking detail (driver card, reputation, masked plate, hidden phone, fare, parcel,
///    receiver, photo), a recipient link, the cancel sheet (not confirmed), an amendment sent and withdrawn, chat
///    (text, quick reply, masked contacts), support chat opened, a safety report, the block confirmation (not blocked).
///    Shell: `driver-amend`, then in the background `driver-say` (text + quick reply) and `operator-reply`.
/// 2. `test2_DriverAndOperator` - the driver's message arrives by polling in the open chat, the driver's amendment is
///    accepted, the operator's reply arrives in the open support chat. `test2b_RussianDark`, `test2c_UzbekDark`,
///    `test2d_SupportReply` (a follow-up; shell `operator-reply` ~50 s in, the answer arrives by polling).
///    Shell: `board`.
/// 3. `test3_Boarded` - awaiting pickup: full plate, no amendment, live location not yet ("olib ketilgandan keyin").
///    Shell: `depart`, `gps --seconds 30` in the background for `test4c_RuDarkLive`, then `gps --seconds 45` for 4.
/// 4. `test4_InTransit` - phone and "Aloqa ochiq", tracking fresh, then delayed and lost after GPS stops.
///    Shell: `deliver`, `complete`.
/// 5. `test5_CompletedRate` - completed: the ladder done, rating sent -> "Baho berildi".
///    Shell: `trip-complete`, `new` again (a spare booking).
/// 6. `test6_CancelSpare` - a real cancel through the sheet.
///    Shell: the spare trip cancelled by the driver.
/// 7. `test7_PostRequest` + shell `offers.py offer` + `test7b_AcceptLandsInChat` - accept goes to the booking's
///    detail with its chat open (Q100); back = detail, back again = the orders list.
/// 8. `test8_Block` - the safety screen's block, confirmed.
final class ClientBookingUITests: ClientUITestCase {
    // MARK: Helpers

    private func openOrders(locale: String = "uz") {
        let menu = app.buttons[locale == "ru" ? "Меню" : "Menyu"].firstMatch
        XCTAssertTrue(menu.waitForExistence(timeout: 20), "no menu button")
        menu.tap()
        tap(locale == "ru" ? "Заказы" : "Buyurtmalar")
        waitFor(locale == "ru" ? "Брони" : "Bronlar", timeout: 20)
    }

    /// The newest booking card with this status (the list is newest first).
    private func openBooking(status: String, detail: String = "Haydovchi va avtomobil") {
        let card = app.buttons.containing(NSPredicate(format: "label CONTAINS %@ AND label CONTAINS %@", "→", status)).firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 20), "no booking card '\(status)'")
        card.tap()
        waitFor(detail, timeout: 20)
    }

    /// Scrolls the screen until a button with this label is hittable, then taps it.
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

    private func back() { tap("Orqaga") }

    /// Picks an option from a `SelectField` (a system menu).
    private func choose(_ field: String, _ option: String) {
        let menu = app.buttons[field].firstMatch
        XCTAssertTrue(menu.waitForExistence(timeout: 10), "no select '\(field)'")
        menu.tap()
        let item = app.buttons[option].firstMatch
        XCTAssertTrue(item.waitForExistence(timeout: 5), "no option '\(option)'")
        item.tap()
    }

    // MARK: Phases

    func test0_SignIn() {
        launch()
        signInAsClient(phone: Self.runPhone)
    }

    func test1_Confirmed() {
        launch(reset: false)
        openOrders()
        waitFor("Tasdiqlandi")
        snap("80-orders-booking")
        openBooking(status: "Tasdiqlandi")
        waitFor("Hali baholanmagan", timeout: 20)
        // The helper's pickup starts within 30 minutes, so the plate may already be the full one (Q64).
        waitFor("Davlat raqami")
        waitFor("Safar jo'naganda ochiladi")
        snap("81-detail-top")
        app.swipeUp()
        waitFor("haydovchiga naqd to'lanadi")
        snap("82-detail-middle")
        app.swipeUp()
        snap("83-detail-bottom")

        // Recipient link: 1 hour.
        scrollTap("1 soat")
        scrollTap("Havola yaratish")
        waitFor("Havola matni faqat birinchi javobda keladi", timeout: 20)
        snap("84-share-link")
        scrollTap("Havolani bekor qilish")
        waitFor("Havola bekor qilindi", timeout: 20)

        // The cancel sheet: reasons, not confirmed.
        scrollTap("Bronni bekor qilish")
        waitFor("Bronni bekor qilasizmi?")
        snap("85-cancel-sheet")
        choose("Sabab", "Boshqa yo'l topdim")
        waitFor("Boshqa yo'l topdim")
        tap("Bronni saqlash")
        waitGone("Bronni bekor qilasizmi?")

        // An amendment: sent, then taken back.
        scrollTap("Shartlarni o'zgartirish")
        waitFor("Hozirgi kelishuv")
        waitFor("faqat narxni kelishib o'zgartirish mumkin")
        type("125000", into: "Narx (so'm)")
        type("Yuk og'irroq bo'lib chiqdi", into: "Sabab")
        waitFor("Yangi jami: 125")
        snap("86-amend-form")
        tap("Taklif yuborish")
        waitFor("Taklif yuborildi", timeout: 20)
        waitFor("Sizning taklifingiz")
        snap("87-amend-sent")
        tap("Taklifni qaytarib olish")
        waitFor("Taklif qaytarib olindi", timeout: 20)
        snap("88-amend-withdrawn")
        back()

        // Chat: empty, a text, a quick reply, a masked contact.
        app.swipeDown()
        scrollTap("Xabarlar")
        waitFor("Xabar yo'q", timeout: 20)
        snap("89-chat-empty")
        type("Salom, posilka tayyor", into: "Xabar yozing")
        tap("Yuborish")
        waitFor("Salom, posilka tayyor", timeout: 20)
        tap("Bekatdaman")
        waitFor("Bekatdaman")
        type("Telefonim 90 123 45 67", into: "Xabar yozing")
        tap("Yuborish")
        waitFor("Aloqa ma'lumotlari yashirildi", timeout: 20)
        snap("90-chat-sent")
        back()

        // Support chat: nothing yet, the first message opens it.
        scrollTap("Yordam / shikoyat")
        waitFor("Javob vaqti va'da qilinmaydi")
        snap("91-support-empty")
        type("Haydovchi bilan bekatni aniqlashtirishda yordam kerak", into: "Xabar")
        tap("Yuborish")
        waitFor("Navbatda", timeout: 20)
        snap("92-support-sent")
        back()

        // Safety: a report, then the block confirmation (not confirmed here).
        scrollTap("Xavfsizlik haqida xabar berish")
        waitFor("Oddiy muammo uchun")
        snap("93-safety")
        choose("Sabab", "Narx bo'yicha bosim")
        type("Narxni oshirishni talab qildi", into: "Izoh (ixtiyoriy)")
        scrollTap("Yuborish")
        waitFor("Shikoyat yuborildi", timeout: 20)
        snap("94-safety-sent")
        scrollTap("Bloklash")
        waitFor("Haydovchini bloklaysizmi?")
        snap("95-block-confirm")
        tap("Ortga")
        back()
    }

    func test2_DriverAndOperator() {
        launch(reset: false)
        openOrders()
        openBooking(status: "Tasdiqlandi")
        // The chat is open before the driver writes: the message comes by polling.
        scrollTap("Xabarlar")
        waitFor("Salom, posilka tayyor", timeout: 20)
        waitFor("Assalomu alaykum", timeout: 90)
        waitFor("5 daqiqada yetaman", timeout: 30)
        snap("100-chat-driver")
        back()

        scrollTap("Shartlarni o'zgartirish")
        waitFor("Ikkinchi tomon taklifi", timeout: 20)
        snap("101-amend-driver")
        tap("Qabul qilish")
        waitFor("Yangi shartlar kuchga kirdi", timeout: 20)
        snap("102-amend-accepted")
        back()
        waitFor("130")

        scrollTap("Yordam / shikoyat")
        waitFor("Navbatda", timeout: 20)
        waitFor("Operator javob berdi", timeout: 120)
        snap("103-support-reply")
    }

    /// Russian + dark: the booking's screens (read-only).
    func test2b_RussianDark() {
        launch(locale: "ru", theme: "dark", reset: false)
        openOrders(locale: "ru")
        openBooking(status: "Подтверждено", detail: "Водитель и автомобиль")
        snap("104-ru-dark-detail")
        app.swipeUp()
        snap("105-ru-dark-detail-middle")
        app.swipeUp()
        snap("106-ru-dark-detail-bottom")
        scrollTap("Сообщения")
        waitFor("Я на месте", timeout: 20)
        snap("107-ru-dark-chat")
        tap("Назад")
        scrollTap("Отслеживание")
        waitFor("Ход выполнения")
        snap("108-ru-dark-tracking")
        tap("Назад")
        scrollTap("Отменить бронь")
        waitFor("Отменить бронь?")
        snap("109-ru-dark-cancel")
        tap("Оставить бронь")
        waitGone("Отменить бронь?")
        scrollTap("Помощь / жалоба")
        waitFor("Оператор", timeout: 20)
        snap("116-ru-dark-support")
    }

    /// The support chat stays open while the client writes again; the operator's second answer comes by polling.
    /// Shell: `operator-reply` about 40 s after this phase starts.
    func test2d_SupportReply() {
        launch(reset: false)
        openOrders()
        openBooking(status: "Tasdiqlandi")
        scrollTap("Yordam / shikoyat")
        waitFor("Operator", timeout: 20)
        type("Posilka qachon olib ketiladi?", into: "Xabar")
        tap("Yuborish")
        waitFor("Posilka qachon olib ketiladi?", timeout: 20)
        snap("117-support-follow-up")
        // The server keeps staff_status "answered" after the client's follow-up; the new answer is the proof.
        waitFor("Olib ketish vaqti haydovchi bilan", timeout: 120)
        waitFor("Operator javob berdi", timeout: 20)
        snap("103-support-reply")
    }

    /// Uzbek + dark: detail, chat, support, tracking, amendments, safety.
    func test2c_UzbekDark() {
        launch(theme: "dark", reset: false)
        openOrders()
        openBooking(status: "Tasdiqlandi")
        snap("110-uz-dark-detail")
        app.swipeUp()
        snap("111-uz-dark-detail-middle")
        scrollTap("Xabarlar")
        waitFor("Bekatdaman", timeout: 20)
        snap("112-uz-dark-chat")
        back()
        scrollTap("Yordam / shikoyat")
        waitFor("Operator", timeout: 20)
        snap("113-uz-dark-support")
        back()
        scrollTap("Shartlarni o'zgartirish")
        waitFor("Tarix")
        snap("114-uz-dark-amend")
        back()
        scrollTap("Xavfsizlik haqida xabar berish")
        snap("115-uz-dark-safety")
    }

    func test3_Boarded() {
        launch(reset: false)
        openOrders()
        openBooking(status: "Olib ketish kutilmoqda")
        waitFor("To'liq raqam ochildi", timeout: 20)
        snap("120-detail-boarded")
        app.swipeUp()
        XCTAssertFalse(app.buttons["Shartlarni o'zgartirish"].exists, "amend offered while awaiting pickup")
        snap("121-detail-boarded-bottom")
        app.swipeDown()
        scrollTap("Kuzatuv")
        waitFor("Safarga tayyorlanmoqda")
        waitFor("posilka olib ketilgandan keyin", timeout: 20)
        snap("122-tracking-not-picked-up")
    }

    func test4_InTransit() {
        launch(reset: false)
        openOrders()
        openBooking(status: "Haydovchi yo'lga chiqdi")
        waitFor("Aloqa ochiq", timeout: 20)
        waitFor("Qo'ng'iroq")
        snap("130-detail-in-transit")
        scrollTap("Kuzatuv")
        waitFor("Jonli joylashuv", timeout: 30)
        waitFor("So'nggi 30 soniya ichida yangilangan", timeout: 40)
        waitFor("Oxirgi nuqta")
        snap("131-tracking-fresh")
        app.swipeUp()
        snap("132-tracking-fresh-bottom")
        // GPS stops in the background: the point ages on the phone - delayed, then lost.
        waitFor("Joylashuv kechikmoqda", timeout: 120)
        snap("133-tracking-delayed")
        waitFor("Haydovchi telefoni bilan aloqa uzilgan", timeout: 150)
        snap("134-tracking-lost")
    }

    /// Russian + dark while the GPS runs: detail with the phone, live tracking.
    func test4c_RuDarkLive() {
        launch(locale: "ru", theme: "dark", reset: false)
        openOrders(locale: "ru")
        openBooking(status: "Водитель выехал", detail: "Водитель и автомобиль")
        snap("137-ru-dark-in-transit")
        scrollTap("Отслеживание")
        waitFor("Местоположение в реальном времени", timeout: 40)
        snap("138-ru-dark-tracking-live")
    }

    func test4b_Delivered() {
        launch(reset: false)
        openOrders()
        openBooking(status: "Operator yetkazilganini qayd etdi")
        snap("135-detail-delivered")
        scrollTap("Kuzatuv")
        waitFor("Holat kuzatuvi")
        snap("136-tracking-delivered")
    }

    func test5_CompletedRate() {
        launch(reset: false)
        openOrders()
        openBooking(status: "Yakunlangan")
        snap("140-detail-completed")
        scrollTap("Haydovchini baholash")
        waitFor("1 dan 5 gacha baho bering")
        snap("141-rating")
        tap("4 yulduz")
        type("Vaqtida yetkazdi, xushmuomala", into: "Izoh qoldiring")
        snap("142-rating-filled")
        tap("Bahoni yuborish")
        waitFor("Baho berildi", timeout: 20)
        snap("143-rated")
        scrollTap("Kuzatuv")
        waitFor("Holat kuzatuvi")
        snap("144-tracking-completed")
        back()
        scrollTap("Xabarlar")
        waitFor("Salom, posilka tayyor", timeout: 20)
        snap("145-chat-after-completion")
    }

    func test6_CancelSpare() {
        launch(reset: false)
        openOrders()
        openBooking(status: "Tasdiqlandi")
        scrollTap("Bronni bekor qilish")
        waitFor("Bronni bekor qilasizmi?")
        choose("Sabab", "Rejalarim o'zgardi")
        type("Boshqa kunga qoldirdim", into: "Izoh (ixtiyoriy)")
        tap("Ha, bekor qilish")
        waitFor("Bron bekor qilindi", timeout: 20)
        waitFor("Bekor qilindi: Siz")
        app.swipeDown()
        snap("150-cancelled")
        back()
        waitFor("Bekor qilingan")
        snap("151-orders-after-cancel")
    }

    func test7_PostRequest() {
        launch(reset: false)
        let menu = app.buttons["Menyu"].firstMatch
        XCTAssertTrue(menu.waitForExistence(timeout: 20))
        menu.tap()
        tap("Bosh sahifa")
        waitFor("Qayerdan?")
        postParcelRequest(price: "120000")
    }

    func test7b_AcceptLandsInChat() {
        launch(reset: false)
        openOrders()
        let listing = app.buttons.containing(NSPredicate(format: "label CONTAINS %@ AND label CONTAINS %@", "→", "E'lon qilingan")).firstMatch
        XCTAssertTrue(listing.waitForExistence(timeout: 20))
        listing.tap()
        // BOSQICH 03: the offers are inline on the listing's detail.
        // Stage 03 alignment: an unrated driver is "Hali baholanmagan" (never "0 ta baho"), answers inside the card.
        waitFor("Hali baholanmagan", timeout: 20)
        XCTAssertFalse(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "0 ta baho")).firstMatch.exists)
        snap("159-offer-card")
        scrollTap("Tanlash")
        tap("Ha, tanlayman")
        // Q100: straight into the new booking's chat.
        waitFor("Xabar yo'q", timeout: 30)
        waitFor("Bekatdaman")
        snap("160-accept-chat")
        back()
        waitFor("Haydovchi va avtomobil", timeout: 20)
        snap("161-accept-detail")
        back()
        waitFor("Haydovchi tanlandi")
        waitFor("Bronlar")
        snap("162-accept-orders")
    }

    func test8_Block() {
        launch(reset: false)
        openOrders()
        openBooking(status: "Tasdiqlandi")
        scrollTap("Xavfsizlik haqida xabar berish")
        scrollTap("Bloklash")
        waitFor("Haydovchini bloklaysizmi?")
        tap("Ha, bloklash")
        waitFor("Haydovchi bloklandi", timeout: 20)
        snap("170-blocked")
    }
}
