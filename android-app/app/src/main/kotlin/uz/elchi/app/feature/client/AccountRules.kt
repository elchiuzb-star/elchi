package uz.elchi.app.feature.client

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.longOrNull
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.BookingClientDTO
import uz.elchi.app.api.generated.ListingDTO
import uz.elchi.app.api.generated.NotificationDTO
import uz.elchi.app.api.generated.PromoBucketDTO
import uz.elchi.app.api.generated.PromoInstrument
import uz.elchi.app.api.generated.ProposalThreadDTO
import uz.elchi.app.api.generated.ReferralCodeDTO
import uz.elchi.app.api.generated.ReportStatus
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.api.generated.SupportTicketStatus
import uz.elchi.app.ui.theme.Tone
import java.time.Instant
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale

/** Where an inbox item leads (`mobile-app/src/app/inbox.ts` `parseInboxLink`). */
sealed interface InboxTarget {
    data class Booking(val id: String, val chat: Boolean) : InboxTarget
    data class Listing(val id: String) : InboxTarget

    /** A negotiation thread; [listingId] from the item's params when the server put it there. */
    data class Proposal(val id: String, val listingId: String?) : InboxTarget
    data class Trip(val id: String) : InboxTarget
    data class SupportThread(val id: String) : InboxTarget

    /** `/wallet`: a top-up decided, the balance moved (driver only). */
    data object Wallet : InboxTarget
}

/** How an item's time reads: today "10:24", yesterday "Kecha, 08:12", older "12 sen". */
sealed interface InboxTime {
    data class Today(val time: String) : InboxTime
    data class Yesterday(val time: String) : InboxTime
    data class Day(val date: String) : InboxTime
}

/**
 * Stage 05 inbox (N4). The pilot has no push provider (Q82), so this list is the delivery channel. The server
 * sends keys and params, never text: the words are this app's, in the reader's language.
 */
object InboxRules {
    private val PATTERNS: List<Pair<Regex, (MatchResult, JsonElement?) -> InboxTarget>> = listOf(
        Regex("^/bookings/([^/?#]+)(/messages)?/?$") to { m, _ -> InboxTarget.Booking(m.groupValues[1], m.groupValues[2].isNotEmpty()) },
        Regex("^/listings/([^/?#]+)/?$") to { m, _ -> InboxTarget.Listing(m.groupValues[1]) },
        // A proposal's own chat is never opened (Q100): the negotiation is the listing's offers screen.
        Regex("^/proposals/([^/?#]+)(/messages)?/?$") to { m, params -> InboxTarget.Proposal(m.groupValues[1], param(params, "listing_id")) },
        Regex("^/trips/([^/?#]+)/?$") to { m, _ -> InboxTarget.Trip(m.groupValues[1]) },
        Regex("^/support-threads/([^/?#]+)/?$") to { m, _ -> InboxTarget.SupportThread(m.groupValues[1]) },
        Regex("^/wallet/?$") to { _, _ -> InboxTarget.Wallet },
    )

    /** Where [link] leads, or null when this app has no screen for it (the tap then only marks the item read). */
    fun parseLink(link: String?, params: JsonElement? = null): InboxTarget? {
        val path = link?.trim()?.takeIf { it.isNotEmpty() }
            ?.replace(Regex("^https?://[^/]+"), "")
            ?.replace(Regex("^/api/v2"), "")
            ?: return null
        for ((pattern, build) in PATTERNS) {
            val match = pattern.find(path) ?: continue
            return build(match, params)
        }
        return null
    }

    /** The server's key first, then the event's generic key, then "Yangi bildirishnoma" - never the raw key. */
    fun titleKeys(item: NotificationDTO): List<String> = listOf(item.titleKey, "notification.${item.type}.title", "notification.fallback.title")

    /** Same order for the body; no body at all is fine (most events have only a title). */
    fun bodyKeys(item: NotificationDTO): List<String> = listOf(item.bodyKey, "notification.${item.type}.body")

    /** The first key [lookup] knows, already filled. */
    fun firstKnown(keys: List<String>, lookup: (String) -> String?): String? = keys.firstNotNullOfOrNull(lookup)

    /** The item's params as `{name}` values: plain values only (ids, counts); nested objects are not text. */
    fun params(element: JsonElement?): Array<Pair<String, Any>> =
        (element as? JsonObject)?.mapNotNull { (key, value) -> (value as? JsonPrimitive)?.takeIf { it !is JsonNull }?.contentOrNull?.let { key to it } }?.toTypedArray()
            ?: emptyArray()

    /**
     * A push tap that names no screen ([uz.elchi.app.push.PushRules.resolveLink]): the newest item (the server's
     * pages are newest first) of [event] whose params mention [ref] (any when null). Null -> the caller's fallback.
     */
    fun pushMatch(items: List<NotificationDTO>, event: String, ref: String?): NotificationDTO? =
        items.firstOrNull { item -> item.type == event && (ref == null || params(item.params).any { (_, value) -> value == ref }) }

    fun unreadCount(items: List<NotificationDTO>): Int = items.count { !it.isRead }

    /** After a tap: the row reads as read at once; the server call may fail without undoing it. */
    fun markRead(items: List<NotificationDTO>, id: String): List<NotificationDTO> = items.map { if (it.id == id && !it.isRead) it.copy(isRead = true) else it }

    /** Newer pages after older ones, never twice (a poll and a page can overlap). */
    fun merge(existing: List<NotificationDTO>, page: List<NotificationDTO>): List<NotificationDTO> {
        val seen = existing.map { it.id }.toMutableSet()
        return existing + page.filter { seen.add(it.id) }
    }

    fun time(createdAt: String?, now: Instant, languageTag: String): InboxTime? {
        val then = OrderRules.tashkent(createdAt) ?: return null
        val today = LocalDateTime.ofInstant(now, ParcelRules.TASHKENT).toLocalDate()
        val hm = then.format(HM)
        return when (then.toLocalDate()) {
            today -> InboxTime.Today(hm)
            today.minusDays(1) -> InboxTime.Yesterday(hm)
            else -> {
                val pattern = if (then.year == today.year) "d MMM" else "d MMM yyyy"
                InboxTime.Day(then.format(DateTimeFormatter.ofPattern(pattern, Locale.forLanguageTag(languageTag))))
            }
        }
    }

    private fun param(params: JsonElement?, key: String): String? = ((params as? JsonObject)?.get(key) as? JsonPrimitive)?.contentOrNull?.takeIf { it.isNotBlank() }

    private val HM: DateTimeFormatter = DateTimeFormatter.ofPattern("HH:mm")
}

/** The profile's numbers. Null parts are unknown (a failed read shows "—", never a made-up zero). */
data class ProfileStats(
    val total: Int,
    val active: Int,
    val offers: Int?,
    val completed: Int,
    /** Dictionary key of the newest booking's or listing's status. */
    val latestKey: String?,
    /** How that status is tinted (design `lastC`): blue while it is still going, green once completed, else plain. */
    val latestTone: Tone? = null,
)

object ProfileRules {
    /**
     * Derived from v2 only (never v1 orders), from the first page of each list:
     * - Jami: my parcel listings.
     * - Faol: open listings (published / paused) + bookings that are not finished.
     * - Taklif: offers waiting for my answer on my open listings ([threads] by listing id; null when not read).
     * - Yakunlangan: completed bookings.
     * - So'nggi: the status of whichever booking or listing was created last.
     */
    fun stats(listings: List<ListingDTO>, bookings: List<BookingClientDTO>, threads: Map<String, List<ProposalThreadDTO>>?, now: Instant): ProfileStats {
        val parcel = listings.filter { it.serviceType == ServiceType.PARCEL }
        val openListings = parcel.count { OrderRules.isLive(it.status) }
        val liveBookings = bookings.count { !BookingRules.isTerminal(it.serviceStatus) }
        val offers = threads?.let { byListing ->
            parcel.filter { OrderRules.isLive(it.status) }.sumOf { listing -> byListing[listing.id].orEmpty().count { OrderRules.negotiationActions(it, now).canAccept } }
        }
        val newestBooking = bookings.maxByOrNull { OrderRules.parseInstant(it.createdAt) ?: Instant.MIN }
        val newestListing = parcel.maxByOrNull { OrderRules.parseInstant(it.createdAt) ?: Instant.MIN }
        val bookingAt = newestBooking?.let { OrderRules.parseInstant(it.createdAt) }
        val listingAt = newestListing?.let { OrderRules.parseInstant(it.createdAt) }
        val bookingIsLatest = newestBooking != null && (listingAt == null || (bookingAt != null && !bookingAt.isBefore(listingAt)))
        val latest = when {
            bookingIsLatest -> OrderRules.bookingStatusKey(newestBooking!!.serviceType, newestBooking.serviceStatus)
            newestListing != null -> OrderRules.listingStatusKey(newestListing.status)
            else -> null
        }
        val latestTone = when {
            bookingIsLatest -> when {
                newestBooking!!.serviceStatus == "completed" -> Tone.OK
                !BookingRules.isTerminal(newestBooking.serviceStatus) -> Tone.BLUE
                else -> null
            }
            newestListing != null -> if (OrderRules.isLive(newestListing.status)) Tone.BLUE else null
            else -> null
        }
        return ProfileStats(
            total = parcel.size,
            active = openListings + liveBookings,
            offers = offers,
            completed = bookings.count { it.serviceStatus == "completed" },
            latestKey = latest,
            latestTone = latestTone,
        )
    }

    /** "AK" for "Aziza Karimova"; null without a name (the avatar then shows the person icon). */
    fun initials(name: String?): String? {
        val words = name?.trim()?.split(Regex("\\s+"))?.filter { it.isNotEmpty() && it.first().isLetter() }.orEmpty()
        if (words.isEmpty()) return null
        return words.take(2).joinToString("") { it.first().uppercase() }
    }

    /** Design 05 ("Kamida 2 ta harf kiriting."): a name needs at least this many letters. */
    const val NAME_MIN_LETTERS = 2

    /** True when the typed name has fewer than [NAME_MIN_LETTERS] letters (spaces, dots and digits do not count). */
    fun nameTooShort(typed: String): Boolean = typed.count { it.isLetter() } < NAME_MIN_LETTERS

    /** What is sent as the new name, or null when there is nothing to send (blank, or unchanged). */
    fun nameToSave(typed: String, current: String?): String? = typed.trim().replace(Regex("\\s+"), " ").takeIf { it.isNotEmpty() && it != current?.trim() }
}

/**
 * One line of a bonus card: label key, amount, and the hint shown only while the amount is not zero. [usable] = the
 * "Ishlatish mumkin" line, drawn green and semibold (design 05).
 */
data class BucketRow(val labelKey: String, val minor: Long, val hintKey: String? = null, val usable: Boolean = false)

/** Bonus screen (`mobile-app/src/app/promo.ts`): Q101-Q104 - a bonus is a discount right, never money (Q16/Q103). */
object PromoRules {
    private val CODE = Regex("^[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{8}$")
    const val FEATURE_DISABLED = "FEATURE_DISABLED"
    const val PROMOTIONS_FLAG = "promotions_enabled"
    const val LINK_CONFIGURED = "configured_unverified"
    const val CODE_LENGTH = 8

    /** The client's own buckets (instrument = client bonus); a driver credit is never shown here. */
    fun clientBuckets(buckets: List<PromoBucketDTO>): List<PromoBucketDTO> = buckets.filter { it.instrument == PromoInstrument.PASSENGER_BONUS }

    /** The driver's credit (`driver_credit`, Q103): it only lowers commission - never money. */
    fun driverBuckets(buckets: List<PromoBucketDTO>): List<PromoBucketDTO> = buckets.filter { it.instrument == PromoInstrument.DRIVER_CREDIT }

    /** The five states in reading order; "expired" includes reversed amounts (both are gone for good). */
    fun bucketRows(bucket: PromoBucketDTO): List<BucketRow> = listOf(
        BucketRow("promo.bucket.available", bucket.availableMinor, usable = true),
        BucketRow("promo.bucket.reserved", bucket.reservedMinor, "promo.bucket.reservedHint"),
        BucketRow("docState.pending", bucket.underReviewMinor, "promo.bucket.underReviewHint"),
        BucketRow("promo.bucket.consumed", bucket.consumedMinor),
        BucketRow("promo.bucket.expired", bucket.expiredMinor + bucket.reversedMinor),
    )

    fun instrumentKey(instrument: PromoInstrument): String = if (instrument == PromoInstrument.DRIVER_CREDIT) "promo.instrument.driverCredit" else "promo.instrument.passengerBonus"

    fun serviceKey(service: ServiceType): String = if (service == ServiceType.PASSENGER) "promoScreen.service.passenger" else "promoScreen.service.parcel"

    /** Same normalisation as the server: trim, drop spaces and dashes, upper-case; null when it cannot be a code. */
    fun normalizeCode(raw: String?): String? = raw?.replace(Regex("[\\s-]"), "")?.uppercase(Locale.ROOT)?.takeIf { CODE.matches(it) }

    /** What the entry field keeps while typing: upper-case letters and digits, at most 8. */
    fun typedCode(raw: String): String = raw.uppercase(Locale.ROOT).filter { it.isLetterOrDigit() }.take(CODE_LENGTH)

    /** `403 FEATURE_DISABLED` for `promotions_enabled`: the programme is off, which is not an error to retry. */
    fun isProgramOff(error: Throwable?): Boolean {
        if (error !is ApiException || error.code != FEATURE_DISABLED) return false
        val flag = BookingRules.detailsString(error.details, "flag")
        return flag == null || flag == PROMOTIONS_FLAG
    }

    /** The note for a switched-off programme: it still points at the balance when there is one. */
    fun programOffKey(hasBuckets: Boolean): String = if (hasBuckets) "promoScreen.programOffWithBalance" else "promoScreen.programOff"

    /** The link is shown only when a host is configured (it may still not open: then the code is typed by hand). */
    fun shareUrl(code: ReferralCodeDTO): String? = code.shareUrl?.takeIf { code.linkStatus == LINK_CONFIGURED && it.isNotBlank() }

    /** What "Havolani ulashish" hands over: the working link when there is one, else the code. "Kodni nusxalash" copies the code only. */
    fun shareText(code: ReferralCodeDTO): String = shareUrl(code) ?: code.code

    /**
     * Why the typed friend's code cannot be sent yet, as a dictionary key; null = fine (or not finished: the button
     * stays disabled until 8 characters). [own] is the caller's own code: entering it is refused before the server.
     */
    fun entryErrorKey(entered: String, own: String?): String? = when {
        entered.length < CODE_LENGTH -> null
        normalizeCode(entered) == null -> "promoScreen.codeFormat"
        own != null && normalizeCode(entered) == normalizeCode(own) -> "client.bonus.ownCode"
        else -> null
    }

    /** The campaign badge's tone: done = ok, staff looking = warn, gone = grey, still running = info. */
    fun enrollmentTone(qualification: String?, status: String): Tone = when (qualification) {
        "qualified", "granted" -> Tone.OK
        "review" -> Tone.WARN
        else -> if (status == "released") Tone.GRAY else Tone.BLUE
    }

    /** Enrolment status line: the qualification step when known, else the enrolment state. */
    fun enrollmentStatusKey(qualification: String?, status: String): String? = when (qualification) {
        "waiting" -> "promo.qualification.waiting"
        "review" -> "promo.qualification.review"
        "qualified", "granted" -> "promo.qualification.qualified"
        else -> when (status) {
            "promised" -> "promo.enrollment.promised"
            "released" -> "promo.enrollment.released"
            else -> null
        }
    }

    /** dd.MM.yyyy in Tashkent. */
    fun date(value: String?): String? = OrderRules.tashkent(value)?.format(DateTimeFormatter.ofPattern("dd.MM.yyyy"))
}

/** Safety centre and help lists: status words and tones. */
object SafetyRules {
    /** open / under review = someone still has to look (warn); dismissed = neutral; actioned = done (ok). */
    fun reportTone(status: ReportStatus): Tone = when (status) {
        ReportStatus.OPEN, ReportStatus.UNDER_REVIEW -> Tone.WARN
        ReportStatus.ACTIONED -> Tone.OK
        else -> Tone.GRAY
    }

    fun reportStatusKey(status: ReportStatus): String = "blockReport.status.${status.value}"

    fun ticketStatusKey(status: SupportTicketStatus): String? = when (status) {
        SupportTicketStatus.OPEN -> "client.support.ticket.open"
        SupportTicketStatus.ACKNOWLEDGED -> "client.support.ticket.acknowledged"
        SupportTicketStatus.RESOLVED -> "client.support.ticket.resolved"
        else -> null
    }

    fun ticketTone(status: SupportTicketStatus): Tone = when (status) {
        SupportTicketStatus.ACKNOWLEDGED -> Tone.BLUE
        SupportTicketStatus.RESOLVED -> Tone.OK
        else -> Tone.GRAY
    }

    /** answered = an answer to read (info); assigned = someone is on it (warn); waiting / closed = grey. */
    fun threadTone(staffStatus: String): Tone = when (staffStatus) {
        "answered" -> Tone.BLUE
        "assigned" -> Tone.WARN
        else -> Tone.GRAY
    }

    /** The ticket's title in the list: its first non-empty line. */
    fun ticketTitle(message: String?): String? = message?.lineSequence()?.map { it.trim() }?.firstOrNull { it.isNotEmpty() }

    /** Help form: the server wants at least a few words; design 05 caps the text at 1000 characters. */
    const val TICKET_MIN = 5
    const val TICKET_MAX = 1000

    fun ticketReady(text: String): Boolean = text.trim().length >= TICKET_MIN

    /** "Kamida 5 ta belgi yozing" shows while something, but too little, is typed (not on an empty field). */
    fun ticketTooShort(text: String): Boolean = text.trim().length in 1 until TICKET_MIN
}

/** One line of "Hozircha o'chirib bo'lmaydi": a dictionary key and, when the line names one, its counter. */
data class DeletionBlocker(val key: String, val count: Long?)

object DeletionRules {
    private val NAMED = listOf("active_bookings", "active_orders", "open_disputes", "open_sos_tickets", "pending_no_show_reviews")
    /** Breakdowns of a named counter (`active_bookings` = as client + as driver): already said, not "something else". */
    private val PARTS = setOf("active_bookings_as_client", "active_bookings_as_driver")
    const val BLOCKED = "ACCOUNT_DELETION_BLOCKED"

    /**
     * `409 ACCOUNT_DELETION_BLOCKED` details -> lines. The five named counters say what and how many; any other
     * non-zero counter (wallet, custody, receipts, held commission...) adds one "something else is open" line, once.
     * Text values (`reason`) are not counters.
     */
    /** "Buyurtmalarga o'tish" in the refusal card: only when an open booking or order is what holds it. */
    fun leadsToOrders(blockers: List<DeletionBlocker>?): Boolean =
        blockers.orEmpty().any { it.key == "client.accountDelete.blocked.active_bookings" || it.key == "client.accountDelete.blocked.active_orders" }

    fun blockers(details: JsonElement?): List<DeletionBlocker> {
        val obj = details as? JsonObject ?: return listOf(DeletionBlocker("client.accountDelete.blocked.other", null))
        val counts = obj.mapNotNull { (key, value) -> (value as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull?.let { key to it } }.toMap()
        val lines = NAMED.mapNotNull { name -> counts[name]?.takeIf { it > 0 }?.let { DeletionBlocker("client.accountDelete.blocked.$name", it) } }
        val other = counts.any { (key, value) -> key !in NAMED && key !in PARTS && value > 0 }
        return if (other || lines.isEmpty()) lines + DeletionBlocker("client.accountDelete.blocked.other", null) else lines
    }
}
