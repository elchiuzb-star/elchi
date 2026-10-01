package uz.elchi.app.feature.entry

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.AuthApi
import uz.elchi.app.session.MobileRole
import uz.elchi.app.session.Session
import uz.elchi.app.session.SessionStorage

/** The phone and OTP steps of sign-in. One instance per sign-in attempt (scoped to the entry graph). */
class SignInViewModel(
    private val auth: AuthApi,
    private val sessions: SessionStorage,
    val otpLength: Int,
) : ViewModel() {

    data class State(
        val role: MobileRole = MobileRole.CLIENT,
        /** The 9 local digits after +998. */
        val digits: String = "",
        val code: String = "",
        val sending: Boolean = false,
        val verifying: Boolean = false,
        /** Seconds until "resend" is allowed; the server's own cooldown (`resend_after_seconds`) when it sent one. */
        val resendIn: Int = 0,
        val error: Throwable? = null,
        /** A bad code keeps the cells red until the next keystroke. */
        val codeRejected: Boolean = false,
        /** "Kod yuborildi" banner after a successful (re)send. */
        val codeSent: Boolean = false,
        /** Development backends return the code instead of sending an SMS; shown only in debug builds. */
        val devOtp: String? = null,
    ) {
        val phone: String get() = "+998$digits"
        val phoneValid: Boolean get() = digits.length == 9
    }

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()
    private var countdown: Job? = null

    fun start(role: MobileRole) = _state.update { State(role = role, digits = it.digits) }

    fun onDigits(input: String) = _state.update { it.copy(digits = input.filter(Char::isDigit).take(9), error = null) }

    /** Requests a code; [onSent] moves to the OTP step. A code already on its way still counts as sent. */
    fun requestCode(onSent: () -> Unit) {
        val s = _state.value
        if (!s.phoneValid || s.sending) return
        _state.update { it.copy(sending = true, error = null) }
        viewModelScope.launch {
            try {
                val sent = auth.requestOtp(s.phone, s.role)
                _state.update { it.copy(sending = false, code = "", codeRejected = false, codeSent = true, devOtp = sent.devOtp) }
                startCountdown(sent.resendAfterSeconds ?: RESEND_SECONDS)
                onSent()
            } catch (e: ApiException) {
                if (e.code == "OTP_RESEND_TOO_SOON") {
                    _state.update { it.copy(sending = false, codeSent = true) }
                    onSent()
                } else {
                    _state.update { it.copy(sending = false, error = e) }
                }
            }
        }
    }

    fun resend() {
        if (_state.value.resendIn > 0) return
        requestCode(onSent = {})
    }

    /** Typing replaces the error state; the last digit submits on its own (the prototype's "auto check"). */
    fun onCode(input: String) {
        val digits = input.filter(Char::isDigit)
        val before = _state.value
        // After a rejected code the next keystroke starts a new one instead of making the person delete four digits.
        val code = if (before.codeRejected && digits.length > before.code.length) digits.takeLast(1) else digits.take(otpLength)
        _state.update { it.copy(code = code, codeRejected = false, error = null, codeSent = if (it.error != null) false else it.codeSent) }
        if (code.length == otpLength) verify()
    }

    fun verify() {
        val s = _state.value
        if (s.code.length != otpLength || s.verifying) return
        _state.update { it.copy(verifying = true, error = null) }
        viewModelScope.launch {
            try {
                val tokens = auth.verifyOtp(s.phone, s.role, s.code)
                // Saving the session is the navigation: the root switches from sign-in to the role's home.
                sessions.save(Session(tokens.accessToken, tokens.refreshToken, tokens.user))
                _state.update { it.copy(verifying = false) }
            } catch (e: ApiException) {
                val wrongCode = e.code in setOf("OTP_INVALID", "OTP_EXPIRED", "OTP_USED", "OTP_TOO_MANY_ATTEMPTS")
                _state.update { it.copy(verifying = false, error = e, codeRejected = wrongCode, codeSent = false) }
            }
        }
    }

    private fun startCountdown(seconds: Int) {
        countdown?.cancel()
        _state.update { it.copy(resendIn = seconds) }
        countdown = viewModelScope.launch {
            while (_state.value.resendIn > 0) {
                delay(1_000)
                _state.update { it.copy(resendIn = it.resendIn - 1) }
            }
        }
    }

    private companion object {
        /** Fallback when the server does not say; matches ELCHI_OTP_RESEND_COOLDOWN_SECONDS' default. */
        const val RESEND_SECONDS = 60
    }
}
