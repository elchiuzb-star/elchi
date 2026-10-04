import Foundation
import os
import Testing
@testable import Elchi

/// DESIGN06 (driver registration): the derived home state, the three-step checklist, the Q94 lock confirmation,
/// cargo 0 = no parcels (null on the wire), upload visibility per document and account state, own vehicle, copy keys.
struct Design06HomeStateTests {
    private func slots(_ states: [String: String]) -> [DocumentSlot] {
        DocumentSlots.derive(states.enumerated().map { DriverFixture.document($0.element.key, $0.element.value, id: $0.offset) })
    }

    private var allSent: [String: String] {
        ["passport": "pending", "selfie": "pending", "license": "pending", "car_document": "pending", "car_photo": "pending"]
    }

    @Test func serverDecisionsWin() {
        #expect(DriverHomeState.derive(status: .approved, vehicleLocked: false, slots: []) == .approved)
        #expect(DriverHomeState.derive(status: .rejected, vehicleLocked: true, slots: slots(allSent)) == .rejected)
        #expect(DriverHomeState.derive(status: .blocked, vehicleLocked: true, slots: slots(allSent)) == .blocked)
        #expect(DriverHomeState.derive(status: .new, vehicleLocked: true, slots: slots(allSent)) == .incomplete)
    }

    @Test func pendingWithOneDocumentIsNotUnderReview() {
        // The server moves new -> pending on the first upload.
        #expect(DriverHomeState.derive(status: .pending, vehicleLocked: true, slots: slots(["passport": "pending"])) == .incomplete)
        #expect(DriverHomeState.derive(status: .pending, vehicleLocked: false, slots: slots(allSent)) == .incomplete)
    }

    @Test func reviewNeedsTheCarAllFiveAndNoRejection() {
        #expect(DriverHomeState.derive(status: .pending, vehicleLocked: true, slots: slots(allSent)) == .review)
        var mixed = allSent
        mixed["license"] = "rejected"
        #expect(DriverHomeState.derive(status: .pending, vehicleLocked: true, slots: slots(mixed)) == .incomplete)
        mixed["license"] = "approved"
        #expect(DriverHomeState.derive(status: .pending, vehicleLocked: true, slots: slots(mixed)) == .review)
        #expect(DriverHomeState.derive(status: .other("in_review"), vehicleLocked: true, slots: slots(allSent)) == .review)
    }

    @Test func documentsNotLoadedYetFallBackToTheServerWord() {
        #expect(DriverHomeState.derive(status: .pending, vehicleLocked: true, slots: nil) == .review)
        #expect(DriverHomeState.derive(status: .pending, vehicleLocked: false, slots: nil) == .incomplete)
    }

    @Test func labelsHintsTones() {
        #expect(DriverHomeState.incomplete.labelKey == "driver.verify.incomplete")
        #expect(DriverHomeState.review.labelKey == "app.driverVerification.pending")
        #expect(DriverHomeState.blocked.labelKey == "app.driverVerification.blocked")
        #expect(DriverHomeState.incomplete.hintKey == "driverHome.onboardingHint")
        #expect(DriverHomeState.review.hintKey == "driver.verify.reviewHint")
        #expect(DriverHomeState.approved.hintKey == "driverHome.approvedHint")
        #expect(DriverHomeState.rejected.hintKey == "app.driverGate.decided")
        #expect(DriverHomeState.incomplete.tone == .warn && DriverHomeState.review.tone == .warn)
        #expect(DriverHomeState.approved.tone == .ok && DriverHomeState.rejected.tone == .err && DriverHomeState.blocked.tone == .err)
    }

    @MainActor @Test func wordsInBothLanguages() {
        let strings = LocaleStore()
        strings.set(.uz)
        #expect(strings.homeStateLabel(.incomplete) == "To'ldirilmagan")
        #expect(strings.homeStateLabel(.review) == "Ko'rib chiqilmoqda")
        #expect(strings.t(DriverHomeState.review.hintKey) == "Operator hujjatlaringizni tekshirmoqda.")
        strings.set(.ru)
        #expect(strings.homeStateLabel(.incomplete) == "Не заполнено")
        strings.set(.uz)
    }
}

struct Design06ChecklistTests {
    @Test func freshDriver() {
        let steps = DriverChecklist.steps(state: .incomplete, profile: DriverFixture.profile(), slots: DocumentSlots.derive([]))
        #expect(steps.map(\.mark) == [.todo, .todo, .todo])
        #expect(steps.map(\.target) == [.form, .documents, .gate])
        #expect(steps[0].detail == .key("driver.checklist.profileTodo", [:]))
        #expect(steps[1].detail == .key("driver.checklist.docsCount", ["submitted": "0", "total": "5"]))
        #expect(steps[2].detail == .key("driver.checklist.reviewAfter", [:]))
    }

    @Test func lockedCarAndRejectedDocuments() {
        let slots = DocumentSlots.derive([DriverFixture.document("passport", "rejected", id: 1),
                                          DriverFixture.document("selfie", "rejected", id: 2),
                                          DriverFixture.document("license", "pending", id: 3)])
        let steps = DriverChecklist.steps(state: .incomplete, profile: DriverFixture.lockedProfile(), slots: slots)
        #expect(steps[0].mark == .done && steps[0].detail == .text("Cobalt · 01 A 452 KA"))
        #expect(steps[1].mark == .failed && steps[1].detail == .key("driver.checklist.docsRejected", ["count": "2"]))
    }

    @Test func underReviewAndDecisions() {
        let all = DocumentSlots.derive(DriverDocumentType.allCases.enumerated().map { DriverFixture.document($0.element.rawValue, "pending", id: $0.offset) })
        let review = DriverChecklist.steps(state: .review, profile: DriverFixture.lockedProfile(), slots: all)
        #expect(review.map(\.mark) == [.done, .done, .todo])
        #expect(review[2].detail == .key("status.pending", [:]))
        let rejected = DriverChecklist.steps(state: .rejected, profile: DriverFixture.lockedProfile(), slots: all)
        #expect(rejected[2].mark == .failed && rejected[2].detail == .key("disputeStatus.rejected", [:]))
        let blocked = DriverChecklist.steps(state: .blocked, profile: DriverFixture.lockedProfile(), slots: all)
        #expect(blocked[2].detail == .key("app.driverVerification.blocked", [:]))
    }
}

struct Design06LockDialogTests {
    @Test func theFirstSaveWithTheCarAsksFirst() {
        let plan = DriverSavePlan.make(form: DriverFixture.fullForm, profile: DriverFixture.profile(), hasVehicle: false)
        #expect(plan.locksVehicle)
    }

    @Test func aNameOnlySaveDoesNotAsk() {
        var form = VehicleLock.values(profile: DriverFixture.lockedProfile(), vehicle: DriverFixture.vehicle())
        form.fullName = "Jasur T."
        let plan = DriverSavePlan.make(form: form, profile: DriverFixture.lockedProfile(), hasVehicle: true)
        #expect(!plan.isEmpty && !plan.locksVehicle)
    }

    @Test func theVehicleOnlyRetryAsksTooBecauseSeatsAndCargoLock() {
        var form = DriverFixture.fullForm
        form.plate = "01 A 452 KA"
        let plan = DriverSavePlan.make(form: form, profile: DriverFixture.lockedProfile(), hasVehicle: false)
        #expect(plan.patch == nil && plan.locksVehicle)
    }

    @Test func summaryReadsAsTypedWithCargoZeroWhenBlank() {
        var form = DriverFixture.fullForm
        form.cargoKg = "0"
        form.cargoLitres = ""
        let summary = LockSummary(form)
        #expect(summary.model == "Cobalt" && summary.color == "Oq" && summary.plate == "01 A 452 KA" && summary.seats == "4")
        #expect(summary.cargoKg == "0" && summary.cargoLitres == "0")
        #expect(LockSummary(DriverFixture.fullForm).cargoKg == "20")
    }

}

struct Design06CargoTests {
    @Test func zeroIsAllowedAndGoesAsNull() {
        var form = DriverFixture.fullForm
        form.cargoKg = "0"
        form.cargoLitres = "0"
        #expect(DriverFormRules.problems(form, vehicleLocked: false, hasVehicle: false).isEmpty)
        let vehicle = try! #require(DriverSavePlan.vehicleCreate(form))
        #expect(vehicle.cargoMaxWeightG == nil && vehicle.cargoMaxVolumeMl == nil)
    }

    @Test func blankIsRequiredAndPositiveIsThousandths() {
        var form = DriverFixture.fullForm
        form.cargoKg = ""
        form.cargoLitres = " "
        let problems = DriverFormRules.problems(form, vehicleLocked: false, hasVehicle: false)
        #expect(problems[.cargoKg] == .required && problems[.cargoLitres] == .required)
        #expect(DriverFormRules.cargoThousandths("25") == 25_000)
        #expect(DriverFormRules.cargoThousandths("0") == nil)
        #expect(DriverFormRules.cargoThousandths("") == nil)
        #expect(DriverFormRules.wholeNumber("0") == 0 && DriverFormRules.wholeNumber("-1") == nil)
    }

    @Test func zeroOnTheWireIsAbsentNotZero() throws {
        var form = DriverFixture.fullForm
        form.cargoKg = "0"
        let json = String(decoding: try JSONEncoder().encode(try #require(DriverSavePlan.vehicleCreate(form))), as: UTF8.self)
        #expect(!json.contains("\"cargo_max_weight_g\":0"))
        #expect(json.contains("\"cargo_max_volume_ml\":100000"))
    }

    @Test func fieldSentences() {
        #expect(DriverFormRules.messageKey(.cargoKg, .required) == "driver.form.cargoKgRequired")
        #expect(DriverFormRules.messageKey(.cargoLitres, .required) == "driver.form.required")
        #expect(DriverFormRules.messageKey(.seats, .required) == "driver.form.seatsRange")
        #expect(DriverFormRules.messageKey(.seats, .seatsRange) == "driver.form.seatsRange")
        #expect(DriverFormRules.messageKey(.fullName, .required) == "driver.form.nameRequired")
        #expect(DriverFormRules.messageKey(.carModel, .required) == "driver.form.modelRequired")
        #expect(DriverFormRules.messageKey(.carColor, .required) == "driver.form.colorRequired")
        #expect(DriverFormRules.messageKey(.plate, .required) == "driver.form.required")
    }
}

struct Design06UploadTests {
    private func slot(_ status: String?) -> DocumentSlot {
        DocumentSlots.derive(status.map { [DriverFixture.document("passport", $0)] } ?? [])[0]
    }

    @Test func approvedDocumentsHaveNoReupload() {
        #expect(!slot("approved").canUpload(account: .pending))
        #expect(!slot("approved").canUpload(account: .approved))
        #expect(slot("pending").canUpload(account: .pending))
        #expect(slot("rejected").canUpload(account: .pending))
        #expect(slot(nil).canUpload(account: .new))
        #expect(slot("pending").canUpload(account: nil))
    }

    @Test func aDecidedAccountUploadsNothing() {
        for state in ["pending", "rejected", nil] as [String?] {
            #expect(!slot(state).canUpload(account: .rejected))
            #expect(!slot(state).canUpload(account: .blocked))
        }
    }

    @Test func labelsAndEmphasis() {
        #expect(slot(nil).uploadLabelKey == "driverDocs.upload" && slot(nil).uploadIsPrimary)
        #expect(slot("rejected").uploadLabelKey == "driverDocs.upload" && slot("rejected").uploadIsPrimary)
        #expect(slot("pending").uploadLabelKey == "driverDocs.reupload" && !slot("pending").uploadIsPrimary)
    }
}

struct Design06MiscTests {
    @Test func ownVehicleMatchesTheProfilePlate() {
        var other = DriverFixture.vehicle()
        other.id = "veh_0"
        other.plateNumber = "10B999CC"
        let own = DriverFixture.vehicle()
        #expect(VehicleLock.ownVehicle(profile: DriverFixture.lockedProfile(), vehicles: [other, own])?.id == "veh_1")
        #expect(VehicleLock.ownVehicle(profile: DriverFixture.profile(), vehicles: [other, own])?.id == "veh_0")
        #expect(VehicleLock.ownVehicle(profile: nil, vehicles: []) == nil)
    }

    @Test func availabilityCopy() {
        #expect(DriverAvailability.subtitleKey(status: .approved, isOn: false) == "driver.home.availableOff")
        #expect(DriverAvailability.doneKey(isOn: false) == "driver.home.availabilityOffDone")
        #expect(DriverAvailability.doneKey(isOn: true) == "driver.home.availableOn")
    }

    @MainActor @Test func newKeysResolveInBothLanguages() {
        let keys = ["driver.verify.incomplete", "driver.verify.reviewHint", "driver.checklist.profileTitle", "driver.checklist.profileTodo",
                    "driver.checklist.docsCount", "driver.checklist.docsRejected", "driver.checklist.reviewTitle", "driver.checklist.reviewAfter",
                    "driverHome.viewProfile", "driver.home.availableOff", "driver.home.availabilityOffDone", "driver.form.lockTitle",
                    "driver.form.lockText", "driver.form.lockConfirm", "driver.form.lockReview", "driver.form.cargoSummary",
                    "driver.form.savedLocked", "driver.form.askOperator", "driver.form.seatsRange", "driver.form.cargoKgRequired",
                    "driver.form.nameRequired", "driver.form.modelRequired", "driver.form.colorRequired", "driver.profile.formHintOpen",
                    "driverOrders.emptyHint", "offerCreate.serviceParcel"]
        let strings = LocaleStore()
        for language in [AppLocale.uz, .ru] {
            strings.set(language)
            for key in keys { #expect(strings.tOrNil(key) != nil, "\(key) missing") }
        }
        strings.set(.uz)
        #expect(strings.t("driver.form.cargoSummary", ("kg", "0"), ("litres", "0")) == "0 kg · 0 l")
    }
}

/// The form model against a scripted server: "Saqlash" with the car opens the dialog and sends nothing; "Tekshirib
/// chiqaman" sends nothing; "Ha, saqlash" sends the v1 PATCH and the v2 vehicle (cargo 0 as null). Part of the
/// serialized transport suite (one shared `StubProtocol`).
extension HTTPTransportTests {
    private func scriptDriverServer() {
        let locked = OSAllocatedUnfairLock(initialState: false)
        respond { request in
            let path = request.url?.path ?? ""
            switch (request.httpMethod ?? "GET", path) {
            case ("GET", "/api/v1/driver/profile"):
                let car = locked.withLock { $0 } ? #""car_model":"Cobalt","car_color":"Oq","plate_number":"01 A 452 KA""#
                    : #""car_model":null,"car_color":null,"plate_number":null"#
                return (200, #"{"success":true,"data":{"id":14,"full_name":"Jasur","verification_status":"new","is_available":false,"# + car + "}}")
            case ("PATCH", "/api/v1/driver/profile"):
                locked.withLock { $0 = true }
                return (200, #"{"success":true,"data":{}}"#)
            case ("GET", "/api/v2/me/vehicles"):
                return (200, #"{"success":true,"data":[]}"#)
            case ("POST", "/api/v2/vehicles"):
                return (201, #"{"success":true,"data":{"color":"Oq","created_at":"2026-10-03T08:00:00Z","document_file_ids":[],"id":"veh_1","make_model":"Cobalt","plate_masked":"01****KA","plate_number":"01A452KA","seat_capacity":4,"verification_status":"pending","version":1}}"#)
            default:
                return (404, #"{"success":false,"error":{"code":"NOT_FOUND","message":"x"}}"#)
            }
        }
    }

    private func sent(_ method: String, _ path: String) -> [URLRequest] {
        StubProtocol.recorded.withLock { $0 }.filter { $0.httpMethod == method && $0.url?.path == path }
    }

    @MainActor @Test func design06LockDialogGatesTheFirstSave() async throws {
        scriptDriverServer()
        let driver = DriverModel(driverAPI: DriverAPI(transport: transport), api: ElchiAPI(transport: transport),
                                 files: FilesAPI(transport: transport), banners: BannerCenter())
        let form = DriverProfileFormModel(driver: driver)
        await driver.loadProfile()
        await driver.loadVehicles()
        form.fill()
        form.form = DriverFixture.fullForm
        form.form.cargoKg = "0"

        #expect(await form.requestSave() == nil)
        #expect(form.confirming?.cargoKg == "0")
        #expect(sent("PATCH", "/api/v1/driver/profile").isEmpty && sent("POST", "/api/v2/vehicles").isEmpty)

        form.cancelLock()
        #expect(form.confirming == nil)
        #expect(sent("PATCH", "/api/v1/driver/profile").isEmpty)

        #expect(await form.requestSave() == nil)
        #expect(await form.confirmLock() == .locked)
        #expect(sent("PATCH", "/api/v1/driver/profile").count == 1)
        let post = try #require(sent("POST", "/api/v2/vehicles").first)
        let body = try #require(post.httpBody ?? post.httpBodyStream.map { stream -> Data in
            stream.open(); defer { stream.close() }
            var data = Data(); var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable { let n = stream.read(&buffer, maxLength: buffer.count); if n <= 0 { break }; data.append(buffer, count: n) }
            return data
        })
        let json = String(decoding: body, as: UTF8.self)
        #expect(!json.contains("cargo_max_weight_g\":0") && json.contains("\"cargo_max_volume_ml\":100000"))
        #expect(form.vehicleLocked)
    }

    @MainActor @Test func design06NameOnlySaveSkipsTheDialog() async throws {
        respond { request in
            switch (request.httpMethod ?? "GET", request.url?.path ?? "") {
            case ("GET", "/api/v1/driver/profile"):
                return (200, #"{"success":true,"data":{"id":14,"full_name":"Jasur","verification_status":"pending","is_available":false,"car_model":"Cobalt","car_color":"Oq","plate_number":"01 A 452 KA"}}"#)
            case ("PATCH", "/api/v1/driver/profile"):
                return (200, #"{"success":true,"data":{}}"#)
            case ("GET", "/api/v2/me/vehicles"):
                return (200, #"{"success":true,"data":[{"color":"Oq","created_at":"2026-10-03T08:00:00Z","document_file_ids":[],"id":"veh_1","make_model":"Cobalt","plate_masked":"01****KA","plate_number":"01A452KA","seat_capacity":4,"verification_status":"pending","version":1}]}"#)
            default:
                return (404, #"{"success":false,"error":{"code":"NOT_FOUND","message":"x"}}"#)
            }
        }
        let driver = DriverModel(driverAPI: DriverAPI(transport: transport), api: ElchiAPI(transport: transport),
                                 files: FilesAPI(transport: transport), banners: BannerCenter())
        let form = DriverProfileFormModel(driver: driver)
        await driver.loadProfile()
        await driver.loadVehicles()
        form.fill()
        form.form.fullName = "Jasur Toshmatov"
        #expect(await form.requestSave() == .name)
        #expect(form.confirming == nil)
        #expect(sent("PATCH", "/api/v1/driver/profile").count == 1)
    }
}
