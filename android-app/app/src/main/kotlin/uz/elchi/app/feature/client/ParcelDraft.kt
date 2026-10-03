package uz.elchi.app.feature.client

import kotlinx.serialization.Serializable
import uz.elchi.app.api.generated.ContactDetails
import uz.elchi.app.api.generated.Currency
import uz.elchi.app.api.generated.DirectionPreviewDTO
import uz.elchi.app.api.generated.DistrictDTO
import uz.elchi.app.api.generated.ListingCreate
import uz.elchi.app.api.generated.ListingKind
import uz.elchi.app.api.generated.ParcelDetails
import uz.elchi.app.api.generated.ParcelPayer
import uz.elchi.app.api.generated.ParcelType
import uz.elchi.app.api.generated.PaymentMethod
import uz.elchi.app.api.generated.PointEndInput
import uz.elchi.app.api.generated.PriceBasis
import uz.elchi.app.api.generated.ServiceType
import java.time.Duration
import java.time.Instant
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.roundToLong
import kotlin.math.sin
import kotlin.math.sqrt

/** Which end of the direction a picker is filling. */
@Serializable
enum class End { ORIGIN, DESTINATION }

/**
 * One end of the direction (Q88): region -> district -> a point on the map. A verified stop is optional; when the
 * person picks one, [stopId] is set and the listing names the stop (an `exact` match) instead of the point.
 */
@Serializable
data class Place(
    val regionId: String,
    val regionUz: String,
    val regionRu: String? = null,
    val districtId: String,
    val districtUz: String,
    val districtRu: String? = null,
    val lat: Double,
    val lng: Double,
    /** Reverse-geocoded, without the country. Null when the geocoder had no real answer: the coordinates stand. */
    val address: String? = null,
    val stopId: String? = null,
    val stopUz: String? = null,
    val stopRu: String? = null,
    /** Set from the phone's position by the home's locate button (design `locate`): titled "Joriy joylashuv". */
    val current: Boolean = false,
) {
    fun region(ru: Boolean) = if (ru) regionRu ?: regionUz else regionUz
    fun district(ru: Boolean) = if (ru) districtRu ?: districtUz else districtUz
    fun stop(ru: Boolean) = if (ru) stopRu ?: stopUz else stopUz

    /** What identifies the place for a person: the stop, the address, or - honestly - the coordinates. */
    fun label(ru: Boolean): String = stop(ru) ?: address ?: ParcelRules.coordinates(lat, lng)

    /** "Samarqand viloyati / Samarqand"; one name when the district is the region (Toshkent shahri). */
    fun area(ru: Boolean): String = if (region(ru) == district(ru)) region(ru) else "${region(ru)} / ${district(ru)}"

    /** The design's subtitle: "Chilonzor, Toshkent shahri"; one name when the district is the region. */
    fun areaLine(ru: Boolean): String = listOf(district(ru), region(ru)).distinct().joinToString(", ")
}

/**
 * The parcel request being written. It survives navigation between the steps and process recreation (saved as
 * JSON in the flow's SavedStateHandle). Windows are Asia/Tashkent wall-clock times (`2026-09-30T09:00`); money is
 * the typed so'm digits, converted to minor units only when the body is built.
 */
@Serializable
data class ParcelDraft(
    val origin: Place? = null,
    val destination: Place? = null,
    val windowStart: String? = null,
    val windowEnd: String? = null,
    val priceDigits: String = "",
    val senderName: String = "",
    /** The 9 local digits after +998. */
    val senderDigits: String = "",
    val receiverName: String = "",
    val receiverDigits: String = "",
    val comment: String = "",
    /** [ParcelType] wire value. */
    val parcelType: String? = null,
    val categoryId: String? = null,
    /** The reference `POST /files/upload` returned; the listing sends it back as `parcel.photo_file_id`. */
    val photoFileUrl: String? = null,
    /** The compressed JPEG in the app cache, only for the preview on screen. */
    val photoLocalPath: String? = null,
    /** Taksi (passenger request) instead of Pochta: the same places, window and price, then seats - no parcel steps. */
    val taxi: Boolean = false,
    /** The seats the person pictured ([Seat] ids, in picking order); only their COUNT is sent (`TaxiRules`). */
    val seats: List<String> = TaxiRules.DEFAULT_SEATS,
) {
    fun end(end: End): Place? = if (end == End.ORIGIN) origin else destination

    fun withEnd(end: End, place: Place?): ParcelDraft = if (end == End.ORIGIN) copy(origin = place) else copy(destination = place)

    val start: LocalDateTime? get() = windowStart?.let(ParcelRules::parseLocal)
    val endTime: LocalDateTime? get() = windowEnd?.let(ParcelRules::parseLocal)
}

/** What still stops the route step (1) - or the Taksi home - from going on, in the order the screen lists it. */
enum class RouteIssue { POINTS, WINDOW_START, WINDOW_END, WINDOW_PAST, WINDOW_ORDER, SEATS, PRICE }

/** What still stops the contact step (2, design `errsFor('contact')`), in the order the screen lists it. */
enum class ContactIssue { SENDER_NAME, SENDER_PHONE, RECEIVER_NAME, RECEIVER_PHONE, TYPE, SIZE, PHOTO }

/** Pure rules of the parcel request: no Android, no network - unit-tested. */
object ParcelRules {
    val TASHKENT: ZoneId = ZoneId.of("Asia/Tashkent")
    const val TIMEZONE = "Asia/Tashkent"

    /** The design's warning threshold: an end further than this from the road is not in the travel time. */
    const val OFF_ROUTE_WARN_M = 5_000L

    private val LOCAL = DateTimeFormatter.ISO_LOCAL_DATE_TIME
    private val LOCAL_MINUTES = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm")
    private val DISPLAY = DateTimeFormatter.ofPattern("dd.MM.yyyy, HH:mm")
    private val SHORT = DateTimeFormatter.ofPattern("dd.MM, HH:mm")

    /** Default departure window: tomorrow 09:00-18:00 in Tashkent, whatever the phone's own zone. */
    fun defaultWindow(now: Instant): Pair<LocalDateTime, LocalDateTime> {
        val tomorrow = now.atZone(TASHKENT).toLocalDate().plusDays(1)
        return LocalDateTime.of(tomorrow, LocalTime.of(9, 0)) to LocalDateTime.of(tomorrow, LocalTime.of(18, 0))
    }

    fun formatLocal(value: LocalDateTime): String = value.format(LOCAL_MINUTES)

    fun parseLocal(value: String): LocalDateTime? = runCatching { LocalDateTime.parse(value, LOCAL) }.getOrNull()

    fun display(value: LocalDateTime): String = value.format(DISPLAY)

    fun displayShort(value: LocalDateTime): String = value.format(SHORT)

    /** A Tashkent wall-clock time as the ISO instant with offset the API wants: `2026-09-30T09:00:00+05:00`. */
    fun toOffsetIso(value: LocalDateTime): String =
        value.withSecond(0).withNano(0).atZone(TASHKENT).toOffsetDateTime().format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)

    /** So'm as typed ("120 000", "120000") to minor units (x100). Null when it is not a positive whole number. */
    fun soumToMinor(text: String): Long? {
        val digits = text.filter { !it.isWhitespace() }
        if (digits.isEmpty() || !digits.all(Char::isDigit) || digits.length > 12) return null
        val soum = digits.toLong()
        return if (soum > 0) soum * 100 else null
    }

    /** Whole so'm for display; the API never sends fractions of a so'm for these prices. */
    fun minorToSoum(minor: Long): Long = minor / 100

    /** `120 000` - thousands grouped with a no-break space, so a price never wraps in the middle. */
    fun groupThousands(value: Long): String {
        val raw = value.toString()
        val negative = raw.startsWith("-")
        val digits = raw.removePrefix("-")
        val grouped = digits.reversed().chunked(3).joinToString(NBSP.toString()).reversed()
        return if (negative) "-$grouped" else grouped
    }

    /** `120 000 so'm` from minor units. */
    fun formatSoum(minor: Long, unit: String): String = "${groupThousands(minorToSoum(minor))}$NBSP$unit"

    const val NBSP = ' '

    fun routeIssues(draft: ParcelDraft, directionReady: Boolean, now: Instant): List<RouteIssue> {
        val issues = mutableListOf<RouteIssue>()
        if (draft.origin == null || draft.destination == null || !directionReady) issues += RouteIssue.POINTS
        val start = draft.start
        val end = draft.endTime
        if (start == null) issues += RouteIssue.WINDOW_START
        if (end == null) issues += RouteIssue.WINDOW_END
        if (start != null && !start.atZone(TASHKENT).toInstant().isAfter(now)) issues += RouteIssue.WINDOW_PAST
        if (start != null && end != null && !end.isAfter(start)) issues += RouteIssue.WINDOW_ORDER
        if (soumToMinor(draft.priceDigits) == null) issues += RouteIssue.PRICE
        return issues
    }

    fun phoneValid(digits: String): Boolean = digits.length == 9 && digits.all(Char::isDigit)

    /** The design's name rule: at least two letters once trimmed. */
    const val NAME_MIN = 2

    fun nameValid(name: String): Boolean = name.trim().length >= NAME_MIN

    fun contactsComplete(draft: ParcelDraft): Boolean =
        nameValid(draft.senderName) && phoneValid(draft.senderDigits) &&
            nameValid(draft.receiverName) && phoneValid(draft.receiverDigits)

    fun parcelComplete(draft: ParcelDraft): Boolean = draft.parcelType != null && draft.categoryId != null

    /** The contact step's issues (sender, receiver, type, size, photo), in the design's order. */
    fun contactIssues(draft: ParcelDraft): List<ContactIssue> = buildList {
        if (!nameValid(draft.senderName)) add(ContactIssue.SENDER_NAME)
        if (!phoneValid(draft.senderDigits)) add(ContactIssue.SENDER_PHONE)
        if (!nameValid(draft.receiverName)) add(ContactIssue.RECEIVER_NAME)
        if (!phoneValid(draft.receiverDigits)) add(ContactIssue.RECEIVER_PHONE)
        if (draft.parcelType == null) add(ContactIssue.TYPE)
        if (draft.categoryId == null) add(ContactIssue.SIZE)
        if (draft.photoFileUrl == null) add(ContactIssue.PHOTO)
    }

    /** Everything the review screen needs before "publish" can be pressed. */
    fun readyToPublish(draft: ParcelDraft, directionReady: Boolean, now: Instant): Boolean =
        routeIssues(draft, directionReady, now).isEmpty() && contactIssues(draft).isEmpty()

    // -- the price stepper (design: -/+ 5 000 so'm, at most 8 digits) ---------------------------------------------

    const val PRICE_STEP = 5_000L
    const val PRICE_MAX_DIGITS = 8
    private const val PRICE_MAX = 99_999_999L

    /** Typed text -> the digits kept in the draft: no leading zeros, at most [PRICE_MAX_DIGITS]. */
    fun cleanPrice(text: String): String = text.filter(Char::isDigit).trimStart('0').take(PRICE_MAX_DIGITS)

    /** One tap on - (direction -1) or + (+1); down to nothing (the "0" placeholder), never below. */
    fun stepPrice(digits: String, direction: Int): String {
        val current = digits.toLongOrNull() ?: 0L
        val next = (current + direction * PRICE_STEP).coerceIn(0L, PRICE_MAX)
        return if (next == 0L) "" else next.toString()
    }

    // -- the comment (design: 300 characters; contacts in it are masked by the server, Q43) ------------------------

    const val NOTE_MAX = 300

    private val NOTE_PHONE = Regex("""\d{7,}|\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}""")
    private val NOTE_LINK = Regex("""https?://\S+|www\.\S+|t\.me/\S+|@\w+""")
    private val NOTE_CONTACT = Regex("""\d{7,}|\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}|https?:|www\.|t\.me|@\w""")

    /** The comment holds something that looks like a phone number or a link: the screen warns it will be hidden. */
    fun noteHasContact(text: String): Boolean = NOTE_CONTACT.containsMatchIn(text)

    /** The review's preview of what the server will publish: numbers and links as `•••` (the server decides). */
    fun maskNote(text: String): String = text.replace(NOTE_PHONE, "•••").replace(NOTE_LINK, "•••")

    /** The window's length in minutes, or null while it is not a valid window. */
    fun windowMinutes(draft: ParcelDraft): Long? {
        val start = draft.start ?: return null
        val end = draft.endTime ?: return null
        return if (end.isAfter(start)) Duration.between(start, end).toMinutes() else null
    }

    // -- "Qayerdan" from the phone's position (no v2 ids come back from reverse-geocode) -----------------------------

    /** Further than this from every district centre: not a place ELCHI can name (abroad, or no fix worth using). */
    const val LOCATE_MAX_KM = 50.0

    /** Great-circle distance in km (the server's `distance_km`). */
    fun distanceKm(lat1: Double, lng1: Double, lat2: Double, lng2: Double): Double {
        val r = 6371.0
        val dLat = Math.toRadians(lat2 - lat1)
        val dLng = Math.toRadians(lng2 - lng1)
        val h = sin(dLat / 2).let { it * it } +
            cos(Math.toRadians(lat1)) * cos(Math.toRadians(lat2)) * sin(dLng / 2).let { it * it }
        return 2 * r * asin(sqrt(h))
    }

    /** The server's `nearest_district`: the active district whose centre is closest, within [LOCATE_MAX_KM]. */
    fun nearestDistrict(lat: Double, lng: Double, districts: List<DistrictDTO>): DistrictDTO? =
        districts
            .filter { it.isActive != false && it.centerLat != null && it.centerLng != null }
            .map { it to distanceKm(lat, lng, it.centerLat!!, it.centerLng!!) }
            .filter { it.second <= LOCATE_MAX_KM }
            .minByOrNull { it.second }
            ?.first

    /** `+998901234567` for the API; the screens keep the 9 local digits. */
    fun uzPhone(digits: String): String = "+998$digits"

    /** The 9 local digits of a stored phone (`+998 90 123 45 67`, `998901234567`); empty when it is not Uzbek. */
    fun localDigits(phone: String?): String {
        val digits = phone.orEmpty().filter(Char::isDigit)
        return when {
            digits.length == 12 && digits.startsWith("998") -> digits.substring(3)
            digits.length == 9 -> digits
            else -> ""
        }
    }

    /**
     * A number from the phone's contacts as the 9 local digits: `+998 90 123-45-67`, `998901234567`, `90 1234567`;
     * anything longer keeps its last nine (design `slice(-9)`); shorter stays as it is (and fails [phoneValid]).
     */
    fun contactDigits(phone: String): String {
        val digits = phone.filter(Char::isDigit)
        return localDigits(phone).ifEmpty { if (digits.length > 9) digits.takeLast(9) else digits }
    }

    /** `90 123 45 67` */
    fun groupPhone(digits: String): String =
        if (digits.length == 9) "${digits.take(2)} ${digits.substring(2, 5)} ${digits.substring(5, 7)} ${digits.substring(7)}" else digits

    /**
     * The request body (steps 1-4). Throws when the draft is not complete: the review screen only calls it after
     * [readyToPublish]. The comment goes through the server's contact filter (Q43); nothing is masked here.
     */
    fun buildListingCreate(draft: ParcelDraft): ListingCreate {
        val origin = checkNotNull(draft.origin) { "origin" }
        val destination = checkNotNull(draft.destination) { "destination" }
        val start = checkNotNull(draft.start) { "window start" }
        val end = checkNotNull(draft.endTime) { "window end" }
        val price = checkNotNull(soumToMinor(draft.priceDigits)) { "price" }
        return ListingCreate(
            kind = ListingKind.REQUEST,
            serviceType = ServiceType.PARCEL,
            originStopId = origin.stopId,
            originPoint = if (origin.stopId == null) point(origin) else null,
            destinationStopId = destination.stopId,
            destinationPoint = if (destination.stopId == null) point(destination) else null,
            departureWindowStart = toOffsetIso(start),
            departureWindowEnd = toOffsetIso(end),
            timezone = TIMEZONE,
            priceBasis = PriceBasis.TOTAL,
            unitPriceMinor = price,
            currency = Currency.UZS,
            paymentMethod = PaymentMethod.CASH,
            comment = draft.comment.trim().ifEmpty { null },
            parcel = ParcelDetails(
                parcelType = ParcelType.entries.firstOrNull { it.value == draft.parcelType && it != ParcelType.UNKNOWN },
                categoryId = draft.categoryId,
                payer = ParcelPayer.SENDER,
                sender = ContactDetails(name = draft.senderName.trim(), phone = uzPhone(draft.senderDigits)),
                receiver = ContactDetails(name = draft.receiverName.trim(), phone = uzPhone(draft.receiverDigits)),
                photoFileId = draft.photoFileUrl,
            ),
        )
    }

    private fun point(place: Place) = PointEndInput(lat = place.lat, lng = place.lng, districtId = place.districtId, address = place.address)

    /**
     * Yandex writes "Oʻzbekiston, Samarqand, Amir Temur koʻchasi, 18А". The country is what everybody on the screen
     * already knows; dropping it leaves the part that identifies the place.
     */
    fun withoutCountry(address: String): String {
        val parts = address.split(",").map(String::trim).filter(String::isNotEmpty).toMutableList()
        val first = parts.firstOrNull()?.lowercase()?.replace(Regex("[ʻ'’`]"), "'")
        if (first == "o'zbekiston" || first == "uzbekistan" || first == "узбекистан") parts.removeAt(0)
        return parts.joinToString(", ")
    }

    /** `39.65480, 66.97560` - a marked place the geocoder could not name still has true coordinates. */
    fun coordinates(lat: Double, lng: Double): String = "%.5f, %.5f".format(java.util.Locale.ROOT, lat, lng)

    /** Hours and minutes, rounded to 5 minutes like the web client - the road time is an estimate, not a promise. */
    fun durationParts(seconds: Long): Pair<Int, Int> {
        val rounded = ((seconds / 300.0).roundToLong() * 300).coerceAtLeast(300)
        return (rounded / 3600).toInt() to ((rounded % 3600) / 60).toInt()
    }

    /** Kilometres for a road distance: whole km, one decimal (comma) under 10 km. */
    fun km(meters: Long): String {
        if (meters >= 10_000) return (meters / 1000.0).roundToLong().toString()
        val tenths = (meters / 100.0).roundToLong()
        return if (tenths % 10 == 0L) (tenths / 10).toString() else "${tenths / 10},${tenths % 10}"
    }

    /** Kilograms from the catalog's grams: `0,5`, `5`, `30`. */
    fun kg(grams: Long): String {
        val tenths = (grams / 100.0).roundToLong()
        return if (tenths % 10 == 0L) (tenths / 10).toString() else "${tenths / 10},${tenths % 10}"
    }

    /** The ends the preview says are more than [OFF_ROUTE_WARN_M] from the road, with that distance. */
    fun offRouteMeters(preview: DirectionPreviewDTO): Long? =
        listOfNotNull(preview.origin.routeOffsetM, preview.destination.routeOffsetM).filter { it > OFF_ROUTE_WARN_M }.maxOrNull()
}
