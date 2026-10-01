import Foundation

/// How the order screens say places, figures and catalogue items in the active language.
extension LocaleStore {
    func name(_ region: RegionDTO) -> String { locale == .ru ? region.nameRu ?? region.nameUz : region.nameUz }
    func name(_ district: DistrictDTO) -> String { locale == .ru ? district.nameRu ?? district.nameUz : district.nameUz }

    /// The place's name on the route card: the district, or the region itself where it has no districts.
    func title(_ end: PlaceEnd) -> String {
        end.region.requiresDistrict == false ? name(end.region) : name(end.district)
    }

    /// Street address, or "Xaritadagi joy" when the geocoder had none.
    func address(_ end: PlaceEnd) -> String { end.address ?? t("app.endLabel.mapPlace") }

    /// `Samarqand viloyati / Samarqand` (region / district), or just the region where it has no districts.
    func area(_ end: PlaceEnd) -> String {
        end.region.requiresDistrict == false ? name(end.region) : "\(name(end.region)) / \(name(end.district))"
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
