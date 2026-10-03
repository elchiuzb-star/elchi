import Foundation
import Testing
@testable import Elchi

/// BOSQICH 02 design ("Elchi Buyurtma Yaratish"): the step counter, tap-to-validate lists, the Taksi block, the price
/// stepper, the comment warning, the window sheet's rules, "locate -> Qayerdan", stops in the request body and the
/// place wording.
struct OrderFlowLogicTests {
    private static func date(_ text: String) -> Date { ISO8601DateFormatter().date(from: text)! }

    @Test func stepCounterPerService() {
        #expect(OrderStep.position(.route, mode: .parcel)! == (1, 3))
        #expect(OrderStep.position(.contact, mode: .parcel)! == (2, 3))
        #expect(OrderStep.position(.review, mode: .parcel)! == (3, 3))
        #expect(OrderStep.position(.review, mode: .passenger)! == (1, 1))
        #expect(OrderStep.position(.route, mode: .passenger) == nil)
    }

    @Test func taxiHomeListsWindowPeopleThenPrice() {
        let now = Self.date("2026-09-28T06:00:00Z")
        let start = Self.date("2026-09-29T04:00:00Z"), end = Self.date("2026-09-29T13:00:00Z")
        #expect(RouteBlocker.taxiHome(start: start, end: end, priceMinor: 100, seatCount: 2, now: now).isEmpty)
        #expect(RouteBlocker.taxiHome(start: nil, end: nil, priceMinor: 0, seatCount: nil, now: now)
            == [.windowStart, .windowEnd, .seats, .price])
        #expect(RouteBlocker.taxiHome(start: end, end: start, priceMinor: 100, seatCount: 4, now: now) == [.endAfterStart])
        #expect(RouteBlocker.seats.key == "client.taxi.err.seats")
        #expect(RouteBlocker.windowEnd.key == "client.order.err.windowEnd")
        #expect(RouteBlocker.endAfterStart.key == "client.order.err.endAfterStart")
        #expect(RouteBlocker.windowEnd.marksEnd && RouteBlocker.windowPast.marksEnd && RouteBlocker.windowStart.marksStart)
        #expect(!RouteBlocker.price.marksStart && !RouteBlocker.price.marksEnd)
    }

    @Test func contactStepListsEveryProblemInOrder() {
        var contacts = ContactsForm()
        contacts.senderName = "A"
        contacts.senderPhone = "90123"
        #expect(ContactBlocker.check(contacts: contacts, parcelType: nil, hasCategory: false, photoUploaded: false)
            == [.senderName, .senderPhone, .receiverName, .receiverPhone, .type, .size, .photo])
        contacts.senderName = "Aziza"
        contacts.senderPhone = "901234567"
        contacts.receiverName = " Di "
        contacts.receiverPhone = "915552211"
        #expect(ContactBlocker.check(contacts: contacts, parcelType: .box, hasCategory: true, photoUploaded: true).isEmpty)
        #expect(ContactBlocker.check(contacts: contacts, parcelType: .box, hasCategory: true, photoUploaded: false) == [.photo])
        #expect(ContactBlocker.senderPhone.key == "client.order.err.phone9")
        #expect(ContactBlocker.photo.key == "orderForm.photoRequired")
        #expect(!ContactBlocker.validName(" A "))
    }

    @Test func priceStepsByFiveThousandWithinLimits() {
        #expect(PriceStep.apply("", delta: 1) == "5000")
        #expect(PriceStep.apply("120000", delta: 1) == "125000")
        #expect(PriceStep.apply("3000", delta: -1) == "")
        #expect(PriceStep.apply("", delta: -1) == "")
        #expect(PriceStep.apply("99999999", delta: 1) == "99999999")
        #expect(PriceStep.digits("1 234 567 890") == "12345678")
        #expect(PriceStep.digits("007") == "7")
    }

    @Test func commentWarnsAboutPhonesAndLinks() {
        #expect(NoteText.carriesContact("Qo'ng'iroq: 901234567"))
        #expect(NoteText.carriesContact("90 123 45 67 ga yozing"))
        #expect(NoteText.carriesContact("t.me/aziza"))
        #expect(NoteText.carriesContact("@aziza"))
        #expect(NoteText.carriesContact("https://x.uz"))
        #expect(!NoteText.carriesContact("Ertalab 10 gacha qo'ng'iroq qilmang"))
        #expect(NoteText.masked("Tel 901234567, t.me/aziza") == "Tel •••, •••")
        #expect(NoteText.limited(String(repeating: "a", count: 400)).count == 300)
    }

    @Test func windowSheetRules() throws {
        // 11:00 Tashkent on 28 Sep.
        let now = Self.date("2026-09-28T06:00:00Z")
        let days = WindowPicker.days(now: now)
        #expect(days.count == 21)
        #expect(DepartureWindow.iso(days[0]) == "2026-09-28T00:00:00+05:00")
        #expect(DepartureWindow.iso(days[20]) == "2026-10-18T00:00:00+05:00")
        let value = WindowPicker.compose(day: days[1], hour: 9, minute: 30)
        #expect(DepartureWindow.iso(value) == "2026-09-29T09:30:00+05:00")
        let parts = WindowPicker.parts(value, days: days)
        #expect(parts.day == 1 && parts.hour == 9 && parts.minute == 30)
        // A day past the strip clamps to its end.
        #expect(WindowPicker.parts(Self.date("2026-12-01T06:00:00Z"), days: days).day == 20)
        #expect(WindowPicker.minuteOptions(including: 30) == [0, 15, 30, 45])
        #expect(WindowPicker.minuteOptions(including: 7) == [0, 7, 15, 30, 45])
        #expect(DepartureWindow.iso(WindowPicker.quick(hours: 4, from: value)) == "2026-09-29T13:30:00+05:00")
        #expect(DepartureWindow.iso(WindowPicker.quick(hours: nil, from: value)) == "2026-09-29T23:45:00+05:00")
        #expect(WindowPicker.problemKey(edge: .start, value: Self.date("2026-09-28T05:00:00Z"), start: nil, now: now) == "client.order.picker.past")
        #expect(WindowPicker.problemKey(edge: .end, value: value, start: value, now: now) == "client.order.err.endAfterStart")
        #expect(WindowPicker.problemKey(edge: .end, value: value.addingTimeInterval(60), start: value, now: now) == nil)
        #expect(WindowPicker.lengthMinutes(start: value, end: value.addingTimeInterval(9 * 3600 + 1800)) == 570)
    }

    @Test func locatePicksTheNearestDistrictInsideUzbekistan() {
        var chilonzor = RequestBodyTests.district
        chilonzor.id = "dst_ch"
        chilonzor.centerLat = 41.2856
        chilonzor.centerLng = 69.2044
        var closed = chilonzor
        closed.id = "dst_closed"
        closed.isActive = false
        closed.centerLat = 41.29
        closed.centerLng = 69.21
        let districts = [closed, chilonzor]
        #expect(LocateRules.district(near: GeoPoint(lat: 41.29, lng: 69.21), in: districts)?.id == "dst_ch")
        // More than 50 km from every centre, or abroad: nothing.
        #expect(LocateRules.district(near: GeoPoint(lat: 40.0, lng: 64.0), in: districts) == nil)
        #expect(LocateRules.district(near: GeoPoint(lat: 55.75, lng: 37.62), in: districts) == nil)
        let region = LocateRules.region(of: RequestBodyTests.sam, in: [RequestBodyTests.region])
        #expect(region.id == "reg_sa" && region.nameUz == "Samarqand viloyati")
        #expect(LocateRules.region(of: chilonzor, in: [RequestBodyTests.region]).requiresDistrict == false)
    }

    @Test func aChosenStopGoesAsTheStopId() throws {
        let start = Self.date("2026-09-29T04:00:00Z")
        let stop = PlaceStop(id: "stp_1", nameUz: "Registon bekati", nameRu: nil)
        let draft = PassengerRequestDraft(
            pickup: PlaceEnd(region: RequestBodyTests.region, district: RequestBodyTests.district, point: GeoPoint(lat: 41.28, lng: 69.2),
                             address: "Chilonzor"),
            dropoff: PlaceEnd(region: RequestBodyTests.region, district: RequestBodyTests.sam, point: GeoPoint(lat: 39.65, lng: 66.97),
                              address: "Registon bekati", stop: stop),
            windowStart: start, windowEnd: start.addingTimeInterval(3600), seats: TaxiSeats.wholeCabin, unitPriceMinor: 10_000_000)
        let json = try #require(try JSONSerialization.jsonObject(with: JSONEncoder().encode(draft.listingCreate())) as? [String: Any])
        #expect(json["destination_stop_id"] as? String == "stp_1")
        #expect(json["destination_point"] == nil)
        #expect(json["origin_stop_id"] == nil)
        #expect((json["origin_point"] as? [String: Any])?["district_id"] as? String == "dst_tk")
        // "Butun salon" books all four seats.
        #expect((json["passenger"] as? [String: Any])?["seat_count"] as? Int == 4)
        #expect(draft.totalMinor == 40_000_000)
    }
}

@MainActor
struct OrderWordingTests {
    @Test func placeAndAreaFollowTheDesign() {
        let strings = LocaleStore()
        strings.set(.uz)
        let point = GeoPoint(lat: 39.65, lng: 66.97)
        let sam = PlaceEnd(region: RegionDTO(code: "UZ-SA", id: "reg_sa", nameUz: "Samarqand viloyati"), district: RequestBodyTests.sam,
                           point: point, address: "Registon ko'chasi")
        #expect(strings.place(sam) == "Registon ko'chasi")
        #expect(strings.area(sam) == "Samarqand, Samarqand viloyati")
        var noAddress = sam
        noAddress.address = nil
        #expect(strings.place(noAddress) == point.text)
        var stop = sam
        stop.stop = PlaceStop(id: "stp_1", nameUz: "Registon bekati", nameRu: "Регистан")
        #expect(strings.place(stop) == "Registon bekati")
        #expect(strings.areaDetail(stop) == "Tasdiqlangan bekat · Samarqand, Samarqand viloyati")
        var here = sam
        here.currentLocation = true
        #expect(strings.place(here) == "Joriy joylashuv")
        // Tashkent city has no districts: one name.
        let city = PlaceEnd(region: RequestBodyTests.region, district: RequestBodyTests.district, point: point, address: nil)
        #expect(strings.area(city) == "Toshkent shahri")
        strings.set(.ru)
        #expect(strings.place(stop) == "Регистан")
        strings.set(.uz)
    }

    @Test func windowWordsAndDesignKeys() {
        let strings = LocaleStore()
        strings.set(.uz)
        let now = ISO8601DateFormatter().date(from: "2026-09-27T06:00:00Z")!
        let tomorrow = ISO8601DateFormatter().date(from: "2026-09-28T04:00:00Z")!
        let friday = ISO8601DateFormatter().date(from: "2026-10-02T04:00:00Z")!
        #expect(strings.tileDate(now, now: now) == "27 sen")
        #expect(strings.tileDate(tomorrow, now: now) == "Ertaga, 28 sen")
        #expect(strings.tileDate(friday, now: now) == "Ju, 2 okt")
        #expect(strings.monthTitle(now) == "Sentabr 2026")
        #expect(strings.windowHint(start: tomorrow, end: tomorrow.addingTimeInterval(9 * 3600))
            == "Oyna: 9 soat · Haydovchilar shu oraliqda jo'nashni taklif qiladi.")
        #expect(strings.windowHint(start: nil, end: nil) == "Haydovchilar shu oraliqda jo'nashni taklif qiladi.")
        #expect(strings.seatValue(nil) == "Tanlang")
        #expect(strings.seatValue(2) == "2 kishi")
        #expect(strings.seatValue(4) == "Butun salon")
        // The design-only keys (generated now) fill their placeholders.
        #expect(strings.t("client.order.pointTitleFrom", ("area", "Chilonzor")) == "Qayerdan: Chilonzor")
        strings.set(.ru)
        #expect(strings.t("client.order.windowStartShort") == "Начало")
        #expect(strings.tileDate(tomorrow, now: now) == "Завтра, 28 сен")
        strings.set(.uz)
    }
}
