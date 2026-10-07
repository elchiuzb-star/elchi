package uz.elchi.app.feature.driver

import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.generated.TripStatus
import uz.elchi.app.ui.theme.Tone
import java.time.Instant
import java.time.LocalDateTime

class TripRulesTest {
    private val now: Instant = Instant.parse("2026-10-01T06:00:00Z") // 11:00 in Tashkent

    @Test
    fun `next action follows the state machine and finished trips have none`() {
        assertEquals(TripCommand.START_BOARDING, TripRules.nextAction(TripStatus.PLANNED))
        assertEquals(TripCommand.DEPART, TripRules.nextAction(TripStatus.BOARDING))
        assertEquals(TripCommand.COMPLETE, TripRules.nextAction(TripStatus.IN_PROGRESS))
        assertNull(TripRules.nextAction(TripStatus.INTERRUPTED))
        assertNull(TripRules.nextAction(TripStatus.COMPLETED))
        assertNull(TripRules.nextAction(TripStatus.CANCELLED))
        assertNull(TripRules.nextAction(TripStatus.UNKNOWN))
    }

    @Test
    fun `pause resume and cancel only where the server allows them`() {
        assertEquals(listOf(TripCommand.START_BOARDING, TripCommand.CANCEL), TripRules.detailCommands(TripStatus.PLANNED))
        assertEquals(listOf(TripCommand.DEPART, TripCommand.INTERRUPT, TripCommand.CANCEL), TripRules.detailCommands(TripStatus.BOARDING))
        assertEquals(listOf(TripCommand.COMPLETE, TripCommand.INTERRUPT), TripRules.detailCommands(TripStatus.IN_PROGRESS))
        assertEquals(listOf(TripCommand.RESUME, TripCommand.CANCEL), TripRules.detailCommands(TripStatus.INTERRUPTED))
        assertEquals(emptyList<TripCommand>(), TripRules.detailCommands(TripStatus.COMPLETED))
        assertTrue(TripCommand.INTERRUPT.needsReason && TripCommand.RESUME.needsReason && TripCommand.CANCEL.needsReason)
        assertFalse(TripCommand.START_BOARDING.needsReason)
    }

    @Test
    fun `status tones and ordering put live trips first`() {
        assertEquals(Tone.BLUE, TripRules.statusTone(TripStatus.PLANNED))
        assertEquals(Tone.OK, TripRules.statusTone(TripStatus.BOARDING))
        assertEquals(Tone.OK, TripRules.statusTone(TripStatus.IN_PROGRESS))
        assertEquals(Tone.ERR, TripRules.statusTone(TripStatus.CANCELLED))
        assertEquals(Tone.WARN, TripRules.statusTone(TripStatus.INTERRUPTED))
        assertEquals(Tone.GRAY, TripRules.statusTone(TripStatus.COMPLETED))
        val old = S08.trip("a", TripStatus.COMPLETED, start = "2026-09-20T04:00:00Z")
        val older = S08.trip("b", TripStatus.CANCELLED, start = "2026-09-10T04:00:00Z")
        val later = S08.trip("c", TripStatus.PLANNED, start = "2026-10-05T04:00:00Z")
        val sooner = S08.trip("d", TripStatus.BOARDING, start = "2026-10-01T06:30:00Z")
        assertEquals(listOf("d", "c", "a", "b"), TripRules.ordered(listOf(older, later, old, sooner)).map { it.id })
    }

    @Test
    fun `boarding window error gives the opening time, other errors do not`() {
        val tooEarly = ApiException(409, "INVALID_STATE_TRANSITION", "x", buildJsonObject { put("reason", "boarding_window_not_open"); put("opens_at", "2026-10-02T03:00:00+00:00") })
        assertEquals(Instant.parse("2026-10-02T03:00:00Z"), TripRules.boardingOpensAt(tooEarly))
        assertEquals("08:00", DriverTime.clock(TripRules.boardingOpensAt(tooEarly)!!))
        assertNull(TripRules.boardingOpensAt(ApiException(409, "INVALID_STATE_TRANSITION", "x", buildJsonObject { put("reason", "other") })))
        assertNull(TripRules.boardingOpensAt(ApiException(409, "VERSION_CONFLICT", "x")))
        assertTrue(TripRules.needsRefresh(ApiException(409, "VERSION_CONFLICT", "x")))
        assertTrue(TripRules.needsRefresh(ApiException(409, "TRIP_HAS_UNRESOLVED_BOOKINGS", "x")))
        assertFalse(TripRules.needsRefresh(ApiException(0, ApiException.NETWORK, "x")))
    }

    @Test
    fun `vehicle limit error marks the field and gives the limit in the form's unit`() {
        val kg = ApiException(409, "VEHICLE_NOT_ELIGIBLE", "x", buildJsonObject { put("field", "cargo_capacity_weight_g"); put("requested", 90_000); put("vehicle_limit", 80_000) })
        assertEquals(TripFormIssue.CARGO_KG, TripRules.vehicleLimitIssue(kg))
        assertEquals(80L, TripRules.vehicleLimit(kg))
        val seats = ApiException(409, "VEHICLE_NOT_ELIGIBLE", "x", buildJsonObject { put("field", "seat_capacity"); put("requested", 6); put("vehicle_limit", 4) })
        assertEquals(TripFormIssue.SEATS, TripRules.vehicleLimitIssue(seats))
        assertEquals(4L, TripRules.vehicleLimit(seats))
        assertNull(TripRules.vehicleLimitIssue(ApiException(409, "VEHICLE_NOT_ELIGIBLE", "x", buildJsonObject { put("reason", "vehicle_not_approved") })))
    }

    @Test
    fun `route labels and approved cars`() {
        assertEquals("512", TripRules.km(512_463))
        assertEquals("564", TripRules.km(563_607))
        assertEquals("8,5", TripRules.hours(30_748))
        assertEquals("4", TripRules.hours(14_400))
        assertEquals(listOf("veh_ok"), TripRules.approvedVehicles(listOf(S08.vehicle("pending", id = "veh_p"), S08.vehicle(id = "veh_ok"))).map { it.id })
    }

    @Test
    fun `form prefills from the car and checks its limits and the future`() {
        val car = S08.vehicle(seats = 4, kg = 80_000, ml = 400_000)
        val form = TripRules.formFromVehicle(TripForm(), car)
        assertEquals("4", form.seats)
        assertEquals("80", form.cargoKg)
        assertEquals("400", form.cargoLitres)
        val route = S08.route()
        val ok = form.copy(routeId = route.id, departure = LocalDateTime.of(2026, 10, 2, 7, 30))
        assertEquals(emptySet<TripFormIssue>(), TripRules.issues(ok, car, route, now))
        assertEquals(setOf(TripFormIssue.DEPARTURE_PAST), TripRules.issues(ok.copy(departure = LocalDateTime.of(2026, 10, 1, 10, 0)), car, route, now))
        assertEquals(setOf(TripFormIssue.SEATS, TripFormIssue.CARGO_KG), TripRules.issues(ok.copy(seats = "5", cargoKg = "81"), car, route, now))
        // Cargo 0 is a trip without parcel offers, not an error; seats 0 is.
        assertEquals(setOf(TripFormIssue.SEATS), TripRules.issues(ok.copy(seats = "0", cargoKg = "0", cargoLitres = "0"), car, route, now))
        assertEquals(setOf(TripFormIssue.VEHICLE, TripFormIssue.ROUTE, TripFormIssue.DEPARTURE), TripRules.issues(TripForm(seats = "1", cargoKg = "0", cargoLitres = "0"), null, null, now))
    }

    @Test
    fun `trip body is the route version without stops (ADR-0028), times from the route, units in g and ml`() {
        val car = S08.vehicle()
        val route = S08.route()
        val form = TripRules.formFromVehicle(TripForm(), car).copy(seats = "3", cargoKg = "20", cargoLitres = "100", departure = LocalDateTime.of(2026, 10, 2, 7, 30, 41))
        val body = TripRules.buildTripCreate(form, car, route)
        assertEquals("2026-10-02T07:30:00+05:00", body.plannedStartAt)
        assertEquals("2026-10-02T16:02:28+05:00", body.plannedEndAt) // + 30 748 s
        assertEquals("rtv_1", body.routeVersionId)
        // The form has no stretch: the server takes the whole road.
        assertNull(body.routeStartM)
        assertNull(body.routeEndM)
        val json = uz.elchi.app.api.ElchiJson.encodeToString(uz.elchi.app.api.generated.TripCreate.serializer(), body)
        assertFalse(json, "stops" in json)
        assertEquals(3L, body.seatCapacity)
        assertEquals(20_000L, body.cargoCapacityWeightG)
        assertEquals(100_000L, body.cargoCapacityVolumeMl)
        assertEquals(15L, body.maxDetourMinutes)
        assertEquals(5_000L, body.maxDetourM)
        assertEquals(10L, body.pickupWaitMinutes)
        assertNull(body.bookingCutoffAt) // = start, the server's default
        assertEquals("veh_1", body.vehicleId)
        assertEquals("rtv_1", body.routeVersionId)
    }

    @Test
    fun `offerable means planned and before the cutoff`() {
        assertTrue(TripRules.offerable(S08.trip(cutoff = "2026-10-02T04:00:00Z"), now))
        assertFalse(TripRules.offerable(S08.trip(cutoff = "2026-10-01T05:00:00Z"), now))
        assertFalse(TripRules.offerable(S08.trip(status = TripStatus.BOARDING), now))
    }

    @Test
    fun `boarding opening time names the day only when it is not today`() {
        val opens = Instant.parse("2026-10-02T04:00:00Z") // 09:00 on 2 October in Tashkent
        assertEquals("02.10, 09:00", DriverTime.clockOrDay(opens, now))
        assertEquals("09:00", DriverTime.clockOrDay(opens, Instant.parse("2026-10-02T01:00:00Z")))
        assertEquals("02.10, 09:00 - 18:00", DriverTime.range(opens, Instant.parse("2026-10-02T13:00:00Z")))
    }

    // -- ADR-0028: trips without stops ----------------------------------------------------------------------------

    @Test
    fun `a trip is named by the direction it serves, else by its times`() {
        val trip = S08.trip("trp_9")
        val end = { region: String, district: String? -> uz.elchi.app.api.generated.DirectionEndDTO(regionId = "r", regionNameUz = region, districtId = district?.let { "d" }, districtNameUz = district) }
        val direction = uz.elchi.app.api.generated.DriverDirectionDTO(
            activeTrip = uz.elchi.app.api.generated.DirectionTripRefDTO(id = "trp_9", plannedEndAt = trip.plannedEndAt, plannedStartAt = trip.plannedStartAt, seatsBooked = 0, status = TripStatus.PLANNED),
            cargoCapacityVolumeMl = 0, cargoCapacityWeightG = 0, createdAt = "2026-10-01T06:00:00Z",
            destination = end("Samarqand viloyati", "Samarqand"), id = "drd_1", origin = end("Toshkent shahri", null), seatCapacity = 4,
            status = "active", updatedAt = "2026-10-01T06:00:00Z", vehicleId = "veh_1", version = 1,
        )
        assertEquals(direction, TripRules.directionOf("trp_9", listOf(direction)))
        assertNull(TripRules.directionOf("trp_other", listOf(direction)))
        assertEquals("Toshkent shahri → Samarqand", TripRules.routeTitle(trip, direction, ru = false))
        assertEquals("02.10, 09:00 → 02.10, 17:30", TripRules.routeTitle(trip, null, ru = false))
    }

    @Test
    fun `places and stretches replace the stop ladder`() {
        val point = uz.elchi.app.api.generated.PointEndDTO(address = "O'zbekiston, Samarqand, Registon", district = uz.elchi.app.api.generated.DistrictRefDTO("dst_s", "Samarqand"), lat = 39.6, lng = 66.9)
        assertEquals("Samarqand, Registon", TripRules.placeName(point))
        assertEquals("Samarqand", TripRules.placeName(point.copy(address = " ")))
        assertNull(TripRules.placeName(null))
        val item = uz.elchi.app.api.generated.ManifestItemDTO(bookingId = "bkg_1", clientFirstName = "Ali", serviceStatus = "confirmed", serviceType = uz.elchi.app.api.generated.ServiceType.PARCEL)
        fun place(seq: Long, pickups: Int, dropoffs: Int) = uz.elchi.app.api.generated.ManifestPlaceDTO(
            dropoffs = List(dropoffs) { item }, pickups = List(pickups) { item }, plannedArrivalAt = "2026-10-02T04:00:00Z", point = point, seq = seq,
        )
        assertEquals(listOf(1L, 3L), TripRules.ladderPlaces(listOf(place(3, 0, 1), place(2, 0, 0), place(1, 1, 0))).map { it.seq })
        assertEquals(0L, TripRules.kmAlong(1_000, 5_000))
        assertEquals(12L, TripRules.kmAlong(17_400, 5_000))
    }

    // -- Safar v3 §4 ------------------------------------------------------------------------------------------------

    private fun stretch(from: Long, to: Long, seats: Long, kgG: Long = 20_000) = uz.elchi.app.api.generated.StretchAvailabilityDTO(
        baggageRemainingMl = 0, cargoRemainingVolumeMl = 100_000, cargoRemainingWeightG = kgG, fromM = from, seatsRemaining = seats, toM = to,
    )

    private fun place(seq: Long, address: String?) = uz.elchi.app.api.generated.ManifestPlaceDTO(
        dropoffs = emptyList(), pickups = emptyList(), plannedArrivalAt = "2026-10-02T05:00:00Z",
        point = address?.let { uz.elchi.app.api.generated.PointEndDTO(address = it, lat = 41.0, lng = 69.0) }, seq = seq,
    )

    @Test
    fun `an empty trip shows one whole-road row with its own capacity`() {
        val rows = TripRules.stretchRows(S08.trip(), emptyList())
        assertEquals(1, rows.size)
        assertNull(rows.single().fromKm)
        assertEquals(3L, rows.single().seats)
        assertEquals(20_000L, rows.single().weightG)
    }

    @Test
    fun `zero-length stretches fold into a neighbour and never print a-a km`() {
        val rows = TripRules.stretchRows(
            S08.trip(),
            listOf(stretch(0, 200, seats = 3), stretch(200, 120_000, seats = 2), stretch(120_000, 120_300, seats = 1), stretch(120_300, 300_000, seats = 3)),
        )
        assertEquals(2, rows.size)
        assertEquals(0L, rows[0].fromKm)
        assertEquals(120L, rows[0].toKm)
        // A short piece joins the stretch before it (the first one joins the next); the smaller remainder binds.
        assertEquals(1L, rows[0].seats)
        assertEquals(120L, rows[1].fromKm)
        assertEquals(300L, rows[1].toKm)
        assertEquals(3L, rows[1].seats)
        assertTrue(rows.none { it.fromKm == it.toKm })
    }

    @Test
    fun `one stretch left is the whole road`() {
        val rows = TripRules.stretchRows(S08.trip(), listOf(stretch(0, 300, seats = 2), stretch(300, 400, seats = 3)))
        assertEquals(1, rows.size)
        assertNull(rows.single().fromKm)
        assertEquals(2L, rows.single().seats)
    }

    @Test
    fun `the detail title names the first and last client place, else nothing`() {
        assertNull(TripRules.detailTitle(null, emptyList(), ru = false))
        assertNull(TripRules.detailTitle(null, listOf(place(1, null)), ru = false))
        assertEquals("Chilonzor 5", TripRules.detailTitle(null, listOf(place(1, "Chilonzor 5")), ru = false))
        assertEquals(
            "Chilonzor 5 → Samarqand, Registon",
            TripRules.detailTitle(null, listOf(place(3, "Samarqand, Registon"), place(1, "Chilonzor 5"), place(2, "Guliston")), ru = false),
        )
    }
}
