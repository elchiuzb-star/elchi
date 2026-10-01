import Foundation
import Observation
import UIKit

// MARK: - The driver's account state

/// Everything the driver shell reads: the v1 profile (verification status, the car, availability), the v2 vehicle,
/// the wallet balance (Q22: viewable before approval) and the five documents. One instance per signed-in driver, so
/// an upload on the documents screen is what home shows when the driver goes back.
@MainActor @Observable
final class DriverModel {
    private let driverAPI: DriverAPI
    private let api: ElchiAPI
    private let files: FilesAPI
    private let banners: BannerCenter
    let keys = ActionKeys()

    private(set) var profile: Loadable<DriverProfileV1> = .loading
    /// nil until the first answer (the form must not offer a second car because the list has not arrived).
    private(set) var vehicles: [VehicleDTO]?
    private(set) var vehiclesError: Error?
    private(set) var wallet: Loadable<WalletDTO> = .loading
    private(set) var documents: Loadable<[DriverDocumentV1]> = .loading
    /// The document type whose file is on its way up (its row says "Yuklanmoqda…").
    private(set) var uploading: DriverDocumentType?
    /// The switch's position while `PATCH /availability` runs; nil = the profile's value.
    private(set) var availabilityPending: Bool?

    init(driverAPI: DriverAPI, api: ElchiAPI, files: FilesAPI, banners: BannerCenter) {
        self.driverAPI = driverAPI
        self.api = api
        self.files = files
        self.banners = banners
    }

    var status: DriverVerification? { profile.value.map { DriverVerification($0.verificationStatus) } }
    var isAvailable: Bool { availabilityPending ?? profile.value?.isAvailable ?? false }
    var vehicle: VehicleDTO? { vehicles?.first }
    var slots: [DocumentSlot] { DocumentSlots.derive(documents.value ?? []) }

    /// Home, the tabs and the form: profile, vehicle and balance together.
    func refresh() async {
        async let profile: Void = loadProfile()
        async let vehicles: Void = loadVehicles()
        async let wallet: Void = loadWallet()
        _ = await (profile, vehicles, wallet)
    }

    func loadProfile() async {
        do {
            profile = .loaded(try await driverAPI.profile())
        } catch {
            if profile.value == nil { profile = .failed(error) }
        }
    }

    func loadVehicles() async {
        do {
            vehicles = try await api.listMyVehicles().data
            vehiclesError = nil
        } catch {
            vehiclesError = error
        }
    }

    /// "—" while loading or on failure; never a made-up zero.
    func loadWallet() async {
        do {
            wallet = .loaded(try await api.getMyWallet().data)
        } catch {
            if wallet.value == nil { wallet = .failed(error) }
        }
    }

    func loadDocuments() async {
        do {
            documents = .loaded(try await driverAPI.documents())
        } catch {
            if documents.value == nil { documents = .failed(error) }
        }
    }

    // MARK: Availability

    /// Moves the switch at once, then asks the server; a refusal puts it back and says why.
    func setAvailability(_ on: Bool) async {
        guard let status, availabilityPending == nil, on != isAvailable,
              DriverAvailability.canToggle(status: status, isOn: isAvailable) else { return }
        banners.clearError()
        availabilityPending = on
        do {
            _ = try await driverAPI.setAvailability(on)
            await loadProfile()
            availabilityPending = nil
            banners.ok("driverHome.availabilityUpdated")
        } catch {
            availabilityPending = nil
            showError(error)
            await loadProfile()
        }
    }

    // MARK: Documents

    /// Upload (step 1, `/files/upload` with the document type) then submit (step 2). Then "sent for review" and a
    /// fresh list and profile (the first upload moves `new` to `pending`).
    func upload(_ type: DriverDocumentType, file: DocumentFile) async {
        guard uploading == nil else { return }
        banners.clearError()
        guard type.accepts(mimeType: file.mimeType, sizeBytes: file.data.count) else {
            showError(APIError(status: 413, code: file.data.count > type.maxBytes ? "FILE_TOO_LARGE" : "DRIVER_DOCUMENT_INVALID_TYPE",
                               message: "", details: nil), type: type)
            return
        }
        uploading = type
        defer { uploading = nil }
        do {
            let uploaded = try await files.upload(type: type.rawValue, data: file.data, filename: file.filename, mimeType: file.mimeType)
            try await driverAPI.submitDocument(type: type.rawValue, fileUrl: uploaded.fileUrl, mimeType: uploaded.mimeType ?? file.mimeType,
                                               sizeBytes: uploaded.sizeBytes ?? file.data.count)
            banners.show(.template("driverDocs.uploadedForReview", keys: ["type": "docType.\(type.rawValue)"]), tone: .ok)
        } catch {
            showError(error, type: type)
        }
        await loadDocuments()
        await loadProfile()
    }

    // MARK: Profile form

    /// Runs a save plan: the v1 PATCH first, then the v2 vehicle. A v1 failure stops there; after a v2 failure the
    /// profile is read again (it is locked now) and the retry's plan is the vehicle alone. True when all of it went.
    func save(_ plan: DriverSavePlan) async -> Result<Void, Error> {
        banners.clearError()
        if let patch = plan.patch {
            do {
                try await driverAPI.updateProfile(patch)
            } catch {
                return .failure(error)
            }
        }
        var outcome: Result<Void, Error> = .success(())
        if let vehicle = plan.vehicle {
            let action = "vehicle.create"
            do {
                _ = try await api.createVehicle(body: vehicle, idempotencyKey: keys.key(action))
                keys.settle(action)
            } catch {
                keys.settle(action, after: error)
                outcome = .failure(error)
            }
        }
        async let profile: Void = loadProfile()
        async let vehicles: Void = loadVehicles()
        _ = await (profile, vehicles)
        return outcome
    }

    // MARK: -

    /// A failure on the app banner, as a sentence (errors stay until dismissed or the next action).
    func showError(_ error: Error, type: DriverDocumentType? = nil) {
        switch DriverErrorText.sentence(error, documentType: type) {
        case .key(let key, let values): banners.show(.template(key, values: values), tone: .err)
        case .generic: banners.error(error)
        }
    }
}

// MARK: - The profile form

/// "Haydovchi profili": the typed values, which parts are locked, the field problems after a save attempt, and the
/// outcome line. Filled from the profile (and the v2 vehicle) when it opens.
@MainActor @Observable
final class DriverProfileFormModel {
    private let driver: DriverModel

    var form = DriverForm()
    /// Problems are shown once "Saqlash" was tried (not while the first letters go in).
    private(set) var attempted = false
    private(set) var saving = false
    private var failure: (error: Error, form: DriverForm)?
    /// The last save's failure, until the person changes something in the form.
    var saveError: Error? { failure.flatMap { $0.form == form ? $0.error : nil } }
    private var filledFrom: DriverProfileV1?
    private var filledVehicle: VehicleDTO?

    init(driver: DriverModel) { self.driver = driver }

    var profile: DriverProfileV1? { driver.profile.value }
    /// Model, colour and plate are in (Q94).
    var vehicleLocked: Bool { VehicleLock.isLocked(profile) }
    /// Seats and cargo live on the v2 vehicle.
    var hasVehicle: Bool { driver.vehicle != nil }
    /// The vehicle list has answered (so "no vehicle" is known, not assumed).
    var vehiclesKnown: Bool { driver.vehicles != nil }

    var problems: [DriverFormField: DriverFormProblem] {
        DriverFormRules.problems(form, vehicleLocked: vehicleLocked, hasVehicle: hasVehicle)
    }

    var plan: DriverSavePlan? {
        guard let profile, vehiclesKnown else { return nil }
        return DriverSavePlan.make(form: form, profile: profile, hasVehicle: hasVehicle)
    }

    /// Something to send, and the vehicle list is known.
    var canSave: Bool { !saving && !(plan?.isEmpty ?? true) }

    func problem(_ field: DriverFormField) -> DriverFormProblem? { attempted ? problems[field] : nil }

    /// Takes the server's values: the first time, and again whenever the profile or vehicle changed underneath
    /// (after a save). Seats and cargo typed before a failed vehicle call are kept for the retry.
    func fill() {
        guard let profile = driver.profile.value else { return }
        let vehicle = driver.vehicle
        guard profile != filledFrom || vehicle != filledVehicle else { return }
        let first = filledFrom == nil
        let values = VehicleLock.values(profile: profile, vehicle: vehicle)
        if first || profile.fullName != filledFrom?.fullName { form.fullName = values.fullName }
        if VehicleLock.isLocked(profile) || first {
            form.carModel = values.carModel
            form.carColor = values.carColor
            form.plate = values.plate
        }
        if vehicle != nil {
            form.seats = values.seats
            form.cargoKg = values.cargoKg
            form.cargoLitres = values.cargoLitres
        }
        filledFrom = profile
        filledVehicle = vehicle
    }

    func save() async -> Bool {
        attempted = true
        failure = nil
        guard problems.isEmpty, let plan, !plan.isEmpty else { return false }
        saving = true
        defer { saving = false }
        let result = await driver.save(plan)
        fill()
        switch result {
        case .success:
            attempted = false
            return true
        case .failure(let error):
            failure = (error, form)
            driver.showError(error)
            return false
        }
    }
}

// MARK: - A file for a document

/// What goes up for one document: bytes, a filename with the real extension, and the declared type.
struct DocumentFile: Sendable {
    let data: Data
    let filename: String
    let mimeType: String

    /// A picture as JPEG under the type's limit: 1600 px first (the Stage 02 pipeline), then smaller and lower
    /// quality until it fits. nil when even the smallest try is too big or the picture cannot be encoded.
    static func image(_ image: UIImage, maxBytes: Int) -> DocumentFile? {
        let attempts: [(side: CGFloat, quality: CGFloat)] = [(1600, 0.8), (1600, 0.6), (1280, 0.6), (1024, 0.5), (800, 0.45)]
        for attempt in attempts {
            if let jpeg = PhotoCompressor.jpeg(image, maxSide: attempt.side, quality: attempt.quality), jpeg.count <= maxBytes {
                return DocumentFile(data: jpeg, filename: "document.jpg", mimeType: "image/jpeg")
            }
        }
        return nil
    }

    /// A PDF as picked (it is not re-encoded); the model checks it against the type's limit.
    static func pdf(_ data: Data) -> DocumentFile {
        DocumentFile(data: data, filename: "document.pdf", mimeType: "application/pdf")
    }
}
