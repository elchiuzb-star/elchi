import Foundation
import UIKit
import Testing
@testable import Elchi

struct MoneyTests {
    @Test func soumToMinorAndBack() {
        #expect(Money.minor(fromSoum: "120 000") == 12_000_000)
        #expect(Money.minor(fromSoum: "120\u{202F}000") == 12_000_000)
        #expect(Money.minor(fromSoum: "") == 0)
        #expect(Money.minor(fromSoum: "000") == 0)
        #expect(Money.minor(fromSoum: "abc12") == 1_200)
        #expect(Money.soumDigits("0050") == "50")
        // Capped so `* 100` can never overflow.
        #expect(Money.soumDigits(String(repeating: "9", count: 30)).count == Money.maxSoumDigits)
    }

    @Test func groupsLikeTheDesign() {
        #expect(Money.grouped("120000") == "120\u{202F}000")
        #expect(Money.grouped("1200") == "1\u{202F}200")
        #expect(Money.grouped("999") == "999")
        #expect(Money.grouped("") == "")
        #expect(Money.format(minor: 12_000_000, currencyWord: "so'm") == "120\u{202F}000\u{00A0}so'm")
        #expect(Money.format(minor: 0, currencyWord: "сум") == "0\u{00A0}сум")
    }
}

struct PhoneTests {
    @Test func localDigitsAndDisplay() {
        #expect(UzPhone.localDigits("90 123 45 67") == "901234567")
        #expect(UzPhone.localDigits("+998 90 123 45 67") == "901234567")
        #expect(UzPhone.localDigits("9012345678999") == "901234567")
        #expect(UzPhone.localDigits(fromE164: "+998901234567") == "901234567")
        #expect(UzPhone.formatLocal("901234567") == "90 123 45 67")
        #expect(UzPhone.display("+998901234567") == "+998 90 123 45 67")
        #expect(UzPhone.isValid("90123456") == false)
    }
}

struct DepartureWindowTests {
    private func tashkent(_ text: String) -> Date {
        let formatter = ISO8601DateFormatter()
        return formatter.date(from: text)!
    }

    @Test func suggestsTomorrowNineToSixInTashkent() {
        // 23:30 in Tashkent on 28 Sep is still 18:30 UTC on 28 Sep: "tomorrow" is the 29th in Tashkent.
        let now = tashkent("2026-09-28T18:30:00Z")
        let window = DepartureWindow.suggested(now: now)
        #expect(DepartureWindow.iso(window.start) == "2026-09-29T09:00:00+05:00")
        #expect(DepartureWindow.iso(window.end) == "2026-09-29T18:00:00+05:00")
        // 00:30 Tashkent on the 29th is 19:30 UTC on the 28th: tomorrow is the 30th.
        let afterMidnight = DepartureWindow.suggested(now: tashkent("2026-09-28T19:30:00Z"))
        #expect(DepartureWindow.text(afterMidnight.start) == "30.09.2026, 09:00")
        #expect(DepartureWindow.shortText(afterMidnight.end) == "30.09, 18:00")
    }

    @Test func listsWhatIsMissing() {
        let now = tashkent("2026-09-28T06:00:00Z")
        let start = tashkent("2026-09-29T04:00:00Z"), end = tashkent("2026-09-29T13:00:00Z")
        #expect(RouteBlocker.check(directionReady: true, start: start, end: end, priceMinor: 100, now: now).isEmpty)
        #expect(RouteBlocker.check(directionReady: false, start: nil, end: nil, priceMinor: 0, now: now)
            == [.bothPoints, .windowStart, .windowEnd, .price])
        #expect(RouteBlocker.check(directionReady: true, start: end, end: start, priceMinor: 100, now: now) == [.endAfterStart])
        let past = tashkent("2026-09-27T13:00:00Z")
        #expect(RouteBlocker.check(directionReady: true, start: tashkent("2026-09-27T04:00:00Z"), end: past, priceMinor: 100, now: now)
            == [.windowPast])
        #expect(RouteBlocker.windowStart.key == "app.validation.windowStart")
        #expect(RouteBlocker.price.key == "listingOwner.invalid.price")
    }
}

struct RequestBodyTests {
    static let region = RegionDTO(centerLat: 41.31, centerLng: 69.28, code: "UZ-TK", id: "reg_tk", nameUz: "Toshkent shahri", requiresDistrict: false)
    static let district = DistrictDTO(id: "dst_tk", nameUz: "Toshkent shahri", region: RegionRefDTO(code: "UZ-TK", id: "reg_tk", nameUz: "Toshkent shahri"))
    static let sam = DistrictDTO(id: "dst_sam", nameUz: "Samarqand", region: RegionRefDTO(code: "UZ-SA", id: "reg_sa", nameUz: "Samarqand viloyati"))

    @Test func buildsTheParcelRequest() throws {
        var contacts = ContactsForm()
        contacts.senderName = " Aziza Karimova "
        contacts.senderPhone = "901234567"
        contacts.receiverName = "Dilnoza"
        contacts.receiverPhone = "915552211"
        contacts.comment = "  "
        let start = ISO8601DateFormatter().date(from: "2026-09-29T04:00:00Z")!
        let draft = ParcelRequestDraft(
            pickup: PlaceEnd(region: Self.region, district: Self.district, point: GeoPoint(lat: 41.2856, lng: 69.2044), address: "Chilonzor"),
            dropoff: PlaceEnd(region: Self.region, district: Self.sam, point: GeoPoint(lat: 39.6547, lng: 66.9758), address: nil),
            windowStart: start, windowEnd: start.addingTimeInterval(9 * 3600), priceMinor: 12_000_000, contacts: contacts,
            parcelType: .box, categoryId: "pct_small", photoFileId: "/api/v1/files/x?sig=1")
        let body = draft.listingCreate()
        let json = try #require(try JSONSerialization.jsonObject(with: JSONEncoder().encode(body)) as? [String: Any])

        #expect(json["kind"] as? String == "request")
        #expect(json["service_type"] as? String == "parcel")
        #expect(json["price_basis"] as? String == "total")
        #expect(json["unit_price_minor"] as? Int == 12_000_000)
        #expect(json["currency"] as? String == "UZS")
        #expect(json["payment_method"] as? String == "cash")
        #expect(json["timezone"] as? String == "Asia/Tashkent")
        #expect(json["departure_window_start"] as? String == "2026-09-29T09:00:00+05:00")
        #expect(json["departure_window_end"] as? String == "2026-09-29T18:00:00+05:00")
        #expect(json["comment"] == nil) // blank comment is not sent
        #expect(json["origin_stop_id"] == nil)
        let origin = try #require(json["origin_point"] as? [String: Any])
        #expect(origin["district_id"] as? String == "dst_tk")
        #expect(origin["lat"] as? Double == 41.2856)
        #expect(origin["address"] as? String == "Chilonzor")
        let destination = try #require(json["destination_point"] as? [String: Any])
        #expect(destination["district_id"] as? String == "dst_sam")
        #expect(destination["address"] == nil)
        let parcel = try #require(json["parcel"] as? [String: Any])
        #expect(parcel["parcel_type"] as? String == "box")
        #expect(parcel["category_id"] as? String == "pct_small")
        #expect(parcel["payer"] as? String == "sender")
        #expect(parcel["photo_file_id"] as? String == "/api/v1/files/x?sig=1")
        #expect((parcel["sender"] as? [String: String]) == ["name": "Aziza Karimova", "phone": "+998901234567"])
        #expect((parcel["receiver"] as? [String: String]) == ["name": "Dilnoza", "phone": "+998915552211"])
        // Q140: sizes come from the category, never typed.
        #expect(parcel["weight_g"] == nil && parcel["length_cm"] == nil)
    }

    @Test func contactsNeedNamesAndFullPhones() {
        var contacts = ContactsForm()
        #expect(!contacts.isComplete)
        // BOSQICH 02: a name is at least two letters.
        contacts.senderName = "A"
        contacts.receiverName = "Bo"
        contacts.senderPhone = "901234567"
        contacts.receiverPhone = "915552211"
        #expect(!contacts.isComplete)
        contacts.senderName = "Al"
        contacts.receiverPhone = "91555221"
        #expect(!contacts.isComplete)
        contacts.receiverPhone = "915552211"
        #expect(contacts.isComplete)
    }

    @Test func nearestDistrictForARegionWithoutDistricts() {
        var chilonzor = Self.district
        chilonzor.id = "dst_ch"
        chilonzor.centerLat = 41.2856
        chilonzor.centerLng = 69.2044
        var yunusobod = Self.district
        yunusobod.id = "dst_yu"
        yunusobod.centerLat = 41.3650
        yunusobod.centerLng = 69.2890
        let noCentre = Self.sam
        #expect(nearestDistrict([noCentre, yunusobod, chilonzor], to: GeoPoint(lat: 41.29, lng: 69.21))?.id == "dst_ch")
        #expect(nearestDistrict([noCentre], to: GeoPoint(lat: 41.29, lng: 69.21)) == nil)
    }
}

struct RouteGeometryTests {
    @Test func decodesGooglePolyline() {
        // The reference example from Google's algorithm description.
        let points = Polyline.decode("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
        #expect(points.count == 3)
        #expect(abs(points[0].lat - 38.5) < 1e-9 && abs(points[0].lng - -120.2) < 1e-9)
        #expect(abs(points[1].lat - 40.7) < 1e-9 && abs(points[1].lng - -120.95) < 1e-9)
        #expect(abs(points[2].lat - 43.252) < 1e-9 && abs(points[2].lng - -126.453) < 1e-9)
        #expect(Polyline.decode("").isEmpty)
        // A truncated chunk stops cleanly instead of inventing a point.
        #expect(Polyline.decode("_p~iF~ps|U_ulL").count == 1)
    }

    @Test func figuresAndWeights() {
        #expect(RouteFigures.kilometres(308_400) == 308)
        #expect(RouteFigures.kilometres(200) == 1)
        #expect(RouteFigures.kilometres(0) == 0)
        #expect(RouteFigures.duration(16_500) == (4, 35))
        #expect(RouteFigures.duration(3_590) == (1, 0))
        #expect(RouteFigures.kilograms(500) == "0,5")
        #expect(RouteFigures.kilograms(5_000) == "5")
        #expect(RouteFigures.kilograms(1_250) == "1,25")
    }

    @Test func searchIgnoresCaseAndApostrophes() {
        #expect(SearchText.matches("Farg'ona viloyati", "fargʻona"))
        #expect(SearchText.matches("Farg'ona viloyati", "FARGONA"))
        #expect(SearchText.matches("Qo'qon", ""))
        #expect(!SearchText.matches("Samarqand", "Buxoro"))
    }
}

struct MultipartTests {
    @Test func buildsAFormWithTheTypeFieldAndFile() {
        var form = MultipartForm()
        form.field("type", "cargo_photo")
        form.file("file", filename: "parcel.jpg", mimeType: "image/jpeg", data: Data([0xFF, 0xD8]))
        form.finish()
        let text = String(decoding: form.body, as: UTF8.self)
        #expect(text.contains("name=\"type\"\r\n\r\ncargo_photo\r\n"))
        #expect(text.contains("name=\"file\"; filename=\"parcel.jpg\"\r\nContent-Type: image/jpeg"))
        #expect(text.hasSuffix("--\(form.boundary)--\r\n"))
    }

    @Test func compressesToAtMost1600Pixels() throws {
        let image = UIGraphicsImageRenderer(size: CGSize(width: 4000, height: 3000), format: {
            let format = UIGraphicsImageRendererFormat.default()
            format.scale = 1
            return format
        }()).image { context in
            UIColor.red.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 4000, height: 3000))
        }
        let data = try #require(PhotoCompressor.jpeg(image))
        let decoded = try #require(UIImage(data: data))
        #expect(max(decoded.size.width * decoded.scale, decoded.size.height * decoded.scale) == 1600)
    }
}

struct AddressTests {
    @Test func dropsTheCountryPrefix() {
        #expect(PointPickerModel.withoutCountry("Oʻzbekiston, Toshkent, Amir Temur shoh koʻchasi, 2") == "Toshkent, Amir Temur shoh koʻchasi, 2")
        #expect(PointPickerModel.withoutCountry("Узбекистан, Ташкент") == "Ташкент")
        #expect(PointPickerModel.withoutCountry("Oʻzbekiston") == "Oʻzbekiston")
    }
}

@Suite struct PolylineLegTests {
    // A straight north-south road with 5 vertices, 1° apart.
    let road = (0...4).map { GeoPoint(lat: 41.0 - Double($0), lng: 69.0) }

    @Test func keepsOnlyTheStretchBetweenTheTwoPlaces() {
        let leg = Polyline.leg(road, from: GeoPoint(lat: 40.5, lng: 69.01), to: GeoPoint(lat: 38.5, lng: 68.99))
        #expect(leg.first?.lat == 40.5)
        #expect(leg.last?.lat == 38.5)
        #expect(leg.map(\.lat) == [40.5, 40.0, 39.0, 38.5])
    }

    @Test func runsInTravelOrderWhenTheRouteIsDrawnTheOtherWay() {
        let leg = Polyline.leg(road, from: GeoPoint(lat: 38.5, lng: 69), to: GeoPoint(lat: 40.5, lng: 69))
        #expect(leg.map(\.lat) == [38.5, 39.0, 40.0, 40.5])
    }

    @Test func bothPlacesOnOneSegment() {
        let leg = Polyline.leg(road, from: GeoPoint(lat: 40.8, lng: 69), to: GeoPoint(lat: 40.2, lng: 69))
        #expect(leg.map(\.lat) == [40.8, 40.2])
    }
}

/// The map's pure rules: the minimum camera span (Android `cameraBounds`) and the "tiles drawn" probe.
@Suite struct MapCameraTests {
    @Test func farPointsKeepTheirBounds() throws {
        let box = try #require(MapCamera.bounds([GeoPoint(lat: 41.3, lng: 69.2), GeoPoint(lat: 39.65, lng: 66.95)]))
        #expect(abs(box.southWest.lat - 39.65) < 1e-9 && abs(box.southWest.lng - 66.95) < 1e-9)
        #expect(abs(box.northEast.lat - 41.3) < 1e-9 && abs(box.northEast.lng - 69.2) < 1e-9)
    }

    @Test func nearPointsGrowToTheMinimumSpanAroundTheirCentre() throws {
        // Two places ~100 m apart: framed as at least 0.01 degrees each way, centred on their midpoint.
        let box = try #require(MapCamera.bounds([GeoPoint(lat: 41.3110, lng: 69.2790), GeoPoint(lat: 41.3118, lng: 69.2801)]))
        #expect(abs((box.northEast.lat - box.southWest.lat) - 0.01) < 1e-9)
        #expect(abs((box.northEast.lng - box.southWest.lng) - 0.01) < 1e-9)
        #expect(abs((box.northEast.lat + box.southWest.lat) / 2 - 41.3114) < 1e-9)
        #expect(abs((box.northEast.lng + box.southWest.lng) / 2 - 69.27955) < 1e-9)
    }

    @Test func onlyTheShortSideGrows() throws {
        // A north-south road: the latitude span stays, the longitude span is widened.
        let box = try #require(MapCamera.bounds([GeoPoint(lat: 40, lng: 69), GeoPoint(lat: 41, lng: 69.001)]))
        #expect(abs((box.northEast.lat - box.southWest.lat) - 1) < 1e-9)
        #expect(abs((box.northEast.lng - box.southWest.lng) - 0.01) < 1e-9)
    }

    @Test func noPointsNoBox() {
        #expect(MapCamera.bounds([]) == nil)
        let single = MapCamera.bounds([GeoPoint(lat: 41, lng: 69)])
        #expect(single.map { abs($0.northEast.lat - $0.southWest.lat - 0.01) < 1e-9 } == true)
    }

    @Test func probeTellsTheEmptyGridFromDrawnTiles() {
        // The loading grid: background, grid lines and a marker - a handful of colours, with antialiasing noise.
        let grid: [UInt32] = (0..<1152).map { i in [0xFFE9EDF1, 0xFFD5DAE0, 0xFF0096FF][i % 3] + UInt32(i % 2) }
        #expect(!MapCamera.looksDrawn(grid))
        // Drawn tiles: dozens of distinct colours.
        let tiles: [UInt32] = (0..<1152).map { i in 0xFF000000 | UInt32((i % 40) * 0x060504) }
        #expect(MapCamera.looksDrawn(tiles))
    }
}
