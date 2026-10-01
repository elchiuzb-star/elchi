import Foundation

/// The one Stage 08 call the generated client cannot make as typed: `GET /feed` is described as returning the whole
/// `FeedEnvelope` (items plus `meta.degraded` / `next_cursor`), so it is decoded as that, not as `data`.
public struct MarketAPI: Sendable {
    let transport: HTTPTransport

    public init(transport: HTTPTransport) { self.transport = transport }

    /// The driver's matching requests: always `side=requests`, `include_alternatives=true` (Q97), `sort=recommended`.
    public func feed(_ query: FeedQuery, cursor: String? = nil, limit: Int = 50) async throws -> FeedEnvelope {
        try await transport.sendWhole(path: "/feed", query: [
            ("service_type", query.serviceType), ("side", FeedSide.requests), ("date_from", query.dateFrom), ("date_to", query.dateTo),
            ("origin_region_id", query.originRegionId), ("origin_district_id", query.originDistrictId),
            ("destination_region_id", query.destinationRegionId), ("destination_district_id", query.destinationDistrictId),
            ("sort", FeedSort.recommended), ("include_alternatives", true), ("cursor", cursor), ("limit", limit),
        ], as: FeedEnvelope.self)
    }
}
