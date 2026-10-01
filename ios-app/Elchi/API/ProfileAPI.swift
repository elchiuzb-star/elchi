import Foundation

/// `PATCH /api/v1/client/profile` - v2 has no profile update, so the name goes through v1 (hand-typed like `AuthAPI`).
/// The server filters contact details out of the name itself; a blank name is `400 VALIDATION_ERROR`.
public struct ClientProfileAPI: Sendable {
    let transport: HTTPTransport

    private struct Update: Codable, Sendable {
        let fullName: String
        enum CodingKeys: String, CodingKey { case fullName = "full_name" }
    }

    public struct Profile: Decodable, Sendable {
        public let fullName: String?
        enum CodingKeys: String, CodingKey { case fullName = "full_name" }
    }

    public func updateName(_ fullName: String) async throws -> Profile {
        try await transport.sendV1(method: "PATCH", path: "/client/profile", body: Update(fullName: fullName), auth: true, as: Profile.self).data
    }
}

extension ElchiAPI {
    /// `DELETE /blocks/{user_id}` with the Idempotency-Key the server's handler requires (the generated call sends
    /// none). Answered as raw JSON: the success body is not something the screen reads.
    func unblock(userId: String, idempotencyKey: String) async throws {
        _ = try await transport.send(method: "DELETE", path: "/blocks/\(userId)", query: [], body: Optional<JSONValue>.none,
                                     idempotencyKey: idempotencyKey, as: JSONValue.self)
    }
}
