package uz.elchi.app.feature.driver

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.api.DriverProfileDTO
import uz.elchi.app.api.DriverUser
import uz.elchi.app.api.generated.VehicleDTO
import uz.elchi.app.ui.theme.Tone

/** Design 06 (driver registration): the derived status, the checklist, the lock dialog, cargo 0, upload rules. */
class Design06RulesTest {
    private fun profile(status: String = "new", plate: String? = null) = DriverProfileDTO(
        id = 6,
        user = DriverUser(20, "+998900002001", "Jasur"),
        fullName = "Jasur",
        carModel = plate?.let { "Cobalt" },
        carColor = plate?.let { "Oq" },
        plateNumber = plate,
        verificationStatus = status,
        isAvailable = false,
    )

    private val vehicle = VehicleDTO(
        cargoMaxVolumeMl = null,
        cargoMaxWeightG = null,
        color = "Oq",
        createdAt = "2026-10-03T10:00:00Z",
        documentFileIds = emptyList(),
        id = "veh_1",
        makeModel = "Cobalt",
        plateMasked = "01****KA",
        plateNumber = "01A452KA",
        seatCapacity = 4,
        verificationStatus = "pending",
        version = 1,
    )

    private fun rows(vararg states: DocState) = DocType.entries.mapIndexed { i, type ->
        DocRow(type, states.getOrElse(i) { DocState.MISSING }, null, null)
    }

    private val allSent = rows(DocState.PENDING, DocState.PENDING, DocState.APPROVED, DocState.PENDING, DocState.PENDING)

    // -- derived status ---------------------------------------------------------------------------------------

    @Test
    fun `pending with one document is still incomplete, not under review`() {
        // The server flips new -> pending on the first upload.
        assertEquals(VerifyState.INCOMPLETE, DriverRules.verifyState(DriverStatus.PENDING, profileDone = true, rows(DocState.PENDING)))
        assertEquals(VerifyState.INCOMPLETE, DriverRules.verifyState(DriverStatus.NEW, profileDone = false, rows()))
    }

    @Test
    fun `under review needs the car stored and all five sent with none rejected`() {
        assertEquals(VerifyState.REVIEW, DriverRules.verifyState(DriverStatus.PENDING, profileDone = true, allSent))
        assertEquals(VerifyState.INCOMPLETE, DriverRules.verifyState(DriverStatus.PENDING, profileDone = false, allSent))
        val oneRejected = rows(DocState.PENDING, DocState.REJECTED, DocState.PENDING, DocState.PENDING, DocState.PENDING)
        assertEquals(VerifyState.INCOMPLETE, DriverRules.verifyState(DriverStatus.PENDING, profileDone = true, oneRejected))
    }

    @Test
    fun `approved, rejected and blocked come from the server whatever the documents say`() {
        assertEquals(VerifyState.APPROVED, DriverRules.verifyState(DriverStatus.APPROVED, false, rows()))
        assertEquals(VerifyState.REJECTED, DriverRules.verifyState(DriverStatus.REJECTED, true, allSent))
        assertEquals(VerifyState.BLOCKED, DriverRules.verifyState(DriverStatus.BLOCKED, true, allSent))
    }

    @Test
    fun `documents not read fall back to the server word`() {
        assertEquals(VerifyState.REVIEW, DriverRules.verifyState(DriverStatus.PENDING, profileDone = true, rows = null))
        assertEquals(VerifyState.INCOMPLETE, DriverRules.verifyState(DriverStatus.NEW, profileDone = true, rows = null))
    }

    @Test
    fun `each state has its label, tone and hint`() {
        assertEquals("driver.verify.incomplete", VerifyState.INCOMPLETE.labelKey)
        assertEquals("driverHome.onboardingHint", VerifyState.INCOMPLETE.hintKey)
        assertEquals("app.driverVerification.pending", VerifyState.REVIEW.labelKey)
        assertEquals("driver.verify.reviewHint", VerifyState.REVIEW.hintKey)
        assertEquals("status.approved", VerifyState.APPROVED.labelKey)
        assertEquals("driverHome.approvedHint", VerifyState.APPROVED.hintKey)
        assertEquals("app.driverGate.decided", VerifyState.REJECTED.hintKey)
        assertEquals("app.driverVerification.blocked", VerifyState.BLOCKED.labelKey)
        assertEquals(Tone.WARN, VerifyState.REVIEW.tone)
        assertEquals(Tone.ERR, VerifyState.BLOCKED.tone)
        assertEquals(Tone.OK, VerifyState.APPROVED.tone)
    }

    @Test
    fun `step 1 needs the v1 lock and, once read, the v2 vehicle`() {
        assertFalse(DriverRules.profileDone(profile(), listOf(vehicle)))
        assertTrue(DriverRules.profileDone(profile(plate = "01 A 452 KA"), listOf(vehicle)))
        assertFalse(DriverRules.profileDone(profile(plate = "01 A 452 KA"), emptyList()))
        assertTrue(DriverRules.profileDone(profile(plate = "01 A 452 KA"), null))
        assertEquals("driverHome.viewProfile", DriverRules.profileButtonKey(true))
        assertEquals("driverHome.completeProfile", DriverRules.profileButtonKey(false))
    }

    // -- checklist --------------------------------------------------------------------------------------------

    @Test
    fun `a fresh driver sees three open steps`() {
        val list = DriverRules.checklist(profile(), emptyList(), rows(), VerifyState.INCOMPLETE)
        assertEquals(ChecklistStep(StepMark.OPEN, "driver.checklist.profileTodo"), list.profile)
        assertEquals(ChecklistStep(StepMark.OPEN, "driver.checklist.docsCount", mapOf("submitted" to 0, "total" to 5)), list.documents)
        assertEquals(ChecklistStep(StepMark.OPEN, "driver.checklist.reviewAfter"), list.review)
    }

    @Test
    fun `under review the first two are ticked and the third waits`() {
        val p = profile("pending", "01 A 452 KA")
        val list = DriverRules.checklist(p, listOf(vehicle), allSent, VerifyState.REVIEW)
        assertEquals(StepMark.DONE, list.profile.mark)
        assertEquals("Cobalt · 01 A 452 KA", list.profile.subText)
        assertEquals(StepMark.DONE, list.documents.mark)
        assertEquals(ChecklistStep(StepMark.OPEN, "status.pending"), list.review)
    }

    @Test
    fun `rejected documents are counted and shown red`() {
        val docs = rows(DocState.REJECTED, DocState.PENDING, DocState.REJECTED, DocState.PENDING, DocState.PENDING)
        val list = DriverRules.checklist(profile("pending", "01A452KA"), listOf(vehicle), docs, VerifyState.INCOMPLETE)
        assertEquals(ChecklistStep(StepMark.FAILED, "driver.checklist.docsRejected", mapOf("count" to 2), alert = true), list.documents)
    }

    @Test
    fun `a rejected or blocked account crosses step 3`() {
        val p = profile("rejected", "01A452KA")
        assertEquals(ChecklistStep(StepMark.FAILED, "status.rejected", alert = true), DriverRules.checklist(p, listOf(vehicle), allSent, VerifyState.REJECTED).review)
        assertEquals(
            ChecklistStep(StepMark.FAILED, "app.driverVerification.blocked", alert = true),
            DriverRules.checklist(p, listOf(vehicle), allSent, VerifyState.BLOCKED).review,
        )
    }

    // -- lock dialog and cargo 0 ------------------------------------------------------------------------------

    @Test
    fun `only the save that stores the car asks for confirmation`() {
        val form = DriverForm("Jasur", "Cobalt", "Oq", "01 A 452 KA", "4", "0", "0")
        assertTrue(DriverRules.locksCar(DriverRules.savePlan(form, profile(), emptyList())))
        val locked = profile("pending", "01 A 452 KA")
        // Name only.
        assertFalse(DriverRules.locksCar(DriverRules.savePlan(form.copy(fullName = "Jasur T."), locked, listOf(vehicle))))
        // The retry of a missing v2 vehicle: the car is already locked.
        assertFalse(DriverRules.locksCar(DriverRules.savePlan(form, locked, emptyList())))
    }

    @Test
    fun `the summary shows what will be stored, empty cargo as 0`() {
        val summary = DriverRules.lockSummary(DriverForm("Jasur", " Cobalt ", "Oq", "01 A 452 KA", "4", "20", ""))
        assertEquals(
            listOf("driverProfileForm.carModel", "driverProfileForm.carColor", "driverProfileForm.plateNumber", "driverProfileForm.passengerSeats", "offerCreate.serviceParcel"),
            summary.map { it.labelKey },
        )
        assertEquals("Cobalt", summary[0].value)
        assertEquals(mapOf("kg" to "20", "litres" to "0"), summary[4].params)
    }

    @Test
    fun `cargo 0 is accepted and sent as null, a positive number in grams and millilitres`() {
        val zero = DriverRules.savePlan(DriverForm("Jasur", "Cobalt", "Oq", "01A452KA", "4", "0", "0"), profile(), emptyList()).vehicle!!
        assertNull(zero.cargoMaxWeightG)
        assertNull(zero.cargoMaxVolumeMl)
        val some = DriverRules.savePlan(DriverForm("Jasur", "Cobalt", "Oq", "01A452KA", "4", "0", "100"), profile(), emptyList()).vehicle!!
        assertNull(some.cargoMaxWeightG)
        assertEquals(100_000L, some.cargoMaxVolumeMl)
        assertEquals(emptySet<FormIssue>(), DriverRules.issues(DriverForm("Jasur", "Cobalt", "Oq", "01A452KA", "4", "0", "0"), false, false))
        assertEquals(setOf(FormIssue.CARGO_KG), DriverRules.issues(DriverForm("Jasur", "Cobalt", "Oq", "01A452KA", "4", " ", "0"), false, false))
    }

    // -- documents and availability ---------------------------------------------------------------------------

    @Test
    fun `no re-upload on an approved document, nor on a rejected or blocked account`() {
        assertFalse(DriverRules.canUpload(DocState.APPROVED, DriverStatus.PENDING))
        assertTrue(DriverRules.canUpload(DocState.PENDING, DriverStatus.PENDING))
        assertTrue(DriverRules.canUpload(DocState.REJECTED, DriverStatus.PENDING))
        assertTrue(DriverRules.canUpload(DocState.MISSING, DriverStatus.NEW))
        assertTrue(DriverRules.canUpload(DocState.MISSING, null))
        DocState.entries.forEach { state ->
            assertFalse(DriverRules.canUpload(state, DriverStatus.REJECTED))
            assertFalse(DriverRules.canUpload(state, DriverStatus.BLOCKED))
        }
        assertTrue(DriverRules.uploadPrimary(DocState.MISSING))
        assertTrue(DriverRules.uploadPrimary(DocState.REJECTED))
        assertFalse(DriverRules.uploadPrimary(DocState.PENDING))
    }

    @Test
    fun `the availability banner says which way it moved`() {
        assertEquals("driver.home.availableOn", DriverRules.availabilityDoneKey(true))
        assertEquals("driver.home.availabilityOffDone", DriverRules.availabilityDoneKey(false))
        assertEquals("driver.home.availableOff", DriverRules.availabilitySubtitleKey(DriverStatus.APPROVED, on = false))
    }
}
