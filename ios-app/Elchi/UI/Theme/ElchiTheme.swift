import Observation
import SwiftUI

/// Design tokens from the Claude Design prototype ("Elchi App", `t` light/dark) - the same values as Android's
/// `ElchiTheme.kt`. Brand azure #0096FF carries navy #0E2350 text, never white: the prototype's contrast choice.
public struct ElchiColors: Sendable {
    public let page, card, text, muted, placeholder, field, line, outline, soft, softText, accentText, shadow: Color
    public let isDark: Bool

    public let brand = Color(hex: 0x0096FF)
    public let onBrand = Color(hex: 0x0E2350)
    public let navy = Color(hex: 0x0E2350)
    public let danger = Color(hex: 0xD64545)
    /// Map pins and the route card's destination glyph: navy, the text colour on the dark palette (navy vanishes on
    /// the night map).
    public var pin: Color { isDark ? text : navy }

    public static let light = ElchiColors(
        page: Color(hex: 0xF3F5F8), card: Color(hex: 0xFFFFFF), text: Color(hex: 0x0E1B33), muted: Color(hex: 0x5B6577),
        placeholder: Color(hex: 0x8792A2), field: Color(hex: 0xEEF1F5), line: Color(hex: 0xE1E5EB), outline: Color(hex: 0xCFD6DF),
        soft: Color(hex: 0xD9EEFF), softText: Color(hex: 0x0B3E73), accentText: Color(hex: 0x0068BF),
        shadow: Color(hex: 0x0E1B33, opacity: 0.12), isDark: false)

    public static let dark = ElchiColors(
        page: Color(hex: 0x0F1115), card: Color(hex: 0x17191E), text: Color(hex: 0xF2F4F7), muted: Color(hex: 0xA3ABB8),
        placeholder: Color(hex: 0x7A828F), field: Color(hex: 0x24272E), line: Color(hex: 0x30343C), outline: Color(hex: 0x3A3F48),
        soft: Color(hex: 0x0E3354), softText: Color(hex: 0xBFE3FF), accentText: Color(hex: 0x4DB5FF),
        shadow: Color(hex: 0x000000, opacity: 0.45), isDark: true)

    /// Status tones (badges, notes). Light values are the prototype's; dark ones are derived (the prototype has none).
    public func tone(_ tone: Tone) -> ToneColors {
        switch (tone, isDark) {
        case (.gray, false): ToneColors(bg: Color(hex: 0xEEF1F5), fg: Color(hex: 0x4A5568), noteText: Color(hex: 0x3A4556))
        case (.blue, false): ToneColors(bg: Color(hex: 0xD9EEFF), fg: Color(hex: 0x0068BF), noteText: Color(hex: 0x0B3E73))
        case (.warn, false): ToneColors(bg: Color(hex: 0xFDF1D6), fg: Color(hex: 0x9A6400), noteText: Color(hex: 0x6B4600))
        case (.ok, false): ToneColors(bg: Color(hex: 0xE2F5E9), fg: Color(hex: 0x1E8E4E), noteText: Color(hex: 0x12663A))
        case (.err, false): ToneColors(bg: Color(hex: 0xFCE6E6), fg: Color(hex: 0xC93838), noteText: Color(hex: 0x8E2020))
        case (.gray, true): ToneColors(bg: Color(hex: 0x24272E), fg: Color(hex: 0xC3CAD5), noteText: Color(hex: 0xC3CAD5))
        case (.blue, true): ToneColors(bg: Color(hex: 0x0E2A45), fg: Color(hex: 0x4DB5FF), noteText: Color(hex: 0xBFE3FF))
        case (.warn, true): ToneColors(bg: Color(hex: 0x3A2E12), fg: Color(hex: 0xF2C46B), noteText: Color(hex: 0xF7D98F))
        case (.ok, true): ToneColors(bg: Color(hex: 0x133524), fg: Color(hex: 0x7FD6A2), noteText: Color(hex: 0xA9E5C0))
        case (.err, true): ToneColors(bg: Color(hex: 0x3D1A1C), fg: Color(hex: 0xF29B9B), noteText: Color(hex: 0xF7B8B8))
        }
    }
}

public enum Tone: Sendable { case gray, blue, warn, ok, err }

public struct ToneColors: Sendable {
    public let bg, fg, noteText: Color
}

extension Color {
    init(hex: UInt32, opacity: Double = 1) {
        self.init(.sRGB, red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255, opacity: opacity)
    }
}

/// Poppins (bundled, OFL) in the prototype's type scale. Sizes scale with Dynamic Type relative to body.
public enum ElchiFont {
    public enum Weight: String { case regular = "Poppins-Regular", medium = "Poppins-Medium", semibold = "Poppins-SemiBold", bold = "Poppins-Bold" }

    public static func poppins(_ size: CGFloat, _ weight: Weight = .regular, relativeTo style: Font.TextStyle = .body) -> Font {
        .custom(weight.rawValue, size: size, relativeTo: style)
    }

    public static let display = poppins(30, .medium, relativeTo: .largeTitle)
    public static let title = poppins(24, .medium, relativeTo: .title)
    public static let section = poppins(16, .medium, relativeTo: .headline)
    public static let body = poppins(15)
    public static let bodyStrong = poppins(15, .semibold)
    public static let label = poppins(13, .medium, relativeTo: .subheadline)
    public static let secondary = poppins(14, relativeTo: .subheadline)
    public static let caption = poppins(12, relativeTo: .caption)
    public static let button = poppins(17, .medium, relativeTo: .headline)
    public static let buttonSmall = poppins(14, .medium, relativeTo: .subheadline)
    public static let badge = poppins(11, .semibold, relativeTo: .caption2)
}

public enum ElchiShape {
    public static let field: CGFloat = 16
    public static let card: CGFloat = 22
    public static let note: CGFloat = 16
    public static let sheet: CGFloat = 32
}

/// The person's choice from the theme switch; `system` follows the phone.
public enum ThemeMode: String, Sendable { case system, light, dark }

@MainActor @Observable
public final class ThemeStore {
    private static let key = "elchi.theme"
    public private(set) var mode: ThemeMode

    public init() {
        mode = UserDefaults.standard.string(forKey: Self.key).flatMap(ThemeMode.init(rawValue:)) ?? .system
    }

    public func set(_ mode: ThemeMode) {
        UserDefaults.standard.set(mode.rawValue, forKey: Self.key)
        self.mode = mode
    }

    /// Also sets every window's style: `.preferredColorScheme(nil)` alone does not hand an explicit choice back to the
    /// phone until the next launch, so "Tizim" follows the device live only through the window.
    public func applyToWindows() {
        let style: UIUserInterfaceStyle = switch mode {
        case .system: .unspecified
        case .light: .light
        case .dark: .dark
        }
        for scene in UIApplication.shared.connectedScenes {
            (scene as? UIWindowScene)?.windows.forEach { $0.overrideUserInterfaceStyle = style }
        }
    }

    /// For `.preferredColorScheme`: nil hands the choice back to the system.
    public var colorScheme: ColorScheme? {
        switch mode {
        case .system: nil
        case .light: .light
        case .dark: .dark
        }
    }
}

private struct ElchiColorsKey: EnvironmentKey {
    static let defaultValue = ElchiColors.light
}

extension EnvironmentValues {
    public var elchi: ElchiColors {
        get { self[ElchiColorsKey.self] }
        set { self[ElchiColorsKey.self] = newValue }
    }
}

/// Resolves the palette from the effective colour scheme, so `.system` follows the phone live.
public struct ElchiThemed: ViewModifier {
    @Environment(\.colorScheme) private var scheme

    public func body(content: Content) -> some View {
        content
            .environment(\.elchi, scheme == .dark ? .dark : .light)
            .tint(ElchiColors.light.brand)
    }
}

extension View {
    public func elchiThemed() -> some View { modifier(ElchiThemed()) }
}
