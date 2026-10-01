package uz.elchi.app.feature.driver

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.generated.RouteVersionDTO
import uz.elchi.app.api.generated.TripCreate
import uz.elchi.app.api.generated.TripDTO
import uz.elchi.app.api.generated.TripStatus
import uz.elchi.app.api.generated.TripStopInput
import uz.elchi.app.api.generated.VehicleDTO
import uz.elchi.app.feature.client.OrderRules
import uz.elchi.app.feature.client.ParcelRules
import uz.elchi.app.ui.theme.Tone
import java.time.Instant
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

/**
 * The driver's commands on a trip (`POST /trips/{id}/actions/{action}`, the trip state machine). Interrupt, resume
 * and cancel need a reason (`REASON_REQUIRED_TRIP_ACTIONS` on the server); the operator reads it.
 */
enum class TripCommand(val wire: String, val labelKey: String, val needsReason: Boolean) {
    START_BOARDING("start_boarding", "tripAction.start_boarding", false),
    DEPART("depart", "tripAction.depart", false),
    COMPLETE("complete", "tripAction.complete", false),
    INTERRUPT("interrupt", "driver.trip.pause", true),
    RESUME("resume", "driver.trip.resume", true),
    CANCEL("cancel", "driver.trip.cancel", true),
}

/** A trip command's meaning for the GPS publisher (Q148): board/depart start it, complete/cancel end it. */
enum class GpsEffect { START, FINISH, NONE }

/** "Yo'nalish qo'shish" as typed: picks by id, numbers as text. The departure is Tashkent wall time. */
data class TripForm(
    val vehicleId: String? = null,
    val corridorId: String? = null,
    val routeId: String? = null,
    /** "Jizzax orqali o'tadigan marshrutlar": a stop the routes must pass (only offered for > 1 route). */
    val stopFilterId: String? = null,
    val stopFilterName: String? = null,
    val departure: LocalDateTime? = null,
    val seats: String = "",
    val cargoKg: String = "",
    val cargoLitres: String = "",
)

enum class TripFormIssue { VEHICLE, ROUTE, DEPARTURE, DEPARTURE_PAST, SEATS, CARGO_KG, CARGO_LITRES }

/** The trip timetable and its commands, pure (no Android, no network) so it is unit-tested. */
object TripRules {
    // -- status and commands --------------------------------------------------------------------------------------

    /** The list card's one button (web `tripNextAction`): planned → board, boarding → depart, on the way → complete. */
    fun nextAction(status: TripStatus): TripCommand? = when (status) {
        TripStatus.PLANNED -> TripCommand.START_BOARDING
        TripStatus.BOARDING -> TripCommand.DEPART
        TripStatus.IN_PROGRESS -> TripCommand.COMPLETE
        else -> null
    }

    fun canPause(status: TripStatus): Boolean = status == TripStatus.BOARDING || status == TripStatus.IN_PROGRESS

    fun canResume(status: TripStatus): Boolean = status == TripStatus.INTERRUPTED

    fun canCancel(status: TripStatus): Boolean = status == TripStatus.PLANNED || status == TripStatus.BOARDING || status == TripStatus.INTERRUPTED

    /** Trip detail: the next step first, then pause / resume, then cancel (danger, last). */
    fun detailCommands(status: TripStatus): List<TripCommand> = listOfNotNull(
        nextAction(status),
        TripCommand.INTERRUPT.takeIf { canPause(status) },
        TripCommand.RESUME.takeIf { canResume(status) },
        TripCommand.CANCEL.takeIf { canCancel(status) },
    )

    fun statusKey(status: TripStatus): String = "tripStatus.${status.value}"

    /** planned / boarding green, on the way blue, interrupted warn, finished grey (the word says it too). */
    fun statusTone(status: TripStatus): Tone = when (status) {
        TripStatus.PLANNED, TripStatus.BOARDING -> Tone.OK
        TripStatus.IN_PROGRESS -> Tone.BLUE
        TripStatus.INTERRUPTED -> Tone.WARN
        else -> Tone.GRAY
    }

    fun isActive(status: TripStatus): Boolean =
        status == TripStatus.PLANNED || status == TripStatus.BOARDING || status == TripStatus.IN_PROGRESS || status == TripStatus.INTERRUPTED

    fun gpsEffect(command: TripCommand): GpsEffect = when (command) {
        TripCommand.START_BOARDING, TripCommand.DEPART -> GpsEffect.START
        TripCommand.COMPLETE, TripCommand.CANCEL -> GpsEffect.FINISH
        TripCommand.INTERRUPT, TripCommand.RESUME -> GpsEffect.NONE
    }

    /** Statuses in which the server accepts a writer session (`rules.PUBLISHABLE_TRIP_STATUSES`). */
    fun publishable(status: TripStatus): Boolean = status == TripStatus.BOARDING || status == TripStatus.IN_PROGRESS || status == TripStatus.INTERRUPTED

    /** The trip that should be publishing now: a running one, the earliest planned start first (web `trackableTrip`). */
    fun trackable(trips: List<TripDTO>): TripDTO? =
        trips.filter { publishable(it.status) }.minByOrNull { OrderRules.parseInstant(it.plannedStartAt) ?: Instant.MAX }

    /** Live trips first (soonest first), then the history (latest first). */
    fun ordered(trips: List<TripDTO>): List<TripDTO> {
        val (live, done) = trips.partition { isActive(it.status) }
        return live.sortedBy { OrderRules.parseInstant(it.plannedStartAt) ?: Instant.MAX } +
            done.sortedByDescending { OrderRules.parseInstant(it.plannedStartAt) ?: Instant.MIN }
    }

    /** "Toshkent → Samarqand": the first and the last stop. */
    fun routeTitle(trip: TripDTO, ru: Boolean): String {
        val first = trip.stops.minByOrNull { it.seq }?.stop
        val last = trip.stops.maxByOrNull { it.seq }?.stop
        fun name(stop: uz.elchi.app.api.generated.StopRefDTO?) = stop?.let { if (ru) it.nameRu ?: it.nameUz else it.nameUz } ?: "?"
        return "${name(first)} → ${name(last)}"
    }

    /** Planned and not yet past its booking cutoff: a trip an offer can be made from. */
    fun offerable(trip: TripDTO, now: Instant): Boolean =
        trip.status == TripStatus.PLANNED && (OrderRules.parseInstant(trip.bookingCutoffAt)?.isAfter(now) ?: false)

    // -- errors --------------------------------------------------------------------------------------------------

    /** `INVALID_STATE_TRANSITION {reason: boarding_window_not_open, opens_at}`: when the boarding window opens. */
    fun boardingOpensAt(error: Throwable): Instant? {
        val api = error as? ApiException ?: return null
        if (api.code != "INVALID_STATE_TRANSITION") return null
        val details = api.details as? JsonObject ?: return null
        if ((details["reason"] as? JsonPrimitive)?.contentOrNull != "boarding_window_not_open") return null
        return OrderRules.parseInstant((details["opens_at"] as? JsonPrimitive)?.contentOrNull)
    }

    /** After these the trip on screen is stale: read it again. */
    fun needsRefresh(error: Throwable): Boolean =
        (error as? ApiException)?.code in setOf("VERSION_CONFLICT", "TRIP_HAS_UNRESOLVED_BOOKINGS", "INVALID_STATE_TRANSITION")

    /** `VEHICLE_NOT_ELIGIBLE {field, requested, vehicle_limit}`: the form field that asks more than the car has. */
    fun vehicleLimitIssue(error: Throwable): TripFormIssue? {
        val api = error as? ApiException ?: return null
        if (api.code != "VEHICLE_NOT_ELIGIBLE") return null
        return when ((api.details as? JsonObject)?.get("field")?.let { (it as? JsonPrimitive)?.contentOrNull }) {
            "seat_capacity" -> TripFormIssue.SEATS
            "cargo_capacity_weight_g" -> TripFormIssue.CARGO_KG
            "cargo_capacity_volume_ml" -> TripFormIssue.CARGO_LITRES
            else -> null
        }
    }

    /** The vehicle limit the server named, in the form's unit (kg / litres / seats). */
    fun vehicleLimit(error: Throwable): Long? {
        val details = (error as? ApiException)?.details as? JsonObject ?: return null
        val limit = (details["vehicle_limit"] as? JsonPrimitive)?.contentOrNull?.toLongOrNull() ?: return null
        return when (vehicleLimitIssue(error)) {
            TripFormIssue.CARGO_KG, TripFormIssue.CARGO_LITRES -> limit / 1000
            else -> limit
        }
    }

    // -- add trip ------------------------------------------------------------------------------------------------

    fun approvedVehicles(vehicles: List<VehicleDTO>): List<VehicleDTO> = vehicles.filter { it.verificationStatus == "approved" }

    /** Only routes that pass [stopId] (the stop-name filter); all of them without one. */
    fun routesThrough(routes: List<RouteVersionDTO>, stopId: String?): List<RouteVersionDTO> =
        if (stopId == null) routes else routes.filter { route -> route.stops.any { it.stopId == stopId } }

    /** `308` (km, rounded). */
    fun km(meters: Long): String = ((meters + 500) / 1000).toString()

    /** `4,5` hours, one decimal, no trailing `,0`. */
    fun hours(seconds: Long): String {
        val tenths = (seconds * 10 + 1800) / 3600
        val whole = tenths / 10
        val rest = tenths % 10
        return if (rest == 0L) whole.toString() else "$whole,$rest"
    }

    /** The form's numbers prefilled from the car: all its seats, its full cargo room. */
    fun formFromVehicle(form: TripForm, vehicle: VehicleDTO): TripForm = form.copy(
        vehicleId = vehicle.id,
        seats = vehicle.seatCapacity.toString(),
        cargoKg = ((vehicle.cargoMaxWeightG ?: 0) / 1000).toString(),
        cargoLitres = ((vehicle.cargoMaxVolumeMl ?: 0) / 1000).toString(),
    )

    private fun count(text: String): Long? = text.trim().takeIf { it.isNotEmpty() && it.all(Char::isDigit) }?.toLongOrNull()

    /** What stops the form from being sent; cargo 0 is allowed (no parcel offers then). */
    fun issues(form: TripForm, vehicle: VehicleDTO?, route: RouteVersionDTO?, now: Instant): Set<TripFormIssue> {
        val out = mutableSetOf<TripFormIssue>()
        if (vehicle == null) out += TripFormIssue.VEHICLE
        if (route == null) out += TripFormIssue.ROUTE
        val departure = form.departure
        if (departure == null) out += TripFormIssue.DEPARTURE
        else if (!departure.atZone(ParcelRules.TASHKENT).toInstant().isAfter(now)) out += TripFormIssue.DEPARTURE_PAST
        val seats = count(form.seats)
        if (seats == null || seats < 1 || (vehicle != null && seats > vehicle.seatCapacity)) out += TripFormIssue.SEATS
        val kg = count(form.cargoKg)
        if (kg == null || (vehicle != null && kg * 1000 > (vehicle.cargoMaxWeightG ?: 0))) out += TripFormIssue.CARGO_KG
        val litres = count(form.cargoLitres)
        if (litres == null || (vehicle != null && litres * 1000 > (vehicle.cargoMaxVolumeMl ?: 0))) out += TripFormIssue.CARGO_LITRES
        return out
    }

    private fun iso(instant: Instant): String =
        instant.atZone(ParcelRules.TASHKENT).toOffsetDateTime().format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)

    /**
     * `POST /trips`: the route's stops in order (`seq` from 1, arrival = start + the route's cumulative time), the
     * end = start + the route's duration, the pilot detour budget (15 min / 5 km), pickup wait 10 min, dwell 5 min,
     * cutoff left to the server (= start), kg/litres in g/ml. Call only when [issues] is empty.
     */
    fun buildTripCreate(form: TripForm, vehicle: VehicleDTO, route: RouteVersionDTO): TripCreate {
        val start = requireNotNull(form.departure).withSecond(0).withNano(0).atZone(ParcelRules.TASHKENT).toInstant()
        val stops = route.stops.sortedBy { it.seq }.mapIndexed { index, stop ->
            TripStopInput(
                dwellMinutes = DWELL_MINUTES,
                plannedArrivalAt = iso(start.plusSeconds(stop.cumulativeDurationS)),
                seq = index + 1L,
                stopId = stop.stopId,
            )
        }
        return TripCreate(
            cargoCapacityVolumeMl = (count(form.cargoLitres) ?: 0) * 1000,
            cargoCapacityWeightG = (count(form.cargoKg) ?: 0) * 1000,
            maxDetourM = MAX_DETOUR_M,
            maxDetourMinutes = MAX_DETOUR_MINUTES,
            pickupWaitMinutes = PICKUP_WAIT_MINUTES,
            plannedEndAt = iso(start.plusSeconds(route.durationS)),
            plannedStartAt = iso(start),
            routeVersionId = route.id,
            seatCapacity = count(form.seats) ?: 0,
            stops = stops,
            vehicleId = vehicle.id,
        )
    }

    const val DWELL_MINUTES = 5L
    const val MAX_DETOUR_MINUTES = 15L
    const val MAX_DETOUR_M = 5_000L
    const val PICKUP_WAIT_MINUTES = 10L
}
