import Foundation

// MARK: - One legacy order (v1)

/// `GET /api/v1/client/orders/{id}`: a v1 order with everything its archive screen shows (Q4: the order lives out its
/// life on v1 and is never copied into v2). Money is DECIMAL so'm (`LegacyMoney`), coordinates and the rating are DECIMAL too (a number or a string),
/// timestamps may be naive (read as UTC by `ServerTime`).
public struct LegacyOrderDetail: Decodable, Hashable, Sendable, Identifiable {
    public struct City: Decodable, Hashable, Sendable {
        public let id: Int?
        public let nameUz: String?

        enum CodingKeys: String, CodingKey {
            case id
            case nameUz = "name_uz"
        }
    }

    /// The driver once one is chosen. `phone` is v1's own rule (the old app called the driver; v1 has no chat).
    public struct Driver: Decodable, Hashable, Sendable {
        public let id: Int?
        public let fullName: String?
        public let phone: String?
        public let carModel: String?
        public let plateNumber: String?
        public let rating: JSONValue?
        public let completedOrders: Int?

        enum CodingKeys: String, CodingKey {
            case id, phone, rating
            case fullName = "full_name"
            case carModel = "car_model"
            case plateNumber = "plate_number"
            case completedOrders = "completed_orders"
        }
    }

    public let id: Int
    public let orderNumber: String?
    public let status: String
    public let fromCity: City?
    public let toCity: City?
    public let fromDistrict: LegacyOrder.District?
    public let toDistrict: LegacyOrder.District?
    public let pickupAddress: String?
    public let dropoffAddress: String?
    public let pickupLat: JSONValue?
    public let pickupLng: JSONValue?
    public let dropoffLat: JSONValue?
    public let dropoffLng: JSONValue?
    public let senderPhone: String?
    public let receiverPhone: String?
    public let cargoPhotoUrl: String?
    public let comment: String?
    public let suggestedPrice: JSONValue?
    public let clientPrice: JSONValue?
    public let finalPrice: JSONValue?
    public let assignedDriver: Driver?
    public let acceptedBidId: Int?
    public let bidsCount: Int?
    public let createdAt: String?

    enum CodingKeys: String, CodingKey {
        case id, status, comment
        case orderNumber = "order_number"
        case fromCity = "from_city"
        case toCity = "to_city"
        case fromDistrict = "from_district"
        case toDistrict = "to_district"
        case pickupAddress = "pickup_address"
        case dropoffAddress = "dropoff_address"
        case pickupLat = "pickup_lat"
        case pickupLng = "pickup_lng"
        case dropoffLat = "dropoff_lat"
        case dropoffLng = "dropoff_lng"
        case senderPhone = "sender_phone"
        case receiverPhone = "receiver_phone"
        case cargoPhotoUrl = "cargo_photo_url"
        case suggestedPrice = "suggested_price"
        case clientPrice = "client_price"
        case finalPrice = "final_price"
        case assignedDriver = "assigned_driver"
        case acceptedBidId = "accepted_bid_id"
        case bidsCount = "bids_count"
        case createdAt = "created_at"
    }

    /// `final_price ?? client_price ?? suggested_price`, in minor units.
    public var priceMinor: Int? { LegacyMoney.price(final: finalPrice, client: clientPrice, suggested: suggestedPrice) }

    public var pickup: GeoPoint? { LegacyMapPoints.point(pickupLat, pickupLng) }
    public var dropoff: GeoPoint? { LegacyMapPoints.point(dropoffLat, dropoffLng) }
}

/// `GET /{id}/bids`: an active bid, cheapest first. The driver's phone is not in it (only after the choice).
public struct LegacyBid: Decodable, Hashable, Sendable, Identifiable {
    public struct Driver: Decodable, Hashable, Sendable {
        public let fullName: String?
        public let carModel: String?
        public let plateNumber: String?
        public let rating: JSONValue?
        public let completedOrders: Int?

        enum CodingKeys: String, CodingKey {
            case rating
            case fullName = "full_name"
            case carModel = "car_model"
            case plateNumber = "plate_number"
            case completedOrders = "completed_orders"
        }
    }

    public let id: Int
    public let price: JSONValue?
    public let status: String?
    public let createdAt: String?
    public let driver: Driver?

    enum CodingKeys: String, CodingKey {
        case id, price, status, driver
        case createdAt = "created_at"
    }

    public var priceMinor: Int? { LegacyMoney.minor(price) }
}

// MARK: - Calls

/// What is left to do on a v1 order: choose a driver, confirm the delivery, rate, cancel, report a problem. Never
/// create, edit or publish (Q4). Hand-typed like `AuthAPI`; answers the commands do not need are read as raw JSON.
extension LegacyOrdersAPI {
    private struct SelectDriver: Encodable, Sendable {
        let bidId: Int
        enum CodingKeys: String, CodingKey { case bidId = "bid_id" }
    }

    private struct Rating: Encodable, Sendable {
        let rating: Int
        let comment: String?
    }

    private struct Cancel: Encodable, Sendable {
        let reason: String
    }

    public func order(_ id: Int) async throws -> LegacyOrderDetail {
        try await transport.sendV1(method: "GET", path: "/client/orders/\(id)", body: Optional<JSONValue>.none, auth: true,
                                   as: LegacyOrderDetail.self).data
    }

    public func bids(_ id: Int) async throws -> [LegacyBid] {
        try await transport.sendV1(method: "GET", path: "/client/orders/\(id)/bids", body: Optional<JSONValue>.none, auth: true,
                                   as: [LegacyBid].self).data
    }

    public func selectDriver(_ id: Int, bidId: Int) async throws {
        _ = try await transport.sendV1(method: "POST", path: "/client/orders/\(id)/select-driver", body: SelectDriver(bidId: bidId),
                                       auth: true, as: JSONValue.self)
    }

    public func confirm(_ id: Int) async throws {
        _ = try await transport.sendV1(method: "POST", path: "/client/orders/\(id)/confirm", body: Optional<JSONValue>.none, auth: true,
                                       as: JSONValue.self)
    }

    public func rate(_ id: Int, stars: Int, comment: String?) async throws {
        _ = try await transport.sendV1(method: "POST", path: "/client/orders/\(id)/rating", body: Rating(rating: stars, comment: comment),
                                       auth: true, as: JSONValue.self)
    }

    /// `reason` is stored text: the web client sends the Uzbek sentence, and so does this app.
    public func cancel(_ id: Int, reason: String) async throws {
        _ = try await transport.sendV1(method: "POST", path: "/client/orders/\(id)/cancel", body: Cancel(reason: reason), auth: true,
                                       as: JSONValue.self)
    }
}
