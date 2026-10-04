package uz.elchi.app.feature.driver

import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.DriverDocumentDTO
import uz.elchi.app.api.DriverProfileDTO
import uz.elchi.app.api.DriverProfileUpdate
import uz.elchi.app.api.DriverUser
import uz.elchi.app.api.generated.VehicleDTO
import uz.elchi.app.ui.theme.Tone

class DriverRulesTest {
    private fun profile(
        status: String = "new",
        name: String? = "Jasur Toshmatov",
        model: String? = null,
        color: String? = null,
        plate: String? = null,
        available: Boolean = false,
    ) = DriverProfileDTO(
        id = 6,
        user = DriverUser(20, "+998900001012", name),
        fullName = name,
        carModel = model,
        carColor = color,
        plateNumber = plate,
        verificationStatus = status,
        isAvailable = available,
    )

    private fun vehicle(plate: String = "01A452KA", kg: Long? = 20_000, ml: Long? = 100_000, status: String = "pending") = VehicleDTO(
        cargoMaxVolumeMl = ml,
        cargoMaxWeightG = kg,
        color = "Oq",
        createdAt = "2026-09-30T10:00:00Z",
        documentFileIds = emptyList(),
        id = "veh_1",
        makeModel = "Cobalt",
        plateMasked = "01 A ••• KA",
        plateNumber = plate,
        seatCapacity = 4,
        verificationStatus = status,
        version = 1,
    )

    private val lockedProfile = profile(status = "pending", model = "Cobalt", color = "Oq", plate = "01 A 452 KA")

    // -- status → label / tone / gate -------------------------------------------------------------------------

    @Test
    fun `every status reads as a sentence with its tone, never the raw code`() {
        assertEquals("app.driverVerification.new", DriverRules.statusKey(DriverStatus.NEW))
        assertEquals("app.driverVerification.pending", DriverRules.statusKey(DriverStatus.PENDING))
        assertEquals("app.driverVerification.blocked", DriverRules.statusKey(DriverStatus.BLOCKED))
        assertEquals("status.approved", DriverRules.statusKey(DriverStatus.APPROVED))
        assertEquals("status.rejected", DriverRules.statusKey(DriverStatus.REJECTED))
        assertEquals(Tone.WARN, DriverRules.statusTone(DriverStatus.NEW))
        assertEquals(Tone.WARN, DriverRules.statusTone(DriverStatus.PENDING))
        assertEquals(Tone.OK, DriverRules.statusTone(DriverStatus.APPROVED))
        assertEquals(Tone.ERR, DriverRules.statusTone(DriverStatus.REJECTED))
        assertEquals(Tone.ERR, DriverRules.statusTone(DriverStatus.BLOCKED))
    }

    @Test
    fun `an unknown status is not approved`() {
        assertEquals(DriverStatus.NEW, DriverStatus.from("suspended"))
        assertEquals(DriverStatus.NEW, DriverStatus.from(null))
        assertEquals(GateVariant.WAITING, DriverRules.gate(DriverStatus.from("suspended")))
    }

    @Test
    fun `the gate waits for new and pending, sends rejected and blocked to support, and opens when approved`() {
        assertEquals(GateVariant.WAITING, DriverRules.gate(DriverStatus.NEW))
        assertEquals(GateVariant.WAITING, DriverRules.gate(DriverStatus.PENDING))
        assertEquals(GateVariant.DECIDED, DriverRules.gate(DriverStatus.REJECTED))
        assertEquals(GateVariant.DECIDED, DriverRules.gate(DriverStatus.BLOCKED))
        assertEquals(GateVariant.NONE, DriverRules.gate(DriverStatus.APPROVED))
        assertTrue(DriverRules.showsSupport(DriverStatus.BLOCKED))
        assertFalse(DriverRules.showsSupport(DriverStatus.PENDING))
    }

    @Test
    fun `home says complete the profile until approved`() {
        assertEquals("driverHome.completeProfileTitle", DriverRules.homeTitleKey(DriverStatus.PENDING))
        assertEquals("clientProfile.home", DriverRules.homeTitleKey(DriverStatus.APPROVED))
        assertEquals("driverHome.onboardingHint", DriverRules.homeHintKey(DriverStatus.REJECTED))
        assertEquals("driverHome.approvedHint", DriverRules.homeHintKey(DriverStatus.APPROVED))
    }

    // -- availability -----------------------------------------------------------------------------------------

    @Test
    fun `only an approved driver can switch on, anyone can switch off`() {
        assertTrue(DriverRules.availabilityEnabled(DriverStatus.APPROVED, on = false))
        assertTrue(DriverRules.availabilityEnabled(DriverStatus.APPROVED, on = true))
        assertFalse(DriverRules.availabilityEnabled(DriverStatus.PENDING, on = false))
        assertFalse(DriverRules.availabilityEnabled(DriverStatus.NEW, on = false))
        // Blocked while available: the switch still turns it off.
        assertTrue(DriverRules.availabilityEnabled(DriverStatus.BLOCKED, on = true))
    }

    @Test
    fun `the switch explains itself`() {
        assertEquals("driverHome.availabilityLocked", DriverRules.availabilitySubtitleKey(DriverStatus.PENDING, on = false))
        assertEquals("driver.home.availableOn", DriverRules.availabilitySubtitleKey(DriverStatus.APPROVED, on = true))
        assertEquals("driver.home.availableOff", DriverRules.availabilitySubtitleKey(DriverStatus.APPROVED, on = false))
        assertEquals("driver.home.availableOn", DriverRules.availabilitySubtitleKey(DriverStatus.BLOCKED, on = true))
    }

    // -- lock and values --------------------------------------------------------------------------------------

    @Test
    fun `the car locks as soon as the profile holds a plate, approved or not`() {
        assertFalse(DriverRules.vehicleLocked(profile()))
        assertFalse(DriverRules.vehicleLocked(profile(plate = "  ")))
        assertFalse(DriverRules.vehicleLocked(null))
        assertTrue(DriverRules.vehicleLocked(lockedProfile))
        assertTrue(DriverRules.vehicleLocked(profile(status = "new", plate = "01A452KA")))
        assertFalse(DriverRules.capacityLocked(emptyList()))
        assertTrue(DriverRules.capacityLocked(listOf(vehicle())))
    }

    @Test
    fun `locked values come from the profile and the v2 vehicle, grams and millilitres as kg and litres`() {
        val form = DriverRules.formFrom(lockedProfile, listOf(vehicle(kg = 20_500, ml = 100_000)), DriverForm(carModel = "typed", seats = "7"))
        assertEquals("Jasur Toshmatov", form.fullName)
        assertEquals("Cobalt", form.carModel)
        assertEquals("Oq", form.carColor)
        assertEquals("01 A 452 KA", form.plate)
        assertEquals("4", form.seats)
        assertEquals("20.5", form.cargoKg)
        assertEquals("100", form.cargoLitres)
    }

    @Test
    fun `without a vehicle the typed capacity stays and a missing cargo value stays empty`() {
        val typed = DriverForm(seats = "3", cargoKg = "15", cargoLitres = "")
        val form = DriverRules.formFrom(lockedProfile, emptyList(), typed)
        assertEquals("3", form.seats)
        assertEquals("15", form.cargoKg)
        assertEquals("", DriverRules.formFrom(lockedProfile, listOf(vehicle(kg = null, ml = null))).cargoKg)
        assertEquals("", DriverRules.thousandths(null))
        assertEquals("20", DriverRules.thousandths(20_000))
    }

    @Test
    fun `the vehicle of this profile is the one with its plate`() {
        val other = vehicle(plate = "90D001AA")
        val own = vehicle(plate = "01A452KA")
        assertEquals(own, DriverRules.ownVehicle(lockedProfile, listOf(other, own)))
        assertEquals(other, DriverRules.ownVehicle(profile(), listOf(other, own)))
        assertNull(DriverRules.ownVehicle(lockedProfile, emptyList()))
    }

    @Test
    fun `plates are compared without spaces and in capitals`() {
        assertEquals("01A123AA", DriverRules.normalizePlate(" 01 a 123\taa "))
        assertEquals("", DriverRules.normalizePlate("   "))
    }

    // -- validation and the save sequence ---------------------------------------------------------------------

    @Test
    fun `first save needs the name, the car, 1 to 8 seats and both cargo numbers, 0 included`() {
        val empty = DriverRules.issues(DriverForm(seats = ""), profileLocked = false, capacityLocked = false)
        assertEquals(
            setOf(FormIssue.NAME, FormIssue.MODEL, FormIssue.COLOR, FormIssue.PLATE, FormIssue.SEATS, FormIssue.CARGO_KG, FormIssue.CARGO_LITRES),
            empty,
        )
        val filled = DriverForm("Jasur", "Cobalt", "Oq", "01 A 123 AA", "4", "0", "0")
        assertEquals(emptySet<FormIssue>(), DriverRules.issues(filled, false, false))
        assertEquals(setOf(FormIssue.SEATS), DriverRules.issues(filled.copy(seats = "9"), false, false))
        assertEquals(setOf(FormIssue.SEATS), DriverRules.issues(filled.copy(seats = "0"), false, false))
        assertEquals(setOf(FormIssue.CARGO_KG, FormIssue.CARGO_LITRES), DriverRules.issues(filled.copy(cargoKg = "", cargoLitres = "x"), false, false))
        assertEquals(setOf(FormIssue.PLATE), DriverRules.issues(filled.copy(plate = "   "), false, false))
        // Locked: only the name is checked.
        assertEquals(setOf(FormIssue.NAME), DriverRules.issues(DriverForm(), profileLocked = true, capacityLocked = true))
    }

    @Test
    fun `the first save sends the whole car to v1, then registers the same car on v2`() {
        val form = DriverForm(" Jasur ", " Cobalt ", "Oq", " 01 a 123 aa ", "4", "20", "100")
        val plan = DriverRules.savePlan(form, profile(), emptyList())
        assertEquals(DriverProfileUpdate("Jasur", "Cobalt", "Oq", "01 a 123 aa"), plan.patch)
        val vehicle = plan.vehicle!!
        assertEquals("01A123AA", vehicle.plateNumber)
        assertEquals("Cobalt", vehicle.makeModel)
        assertEquals("Oq", vehicle.color)
        assertEquals(4L, vehicle.seatCapacity)
        assertEquals(20_000L, vehicle.cargoMaxWeightG)
        assertEquals(100_000L, vehicle.cargoMaxVolumeMl)
    }

    @Test
    fun `cargo 0 means no parcels and is sent as null`() {
        val plan = DriverRules.savePlan(DriverForm("Jasur", "Cobalt", "Oq", "01A123AA", "4", "0", "0"), profile(), emptyList())
        val vehicle = plan.vehicle!!
        assertNull(vehicle.cargoMaxWeightG)
        assertNull(vehicle.cargoMaxVolumeMl)
    }

    @Test
    fun `a retry after the v2 call failed sends only the missing vehicle, from the locked profile`() {
        // v1 stored the car; the form now shows the profile's values and the capacity the person typed.
        val form = DriverRules.formFrom(lockedProfile, emptyList(), DriverForm(seats = "4", cargoKg = "20", cargoLitres = "100"))
        val plan = DriverRules.savePlan(form, lockedProfile, emptyList())
        assertNull(plan.patch)
        val vehicle = plan.vehicle!!
        assertEquals("01A452KA", vehicle.plateNumber)
        assertEquals("Cobalt", vehicle.makeModel)
        assertEquals(20_000L, vehicle.cargoMaxWeightG)
    }

    @Test
    fun `a locked profile sends the name only, and only when it changed`() {
        val form = DriverRules.formFrom(lockedProfile, listOf(vehicle()))
        assertEquals(SavePlan(null, null), DriverRules.savePlan(form, lockedProfile, listOf(vehicle())))
        val renamed = DriverRules.savePlan(form.copy(fullName = "Jasur T."), lockedProfile, listOf(vehicle()))
        assertEquals(DriverProfileUpdate(fullName = "Jasur T."), renamed.patch)
        assertNull(renamed.vehicle)
    }

    @Test
    fun `no second vehicle is created from the form`() {
        val form = DriverForm("Jasur", "Cobalt", "Oq", "01A123AA", "4", "", "")
        assertNull(DriverRules.savePlan(form, profile(), listOf(vehicle(plate = "90D001AA"))).vehicle)
    }

    // -- documents --------------------------------------------------------------------------------------------

    private fun doc(type: String, status: String, reason: String? = null, id: Long = 1) =
        DriverDocumentDTO(id, type, "/api/v1/files/k?sig=1", status, reason)

    @Test
    fun `one row per type in order, a missing type is missing, and N counts the types sent`() {
        val rows = DriverRules.docRows(
            listOf(
                doc("passport", "approved"),
                doc("license", "rejected", "rasm xira, matn o'qilmaydi"),
                doc("selfie", "pending"),
                doc("unknown_type", "pending"),
            ),
        )
        assertEquals(DocType.entries.toList(), rows.map { it.type })
        assertEquals(
            listOf(DocState.APPROVED, DocState.PENDING, DocState.REJECTED, DocState.MISSING, DocState.MISSING),
            rows.map { it.state },
        )
        assertEquals("rasm xira, matn o'qilmaydi", rows[2].reason)
        assertNull(rows[0].reason)
        assertNull(rows[3].fileUrl)
        assertEquals(3, DriverRules.submitted(rows))
        assertEquals(0, DriverRules.submitted(DriverRules.docRows(emptyList())))
    }

    @Test
    fun `a later row of a type wins and a reason only shows on a rejected row`() {
        val rows = DriverRules.docRows(listOf(doc("passport", "rejected", "old", 1), doc("passport", "pending", "old", 2)))
        assertEquals(DocState.PENDING, rows[0].state)
        assertNull(rows[0].reason)
    }

    @Test
    fun `document tones`() {
        assertEquals(Tone.OK, DriverRules.docTone(DocState.APPROVED))
        assertEquals(Tone.WARN, DriverRules.docTone(DocState.PENDING))
        assertEquals(Tone.ERR, DriverRules.docTone(DocState.REJECTED))
        assertEquals(Tone.GRAY, DriverRules.docTone(DocState.MISSING))
        assertEquals(DocState.PENDING, DriverRules.docState("in_review"))
    }

    @Test
    fun `selfie and car photo take images up to 5 MB, the others also a PDF up to 10 MB`() {
        assertTrue(DriverRules.mimeAllowed(DocType.SELFIE, "image/jpeg"))
        assertTrue(DriverRules.mimeAllowed(DocType.CAR_PHOTO, "image/webp"))
        assertFalse(DriverRules.mimeAllowed(DocType.SELFIE, "application/pdf"))
        assertFalse(DriverRules.mimeAllowed(DocType.CAR_PHOTO, "application/pdf"))
        assertTrue(DriverRules.mimeAllowed(DocType.PASSPORT, "application/pdf"))
        assertTrue(DriverRules.mimeAllowed(DocType.LICENSE, "image/png"))
        assertTrue(DriverRules.mimeAllowed(DocType.CAR_DOCUMENT, "application/pdf"))
        assertFalse(DriverRules.mimeAllowed(DocType.PASSPORT, "image/heic"))
        assertFalse(DriverRules.mimeAllowed(DocType.PASSPORT, null))

        val mb = 1024L * 1024L
        assertTrue(DriverRules.sizeAllowed(DocType.SELFIE, 5 * mb))
        assertFalse(DriverRules.sizeAllowed(DocType.SELFIE, 5 * mb + 1))
        assertTrue(DriverRules.sizeAllowed(DocType.PASSPORT, 10 * mb))
        assertFalse(DriverRules.sizeAllowed(DocType.PASSPORT, 10 * mb + 1))
        assertFalse(DriverRules.sizeAllowed(DocType.PASSPORT, 0))
        assertEquals("driver.docs.fileHintImage", DriverRules.fileHintKey(DocType.CAR_PHOTO))
        assertEquals("driver.docs.fileHintImageOrPdf", DriverRules.fileHintKey(DocType.CAR_DOCUMENT))
    }

    // -- errors -----------------------------------------------------------------------------------------------

    @Test
    fun `driver codes map to driver sentences, the rest to the generic one`() {
        assertEquals("driver.error.plateTaken", DriverRules.errorKey(ApiException(409, "PLATE_NUMBER_ALREADY_EXISTS", "x")))
        val v2Plate = ApiException(422, "VALIDATION_ERROR", "plate_number is already registered", buildJsonObject { put("field", "plate_number") })
        assertEquals("driver.error.plateTaken", DriverRules.errorKey(v2Plate))
        assertNull(DriverRules.errorKey(ApiException(422, "VALIDATION_ERROR", "x", buildJsonObject { put("field", "seat_capacity") })))
        assertEquals("driver.error.blocked", DriverRules.errorKey(ApiException(403, "DRIVER_BLOCKED", "x")))
        assertEquals("driver.error.fileTooLarge", DriverRules.errorKey(ApiException(413, "FILE_TOO_LARGE", "x")))
        // These have their own `error.<CODE>` sentence.
        assertNull(DriverRules.errorKey(ApiException(403, "DRIVER_VEHICLE_LOCKED", "x")))
        assertNull(DriverRules.errorKey(ApiException(400, "DRIVER_NOT_APPROVED", "x")))
        assertNull(DriverRules.errorKey(IllegalStateException()))
    }
}
