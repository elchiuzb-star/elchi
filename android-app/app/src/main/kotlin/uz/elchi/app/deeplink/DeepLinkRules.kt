package uz.elchi.app.deeplink

import uz.elchi.app.api.ApiException
import uz.elchi.app.feature.client.InboxTarget
import uz.elchi.app.feature.client.PromoRules
import uz.elchi.app.session.MobileRole
import kotlinx.coroutines.flow.StateFlow
import java.net.URI
import java.net.URISyntaxException

/** Where a link opened from outside the app (another app, the browser, a push tap) leads. */
sealed interface DeepLinkTarget {
    /** `/r/<code>`: a referral code, already normalised (8 characters, upper case). */
    data class Referral(val code: String) : DeepLinkTarget
    data class Booking(val id: String) : DeepLinkTarget
    data class BookingChat(val id: String) : DeepLinkTarget
    data class Listing(val id: String) : DeepLinkTarget
    data class Proposal(val id: String) : DeepLinkTarget
    data class SupportThread(val id: String) : DeepLinkTarget

    /** `elchi://trips/{id}`: the driver's trip (the GPS notification's tap, a trip push). */
    data class Trip(val id: String) : DeepLinkTarget

    /** `elchi://wallet`: the driver's commission balance (a top-up push). */
    data object Wallet : DeepLinkTarget

    /** `elchi://support-threads`: the operator conversations list (a push about a reply names no thread). */
    data object SupportThreads : DeepLinkTarget

    /**
     * `elchi://notifications[?event=<type>[&ref=<public id>]]`: the inbox. With [event] (a push tap whose payload
     * names no screen), the newest inbox item of that event - and mentioning [ref], when given - is opened instead
     * when there is one ([uz.elchi.app.feature.client.InboxRules.pushMatch]).
     */
    data class Inbox(val event: String? = null, val ref: String? = null) : DeepLinkTarget

    /** Nothing in this app opens it: the banner `link.unsupported`. */
    data object Unsupported : DeepLinkTarget
}

/**
 * Pure parsing of the links the manifest claims:
 * - `elchi://bookings/{id}`, `elchi://bookings/{id}/messages`, `elchi://listings/{id}`, `elchi://proposals/{id}`,
 *   `elchi://support-threads[/{id}]`, `elchi://notifications[?event=&ref=]`, `elchi://r/{code}` - the in-app paths (the inbox's
 *   links and push taps, [uz.elchi.app.push.PushRules.link]);
 * - `https://<link host>/r/{code}` - the referral App Link (Q107). Only `/r/` is claimed on the web hosts: `/t/` and
 *   `/e/` stay in the browser until their public pages exist in the app (Stage 10), so they are Unsupported here.
 */
object DeepLinkRules {
    const val SCHEME = "elchi"
    private val ID = Regex("^[A-Za-z0-9_-]{1,64}$")
    private val EVENT = Regex("^[a-z0-9_.]{1,80}$")

    /** [raw] = the intent's data string; [webHosts] = the hosts from the build (`BuildConfig.LINK_HOSTS`). */
    fun parse(raw: String?, webHosts: Collection<String>): DeepLinkTarget {
        val uri = try {
            URI(raw?.trim()?.takeIf { it.isNotEmpty() } ?: return DeepLinkTarget.Unsupported)
        } catch (_: URISyntaxException) {
            return DeepLinkTarget.Unsupported
        }
        val scheme = uri.scheme?.lowercase() ?: return DeepLinkTarget.Unsupported
        val path = segments(uri.rawPath)
        return when (scheme) {
            // `elchi://bookings/1` puts the first word in the host; `elchi:/bookings/1` and `elchi:///bookings/1` do not.
            SCHEME -> route(listOfNotNull((uri.host ?: uri.rawAuthority)?.lowercase()?.takeIf { it.isNotEmpty() }) + path, inApp = true, query(uri.rawQuery))
            "https" -> {
                val host = uri.host?.lowercase() ?: return DeepLinkTarget.Unsupported
                if (webHosts.none { it.equals(host, ignoreCase = true) }) DeepLinkTarget.Unsupported else route(path, inApp = false)
            }
            else -> DeepLinkTarget.Unsupported
        }
    }

    /** `"www.elchigo.uz,elchigo.uz"` -> both, trimmed; the build keeps them in one comma-separated field. */
    fun hosts(field: String): List<String> = field.split(',').map { it.trim().lowercase() }.filter { it.isNotEmpty() }

    private fun route(parts: List<String>, inApp: Boolean, query: Map<String, String> = emptyMap()): DeepLinkTarget {
        if (parts.firstOrNull() == "r" && parts.size == 2) {
            return PromoRules.normalizeCode(parts[1])?.let { DeepLinkTarget.Referral(it) } ?: DeepLinkTarget.Unsupported
        }
        if (!inApp) return DeepLinkTarget.Unsupported
        if (parts == listOf("notifications")) return inbox(query)
        if (parts == listOf("support-threads")) return DeepLinkTarget.SupportThreads
        if (parts == listOf("wallet")) return DeepLinkTarget.Wallet
        val id = parts.getOrNull(1)?.takeIf { ID.matches(it) } ?: return DeepLinkTarget.Unsupported
        return when {
            parts.size == 2 && parts[0] == "bookings" -> DeepLinkTarget.Booking(id)
            parts.size == 3 && parts[0] == "bookings" && parts[2] == "messages" -> DeepLinkTarget.BookingChat(id)
            parts.size == 2 && parts[0] == "listings" -> DeepLinkTarget.Listing(id)
            parts.size == 2 && parts[0] == "proposals" -> DeepLinkTarget.Proposal(id)
            parts.size == 2 && parts[0] == "support-threads" -> DeepLinkTarget.SupportThread(id)
            parts.size == 2 && parts[0] == "trips" -> DeepLinkTarget.Trip(id)
            else -> DeepLinkTarget.Unsupported
        }
    }

    /** A hint of an unexpected shape is dropped (the plain inbox opens), never passed on. */
    private fun inbox(query: Map<String, String>): DeepLinkTarget {
        val event = query["event"]?.takeIf { EVENT.matches(it) } ?: return DeepLinkTarget.Inbox()
        return DeepLinkTarget.Inbox(event, query["ref"]?.takeIf { ID.matches(it) })
    }

    private fun query(raw: String?): Map<String, String> = raw.orEmpty().split('&').mapNotNull { pair ->
        val name = pair.substringBefore('=', missingDelimiterValue = "")
        if (name.isEmpty()) return@mapNotNull null
        name to runCatching { java.net.URLDecoder.decode(pair.substringAfter('='), "UTF-8") }.getOrDefault("")
    }.toMap()

    /** Path words, decoded, without empty ones (a trailing slash is fine). */
    private fun segments(rawPath: String?): List<String> =
        rawPath.orEmpty().split('/').filter { it.isNotEmpty() }.map { runCatching { java.net.URLDecoder.decode(it, "UTF-8") }.getOrDefault(it) }

    /**
     * What the signed-in role can open. A client has every in-app screen the inbox has except the driver's trip and
     * wallet; a driver (Stage 09) its bookings and their chat, its offers, trips, wallet, the operator conversations
     * and the inbox - not a client's listing. A referral is for both roles.
     */
    fun forRole(target: DeepLinkTarget, role: MobileRole?): DeepLinkTarget = when (role) {
        MobileRole.CLIENT -> when (target) {
            is DeepLinkTarget.Trip, DeepLinkTarget.Wallet -> DeepLinkTarget.Unsupported
            else -> target
        }
        MobileRole.DRIVER -> when (target) {
            is DeepLinkTarget.Referral, is DeepLinkTarget.SupportThread, DeepLinkTarget.SupportThreads, is DeepLinkTarget.Inbox,
            is DeepLinkTarget.Booking, is DeepLinkTarget.BookingChat, is DeepLinkTarget.Proposal, is DeepLinkTarget.Trip, DeepLinkTarget.Wallet -> target
            else -> DeepLinkTarget.Unsupported
        }
        null -> DeepLinkTarget.Unsupported
    }

    /** The client's screens are the inbox's: the same target, the same navigation. The two lists are not items. */
    fun inboxTarget(target: DeepLinkTarget): InboxTarget? = when (target) {
        is DeepLinkTarget.Booking -> InboxTarget.Booking(target.id, chat = false)
        is DeepLinkTarget.BookingChat -> InboxTarget.Booking(target.id, chat = true)
        is DeepLinkTarget.Listing -> InboxTarget.Listing(target.id)
        // A link carries no listing id: the inbox's fallback, the orders list.
        is DeepLinkTarget.Proposal -> InboxTarget.Proposal(target.id, listingId = null)
        is DeepLinkTarget.SupportThread -> InboxTarget.SupportThread(target.id)
        is DeepLinkTarget.Trip -> InboxTarget.Trip(target.id)
        DeepLinkTarget.Wallet -> InboxTarget.Wallet
        is DeepLinkTarget.Referral, DeepLinkTarget.SupportThreads, is DeepLinkTarget.Inbox, DeepLinkTarget.Unsupported -> null
    }
}

/** The kept referral code as the screens that use it see it ([ReferralStore] on the phone, a fake in tests). */
interface PendingReferral {
    val pending: StateFlow<String?>
    fun forget()
}

/**
 * The referral code from a link, kept until it is used (web `mobile-app/src/app/promo.ts` `rememberCode` /
 * `pendingCode` / `forgetCode`). The first code wins: the server keeps the first attribution anyway (Q106/Q117).
 */
object ReferralRules {
    /** The code to keep: the one already stored, else the new one. */
    fun keep(stored: String?, incoming: String): String = stored ?: incoming

    /** Refusals about the person, not the code: whatever code is pending can never be applied any more. */
    private val PERSON_FINAL = setOf(
        "REFERRAL_ALREADY_ATTRIBUTED",
        "REFERRAL_WINDOW_CLOSED",
        "REFERRAL_NOT_ELIGIBLE",
        "REFERRAL_SELF_REFERRAL",
    )

    /** Refusals about the code that was sent. */
    private val CODE_FINAL = setOf("REFERRAL_CODE_INVALID", "VALIDATION_ERROR")

    /**
     * After an attribution attempt with [sent]: should the pending code be forgotten?
     * - success (error == null): yes - the attribution is made, and it is never replaced;
     * - the person can no longer be attributed (already attributed, window closed, not eligible, self): yes;
     * - that code is invalid: yes when it is the pending one (a mistyped other code leaves the link's code alone);
     * - the programme is off (`FEATURE_DISABLED`), rate limited, offline, a 5xx or anything else: no - try later.
     */
    fun forgetAfter(error: Throwable?, sent: String, pending: String?): Boolean {
        if (pending == null) return false
        if (error == null) return true
        val code = (error as? ApiException)?.code ?: return false
        return code in PERSON_FINAL || (code in CODE_FINAL && sent == pending)
    }
}
