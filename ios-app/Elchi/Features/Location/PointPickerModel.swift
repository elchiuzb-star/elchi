import Foundation
import Observation

/// Step 3 of choosing a place (Q88): a point inside the chosen district. The camera centre is the point; its
/// address comes from our server's geocoder 400 ms after the pin stops; typed text is suggested 300 ms after the
/// last keystroke. Without a map the point is the district centre or a picked search result.
@MainActor @Observable
final class PointPickerModel {
    enum Address: Equatable {
        case resolving
        case found(String)
        /// The geocoder had no real address (`provider=local`) or failed: the screen shows coordinates.
        case unavailable
    }

    let region: RegionDTO
    /// Nil for a region without districts (Tashkent city): the nearest district is worked out when the point is chosen.
    let district: DistrictDTO?
    private let geo: GeoAPI
    private let locale: AppLocale

    /// The chosen point (the camera centre when a map is shown).
    private(set) var centre: GeoPoint
    /// Where the camera should go; changes only on a search pick or "district centre", never on a drag.
    private(set) var focus: GeoPoint
    private(set) var address: Address = .resolving

    var query = "" { didSet { if query != oldValue { scheduleSuggest() } } }
    private(set) var suggestions: [PlaceSuggestion] = []
    private(set) var searchMiss = false
    private(set) var searchError: Error?
    private(set) var resolving = false

    private var geocodeTask: Task<Void, Never>?
    private var suggestTask: Task<Void, Never>?

    init(region: RegionDTO, district: DistrictDTO?, current: PlaceEnd?, geo: GeoAPI, locale: AppLocale) {
        self.region = region
        self.district = district
        self.geo = geo
        self.locale = locale
        let start: GeoPoint
        if let current, current.region.id == region.id, district == nil || current.district.id == district?.id {
            start = current.point
            address = current.address.map(Address.found) ?? .unavailable
        } else {
            start = Self.centre(of: district, region: region)
        }
        centre = start
        focus = start
        if case .resolving = address { scheduleReverseGeocode(delay: 0) }
    }

    /// The district's centre, else the region's, else Tashkent.
    static func centre(of district: DistrictDTO?, region: RegionDTO) -> GeoPoint {
        if let lat = district?.centerLat, let lng = district?.centerLng { return GeoPoint(lat: lat, lng: lng) }
        if let lat = region.centerLat, let lng = region.centerLng { return GeoPoint(lat: lat, lng: lng) }
        return GeoPoint(lat: 41.3111, lng: 69.2797)
    }

    var districtCentre: GeoPoint { Self.centre(of: district, region: region) }

    /// The camera stopped: that centre is the point (ADR-0028: a place is always a marked point, never a stop).
    func cameraIdle(_ point: GeoPoint) {
        guard abs(point.lat - centre.lat) > 1e-6 || abs(point.lng - centre.lng) > 1e-6 else { return }
        centre = point
        address = .resolving
        scheduleReverseGeocode(delay: 400)
    }

    func useDistrictCentre() {
        move(to: districtCentre, address: nil)
    }

    /// A picked suggestion carries no coordinates: resolve it, then move there.
    func pick(_ suggestion: PlaceSuggestion) async {
        suggestTask?.cancel()
        resolving = true
        defer { resolving = false }
        do {
            let place = try await geo.resolvePlace(uri: suggestion.uri, language: locale)
            guard let lat = place.lat, let lng = place.lng else { searchMiss = true; return }
            suggestions = []
            query = ""
            searchMiss = false
            move(to: GeoPoint(lat: lat, lng: lng), address: (place.formattedAddress ?? suggestion.title).map(Self.withoutCountry))
        } catch {
            searchError = error
        }
    }

    private func move(to point: GeoPoint, address known: String?) {
        centre = point
        focus = point
        if let known {
            geocodeTask?.cancel()
            address = .found(known)
        } else {
            address = .resolving
            scheduleReverseGeocode(delay: 0)
        }
    }

    private func scheduleReverseGeocode(delay milliseconds: Int) {
        geocodeTask?.cancel()
        let point = centre
        geocodeTask = Task { [weak self] in
            if milliseconds > 0 { try? await Task.sleep(for: .milliseconds(milliseconds)) }
            guard let self, !Task.isCancelled else { return }
            let result = try? await geo.reverseGeocode(point, language: locale)
            guard !Task.isCancelled, point == centre else { return }
            if let result, !result.isLocal, let text = result.formattedAddress, !text.isEmpty {
                address = .found(Self.withoutCountry(text))
            } else {
                address = .unavailable
            }
        }
    }

    private func scheduleSuggest() {
        suggestTask?.cancel()
        searchMiss = false
        searchError = nil
        let text = query.trimmingCharacters(in: .whitespaces)
        guard text.count >= 2 else {
            suggestions = []
            return
        }
        let near = districtCentre
        let districtName = district?.nameUz
        suggestTask = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(300))
            guard let self, !Task.isCancelled else { return }
            do {
                let found = try await geo.suggest(text, near: near, district: districtName, language: locale)
                guard !Task.isCancelled else { return }
                suggestions = found
                searchMiss = found.isEmpty
            } catch {
                if !Task.isCancelled { searchError = error }
            }
        }
    }

    /// `Oʻzbekiston, Toshkent, ...` -> `Toshkent, ...`: every place here is in Uzbekistan, so the country is noise.
    nonisolated static func withoutCountry(_ address: String) -> String {
        let trimmed = address.replacingOccurrences(of: #"^(O[ʻ'‘’`]?zbekiston|Узбекистан|Uzbekistan),\s*"#, with: "", options: .regularExpression)
        return trimmed.isEmpty ? address : trimmed
    }

    var addressText: String? {
        if case .found(let text) = address { return text }
        return nil
    }

    /// The chosen end. A region without districts gets the nearest of its catalogue districts to the point (the
    /// preview needs a district id at both ends); nil when the catalogue has none with a centre.
    func makeEnd(regionDistricts: [DistrictDTO]) -> PlaceEnd? {
        guard let chosen = district ?? nearestDistrict(regionDistricts, to: centre) ?? regionDistricts.first else { return nil }
        return PlaceEnd(region: region, district: chosen, point: centre, address: addressText)
    }
}
