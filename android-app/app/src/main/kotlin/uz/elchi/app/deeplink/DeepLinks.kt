package uz.elchi.app.deeplink

import android.content.Context
import androidx.core.content.edit
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import uz.elchi.app.ui.components.BannerText
import uz.elchi.app.ui.components.BannerTone

/** The pending referral code on this phone, across sign-in and restarts, until it is used ([ReferralRules]). */
class ReferralStore(context: Context) : PendingReferral {
    private val prefs = context.getSharedPreferences("elchi.referral", Context.MODE_PRIVATE)
    private val _pending = MutableStateFlow(prefs.getString(KEY, null))
    override val pending: StateFlow<String?> = _pending.asStateFlow()

    /** Keeps [code] unless one is already kept; returns the code that is kept (the first one wins). */
    @Synchronized
    fun remember(code: String): String {
        val kept = ReferralRules.keep(_pending.value, code)
        if (kept != _pending.value) {
            prefs.edit { putString(KEY, kept) }
            _pending.value = kept
        }
        return kept
    }

    @Synchronized
    override fun forget() {
        prefs.edit { remove(KEY) }
        _pending.value = null
    }

    private companion object {
        const val KEY = "pending_code"
    }
}

/** A banner the link handler wants shown once the app's tree is up (a cold start clears banners on sign-in). */
data class LinkNotice(val tone: BannerTone, val text: BannerText)

/**
 * Links from intents (cold start and `onNewIntent`) wait here until a signed-in flow takes them. Signed out, the
 * target stays in memory (this process only) and is opened right after sign-in; the referral code itself is also
 * saved in [ReferralStore], so it survives a restart. Unsupported links only say so.
 */
class DeepLinkCenter(private val referral: ReferralStore, private val webHosts: List<String>) {
    private val _target = MutableStateFlow<DeepLinkTarget?>(null)
    val target: StateFlow<DeepLinkTarget?> = _target.asStateFlow()
    private val _notices = Channel<LinkNotice>(Channel.BUFFERED)
    val notices: Flow<LinkNotice> = _notices.receiveAsFlow()

    fun open(raw: String?) {
        when (val parsed = DeepLinkRules.parse(raw, webHosts)) {
            DeepLinkTarget.Unsupported -> unsupported()
            is DeepLinkTarget.Referral -> {
                val kept = referral.remember(parsed.code)
                notice(BannerTone.INFO, BannerText.Key("link.referralSaved", params = mapOf("code" to kept)))
                _target.value = DeepLinkTarget.Referral(kept)
            }
            else -> _target.value = parsed
        }
    }

    /** The waiting target, handed out once (only to the flow that consumes it). */
    fun take(expected: DeepLinkTarget): Boolean = _target.compareAndSet(expected, null)

    fun unsupported() = notice(BannerTone.WARN, BannerText.Key("link.unsupported"))

    private fun notice(tone: BannerTone, text: BannerText) {
        _notices.trySend(LinkNotice(tone, text))
    }
}
