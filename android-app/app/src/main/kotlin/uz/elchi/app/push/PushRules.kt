package uz.elchi.app.push

import uz.elchi.app.session.MobileRole

/**
 * One FCM data message (ADR-0022). The server sends exactly `PUSH_PAYLOAD_KEYS` (`event_type`, `aggregate_id`,
 * `title_key`) and never text, so everything the person reads is this app's own dictionary.
 */
data class PushMessage(val eventType: String, val aggregateId: String?, val titleKey: String?)

/** What this phone last told the server (`POST /devices/push-token`); [deviceId] null = nothing registered. */
data class PushRegistration(val token: String?, val userId: Long?, val deviceId: String?, val atMillis: Long)

/** Pure rules for push: reading a message, its words, where a tap leads, and when to (re-)register the token. */
object PushRules {
    const val INBOX_LINK = "elchi://notifications"
    const val FALLBACK_TITLE = "notification.fallback.title"
    const val CHAT_MESSAGE = "chat.message.created"
    const val SUPPORT_REPLIED = "support.thread.replied"

    /** A registration older than this is sent again (it only refreshes the server's `last_seen_at`; it is an upsert). */
    const val REFRESH_AFTER_MILLIS = 24L * 60 * 60 * 1000

    private val ID = Regex("^[A-Za-z0-9_-]{1,64}$")
    private val EVENT = Regex("^[a-z0-9_.]{1,80}$")
    private val KEY = Regex("^[A-Za-z0-9_.]{1,120}$")

    /**
     * The message, or null when it is not one of ours (no usable `event_type`). Keys outside the allowlist are
     * ignored, not trusted; an id or key of an unexpected shape is dropped rather than put into a link.
     */
    fun parse(data: Map<String, String>): PushMessage? {
        val type = data["event_type"]?.trim()?.takeIf { EVENT.matches(it) } ?: return null
        return PushMessage(
            eventType = type,
            aggregateId = data["aggregate_id"]?.trim()?.takeIf { ID.matches(it) },
            titleKey = data["title_key"]?.trim()?.takeIf { KEY.matches(it) },
        )
    }

    /** The inbox's order (`InboxRules.titleKeys`): the server's key, the event's generic key, "Yangi bildirishnoma". */
    fun titleKeys(message: PushMessage): List<String> =
        listOfNotNull(message.titleKey, "notification.${message.eventType}.title", FALLBACK_TITLE).distinct()

    /** The event's own body when the dictionary has one; otherwise the caller's generic line. */
    fun bodyKeys(message: PushMessage): List<String> = listOf("notification.${message.eventType}.body")

    /**
     * The first key [lookup] knows. A text that still has a `{placeholder}` is skipped: a push carries no params to
     * fill it, and a raw `{name}` must never reach the notification shade.
     */
    fun firstKnown(keys: List<String>, lookup: (String) -> String?): String? =
        keys.firstNotNullOfOrNull { key -> lookup(key)?.takeIf { it.isNotBlank() && !it.contains('{') } }

    /**
     * Where a tap leads (an `elchi://` link for [uz.elchi.app.deeplink.DeepLinkRules]). The payload has no link, so
     * it is derived from the event and the aggregate's public id prefix:
     * - a client: `bkg_` -> the booking, `lst_` -> the listing, `prp_` -> the proposal (the orders list);
     * - everything else -> the inbox, asked to open the newest item of this event that mentions the aggregate
     *   ([resolveLink]). That is how a chat message (aggregate = the chat thread, `cht_...`, which no screen opens by
     *   id) reaches the booking chat, and an operator reply (aggregate = the requester, `usr_...`) its conversation:
     *   the inbox row the server wrote for the same event carries the real link;
     * - a driver has only the inbox and the operator conversations in the app so far, so always the inbox way.
     */
    fun link(message: PushMessage, role: MobileRole?): String {
        val id = message.aggregateId
        if (role == MobileRole.CLIENT && id != null) {
            when (id.substringBefore('_', missingDelimiterValue = "")) {
                "bkg" -> return if (message.eventType == CHAT_MESSAGE) "elchi://bookings/$id/messages" else "elchi://bookings/$id"
                "lst" -> return "elchi://listings/$id"
                "prp" -> return "elchi://proposals/$id"
            }
        }
        return resolveLink(message)
    }

    /** `elchi://notifications?event=<type>[&ref=<id>]`; a user id is never in an item's params, so it is not a ref. */
    fun resolveLink(message: PushMessage): String {
        val ref = message.aggregateId?.takeUnless { it.startsWith("usr_") }
        return "$INBOX_LINK?event=${message.eventType}" + (ref?.let { "&ref=$it" } ?: "")
    }

    /** No inbox item matched: an operator reply still opens the conversations list; anything else, the inbox. */
    fun fallsBackToThreads(event: String?): Boolean = event == SUPPORT_REPLIED

    /** Notifications about one thing (one booking, one listing...) sit in one group; without an id, the app's own. */
    fun group(message: PushMessage): String = "elchi.${message.aggregateId ?: "app"}"

    /**
     * Whether [token] for [userId] must be sent: nothing registered yet, the token or the person changed, the saved
     * time is in the future (clock moved), or the last registration is older than [REFRESH_AFTER_MILLIS].
     */
    fun needsRegistration(saved: PushRegistration, token: String, userId: Long, nowMillis: Long): Boolean =
        saved.deviceId == null ||
            saved.token != token ||
            saved.userId != userId ||
            nowMillis < saved.atMillis ||
            nowMillis - saved.atMillis >= REFRESH_AFTER_MILLIS
}
