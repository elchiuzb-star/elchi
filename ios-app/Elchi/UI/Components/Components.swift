import SwiftUI

// MARK: - Icons

extension ElchiIcon {
    /// The kit's stroke icon as a template image, tinted by `foregroundStyle`.
    public func image(size: CGFloat = 20) -> some View {
        Image(rawValue).resizable().renderingMode(.template).frame(width: size, height: size).accessibilityHidden(true)
    }
}

// MARK: - Buttons

/// The prototype's button variants (`BV` in elchi-mobile.js).
public enum ButtonVariant: Sendable { case primary, soft, neutral, dangerSoft, outline, ghost, danger, navy }

public enum ButtonSize: Sendable {
    /// `pair` = two buttons side by side (the prototype's `btns`, 48 high).
    case large, medium, pair
    var height: CGFloat {
        switch self {
        case .large: 56
        case .medium: 44
        case .pair: 48
        }
    }
}

private struct ButtonColors {
    let bg: Color, fg: Color, border: Color?
}

private func buttonColors(_ variant: ButtonVariant, _ c: ElchiColors) -> ButtonColors {
    switch variant {
    case .primary: ButtonColors(bg: c.brand, fg: c.onBrand, border: nil)
    case .soft: ButtonColors(bg: c.soft, fg: c.softText, border: nil)
    case .neutral: ButtonColors(bg: c.field, fg: c.text, border: nil)
    case .dangerSoft: ButtonColors(bg: c.tone(.err).bg, fg: c.tone(.err).fg, border: nil)
    case .outline: ButtonColors(bg: .clear, fg: c.text, border: c.outline)
    case .ghost: ButtonColors(bg: .clear, fg: c.accentText, border: nil)
    case .danger: ButtonColors(bg: c.danger, fg: .white, border: nil)
    case .navy: ButtonColors(bg: c.isDark ? Color(hex: 0x1B3563) : c.navy, fg: .white, border: nil)
    }
}

/// Pill button. Disabled is the prototype's `x` variant (grey, not faded brand) so it still reads in sunlight;
/// loading keeps the size and shows a spinner instead of the label. `dimmed` draws the same grey but keeps the button
/// tappable (BOSQICH 02: a tap on an incomplete step says what is missing).
public struct ElchiButton: View {
    let title: String
    let variant: ButtonVariant
    let size: ButtonSize
    let icon: ElchiIcon?
    let loading: Bool
    let dimmed: Bool
    let action: () -> Void
    @Environment(\.elchi) private var c
    @Environment(\.isEnabled) private var enabled

    public init(_ title: String, variant: ButtonVariant = .primary, size: ButtonSize = .large, icon: ElchiIcon? = nil,
                loading: Bool = false, dimmed: Bool = false, action: @escaping () -> Void) {
        self.title = title
        self.variant = variant
        self.size = size
        self.icon = icon
        self.loading = loading
        self.dimmed = dimmed
        self.action = action
    }

    public var body: some View {
        let colors = enabled && !dimmed
            ? buttonColors(variant, c)
            : ButtonColors(bg: c.isDark ? Color(hex: 0x24272E) : Color(hex: 0xE4E9EF), fg: c.isDark ? Color(hex: 0x6B7482) : Color(hex: 0x8A96A6), border: nil)
        Button(action: action) {
            HStack(spacing: 8) {
                if loading {
                    ProgressView().tint(colors.fg)
                } else {
                    if let icon { icon.image(size: 18) }
                    Text(title).font(size == .large ? ElchiFont.button : ElchiFont.buttonSmall).lineLimit(1).minimumScaleFactor(0.8)
                }
            }
            .foregroundStyle(colors.fg)
            .frame(maxWidth: .infinity, minHeight: size.height, maxHeight: size.height)
            .padding(.horizontal, size == .pair ? 10 : 18)
            .background(colors.bg, in: Capsule())
            .overlay { if let border = colors.border { Capsule().strokeBorder(border, lineWidth: 1.5) } }
            .contentShape(Capsule())
        }
        .buttonStyle(PressFade())
        .disabled(loading)
    }
}

struct PressFade: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.opacity(configuration.isPressed ? 0.85 : 1)
    }
}

/// 44pt round button floating over a map or sheet (profile, back, locate). `dot` = something new behind it (unread
/// notifications on the menu); `dotLabel` says so to VoiceOver.
public struct RoundIconButton: View {
    let icon: ElchiIcon
    let label: String
    let dot: Bool
    let dotLabel: String?
    let action: () -> Void
    @Environment(\.elchi) private var c

    public init(_ icon: ElchiIcon, label: String, dot: Bool = false, dotLabel: String? = nil, action: @escaping () -> Void) {
        self.icon = icon
        self.label = label
        self.dot = dot
        self.dotLabel = dotLabel
        self.action = action
    }

    public var body: some View {
        Button(action: action) {
            icon.image().foregroundStyle(c.text)
                .frame(width: 44, height: 44)
                .background(c.card, in: Circle())
                .overlay(alignment: .topTrailing) {
                    if dot {
                        Circle().fill(c.danger).frame(width: 10, height: 10)
                            .overlay { Circle().strokeBorder(c.card, lineWidth: 2) }
                            .offset(x: -6, y: 6)
                    }
                }
                .shadow(color: c.shadow, radius: 12, y: 6)
        }
        .buttonStyle(PressFade())
        .accessibilityLabel(label)
        .accessibilityValue(dot ? (dotLabel ?? "") : "")
    }
}

/// Sun / moon pill from the prototype's top bar; a second tap on the active one returns to "follow the phone".
public struct ThemeSwitch: View {
    let mode: ThemeMode
    let onChange: (ThemeMode) -> Void
    let lightLabel: String
    let darkLabel: String
    @Environment(\.elchi) private var c

    public init(mode: ThemeMode, lightLabel: String, darkLabel: String, onChange: @escaping (ThemeMode) -> Void) {
        self.mode = mode
        self.lightLabel = lightLabel
        self.darkLabel = darkLabel
        self.onChange = onChange
    }

    public var body: some View {
        HStack(spacing: 4) {
            segment(.sun, target: .light, label: lightLabel, active: !c.isDark)
            segment(.moon, target: .dark, label: darkLabel, active: c.isDark)
        }
        .padding(4)
        .background(c.card, in: Capsule())
        .shadow(color: c.shadow, radius: 12, y: 6)
    }

    private func segment(_ icon: ElchiIcon, target: ThemeMode, label: String, active: Bool) -> some View {
        Button { onChange(mode == target ? .system : target) } label: {
            icon.image(size: 18)
                .foregroundStyle(active ? c.onBrand : c.muted)
                .frame(width: 36, height: 36)
                .background(active ? c.brand : .clear, in: Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
        .accessibilityAddTraits(mode == target ? .isSelected : [])
    }
}

// MARK: - Text blocks

public struct Heading: View {
    let title: String
    let subtitle: String?
    let large: Bool
    let centered: Bool
    @Environment(\.elchi) private var c

    public init(_ title: String, subtitle: String? = nil, large: Bool = false, centered: Bool = false) {
        self.title = title
        self.subtitle = subtitle
        self.large = large
        self.centered = centered
    }

    public var body: some View {
        VStack(alignment: centered ? .center : .leading, spacing: 4) {
            Text(title).font(large ? ElchiFont.display : ElchiFont.title).foregroundStyle(c.text)
            if let subtitle { Text(subtitle).font(ElchiFont.secondary).foregroundStyle(c.muted) }
        }
        .multilineTextAlignment(centered ? .center : .leading)
        .frame(maxWidth: .infinity, alignment: centered ? .center : .leading)
    }
}

public struct SectionTitle: View {
    let title: String
    let description: String?
    let action: String?
    let onAction: (() -> Void)?
    @Environment(\.elchi) private var c

    public init(_ title: String, description: String? = nil, action: String? = nil, onAction: (() -> Void)? = nil) {
        self.title = title
        self.description = description
        self.action = action
        self.onAction = onAction
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(alignment: .firstTextBaseline) {
                Text(title).font(ElchiFont.section).foregroundStyle(c.text)
                Spacer()
                if let action {
                    Button(action) { onAction?() }.font(ElchiFont.poppins(13, .semibold)).foregroundStyle(c.accentText)
                }
            }
            if let description { Text(description).font(ElchiFont.caption).foregroundStyle(c.muted) }
        }
        .padding(.top, 4)
    }
}

// MARK: - Surfaces

/// Card surface. `tint` gives the prototype's flat tinted cards (estimate, total: no border, no shadow); the
/// default white card keeps the hairline border and soft shadow.
public struct ElchiCard<Content: View>: View {
    public enum Tint: Sendable { case none, blue, field }

    let padding: EdgeInsets
    let tint: Tint
    let content: Content
    @Environment(\.elchi) private var c

    public init(padding: EdgeInsets = EdgeInsets(top: 4, leading: 16, bottom: 4, trailing: 16), tint: Tint = .none,
                @ViewBuilder content: () -> Content) {
        self.padding = padding
        self.tint = tint
        self.content = content()
    }

    public var body: some View {
        let shape = RoundedRectangle(cornerRadius: ElchiShape.card)
        VStack(alignment: .leading, spacing: 0) { content }
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(fill, in: shape)
            .overlay { if tint == .none { shape.strokeBorder(c.line, lineWidth: 1) } }
            .shadow(color: tint == .none ? c.shadow : .clear, radius: 12, y: 6)
    }

    private var fill: Color {
        switch tint {
        case .none: c.card
        case .blue: c.isDark ? Color(hex: 0x0E2A45) : Color(hex: 0xEAF5FF)
        case .field: c.field
        }
    }
}

/// A key/value row inside an `ElchiCard`; rows after the first draw the hairline above themselves. `onTrailing`
/// turns the trailing pill into a button ("O'zgartirish"); `placeholder` greys the value ("Manzil kiritilmagan").
public struct CardRow: View {
    let key: String, value: String, detail: String?, trailing: String?, first: Bool, strong: Bool, placeholder: Bool
    let onTrailing: (() -> Void)?
    @Environment(\.elchi) private var c

    public init(_ key: String, _ value: String, first: Bool = false, detail: String? = nil, trailing: String? = nil,
                strong: Bool = false, placeholder: Bool = false, onTrailing: (() -> Void)? = nil) {
        self.key = key
        self.value = value
        self.first = first
        self.detail = detail
        self.trailing = trailing
        self.strong = strong
        self.placeholder = placeholder
        self.onTrailing = onTrailing
    }

    public var body: some View {
        VStack(spacing: 0) {
            if !first { Rectangle().fill(c.field).frame(height: 1) }
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(key).font(ElchiFont.caption).foregroundStyle(c.muted)
                    Text(value).font(ElchiFont.poppins(14, strong ? .semibold : .medium)).foregroundStyle(placeholder ? c.placeholder : c.text)
                        .fixedSize(horizontal: false, vertical: true)
                    if let detail {
                        Text(detail).font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
                    }
                }
                .accessibilityElement(children: .combine)
                Spacer(minLength: 0)
                if let trailing {
                    let pill = Text(trailing).font(ElchiFont.poppins(13, .semibold)).foregroundStyle(c.accentText)
                        .padding(.horizontal, 12).padding(.vertical, 6)
                        .background(c.field, in: Capsule())
                    if let onTrailing {
                        Button(action: onTrailing) { pill.frame(minHeight: 44).contentShape(Rectangle()) }
                            .buttonStyle(.plain)
                            .accessibilityLabel("\(trailing): \(key)")
                    } else {
                        pill
                    }
                }
            }
            .padding(.vertical, 10)
        }
    }
}

/// The rounded-top panel that holds a screen's controls over a map (the prototype's bottom sheet).
public struct BottomPanel<Content: View>: View {
    let content: Content
    @Environment(\.elchi) private var c

    public init(@ViewBuilder content: () -> Content) { self.content = content() }

    public var body: some View {
        VStack(alignment: .leading, spacing: 16) { content }
            .padding(EdgeInsets(top: 24, leading: 16, bottom: 24, trailing: 16))
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(c.card, in: UnevenRoundedRectangle(topLeadingRadius: ElchiShape.sheet, topTrailingRadius: ElchiShape.sheet))
    }
}

public struct Note: View {
    let text: String, title: String?, tone: Tone
    @Environment(\.elchi) private var c

    public init(_ text: String, tone: Tone = .blue, title: String? = nil) {
        self.text = text
        self.tone = tone
        self.title = title
    }

    public var body: some View {
        let colors = c.tone(tone)
        let icon: ElchiIcon = switch tone {
        case .warn, .err: .alert
        case .ok: .checkC
        default: .info
        }
        HStack(alignment: .top, spacing: 10) {
            icon.image(size: 18).foregroundStyle(colors.fg).padding(.top, 1)
            VStack(alignment: .leading, spacing: 2) {
                if let title { Text(title).font(ElchiFont.poppins(13, .semibold)) }
                Text(text).font(ElchiFont.poppins(13)).lineSpacing(3)
            }
            .foregroundStyle(colors.noteText)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .background(tone == .blue && !c.isDark ? Color(hex: 0xEEF6FF) : colors.bg, in: RoundedRectangle(cornerRadius: ElchiShape.note))
    }
}

/// Status pill with a dot: the dot keeps the meaning when colour cannot (greyscale, sunlight).
public struct Badge: View {
    let text: String, tone: Tone
    @Environment(\.elchi) private var c

    public init(_ text: String, tone: Tone) {
        self.text = text
        self.tone = tone
    }

    public var body: some View {
        let colors = c.tone(tone)
        HStack(spacing: 5) {
            Circle().fill(colors.fg).frame(width: 6, height: 6)
            Text(text).font(ElchiFont.badge).lineLimit(1)
        }
        .foregroundStyle(colors.fg)
        .padding(.horizontal, 10).padding(.vertical, 4)
        .background(colors.bg, in: Capsule())
    }
}

// MARK: - Inputs

/// Text field: label above, optional fixed prefix (`+998`) behind a divider, hint or error below. `error`
/// replaces the hint and adds an error-tone border so the state is not colour-only.
public struct ElchiField: View {
    @Binding var text: String
    let label: String?, placeholder: String?, prefix: String?, icon: ElchiIcon?, hint: String?, error: String?
    /// A fixed unit after the text ("so'm").
    let suffix: String?
    let keyboard: UIKeyboardType
    let contentType: UITextContentType?
    let multiline: Bool
    let monospaced: Bool
    /// Told when the field gains or loses the keyboard (a screen keeps what the number changes in sight).
    let onFocus: ((Bool) -> Void)?
    @Environment(\.elchi) private var c
    @FocusState private var focused: Bool

    public init(text: Binding<String>, label: String? = nil, placeholder: String? = nil, prefix: String? = nil, icon: ElchiIcon? = nil,
                hint: String? = nil, error: String? = nil, keyboard: UIKeyboardType = .default, contentType: UITextContentType? = nil,
                multiline: Bool = false, monospaced: Bool = false, suffix: String? = nil, onFocus: ((Bool) -> Void)? = nil) {
        self.onFocus = onFocus
        self.suffix = suffix
        _text = text
        self.label = label
        self.placeholder = placeholder
        self.prefix = prefix
        self.icon = icon
        self.hint = hint
        self.error = error
        self.keyboard = keyboard
        self.contentType = contentType
        self.multiline = multiline
        self.monospaced = monospaced
    }

    public var body: some View {
        let errorColors = c.tone(.err)
        VStack(alignment: .leading, spacing: 6) {
            if let label { Text(label).font(ElchiFont.label).foregroundStyle(c.text) }
            HStack(alignment: multiline ? .top : .center, spacing: 10) {
                if let icon { icon.image(size: 18).foregroundStyle(c.muted) }
                if let prefix {
                    Text(prefix).font(ElchiFont.bodyStrong).foregroundStyle(c.text)
                    Rectangle().fill(c.outline).frame(width: 1, height: 22)
                }
                TextField("", text: $text, prompt: placeholder.map { Text($0).foregroundStyle(c.placeholder) },
                          axis: multiline ? .vertical : .horizontal)
                    .lineLimit(multiline ? 3...6 : 1...1)
                    .font(monospaced ? .system(size: 15, design: .monospaced) : ElchiFont.body)
                    .foregroundStyle(c.text)
                    .keyboardType(keyboard)
                    .textContentType(contentType)
                    .tint(c.brand)
                    .accessibilityLabel(label ?? placeholder ?? "")
                    .focused($focused)
                    .onChange(of: focused) { _, now in onFocus?(now) }
                if let suffix { Text(suffix).font(ElchiFont.poppins(14)).foregroundStyle(c.muted).accessibilityHidden(true) }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, multiline ? 14 : 0)
            .frame(minHeight: multiline ? 96 : 52, alignment: multiline ? .top : .center)
            .background(c.field, in: RoundedRectangle(cornerRadius: ElchiShape.field))
            .overlay { if error != nil { RoundedRectangle(cornerRadius: ElchiShape.field).strokeBorder(errorColors.fg, lineWidth: 1.5) } }
            if let below = error ?? hint {
                Text(below).font(ElchiFont.caption).foregroundStyle(error != nil ? errorColors.fg : c.muted)
            }
        }
    }
}

/// Segmented control (pill track, the selected segment raised on a card).
public struct Segmented<Value: Hashable>: View {
    let options: [(Value, String)]
    let selected: Value
    let onSelect: (Value) -> Void
    @Environment(\.elchi) private var c

    public init(_ options: [(Value, String)], selected: Value, onSelect: @escaping (Value) -> Void) {
        self.options = options
        self.selected = selected
        self.onSelect = onSelect
    }

    public var body: some View {
        HStack(spacing: 4) {
            ForEach(options, id: \.0) { value, label in
                let active = value == selected
                Button { onSelect(value) } label: {
                    Text(label).font(ElchiFont.buttonSmall).lineLimit(1)
                        .foregroundStyle(active ? c.text : c.muted)
                        .frame(maxWidth: .infinity, minHeight: 38)
                        .background(active ? c.card : .clear, in: Capsule())
                        .shadow(color: active ? c.shadow : .clear, radius: 4, y: 2)
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(active ? .isSelected : [])
            }
        }
        .padding(4)
        .background(c.field, in: Capsule())
    }
}

/// A pill choice. `filled` is the prototype's `chips` block (the chosen one brand-blue with navy text: sort, TTL);
/// the default keeps the soft tint of the sign-in role chip.
public struct Chip: View {
    let text: String, selected: Bool, icon: ElchiIcon?, filled: Bool, action: () -> Void
    @Environment(\.elchi) private var c

    public init(_ text: String, selected: Bool, icon: ElchiIcon? = nil, filled: Bool = false, action: @escaping () -> Void) {
        self.text = text
        self.selected = selected
        self.icon = icon
        self.filled = filled
        self.action = action
    }

    public var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                if let icon { icon.image(size: 14) }
                Text(text).font(ElchiFont.label)
            }
            .foregroundStyle(selected ? (filled ? c.onBrand : c.softText) : c.text)
            .padding(.horizontal, 14).padding(.vertical, 8)
            .frame(minHeight: 36)
            .background(selected ? (filled ? c.brand : c.soft) : c.card, in: Capsule())
            .overlay { Capsule().strokeBorder(selected ? .clear : c.line, lineWidth: 1) }
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

/// A setting on its own card: title, one-line explanation, switch.
public struct ToggleRow: View {
    let title: String, description: String
    @Binding var isOn: Bool
    @Environment(\.elchi) private var c

    public init(_ title: String, description: String, isOn: Binding<Bool>) {
        self.title = title
        self.description = description
        _isOn = isOn
    }

    public var body: some View {
        ElchiCard(padding: EdgeInsets(top: 14, leading: 16, bottom: 14, trailing: 16)) {
            Toggle(isOn: $isOn) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(ElchiFont.poppins(14, .semibold)).foregroundStyle(c.text)
                    Text(description).font(ElchiFont.caption).foregroundStyle(c.muted)
                }
            }
            .tint(c.brand)
        }
    }
}

/// One circle per OTP digit (the prototype's `otp` block): empty = outline, filled = brand ring on a soft fill,
/// next = thicker brand ring, error = red on red tint. Input goes to a hidden field (see OtpView).
public struct OtpCells: View {
    let code: String, length: Int, error: Bool
    @Environment(\.elchi) private var c

    public init(code: String, length: Int, error: Bool = false) {
        self.code = code
        self.length = length
        self.error = error
    }

    public var body: some View {
        let err = c.tone(.err)
        HStack(spacing: 14) {
            ForEach(0..<length, id: \.self) { i in
                let digit = i < code.count ? String(code[code.index(code.startIndex, offsetBy: i)]) : ""
                let style: (CGFloat, Color, Color) =
                    error ? (2, err.fg, err.bg)
                    : i == code.count ? (2.5, c.brand, c.card)
                    : !digit.isEmpty ? (2, c.brand, c.isDark ? Color(hex: 0x0E2A45) : Color(hex: 0xEAF5FF))
                    : (1.5, c.outline, c.card)
                Text(digit).font(ElchiFont.poppins(24, .semibold)).foregroundStyle(error ? err.fg : c.text)
                    .frame(width: 60, height: 60)
                    .background(style.2, in: Circle())
                    .overlay { Circle().strokeBorder(style.1, lineWidth: style.0) }
            }
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .ignore)
        .accessibilityValue(code)
    }
}

/// Screen top bar from the prototype: floating back button, optional logo on the right.
public struct TopBar: View {
    let onBack: (() -> Void)?
    let backLabel: String
    let logo: Bool

    public init(backLabel: String, logo: Bool = false, onBack: (() -> Void)?) {
        self.backLabel = backLabel
        self.logo = logo
        self.onBack = onBack
    }

    public var body: some View {
        HStack {
            if let onBack { RoundIconButton(.back, label: backLabel, action: onBack) }
            Spacer()
            if logo { ElchiLogo(height: 24) }
        }
        .frame(height: 58)
        .padding(.horizontal, 16)
    }
}

public struct ElchiLogo: View {
    let height: CGFloat
    public init(height: CGFloat) { self.height = height }

    public var body: some View {
        Image("ElchiLogo").resizable().scaledToFit().frame(height: height).accessibilityLabel("elchi")
    }
}

/// Full-width status strip under the top bar ("Kod yuborildi", "Kod noto'g'ri"). Announced to VoiceOver.
public struct Banner: View {
    let text: String, tone: Tone
    @Environment(\.elchi) private var c

    public init(_ text: String, tone: Tone) {
        self.text = text
        self.tone = tone
    }

    public var body: some View {
        let colors = c.tone(tone)
        Text(text).font(ElchiFont.poppins(12.5, .medium)).foregroundStyle(colors.fg)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 16).padding(.vertical, 9)
            .background(colors.bg)
            .onAppear { AccessibilityNotification.Announcement(text).post() }
    }
}

/// A large choice card (role screen): tinted icon tile, title, one line, chevron.
public struct ChoiceCard: View {
    let icon: ElchiIcon, title: String, description: String, action: () -> Void
    @Environment(\.elchi) private var c

    public init(icon: ElchiIcon, title: String, description: String, action: @escaping () -> Void) {
        self.icon = icon
        self.title = title
        self.description = description
        self.action = action
    }

    public var body: some View {
        Button(action: action) {
            HStack(spacing: 14) {
                icon.image(size: 26).foregroundStyle(c.accentText)
                    .frame(width: 56, height: 56)
                    .background(c.soft, in: RoundedRectangle(cornerRadius: 18))
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(ElchiFont.poppins(16, .semibold)).foregroundStyle(c.text)
                    Text(description).font(ElchiFont.poppins(13)).foregroundStyle(c.muted).multilineTextAlignment(.leading)
                }
                Spacer(minLength: 0)
                ElchiIcon.chevR.image(size: 18).foregroundStyle(c.placeholder)
            }
            .padding(18)
            .background(c.card, in: RoundedRectangle(cornerRadius: 24))
            .overlay { RoundedRectangle(cornerRadius: 24).strokeBorder(c.line, lineWidth: 1) }
            .shadow(color: c.shadow, radius: 12, y: 6)
        }
        .buttonStyle(.plain)
    }
}

/// Page dots: the current one stretches to a bar (the prototype's onboarding dots).
public struct PageDots: View {
    let count: Int, current: Int
    @Environment(\.elchi) private var c

    public init(count: Int, current: Int) {
        self.count = count
        self.current = current
    }

    public var body: some View {
        HStack(spacing: 6) {
            ForEach(0..<count, id: \.self) { i in
                Capsule().fill(i == current ? c.brand : c.outline).frame(width: i == current ? 24 : 8, height: 8)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityValue("\(current + 1) / \(count)")
    }
}

// MARK: - Stage 02 blocks

/// Flow screen skeleton (the prototype's `bar` screens): back button + title (+ optional right text), scrolling
/// body on the page colour, footer on the card colour behind a hairline, pinned above the keyboard.
/// `leading` swaps the back arrow for another round button (the orders screen's menu); `onRight` makes the right
/// text a button (with `rightIcon`); `showsFooter: false` drops the footer bar when its content is conditional;
/// `banner` is a status strip under the top bar that stays visible however far the body is scrolled.
public struct ScreenScaffold<Content: View, Footer: View>: View {
    let title: String
    let right: String?
    let rightIcon: ElchiIcon?
    let onRight: (() -> Void)?
    let leading: ElchiIcon
    let backLabel: String
    let onBack: (() -> Void)?
    let showsFooter: Bool
    let banner: (text: String, tone: Tone)?
    let keepVisible: AnyHashable?
    let keyboardDone: String?
    /// `(n, total)`: the "n / total" pill at the right and the thin progress bar under the bar (the order steps).
    let step: (Int, Int)?
    /// Each change scrolls the body back to its top (where a tap-to-validate error list appears).
    let scrollTop: Int
    /// Round icon buttons at the right of the bar (BOSQICH 03: the orders bell, the detail's pencil and share).
    let actions: [BarAction]
    /// The section roots' big title (26 pt: "Buyurtmalar").
    let largeTitle: Bool
    /// A view id the body scrolls to once it has appeared (a link to a listing's offers).
    let initialScroll: AnyHashable?
    let content: Content
    let footer: Footer
    @Environment(\.elchi) private var c
    /// The app's banner (Stage 06), drawn under the top bar when the app provides one.
    @Environment(BannerCenter.self) private var banners: BannerCenter?
    /// A line the screen's owner puts under the bar (the driver's GPS bar on a running trip's screens).
    @Environment(\.screenAccessory) private var accessory

    public init(title: String, right: String? = nil, rightIcon: ElchiIcon? = nil, onRight: (() -> Void)? = nil, leading: ElchiIcon = .back,
                backLabel: String, onBack: (() -> Void)?, showsFooter: Bool = true, banner: (text: String, tone: Tone)? = nil,
                keepVisible: AnyHashable? = nil, keyboardDone: String? = nil, step: (Int, Int)? = nil, scrollTop: Int = 0,
                actions: [BarAction] = [], largeTitle: Bool = false, initialScroll: AnyHashable? = nil,
                @ViewBuilder content: () -> Content, @ViewBuilder footer: () -> Footer) {
        self.actions = actions
        self.largeTitle = largeTitle
        self.initialScroll = initialScroll
        self.step = step
        self.scrollTop = scrollTop
        self.keepVisible = keepVisible
        self.keyboardDone = keyboardDone
        self.title = title
        self.right = right
        self.rightIcon = rightIcon
        self.onRight = onRight
        self.leading = leading
        self.backLabel = backLabel
        self.onBack = onBack
        self.showsFooter = showsFooter
        self.banner = banner
        self.content = content()
        self.footer = footer()
    }

    public var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                if let onBack { RoundIconButton(leading, label: backLabel, action: onBack) }
                Text(title).font(largeTitle ? ElchiFont.poppins(26, .medium, relativeTo: .title) : ElchiFont.poppins(18, .medium, relativeTo: .headline))
                    .foregroundStyle(c.text)
                    .lineLimit(1).minimumScaleFactor(0.8).accessibilityAddTraits(.isHeader)
                Spacer(minLength: 0)
                ForEach(actions) { BarActionButton(action: $0) }
                if let right, let onRight {
                    Button(action: onRight) {
                        HStack(spacing: 6) {
                            if let rightIcon { rightIcon.image(size: 16) }
                            Text(right).font(ElchiFont.poppins(13, .semibold)).lineLimit(1)
                        }
                        .foregroundStyle(c.accentText)
                        .padding(.horizontal, 12)
                        .frame(minHeight: 44)
                        .background(c.card, in: Capsule())
                        .overlay { Capsule().strokeBorder(c.line, lineWidth: 1) }
                    }
                    .buttonStyle(PressFade())
                } else if let right {
                    Text(right).font(ElchiFont.poppins(12, .semibold)).foregroundStyle(c.accentText).lineLimit(1)
                }
                if let step {
                    Text("\(step.0) / \(step.1)").font(ElchiFont.poppins(12, .semibold)).foregroundStyle(c.softText)
                        .padding(.horizontal, 12).padding(.vertical, 6)
                        .background(c.soft, in: Capsule())
                        .accessibilityIdentifier("elchi.step")
                }
            }
            .frame(height: 64)
            .padding(.horizontal, 16)
            if let step {
                GeometryReader { geo in
                    Capsule().fill(c.brand).frame(width: geo.size.width * CGFloat(step.0) / CGFloat(max(step.1, 1)))
                }
                .frame(height: 4)
                .background(c.line, in: Capsule())
                .padding(.horizontal, 16).padding(.bottom, 6)
                .accessibilityHidden(true)
            }
            if let accessory { accessory }
            if let banners { BannerHost(center: banners) }
            if let banner { Banner(banner.text, tone: banner.tone).id(banner.text) }
            ScrollViewReader { proxy in
                ScrollView {
                    Color.clear.frame(height: 0).id(Self.topID)
                    VStack(alignment: .leading, spacing: 12) { content }
                        .padding(EdgeInsets(top: 6, leading: 16, bottom: 18, trailing: 16))
                }
                .scrollDismissesKeyboard(.interactively)
                .onChange(of: scrollTop) { _, _ in withAnimation(.easeOut(duration: 0.25)) { proxy.scrollTo(Self.topID, anchor: .top) } }
                .task(id: initialScroll) {
                    guard let initialScroll else { return }
                    // After the first layout pass, so the target exists.
                    try? await Task.sleep(for: .milliseconds(350))
                    withAnimation(.easeOut(duration: 0.3)) { proxy.scrollTo(initialScroll, anchor: .top) }
                }
                // `keepVisible`: the view (by id) that must stay above the keyboard while a field is being typed in -
                // once now, and again when the keyboard has finished rising and the scroll area has shrunk.
                .onChange(of: keepVisible) { _, id in reveal(id, proxy) }
                .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardDidShowNotification)) { _ in reveal(keepVisible, proxy) }
            }
            let footerView = VStack(spacing: 8) { footer }
            if showsFooter && !(footer is EmptyView) {
                footerView
                    .padding(EdgeInsets(top: 12, leading: 16, bottom: 6, trailing: 16))
                    .frame(maxWidth: .infinity)
                    .background(c.card.ignoresSafeArea(edges: .bottom))
                    .overlay(alignment: .top) { Rectangle().fill(c.line).frame(height: 1) }
            }
        }
        .background(c.page.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
        .toolbar {
            // The number pad has no return key: "Yopish" over it puts it away.
            if let keyboardDone {
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button(keyboardDone) {
                        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
                    }
                    .font(ElchiFont.poppins(15, .semibold))
                    .tint(c.brand)
                    .accessibilityIdentifier("elchi.keyboard.done")
                }
            }
        }
    }

    private static var topID: String { "elchi.scaffold.top" }

    private func reveal(_ id: AnyHashable?, _ proxy: ScrollViewProxy) {
        guard let id else { return }
        withAnimation(.easeOut(duration: 0.25)) { proxy.scrollTo(id, anchor: .bottom) }
    }
}

/// From / To card of the home sheet: origin ring, destination pin, dashed connector, chevrons. An end with no place
/// shows its question ("Qayerdan?") in the placeholder colour.
public struct RouteCard: View {
    public struct End {
        let title: String, detail: String?, isSet: Bool, label: String, action: () -> Void
        public init(title: String, detail: String?, isSet: Bool, label: String, action: @escaping () -> Void) {
            self.title = title
            self.detail = detail
            self.isSet = isSet
            self.label = label
            self.action = action
        }
    }

    let from: End, to: End
    /// The design's swap button (BOSQICH 02 home): drawn at the right instead of the chevrons.
    let swapLabel: String?
    let onSwap: (() -> Void)?
    @Environment(\.elchi) private var c

    public init(from: End, to: End, swapLabel: String? = nil, onSwap: (() -> Void)? = nil) {
        self.from = from
        self.to = to
        self.swapLabel = swapLabel
        self.onSwap = onSwap
    }

    public var body: some View {
        VStack(spacing: 0) {
            row(from, origin: true)
            Rectangle().fill(c.field).frame(height: 1).padding(.leading, 28)
            row(to, origin: false)
        }
        .padding(.horizontal, 16).padding(.vertical, 4)
        .background(c.card, in: RoundedRectangle(cornerRadius: ElchiShape.card))
        .overlay(alignment: .leading) {
            // Dashed connector between the two symbols (decorative).
            VerticalLine()
                .stroke(c.isDark ? Color(hex: 0x3A4A60) : Color(hex: 0xB8C7D9), style: StrokeStyle(lineWidth: 2, dash: [4, 4]))
                .frame(width: 2)
                .padding(.vertical, 38)
                .offset(x: 22)
                .accessibilityHidden(true)
        }
        .overlay(alignment: .trailing) {
            if let onSwap {
                Button(action: onSwap) {
                    Image(systemName: "arrow.up.arrow.down").font(.system(size: 14, weight: .semibold)).foregroundStyle(c.text)
                        .frame(width: 36, height: 36)
                        .background(c.card, in: Circle())
                        .overlay { Circle().strokeBorder(c.line, lineWidth: 1) }
                        .frame(width: 44, height: 44)
                        .contentShape(Circle())
                }
                .buttonStyle(PressFade())
                .padding(.trailing, 8)
                .accessibilityLabel(swapLabel ?? "")
                .accessibilityIdentifier("elchi.route.swap")
            }
        }
        .shadow(color: c.shadow.opacity(0.8), radius: 12, y: 6)
    }

    private func row(_ end: End, origin: Bool) -> some View {
        Button(action: end.action) {
            HStack(spacing: 14) {
                Group {
                    if origin {
                        Circle().strokeBorder(c.brand, lineWidth: 3).background(Circle().fill(c.card)).frame(width: 14, height: 14)
                    } else {
                        UnevenRoundedRectangle(topLeadingRadius: 7, bottomLeadingRadius: 0, bottomTrailingRadius: 7, topTrailingRadius: 7)
                            .fill(c.isDark ? c.brand : c.navy)
                            .frame(width: 13, height: 13)
                            .rotationEffect(.degrees(-45))
                    }
                }
                .frame(width: 14)
                VStack(alignment: .leading, spacing: 1) {
                    Text(end.title).font(ElchiFont.poppins(15, .semibold)).foregroundStyle(end.isSet ? c.text : c.placeholder).lineLimit(1)
                    if let detail = end.detail {
                        Text(detail).font(ElchiFont.caption).foregroundStyle(c.muted).lineLimit(1)
                    }
                }
                Spacer(minLength: 0)
                if onSwap == nil {
                    ElchiIcon.chevR.image(size: 18).foregroundStyle(c.placeholder)
                } else {
                    Color.clear.frame(width: 36, height: 1)
                }
            }
            .padding(.vertical, 12)
            .frame(minHeight: 44)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(end.isSet ? "\(end.label): \(end.title)\(end.detail.map { ", \($0)" } ?? "")" : end.title)
        .accessibilityAddTraits(.isButton)
    }
}

private struct VerticalLine: Shape {
    func path(in rect: CGRect) -> Path {
        Path { p in
            p.move(to: CGPoint(x: rect.midX, y: rect.minY))
            p.addLine(to: CGPoint(x: rect.midX, y: rect.maxY))
        }
    }
}

/// One row of the prototype's `list` block: tinted icon circle, title, description, optional trailing text,
/// chevron. `highlighted` = the current item (azure), `danger` = sign out (red, no chevron).
public struct ListRow: View {
    let icon: ElchiIcon?, title: String, description: String?, trailing: String?, highlighted: Bool, danger: Bool, chevron: Bool
    let first: Bool
    let action: (() -> Void)?
    @Environment(\.elchi) private var c

    public init(icon: ElchiIcon? = nil, title: String, description: String? = nil, trailing: String? = nil, highlighted: Bool = false,
                danger: Bool = false, chevron: Bool = true, first: Bool = false, action: (() -> Void)?) {
        self.icon = icon
        self.title = title
        self.description = description
        self.trailing = trailing
        self.highlighted = highlighted
        self.danger = danger
        self.chevron = chevron
        self.first = first
        self.action = action
    }

    public var body: some View {
        let err = c.tone(.err)
        let content = HStack(spacing: 12) {
            if let icon {
                icon.image(size: 18)
                    .foregroundStyle(danger ? err.fg : highlighted ? c.onBrand : c.accentText)
                    .frame(width: 38, height: 38)
                    .background(danger ? err.bg : highlighted ? c.brand : (c.isDark ? Color(hex: 0x1D2A3A) : Color(hex: 0xEEF4FA)), in: Circle())
            }
            VStack(alignment: .leading, spacing: 1) {
                Text(title).font(ElchiFont.poppins(14, .semibold)).foregroundStyle(danger ? err.fg : c.text)
                if let description { Text(description).font(ElchiFont.caption).foregroundStyle(c.muted) }
            }
            Spacer(minLength: 0)
            if let trailing { Text(trailing).font(ElchiFont.poppins(12, .semibold)).foregroundStyle(c.muted).lineLimit(1) }
            if chevron && !danger && action != nil { ElchiIcon.chevR.image(size: 16).foregroundStyle(c.placeholder) }
        }
        .padding(.horizontal, 14).padding(.vertical, 10)
        .frame(minHeight: description == nil ? 52 : 64)
        .background(highlighted ? (c.isDark ? Color(hex: 0x0E2A45) : Color(hex: 0xEAF5FF)) : .clear)
        .overlay(alignment: .top) { if !first { Rectangle().fill(c.field).frame(height: 1) } }
        .contentShape(Rectangle())

        if let action {
            Button(action: action) { content }
                .buttonStyle(PressFade())
                .accessibilityAddTraits(highlighted ? .isSelected : [])
        } else {
            content.accessibilityElement(children: .combine)
        }
    }
}

/// White rounded container for `ListRow`s.
public struct ElchiList<Content: View>: View {
    let content: Content
    @Environment(\.elchi) private var c

    public init(@ViewBuilder content: () -> Content) { self.content = content() }

    public var body: some View {
        VStack(spacing: 0) { content }
            .padding(.vertical, 4)
            .background(c.card, in: RoundedRectangle(cornerRadius: ElchiShape.card))
            .clipShape(RoundedRectangle(cornerRadius: ElchiShape.card))
            .shadow(color: c.shadow.opacity(0.8), radius: 12, y: 6)
    }
}

/// Three-column choice grid (parcel type): the chosen tile is azure with navy text.
public struct OptionGrid<Value: Hashable>: View {
    let options: [(Value, String)]
    let selected: Value?
    let onSelect: (Value) -> Void
    @Environment(\.elchi) private var c

    public init(_ options: [(Value, String)], selected: Value?, onSelect: @escaping (Value) -> Void) {
        self.options = options
        self.selected = selected
        self.onSelect = onSelect
    }

    public var body: some View {
        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 3), spacing: 8) {
            ForEach(options, id: \.0) { value, label in
                let active = value == selected
                Button { onSelect(value) } label: {
                    Text(label).font(ElchiFont.poppins(13, .medium)).lineLimit(1).minimumScaleFactor(0.8)
                        .foregroundStyle(active ? c.onBrand : c.text)
                        .frame(maxWidth: .infinity, minHeight: 44)
                        .background(active ? c.brand : c.field, in: RoundedRectangle(cornerRadius: 14))
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(active ? .isSelected : [])
            }
        }
    }
}

/// A radio card (size category): icon tile, name, limits line, radio ring. Selected = azure border + ring.
public struct RadioCard: View {
    let icon: ElchiIcon, title: String, detail: String, selected: Bool, action: () -> Void
    @Environment(\.elchi) private var c

    public init(icon: ElchiIcon, title: String, detail: String, selected: Bool, action: @escaping () -> Void) {
        self.icon = icon
        self.title = title
        self.detail = detail
        self.selected = selected
        self.action = action
    }

    public var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                icon.image(size: 20).foregroundStyle(c.accentText)
                    .frame(width: 40, height: 40)
                    .background(c.card, in: RoundedRectangle(cornerRadius: 12))
                    .overlay { RoundedRectangle(cornerRadius: 12).strokeBorder(c.line, lineWidth: 1) }
                VStack(alignment: .leading, spacing: 1) {
                    Text(title).font(ElchiFont.poppins(14, .semibold)).foregroundStyle(c.text)
                    Text(detail).font(ElchiFont.caption).foregroundStyle(c.muted)
                }
                Spacer(minLength: 0)
                Circle().strokeBorder(selected ? c.brand : Color(hex: 0xB8C2CE), lineWidth: selected ? 6 : 2).frame(width: 20, height: 20)
            }
            .padding(.horizontal, 14).padding(.vertical, 12)
            .background(selected ? (c.isDark ? Color(hex: 0x0E2A45) : Color(hex: 0xF0F8FF)) : c.card, in: RoundedRectangle(cornerRadius: 16))
            .overlay { RoundedRectangle(cornerRadius: 16).strokeBorder(selected ? c.brand : c.line, lineWidth: selected ? 2 : 1) }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
    }
}

/// Dashed upload target (parcel photo).
public struct UploadBox: View {
    let title: String, description: String, action: () -> Void
    @Environment(\.elchi) private var c

    public init(title: String, description: String, action: @escaping () -> Void) {
        self.title = title
        self.description = description
        self.action = action
    }

    public var body: some View {
        Button(action: action) {
            VStack(spacing: 8) {
                ElchiIcon.upload.image(size: 24).foregroundStyle(c.accentText)
                    .frame(width: 56, height: 56)
                    .background(c.soft, in: Circle())
                Text(title).font(ElchiFont.poppins(15, .semibold)).foregroundStyle(c.text)
                Text(description).font(ElchiFont.poppins(13)).foregroundStyle(c.muted).frame(maxWidth: 260)
            }
            .multilineTextAlignment(.center)
            .padding(.vertical, 30).padding(.horizontal, 16)
            .frame(maxWidth: .infinity)
            .background(c.isDark ? Color(hex: 0x0F2233) : Color(hex: 0xF4FAFF), in: RoundedRectangle(cornerRadius: ElchiShape.card))
            .overlay { RoundedRectangle(cornerRadius: ElchiShape.card).strokeBorder(c.brand, style: StrokeStyle(lineWidth: 2, dash: [7, 5])) }
            .contentShape(Rectangle())
        }
        .buttonStyle(PressFade())
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
    }
}

/// Centered icon, title and one line (empty and done states).
public struct EmptyState: View {
    let icon: ElchiIcon, title: String, description: String?
    @Environment(\.elchi) private var c

    public init(icon: ElchiIcon, title: String, description: String? = nil) {
        self.icon = icon
        self.title = title
        self.description = description
    }

    public var body: some View {
        VStack(spacing: 10) {
            icon.image(size: 28).foregroundStyle(c.muted)
                .frame(width: 64, height: 64)
                .background(c.isDark ? Color(hex: 0x24272E) : Color(hex: 0xE4E9EF), in: Circle())
            Text(title).font(ElchiFont.poppins(16, .semibold)).foregroundStyle(c.text)
            if let description {
                Text(description).font(ElchiFont.poppins(13)).foregroundStyle(c.muted).lineSpacing(3).frame(maxWidth: 280)
            }
        }
        .multilineTextAlignment(.center)
        .padding(.vertical, 32).padding(.horizontal, 16)
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
    }
}

/// A read-only field that opens a picker (departure window): label, value or placeholder, trailing icon.
public struct PickerField: View {
    let label: String, value: String?, placeholder: String, icon: ElchiIcon, hint: String?, error: Bool, action: () -> Void
    @Environment(\.elchi) private var c

    public init(label: String, value: String?, placeholder: String, icon: ElchiIcon = .clock, hint: String? = nil, error: Bool = false,
                action: @escaping () -> Void) {
        self.label = label
        self.value = value
        self.placeholder = placeholder
        self.icon = icon
        self.hint = hint
        self.error = error
        self.action = action
    }

    public var body: some View {
        let err = c.tone(.err)
        VStack(alignment: .leading, spacing: 6) {
            Text(label).font(ElchiFont.label).foregroundStyle(c.text)
            Button(action: action) {
                HStack(spacing: 10) {
                    Text(value ?? placeholder).font(ElchiFont.body).foregroundStyle(value == nil ? c.placeholder : c.text)
                    Spacer(minLength: 0)
                    icon.image(size: 18).foregroundStyle(c.muted)
                }
                .padding(.horizontal, 16)
                .frame(minHeight: 52)
                .background(c.field, in: RoundedRectangle(cornerRadius: ElchiShape.field))
                .overlay { if error { RoundedRectangle(cornerRadius: ElchiShape.field).strokeBorder(err.fg, lineWidth: 1.5) } }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(label)
            .accessibilityValue(value ?? placeholder)
            if let hint { Text(hint).font(ElchiFont.caption).foregroundStyle(c.muted) }
        }
    }
}

/// Grey placeholder cards while a list loads.
public struct SkeletonCards: View {
    let count: Int
    @Environment(\.elchi) private var c

    public init(count: Int = 1) { self.count = count }

    public var body: some View {
        VStack(spacing: 10) {
            ForEach(0..<count, id: \.self) { _ in
                VStack(alignment: .leading, spacing: 10) {
                    Capsule().fill(c.isDark ? Color(hex: 0x2A2E36) : Color(hex: 0xE4E9EF)).frame(width: 180, height: 12)
                    Capsule().fill(c.field).frame(height: 10).padding(.trailing, 40)
                    Capsule().fill(c.field).frame(width: 120, height: 10)
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(c.card, in: RoundedRectangle(cornerRadius: 20))
                .overlay { RoundedRectangle(cornerRadius: 20).strokeBorder(c.line, lineWidth: 1) }
            }
        }
        .accessibilityHidden(true)
    }
}

// MARK: - Stage 03 blocks

/// One detail line of an `ItemCard`: muted by default, or in a tone's colour (the offer countdown is `warn`).
public struct ItemLine: Hashable {
    let text: String
    let tone: Tone?
    public init(_ text: String, tone: Tone? = nil) {
        self.text = text
        self.tone = tone
    }
}

/// A list/detail item (the prototype's `item` block): title (+ icon) and status badge, a secondary line, detail lines,
/// then meta on the left and the amount on the right; `actions` go last, inside the card, so a card's buttons are
/// never mistaken for the next one's. `highlighted` = brand border, `underline` = the offer cards' brand rule under
/// the title, `muted` = a closed offer (grey amount). With `action` the whole card is one button.
public struct ItemCard<Actions: View>: View {
    public typealias Line = ItemLine

    let title: String, icon: ElchiIcon?, badge: (text: String, tone: Tone)?, sub: String?, lines: [Line], meta: String?, right: String?
    let highlighted: Bool, underline: Bool, muted: Bool
    /// The meta line in the accent colour ("Yangi taklif: …" while an open offer waits).
    let metaAccent: Bool
    let action: (() -> Void)?
    let actions: Actions
    @Environment(\.elchi) private var c

    public init(title: String, icon: ElchiIcon? = nil, badge: (text: String, tone: Tone)? = nil, sub: String? = nil, lines: [Line] = [],
                meta: String? = nil, right: String? = nil, highlighted: Bool = false, underline: Bool = false, muted: Bool = false,
                metaAccent: Bool = false, action: (() -> Void)? = nil, @ViewBuilder actions: () -> Actions) {
        self.metaAccent = metaAccent
        self.title = title
        self.icon = icon
        self.badge = badge
        self.sub = sub
        self.lines = lines
        self.meta = meta
        self.right = right
        self.highlighted = highlighted
        self.underline = underline
        self.muted = muted
        self.action = action
        self.actions = actions()
    }

    public var body: some View {
        if let action {
            Button(action: action) { card.contentShape(Rectangle()) }
                .buttonStyle(PressFade())
                .accessibilityElement(children: .combine)
                .accessibilityAddTraits(.isButton)
        } else {
            card
        }
    }

    private var longBadge: Bool { (badge?.text.count ?? 0) > 16 }

    private var card: some View {
        let shape = RoundedRectangle(cornerRadius: ElchiShape.card)
        return VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top, spacing: 10) {
                HStack(spacing: 8) {
                    if let icon { icon.image(size: 16).foregroundStyle(c.accentText) }
                    Text(title).font(ElchiFont.poppins(15, .semibold)).foregroundStyle(muted ? c.muted : c.text)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
                if let badge, !longBadge { Badge(badge.text, tone: badge.tone) }
            }
            .padding(.bottom, underline ? 10 : 0)
            .overlay(alignment: .bottom) { if underline { Rectangle().fill(c.brand).frame(height: 1.5) } }
            .accessibilityElement(children: .combine)
            // A long status ("Operator yetkazilganini qayd etdi") goes under the title rather than being cut short.
            if let badge, longBadge { Badge(badge.text, tone: badge.tone) }
            if let sub {
                Text(sub).font(ElchiFont.poppins(13)).foregroundStyle(c.muted).lineSpacing(2).fixedSize(horizontal: false, vertical: true)
            }
            ForEach(lines, id: \.self) { line in
                Text(line.text).font(ElchiFont.caption).lineSpacing(2)
                    .foregroundStyle(line.tone.map { c.tone($0).fg } ?? c.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if meta != nil || right != nil {
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text(meta ?? "").font(ElchiFont.poppins(13)).foregroundStyle(metaAccent ? c.accentText : c.muted)
                    Spacer(minLength: 0)
                    if let right {
                        Text(right).font(ElchiFont.poppins(16, .semibold)).foregroundStyle(muted ? c.placeholder : c.accentText).lineLimit(1)
                    }
                }
                .padding(.top, 4)
            }
            actions
        }
        .padding(.horizontal, 16).padding(.vertical, 14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(c.card, in: shape)
        .overlay { shape.strokeBorder(highlighted ? c.brand : c.line, lineWidth: highlighted ? 2 : 1) }
        .shadow(color: c.shadow, radius: 12, y: 6)
    }
}

extension ItemCard where Actions == EmptyView {
    public init(title: String, icon: ElchiIcon? = nil, badge: (text: String, tone: Tone)? = nil, sub: String? = nil, lines: [Line] = [],
                meta: String? = nil, right: String? = nil, highlighted: Bool = false, underline: Bool = false, muted: Bool = false,
                metaAccent: Bool = false, action: (() -> Void)? = nil) {
        self.init(title: title, icon: icon, badge: badge, sub: sub, lines: lines, meta: meta, right: right, highlighted: highlighted,
                  underline: underline, muted: muted, metaAccent: metaAccent, action: action) { EmptyView() }
    }
}

/// Money lines (the prototype's `money` block): label left, amount right, the emphasised line after a hairline;
/// an optional unticked checkbox under them ("Bonusni ishlataman").
public struct MoneyLines: View {
    public struct Row: Hashable {
        let label: String, value: String, emphasis: Bool, tone: Tone?
        public init(_ label: String, _ value: String, emphasis: Bool = false, tone: Tone? = nil) {
            self.label = label
            self.value = value
            self.emphasis = emphasis
            self.tone = tone
        }
    }

    let title: String?
    let rows: [Row]
    let check: String?
    @Binding var checked: Bool
    @Environment(\.elchi) private var c

    public init(title: String? = nil, rows: [Row], check: String? = nil, checked: Binding<Bool> = .constant(false)) {
        self.title = title
        self.rows = rows
        self.check = check
        _checked = checked
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let title { Text(title).font(ElchiFont.poppins(13, .semibold)).foregroundStyle(c.text).padding(.top, 8).padding(.bottom, 2) }
            ForEach(Array(rows.enumerated()), id: \.offset) { index, row in
                HStack(spacing: 10) {
                    Text(row.label)
                    Spacer(minLength: 0)
                    Text(row.value).lineLimit(1)
                }
                .font(ElchiFont.poppins(13, row.emphasis ? .semibold : .regular))
                .foregroundStyle(row.tone.map { c.tone($0).fg } ?? c.text)
                .padding(.vertical, 7)
                .overlay(alignment: .top) { if index > 0 && row.emphasis { Rectangle().fill(c.line).frame(height: 1) } }
                .accessibilityElement(children: .combine)
            }
            if let check {
                Button { checked.toggle() } label: {
                    HStack(alignment: .top, spacing: 10) {
                        CheckBox(on: checked)
                        Text(check).font(ElchiFont.poppins(13, .medium)).foregroundStyle(c.text).multilineTextAlignment(.leading)
                        Spacer(minLength: 0)
                    }
                    .padding(.top, 10).padding(.bottom, 8)
                    .frame(minHeight: 44)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .overlay(alignment: .top) { Rectangle().fill(c.line).frame(height: 1) }
                .accessibilityAddTraits(checked ? [.isSelected] : [])
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 6)
        .background(c.page, in: RoundedRectangle(cornerRadius: 16))
        .overlay { RoundedRectangle(cornerRadius: 16).strokeBorder(c.line, lineWidth: 1) }
    }
}

/// A square tick box: grey outline when off, brand fill with a check when on (the state is also in the traits).
public struct CheckBox: View {
    let on: Bool
    @Environment(\.elchi) private var c

    public init(on: Bool) { self.on = on }

    public var body: some View {
        RoundedRectangle(cornerRadius: 6)
            .fill(on ? c.brand : c.card)
            .overlay { RoundedRectangle(cornerRadius: 6).strokeBorder(on ? c.brand : Color(hex: 0x9AA6B5), lineWidth: 2) }
            .overlay { if on { ElchiIcon.check.image(size: 14).foregroundStyle(c.onBrand) } }
            .frame(width: 20, height: 20)
    }
}

/// A centred confirmation card over a dim scrim (the prototype's `dialog` overlay). Tapping the scrim dismisses.
public struct DialogOverlay<Content: View>: View {
    let dismissLabel: String
    let onDismiss: () -> Void
    let content: Content
    @Environment(\.elchi) private var c

    public init(dismissLabel: String, onDismiss: @escaping () -> Void, @ViewBuilder content: () -> Content) {
        self.dismissLabel = dismissLabel
        self.onDismiss = onDismiss
        self.content = content()
    }

    public var body: some View {
        ZStack {
            Color(hex: 0x0A1226, opacity: 0.5).ignoresSafeArea()
                .onTapGesture(perform: onDismiss)
                .accessibilityElement()
                .accessibilityLabel(dismissLabel)
                .accessibilityAddTraits(.isButton)
                .accessibilityAction { onDismiss() }
            VStack(alignment: .leading, spacing: 14) { content }
                .padding(22)
                .frame(maxWidth: 360)
                .background(c.card, in: RoundedRectangle(cornerRadius: 28))
                .shadow(color: c.shadow, radius: 24, y: 10)
                .padding(.horizontal, 20)
                .accessibilityElement(children: .contain)
                .accessibilityAddTraits(.isModal)
        }
    }
}

// MARK: - Stage 04 blocks

/// A card's own title line (the prototype's `card` with a title): semibold title, optional badge on the right.
/// The first `CardRow` after it keeps its hairline (`first: false`).
public struct CardTitle: View {
    let title: String
    let badge: (text: String, tone: Tone)?
    @Environment(\.elchi) private var c

    public init(_ title: String, badge: (text: String, tone: Tone)? = nil) {
        self.title = title
        self.badge = badge
    }

    public var body: some View {
        HStack(spacing: 8) {
            Text(title).font(ElchiFont.poppins(15, .semibold)).foregroundStyle(c.text).lineLimit(2)
                .accessibilityAddTraits(.isHeader)
            Spacer(minLength: 0)
            if let badge { Badge(badge.text, tone: badge.tone) }
        }
        .padding(.top, 12).padding(.bottom, 4)
    }
}

/// A choice field (the prototype's `field` with `sel`): label, the chosen option on the field colour, a chevron;
/// tapping opens the system menu with every option.
public struct SelectField<Value: Hashable>: View {
    let label: String
    let options: [(Value, String)]
    let selected: Value?
    let placeholder: String
    let onSelect: (Value) -> Void
    @Environment(\.elchi) private var c

    public init(label: String, options: [(Value, String)], selected: Value?, placeholder: String, onSelect: @escaping (Value) -> Void) {
        self.label = label
        self.options = options
        self.selected = selected
        self.placeholder = placeholder
        self.onSelect = onSelect
    }

    public var body: some View {
        let value = options.first { $0.0 == selected }?.1
        VStack(alignment: .leading, spacing: 6) {
            Text(label).font(ElchiFont.label).foregroundStyle(c.text)
            Menu {
                ForEach(options, id: \.0) { option, text in
                    Button(text) { onSelect(option) }
                }
            } label: {
                HStack(spacing: 10) {
                    Text(value ?? placeholder).font(ElchiFont.body).foregroundStyle(value == nil ? c.placeholder : c.text)
                        .multilineTextAlignment(.leading)
                    Spacer(minLength: 0)
                    ElchiIcon.chevD.image(size: 18).foregroundStyle(c.muted)
                }
                .padding(.horizontal, 16)
                .frame(minHeight: 52)
                .background(c.field, in: RoundedRectangle(cornerRadius: ElchiShape.field))
                .contentShape(Rectangle())
            }
            .accessibilityLabel(label)
            .accessibilityValue(value ?? placeholder)
        }
    }
}

/// A status ladder (the prototype's `steps`): green dot and line behind, azure dot for the current step, an empty
/// ring ahead. The state is also said in words to VoiceOver, not only in colour.
public struct StepLadder: View {
    public struct Step: Hashable {
        public enum State: Hashable { case done, current, ahead }
        let title: String, detail: String?, state: State
        public init(_ title: String, detail: String? = nil, state: State) {
            self.title = title
            self.detail = detail
            self.state = state
        }
    }

    let steps: [Step]
    let stateLabels: (done: String, current: String)
    @Environment(\.elchi) private var c

    public init(_ steps: [Step], doneLabel: String, currentLabel: String) {
        self.steps = steps
        stateLabels = (doneLabel, currentLabel)
    }

    public var body: some View {
        let ok = c.tone(.ok).fg
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                HStack(alignment: .top, spacing: 12) {
                    VStack(spacing: 0) {
                        Circle()
                            .fill(step.state == .done ? ok : step.state == .current ? c.brand : c.card)
                            .overlay { if step.state == .ahead { Circle().strokeBorder(c.outline, lineWidth: 2) } }
                            .frame(width: 14, height: 14)
                        Rectangle().fill(index == steps.count - 1 ? .clear : step.state == .done ? ok : c.line)
                            .frame(width: 2).frame(minHeight: 20)
                    }
                    .frame(width: 14)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(step.title).font(ElchiFont.poppins(14, step.state == .ahead ? .medium : .semibold))
                            .foregroundStyle(step.state == .ahead ? c.placeholder : c.text)
                        if let detail = step.detail { Text(detail).font(ElchiFont.caption).foregroundStyle(c.muted) }
                    }
                    .padding(.bottom, 14)
                    .offset(y: -3)
                    Spacer(minLength: 0)
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel([step.title, step.detail, step.state == .done ? stateLabels.done : step.state == .current ? stateLabels.current : nil]
                    .compactMap { $0 }.joined(separator: ", "))
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(c.card, in: RoundedRectangle(cornerRadius: ElchiShape.card))
        .shadow(color: c.shadow, radius: 12, y: 6)
    }
}

/// Five tappable stars (the prototype's `stars`): azure up to the choice, grey after; one adjustable element for
/// VoiceOver.
public struct StarsInput: View {
    @Binding var value: Int
    let label: (Int) -> String
    @Environment(\.elchi) private var c

    public init(value: Binding<Int>, label: @escaping (Int) -> String) {
        _value = value
        self.label = label
    }

    public var body: some View {
        HStack(spacing: 10) {
            ForEach(1...5, id: \.self) { star in
                Button { value = star } label: {
                    Image(systemName: "star.fill").resizable().scaledToFit()
                        .foregroundStyle(star <= value ? c.brand : (c.isDark ? Color(hex: 0x3A3F48) : Color(hex: 0xD5DCE5)))
                        .frame(width: 40, height: 40)
                        .frame(minWidth: 44, minHeight: 44)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(label(star))
                .accessibilityAddTraits(star == value ? .isSelected : [])
            }
        }
        .frame(maxWidth: .infinity)
    }
}

/// One chat line (the prototype's `chat`): the person's own on the right in brand azure, the other side's on the
/// left on a card with its label above, a hidden one grey and italic, a system line centred without a bubble.
public struct ChatBubble: View {
    public enum Kind { case mine, theirs, hidden, system, operatorReply }

    let kind: Kind
    let text: String
    let label: String?
    let time: String?
    @Environment(\.elchi) private var c

    public init(_ kind: Kind, text: String, label: String? = nil, time: String? = nil) {
        self.kind = kind
        self.text = text
        self.label = label
        self.time = time
    }

    public var body: some View {
        let mine = kind == .mine
        HStack {
            if mine || kind == .system { Spacer(minLength: kind == .system ? 0 : 56) }
            VStack(alignment: mine ? .trailing : kind == .system ? .center : .leading, spacing: 3) {
                if let label { Text(label).font(ElchiFont.poppins(11, .semibold)).foregroundStyle(c.accentText) }
                if kind == .system {
                    Text(text).font(ElchiFont.caption).foregroundStyle(c.muted).multilineTextAlignment(.center)
                        .padding(.horizontal, 8).padding(.vertical, 2)
                } else {
                    Text(text).font(ElchiFont.poppins(13.5)).italic(kind == .hidden).lineSpacing(3)
                        .foregroundStyle(mine ? c.onBrand : kind == .hidden ? c.muted : c.text)
                        .padding(.horizontal, 14).padding(.vertical, 10)
                        .background(mine ? c.brand : kind == .hidden ? c.field : c.card, in: RoundedRectangle(cornerRadius: 18))
                        .overlay {
                            if kind == .theirs || kind == .operatorReply {
                                RoundedRectangle(cornerRadius: 18).strokeBorder(kind == .operatorReply ? c.brand : c.line, lineWidth: kind == .operatorReply ? 1.5 : 1)
                            }
                        }
                        .textSelection(.enabled)
                }
                if let time { Text(time).font(ElchiFont.poppins(11)).foregroundStyle(c.placeholder) }
            }
            .accessibilityElement(children: .combine)
            if !mine || kind == .system { Spacer(minLength: kind == .system ? 0 : 56) }
        }
        .frame(maxWidth: .infinity)
    }
}

/// A live-location state row (the prototype's `gps`): a coloured dot (with a halo while live), the state, and its
/// explanation lines.
public struct LiveStateRow: View {
    public enum Level { case live, delayed, lost, none }

    let level: Level
    let title: String
    let lines: [String]
    @Environment(\.elchi) private var c

    public init(_ level: Level, title: String, lines: [String]) {
        self.level = level
        self.title = title
        self.lines = lines
    }

    public var body: some View {
        let dot: Color = switch level {
        case .live: Color(hex: 0x1E8E4E)
        case .delayed: Color(hex: 0xE0A100)
        case .lost: Color(hex: 0xD64545)
        case .none: Color(hex: 0x9AA6B5)
        }
        HStack(alignment: .top, spacing: 10) {
            Circle().fill(dot).frame(width: 10, height: 10)
                .background { if level == .live { Circle().fill(dot.opacity(0.2)).frame(width: 18, height: 18) } }
                .padding(.top, 4)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(ElchiFont.poppins(12.5, .semibold)).foregroundStyle(c.text)
                ForEach(lines, id: \.self) { Text($0).font(ElchiFont.poppins(11)).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true) }
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 12).padding(.vertical, 10)
        .background(c.card, in: RoundedRectangle(cornerRadius: 14))
        .overlay { RoundedRectangle(cornerRadius: 14).strokeBorder(c.line, lineWidth: 1) }
        .accessibilityElement(children: .combine)
    }
}

// MARK: - Stage 05 blocks

/// Figures side by side (the prototype's `stat` block): a small grey label over a larger value.
public struct StatTiles: View {
    let items: [(label: String, value: String)]
    @Environment(\.elchi) private var c

    public init(_ items: [(label: String, value: String)]) { self.items = items }

    public var body: some View {
        HStack(spacing: 8) {
            ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.label).font(ElchiFont.caption).foregroundStyle(c.muted).lineLimit(1).minimumScaleFactor(0.8)
                    Text(item.value).font(ElchiFont.poppins(18, .semibold)).foregroundStyle(c.text).lineLimit(1).minimumScaleFactor(0.6)
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(c.card, in: RoundedRectangle(cornerRadius: 18))
                .shadow(color: c.shadow.opacity(0.7), radius: 12, y: 6)
                .accessibilityElement(children: .combine)
            }
        }
    }
}

/// Who is signed in (the prototype's `avatar` block): initials (or a person icon) on the soft tint, name, phone, badges.
public struct AvatarCard: View {
    let initials: String?
    let name: String
    let phone: String?
    let badges: [(text: String, tone: Tone)]
    @Environment(\.elchi) private var c

    public init(initials: String?, name: String, phone: String?, badge: (text: String, tone: Tone)? = nil) {
        self.init(initials: initials, name: name, phone: phone, badges: badge.map { [$0] } ?? [])
    }

    public init(initials: String?, name: String, phone: String?, badges: [(text: String, tone: Tone)]) {
        self.initials = initials
        self.name = name
        self.phone = phone
        self.badges = badges
    }

    public var body: some View {
        HStack(spacing: 14) {
            Group {
                if let initials {
                    Text(initials).font(ElchiFont.poppins(22, .semibold)).foregroundStyle(c.softText)
                } else {
                    ElchiIcon.user.image(size: 28).foregroundStyle(c.softText)
                }
            }
            .frame(width: 64, height: 64)
            .background(c.soft, in: Circle())
            .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 3) {
                Text(name).font(ElchiFont.poppins(18, .semibold)).foregroundStyle(c.text).lineLimit(2)
                if let phone { Text(phone).font(ElchiFont.poppins(13)).foregroundStyle(c.muted) }
                if !badges.isEmpty {
                    HStack(spacing: 6) {
                        ForEach(Array(badges.enumerated()), id: \.offset) { _, badge in Badge(badge.text, tone: badge.tone) }
                    }
                    .padding(.top, 4)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(16)
        .background(c.card, in: RoundedRectangle(cornerRadius: ElchiShape.card))
        .shadow(color: c.shadow, radius: 12, y: 6)
        .accessibilityElement(children: .combine)
    }
}

/// Questions and answers (the prototype's `faq` block): one card, a question per row, tap to open or close.
public struct FaqList: View {
    let items: [(question: String, answer: String)]
    @State private var open: Set<Int>
    @Environment(\.elchi) private var c

    public init(_ items: [(question: String, answer: String)], initiallyOpen: Set<Int> = [0]) {
        self.items = items
        _open = State(initialValue: initiallyOpen)
    }

    public var body: some View {
        VStack(spacing: 0) {
            ForEach(Array(items.enumerated()), id: \.offset) { index, item in
                let isOpen = open.contains(index)
                VStack(alignment: .leading, spacing: 6) {
                    Button {
                        withAnimation(.easeOut(duration: 0.2)) {
                            if isOpen { open.remove(index) } else { open.insert(index) }
                        }
                    } label: {
                        HStack(spacing: 10) {
                            Text(item.question).font(ElchiFont.poppins(14, .medium)).foregroundStyle(c.text)
                                .multilineTextAlignment(.leading)
                            Spacer(minLength: 0)
                            (isOpen ? ElchiIcon.chevU : ElchiIcon.chevD).image(size: 16).foregroundStyle(c.muted)
                        }
                        .frame(minHeight: 32)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(isOpen ? .isSelected : [])
                    if isOpen {
                        Text(item.answer).font(ElchiFont.poppins(13)).foregroundStyle(c.muted).lineSpacing(3)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(.vertical, 10)
                .overlay(alignment: .top) { if index > 0 { Rectangle().fill(c.line).frame(height: 1) } }
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 4)
        .background(c.card, in: RoundedRectangle(cornerRadius: ElchiShape.card))
        .shadow(color: c.shadow, radius: 12, y: 6)
    }
}

/// A tick box with its sentence (the prototype's `check` block); the whole row toggles it.
public struct CheckRow: View {
    let text: String
    @Binding var on: Bool
    let danger: Bool
    @Environment(\.elchi) private var c

    public init(_ text: String, on: Binding<Bool>, danger: Bool = false) {
        self.text = text
        _on = on
        self.danger = danger
    }

    public var body: some View {
        Button { on.toggle() } label: {
            HStack(alignment: .top, spacing: 10) {
                CheckBox(on: on)
                Text(text).font(ElchiFont.poppins(13, .medium)).foregroundStyle(c.text).multilineTextAlignment(.leading)
                Spacer(minLength: 0)
            }
            .padding(14)
            .frame(minHeight: 44)
            .background(danger && on ? c.tone(.err).bg : c.card, in: RoundedRectangle(cornerRadius: 14))
            .overlay { RoundedRectangle(cornerRadius: 14).strokeBorder(danger && on ? c.tone(.err).fg : c.line, lineWidth: 1) }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(on ? [.isSelected] : [])
    }
}

/// One of the appearance tiles (Yorug' / Qorong'i / Tizim): icon, name, hint; the chosen one on the brand colour.
public struct ChoiceTile: View {
    let icon: ElchiIcon
    let title: String
    let hint: String
    let selected: Bool
    let action: () -> Void
    @Environment(\.elchi) private var c

    public init(icon: ElchiIcon, title: String, hint: String, selected: Bool, action: @escaping () -> Void) {
        self.icon = icon
        self.title = title
        self.hint = hint
        self.selected = selected
        self.action = action
    }

    public var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 6) {
                icon.image(size: 20).foregroundStyle(selected ? c.onBrand : c.accentText)
                Text(title).font(ElchiFont.poppins(15, .semibold)).foregroundStyle(selected ? c.onBrand : c.text).lineLimit(1)
                Text(hint).font(ElchiFont.poppins(11)).foregroundStyle(selected ? c.onBrand.opacity(0.85) : c.muted)
                    .lineLimit(2).minimumScaleFactor(0.85).multilineTextAlignment(.leading)
            }
            .padding(12)
            .frame(maxWidth: .infinity, minHeight: 96, maxHeight: .infinity, alignment: .topLeading)
            .background(selected ? c.brand : c.card, in: RoundedRectangle(cornerRadius: 18))
            .overlay { RoundedRectangle(cornerRadius: 18).strokeBorder(selected ? c.brand : c.line, lineWidth: 1) }
            .shadow(color: c.shadow.opacity(0.6), radius: 10, y: 4)
            .contentShape(Rectangle())
        }
        .buttonStyle(PressFade())
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
    }
}


// MARK: - Bar actions

/// A round icon button at the right of a screen's bar (44 pt, card colour, shadow), with an optional red count.
public struct BarAction: Identifiable {
    public let id: String
    let icon: ElchiIcon?
    /// An SF Symbol where the kit has no glyph (the design's pencil, registered but not in the generated set).
    let systemImage: String?
    let label: String
    let badge: String?
    let loading: Bool
    let action: () -> Void

    public init(id: String, icon: ElchiIcon? = nil, systemImage: String? = nil, label: String, badge: String? = nil, loading: Bool = false,
                action: @escaping () -> Void) {
        self.id = id
        self.icon = icon
        self.systemImage = systemImage
        self.label = label
        self.badge = badge
        self.loading = loading
        self.action = action
    }
}

struct BarActionButton: View {
    let action: BarAction
    @Environment(\.elchi) private var c

    var body: some View {
        Button(action: action.action) {
            Group {
                if action.loading {
                    ProgressView().tint(c.text)
                } else if let icon = action.icon {
                    icon.image(size: 19)
                } else if let name = action.systemImage {
                    Image(systemName: name).font(.system(size: 17, weight: .medium))
                }
            }
            .foregroundStyle(c.text)
            .frame(width: 44, height: 44)
            .background(c.card, in: Circle())
            .overlay(alignment: .topTrailing) {
                if let badge = action.badge {
                    Text(badge).font(ElchiFont.poppins(11, .bold)).foregroundStyle(.white).lineLimit(1)
                        .padding(.horizontal, 5)
                        .frame(minWidth: 20, minHeight: 20)
                        .background(Color(hex: 0xE0413A), in: Capsule())
                        .overlay { Capsule().strokeBorder(c.page, lineWidth: 2) }
                        .offset(x: 4, y: -4)
                }
            }
            .shadow(color: c.shadow, radius: 12, y: 6)
        }
        .buttonStyle(PressFade())
        .disabled(action.loading)
        .accessibilityLabel(action.label)
        .accessibilityValue(action.badge ?? "")
        .accessibilityIdentifier("elchi.bar.\(action.id)")
    }
}
