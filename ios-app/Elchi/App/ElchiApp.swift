import SwiftUI

/// Manual dependency wiring: one instance of each for the whole process.
final class AppContainer: Sendable {
    let sessions = SessionStore()
    /// Session expiry and sign-out notices, from the HTTP layer to the UI.
    let events = SessionEvents()
    let transport: HTTPTransport
    let auth: AuthAPI
    let clientProfile: ClientProfileAPI
    let api: ElchiAPI
    let geo: GeoAPI
    let files: FilesAPI
    let driver: DriverAPI
    let legacyOrders: LegacyOrdersAPI
    /// The app's one status banner (ok / err / warn / info, and the loading line), drawn over every screen.
    let banners: BannerCenter
    /// Opened links (`elchi://…`, the `elchigo.uz/r/<code>` Universal Link) and the kept referral code.
    let links: DeepLinkCenter
    /// The configured API base (`…/api/v1`); the tracking socket's address is derived from it.
    let apiBase: URL

    @MainActor
    init() {
        banners = BannerCenter()
        links = DeepLinkCenter(banners: banners)
        #if DEBUG
        // UI tests: an unreachable API ("Internet aloqasi yo'q" everywhere), the session kept.
        let offline = ProcessInfo.processInfo.arguments.contains("-uiTestOffline")
        #else
        let offline = false
        #endif
        // Set per build configuration in project.yml (Debug: local backend, Release: production).
        let base = Bundle.main.object(forInfoDictionaryKey: "ElchiAPIBaseURL") as? String ?? "https://api.elchigo.uz/api/v1"
        apiBase = URL(string: offline ? "http://127.0.0.1:9/api/v1" : base)!
        let events = events
        transport = HTTPTransport(v1BaseURL: apiBase, sessions: sessions, onSessionEnded: { events.refreshRejected($0) })
        auth = AuthAPI(transport: transport)
        clientProfile = ClientProfileAPI(transport: transport)
        api = ElchiAPI(transport: transport)
        geo = GeoAPI(transport: transport)
        files = FilesAPI(transport: transport)
        driver = DriverAPI(transport: transport)
        legacyOrders = LegacyOrdersAPI(transport: transport)
    }

    /// "Chiqish" (after the confirm): v1 `/auth/logout`, then the local session goes. A refresh refused meanwhile is
    /// part of signing out, not "Sessiya tugadi".
    func signOut() async {
        let sessions = sessions
        let auth = auth
        await events.deliberately {
            if let session = sessions.current() { try? await auth.logout(refreshToken: session.refreshToken) }
            sessions.clear()
        }
    }

    /// The account is gone (the server already revoked its tokens): drop the session and say so on the sign-in screen.
    func endDeletedSession(notice: String) async {
        let sessions = sessions
        await events.deliberately { sessions.clear() }
        events.post(.notice(notice))
    }
}

@main
struct ElchiApp: App {
    private let container: AppContainer
    @State private var strings = LocaleStore()
    @State private var theme = ThemeStore()
    @State private var session: SessionState

    init() {
        #if DEBUG
        // UI tests start from a first install: no session, no "seen" intro, default language and theme.
        if ProcessInfo.processInfo.arguments.contains("-uiTestReset") {
            SessionStore().clear()
            if let domain = Bundle.main.bundleIdentifier { UserDefaults.standard.removePersistentDomain(forName: domain) }
        }
        // UI tests that switch between a client and a driver: `-uiTestSession <base64 verify-otp answer>` signs in
        // without asking for another OTP (the dev backend allows 5 per phone in 30 minutes).
        let arguments = ProcessInfo.processInfo.arguments
        if let index = arguments.firstIndex(of: "-uiTestSession"), index + 1 < arguments.count,
           let data = Data(base64Encoded: arguments[index + 1]), let tokens = try? JSONDecoder().decode(TokenResponse.self, from: data) {
            SessionStore().save(Session(accessToken: tokens.accessToken, refreshToken: tokens.refreshToken, user: tokens.user))
        }
        // "Sessiya tugadi" on demand: both stored tokens become garbage, so the first call's refresh is refused.
        if ProcessInfo.processInfo.arguments.contains("-uiTestExpireSession") {
            let store = SessionStore()
            if let current = store.current() {
                store.save(Session(accessToken: "expired.\(UUID().uuidString)", refreshToken: "revoked.\(UUID().uuidString)", user: current.user))
            }
        }
        #endif
        let container = AppContainer()
        self.container = container
        _session = State(initialValue: SessionState(store: container.sessions, events: container.events))
    }

    var body: some Scene {
        WindowGroup {
            // The session decides the tree: signing in or out (or a refresh the server rejects) swaps it.
            Group {
                if let current = session.session {
                    // A new sign-in is a new tree: the previous person's draft never leaks into it.
                    if current.user.mobileRole == .driver {
                        DriverFlow(container: container, session: current).id(current.user.id)
                    } else {
                        ClientFlow(container: container, session: current).id(current.user.id)
                    }
                } else {
                    // "Qayta kirish" starts a fresh sign-in on the phone step with the number filled in.
                    EntryFlow(container: container, relogin: session.relogin).id(session.reloginCount)
                }
            }
            .overlay {
                if session.expired != nil {
                    SessionExpiredDialog { session.startRelogin() }
                }
            }
            // Screens with the standard top bar draw the banner under it; the sign-in screens get it floating.
            .overlay { if session.session == nil { BannerHost(center: container.banners, floating: true) } }
            .environment(container.banners)
            // `elchi://…` links (cold and warm) and Universal Links (`https://(www.)elchigo.uz/r/<code>`): one router.
            .onOpenURL { container.links.handle($0) }
            .onContinueUserActivity(NSUserActivityTypeBrowsingWeb) { container.links.handle(activity: $0) }
            #if DEBUG
            // Checks without the server's apple-app-site-association file: `-elchiDebugWebLink https://…` goes through
            // the Universal Link path (a browsing-web activity), as iOS would deliver it.
            .task {
                if let raw = UserDefaults.standard.string(forKey: "elchiDebugWebLink"), let url = URL(string: raw) {
                    let activity = NSUserActivity(activityType: NSUserActivityTypeBrowsingWeb)
                    activity.webpageURL = url
                    container.links.handle(activity: activity)
                }
            }
            #endif
            // A notice from the session layer ("Akkaunt o'chirildi") goes to the app's banner.
            .onChange(of: session.notice, initial: true) { _, notice in
                guard let notice else { return }
                container.banners.show(.text(notice), tone: .ok)
                session.clearNotice()
            }
            .elchiThemed()
            .environment(strings)
            .environment(theme)
            .preferredColorScheme(theme.colorScheme)
            .onAppear { theme.applyToWindows() }
            .onChange(of: theme.mode) { _, _ in theme.applyToWindows() }
        }
    }
}

/// "Sessiya tugadi": the refresh token was refused. One button, no dismiss - the only way on is signing in again.
/// It never claims the half-typed request is kept.
private struct SessionExpiredDialog: View {
    let onRelogin: () -> Void
    @Environment(LocaleStore.self) private var strings

    var body: some View {
        DialogOverlay(dismissLabel: strings.t("client.session.expiredTitle"), onDismiss: {}) {
            Heading(strings.t("client.session.expiredTitle"), subtitle: strings.t("client.session.expiredText"))
            ElchiButton(strings.t("client.session.relogin"), action: onRelogin)
        }
    }
}
