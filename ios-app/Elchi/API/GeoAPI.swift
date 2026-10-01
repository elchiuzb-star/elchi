import Foundation

/// A place name for a pin, or coordinates for a picked suggestion (`/api/v1/geo/*`, hand-typed like AuthAPI).
public struct GeocodeResult: Codable, Hashable, Sendable {
    public let formattedAddress: String?
    public let lat: Double?
    public let lng: Double?
    public let region: String?
    public let district: String?
    /// `yandex`, or `local` when the server had no real address (then the address is only a district name or
    /// coordinates, and the screen shows coordinates).
    public let provider: String?

    public var isLocal: Bool { provider == "local" }

    enum CodingKeys: String, CodingKey {
        case lat, lng, region, district, provider
        case formattedAddress = "formatted_address"
    }
}

/// A typed-text suggestion. It carries no coordinates: `resolvePlace(uri:)` turns the picked one into a point.
public struct PlaceSuggestion: Codable, Hashable, Sendable, Identifiable {
    public let title: String?
    public let subtitle: String?
    public let formattedAddress: String?
    public let distanceM: Int?
    public let uri: String

    public var id: String { uri }

    enum CodingKeys: String, CodingKey {
        case title, subtitle, uri
        case formattedAddress = "formatted_address"
        case distanceM = "distance_m"
    }
}

private struct SuggestList: Codable, Sendable {
    let results: [PlaceSuggestion]
}

private struct ReverseRequest: Codable, Sendable {
    let lat: Double
    let lng: Double
    let language: String
}

private struct SuggestRequest: Codable, Sendable {
    let text: String
    let language: String
    let nearLat: Double?
    let nearLng: Double?
    let spanDeg: Double?
    let district: String?
    let limit: Int

    enum CodingKeys: String, CodingKey {
        case text, language, district, limit
        case nearLat = "near_lat"
        case nearLng = "near_lng"
        case spanDeg = "span_deg"
    }
}

private struct ResolveRequest: Codable, Sendable {
    let uri: String
    let language: String
}

/// Geocoding goes through our server: the Yandex geocoder and suggest keys live only on the backend, never in the app.
public struct GeoAPI: Sendable {
    let transport: HTTPTransport

    public func reverseGeocode(_ point: GeoPoint, language: AppLocale) async throws -> GeocodeResult {
        try await transport.sendV1(method: "POST", path: "/geo/reverse-geocode",
                                   body: ReverseRequest(lat: point.lat, lng: point.lng, language: language.rawValue),
                                   auth: false, as: GeocodeResult.self).data
    }

    /// Places for typed text, ranked towards the chosen district (its centre and name); nothing outside is hidden.
    public func suggest(_ text: String, near: GeoPoint?, district: String?, language: AppLocale) async throws -> [PlaceSuggestion] {
        let body = SuggestRequest(text: text, language: language.rawValue, nearLat: near?.lat, nearLng: near?.lng,
                                  spanDeg: near == nil ? nil : 0.35, district: district, limit: 10)
        return try await transport.sendV1(method: "POST", path: "/geo/suggest", body: body, auth: false, as: SuggestList.self).data.results
    }

    /// Coordinates for a picked suggestion; `GEOCODE_FAILED` when the provider cannot place it.
    public func resolvePlace(uri: String, language: AppLocale) async throws -> GeocodeResult {
        try await transport.sendV1(method: "POST", path: "/geo/resolve-place", body: ResolveRequest(uri: uri, language: language.rawValue),
                                   auth: false, as: GeocodeResult.self).data
    }
}

/// `POST /api/v1/files/upload` answer. `file_url` is what `parcel.photo_file_id` takes.
public struct UploadedFile: Codable, Hashable, Sendable {
    public let fileUrl: String
    public let type: String?
    public let mimeType: String?
    public let sizeBytes: Int?

    enum CodingKeys: String, CodingKey {
        case type
        case fileUrl = "file_url"
        case mimeType = "mime_type"
        case sizeBytes = "size_bytes"
    }
}

public struct FilesAPI: Sendable {
    let transport: HTTPTransport

    /// Uploads a parcel photo (`type=cargo_photo`; the form field is `type`, see app/api/v1/files.py).
    public func uploadCargoPhoto(jpeg: Data) async throws -> UploadedFile {
        try await upload(type: "cargo_photo", data: jpeg, filename: "parcel.jpg", mimeType: "image/jpeg")
    }

    /// Any v1 upload type (`cargo_photo`, a driver document type such as `passport`). The server checks the file's
    /// extension, declared type and magic bytes against the upload type, so `filename` must end in the real
    /// extension (`.jpg`, `.pdf`). `FILE_TOO_LARGE` comes back as 413.
    public func upload(type: String, data: Data, filename: String, mimeType: String) async throws -> UploadedFile {
        var form = MultipartForm()
        form.field("type", type)
        form.file("file", filename: filename, mimeType: mimeType, data: data)
        form.finish()
        return try await transport.uploadV1(path: "/files/upload", form: form, as: UploadedFile.self).data
    }
}
