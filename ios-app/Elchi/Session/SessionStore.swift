import Foundation
import Observation
import os
import Security

/// The v1 `/auth/me` user as the auth endpoints return it (v1 is hand-typed by design, ADR-0010 §5).
public struct AuthUser: Codable, Hashable, Sendable {
    public let id: Int
    public let phone: String
    public let fullName: String?
    public let role: String
    public let status: String?

    public var mobileRole: MobileRole? { MobileRole(rawValue: role) }

    enum CodingKeys: String, CodingKey {
        case id, phone, role, status
        case fullName = "full_name"
    }
}

public enum MobileRole: String, Codable, Sendable {
    case client, driver
}

public struct Session: Codable, Hashable, Sendable {
    public let accessToken: String
    public let refreshToken: String
    public let user: AuthUser
}

/// Where the HTTP layer reads and replaces the session (a fake in tests).
public protocol SessionStorage: Sendable {
    func current() -> Session?
    func save(_ session: Session)
    func clear()
}

/// The signed-in session in the Keychain (this device only, readable after first unlock). Loaded once at start,
/// then served from memory; `onChange` lets the UI follow sign-in, refresh and sign-out.
public final class SessionStore: SessionStorage, @unchecked Sendable {
    private let service = "uz.elchi.app.session"
    private let state: OSAllocatedUnfairLock<Session?>
    private let listeners = OSAllocatedUnfairLock<[@Sendable (Session?) -> Void]>(initialState: [])

    public init() {
        state = OSAllocatedUnfairLock(initialState: nil)
        state.withLock { $0 = load() }
    }

    public func current() -> Session? { state.withLock { $0 } }

    public func save(_ session: Session) {
        guard let data = try? JSONEncoder().encode(session) else { return }
        delete()
        let item: [String: Any] = base.merging([
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]) { $1 }
        SecItemAdd(item as CFDictionary, nil)
        state.withLock { $0 = session }
        notify(session)
    }

    public func clear() {
        delete()
        state.withLock { $0 = nil }
        notify(nil)
    }

    public func onChange(_ listener: @escaping @Sendable (Session?) -> Void) {
        listeners.withLock { $0.append(listener) }
    }

    private var base: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: "session"]
    }

    private func load() -> Session? {
        var result: AnyObject?
        let query = base.merging([kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]) { $1 }
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess, let data = result as? Data else { return nil }
        return try? JSONDecoder().decode(Session.self, from: data)
    }

    private func delete() {
        SecItemDelete(base as CFDictionary)
    }

    private func notify(_ session: Session?) {
        for listener in listeners.withLock({ $0 }) { listener(session) }
    }
}
