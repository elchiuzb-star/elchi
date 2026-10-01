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
        else -> "driverProfile.availabilityOff"
    }

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

    /** What stops a save. Cargo is optional, but a number there must be a whole number above 0. */
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
            if (form.cargoKg.isNotBlank() && positiveInt(form.cargoKg) == null) issues += FormIssue.CARGO_KG
            if (form.cargoLitres.isNotBlank() && positiveInt(form.cargoLitres) == null) issues += FormIssue.CARGO_LITRES
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
