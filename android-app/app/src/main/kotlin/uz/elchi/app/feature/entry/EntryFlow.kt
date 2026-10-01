package uz.elchi.app.feature.entry

import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import kotlinx.serialization.Serializable
import uz.elchi.app.AppContainer
import uz.elchi.app.BuildConfig
import uz.elchi.app.R
import uz.elchi.app.feature.client.ParcelRules
import uz.elchi.app.i18n.t
import uz.elchi.app.session.MobileRole
import uz.elchi.app.session.SessionExpiry
import uz.elchi.app.ui.components.ElchiDialog

@Serializable private data object Splash
@Serializable private data object Onboarding
@Serializable private data object Role
@Serializable private data object Phone
@Serializable private data object Otp

/** Remembers that this phone has seen the splash and onboarding; they are shown once, not on every sign-out. */
class FirstRunStore(context: Context) {
    private val prefs = context.getSharedPreferences("elchi.settings", Context.MODE_PRIVATE)
    val seen: Boolean get() = prefs.getBoolean(KEY, false)

    fun markSeen() = prefs.edit().putBoolean(KEY, true).apply()

    private companion object {
        const val KEY = "entry.seen"
    }
}

/**
 * Stage 01, signed out: splash -> onboarding -> role -> phone -> OTP. A returning phone starts at the role screen.
 * There is no "done" callback: a successful OTP saves the session and the root switches to the role's home.
 * Stage 05: when the server ended the session ([expired]), the modal "Sessiya tugadi" comes first; its one button
 * leads to the phone step with the number already filled in. It is shown once per expiry.
 */
@Composable
fun EntryFlow(container: AppContainer, expired: SessionExpiry? = null) {
    val nav = rememberNavController()
    val locale by container.locale.state.collectAsStateWithLifecycle()
    val signIn: SignInViewModel = viewModel(factory = viewModelFactory {
        initializer { SignInViewModel(container.auth, container.sessions, BuildConfig.OTP_LENGTH) }
    })
    val finishIntro = {
        container.firstRun.markSeen()
        nav.navigate(Role) { popUpTo(0) }
    }
    NavHost(nav, startDestination = if (container.firstRun.seen) Role else Splash) {
        composable<Splash> { SplashScreen(onStart = { nav.navigate(Onboarding) }) }
        composable<Onboarding> { OnboardingScreen(onDone = finishIntro) }
        composable<Role> {
            RoleScreen(
                locale = locale,
                onLocale = container.locale::set,
                onBack = if (nav.previousBackStackEntry != null) ({ nav.popBackStack() }) else null,
                onRole = { signIn.start(it); nav.navigate(Phone) },
            )
        }
        composable<Phone> { PhoneScreen(signIn, onBack = { nav.popBackStack() }, onSent = { nav.navigate(Otp) }) }
        composable<Otp> { OtpScreen(signIn, onBack = { nav.popBackStack() }) }
    }
    if (expired != null) {
        ElchiDialog(
            title = t(R.string.client_session_expiredTitle),
            text = t(R.string.client_session_expiredText),
            confirm = t(R.string.client_session_relogin),
            onConfirm = {
                container.firstRun.markSeen()
                signIn.start(expired.role ?: MobileRole.CLIENT)
                signIn.onDigits(ParcelRules.localDigits(expired.phone))
                nav.navigate(Role) { popUpTo(0) }
                nav.navigate(Phone)
                container.sessions.dismissExpired()
            },
            onDismiss = {},
            dismissible = false,
        )
    }
}
