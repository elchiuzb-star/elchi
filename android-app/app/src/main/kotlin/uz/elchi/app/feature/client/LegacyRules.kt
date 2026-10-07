package uz.elchi.app.feature.client

import kotlinx.serialization.json.JsonElement
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.LegacyDriver
import uz.elchi.app.api.LegacyOrderDetail
import java.math.BigDecimal
import java.time.Instant
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneOffset
import java.util.Locale

/** What the client may still do with a v1 order in its status (Q4: never create, edit or publish). */
data class LegacyActions(
    /** `published` / `bidding`: the bids screen (with its "no bids yet" state). */
    val viewBids: Boolean = false,
    /** `delivered`: confirm, then rate. */
    val confirmDelivery: Boolean = false,
    /** `confirmed` and not rated in this session. */
    val rate: Boolean = false,
    /** `draft` / `published` / `bidding` / `accepted`. */
    val cancel: Boolean = false,
    /**
     * `accepted` / `picked_up` / `in_transit` / `delivered`: "Muammo haqida xabar" - a Yordam ticket about the order
     * (Q141, user decision: no dispute form any more).
     */
    val report: Boolean = false,
)

/**
 * The first (v1) marketplace, kept as an archive (Q4): the orders a client already had finish their life cycle here
 * with the actions the old app offered, and nothing else. Pure rules, shared by the screens and the tests.
 */
object LegacyRules {
    private val BIDS_OPEN = setOf("published", "bidding")
    private val CANCELLABLE = setOf("draft", "published", "bidding", "accepted")
    private val REPORTABLE = setOf("accepted", "picked_up", "in_transit", "delivered")

    /** From `accepted` on the client needs to reach the driver, and v1 has no chat: the phone shows from then on. */
    private val PHONE_VISIBLE = setOf("accepted", "picked_up", "in_transit", "delivered", "confirmed", "disputed")

    fun actions(status: String, ratedThisSession: Boolean): LegacyActions = LegacyActions(
        viewBids = status in BIDS_OPEN,
        confirmDelivery = status == "delivered",
        rate = status == "confirmed" && !ratedThisSession,
        cancel = status in CANCELLABLE,
        report = status in REPORTABLE,
    )

    /** Bids can still be looked at and chosen from. Otherwise the bids screen says they are closed. */
    fun bidsOpen(status: String): Boolean = status in BIDS_OPEN

    fun phoneVisible(status: String): Boolean = status in PHONE_VISIBLE

    /** The number to show and call, or null (before `accepted`, or when v1 sent none). */
    fun driverPhone(status: String, driver: LegacyDriver?): String? =
        driver?.phone?.takeIf { phoneVisible(status) && it.isNotBlank() }

    /** `cancelOrder.acceptedText` once a driver was chosen (someone is counting on the parcel), else the plain text. */
    fun cancelTextKey(status: String): String =
        if (status == "accepted") "confirmDialog.cancelOrder.acceptedText" else "confirmDialog.cancelOrder.text"

    /**
     * The Yordam ticket's first words for "Muammo haqida xabar" (Q141): the order number and a colon, so the operator
     * knows which v1 order it is about (v1 orders have no v2 booking, so there is no booking-bound chat). Null without
     * a number: the ticket starts empty.
     */
    fun supportPrefill(orderNumber: String?): String? = orderNumber?.trim()?.takeIf { it.isNotEmpty() }?.let { "$it: " }

    // -- the archive list (DESIGN10 1.2) ------------------------------------------------------------------------------

    /** The list's chips. `GET /client/orders` takes one status, and "Yakunlangan" is two, so they filter on the phone. */
    enum class Filter(val labelKey: String) {
        ALL("client.v3archive.filterAll"),
        COMPLETED("status.completed"),
        CANCELLED("status.cancelled"),
        DISPUTED("client.v3archive.filterDisputed"),
    }

    private val COMPLETED = setOf("delivered", "confirmed", "paid_manual")

    fun matches(filter: Filter, status: String): Boolean = when (filter) {
        Filter.ALL -> true
        Filter.COMPLETED -> status in COMPLETED
        Filter.CANCELLED -> status == "cancelled"
        Filter.DISPUTED -> status == "disputed"
    }

    /** With fewer rows than this after a filter, the list asks for the next page by itself (v1 history is small). */
    const val FILL_ROWS = 8

    /** The row's and the detail's meta: "EL-10422 · 04.08.2026" (either half alone when the other is missing). */
    fun numberAndDate(orderNumber: String?, createdAt: String?): String? =
        listOfNotNull(orderNumber?.takeIf { it.isNotBlank() }, tashkent(createdAt)?.format(DATE)).joinToString(" · ").ifEmpty { null }

    private val DATE = java.time.format.DateTimeFormatter.ofPattern("dd.MM.yyyy")

    /** "★★★★ (4 / 5)": the stars just sent (DESIGN10 2.8 - only in this session, the server keeps no rating field). */
    fun starsText(stars: Int): String? = stars.takeIf { it in 1..5 }?.let { "★".repeat(it) + " ($it / 5)" }

    // -- the map sheet (DESIGN10 3.4) -------------------------------------------------------------------------------

    /** The sheet's tabs: only an end with a point gets one. */
    enum class MapEnd { PICKUP, DROPOFF }

    fun mapEnds(detail: LegacyOrderDetail): List<MapEnd> = listOfNotNull(
        MapEnd.PICKUP.takeIf { hasPoint(detail.pickupLat, detail.pickupLng) },
        MapEnd.DROPOFF.takeIf { hasPoint(detail.dropoffLat, detail.dropoffLng) },
    )

    /** "41.31108, 69.27974": five decimals, a dot whatever the language. */
    fun coordinates(lat: Double, lng: Double): String = String.format(Locale.US, "%.5f, %.5f", lat, lng)

    // -- the order's words ----------------------------------------------------------------------------------------

    /** "Toshkent shahri → Samarqand viloyati": the region, else the district, else "?". */
    fun route(detail: LegacyOrderDetail): String =
        "${detail.fromCity?.nameUz ?: detail.fromDistrict?.nameUz ?: "?"} → ${detail.toCity?.nameUz ?: detail.toDistrict?.nameUz ?: "?"}"

    /** The price the client sees: agreed (`final_price`), else the client's own, else the suggested one - in minor units. */
    fun priceMinor(detail: LegacyOrderDetail): Long? = OrderRules.legacyPriceMinor(detail.finalPrice, detail.suggestedPrice, detail.clientPrice)

    /** A bid's DECIMAL so'm price (`68000.0`) in minor units. */
    fun bidPriceMinor(price: JsonElement?): Long? = OrderRules.legacyPriceMinor(price, null)

    /** "★ 4,6", or null when the driver has no rating yet (v1 sends 0.0 then - never shown as a score). */
    fun ratingText(rating: Double?, locale: Locale): String? =
        rating?.takeIf { it > 0.0 }?.let { "★ ${BookingRules.formatRating(it, locale)}" }

    /** Coordinates only when both halves are there (and not the 0,0 of an empty form). */
    fun hasPoint(lat: Double?, lng: Double?): Boolean = lat != null && lng != null && !(lat == 0.0 && lng == 0.0)

    fun hasAnyPoint(detail: LegacyOrderDetail): Boolean =
        hasPoint(detail.pickupLat, detail.pickupLng) || hasPoint(detail.dropoffLat, detail.dropoffLng)

    // -- Yandex Maps (the old app's links) ------------------------------------------------------------------------

    /** The pickup point on the map. Yandex's `pt` is **longitude first**. */
    fun yandexPointUrl(lat: Double, lng: Double): String = "https://yandex.uz/maps/?pt=${plain(lng)},${plain(lat)}&z=16&l=map"

    /** A drive to the drop-off from wherever the phone is (`rtext=~lat,lng`, latitude first here). */
    fun yandexRouteUrl(lat: Double, lng: Double): String = "https://yandex.uz/maps/?rtext=~${plain(lat)},${plain(lng)}&rtt=auto"

    private fun plain(value: Double): String = BigDecimal.valueOf(value).stripTrailingZeros().toPlainString()

    // -- time -----------------------------------------------------------------------------------------------------

    /**
     * A v1 timestamp: some fields carry an offset (`created_at`), others are naive (`published_at`, Q9: the timestamptz
     * migration is pending) and are UTC. Both become an instant.
     */
    fun parseTimestamp(value: String?): Instant? {
        val text = value?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        runCatching { return OffsetDateTime.parse(text).toInstant() }
        runCatching { return Instant.parse(text) }
        return runCatching { LocalDateTime.parse(text).toInstant(ZoneOffset.UTC) }.getOrNull()
    }

    /** The same moment on a Tashkent wall clock (the app shows every time there). */
    fun tashkent(value: String?): LocalDateTime? = parseTimestamp(value)?.let { LocalDateTime.ofInstant(it, ParcelRules.TASHKENT) }

    /** `30.09, 20:28` in Tashkent, or null when it cannot be read. */
    fun displayTime(value: String?): String? = tashkent(value)?.let(ParcelRules::displayShort)

    /** As an ISO instant, for the list's day helpers (which read offsets only). */
    fun isoInstant(value: String?): String? = parseTimestamp(value)?.toString()

    // -- refusals -------------------------------------------------------------------------------------------------

    /** 404 / 403 on the detail: not (or no longer) this client's order - the not-found state, not an error. */
    fun isNotFound(error: Throwable): Boolean {
        val api = error as? ApiException ?: return false
        return api.status == 404 || api.status == 403 || api.code == "NOT_FOUND" || api.code == "FORBIDDEN"
    }

    /** A repeated rating (409 ALREADY_EXISTS) means it is already done. */
    fun ratingAlreadyDone(error: Throwable): Boolean = (error as? ApiException)?.code == "ALREADY_EXISTS"

    /** BID_NOT_ACTIVE: someone else's choice or a withdrawn bid - the list is read again. */
    fun bidGone(error: Throwable): Boolean = (error as? ApiException)?.code == "BID_NOT_ACTIVE"

    /** ORDER_INVALID_STATUS: the order is no longer where the screen shows it - read it again. */
    fun statusChanged(error: Throwable): Boolean = (error as? ApiException)?.code == "ORDER_INVALID_STATUS"

    /** The dictionary key a failed v1 command reads as; null = the generic mapping (offline, 429, `error.<CODE>`). */
    fun errorKey(error: Throwable): String? = when ((error as? ApiException)?.code) {
        "ORDER_INVALID_STATUS" -> "client.legacy.error.orderChanged"
        "BID_NOT_ACTIVE" -> "client.legacy.error.bidGone"
        // The dictionary's DRIVER_* sentences speak to the driver ("Faol holatni yoqing"); the client reads this.
        "DRIVER_NOT_APPROVED", "DRIVER_BLOCKED", "DRIVER_NOT_AVAILABLE" -> "client.legacy.error.driverUnavailable"
        else -> null
    }
}
