import Observation

/// Who to sign in again after "Sessiya tugadi": the phone step opens with this number filled in.
struct ReloginPrefill: Equatable {
    let phone: String
    let role: MobileRole
}

/// The session as SwiftUI state: follows sign-in, refresh and sign-out (also the HTTP layer's, when a refresh is
/// rejected) so the root view can switch between sign-in and the role's home. It also carries what the person must
/// be told about the session: "Sessiya tugadi" (once per expiry) and a sign-out notice ("Akkaunt o'chirildi").
@MainActor @Observable
final class SessionState {
    private(set) var session: Session?
    /// Set when the server refused the refresh token; the dialog shows until "Qayta kirish".
    private(set) var expired: ReloginPrefill?
    /// The sign-in flow to start after "Qayta kirish" (nil = the usual start).
    private(set) var relogin: ReloginPrefill?
    /// Bumped on "Qayta kirish" so the sign-in flow starts over on the phone step.
    private(set) var reloginCount = 0
    private(set) var notice: String?

    init(store: SessionStore, events: SessionEvents) {
        session = store.current()
        store.onChange { [weak self] session in
            Task { @MainActor in self?.session = session }
        }
        events.onEvent { [weak self] event in
            Task { @MainActor in self?.handle(event) }
        }
    }

    private func handle(_ event: SessionEvent) {
        switch event {
        case .expired(let phone, let role):
            // Once per expiry: a second refusal while the dialog is up says nothing new.
            guard expired == nil else { return }
            expired = ReloginPrefill(phone: phone, role: role ?? .client)
        case .notice(let text):
            relogin = nil
            notice = text
        }
    }

    func startRelogin() {
        relogin = expired
        expired = nil
        reloginCount += 1
    }

    func clearNotice() { notice = nil }
}
