package uz.elchi.app.feature.driver

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.generated.DirectionEndDTO
import uz.elchi.app.api.generated.DirectionEndInput
import uz.elchi.app.api.generated.DirectionOfferCreate
import uz.elchi.app.api.generated.DirectionOfferDTO
import uz.elchi.app.api.generated.DirectionRequestItemDTO
import uz.elchi.app.api.generated.DistrictDTO
import uz.elchi.app.api.generated.DriverDirectionCreate
import uz.elchi.app.api.generated.DriverDirectionDTO
import uz.elchi.app.api.generated.PointEndDTO
import uz.elchi.app.api.generated.RegionDTO
import uz.elchi.app.api.generated.VehicleDTO
import uz.elchi.app.feature.client.OrderRules
import uz.elchi.app.feature.client.ParcelRules
import java.time.Duration
import java.time.Instant
import java.time.format.DateTimeFormatter

/** The direction feed's day chips (web `FeedDay`). */
enum class DirectionDay(val key: String) {
    TODAY("dir.day.today"),
    TOMORROW("dir.day.tomorrow"),
    WEEK("dir.day.week"),
}

/** The feed page cut into the three answers the server gave (web `DirectionGroups`). */
data class DirectionGroups(
    val fits: List<DirectionRequestItemDTO>,
    val fresh: List<DirectionRequestItemDTO>,
    val otherTime: List<DirectionRequestItemDTO>,
)

/** The add form as picked: a region, and a district where the region asks for one. */
data class DirectionForm(
    val originRegion: RegionDTO? = null,
    val originDistrict: DistrictDTO? = null,
    val destinationRegion: RegionDTO? = null,
    val destinationDistrict: DistrictDTO? = null,
)

/** What the add form still lacks. */
enum class DirectionFormIssue { ORIGIN_REGION, ORIGIN_DISTRICT, DESTINATION_REGION, DESTINATION_DISTRICT }

/** A product answer the add form says in place (not a failure banner). */
enum class DirectionNotice(val key: String) {
    NO_ROAD("dir.noRoad"),
    EXISTS("dir.exists"),
}

/** How an offer from a direction ended, for the screen. */
sealed interface DirectionOfferOutcome {
    /** Sent: [key] is the toast ("dir.bid.tripCreated" / "dir.bid.tripRetimed" / "driverBid.sent"), [time] its `{time}`. */
    data class Sent(val threadId: String, val key: String, val time: String?) : DirectionOfferOutcome

    /** `409 TIME_WINDOW_CONFLICT` with the car's ETA: offer exactly that time instead (Q153). */
    data class ProposeTime(val eta: String) : DirectionOfferOutcome

    /** Q157: the car's time is too far from the client's - no proposal can work; the limits in hours. */
    data class TooFar(val early: Long, val late: Long) : DirectionOfferOutcome

    /** `409 BOOKING_CUTOFF_PASSED` / `pickup_passed`: the car is already past this pickup (Q154). */
    data object Passed : DirectionOfferOutcome

    /** This driver already has an open offer on the request: open it instead of a second. */
    data class Existing(val threadId: String) : DirectionOfferOutcome

    /** Anything else: the generic `error.<CODE>` sentence. */
    data class Failed(val error: Throwable) : DirectionOfferOutcome
}

/**
 * ADR-0027 (Q150-Q158), the rules of the driver's direction screens - a port of the web `directionFeed.ts`. The
 * driver names two ends; trips and the departure are the server's. Pure, so it is unit-tested.
 */
object DirectionRules {
    const val ACTIVE = "active"
    const val PAUSED = "paused"
    const val ARCHIVED = "archived"

    const val FITS_TRIP = "fits_trip"
    const val NO_TRIP = "no_trip"
    const val TIME_DIFFERS = "time_differs"

    // -- the list -----------------------------------------------------------------------------------------------

    /** The direction the feed opens on: the chosen one while it is still live, else the first active, else any live. */
    fun pickDirection(list: List<DriverDirectionDTO>, current: String?): String? {
        if (list.any { it.id == current && it.status != ARCHIVED }) return current
        return list.firstOrNull { it.status == ACTIVE }?.id ?: list.firstOrNull { it.status != ARCHIVED }?.id
    }

    /** The live directions (an archived one is gone for the driver). */
    fun live(list: List<DriverDirectionDTO>): List<DriverDirectionDTO> = list.filter { it.status != ARCHIVED }

    /** Pause ↔ resume. */
    fun toggledStatus(direction: DriverDirectionDTO): String = if (direction.status == ACTIVE) PAUSED else ACTIVE

    /** An end's name for a card: the district when there is one, else the region (a city without districts). */
    fun endName(end: DirectionEndDTO, ru: Boolean): String =
        if (end.districtId != null) (if (ru) end.districtNameRu else null) ?: end.districtNameUz ?: "-"
        else (if (ru) end.regionNameRu else null) ?: end.regionNameUz

    fun title(direction: DriverDirectionDTO, ru: Boolean): String = "${endName(direction.origin, ru)} → ${endName(direction.destination, ru)}"

    /** Kilograms of the direction's cargo room, rounded (web `Math.round(g / 1000)`). */
    fun kg(grams: Long): Long = Math.round(grams / 1000.0)

    // -- the add form -------------------------------------------------------------------------------------------

    /** A region asks for a district unless the catalogue says it does not (Tashkent city). */
    fun needsDistrict(region: RegionDTO?): Boolean = region?.requiresDistrict != false

    fun issues(form: DirectionForm): Set<DirectionFormIssue> = buildSet {
        if (form.originRegion == null) add(DirectionFormIssue.ORIGIN_REGION)
        else if (needsDistrict(form.originRegion) && form.originDistrict == null) add(DirectionFormIssue.ORIGIN_DISTRICT)
        if (form.destinationRegion == null) add(DirectionFormIssue.DESTINATION_REGION)
        else if (needsDistrict(form.destinationRegion) && form.destinationDistrict == null) add(DirectionFormIssue.DESTINATION_DISTRICT)
    }

    /**
     * `POST /driver-directions`: two ends, nothing else. The car is named only when the driver has more than one
     * approved car (with one the server takes it, Q150); capacity is the car's.
     */
    fun createBody(form: DirectionForm, vehicles: List<VehicleDTO>?): DriverDirectionCreate? {
        if (issues(form).isNotEmpty()) return null
        val origin = form.originRegion ?: return null
        val destination = form.destinationRegion ?: return null
        val approved = vehicles.orEmpty().filter { it.verificationStatus == "approved" }
        return DriverDirectionCreate(
            origin = DirectionEndInput(regionId = origin.id, districtId = form.originDistrict?.id),
            destination = DirectionEndInput(regionId = destination.id, districtId = form.destinationDistrict?.id),
            vehicleId = approved.firstOrNull()?.id?.takeIf { approved.size > 1 },
        )
    }

    /** The district list filtered by the search text (name in either language, case-insensitive). */
    fun searchDistricts(list: List<DistrictDTO>, query: String): List<DistrictDTO> {
        val q = query.trim().lowercase()
        if (q.isEmpty()) return list
        return list.filter { it.nameUz.lowercase().contains(q) || it.nameRu?.lowercase()?.contains(q) == true }
    }

    // -- the feed -----------------------------------------------------------------------------------------------

    /** The server's order is kept inside each group (it sorts by time already). */
    fun group(items: List<DirectionRequestItemDTO>): DirectionGroups = DirectionGroups(
        fits = items.filter { it.fit == FITS_TRIP },
        fresh = items.filter { it.fit == NO_TRIP },
        otherTime = items.filter { it.fit == TIME_DIFFERS },
    )

    private fun iso(instant: Instant): String =
        instant.atZone(ParcelRules.TASHKENT).toOffsetDateTime().format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)

    /** The Tashkent day(s) a chip means: today = now → midnight, tomorrow = the whole next day, week = now → +7 days. */
    fun range(day: DirectionDay, now: Instant): Pair<String, String> {
        val midnight = now.atZone(ParcelRules.TASHKENT).toLocalDate().atStartOfDay(ParcelRules.TASHKENT).toInstant()
        val dayLength = Duration.ofDays(1)
        val start = if (day == DirectionDay.TOMORROW) midnight.plus(dayLength) else now
        val end = when (day) {
            DirectionDay.TODAY -> midnight.plus(dayLength)
            DirectionDay.TOMORROW -> midnight.plus(dayLength.multipliedBy(2))
            DirectionDay.WEEK -> now.plus(Duration.ofDays(7))
        }
        return iso(start) to iso(end)
    }

    /** ADR-0028: a place on a card - a marked point by its address, else its district. Never a stop name. */
    fun place(point: PointEndDTO?, fallback: String): String {
        point ?: return fallback
        return point.address?.let(ParcelRules::withoutCountry)?.trim()?.takeIf { it.isNotEmpty() } ?: point.district?.nameUz ?: fallback
    }

    /** "29.09, 07:30" in Tashkent; "-" when unreadable. */
    fun dayClock(iso: String?): String = OrderRules.parseInstant(iso)?.let(DriverTime::dayClock) ?: "-"

    /** "07:30" in Tashkent; "-" when unreadable. */
    fun clock(iso: String?): String = OrderRules.parseInstant(iso)?.let(DriverTime::clock) ?: "-"

    // -- the offer ----------------------------------------------------------------------------------------------

    /** A request at another time is offered at the car's own ETA (a time proposal); a conflict's ETA wins. */
    fun proposeAt(item: DirectionRequestItemDTO, conflictEta: String?): String? =
        conflictEta ?: item.pickupEta.takeIf { item.fit == TIME_DIFFERS }

    /** `POST /driver-directions/{id}/offers`: the price (and the time proposal, when there is one). No trip, no window. */
    fun offerBody(listingId: String, unitPriceMinor: Long, pickupAt: String?, message: String? = null) = DirectionOfferCreate(
        listingId = listingId,
        unitPriceMinor = unitPriceMinor,
        pickupAt = pickupAt,
        message = message?.trim()?.takeIf { it.isNotEmpty() },
    )

    /** One idempotency key per distinct request: a retry of the same body reuses it, a time proposal is a new one. */
    fun offerScope(directionId: String, listingId: String, unitPriceMinor: Long, pickupAt: String?): String =
        "dir-offer:$directionId:$listingId:$unitPriceMinor:${pickupAt.orEmpty()}"

    /** The toast after a sent offer: the trip the system planned or re-timed, else the plain "sent". */
    fun sent(dto: DirectionOfferDTO): DirectionOfferOutcome.Sent = when {
        dto.tripCreated -> DirectionOfferOutcome.Sent(dto.thread.id, "dir.bid.tripCreated", dayClock(dto.trip.plannedStartAt))
        dto.tripRetimed -> DirectionOfferOutcome.Sent(dto.thread.id, "dir.bid.tripRetimed", dayClock(dto.trip.plannedStartAt))
        else -> DirectionOfferOutcome.Sent(dto.thread.id, "driverBid.sent", null)
    }

    /** A refused offer, read the way the web reads it (`timeProposalEta`, `isPickupPassed`, `timeProposalTooFar`). */
    fun failed(error: Throwable, pickupAt: String?): DirectionOfferOutcome {
        val eta = timeProposalEta(error)
        if (eta != null && pickupAt == null) return DirectionOfferOutcome.ProposeTime(eta)
        if (isPickupPassed(error)) return DirectionOfferOutcome.Passed
        timeProposalTooFar(error)?.let { (early, late) -> return DirectionOfferOutcome.TooFar(early, late) }
        OfferRules.openThreadId(error)?.let { return DirectionOfferOutcome.Existing(it) }
        return DirectionOfferOutcome.Failed(error)
    }

    // -- the server's answers -----------------------------------------------------------------------------------

    private fun details(error: Throwable, code: String): JsonObject? {
        val api = error as? ApiException ?: return null
        if (api.code != code) return null
        return api.details as? JsonObject ?: JsonObject(emptyMap())
    }

    private fun JsonObject.string(key: String): String? = (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.contentOrNull

    private fun JsonObject.bool(key: String): Boolean? = (this[key] as? JsonPrimitive)?.booleanOrNull

    private fun JsonObject.number(key: String): Double? = (this[key] as? JsonPrimitive)?.takeIf { !it.isString }?.doubleOrNull

    private fun tooFar(d: JsonObject): Boolean = d.bool("time_proposal_possible") == false || d.string("reason") == "time_proposal_too_far"

    /** The car's real ETA from a time conflict - unless the server says no time proposal can work (Q157). */
    fun timeProposalEta(error: Throwable): String? {
        val d = details(error, "TIME_WINDOW_CONFLICT") ?: return null
        if (tooFar(d)) return null
        return d.string("eta")
    }

    /** Q157: the server's limits (hours) when the car's time is too far from the client's; null otherwise. */
    fun timeProposalTooFar(error: Throwable): Pair<Long, Long>? {
        val d = details(error, "TIME_WINDOW_CONFLICT") ?: return null
        if (!tooFar(d)) return null
        fun hours(key: String, fallback: Long) = d.number(key)?.let { Math.round(it / 60) } ?: fallback
        return hours("max_early_minutes", 3) to hours("max_late_minutes", 12)
    }

    /** `409 ROUTE_MISMATCH` on create: no ELCHI road serves these two ends yet. */
    fun isNoRoad(error: Throwable): Boolean = (error as? ApiException)?.code == "ROUTE_MISMATCH"

    /** `400 VALIDATION_ERROR` with `direction_exists`. */
    fun isDuplicate(error: Throwable): Boolean = details(error, "VALIDATION_ERROR")?.string("reason") == "direction_exists"

    /** `409 BOOKING_CUTOFF_PASSED` / `pickup_passed` (Q154). */
    fun isPickupPassed(error: Throwable): Boolean = details(error, "BOOKING_CUTOFF_PASSED")?.string("reason") == "pickup_passed"

    /** The add form's in-place answer for a refusal, or null for an ordinary error. */
    fun notice(error: Throwable): DirectionNotice? = when {
        isNoRoad(error) -> DirectionNotice.NO_ROAD
        isDuplicate(error) -> DirectionNotice.EXISTS
        else -> null
    }
}
