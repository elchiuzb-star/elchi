package uz.elchi.app.ui.components

import androidx.annotation.StringRes
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import uz.elchi.app.R
import uz.elchi.app.api.ApiException
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone

/** The four kinds of app-level message (the prototype's `banners` screen). */
enum class BannerTone { OK, ERR, WARN, INFO }

/**
 * What a banner says, kept unresolved until it is drawn, so a language switch while it shows re-renders it in the
 * new language and the model stays free of Android resources.
 */
sealed interface BannerText {
    data class Res(@StringRes val id: Int) : BannerText
    /**
     * A dictionary key; [fallback] when the dictionary does not have it. [params] fill its `{name}` placeholders;
     * [keyParams] fill them with another dictionary key's sentence (`{type}` = `docType.passport`).
     */
    data class Key(
        val key: String,
        val fallback: String? = null,
        val params: Map<String, String> = emptyMap(),
        val keyParams: Map<String, String> = emptyMap(),
    ) : BannerText
    /** A failed request: offline, rate limited, or the dictionary's sentence for its code ([BannerPolicy.errorKey]). */
    data class Error(val error: Throwable) : BannerText
    data class Plain(val text: String) : BannerText
}

data class AppBanner(val id: Long, val tone: BannerTone, val text: BannerText, val onTap: (() -> Unit)? = null)

/** When a banner leaves and which sentence a failure gets. Pure, so the policy is unit-tested. */
object BannerPolicy {
    const val AUTO_HIDE_MS = 4_000L

    /**
     * DESIGN10 7.2: only success leaves after 4 s. Errors, warnings and info stay until tapped (they carry a close
     * mark); a standing error also goes when the next action starts.
     */
    fun autoHideMs(tone: BannerTone): Long? = if (tone == BannerTone.OK) AUTO_HIDE_MS else null

    /** Every banner that stays shows the close mark. */
    fun closable(tone: BannerTone): Boolean = autoHideMs(tone) == null

    /**
     * The dictionary key a failure maps to before its own code: no connection and 429 read the same everywhere.
     * Null = the code's own sentence (`error.<CODE>`, see `errorText`).
     */
    fun errorKey(error: Throwable): String? {
        val api = error as? ApiException ?: return null
        return when {
            api.code == ApiException.NETWORK -> "error.offline"
            api.status == 429 || api.code == "RATE_LIMITED" -> "error.RATE_LIMITED"
            else -> null
        }
    }

    /** A server warning (`CONTACT_INFO_MASKED`) → `warning.<CODE>`. */
    fun warningKey(code: String): String = "warning.$code"
}

/**
 * The one app-level banner, plus an optional "loading" line under it. Screens report the outcome of a command here
 * instead of each keeping its own notice; [AppBannerHost] draws it over every screen, under the title bar.
 */
class BannerCenter {
    private val _banner = MutableStateFlow<AppBanner?>(null)
    val banner: StateFlow<AppBanner?> = _banner.asStateFlow()
    private val _loading = MutableStateFlow(false)
    val loading: StateFlow<Boolean> = _loading.asStateFlow()
    private var nextId = 0L

    fun show(tone: BannerTone, text: BannerText, onTap: (() -> Unit)? = null) {
        _banner.value = AppBanner(++nextId, tone, text, onTap)
    }

    fun ok(@StringRes id: Int) = show(BannerTone.OK, BannerText.Res(id))

    fun error(error: Throwable) = show(BannerTone.ERR, BannerText.Error(error))

    fun warning(code: String, message: String? = null) = show(BannerTone.WARN, BannerText.Key(BannerPolicy.warningKey(code), message))

    fun info(text: BannerText, onTap: (() -> Unit)? = null) = show(BannerTone.INFO, text, onTap)

    /** A new command starts: a standing error is no longer the latest news, and the loading line shows. */
    fun startAction() {
        _banner.update { if (it?.tone == BannerTone.ERR) null else it }
        _loading.value = true
    }

    fun endAction() {
        _loading.value = false
    }

    /** Only [id] - a newer banner shown meanwhile stays. */
    fun dismiss(id: Long) = _banner.update { if (it?.id == id) null else it }

    fun clear() {
        _banner.value = null
        _loading.value = false
    }
}

private fun BannerTone.tone(): Tone = when (this) {
    BannerTone.OK -> Tone.OK
    BannerTone.ERR -> Tone.ERR
    BannerTone.WARN -> Tone.WARN
    BannerTone.INFO -> Tone.BLUE
}

@Composable
private fun resolve(text: BannerText): String = when (text) {
    is BannerText.Res -> t(text.id)
    is BannerText.Key -> {
        val values = text.params.toList() + text.keyParams.map { (name, key) -> name to (tOrNull(key) ?: key) }
        tOrNull(text.key, *values.toTypedArray()) ?: text.fallback ?: t(R.string.error_fallback)
    }
    is BannerText.Error -> BannerPolicy.errorKey(text.error)?.let { tOrNull(it) } ?: errorText(text.error)
    is BannerText.Plain -> text.text
}

/**
 * Draws [center] over the whole app, just under the 64dp title bar every screen has: a floating card in the tone's
 * colours (tap: its action, else close; every banner that stays carries a close mark), and the loading line while a
 * command runs.
 */
@Composable
fun AppBannerHost(center: BannerCenter, modifier: Modifier = Modifier) {
    val banner by center.banner.collectAsStateWithLifecycle()
    val loading by center.loading.collectAsStateWithLifecycle()
    val current = banner
    LaunchedEffect(current?.id) {
        val shown = current ?: return@LaunchedEffect
        val hide = BannerPolicy.autoHideMs(shown.tone) ?: return@LaunchedEffect
        delay(hide)
        center.dismiss(shown.id)
    }
    Column(
        modifier.fillMaxWidth().statusBarsPadding().padding(top = 64.dp, start = 16.dp, end = 16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        AnimatedVisibility(current != null, enter = fadeIn() + slideInVertically(), exit = fadeOut() + slideOutVertically()) {
            if (current != null) BannerCard(current, onClose = { center.dismiss(current.id) })
        }
        AnimatedVisibility(loading, enter = fadeIn(), exit = fadeOut()) { LoadingStrip() }
    }
}

@Composable
private fun BannerCard(banner: AppBanner, onClose: () -> Unit) {
    val c = Elchi.colors
    val colors = c.tone(banner.tone.tone())
    val shape = RoundedCornerShape(16.dp)
    val icon = when (banner.tone) {
        BannerTone.OK -> ElchiIcon.CHECK_C
        BannerTone.ERR, BannerTone.WARN -> ElchiIcon.ALERT
        BannerTone.INFO -> ElchiIcon.INFO
    }
    val text = resolve(banner.text)
    val closeLabel = t(R.string.common_close)
    Row(
        Modifier
            .fillMaxWidth()
            .shadow(10.dp, shape, ambientColor = c.shadow, spotColor = c.shadow)
            .clip(shape)
            .background(c.card)
            .background(colors.bg)
            .clickable(role = Role.Button) {
                val tap = banner.onTap
                onClose()
                tap?.invoke()
            }
            .semantics { liveRegion = if (banner.tone == BannerTone.ERR) LiveRegionMode.Assertive else LiveRegionMode.Polite }
            .padding(start = 14.dp, end = 8.dp, top = 12.dp, bottom = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        ElchiIconView(icon, colors.fg, size = 18.dp)
        Text(text, Modifier.weight(1f), style = Elchi.type.label, color = colors.noteText)
        if (BannerPolicy.closable(banner.tone)) {
            Box(Modifier.size(32.dp).clip(CircleShape), contentAlignment = Alignment.Center) {
                ElchiIconView(ElchiIcon.X, colors.fg, size = 16.dp, contentDescription = closeLabel)
            }
        } else {
            Box(Modifier.size(8.dp))
        }
    }
}

/** The prototype's `banner: ['load', …]` line. */
@Composable
private fun LoadingStrip() {
    val c = Elchi.colors
    val shape = RoundedCornerShape(16.dp)
    Row(
        Modifier
            .fillMaxWidth()
            .shadow(10.dp, shape, ambientColor = c.shadow, spotColor = c.shadow)
            .clip(shape)
            .background(c.card)
            .semantics { liveRegion = LiveRegionMode.Polite }
            .padding(horizontal = 14.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        CircularProgressIndicator(Modifier.size(16.dp), color = c.brand, strokeWidth = 2.dp)
        Text(t(R.string.common_loading), style = Elchi.type.label, color = c.muted)
    }
}
