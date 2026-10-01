import Foundation

struct RefreshRequest: Codable, Sendable {
    let refreshToken: String
    enum CodingKeys: String, CodingKey { case refreshToken = "refresh_token" }
}

struct TokenResponse: Codable, Sendable {
    let accessToken: String
    let refreshToken: String
    let user: AuthUser
    enum CodingKeys: String, CodingKey {
        case user
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
    }
}

public struct OTPSent: Codable, Sendable {
    public let otpSent: Bool
    public let phone: String
    /// Only when the backend runs without SMS (development); the verify screen shows it.
    public let devOtp: String?
    /// The server's cooldown before another code may be requested.
    public let resendAfterSeconds: Int?
    enum CodingKeys: String, CodingKey {
        case phone
        case otpSent = "otp_sent"
        case devOtp = "dev_otp"
        case resendAfterSeconds = "resend_after_seconds"
    }
}

private struct OTPRequest: Codable, Sendable {
    let phone: String
    let role: String
}

private struct OTPVerify: Codable, Sendable {
    let phone: String
    let role: String
    let otp: String
}

/// Auth stays on `/api/v1` (ADR-0006); the token it issues is accepted by v2.
public struct AuthAPI: Sendable {
    let transport: HTTPTransport

    public func requestOTP(phone: String, role: MobileRole) async throws -> OTPSent {
        try await transport.sendV1(method: "POST", path: "/auth/request-otp", body: OTPRequest(phone: phone, role: role.rawValue), auth: false, as: OTPSent.self).data
    }

    func verifyOTP(phone: String, role: MobileRole, otp: String) async throws -> TokenResponse {
        try await transport.sendV1(method: "POST", path: "/auth/verify-otp", body: OTPVerify(phone: phone, role: role.rawValue, otp: otp), auth: false, as: TokenResponse.self).data
    }

    /// The signed-in user (v1 answers this one without the envelope).
    public func me() async throws -> AuthUser {
        try await transport.sendV1(method: "GET", path: "/auth/me", body: Optional<JSONValue>.none, auth: true, bare: true, as: AuthUser.self).data
    }

    public func logout(refreshToken: String) async throws {
        _ = try await transport.sendV1(method: "POST", path: "/auth/logout", body: RefreshRequest(refreshToken: refreshToken), auth: true, as: JSONValue.self)
    }
}
