import Foundation
import Observation

/// The two app languages. Uzbek is the product's language and the fallback; strings come from the shared web
/// dictionary via scripts/gen_native_strings.mjs (Resources/Localizable.xcstrings).
public enum AppLocale: String, CaseIterable, Sendable {
    case uz, ru

    public var label: String {
        switch self {
        case .uz: "O'zbekcha"
        case .ru: "Русский"
        }
    }
}

/// Holds the chosen language; the choice survives restarts. Views re-render because they read `locale`.
@MainActor @Observable
public final class LocaleStore {
    private static let key = "elchi.locale"

    public private(set) var locale: AppLocale
    private var bundle: Bundle

    public init() {
        let stored = UserDefaults.standard.string(forKey: Self.key).flatMap(AppLocale.init(rawValue:)) ?? .uz
        locale = stored
        bundle = Self.bundle(for: stored)
    }

    public func set(_ locale: AppLocale) {
        UserDefaults.standard.set(locale.rawValue, forKey: Self.key)
        self.locale = locale
        bundle = Self.bundle(for: locale)
    }

    /// The sentence for a dictionary key in the active language, with `{name}` placeholders filled.
    public func t(_ key: String, _ values: (String, Any)...) -> String {
        fill(lookup(key) ?? lookup(key, in: Self.bundle(for: .uz)) ?? key, values)
    }

    /// The same lookup for a key only known at runtime (`error.<code>`, a status): nil when it is not in the
    /// dictionary, so the caller decides what an unknown value looks like.
    public func tOrNil(_ key: String, _ values: (String, Any)...) -> String? {
        lookup(key).map { fill($0, values) }
    }

    /// `tOrNil` with the fillers as a list (a notification's `params`, known only at runtime).
    public func tOrNil(_ key: String, values: [(String, Any)]) -> String? {
        lookup(key).map { fill($0, values) }
    }

    private func lookup(_ key: String, in source: Bundle? = nil) -> String? {
        let missing = "\u{0}"
        let text = (source ?? bundle).localizedString(forKey: key, value: missing, table: nil)
        return text == missing ? nil : text
    }

    private func fill(_ template: String, _ values: [(String, Any)]) -> String {
        values.reduce(template) { text, pair in text.replacingOccurrences(of: "{\(pair.0)}", with: "\(pair.1)") }
    }

    private static func bundle(for locale: AppLocale) -> Bundle {
        Bundle.main.path(forResource: locale.rawValue, ofType: "lproj").flatMap(Bundle.init(path:)) ?? .main
    }
}
