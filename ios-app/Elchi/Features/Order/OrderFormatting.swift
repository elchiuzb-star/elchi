import Foundation

/// How the order screens say places, figures and catalogue items in the active language.
extension LocaleStore {
    func name(_ region: RegionDTO) -> String { locale == .ru ? region.nameRu ?? region.nameUz : region.nameUz }
    func name(_ district: DistrictDTO) -> String { locale == .ru ? district.nameRu ?? district.nameUz : district.nameUz }

    /// The place itself (the design's card title): "Joriy joylashuv" for the locate button's fill, the verified stop,
    /// the street address, else the coordinates.
    func place(_ end: PlaceEnd) -> String {
        if end.currentLocation { return t("home.currentLocation") }
        if let stop = end.stop { return locale == .ru ? stop.nameRu ?? stop.nameUz : stop.nameUz }
        return end.address ?? end.point.text
    }

    /// `Samarqand, Samarqand viloyati` (district, region); one name where the region has no districts or both match.
    func area(_ end: PlaceEnd) -> String {
        let region = name(end.region), district = name(end.district)
        return end.region.requiresDistrict == false || district == region ? region : "\(district), \(region)"
    }

    /// The review's detail for an end: "Tasdiqlangan bekat · District, Region" for a stop.
    func areaDetail(_ end: PlaceEnd) -> String {
        end.stop == nil ? area(end) : t("orderForm.review.verifiedStop", ("where", area(end)))
    }

    /// `308 km · 4 soat 35 daqiqa`.
    func routeFigures(distanceM: Int, durationS: Int) -> String {
        let km = t("location.distanceKm", ("km", RouteFigures.kilometres(distanceM)))
        let (hours, minutes) = RouteFigures.duration(durationS)
        let time = hours == 0 ? t("app.duration.minutes", ("minutes", minutes))
            : minutes == 0 ? t("app.duration.hours", ("hours", hours))
            : t("app.duration.hoursMinutes", ("hours", hours), ("minutes", minutes))
        return "\(km) · \(time)"
    }

    func money(_ minor: Int) -> String { Money.format(minor: minor, currencyWord: t("common.soum")) }

    func parcelTypeName(_ type: ParcelType) -> String { tOrNil("app.parcelType.\(type.rawValue)") ?? type.rawValue }

    func name(_ category: ParcelCategoryDTO) -> String { locale == .ru ? category.nameRu ?? category.nameUz : category.nameUz }

    /// `30×20×20 sm gacha · 5 kg gacha`.
    func limits(_ category: ParcelCategoryDTO) -> String {
        t("parcelCategory.limits", ("length", category.maxLengthCm), ("width", category.maxWidthCm), ("height", category.maxHeightCm),
          ("weight", RouteFigures.kilograms(category.maxWeightG)))
    }

    /// `2026-09-01` -> `01.09.2026` (catalogue dates); anything else is shown as it came.
    func day(_ isoDate: String) -> String {
        let parts = isoDate.prefix(10).split(separator: "-")
        return parts.count == 3 ? "\(parts[2]).\(parts[1]).\(parts[0])" : isoDate
    }

    /// One sentence per server warning; the server's own message for a code the dictionary does not know yet.
    func warningText(_ warning: ApiWarning) -> String { tOrNil("warning.\(warning.code)") ?? warning.message }
}

extension ParcelCategoryDTO {
    /// The catalogue's `icon_key` as a kit icon (envelope, box_small/medium/large, bag).
    var icon: ElchiIcon {
        switch iconKey {
        case "envelope", "env": .env
        case "box_large": .archive
        case "bag": .bag
        default: .pkg
        }
    }
}

/// Case-, accent- and apostrophe-insensitive "contains" for the region and district search (`Farg'ona`,
/// `Fargʻona` and `fargona` all match).
enum SearchText {
    static func normalized(_ text: String) -> String {
        text.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: nil)
            .replacingOccurrences(of: #"['ʻʼ‘’`]"#, with: "", options: .regularExpression)
    }

    static func matches(_ name: String, _ query: String) -> Bool {
        let q = normalized(query.trimmingCharacters(in: .whitespaces))
        return q.isEmpty || normalized(name).contains(q)
    }
}

// MARK: - Departure window (BOSQICH 02 design)

extension LocaleStore {
    private func list(_ key: String) -> [String] { t(key).components(separatedBy: ",").map { $0.trimmingCharacters(in: .whitespaces) } }

    /// `Ya` / `Du` ... (Sunday first, as `Calendar.weekday`).
    func weekdayShort(_ date: Date) -> String {
        let names = list("client.order.picker.weekdays")
        let index = DepartureWindow.calendar.component(.weekday, from: date) - 1
        return names.indices.contains(index) ? names[index] : ""
    }

    func monthShort(_ date: Date) -> String {
        let names = list("client.order.picker.months")
        let index = DepartureWindow.calendar.component(.month, from: date) - 1
        return names.indices.contains(index) ? names[index] : ""
    }

    /// `Sentabr 2026` over the day strip.
    func monthTitle(_ date: Date) -> String {
        let names = list("client.order.picker.monthsFull")
        let c = DepartureWindow.calendar.dateComponents([.month, .year], from: date)
        let index = (c.month ?? 1) - 1
        return "\(names.indices.contains(index) ? names[index] : "") \(c.year ?? 0)"
    }

    /// `28 sen` (the design's month abbreviations).
    func shortDay(_ date: Date) -> String {
        "\(DepartureWindow.calendar.component(.day, from: date)) \(monthShort(date))"
    }

    /// The strip's top line: "Bugun", "Ertaga" or the weekday.
    func dayName(_ date: Date, now: Date = Date()) -> String {
        let calendar = DepartureWindow.calendar
        let days = calendar.dateComponents([.day], from: calendar.startOfDay(for: now), to: calendar.startOfDay(for: date)).day ?? 99
        return days == 0 ? t("driver.feed.dateToday") : days == 1 ? t("driver.feed.dateTomorrow") : weekdayShort(date)
    }

    /// A window tile's small line: `28 sen` today, `Ertaga, 28 sen`, `Pa, 2 okt`.
    func tileDate(_ date: Date, now: Date = Date()) -> String {
        let calendar = DepartureWindow.calendar
        let days = calendar.dateComponents([.day], from: calendar.startOfDay(for: now), to: calendar.startOfDay(for: date)).day ?? 99
        return days == 0 ? shortDay(date) : "\(dayName(date, now: now)), \(shortDay(date))"
    }

    /// `9 soat 30 daqiqa`.
    func duration(minutes: Int) -> String {
        let (hours, rest) = (minutes / 60, minutes % 60)
        return hours == 0 ? t("app.duration.minutes", ("minutes", rest))
            : rest == 0 ? t("app.duration.hours", ("hours", hours))
            : t("app.duration.hoursMinutes", ("hours", hours), ("minutes", rest))
    }

    /// "Oyna: 9 soat · Haydovchilar shu oraliqda jo'nashni taklif qiladi." (without the length while the order is wrong).
    func windowHint(start: Date?, end: Date?) -> String {
        let hint = t("routeSummary.windowHint")
        guard let start, let end, end > start else { return hint }
        return "\(t("client.order.windowLength", ("length", duration(minutes: WindowPicker.lengthMinutes(start: start, end: end))))) · \(hint)"
    }

    /// `27.09, 09:00 – 27.09, 18:00`.
    func windowLine(start: Date, end: Date) -> String {
        "\(DepartureWindow.shortText(start)) – \(DepartureWindow.shortText(end))"
    }

    /// "2 kishi" / "Butun salon" (the home's value next to "Necha kishi"), or "Tanlang".
    func seatValue(_ count: Int?) -> String {
        guard let count else { return t("client.order.choose") }
        return TaxiSeats.isWholeCabin(count) ? t("client.taxi.wholeCabin") : t("orderForm.review.peopleCount", ("count", count))
    }
}
