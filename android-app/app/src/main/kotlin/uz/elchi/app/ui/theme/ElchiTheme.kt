package uz.elchi.app.ui.theme

import android.content.Context
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import uz.elchi.app.R

/**
 * Design tokens from the Claude Design prototype ("Elchi App", `t` light/dark). Brand azure #0096FF carries navy
 * #0E2350 text, never white - that is the prototype's contrast choice and it holds in sunlight.
 */
@Immutable
data class ElchiColors(
    val page: Color,
    val card: Color,
    val text: Color,
    val muted: Color,
    val placeholder: Color,
    val field: Color,
    val line: Color,
    val outline: Color,
    val soft: Color,
    val softText: Color,
    val accentText: Color,
    val shadow: Color,
    val isDark: Boolean,
) {
    val brand = Color(0xFF0096FF)
    val onBrand = Color(0xFF0E2350)
    val navy = Color(0xFF0E2350)
    val danger = Color(0xFFD64545)

    /** The prototype's pale-blue surface (#EAF5FF): the "direction ready" and "total" cards, a selected row. */
    val highlight: Color get() = if (isDark) Color(0xFF0E2A45) else Color(0xFFEAF5FF)

    /** The destination pin's navy; on dark surfaces navy disappears, so it takes the text colour. */
    val pin: Color get() = if (isDark) text else navy
}

val LightColors = ElchiColors(
    page = Color(0xFFF3F5F8), card = Color(0xFFFFFFFF), text = Color(0xFF0E1B33), muted = Color(0xFF5B6577),
    placeholder = Color(0xFF8792A2), field = Color(0xFFEEF1F5), line = Color(0xFFE1E5EB), outline = Color(0xFFCFD6DF),
    soft = Color(0xFFD9EEFF), softText = Color(0xFF0B3E73), accentText = Color(0xFF0068BF),
    shadow = Color(0x1F0E1B33), isDark = false,
)

val DarkColors = ElchiColors(
    page = Color(0xFF0F1115), card = Color(0xFF17191E), text = Color(0xFFF2F4F7), muted = Color(0xFFA3ABB8),
    placeholder = Color(0xFF7A828F), field = Color(0xFF24272E), line = Color(0xFF30343C), outline = Color(0xFF3A3F48),
    soft = Color(0xFF0E3354), softText = Color(0xFFBFE3FF), accentText = Color(0xFF4DB5FF),
    shadow = Color(0x73000000), isDark = true,
)

/** Status tones (badges, notes). Light values are the prototype's; dark ones are derived (the prototype has none). */
enum class Tone { GRAY, BLUE, WARN, OK, ERR }

@Immutable
data class ToneColors(val bg: Color, val fg: Color, val noteText: Color)

fun ElchiColors.tone(tone: Tone): ToneColors = if (!isDark) {
    when (tone) {
        Tone.GRAY -> ToneColors(Color(0xFFEEF1F5), Color(0xFF4A5568), Color(0xFF3A4556))
        Tone.BLUE -> ToneColors(Color(0xFFD9EEFF), Color(0xFF0068BF), Color(0xFF0B3E73))
        Tone.WARN -> ToneColors(Color(0xFFFDF1D6), Color(0xFF9A6400), Color(0xFF6B4600))
        Tone.OK -> ToneColors(Color(0xFFE2F5E9), Color(0xFF1E8E4E), Color(0xFF12663A))
        Tone.ERR -> ToneColors(Color(0xFFFCE6E6), Color(0xFFC93838), Color(0xFF8E2020))
    }
} else {
    when (tone) {
        Tone.GRAY -> ToneColors(Color(0xFF24272E), Color(0xFFC3CAD5), Color(0xFFC3CAD5))
        Tone.BLUE -> ToneColors(Color(0xFF0E2A45), Color(0xFF4DB5FF), Color(0xFFBFE3FF))
        Tone.WARN -> ToneColors(Color(0xFF3A2E12), Color(0xFFF2C46B), Color(0xFFF7D98F))
        Tone.OK -> ToneColors(Color(0xFF133524), Color(0xFF7FD6A2), Color(0xFFA9E5C0))
        Tone.ERR -> ToneColors(Color(0xFF3D1A1C), Color(0xFFF29B9B), Color(0xFFF7B8B8))
    }
}

val Poppins = FontFamily(
    Font(R.font.poppins_regular, FontWeight.Normal),
    Font(R.font.poppins_medium, FontWeight.Medium),
    Font(R.font.poppins_semibold, FontWeight.SemiBold),
    Font(R.font.poppins_bold, FontWeight.Bold),
)

/** Type scale used by the prototype's screens (px there = sp here). */
@Immutable
data class ElchiType(
    val display: TextStyle = TextStyle(fontFamily = Poppins, fontWeight = FontWeight.Medium, fontSize = 30.sp, lineHeight = 36.sp, letterSpacing = (-0.01).em),
    val title: TextStyle = TextStyle(fontFamily = Poppins, fontWeight = FontWeight.Medium, fontSize = 24.sp, lineHeight = 29.sp),
    val section: TextStyle = TextStyle(fontFamily = Poppins, fontWeight = FontWeight.Medium, fontSize = 16.sp, lineHeight = 22.sp),
    val body: TextStyle = TextStyle(fontFamily = Poppins, fontWeight = FontWeight.Normal, fontSize = 15.sp, lineHeight = 22.sp),
    val bodyStrong: TextStyle = TextStyle(fontFamily = Poppins, fontWeight = FontWeight.SemiBold, fontSize = 15.sp, lineHeight = 22.sp),
    val label: TextStyle = TextStyle(fontFamily = Poppins, fontWeight = FontWeight.Medium, fontSize = 13.sp, lineHeight = 18.sp),
    val secondary: TextStyle = TextStyle(fontFamily = Poppins, fontWeight = FontWeight.Normal, fontSize = 14.sp, lineHeight = 21.sp),
    val caption: TextStyle = TextStyle(fontFamily = Poppins, fontWeight = FontWeight.Normal, fontSize = 12.sp, lineHeight = 17.sp),
    val button: TextStyle = TextStyle(fontFamily = Poppins, fontWeight = FontWeight.Medium, fontSize = 17.sp, lineHeight = 22.sp),
    val buttonSmall: TextStyle = TextStyle(fontFamily = Poppins, fontWeight = FontWeight.Medium, fontSize = 14.sp, lineHeight = 20.sp),
    val badge: TextStyle = TextStyle(fontFamily = Poppins, fontWeight = FontWeight.SemiBold, fontSize = 11.sp, lineHeight = 14.sp),
)

object ElchiShape {
    val field = 16.dp
    val card = 22.dp
    val note = 16.dp
    val sheet = 32.dp
}

val LocalElchiColors = staticCompositionLocalOf { LightColors }
val LocalElchiType = staticCompositionLocalOf { ElchiType() }

/** `Elchi.colors.brand`, `Elchi.type.title` - the one way screens read tokens. */
object Elchi {
    val colors: ElchiColors @Composable get() = LocalElchiColors.current
    val type: ElchiType @Composable get() = LocalElchiType.current
}

/** The person's choice from the theme switch; SYSTEM follows the phone. */
enum class ThemeMode { SYSTEM, LIGHT, DARK }

class ThemeStore(context: Context) {
    private val prefs = context.getSharedPreferences("elchi.settings", Context.MODE_PRIVATE)
    private val _state = MutableStateFlow(ThemeMode.entries.firstOrNull { it.name == prefs.getString(KEY, null) } ?: ThemeMode.SYSTEM)
    val state: StateFlow<ThemeMode> = _state.asStateFlow()

    fun set(mode: ThemeMode) {
        prefs.edit().putString(KEY, mode.name).apply()
        _state.value = mode
    }

    private companion object {
        const val KEY = "theme"
    }
}

@Composable
fun ElchiTheme(mode: ThemeMode, content: @Composable () -> Unit) {
    val dark = when (mode) {
        ThemeMode.SYSTEM -> isSystemInDarkTheme()
        ThemeMode.LIGHT -> false
        ThemeMode.DARK -> true
    }
    val colors = if (dark) DarkColors else LightColors
    // Material components we still use (text selection, ripples) take their colours from the same tokens.
    val material = (if (dark) darkColorScheme() else lightColorScheme()).copy(
        primary = colors.brand, onPrimary = colors.onBrand, background = colors.page, surface = colors.card,
        onBackground = colors.text, onSurface = colors.text, onSurfaceVariant = colors.muted, outline = colors.outline,
        error = colors.danger,
    )
    CompositionLocalProvider(LocalElchiColors provides colors, LocalElchiType provides ElchiType()) {
        MaterialTheme(colorScheme = material, content = content)
    }
}
