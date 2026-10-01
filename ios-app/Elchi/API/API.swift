import Foundation

/// A successful v2 answer: `data`, plus the warnings (Q43, Q90) and the cursor page the envelope carried.
public struct APIResult<T: Sendable>: Sendable {
    public let data: T
    public let warnings: [ApiWarning]
    public let meta: PageMeta?
}

/// A refused or failed request. `code` is the server's `ErrorCode` (or `APIError.network` when nothing came
/// back); the UI turns it into a sentence, and shows `message` only for a code it does not know.
public struct APIError: Error, Sendable {
    public static let network = "NETWORK_ERROR"
    public static let server = "SERVER_ERROR"

    public let status: Int
    public let code: String
    public let message: String
    public let details: JSONValue?
}

/// A generated enum: `rawValue` is what goes on the wire (`"client"`).
public protocol WireEnum: Codable, Hashable, Sendable {
    var rawValue: String { get }
}

/// What the generated `ElchiAPI` needs; `HTTPTransport` is the real one.
public protocol APITransport: Sendable {
    func send<Body: Encodable & Sendable, T: Decodable & Sendable>(
        method: String,
        path: String,
        query: [(String, (any Sendable)?)],
        body: Body?,
        idempotencyKey: String?,
        as type: T.Type
    ) async throws -> APIResult<T>
}
