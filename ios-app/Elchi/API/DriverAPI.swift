import Foundation

/// The v1 driver profile (`GET /api/v1/driver/profile`): the source of the verification status the web uses, and of
/// the car the driver entered once (Q94). Hand-typed like `AuthAPI` (v1 is not generated, ADR-0010 §5).
public struct DriverProfileV1: Decodable, Hashable, Sendable {
    public struct User: Decodable, Hashable, Sendable {
        public let phone: String?
        public let fullName: String?
        enum CodingKeys: String, CodingKey {
            case phone
            case fullName = "full_name"
        }
    }

    public let id: Int
    public let user: User?
    public let fullName: String?
    public let carModel: String?
    public let carColor: String?
    public let plateNumber: String?
    /// `new | pending | approved | rejected | blocked`.
    public let verificationStatus: String
    public let rating: Double?
    public let completedOrders: Int?
    /// Legacy v1 counter (all orders ever taken on the old app), shown labelled as such.
    public let totalOrders: Int?
    public let isAvailable: Bool

    public init(id: Int, user: User? = nil, fullName: String? = nil, carModel: String? = nil, carColor: String? = nil,
                plateNumber: String? = nil, verificationStatus: String, rating: Double? = nil, completedOrders: Int? = nil,
                totalOrders: Int? = nil, isAvailable: Bool = false) {
        self.id = id
        self.user = user
        self.fullName = fullName
        self.carModel = carModel
        self.carColor = carColor
        self.plateNumber = plateNumber
        self.verificationStatus = verificationStatus
        self.rating = rating
        self.completedOrders = completedOrders
        self.totalOrders = totalOrders
        self.isAvailable = isAvailable
    }

    enum CodingKeys: String, CodingKey {
        case id, user, rating
        case fullName = "full_name"
        case carModel = "car_model"
        case carColor = "car_color"
        case plateNumber = "plate_number"
        case verificationStatus = "verification_status"
        case completedOrders = "completed_orders"
        case totalOrders = "total_orders"
        case isAvailable = "is_available"
    }
}

/// `PATCH /api/v1/driver/profile`: only the keys that are set go on the wire. A vehicle key that already holds a
/// value is refused with `DRIVER_VEHICLE_LOCKED` (Q94), so a locked profile sends the name alone.
public struct DriverProfilePatch: Encodable, Equatable, Sendable {
    public var fullName: String?
    public var carModel: String?
    public var carColor: String?
    public var plateNumber: String?

    public init(fullName: String? = nil, carModel: String? = nil, carColor: String? = nil, plateNumber: String? = nil) {
        self.fullName = fullName
        self.carModel = carModel
        self.carColor = carColor
        self.plateNumber = plateNumber
    }

    enum CodingKeys: String, CodingKey {
        case fullName = "full_name"
        case carModel = "car_model"
        case carColor = "car_color"
        case plateNumber = "plate_number"
    }
}

/// One row of `GET /api/v1/driver/documents` (one per type; no row = not uploaded). `file_url` is a signed link.
public struct DriverDocumentV1: Decodable, Hashable, Sendable {
    public let documentId: Int
    public let documentType: String
    public let fileUrl: String?
    /// `pending | approved | rejected`.
    public let status: String
    public let rejectionReason: String?

    public init(documentId: Int, documentType: String, fileUrl: String? = nil, status: String, rejectionReason: String? = nil) {
        self.documentId = documentId
        self.documentType = documentType
        self.fileUrl = fileUrl
        self.status = status
        self.rejectionReason = rejectionReason
    }

    enum CodingKeys: String, CodingKey {
        case status
        case documentId = "document_id"
        case documentType = "document_type"
        case fileUrl = "file_url"
        case rejectionReason = "rejection_reason"
    }
}

private struct DocumentSubmit: Encodable, Sendable {
    let documentType: String
    let fileUrl: String
    let mimeType: String?
    let sizeBytes: Int?
    enum CodingKeys: String, CodingKey {
        case documentType = "document_type"
        case fileUrl = "file_url"
        case mimeType = "mime_type"
        case sizeBytes = "size_bytes"
    }
}

private struct AvailabilityUpdate: Codable, Sendable {
    let isAvailable: Bool
    enum CodingKeys: String, CodingKey { case isAvailable = "is_available" }
}

/// `/api/v1/driver/*`: the profile, the car entered once, the five documents and availability. v2 has no driver
/// onboarding yet; the v2 vehicle (`POST /vehicles`) and wallet go through the generated `ElchiAPI`.
public struct DriverAPI: Sendable {
    let transport: HTTPTransport

    /// A non-driver gets 403.
    public func profile() async throws -> DriverProfileV1 {
        try await transport.sendV1(method: "GET", path: "/driver/profile", body: Optional<JSONValue>.none, auth: true, as: DriverProfileV1.self).data
    }

    /// Answers a smaller dict than `profile()`; the caller reads the profile again.
    public func updateProfile(_ patch: DriverProfilePatch) async throws {
        _ = try await transport.sendV1(method: "PATCH", path: "/driver/profile", body: patch, auth: true, as: JSONValue.self)
    }

    public func documents() async throws -> [DriverDocumentV1] {
        try await transport.sendV1(method: "GET", path: "/driver/documents", body: Optional<JSONValue>.none, auth: true,
                                   as: [DriverDocumentV1].self).data
    }

    /// Step 2 of an upload: the `file_url` from `/files/upload` becomes the document of that type (a re-upload
    /// replaces the row and puts it back to pending; `new`/`rejected` drivers move to `pending`).
    public func submitDocument(type: String, fileUrl: String, mimeType: String?, sizeBytes: Int?) async throws {
        _ = try await transport.sendV1(method: "POST", path: "/driver/documents",
                                       body: DocumentSubmit(documentType: type, fileUrl: fileUrl, mimeType: mimeType, sizeBytes: sizeBytes),
                                       auth: true, as: JSONValue.self)
    }

    /// Turning on: 400 `DRIVER_NOT_APPROVED`, 403 `DRIVER_BLOCKED`. Turning off always works.
    public func setAvailability(_ on: Bool) async throws -> Bool {
        try await transport.sendV1(method: "PATCH", path: "/driver/availability", body: AvailabilityUpdate(isAvailable: on), auth: true,
                                   as: AvailabilityUpdate.self).data.isAvailable
    }
}
