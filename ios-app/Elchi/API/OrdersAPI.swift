import Foundation

// MARK: - The client's booking (v2)

/// `BookingClientDTO`: a booking as its client sees it (Q16 - no fee, commission or wallet fields). The generated
/// API returns the booking union (`BookingDTO | BookingClientDTO`) as raw JSON; `from(_:)` keeps only the client
/// side, told apart by `viewer_side == "client"`. Typed: what the orders list and the booking's screens show (Stage 04
/// adds the driver and vehicle, the contact rules, the parcel photo and category, the cancellation).
public struct ClientBookingDTO: Codable, Hashable, Sendable, Identifiable {
    /// One end of the booking (`BookingEndDTO`, ADR-0028): the agreed map point (Q88), its time window and the
    /// arrival estimated from its road position.
    public struct End: Codable, Hashable, Sendable {
        public let point: PointEndDTO?
        public let windowStart: String?
        public let windowEnd: String?
        public let plannedArrivalAt: String?

        enum CodingKeys: String, CodingKey {
            case point
            case windowStart = "window_start"
            case windowEnd = "window_end"
            case plannedArrivalAt = "planned_arrival_at"
        }
    }

    public struct Cancelled: Codable, Hashable, Sendable {
        public let bySide: String
        public let reasonCode: String
        public let faultSide: String?
        public let at: String

        enum CodingKeys: String, CodingKey {
            case at
            case bySide = "by_side"
            case reasonCode = "reason_code"
            case faultSide = "fault_side"
        }
    }

    /// Q64: after accept the make, colour and a masked plate; the full plate only from `plate_number_visible_from`
    /// (trip boarding or 30 minutes before the pickup window).
    public struct Vehicle: Codable, Hashable, Sendable {
        public let vehicleClass: String
        public let seatCapacity: Int
        public let makeModel: String
        public let color: String
        public let plateMasked: String
        public let plateNumber: String?
        public let plateNumberVisibleFrom: String?

        enum CodingKeys: String, CodingKey {
            case color
            case vehicleClass = "vehicle_class"
            case seatCapacity = "seat_capacity"
            case makeModel = "make_model"
            case plateMasked = "plate_masked"
            case plateNumber = "plate_number"
            case plateNumberVisibleFrom = "plate_number_visible_from"
        }
    }

    /// The driver as the client sees it after accept: first name only, the vehicle, and the phone once the service
    /// has started (Q44/Q142: parcel = the trip departed).
    public struct Driver: Codable, Hashable, Sendable {
        public let id: String
        public let displayName: String
        public let vehicle: Vehicle
        public let contactPhone: String?

        enum CodingKeys: String, CodingKey {
            case id, vehicle
            case displayName = "display_name"
            case contactPhone = "contact_phone"
        }
    }

    public struct Contact: Codable, Hashable, Sendable {
        public let phonesVisible: Bool
        public let visibleFrom: String?
        public let visibleUntil: String?
        public let chatThreadId: String?
        public let supportAvailable: Bool?

        enum CodingKeys: String, CodingKey {
            case phonesVisible = "phones_visible"
            case visibleFrom = "visible_from"
            case visibleUntil = "visible_until"
            case chatThreadId = "chat_thread_id"
            case supportAvailable = "support_available"
        }
    }

    /// Q6: the cargo photo as a short-lived signed link; re-reading the booking mints a fresh one.
    public struct Photo: Codable, Hashable, Sendable {
        public let fileId: String?
        public let url: String

        enum CodingKeys: String, CodingKey {
            case url
            case fileId = "file_id"
        }
    }

    public struct ListingIds: Codable, Hashable, Sendable {
        public let request: String?
        public let supply: String?
    }

    /// Q7: the driver reported a no-show; `pending` until an operator confirms or rejects it.
    public struct NoShowReview: Codable, Hashable, Sendable {
        public let status: String
        public let reportedAt: String?
        public let decidedAt: String?

        enum CodingKeys: String, CodingKey {
            case status
            case reportedAt = "reported_at"
            case decidedAt = "decided_at"
        }
    }

    public let id: String
    public let viewerSide: String
    public let serviceType: ServiceType
    public let serviceStatus: String
    /// Passenger: `unpaid`, `reported_paid`, `acknowledged`, `contested` (a string: a new value must not break decoding).
    public let cashStatus: String?
    /// Every command on the booking sends it back as `expected_version`.
    public let version: Int
    public let pickup: End
    public let dropoff: End
    public let quantity: Int
    /// `per_seat` for a passenger booking (the total is quantity x unit), `total` for a parcel.
    public let priceBasis: PriceBasis?
    public let unitPriceMinor: Int
    public let totalMinor: Int
    public let currency: String
    /// Q145: whether an amendment may change the quantity (false for every booking made on a client request, D9).
    public let quantityAmendable: Bool?
    /// The newest cash record (passenger), so the other side can answer it after a reload.
    public let cashReceipt: CashReceiptDTO?
    public let noShowReview: NoShowReview?
    /// Present only on a discounted booking: the client then hands over `cash_due_minor`, not the total.
    public let promo: BookingPromoClientDTO?
    public let createdAt: String
    public let updatedAt: String?
    public let cancelled: Cancelled?
    public let listingIds: ListingIds?
    /// Q140: the agreed size category, frozen on the booking.
    public let parcelCategory: ParcelCategoryDTO?
    public let driver: Driver?
    public let contact: Contact?
    public let parcelPhoto: Photo?
    /// The server's one-line cancellation policy (Uzbek only, so the screens say it from the dictionary).
    public let cancellationPolicySummary: String?

    enum CodingKeys: String, CodingKey {
        case id, version, pickup, dropoff, quantity, currency, promo, cancelled, driver, contact
        case viewerSide = "viewer_side"
        case serviceType = "service_type"
        case serviceStatus = "service_status"
        case cashStatus = "cash_status"
        case unitPriceMinor = "unit_price_minor"
        case priceBasis = "price_basis"
        case quantityAmendable = "quantity_amendable"
        case cashReceipt = "cash_receipt"
        case noShowReview = "no_show_review"
        case totalMinor = "total_minor"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case listingIds = "listing_ids"
        case parcelCategory = "parcel_category"
        case parcelPhoto = "parcel_photo"
        case cancellationPolicySummary = "cancellation_policy_summary"
    }

    /// The cash that changes hands: the discounted amount when a bonus applies, the agreed total otherwise.
    public var cashDueMinor: Int { promo?.cashDueMinor ?? totalMinor }

    /// The client side of the union, or nil for anything else (a driver view never belongs in the client's list).
    public static func from(_ json: JSONValue) -> ClientBookingDTO? {
        guard json["viewer_side"] == .string("client") else { return nil }
        return try? json.decode(ClientBookingDTO.self)
    }
}

// MARK: - Legacy orders (v1, read-only)

/// A v1 order (Q4: read-only in the new app). Prices are DECIMAL so'm - not minor units - and arrive as a number or
/// a string depending on the serializer, so they stay raw here and `LegacyMoney` reads them.
public struct LegacyOrder: Decodable, Hashable, Sendable, Identifiable {
    public struct District: Decodable, Hashable, Sendable {
        public let nameUz: String?
        public let nameRu: String?

        enum CodingKeys: String, CodingKey {
            case nameUz = "name_uz"
            case nameRu = "name_ru"
        }
    }

    public let id: Int
    public let orderNumber: String?
    public let status: String
    public let fromCity: String?
    public let toCity: String?
    public let fromDistrict: District?
    public let toDistrict: District?
    public let cargoType: String?
    public let suggestedPrice: JSONValue?
    public let clientPrice: JSONValue?
    public let finalPrice: JSONValue?
    public let bidsCount: Int?
    public let createdAt: String?

    enum CodingKeys: String, CodingKey {
        case id, status
        case orderNumber = "order_number"
        case fromCity = "from_city"
        case toCity = "to_city"
        case fromDistrict = "from_district"
        case toDistrict = "to_district"
        case cargoType = "cargo_type"
        case suggestedPrice = "suggested_price"
        case clientPrice = "client_price"
        case finalPrice = "final_price"
        case bidsCount = "bids_count"
        case createdAt = "created_at"
    }

    /// What the order was agreed at, else what the client asked, else the tariff's suggestion
    /// (`final_price ?? client_price ?? suggested_price`), in minor units.
    public var priceMinor: Int? { LegacyMoney.price(final: finalPrice, client: clientPrice, suggested: suggestedPrice) }

    init(id: Int, orderNumber: String?, status: String, fromCity: String?, toCity: String?, fromDistrict: District?, toDistrict: District?,
         cargoType: String?, suggestedPrice: JSONValue?, clientPrice: JSONValue?, finalPrice: JSONValue?, bidsCount: Int?, createdAt: String?) {
        self.id = id
        self.orderNumber = orderNumber
        self.status = status
        self.fromCity = fromCity
        self.toCity = toCity
        self.fromDistrict = fromDistrict
        self.toDistrict = toDistrict
        self.cargoType = cargoType
        self.suggestedPrice = suggestedPrice
        self.clientPrice = clientPrice
        self.finalPrice = finalPrice
        self.bidsCount = bidsCount
        self.createdAt = createdAt
    }

    /// The same row after its detail was re-read (a command moved it on).
    func with(status: String, bidsCount: Int?, finalPrice: JSONValue?) -> LegacyOrder {
        LegacyOrder(id: id, orderNumber: orderNumber, status: status, fromCity: fromCity, toCity: toCity, fromDistrict: fromDistrict,
                    toDistrict: toDistrict, cargoType: cargoType, suggestedPrice: suggestedPrice, clientPrice: clientPrice,
                    finalPrice: finalPrice ?? self.finalPrice, bidsCount: bidsCount ?? self.bidsCount, createdAt: createdAt)
    }
}

/// One page of `GET /client/orders`: the cards and v1's page counter.
public struct LegacyOrderPage: Decodable, Sendable {
    public struct Pagination: Decodable, Sendable {
        public let page: Int
        public let totalPages: Int

        enum CodingKeys: String, CodingKey {
            case page
            case totalPages = "total_pages"
        }
    }

    public let items: [LegacyOrder]
    public let pagination: Pagination?

    /// v1 pages by number; another page exists while this one is short of `total_pages` (a page without the counter
    /// ends the list).
    public var hasMore: Bool { pagination.map { $0.page < $0.totalPages } ?? false }
}

/// `/api/v1/client/orders` - hand-typed like GeoAPI (v1 is not in the generated contract). Most accounts have
/// none; a person whose `users.role` is not client gets 403, which the list treats as "nothing to show". The
/// detail and its commands are in `LegacyOrderAPI.swift`.
public struct LegacyOrdersAPI: Sendable {
    let transport: HTTPTransport

    public static let pageSize = 20

    public func clientOrders(page: Int = 1, limit: Int = pageSize) async throws -> LegacyOrderPage {
        try await transport.sendV1(method: "GET", path: "/client/orders", query: [("page", page), ("limit", limit)],
                                   body: Optional<JSONValue>.none, auth: true, as: LegacyOrderPage.self).data
    }
}
