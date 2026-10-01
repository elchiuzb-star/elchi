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
