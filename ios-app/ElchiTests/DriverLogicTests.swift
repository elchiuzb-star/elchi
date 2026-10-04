import Foundation
import Testing
import UIKit
@testable import Elchi

/// Stage 07 pure logic: verification status -> label / tone / gate, availability rules, the Q94 vehicle lock and the
/// locked values (g -> kg, ml -> litres), the v1 PATCH / v2 POST save plan (and its retry after a v2 failure),
/// document slots and the N / 5 count, per-type file rules, plate normalisation, form validation and error sentences.
enum DriverFixture {
    static func profile(status: String = "new", name: String? = "Jasur Toshmatov", model: String? = nil, color: String? = nil,
                        plate: String? = nil, available: Bool = false) -> DriverProfileV1 {
        DriverProfileV1(id: 14, user: .init(phone: "+998950000001", fullName: name), fullName: name, carModel: model, carColor: color,
                        plateNumber: plate, verificationStatus: status, isAvailable: available)
    }

    static func lockedProfile(status: String = "pending") -> DriverProfileV1 {
        profile(status: status, model: "Cobalt", color: "Oq", plate: "01 A 452 KA")
    }

    static func vehicle(seats: Int = 4, grams: Int? = 20_000, millilitres: Int? = 100_000, status: String = "pending") -> VehicleDTO {
        VehicleDTO(cargoMaxVolumeMl: millilitres, cargoMaxWeightG: grams, color: "Oq", createdAt: "2026-09-30T10:00:00Z", documentFileIds: [],
                   id: "veh_1", makeModel: "Cobalt", plateMasked: "01****KA", plateNumber: "01A452KA", seatCapacity: seats,
                   verificationStatus: status, version: 1)
    }

    static func document(_ type: String, _ status: String, reason: String? = nil, id: Int = 1) -> DriverDocumentV1 {
        DriverDocumentV1(documentId: id, documentType: type, fileUrl: "/api/v1/files/x?sig=1", status: status, rejectionReason: reason)
    }

    static let fullForm = DriverForm(fullName: "Jasur Toshmatov", carModel: "Cobalt", carColor: "Oq", plate: " 01 a  452 ka ",
                                     seats: "4", cargoKg: "20", cargoLitres: "100")
}

struct DriverVerificationTests {
    @Test func labelsAreTranslatedKeysNeverRawCodes() {
        #expect(DriverVerification("new").labelKey == "app.driverVerification.new")
        #expect(DriverVerification("pending").labelKey == "app.driverVerification.pending")
        #expect(DriverVerification("blocked").labelKey == "app.driverVerification.blocked")
        #expect(DriverVerification("approved").labelKey == "status.approved")
        #expect(DriverVerification("rejected").labelKey == "status.rejected")
        #expect(DriverVerification(nil) == .new)
    }

    @Test func tones() {
        #expect(DriverVerification("new").tone == .warn)
        #expect(DriverVerification("pending").tone == .warn)
        #expect(DriverVerification("approved").tone == .ok)
        #expect(DriverVerification("rejected").tone == .err)
        #expect(DriverVerification("blocked").tone == .err)
        #expect(DriverVerification("suspended_somehow").tone == .warn)
    }

    @Test func gateVariants() {
        #expect(DriverVerification("approved").gate == nil)
        #expect(DriverVerification("new").gate == .pending)
        #expect(DriverVerification("pending").gate == .pending)
        #expect(DriverVerification("rejected").gate == .decided)
        #expect(DriverVerification("blocked").gate == .decided)
        #expect(DriverVerification("whatever").gate == .pending)
    }

    @MainActor @Test func everyStatusReadsAsWordsInBothLanguages() {
        let strings = LocaleStore()
        strings.set(.uz)
        #expect(strings.verificationLabel(.pending) == "Ko'rib chiqilmoqda")
        #expect(strings.verificationLabel(.approved) == "Tasdiqlangan")
        #expect(strings.verificationLabel(.other("mystery")) == "Ko'rib chiqilmoqda")
        strings.set(.ru)
        #expect(strings.verificationLabel(.blocked) == "Заблокирован")
        #expect(strings.verificationLabel(.rejected) == "Отклонено")
        strings.set(.uz)
    }
}

struct DriverAvailabilityTests {
    @Test func onlyAnApprovedDriverCanTurnOnButAnyoneCanTurnOff() {
        #expect(DriverAvailability.canToggle(status: .approved, isOn: false))
        #expect(DriverAvailability.canToggle(status: .approved, isOn: true))
        #expect(!DriverAvailability.canToggle(status: .pending, isOn: false))
        #expect(!DriverAvailability.canToggle(status: .new, isOn: false))
        #expect(!DriverAvailability.canToggle(status: .blocked, isOn: false))
        // Blocked while still on: switching off must stay possible.
        #expect(DriverAvailability.canToggle(status: .blocked, isOn: true))
    }

    @Test func subtitles() {
        #expect(DriverAvailability.subtitleKey(status: .pending, isOn: false) == "driverHome.availabilityLocked")
        #expect(DriverAvailability.subtitleKey(status: .approved, isOn: true) == "driver.home.availableOn")
        #expect(DriverAvailability.subtitleKey(status: .approved, isOn: false) == "driver.home.availableOff")
    }
}

struct VehicleLockTests {
    @Test func locksOnceThePlateIsIn() {
        #expect(!VehicleLock.isLocked(nil))
        #expect(!VehicleLock.isLocked(DriverFixture.profile()))
        #expect(!VehicleLock.isLocked(DriverFixture.profile(plate: "  ")))
        #expect(VehicleLock.isLocked(DriverFixture.lockedProfile()))
    }

    @Test func thousandthsToKilogramsAndLitres() {
        #expect(VehicleLock.thousandths(20_000) == "20")
        #expect(VehicleLock.thousandths(20_500) == "20.5")
        #expect(VehicleLock.thousandths(1_250) == "1.25")
        #expect(VehicleLock.thousandths(400_000) == "400")
        #expect(VehicleLock.thousandths(nil) == "")
    }

    @Test func lockedValuesComeFromTheProfileAndTheVehicle() {
        let values = VehicleLock.values(profile: DriverFixture.lockedProfile(), vehicle: DriverFixture.vehicle(seats: 3, grams: 80_000, millilitres: 400_000))
        #expect(values.carModel == "Cobalt")
        #expect(values.carColor == "Oq")
        #expect(values.plate == "01 A 452 KA")
        #expect(values.seats == "3")
        #expect(values.cargoKg == "80")
        #expect(values.cargoLitres == "400")
    }

    @Test func noVehicleLeavesSeatsAndCargoEmptyNotDefaults() {
        let values = VehicleLock.values(profile: DriverFixture.lockedProfile(), vehicle: nil)
        #expect(values.seats.isEmpty && values.cargoKg.isEmpty && values.cargoLitres.isEmpty)
    }
}

struct PlateTests {
    @Test func normalisation() {
        #expect(Plate.display(" 01 a  452 ka ") == "01 A 452 KA")
        #expect(Plate.compact(" 01 a  452 ka ") == "01A452KA")
        #expect(Plate.compact("01\tA 452\nKA") == "01A452KA")
        #expect(Plate.compact("   ").isEmpty)
    }
}

struct DriverSavePlanTests {
    @Test func firstSaveSendsTheCarToV1ThenCreatesTheV2Vehicle() {
        let plan = DriverSavePlan.make(form: DriverFixture.fullForm, profile: DriverFixture.profile(), hasVehicle: false)
        #expect(plan.patch == DriverProfilePatch(fullName: "Jasur Toshmatov", carModel: "Cobalt", carColor: "Oq", plateNumber: "01 A 452 KA"))
        let vehicle = try! #require(plan.vehicle)
        #expect(vehicle.plateNumber == "01A452KA")
        #expect(vehicle.makeModel == "Cobalt")
        #expect(vehicle.color == "Oq")
        #expect(vehicle.seatCapacity == 4)
        #expect(vehicle.cargoMaxWeightG == 20_000)
        #expect(vehicle.cargoMaxVolumeMl == 100_000)
    }

    @Test func retryAfterAV2FailureSendsOnlyTheVehicle() {
        // v1 went through (the profile now has the plate), v2 failed: nothing for v1, the vehicle again.
        var form = DriverFixture.fullForm
        form.plate = "01 A 452 KA"
        let plan = DriverSavePlan.make(form: form, profile: DriverFixture.lockedProfile(), hasVehicle: false)
        #expect(plan.patch == nil)
        #expect(plan.vehicle?.plateNumber == "01A452KA")
    }

    @Test func lockedWithVehicleSendsTheNameOnlyAndOnlyWhenChanged() {
        var form = VehicleLock.values(profile: DriverFixture.lockedProfile(), vehicle: DriverFixture.vehicle())
        #expect(DriverSavePlan.make(form: form, profile: DriverFixture.lockedProfile(), hasVehicle: true).isEmpty)
        form.fullName = "Jasur T."
        let plan = DriverSavePlan.make(form: form, profile: DriverFixture.lockedProfile(), hasVehicle: true)
        #expect(plan.patch == DriverProfilePatch(fullName: "Jasur T."))
        #expect(plan.vehicle == nil)
    }

    @Test func cargoIsOptionalButNeverZero() {
        var form = DriverFixture.fullForm
        form.cargoKg = ""
        form.cargoLitres = ""
        let vehicle = DriverSavePlan.vehicleCreate(form)
        #expect(vehicle?.cargoMaxWeightG == nil && vehicle?.cargoMaxVolumeMl == nil)
        form.seats = ""
        #expect(DriverSavePlan.vehicleCreate(form) == nil)
    }

    @Test func thePatchOmitsUnsetKeysOnTheWire() throws {
        let json = String(decoding: try JSONEncoder().encode(DriverProfilePatch(fullName: "Ali")), as: UTF8.self)
        #expect(json == #"{"full_name":"Ali"}"#)
    }
}

struct DriverFormRulesTests {
    @Test func firstTimeNeedsEverythingCargoIncluded() {
        let empty = DriverFormRules.problems(DriverForm(), vehicleLocked: false, hasVehicle: false)
        #expect(empty[.fullName] == .required)
        #expect(empty[.carModel] == .required)
        #expect(empty[.carColor] == .required)
        #expect(empty[.plate] == .required)
        #expect(empty[.seats] == .required)
        // DESIGN06 2.6: both cargo figures are required (0 allowed).
        #expect(empty[.cargoKg] == .required && empty[.cargoLitres] == .required)
        #expect(DriverFormRules.problems(DriverFixture.fullForm, vehicleLocked: false, hasVehicle: false).isEmpty)
    }

    @Test func seatsInRangeAndCargoAWholeNumberZeroIncluded() {
        var form = DriverFixture.fullForm
        form.seats = "9"
        form.cargoKg = "0"
        form.cargoLitres = "-5"
        let problems = DriverFormRules.problems(form, vehicleLocked: false, hasVehicle: false)
        #expect(problems[.seats] == .seatsRange)
        #expect(problems[.cargoKg] == nil)
        #expect(problems[.cargoLitres] == .notNumber)
        #expect(DriverFormRules.positiveInt("12") == 12)
        #expect(DriverFormRules.positiveInt("2.5") == nil)
    }

    @Test func lockedPartsAreNotChecked() {
        let form = DriverForm(fullName: "Ali")
        #expect(DriverFormRules.problems(form, vehicleLocked: true, hasVehicle: true).isEmpty)
        #expect(DriverFormRules.problems(form, vehicleLocked: true, hasVehicle: false)[.seats] == .required)
    }
}

struct DocumentSlotTests {
    @Test func everyTypeHasARowInOrderAndMissingIsGray() {
        let slots = DocumentSlots.derive([])
        #expect(slots.map(\.type) == [.passport, .selfie, .license, .carDocument, .carPhoto])
        #expect(slots.allSatisfy { $0.state == .missing && $0.state.tone == .gray })
        #expect(DocumentSlots.submitted(slots) == 0)
    }

    @Test func mixedStatesAndCount() {
        let slots = DocumentSlots.derive([
            DriverFixture.document("passport", "approved"),
            DriverFixture.document("selfie", "pending"),
            DriverFixture.document("license", "rejected", reason: "rasm xira, matn o'qilmaydi"),
        ])
        #expect(slots[0].state == .approved && slots[0].state.tone == .ok)
        #expect(slots[1].state == .pending && slots[1].state.tone == .warn)
        #expect(slots[2].state == .rejected && slots[2].state.tone == .err)
        #expect(slots[2].rejectionReason == "rasm xira, matn o'qilmaydi")
        #expect(slots[1].rejectionReason == nil)
        #expect(slots[3].state == .missing)
        #expect(DocumentSlots.submitted(slots) == 3)
    }

    @Test func theLastRowOfATypeWinsAndUnknownCountsAsPending() {
        let slots = DocumentSlots.derive([
            DriverFixture.document("selfie", "rejected", reason: "x", id: 1),
            DriverFixture.document("selfie", "pending", id: 2),
            DriverFixture.document("car_photo", "in_review", id: 3),
        ])
        #expect(slots[1].state == .pending && slots[1].document?.documentId == 2)
        #expect(slots[4].state == .pending)
        #expect(DocumentSlots.submitted(slots) == 2)
    }
}

struct DocumentFileRuleTests {
    @Test func perTypeMimeAndSize() {
        #expect(!DriverDocumentType.selfie.allowsPDF && !DriverDocumentType.carPhoto.allowsPDF)
        #expect(DriverDocumentType.passport.allowsPDF && DriverDocumentType.license.allowsPDF && DriverDocumentType.carDocument.allowsPDF)
        #expect(DriverDocumentType.selfie.maxMB == 5)
        #expect(DriverDocumentType.carDocument.maxMB == 10)
        #expect(DriverDocumentType.selfie.accepts(mimeType: "image/jpeg", sizeBytes: 5 * 1024 * 1024))
        #expect(!DriverDocumentType.selfie.accepts(mimeType: "image/jpeg", sizeBytes: 5 * 1024 * 1024 + 1))
        #expect(!DriverDocumentType.selfie.accepts(mimeType: "application/pdf", sizeBytes: 1000))
        #expect(DriverDocumentType.license.accepts(mimeType: "application/pdf", sizeBytes: 10 * 1024 * 1024))
        #expect(!DriverDocumentType.license.accepts(mimeType: "image/gif", sizeBytes: 1000))
        #expect(DriverDocumentType.selfie.hintKey == "driver.docs.fileHintImage")
        #expect(DriverDocumentType.passport.hintKey == "driver.docs.fileHintImageOrPdf")
    }

    @Test func imagesAreCompressedUnderTheLimit() {
        let image = UIGraphicsImageRenderer(size: CGSize(width: 3000, height: 2000)).image { context in
            for x in stride(from: 0, to: 3000, by: 10) {
                UIColor(hue: CGFloat(x % 360) / 360, saturation: 1, brightness: 1, alpha: 1).setFill()
                context.fill(CGRect(x: x, y: 0, width: 10, height: 2000))
            }
        }
        let file = DocumentFile.image(image, maxBytes: DriverDocumentType.selfie.maxBytes)
        #expect(file != nil)
        #expect((file?.data.count ?? .max) <= DriverDocumentType.selfie.maxBytes)
        #expect(file?.mimeType == "image/jpeg" && file?.filename == "document.jpg")
        #expect(DocumentFile.image(image, maxBytes: 100) == nil)
        #expect(DocumentFile.pdf(Data("%PDF".utf8)).filename == "document.pdf")
    }
}

struct DriverErrorTextTests {
    func error(_ code: String, status: Int = 400, field: String? = nil) -> APIError {
        APIError(status: status, code: code, message: "server words", details: field.map { .object(["field": .string($0)]) })
    }

    @Test func driverSpecificSentences() {
        #expect(DriverErrorText.sentence(error("PLATE_NUMBER_ALREADY_EXISTS", status: 409)) == .key("driver.error.plateTaken", [:]))
        #expect(DriverErrorText.sentence(error("VALIDATION_ERROR", field: "plate_number")) == .key("driver.error.plateTaken", [:]))
        #expect(DriverErrorText.sentence(error("VALIDATION_ERROR", field: "seat_capacity")) == .generic)
        #expect(DriverErrorText.sentence(error("FILE_TOO_LARGE", status: 413), documentType: .selfie) == .key("driver.error.fileTooLarge", ["max": "5"]))
        #expect(DriverErrorText.sentence(error("FILE_TOO_LARGE", status: 413), documentType: .license) == .key("driver.error.fileTooLarge", ["max": "10"]))
        #expect(DriverErrorText.sentence(error("DRIVER_BLOCKED", status: 403)) == .key("driver.error.blocked", [:]))
        #expect(DriverErrorText.sentence(error("DRIVER_NOT_APPROVED")) == .generic)
    }

    @MainActor @Test func sentencesInBothLanguages() {
        let strings = LocaleStore()
        strings.set(.uz)
        #expect(strings.driverErrorText(error("FILE_TOO_LARGE", status: 413), documentType: .selfie) == "Fayl juda katta: 5 MB gacha yuklash mumkin.")
        #expect(strings.driverErrorText(error("DRIVER_NOT_APPROVED")) == "Profil tasdiqlanmagan")
        #expect(strings.driverErrorText(error("DRIVER_VEHICLE_LOCKED", status: 403)).hasPrefix("Avtomobil ma'lumotlari bir marta"))
        #expect(strings.driverErrorText(APIError(status: 0, code: APIError.network, message: "", details: nil)) == strings.t("error.offline"))
        strings.set(.ru)
        #expect(strings.driverErrorText(error("PLATE_NUMBER_ALREADY_EXISTS", status: 409)).hasPrefix("Этот госномер"))
        strings.set(.uz)
    }
}
