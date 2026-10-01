package uz.elchi.app

import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.LocalActivityResultRegistryOwner
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.elchi.app.feature.client.ClientFlow
import uz.elchi.app.feature.driver.DriverFlow
import uz.elchi.app.feature.entry.EntryFlow
import uz.elchi.app.i18n.withLocale
import uz.elchi.app.session.MobileRole
import uz.elchi.app.ui.components.AppBannerHost
import uz.elchi.app.ui.components.LocalSystemBarIcons
import uz.elchi.app.ui.components.SystemBarIconsController
import uz.elchi.app.ui.components.SystemBarIconsHost
import uz.elchi.app.ui.map.MapKitSupport
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.ElchiTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        installSplashScreen()
        // Transparent bars: every screen paints behind them and sets its own icon colour (SystemBarIcons).
        val bars = SystemBarStyle.auto(Color.TRANSPARENT, Color.TRANSPARENT)
        enableEdgeToEdge(statusBarStyle = bars, navigationBarStyle = bars)
        super.onCreate(savedInstanceState)
        val container = (application as ElchiApplication).container
        // Debug builds only: `adb shell am start ... --ez elchi.debug.breakTokens true` makes both stored tokens
        // garbage, so the next call's refresh is refused and the session-expired dialog can be seen on demand.
        if (BuildConfig.DEBUG && savedInstanceState == null && intent?.getBooleanExtra(DEBUG_BREAK_TOKENS, false) == true) {
            container.sessions.breakTokensForTesting()
        }
        // Debug builds only: `--el elchi.debug.legacyOrder <id>` opens that v1 order's detail (any id - a foreign or
        // missing one shows the not-found state, which no list row can reach).
        if (BuildConfig.DEBUG && savedInstanceState == null) {
            intent?.getLongExtra(DEBUG_LEGACY_ORDER, 0L)?.takeIf { it > 0 }?.let { container.debugLegacyOrder.value = it }
        }
        // A link that started the app (cold start). Not again after a rotation / process restore, nor when the app
        // is reopened from the recents list (Android hands back the original intent then).
        val fromHistory = ((intent?.flags ?: 0) and Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY) != 0
        if (savedInstanceState == null && !fromHistory) openLink(intent)
        MapKitSupport.initialize(this, container.locale.state.value.tag)
        setContent {
            val locale by container.locale.state.collectAsStateWithLifecycle()
            val themeMode by container.theme.state.collectAsStateWithLifecycle()
            val localized = remember(locale) { withLocale(locale) }
            // Every stringResource below reads this context, so switching the language re-renders the whole tree.
            // The localized context is not the Activity, so the Activity's result registry (photo picker, camera)
            // is handed down explicitly.
            CompositionLocalProvider(
                LocalContext provides localized,
                LocalConfiguration provides localized.resources.configuration,
                LocalActivityResultRegistryOwner provides this,
            ) {
                ElchiTheme(themeMode) {
                    val barIcons = remember { SystemBarIconsController() }
                    SystemBarIconsHost(barIcons, fallbackDark = !Elchi.colors.isDark)
                    CompositionLocalProvider(LocalSystemBarIcons provides barIcons) {
                        // The session decides the tree: signing in or out (or a refresh the server rejects) swaps it.
                        val session by container.sessions.state.collectAsStateWithLifecycle()
                        val expired by container.sessions.expired.collectAsStateWithLifecycle()
                        val current = session
                        // A banner belongs to the person who caused it: signing out (or in) starts clean.
                        LaunchedEffect(current?.user?.id) { container.banners.clear() }
                        // After the clear above: a link's banner ("Taklif kodi saqlandi", "Bu havolani...") survives it.
                        LaunchedEffect(Unit) { container.links.notices.collect { container.banners.show(it.tone, it.text) } }
                        Box(Modifier.fillMaxSize()) {
                            when {
                                current == null -> EntryFlow(container, expired)
                                current.user.mobileRole == MobileRole.CLIENT -> ClientFlow(container, current)
                                else -> DriverFlow(container, current)
                            }
                            AppBannerHost(container.banners)
                        }
                    }
                }
            }
        }
    }

    private companion object {
        const val DEBUG_BREAK_TOKENS = "elchi.debug.breakTokens"
        const val DEBUG_LEGACY_ORDER = "elchi.debug.legacyOrder"
    }

    /** Warm start: the app is already open (singleTask) and a link arrives. */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        openLink(intent)
    }

    private fun openLink(intent: Intent?) {
        if (intent?.action != Intent.ACTION_VIEW) return
        (application as ElchiApplication).container.links.open(intent.dataString)
    }

    override fun onStart() {
        super.onStart()
        MapKitSupport.onStart()
    }

    override fun onStop() {
        MapKitSupport.onStop()
        super.onStop()
    }
}
