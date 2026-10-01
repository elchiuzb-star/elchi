import Foundation
import Observation

/// The phone and OTP steps of sign-in (same behaviour as Android's SignInViewModel).
@MainActor @Observable
final class SignInModel {
    private let auth: AuthAPI
    private let sessions: SessionStorage
    let otpLength: Int

    var role: MobileRole = .client
    /// The 9 local digits after +998.
    var digits = "" { didSet { if digits != oldValue { error = nil } } }
    private(set) var code = ""
    private(set) var sending = false
    private(set) var verifying = false
    /// Seconds until "resend" is allowed; the server's own cooldown (`resend_after_seconds`) when it sent one.
    private(set) var resendIn = 0
    private(set) var error: Error?
    /// A bad code keeps the cells red until the next keystroke.
    private(set) var codeRejected = false
    /// "Kod yuborildi" banner after a successful (re)send.
    private(set) var codeSent = false
    /// Development backends return the code instead of sending an SMS; shown only in debug builds.
    private(set) var devOtp: String?
    private var countdown: Task<Void, Never>?

    init(auth: AuthAPI, sessions: SessionStorage, otpLength: Int = 4) {
        self.auth = auth
        self.sessions = sessions
        self.otpLength = otpLength
    }

    var phone: String { "+998\(digits)" }
    var phoneValid: Bool { digits.count == 9 }

    func start(_ role: MobileRole) {
        self.role = role
        error = nil
        code = ""
        codeRejected = false
    }

    func setDigits(_ input: String) { digits = String(input.filter(\.isNumber).prefix(9)) }

    /// Requests a code; returns true when the OTP step should open. A code already on its way still counts as sent.
    @discardableResult
    func requestCode() async -> Bool {
        guard phoneValid, !sending else { return false }
        sending = true
        error = nil
        defer { sending = false }
        do {
            let sent = try await auth.requestOTP(phone: phone, role: role)
            code = ""
            codeRejected = false
            codeSent = true
            devOtp = sent.devOtp
            startCountdown(sent.resendAfterSeconds ?? 60)
            return true
        } catch let apiError as APIError where apiError.code == "OTP_RESEND_TOO_SOON" {
            codeSent = true
            return true
        } catch {
            self.error = error
            return false
        }
    }

    func resend() async {
        guard resendIn == 0 else { return }
        await requestCode()
    }

    /// Typing replaces the error state; after a rejected code the next keystroke starts a new one; the last digit
    /// submits on its own (the prototype's "auto check").
    func setCode(_ input: String) {
        let typed = input.filter(\.isNumber)
        code = codeRejected && typed.count > code.count ? String(typed.suffix(1)) : String(typed.prefix(otpLength))
        if error != nil { codeSent = false }
        codeRejected = false
        error = nil
        if code.count == otpLength { Task { await verify() } }
    }

    func verify() async {
        guard code.count == otpLength, !verifying else { return }
        verifying = true
        error = nil
        defer { verifying = false }
        do {
            let tokens = try await auth.verifyOTP(phone: phone, role: role, otp: code)
            // Saving the session is the navigation: the root switches from sign-in to the role's home.
            sessions.save(Session(accessToken: tokens.accessToken, refreshToken: tokens.refreshToken, user: tokens.user))
        } catch {
            let wrongCode = (error as? APIError).map { ["OTP_INVALID", "OTP_EXPIRED", "OTP_USED", "OTP_TOO_MANY_ATTEMPTS"].contains($0.code) } ?? false
            self.error = error
            codeRejected = wrongCode
            codeSent = false
        }
    }

    private func startCountdown(_ seconds: Int) {
        countdown?.cancel()
        resendIn = seconds
        countdown = Task { [weak self] in
            while let self, self.resendIn > 0 {
                try? await Task.sleep(for: .seconds(1))
                if Task.isCancelled { return }
                self.resendIn -= 1
            }
        }
    }
}
