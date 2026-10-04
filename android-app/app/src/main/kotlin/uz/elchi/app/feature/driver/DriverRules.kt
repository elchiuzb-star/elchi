package uz.elchi.app.feature.driver

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.DriverDocumentDTO
import uz.elchi.app.api.DriverProfileDTO
import uz.elchi.app.api.DriverProfileUpdate
import uz.elchi.app.api.FilesApi
import uz.elchi.app.api.generated.VehicleCreate
import uz.elchi.app.api.generated.VehicleDTO
import uz.elchi.app.ui.theme.Tone
import java.math.BigDecimal

/** `driver_profiles.verification_status`. An unknown value reads as [NEW]: never approved by accident. */
enum class DriverStatus(val wire: String) {
    NEW("new"),
    PENDING("pending"),
    APPROVED("approved"),
    REJECTED("rejected"),
    BLOCKED("blocked");

    companion object {
        fun from(wire: String?): DriverStatus = entries.firstOrNull { it.wire == wire } ?: NEW
    }
}

/** What the Routes / Matches / Orders tabs show before the driver may work (Q96, web `DriverVerificationGate`). */
enum class GateVariant {
    /** Approved: no gate. */
    NONE,

    /** new / pending: finish the profile and the documents, then wait for the operator. */
    WAITING,

    /** rejected / blocked: nothing an upload changes; the way forward is support. */
    DECIDED,
}

/**
 * The form's inputs: text as typed. The vehicle half is entered once (Q94) and then read back from the v1 profile
 * and the v2 vehicle.
 */
data class DriverForm(
    val fullName: String = "",
    val carModel: String = "",
    val carColor: String = "",
    val plate: String = "",
    val seats: String = "",
    val cargoKg: String = "",
    val cargoLitres: String = "",
)

enum class FormIssue { NAME, MODEL, COLOR, PLATE, SEATS, CARGO_KG, CARGO_LITRES }

/**
 * One save of the driver profile form: the v1 PATCH (null = nothing to send) and then the v2 vehicle to register
 * (null = none). After the v1 PATCH has stored the car the form is locked, so a retry after a failed v2 call sends
 * only the missing vehicle.
 */
data class SavePlan(val patch: DriverProfileUpdate?, val vehicle: VehicleCreate?)

/** The five verification documents, in the design's order, with the server's per-type upload limits. */
enum class DocType(val wire: String, val pdfAllowed: Boolean, val maxMb: Int) {
    PASSPORT("passport", pdfAllowed = true, maxMb = 10),
    SELFIE("selfie", pdfAllowed = false, maxMb = 5),
    LICENSE("license", pdfAllowed = true, maxMb = 10),
    CAR_DOCUMENT("car_document", pdfAllowed = true, maxMb = 10),
    CAR_PHOTO("car_photo", pdfAllowed = false, maxMb = 5);

    val maxBytes: Long get() = maxMb * 1024L * 1024L

    companion object {
        fun from(wire: String): DocType? = entries.firstOrNull { it.wire == wire }
    }
}

/** A row's state; [MISSING] is "no row of this type yet". */
enum class DocState(val wire: String) { MISSING("missing"), PENDING("pending"), APPROVED("approved"), REJECTED("rejected") }

data class DocRow(val type: DocType, val state: DocState, val reason: String?, val fileUrl: String?)

/**
 * The account as the driver reads it (design 06 §1.5). The server moves `new` to `pending` on the first upload, so
 * "pending" alone does not mean "under review": [REVIEW] needs the car stored and all five documents sent with none
 * rejected; anything short of that is [INCOMPLETE].
 */
enum class VerifyState(val labelKey: String, val tone: Tone, val hintKey: String) {
    INCOMPLETE("driver.verify.incomplete", Tone.WARN, "driverHome.onboardingHint"),
    REVIEW("app.driverVerification.pending", Tone.WARN, "driver.verify.reviewHint"),
    APPROVED("status.approved", Tone.OK, "driverHome.approvedHint"),
    REJECTED("status.rejected", Tone.ERR, "app.driverGate.decided"),
    BLOCKED("app.driverVerification.blocked", Tone.ERR, "app.driverGate.decided"),
}

/** A checklist row's circle: its number, a green tick, or a red cross. */
enum class StepMark { OPEN, DONE, FAILED }

/**
 * One row of home's 3-step checklist (design 06 §1.7). The sub-line is a dictionary key with its params, or
 * [subText] when it is the driver's own data ("Cobalt · 01 A 452 KA"); [alert] paints it red.
 */
data class ChecklistStep(
    val mark: StepMark,
    val subKey: String? = null,
    val params: Map<String, Any> = emptyMap(),
    val subText: String? = null,
    val alert: Boolean = false,
)

data class Checklist(val profile: ChecklistStep, val documents: ChecklistStep, val review: ChecklistStep)

/** One line of the lock dialog's summary: the field's label key and the value as it will be stored. */
data class LockSummaryRow(val labelKey: String, val value: String, val params: Map<String, Any> = emptyMap())

/** Pure driver-side rules for Stage 07 (unit-tested in DriverRulesTest). */
object DriverRules {
    const val SEATS_MIN = 1
    const val SEATS_MAX = 8

    // -- verification status ----------------------------------------------------------------------------------

    /**
     * The translated status, never the raw code (the web prints it raw; the design fixes that): new / pending /
     * blocked from `app.driverVerification.*`, approved / rejected from `status.*`.
     */
    fun statusKey(status: DriverStatus): String = when (status) {
        DriverStatus.NEW -> "app.driverVerification.new"
        DriverStatus.PENDING -> "app.driverVerification.pending"
        DriverStatus.BLOCKED -> "app.driverVerification.blocked"
        DriverStatus.APPROVED -> "status.approved"
        DriverStatus.REJECTED -> "status.rejected"
    }

    fun statusTone(status: DriverStatus): Tone = when (status) {
        DriverStatus.NEW, DriverStatus.PENDING -> Tone.WARN
        DriverStatus.APPROVED -> Tone.OK
        DriverStatus.REJECTED, DriverStatus.BLOCKED -> Tone.ERR
    }

    fun gate(status: DriverStatus): GateVariant = when (status) {
        DriverStatus.APPROVED -> GateVariant.NONE
        DriverStatus.NEW, DriverStatus.PENDING -> GateVariant.WAITING
        DriverStatus.REJECTED, DriverStatus.BLOCKED -> GateVariant.DECIDED
    }

    /** Home's title: "Profilni to'ldiring" until approved, then "Bosh sahifa". */
    fun homeTitleKey(status: DriverStatus): String =
        if (status == DriverStatus.APPROVED) "clientProfile.home" else "driverHome.completeProfileTitle"

    fun homeHintKey(status: DriverStatus): String =
        if (status == DriverStatus.APPROVED) "driverHome.approvedHint" else "driverHome.onboardingHint"

    // -- derived verification state and the checklist (design 06) ---------------------------------------------

    /**
     * Step 1 is done when the car is stored: the v1 profile holds it (Q94 lock) and, once the vehicles are read,
     * the v2 vehicle exists too (a failed v2 call leaves the form to finish). [vehicles] null = not read.
     */
    fun profileDone(profile: DriverProfileDTO?, vehicles: List<VehicleDTO>?): Boolean =
        vehicleLocked(profile) && (vehicles == null || vehicles.isNotEmpty())

    /** All five documents sent and none of them rejected. */
    fun documentsDone(rows: List<DocRow>): Boolean = submitted(rows) == DocType.entries.size && rows.none { it.state == DocState.REJECTED }

    /**
     * approved / rejected / blocked come from the server; otherwise [VerifyState.REVIEW] only when the operator has
     * everything ([profileDone] and [documentsDone]). [rows] null = the documents could not be read: the server's
     * word decides.
     */
    fun verifyState(status: DriverStatus, profileDone: Boolean, rows: List<DocRow>?): VerifyState = when (status) {
        DriverStatus.APPROVED -> VerifyState.APPROVED
        DriverStatus.REJECTED -> VerifyState.REJECTED
        DriverStatus.BLOCKED -> VerifyState.BLOCKED
        DriverStatus.NEW, DriverStatus.PENDING -> when {
            rows == null -> if (status == DriverStatus.PENDING && profileDone) VerifyState.REVIEW else VerifyState.INCOMPLETE
            profileDone && documentsDone(rows) -> VerifyState.REVIEW
            else -> VerifyState.INCOMPLETE
        }
    }

    /** "Profilni ko'rish" once the car is stored, "Profilni to'ldirish" before (home and the gate). */
    fun profileButtonKey(profileDone: Boolean): String = if (profileDone) "driverHome.viewProfile" else "driverHome.completeProfile"

    /** Home's checklist until approval: profile and car, documents, the operator's review. */
    fun checklist(profile: DriverProfileDTO, vehicles: List<VehicleDTO>?, rows: List<DocRow>?, state: VerifyState): Checklist {
        val done = profileDone(profile, vehicles)
        val car = listOfNotNull(profile.carModel, profile.plateNumber).filter { it.isNotBlank() }.joinToString(" · ")
        val profileStep = if (done) ChecklistStep(StepMark.DONE, subText = car) else ChecklistStep(StepMark.OPEN, "driver.checklist.profileTodo")
        val total = DocType.entries.size
        val rejected = rows?.count { it.state == DocState.REJECTED } ?: 0
        val docsStep = when {
            rows == null -> ChecklistStep(StepMark.OPEN, "driverProfile.action.documentsHint")
            rejected > 0 -> ChecklistStep(StepMark.FAILED, "driver.checklist.docsRejected", mapOf("count" to rejected), alert = true)
            else -> ChecklistStep(
                if (documentsDone(rows)) StepMark.DONE else StepMark.OPEN,
                "driver.checklist.docsCount",
                mapOf("submitted" to submitted(rows), "total" to total),
            )
        }
        val reviewStep = when (state) {
            VerifyState.REVIEW -> ChecklistStep(StepMark.OPEN, "status.pending")
            VerifyState.REJECTED -> ChecklistStep(StepMark.FAILED, "status.rejected", alert = true)
            VerifyState.BLOCKED -> ChecklistStep(StepMark.FAILED, "app.driverVerification.blocked", alert = true)
            VerifyState.APPROVED -> ChecklistStep(StepMark.DONE, "status.approved")
            VerifyState.INCOMPLETE -> ChecklistStep(StepMark.OPEN, "driver.checklist.reviewAfter")
        }
        return Checklist(profileStep, docsStep, reviewStep)
    }

    /** rejected / blocked: home adds the way to support next to "complete the profile". */
    fun showsSupport(status: DriverStatus): Boolean = gate(status) == GateVariant.DECIDED

    // -- availability -----------------------------------------------------------------------------------------

    /**
     * The switch can be used when the driver is approved, or to turn it OFF whatever the status (the server always
     * accepts "off": a driver blocked while available must still be able to stop).
     */
    fun availabilityEnabled(status: DriverStatus, on: Boolean): Boolean = status == DriverStatus.APPROVED || on

    fun availabilitySubtitleKey(status: DriverStatus, on: Boolean): String = when {
        status != DriverStatus.APPROVED && !on -> "driverHome.availabilityLocked"
        on -> "driver.home.availableOn"
        else -> "driver.home.availableOff"
    }

    /** The banner after the switch moved: "Faollik o'chirildi" / "Faolman — buyurtma qabul qilishga tayyor". */
    fun availabilityDoneKey(on: Boolean): String = if (on) "driver.home.availableOn" else "driver.home.availabilityOffDone"

    // -- profile form: lock and values ------------------------------------------------------------------------

    /** Q94, the web's rule: the car is locked as soon as the profile holds a plate, approved or not. */
    fun vehicleLocked(profile: DriverProfileDTO?): Boolean = !profile?.plateNumber.isNullOrBlank()

    /**
     * Seats / cargo belong to the v2 vehicle: they lock when it exists. Without one (the v2 call failed after the v1
     * save) they stay editable, because nothing stored them yet.
     */
    fun capacityLocked(vehicles: List<VehicleDTO>): Boolean = vehicles.isNotEmpty()

    /** `01 A 123 AA` -> `01A123AA`: what v2 stores and compares. */
    fun normalizePlate(plate: String): String = plate.filterNot { it.isWhitespace() }.uppercase()

    /** 20000 g -> "20", 20500 g -> "20.5". */
    fun thousandths(value: Long?): String =
        value?.let { BigDecimal(it).divide(BigDecimal(1000)).stripTrailingZeros().toPlainString() }.orEmpty()

    /** The vehicle this profile registered: same plate if the profile has one, else the newest. */
    fun ownVehicle(profile: DriverProfileDTO?, vehicles: List<VehicleDTO>): VehicleDTO? {
        val plate = profile?.plateNumber?.let(::normalizePlate)
        return vehicles.firstOrNull { plate != null && normalizePlate(it.plateNumber) == plate } ?: vehicles.firstOrNull()
    }

    /**
     * The form as the server has it: the name and the v1 car, with seats / kg / litres from the v2 vehicle (the web
     * leaves its defaults there; that would show numbers nobody entered). [typed] keeps what the person entered for
     * the parts the server does not hold yet.
     */
    fun formFrom(profile: DriverProfileDTO, vehicles: List<VehicleDTO>, typed: DriverForm = DriverForm()): DriverForm {
        val vehicle = ownVehicle(profile, vehicles)
        val locked = vehicleLocked(profile)
        return DriverForm(
            fullName = profile.fullName ?: profile.user?.fullName ?: typed.fullName,
            carModel = if (locked) profile.carModel ?: vehicle?.makeModel.orEmpty() else typed.carModel,
            carColor = if (locked) profile.carColor ?: vehicle?.color.orEmpty() else typed.carColor,
            plate = if (locked) profile.plateNumber.orEmpty() else typed.plate,
            seats = vehicle?.seatCapacity?.toString() ?: typed.seats,
            cargoKg = if (vehicle != null) thousandths(vehicle.cargoMaxWeightG) else typed.cargoKg,
            cargoLitres = if (vehicle != null) thousandths(vehicle.cargoMaxVolumeMl) else typed.cargoLitres,
        )
    }

    // -- profile form: validation and the save sequence -------------------------------------------------------

    private fun positiveInt(text: String): Long? = text.trim().toLongOrNull()?.takeIf { it > 0 }

    private fun wholeNumber(text: String): Long? = text.trim().toLongOrNull()?.takeIf { it >= 0 }

    /**
     * What stops a save. Cargo kg and litres are required, 0 included: 0 = "no parcels" and is sent as null
     * (v2 `VehicleCreate` takes `> 0` or null, and reads null as no cargo capacity).
     */
    fun issues(form: DriverForm, profileLocked: Boolean, capacityLocked: Boolean): Set<FormIssue> {
        val issues = mutableSetOf<FormIssue>()
        if (form.fullName.isBlank()) issues += FormIssue.NAME
        if (!profileLocked) {
            if (form.carModel.isBlank()) issues += FormIssue.MODEL
            if (form.carColor.isBlank()) issues += FormIssue.COLOR
            if (normalizePlate(form.plate).isEmpty()) issues += FormIssue.PLATE
        }
        if (!capacityLocked) {
            val seats = form.seats.trim().toIntOrNull()
            if (seats == null || seats !in SEATS_MIN..SEATS_MAX) issues += FormIssue.SEATS
            if (wholeNumber(form.cargoKg) == null) issues += FormIssue.CARGO_KG
            if (wholeNumber(form.cargoLitres) == null) issues += FormIssue.CARGO_LITRES
        }
        return issues
    }

    /**
     * First save: v1 `PATCH {full_name, car_model, car_color, plate_number}`, then (no v2 vehicle yet, every field
     * filled) `POST /vehicles`. Locked: the name only, and only when it changed; the vehicle only when still missing.
     */
    fun savePlan(form: DriverForm, profile: DriverProfileDTO, vehicles: List<VehicleDTO>): SavePlan {
        val locked = vehicleLocked(profile)
        val name = form.fullName.trim()
        val patch = if (locked) {
            DriverProfileUpdate(fullName = name).takeIf { name != (profile.fullName ?: profile.user?.fullName).orEmpty().trim() }
        } else {
            DriverProfileUpdate(fullName = name, carModel = form.carModel.trim(), carColor = form.carColor.trim(), plateNumber = form.plate.trim())
        }
        // After the v1 save the car is the profile's (locked); before it, the form's.
        val model = (if (locked) profile.carModel else form.carModel)?.trim().orEmpty()
        val color = (if (locked) profile.carColor else form.carColor)?.trim().orEmpty()
        val plate = normalizePlate((if (locked) profile.plateNumber else form.plate).orEmpty())
        val seats = form.seats.trim().toLongOrNull()
        val vehicle = if (vehicles.isEmpty() && model.isNotEmpty() && color.isNotEmpty() && plate.isNotEmpty() && seats != null) {
            VehicleCreate(
                plateNumber = plate,
                makeModel = model,
                color = color,
                seatCapacity = seats,
                cargoMaxWeightG = positiveInt(form.cargoKg)?.times(1000),
                cargoMaxVolumeMl = positiveInt(form.cargoLitres)?.times(1000),
            )
        } else {
            null
        }
        return SavePlan(patch, vehicle)
    }

    /**
     * Q94: this save stores the car on v1, after which only an operator can change it - ask first. A name-only save
     * and the retry of a missing v2 vehicle (the car is already locked) go straight through.
     */
    fun locksCar(plan: SavePlan): Boolean = plan.patch?.plateNumber != null

    /**
     * The lock dialog's summary: model, colour, plate, seats, and cargo ("Yuk") whose value is
     * `driver.form.cargoSummary` "{kg} kg · {litres} l" filled with [LockSummaryRow.params] (empty = 0).
     */
    fun lockSummary(form: DriverForm): List<LockSummaryRow> {
        fun zero(text: String) = text.trim().ifEmpty { "0" }
        return listOf(
            LockSummaryRow("driverProfileForm.carModel", form.carModel.trim()),
            LockSummaryRow("driverProfileForm.carColor", form.carColor.trim()),
            LockSummaryRow("driverProfileForm.plateNumber", form.plate.trim()),
            LockSummaryRow("driverProfileForm.passengerSeats", form.seats.trim()),
            LockSummaryRow("offerCreate.serviceParcel", "", mapOf("kg" to zero(form.cargoKg), "litres" to zero(form.cargoLitres))),
        )
    }

    // -- documents --------------------------------------------------------------------------------------------

    fun docState(status: String?): DocState = when (status) {
        null -> DocState.MISSING
        "approved" -> DocState.APPROVED
        "rejected" -> DocState.REJECTED
        else -> DocState.PENDING
    }

    /** One row per type in the design's order; no server row = missing. A later row of a type wins. */
    fun docRows(documents: List<DriverDocumentDTO>): List<DocRow> = DocType.entries.map { type ->
        val row = documents.lastOrNull { it.documentType == type.wire }
        DocRow(type, docState(row?.status), row?.rejectionReason?.takeIf { row.status == "rejected" && it.isNotBlank() }, row?.fileUrl)
    }

    /** N of "N / 5": types with a row. */
    fun submitted(rows: List<DocRow>): Int = rows.count { it.state != DocState.MISSING }

    /**
     * The row's upload button: none on an approved document (a re-upload would quietly put it back to review), and
     * none at all once the account is rejected or blocked (decided: support is the way on, Q96).
     */
    fun canUpload(state: DocState, account: DriverStatus?): Boolean =
        state != DocState.APPROVED && account != DriverStatus.REJECTED && account != DriverStatus.BLOCKED

    /** "Yuklash" is primary for a missing or rejected document; a pending one's "Qayta yuklash" is soft. */
    fun uploadPrimary(state: DocState): Boolean = state == DocState.MISSING || state == DocState.REJECTED

    fun docTone(state: DocState): Tone = when (state) {
        DocState.APPROVED -> Tone.OK
        DocState.PENDING -> Tone.WARN
        DocState.REJECTED -> Tone.ERR
        DocState.MISSING -> Tone.GRAY
    }

    /** `selfie` / `car_photo` take images only (jpg/png/webp); the other three also a PDF. */
    fun mimeAllowed(type: DocType, mime: String?): Boolean = when (mime?.lowercase()) {
        "image/jpeg", "image/jpg", "image/png", "image/webp" -> true
        FilesApi.PDF -> type.pdfAllowed
        else -> false
    }

    fun sizeAllowed(type: DocType, bytes: Long): Boolean = bytes in 1..type.maxBytes

    /** The hint under a row: "Rasm (JPG, PNG, WEBP), 5 MB gacha" or "Rasm yoki PDF, 10 MB gacha". */
    fun fileHintKey(type: DocType): String = if (type.pdfAllowed) "driver.docs.fileHintImageOrPdf" else "driver.docs.fileHintImage"

    // -- errors -----------------------------------------------------------------------------------------------

    /**
     * Driver codes the dictionary has no `error.<CODE>` for, mapped to the driver sentences; null = the generic
     * `errorText` (which reads `error.<CODE>`, e.g. `DRIVER_VEHICLE_LOCKED`, `DRIVER_NOT_APPROVED`).
     * v2 reports a duplicate plate as `VALIDATION_ERROR` on `plate_number`.
     */
    fun errorKey(error: Throwable): String? {
        val api = error as? ApiException ?: return null
        return when (api.code) {
            "PLATE_NUMBER_ALREADY_EXISTS" -> "driver.error.plateTaken"
            "DRIVER_BLOCKED" -> "driver.error.blocked"
            "FILE_TOO_LARGE", "DRIVER_DOCUMENT_TOO_LARGE" -> "driver.error.fileTooLarge"
            "VALIDATION_ERROR" -> "driver.error.plateTaken".takeIf { field(api) == "plate_number" }
            else -> null
        }
    }

    private fun field(error: ApiException): String? =
        (error.details as? JsonObject)?.get("field")?.let { runCatching { it.jsonPrimitive.contentOrNull }.getOrNull() }
}
