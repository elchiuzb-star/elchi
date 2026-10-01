import Foundation
import os

/// What happened to the session that the person must be told about, from any thread to the UI.
public enum SessionEvent: Sendable, Equatable {
    /// The server refused the refresh token: "Sessiya tugadi" once, then sign in again (phone pre-filled).
    case expired(phone: String, role: MobileRole?)
    /// The session ended on purpose with a sentence to show on the sign-in screen ("Akkaunt o'chirildi").
    case notice(String)
}

/// The channel between the HTTP layer (refresh refused) and the UI, plus the "we are signing out on purpose" window
/// in which a refused refresh is not an expiry (logout, a deleted account).
public final class SessionEvents: Sendable {
    private let listeners = OSAllocatedUnfairLock<[@Sendable (SessionEvent) -> Void]>(initialState: [])
    private let deliberate = OSAllocatedUnfairLock(initialState: 0)

    public init() {}

    public func onEvent(_ listener: @escaping @Sendable (SessionEvent) -> Void) {
        listeners.withLock { $0.append(listener) }
    }

    public func post(_ event: SessionEvent) {
        for listener in listeners.withLock({ $0 }) { listener(event) }
    }

    /// The transport gave up on this session (the refresh token was refused). Silent while signing out on purpose.
    public func refreshRejected(_ session: Session) {
        guard deliberate.withLock({ $0 }) == 0 else { return }
        post(.expired(phone: session.user.phone, role: session.user.mobileRole))
    }

    /// Runs a deliberate sign-out; a refresh refused meanwhile is part of it, not an expiry.
    public func deliberately<T: Sendable>(_ work: @Sendable () async -> T) async -> T {
        deliberate.withLock { $0 += 1 }
        defer { deliberate.withLock { $0 -= 1 } }
        return await work()
    }
}
