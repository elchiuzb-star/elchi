import Observation
import SwiftUI

// MARK: - Policy (pure)

/// The four banner tones of the design (`ok`, `err`, `warn`, `info`).
public enum BannerTone: Sendable, CaseIterable {
    case ok, err, warn, info

    var tone: Tone {
        switch self {
        case .ok: .ok
        case .err: .err
        case .warn: .warn
        case .info: .blue
        }
    }
}

public enum BannerPolicy {
    /// Success, info and warnings go by themselves after 4 s; an error stays until it is dismissed or the next action
    /// starts (a sentence about a failure must not vanish before it is read).
    public static func autoHide(_ tone: BannerTone) -> Duration? {
        tone == .err ? nil : .seconds(4)
    }
}

/// What a banner says. Resolved when drawn, so a language switch re-says it.
public enum BannerMessage: Sendable {
    /// A dictionary key.
    case key(String)
    /// A failed request: offline, rate limit, the code's sentence or the server's message.
    case error(APIError)
    /// A server warning (`CONTACT_INFO_MASKED`).
    case warning(ApiWarning)
    /// Text that is already a sentence in the active language.
    case text(String)
    /// A dictionary key with `{name}` fillers: `values` as given, `keys` translated first
    /// (`driverDocs.uploadedForReview` with `type` = `docType.passport`).
    case template(String, values: [String: String] = [:], keys: [String: String] = [:])
}

extension LocaleStore {
    func bannerText(_ message: BannerMessage) -> String {
        switch message {
        case .key(let key): return t(key)
        case .error(let error): return bannerErrorText(error)
        case .warning(let warning): return warningText(warning)
        case .text(let text): return text
        case .template(let key, let values, let keys):
            let fillers = values.map { ($0.key, $0.value as Any) } + keys.map { ($0.key, t($0.value) as Any) }
            return tOrNil(key, values: fillers) ?? t(key)
        }
    }

    /// Offline and too-many-requests have their own sentences whatever code the server (or no server) gave.
    func bannerErrorText(_ error: Error) -> String {
        if let error = error as? APIError {
            if error.code == APIError.network { return t("error.offline") }
            if error.status == 429 { return t("error.RATE_LIMITED") }
        }
        return errorText(error)
    }
}

// MARK: - The app's one banner

/// The app-level status strip: at most one message at a time (a new one replaces the old), plus the loading line.
/// Screens post to it; `BannerHost` draws it over every screen.
@MainActor @Observable
public final class BannerCenter {
    public struct Item: Identifiable {
        public let id = UUID()
        public let message: BannerMessage
        public let tone: BannerTone
        /// A tappable banner ("Yangi taklif bor — yangilash uchun bosing"); tapping runs it and closes the banner.
        public let onTap: (@MainActor () -> Void)?
    }

    public private(set) var current: Item?
    /// Work in flight that asked for the loading line (`common.loading`).
    public private(set) var loadingCount = 0
    private var hide: Task<Void, Never>?

    public init() {}

    public var loading: Bool { loadingCount > 0 }

    /// `hideAfter` replaces the tone's own timing (the map's "location not found" goes after 6 s, as on Android).
    public func show(_ message: BannerMessage, tone: BannerTone, hideAfter: Duration? = nil, onTap: (@MainActor () -> Void)? = nil) {
        let item = Item(message: message, tone: tone, onTap: onTap)
        current = item
        hide?.cancel()
        guard let delay = hideAfter ?? BannerPolicy.autoHide(tone) else { return }
        hide = Task { [weak self] in
            try? await Task.sleep(for: delay)
            guard !Task.isCancelled, self?.current?.id == item.id else { return }
            self?.current = nil
        }
    }

    public func ok(_ key: String) { show(.key(key), tone: .ok) }

    public func error(_ error: Error) {
        if let error = error as? APIError { show(.error(error), tone: .err) } else { show(.key("error.fallback"), tone: .err) }
    }

    public func warnings(_ warnings: [ApiWarning]) {
        if let first = warnings.first { show(.warning(first), tone: .warn) }
    }

    public func dismiss() {
        hide?.cancel()
        current = nil
    }

    /// The next action starts: a standing error is no longer news.
    public func clearError() {
        if current?.tone == .err { dismiss() }
    }

    /// Runs `work` with the loading line shown.
    public func whileLoading<T>(_ work: () async throws -> T) async rethrows -> T {
        loadingCount += 1
        defer { loadingCount -= 1 }
        return try await work()
    }
}

/// Draws `BannerCenter`: the loading line and the message strip (tap to act or to close; errors carry a close
/// button). Announced to VoiceOver. `ScreenScaffold` puts it in the flow under its top bar (the design's place, so it
/// never covers the first card); `floating` is the app-level fallback for screens without that bar (sign-in).
struct BannerHost: View {
    let center: BannerCenter
    var floating = false
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        VStack(spacing: 6) {
            if center.loading {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small).tint(c.tone(.blue).fg)
                    Text(strings.t("common.loading")).font(ElchiFont.poppins(12.5, .medium)).foregroundStyle(c.tone(.blue).fg)
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 14).padding(.vertical, 8)
                .background(c.tone(.blue).bg, in: RoundedRectangle(cornerRadius: 14))
                .accessibilityElement(children: .combine)
            }
            if let item = center.current {
                strip(item).id(item.id).transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .padding(.horizontal, 12)
        .padding(.top, floating ? 60 : 0)
        .padding(.bottom, !floating && (center.loading || center.current != nil) ? 6 : 0)
        .frame(maxWidth: .infinity, maxHeight: floating ? .infinity : nil, alignment: .top)
        .animation(.easeOut(duration: 0.2), value: center.current?.id)
        .animation(.easeOut(duration: 0.2), value: center.loading)
    }

    private func strip(_ item: BannerCenter.Item) -> some View {
        let colors = c.tone(item.tone.tone)
        let text = strings.bannerText(item.message)
        return HStack(alignment: .top, spacing: 10) {
            icon(item.tone).image(size: 18).padding(.top, 1)
            Text(text).font(ElchiFont.poppins(13.5, .medium)).fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
            if item.tone == .err {
                Button { center.dismiss() } label: {
                    ElchiIcon.x.image(size: 16).frame(width: 28, height: 28).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(strings.t("common.close"))
            }
        }
        .foregroundStyle(colors.noteText)
        .padding(.horizontal, 14).padding(.vertical, 12)
        .background(colors.bg, in: RoundedRectangle(cornerRadius: 16))
        .overlay { RoundedRectangle(cornerRadius: 16).strokeBorder(colors.fg.opacity(0.25), lineWidth: 1) }
        .shadow(color: c.shadow, radius: 12, y: 6)
        .contentShape(Rectangle())
        .onTapGesture {
            let action = item.onTap
            center.dismiss()
            action?()
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("elchi.banner")
        .accessibilityLabel(text)
        .accessibilityAddTraits(item.onTap != nil ? .isButton : [])
        .onAppear { AccessibilityNotification.Announcement(text).post() }
    }

    private func icon(_ tone: BannerTone) -> ElchiIcon {
        switch tone {
        case .ok: .checkC
        case .err: .alert
        case .warn: .alert
        case .info: .info
        }
    }
}
