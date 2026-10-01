import SwiftUI

/// Remembers that this phone has seen the splash and onboarding; they are shown once, not on every sign-out.
enum FirstRun {
    private static let key = "elchi.entry.seen"
    static var seen: Bool { UserDefaults.standard.bool(forKey: key) }
    static func markSeen() { UserDefaults.standard.set(true, forKey: key) }
}

private enum EntryStep: Hashable { case onboarding, role, phone, otp }

/// Stage 01, signed out: splash -> onboarding -> role -> phone -> OTP. A returning phone starts at the role screen.
/// There is no "done" callback: a successful OTP saves the session and the root switches to the role's home.
struct EntryFlow: View {
    let container: AppContainer
    @State private var path: [EntryStep] = []
    @State private var signIn: SignInModel
    @State private var introDone = FirstRun.seen

    /// `relogin` ("Sessiya tugadi" -> "Qayta kirish") opens straight on the phone step with the number filled in.
    init(container: AppContainer, relogin: ReloginPrefill? = nil) {
        self.container = container
        let signIn = SignInModel(auth: container.auth, sessions: container.sessions)
        if let relogin {
            signIn.start(relogin.role)
            signIn.setDigits(UzPhone.localDigits(fromE164: relogin.phone))
            _path = State(initialValue: [.phone])
            _introDone = State(initialValue: true)
        }
        _signIn = State(initialValue: signIn)
    }

    var body: some View {
        NavigationStack(path: $path) {
            Group {
                if introDone {
                    RoleView(onBack: nil) { role in
                        signIn.start(role)
                        path.append(.phone)
                    }
                } else {
                    SplashView { path.append(.onboarding) }
                }
            }
            .navigationDestination(for: EntryStep.self) { step in
                switch step {
                case .onboarding:
                    OnboardingView {
                        FirstRun.markSeen()
                        introDone = true
                        path = []
                    }
                case .role:
                    RoleView(onBack: { path.removeLast() }) { role in
                        signIn.start(role)
                        path.append(.phone)
                    }
                case .phone:
                    PhoneView(model: signIn, onBack: { path.removeLast() }) { path.append(.otp) }
                case .otp:
                    OtpView(model: signIn) { path.removeLast() }
                }
            }
        }
    }
}

/// Screen skeleton shared by the entry flow: top bar, scrolling body, footer pinned above the keyboard.
private struct EntryScaffold<Top: View, Body: View, Footer: View>: View {
    @ViewBuilder let top: Top
    @ViewBuilder let content: Body
    @ViewBuilder let footer: Footer
    @Environment(\.elchi) private var c

    var body: some View {
        VStack(spacing: 0) {
            top
            ScrollView {
                VStack(alignment: .leading, spacing: 16) { content }
                    .padding(.horizontal, 16).padding(.vertical, 8)
            }
            .scrollDismissesKeyboard(.interactively)
            VStack(spacing: 8) { footer }
                .padding(.horizontal, 16).padding(.vertical, 12)
        }
        .background(c.page.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
    }
}

// MARK: - 01 Splash

/// Always navy, whatever the theme (the prototype's splash). Says only what is true today: parcels between cities
/// (passenger service is off, K7/Q5) - no counts, no promises.
private struct SplashView: View {
    let onStart: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ElchiLogo(height: 47)
            Text(strings.t("entry.tagline")).font(ElchiFont.poppins(17)).foregroundStyle(Color(hex: 0xB8C6DE)).padding(.top, 18)
            // Route motif: origin ring - road - destination pin (decorative).
            HStack(spacing: 10) {
                Circle().strokeBorder(c.brand, lineWidth: 3).frame(width: 16, height: 16)
                Rectangle().fill(Color(hex: 0x3C5A8C)).frame(height: 2)
                ElchiIcon.pin.image(size: 20).foregroundStyle(c.brand)
            }
            .padding(.top, 44)
            .accessibilityHidden(true)
            Spacer()
            ElchiButton(strings.t("onboarding.start"), action: onStart)
            Text(strings.t("entry.footer")).font(ElchiFont.caption).foregroundStyle(Color(hex: 0x8FA2C4))
                .frame(maxWidth: .infinity).padding(.top, 20)
        }
        .padding(.horizontal, 28).padding(.top, 100).padding(.bottom, 20)
        .background(c.navy.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
        .preferredColorScheme(.dark) // light status bar over navy, whatever the theme
    }
}

// MARK: - 02 Onboarding

private struct OnboardingView: View {
    let onDone: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var step = 0

    private let steps: [(ElchiIcon, Tone, String, String)] = [
        (.pin, .blue, "onboarding.step1Title", "onboarding.step1Text"),
        (.tag, .ok, "onboarding.step2Title", "onboarding.step2Text"),
        // Q139/Q144: the old "confirm and rate" step is gone - an operator records delivery.
        (.checkC, .warn, "onboarding.step3OperatorTitle", "onboarding.step3OperatorText"),
    ]

    var body: some View {
        let current = steps[step]
        let colors = c.tone(current.1)
        let last = step == steps.count - 1
        EntryScaffold {
            HStack { ElchiLogo(height: 30); Spacer() }.padding(.leading, 20).padding(.top, 14)
        } content: {
            VStack(spacing: 20) {
                current.0.image(size: 60).foregroundStyle(colors.fg)
                    .frame(width: 128, height: 128)
                    .background(colors.bg, in: RoundedRectangle(cornerRadius: 36))
                PageDots(count: steps.count, current: step)
                Text(strings.t(current.2)).font(ElchiFont.poppins(26, .medium)).foregroundStyle(c.text)
                Text(strings.t(current.3)).font(ElchiFont.body).foregroundStyle(c.muted).frame(maxWidth: 300)
            }
            .multilineTextAlignment(.center)
            .frame(maxWidth: .infinity)
            .padding(.top, 20)
        } footer: {
            ElchiButton(strings.t(last ? "onboarding.start" : "onboarding.next")) {
                if last { onDone() } else { withAnimation { step += 1 } }
            }
            if !last { ElchiButton(strings.t("onboarding.skip"), variant: .ghost, size: .medium, action: onDone) }
        }
    }
}

// MARK: - 03 Role

/// The role is permanent for a phone number (the server refuses the other role: ROLE_MISMATCH), so the subtitle says
/// so instead of the old "you can change it later". The language choice lives here (design note).
private struct RoleView: View {
    let onBack: (() -> Void)?
    let onRole: (MobileRole) -> Void
    @Environment(LocaleStore.self) private var strings

    var body: some View {
        EntryScaffold {
            TopBar(backLabel: strings.t("common.back"), logo: true, onBack: onBack)
        } content: {
            Heading(strings.t("onboarding.roleTitle"), subtitle: strings.t("onboarding.roleSubtitlePermanent"))
            VStack(spacing: 12) {
                ChoiceCard(icon: .pkg, title: strings.t("onboarding.roleClient"), description: strings.t("onboarding.roleClientHint")) { onRole(.client) }
                ChoiceCard(icon: .truck, title: strings.t("onboarding.roleDriver"), description: strings.t("onboarding.roleDriverHint")) { onRole(.driver) }
            }
            Segmented(AppLocale.allCases.map { ($0, $0.label) }, selected: strings.locale) { strings.set($0) }
        } footer: {
            Text(strings.t("entry.footer")).font(ElchiFont.caption).foregroundStyle(Color.secondary)
        }
    }
}

// MARK: - 04 Phone

private struct PhoneView: View {
    @Bindable var model: SignInModel
    let onBack: () -> Void
    let onSent: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @FocusState private var focused: Bool
    @State private var phoneText = ""

    var body: some View {
        EntryScaffold {
            TopBar(backLabel: strings.t("common.back"), onBack: onBack)
        } content: {
            HStack {
                Chip(strings.t(model.role == .client ? "auth.asClient" : "auth.asDriver"), selected: true,
                     icon: model.role == .client ? .pkg : .truck, action: onBack)
                Spacer()
            }
            Heading(strings.t("auth.phoneTitle"), subtitle: strings.t("auth.phoneSubtitle"))
            // One field with a fixed prefix; the digits are formatted as they are typed (design note).
            HStack(spacing: 10) {
                Text("+998").font(ElchiFont.poppins(17, .semibold)).foregroundStyle(c.text)
                Rectangle().fill(c.outline).frame(width: 1, height: 22)
                TextField("", text: $phoneText, prompt: Text("90 123 45 67").foregroundStyle(c.placeholder))
                    .onChange(of: phoneText) { _, typed in
                        model.setDigits(typed)
                        let formatted = formatLocal(model.digits)
                        if phoneText != formatted { phoneText = formatted }
                    }
                    .font(.system(size: 17, design: .monospaced))
                    .foregroundStyle(c.text)
                    .keyboardType(.phonePad)
                    .textContentType(.telephoneNumber)
                    .focused($focused)
                    .tint(c.brand)
            }
            .padding(.horizontal, 16)
            .frame(height: 56)
            .background(c.field, in: RoundedRectangle(cornerRadius: 16))
            .overlay { if model.error != nil { RoundedRectangle(cornerRadius: 16).strokeBorder(c.tone(.err).fg, lineWidth: 1.5) } }
            if let error = model.error {
                Text(strings.errorText(error)).font(ElchiFont.caption).foregroundStyle(c.tone(.err).fg)
            }
        } footer: {
            ElchiButton(strings.t("auth.getCode"), icon: .send, loading: model.sending) {
                Task { if await model.requestCode() { onSent() } }
            }
            .disabled(!model.phoneValid)
        }
        .onAppear {
            phoneText = formatLocal(model.digits)
            focused = true
        }
    }

    /// `901234567` shown as `90 123 45 67`.
    private func formatLocal(_ digits: String) -> String {
        var out = ""
        for (i, ch) in digits.enumerated() {
            if [2, 5, 7].contains(i) { out.append(" ") }
            out.append(ch)
        }
        return out
    }
}

// MARK: - 05 OTP

private struct OtpView: View {
    @Bindable var model: SignInModel
    let onBack: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @FocusState private var focused: Bool
    @State private var codeText = ""

    var body: some View {
        EntryScaffold {
            VStack(spacing: 0) {
                TopBar(backLabel: strings.t("common.back"), onBack: onBack)
                if let error = model.error {
                    Banner(strings.errorText(error), tone: .err)
                } else if model.codeSent {
                    Banner(strings.t("auth.codeSent"), tone: .ok)
                }
            }
        } content: {
            Heading(strings.t("auth.otpTitle"), subtitle: "\(strings.t("auth.otpSentTo")): \(formatPhone(model.phone))", centered: true)
            Text(strings.t("auth.otpLabel", ("length", model.otpLength))).font(ElchiFont.label).foregroundStyle(c.text)
                .frame(maxWidth: .infinity)
            // The digits go into one hidden field (SMS autofill, paste, the number pad); the circles only draw it.
            ZStack {
                // SwiftUI's TextField does not follow a binding that rewrites what was typed, so the field keeps its own
                // text and is reset to the model's cleaned value after every edit.
                TextField("", text: $codeText)
                    .onChange(of: codeText) { _, typed in
                        model.setCode(typed)
                        if codeText != model.code { codeText = model.code }
                    }
                    .keyboardType(.numberPad)
                    .textContentType(.oneTimeCode)
                    .focused($focused)
                    .foregroundStyle(.clear)
                    .tint(.clear)
                    .frame(width: 1, height: 1)
                    .opacity(0.02)
                    .accessibilityLabel(strings.t("auth.otpLabel", ("length", model.otpLength)))
                OtpCells(code: model.code, length: model.otpLength, error: model.codeRejected)
                    .contentShape(Rectangle())
                    .onTapGesture { focused = true }
            }
            if model.resendIn > 0 {
                Text(strings.t("auth.resendIn", ("seconds", String(format: "%02d", model.resendIn))))
                    .font(.system(size: 14, design: .monospaced)).foregroundStyle(c.muted).frame(maxWidth: .infinity)
            } else {
                ElchiButton(strings.t("auth.resendCode"), variant: .ghost, size: .medium, icon: .refresh, loading: model.sending) {
                    Task { await model.resend() }
                }
            }
            #if DEBUG
            if let dev = model.devOtp {
                Text(strings.t("auth.devCode", ("code", dev))).font(ElchiFont.caption).foregroundStyle(c.muted).frame(maxWidth: .infinity)
            }
            #endif
        } footer: {
            ElchiButton(strings.t("common.confirm"), icon: .chevR, loading: model.verifying) { Task { await model.verify() } }
                .disabled(model.code.count != model.otpLength)
        }
        .onAppear { focused = true }
    }

    private func formatPhone(_ phone: String) -> String {
        let d = Array(phone.dropFirst(4))
        guard d.count == 9 else { return phone }
        return "+998 \(String(d[0..<2])) \(String(d[2..<5])) \(String(d[5..<7])) \(String(d[7..<9]))"
    }
}
