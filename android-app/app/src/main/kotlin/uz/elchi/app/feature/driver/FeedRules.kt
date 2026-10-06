package uz.elchi.app.feature.driver

import kotlinx.serialization.Serializable
import uz.elchi.app.api.ElchiJson
import uz.elchi.app.api.generated.FeedItemDTO
import uz.elchi.app.api.generated.FeedSide
import uz.elchi.app.api.generated.MatchGroup
import uz.elchi.app.api.generated.MatchReason
import uz.elchi.app.api.generated.MatchType
import uz.elchi.app.api.generated.PointEndDTO
import uz.elchi.app.api.generated.SavedSearchCreate
import uz.elchi.app.api.generated.SavedSearchDTO
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.api.generated.StopRefDTO
import uz.elchi.app.feature.client.ParcelRules
import java.time.Instant
import java.time.LocalDate
import java.time.format.DateTimeFormatter

/** The feed's date chips (`driver.feed.date*`); 14 days is the default (the web's only choice before). */
enum class FeedDays(val key: String, val startOffset: Long, val days: Long) {
    TODAY("driver.feed.dateToday", 0, 1),
    TOMORROW("driver.feed.dateTomorrow", 1, 1),
    THREE("driver.feed.date3", 0, 3),
    FOURTEEN("driver.feed.date14", 0, 14),
}

/** One end of the feed's direction as picked: a region, then (where the region asks for it) a district. */
@Serializable
data class FeedEnd(
    val regionId: String? = null,
    val regionName: String? = null,
    val requiresDistrict: Boolean = true,
    val districtId: String? = null,
    val districtName: String? = null,
    val regionNameRu: String? = null,
    val districtNameRu: String? = null,
) {
    /** "Samarqand" / "Toshkent shahri": the district when there is one, else the region. */
    val label: String? get() = districtName ?: regionName

    /** [label] in the app's language (Russian names when the catalogue has them). */
    fun label(ru: Boolean): String? = if (districtId != null) district(ru) else region(ru)

    fun region(ru: Boolean): String? = (if (ru) regionNameRu else null) ?: regionName

    fun district(ru: Boolean): String? = (if (ru) districtNameRu else null) ?: districtName
}

/** What the driver is looking at in "Moslar"; remembered per driver between launches. */
@Serializable
data class FeedFilter(
    val service: String = ServiceType.PARCEL.value,
    val origin: FeedEnd = FeedEnd(),
    val destination: FeedEnd = FeedEnd(),
    val days: FeedDays = FeedDays.FOURTEEN,
) {
    val serviceType: ServiceType get() = ServiceType.entries.firstOrNull { it.value == service && it != ServiceType.UNKNOWN } ?: ServiceType.PARCEL
}

/** The one id per side the feed takes: a district, or a whole region where no district is asked for. */
data class EndIds(val regionId: String?, val districtId: String?)

/** `GET /feed` as the app sends it (always requests, alternatives on, recommended order). */
data class FeedQuery(
    val service: ServiceType,
    val dateFrom: String,
    val dateTo: String,
    val origin: EndIds,
    val destination: EndIds,
)

/** The feed's page cut in two (web `feedGroups.ts`): never mixed on screen (Q97). */
data class FeedGroups(val primary: List<FeedItemDTO>, val alternative: List<FeedItemDTO>)

object FeedRules {
    // -- the query ----------------------------------------------------------------------------------------------

    /** Exactly one id per side: the district if picked; the region only where it does not require a district. */
    fun endIds(end: FeedEnd): EndIds? = when {
        end.districtId != null -> EndIds(null, end.districtId)
        end.regionId != null && !end.requiresDistrict -> EndIds(end.regionId, null)
        else -> null
    }

    private fun iso(date: LocalDate): String =
        date.atStartOfDay(ParcelRules.TASHKENT).toOffsetDateTime().format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)

    /** The chip as Tashkent day boundaries (`2026-10-01T00:00:00+05:00`), end exclusive. */
    fun dateRange(days: FeedDays, now: Instant): Pair<String, String> {
        val today = now.atZone(ParcelRules.TASHKENT).toLocalDate()
        val from = today.plusDays(days.startOffset)
        return iso(from) to iso(from.plusDays(days.days))
    }

    /** Null until both ends are complete: the screen then says "choose the route first". */
    fun query(filter: FeedFilter, now: Instant): FeedQuery? {
        val origin = endIds(filter.origin) ?: return null
        val destination = endIds(filter.destination) ?: return null
        val (from, to) = dateRange(filter.days, now)
        return FeedQuery(filter.serviceType, from, to, origin, destination)
    }

    /** With passenger switched off for this driver (flags), the feed is parcel only whatever was remembered. */
    fun effectiveService(filter: FeedFilter, passengerEnabled: Boolean): FeedFilter =
        if (!passengerEnabled && filter.serviceType == ServiceType.PASSENGER) filter.copy(service = ServiceType.PARCEL.value) else filter

    // -- the page -----------------------------------------------------------------------------------------------

    /** Anything the server did not call an alternative is a primary result (a new group never demotes a match). */
    fun split(items: List<FeedItemDTO>): FeedGroups {
        val (alternative, primary) = items.partition { it.group == MatchGroup.ALTERNATIVE }
        return FeedGroups(primary, alternative)
    }

    /** Why an alternative is one: `time_differs` wins (it can break the trip; a nearby stop is a few minutes). */
    fun alternativeReason(reasons: List<MatchReason>): String? = when {
        MatchReason.TIME_DIFFERS in reasons -> "time_differs"
        MatchReason.NEARBY_STOP in reasons -> "nearby_stop"
        else -> null
    }

    /** The primary card's badge: "Bekat mos" / "Yo'l yo'nalishida". */
    fun matchKey(type: MatchType): String? = when (type) {
        MatchType.EXACT -> "match.exact"
        MatchType.ON_ROUTE -> "match.on_route"
        else -> null
    }

    /** A card's end: the stop's district, else the district of the map point - never the street address (Q43 spirit). */
    fun endName(stop: StopRefDTO?, point: PointEndDTO?, ru: Boolean): String =
        // Q158 (ADR-0027): a legacy stop end reads as its district, not as a stop.
        stop?.let { TripRules.placeName(it, ru) } ?: point?.district?.nameUz ?: "?"

    // -- saved routes -------------------------------------------------------------------------------------------

    /** "Shu yo'nalishni saqlash": the feed's ends, requests, quantity 1, notify on, now → +14 days. */
    fun savedSearchBody(query: FeedQuery, now: Instant): SavedSearchCreate {
        val start = now.atZone(ParcelRules.TASHKENT).withSecond(0).withNano(0)
        return SavedSearchCreate(
            destinationDistrictId = query.destination.districtId,
            destinationRegionId = query.destination.regionId,
            notify = true,
            originDistrictId = query.origin.districtId,
            originRegionId = query.origin.regionId,
            quantity = 1,
            serviceType = query.service,
            side = FeedSide.REQUESTS,
            timeWindowEnd = start.plusDays(SAVED_WINDOW_DAYS).toOffsetDateTime().format(DateTimeFormatter.ISO_OFFSET_DATE_TIME),
            timeWindowStart = start.toOffsetDateTime().format(DateTimeFormatter.ISO_OFFSET_DATE_TIME),
        )
    }

    /** A saved route's ends by name from the catalogue the screen has read; the id itself never shows. */
    fun savedRouteTitle(saved: SavedSearchDTO, names: Map<String, String>, stopLabel: String): String {
        fun end(stop: String?, district: String?, region: String?): String =
            district?.let(names::get) ?: region?.let(names::get) ?: stop?.let { stopLabel } ?: "?"
        return "${end(saved.originStopId, saved.originDistrictId, saved.originRegionId)} → " +
            end(saved.destinationStopId, saved.destinationDistrictId, saved.destinationRegionId)
    }

    // -- remembering the filter ---------------------------------------------------------------------------------

    fun encode(filter: FeedFilter): String = ElchiJson.encodeToString(FeedFilter.serializer(), filter)

    fun decode(text: String?): FeedFilter = text?.let { runCatching { ElchiJson.decodeFromString(FeedFilter.serializer(), it) }.getOrNull() } ?: FeedFilter()

    const val SAVED_WINDOW_DAYS = 14L
    const val SAVED_LIMIT = 10
}
