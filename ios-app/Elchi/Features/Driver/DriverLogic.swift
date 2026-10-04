import Foundation

// MARK: - Verification status

/// The v1 profile's `verification_status` (the web's source for the gate). Shown translated, never as the raw code.
public enum DriverVerification: Hashable, Sendable {
    case new, pending, approved, rejected, blocked
    /// A value this build does not know: treated as "not approved yet, keep going" (the gate's pending variant).
    case other(String)

    public init(_ raw: String?) {
        switch raw {
        case "new", nil: self = .new
        case "pending": self = .pending
        case "approved": self = .approved
        case "rejected": self = .rejected
        case "blocked": self = .blocked
        case let value?: self = .other(value)
        }
    }

    public var raw: String {
        switch self {
        case .new: "new"
        case .pending: "pending"
        case .approved: "approved"
        case .rejected: "rejected"
        case .blocked: "blocked"
        case .other(let value): value
        }
    }

    /// new / pending / blocked read `app.driverVerification.*`; approved / rejected read the shared `status.*`.
    public var labelKey: String {
        switch self {
        case .new, .pending, .blocked: "app.driverVerification.\(raw)"
        case .approved, .rejected: "status.\(raw)"
        case .other(let value): "app.driverVerification.\(value)"
        }
    }

    /// warn while it is being worked on, ok once approved, err when a decision went against the driver.
    public var tone: Tone {
        switch self {
        case .approved: .ok
        case .rejected, .blocked: .err
        case .new, .pending, .other: .warn
        }
    }

    public var isApproved: Bool { self == .approved }

    /// Q96: what the Routes / Matches / Orders tabs show instead of their content.
    public var gate: DriverGate? {
        switch self {
        case .approved: nil
        case .rejected, .blocked: .decided
        case .new, .pending, .other: .pending
        }
    }
}

// MARK: - Home state (DESIGN06 1.5)

/// What home, the gate and the profile badge call the account: the server's word for a decision (approved /
/// rejected / blocked), otherwise derived from what the driver has sent - the server turns `new` into `pending` on
/// the first upload, so "pending" with one document is not "under review" yet. Review = the car is in (Q94 lock),
/// all five documents were sent, and none of them is rejected; anything short of that is "To'ldirilmagan".
public enum DriverHomeState: Hashable, Sendable {
    case incomplete, review, approved, rejected, blocked

    /// `slots` nil = the documents have not answered yet: the server's word decides until they do.
    public static func derive(status: DriverVerification, vehicleLocked: Bool, slots: [DocumentSlot]?) -> DriverHomeState {
        switch status {
        case .approved: return .approved
        case .rejected: return .rejected
        case .blocked: return .blocked
        case .new: return .incomplete
        case .pending, .other:
            guard let slots else { return vehicleLocked ? .review : .incomplete }
            let complete = vehicleLocked && DocumentSlots.submitted(slots) == DriverDocumentType.allCases.count
                && DocumentSlots.rejected(slots) == 0
            return complete ? .review : .incomplete
        }
    }

    public var labelKey: String {
        switch self {
        case .incomplete: "driver.verify.incomplete"
        case .review: "app.driverVerification.pending"
        case .approved: "status.approved"
        case .rejected: "status.rejected"
        case .blocked: "app.driverVerification.blocked"
        }
    }

    public var hintKey: String {
        switch self {
        case .incomplete: "driverHome.onboardingHint"
        case .review: "driver.verify.reviewHint"
        case .approved: "driverHome.approvedHint"
        case .rejected, .blocked: "app.driverGate.decided"
        }
    }

    public var tone: Tone {
        switch self {
        case .approved: .ok
        case .rejected, .blocked: .err
        case .incomplete, .review: .warn
        }
    }

    public var isDecided: Bool { self == .rejected || self == .blocked }
}

// MARK: - Onboarding checklist (DESIGN06 1.7)

/// The three steps under the status card until approval: the car (form), the five documents, the operator.
public struct ChecklistStep: Hashable, Sendable {
    public enum Mark: Hashable, Sendable { case todo, done, failed }
    public enum Target: Hashable, Sendable { case form, documents, gate }

    public let number: Int
    public let mark: Mark
    public let titleKey: String
    /// The sub-line: a key with its fillers, or text taken as it is (the car's model and plate).
    public let detail: Detail
    public let target: Target

    public enum Detail: Hashable, Sendable {
        case key(String, [String: String])
        case text(String)
    }
}

public enum DriverChecklist {
    public static func steps(state: DriverHomeState, profile: DriverProfileV1?, slots: [DocumentSlot]) -> [ChecklistStep] {
        let locked = VehicleLock.isLocked(profile)
        let car = [profile?.carModel, profile?.plateNumber].compactMap { $0?.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }.joined(separator: " · ")
        let first = ChecklistStep(number: 1, mark: locked ? .done : .todo, titleKey: "driver.checklist.profileTitle",
                                  detail: locked && !car.isEmpty ? .text(car) : .key("driver.checklist.profileTodo", [:]), target: .form)
        let total = DriverDocumentType.allCases.count
        let sent = DocumentSlots.submitted(slots)
        let rejected = DocumentSlots.rejected(slots)
        let docs: ChecklistStep = rejected > 0
            ? ChecklistStep(number: 2, mark: .failed, titleKey: "driverDocs.title",
                            detail: .key("driver.checklist.docsRejected", ["count": String(rejected)]), target: .documents)
            : ChecklistStep(number: 2, mark: sent == total ? .done : .todo, titleKey: "driverDocs.title",
                            detail: .key("driver.checklist.docsCount", ["submitted": String(sent), "total": String(total)]), target: .documents)
        let review: ChecklistStep.Detail = switch state {
        case .review: .key("status.pending", [:])
        case .rejected: .key("disputeStatus.rejected", [:])
        case .blocked: .key("app.driverVerification.blocked", [:])
        case .incomplete, .approved: .key("driver.checklist.reviewAfter", [:])
        }
        let third = ChecklistStep(number: 3, mark: state.isDecided ? .failed : state == .approved ? .done : .todo,
                                  titleKey: "driver.checklist.reviewTitle", detail: review, target: .gate)
        return [first, docs, third]
    }
}

/// The verification gate's two variants: keep going (documents + profile), or a decision was made (support only;
/// nothing the driver uploads changes it).
public enum DriverGate: Hashable, Sendable { case pending, decided }

// MARK: - Availability

public enum DriverAvailability {
    /// Turning on needs an approved driver; turning off always works (a blocked driver who is still "on" can go off).
    public static func canToggle(status: DriverVerification, isOn: Bool) -> Bool {
        status.isApproved || isOn
    }

    /// The subtitle under "Faollik holati".
    public static func subtitleKey(status: DriverVerification, isOn: Bool) -> String {
        if !status.isApproved && !isOn { return "driverHome.availabilityLocked" }
        return isOn ? "driver.home.availableOn" : "driver.home.availableOff"
    }

    /// The confirmation after the switch moved (DESIGN06 1.10).
    public static func doneKey(isOn: Bool) -> String {
        isOn ? "driver.home.availableOn" : "driver.home.availabilityOffDone"
    }
}

// MARK: - Vehicle lock (Q94)

/// The car is entered once: the form locks as soon as the v1 profile has a plate (the web's rule), without waiting
/// for approval. The seats and cargo figures live on the v2 vehicle, so they lock once that exists.
public enum VehicleLock {
    public static func isLocked(_ profile: DriverProfileV1?) -> Bool {
        !(profile?.plateNumber?.trimmingCharacters(in: .whitespaces).isEmpty ?? true)
    }

    /// The vehicle this profile registered: the one with the profile's plate, else the first (DESIGN06 2.9: the form
    /// and home show the driver's own car, not every row the list returns).
    public static func ownVehicle(profile: DriverProfileV1?, vehicles: [VehicleDTO]) -> VehicleDTO? {
        let plate = profile?.plateNumber.map(Plate.compact).flatMap { $0.isEmpty ? nil : $0 }
        return vehicles.first { plate != nil && Plate.compact($0.plateNumber) == plate } ?? vehicles.first
    }

    /// Grams -> kilograms and millilitres -> litres for the read-only fields: whole numbers stay whole, anything else
    /// keeps up to 2 decimals (`20500` g -> `20.5`).
    public static func thousandths(_ value: Int?) -> String {
        guard let value else { return "" }
        if value % 1000 == 0 { return String(value / 1000) }
        let text = String(format: "%.2f", Double(value) / 1000)
        return text.replacingOccurrences(of: #"\.?0+$"#, with: "", options: .regularExpression)
    }

    /// What the locked form shows: the car from the v1 profile, seats and cargo from the v2 vehicle (never the
    /// defaults the web leaves in place).
    public static func values(profile: DriverProfileV1, vehicle: VehicleDTO?) -> DriverForm {
        DriverForm(fullName: profile.fullName ?? profile.user?.fullName ?? "",
                   carModel: profile.carModel ?? vehicle?.makeModel ?? "",
                   carColor: profile.carColor ?? vehicle?.color ?? "",
                   plate: profile.plateNumber ?? vehicle?.plateNumber ?? "",
                   seats: vehicle.map { String($0.seatCapacity) } ?? "",
                   cargoKg: thousandths(vehicle?.cargoMaxWeightG),
                   cargoLitres: thousandths(vehicle?.cargoMaxVolumeMl))
    }
}

// MARK: - Plate

public enum Plate {
    /// For v1 (the server keeps the plate as typed and normalises its own key): trimmed, inner spaces collapsed,
    /// upper-case - `" 01 a  123 aa "` -> `"01 A 123 AA"`.
    public static func display(_ typed: String) -> String {
        typed.split(whereSeparator: \.isWhitespace).joined(separator: " ").uppercased()
    }

    /// For v2 `POST /vehicles`: no spaces at all, upper-case - `"01 A 123 AA"` -> `"01A123AA"`.
    public static func compact(_ typed: String) -> String {
        typed.filter { !$0.isWhitespace }.uppercased()
    }
}

// MARK: - The profile form

/// What the form holds, as typed.
public struct DriverForm: Equatable, Sendable {
    public var fullName = ""
    public var carModel = ""
    public var carColor = ""
    public var plate = ""
    public var seats = ""
    public var cargoKg = ""
    public var cargoLitres = ""

    public init(fullName: String = "", carModel: String = "", carColor: String = "", plate: String = "", seats: String = "",
                cargoKg: String = "", cargoLitres: String = "") {
        self.fullName = fullName
        self.carModel = carModel
        self.carColor = carColor
        self.plate = plate
        self.seats = seats
        self.cargoKg = cargoKg
        self.cargoLitres = cargoLitres
    }
}

public enum DriverFormField: Hashable, Sendable, CaseIterable {
    case fullName, carModel, carColor, plate, seats, cargoKg, cargoLitres
}

public enum DriverFormProblem: Hashable, Sendable {
    /// Empty where a value is needed.
    case required
    /// Seats outside 1...8.
    case seatsRange
    /// Not a whole number above zero.
    case positive
    /// Not a whole number (0 allowed: cargo 0 = no parcels).
    case notNumber
}

public enum DriverFormRules {
    public static let seats = 1...8

    /// A whole number above zero, or nil ("abc", "0", "-3", "2.5").
    public static func positiveInt(_ text: String) -> Int? {
        let trimmed = text.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty, trimmed.allSatisfy(\.isNumber), let value = Int(trimmed), value > 0 else { return nil }
        return value
    }

    /// The sentence under a field (DESIGN06 2.3, 2.5, 2.6): per-field "kiriting" lines, seats "1 dan 8 gacha o'rin.",
    /// cargo kg says that 0 means no parcels.
    public static func messageKey(_ field: DriverFormField, _ problem: DriverFormProblem) -> String {
        switch (field, problem) {
        case (.seats, _): "driver.form.seatsRange"
        case (.fullName, .required): "driver.form.nameRequired"
        case (.carModel, .required): "driver.form.modelRequired"
        case (.carColor, .required): "driver.form.colorRequired"
        case (.cargoKg, .required), (.cargoKg, .notNumber): "driver.form.cargoKgRequired"
        case (_, .positive): "driver.form.positiveNumber"
        default: "driver.form.required"
        }
    }

    /// A whole number, zero included, or nil ("", "abc", "-3", "2.5").
    public static func wholeNumber(_ text: String) -> Int? {
        let trimmed = text.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty, trimmed.allSatisfy(\.isNumber), let value = Int(trimmed) else { return nil }
        return value
    }

    /// Cargo for v2: kg or litres -> grams or millilitres; 0 means "no parcels", which v2 takes as null (`gt=0` or
    /// null; null counts as no capacity).
    public static func cargoThousandths(_ text: String) -> Int? {
        guard let value = wholeNumber(text), value > 0 else { return nil }
        return value * 1000
    }

    /// What is wrong with each editable field. `vehicleLocked` = the v1 car is in (model, colour, plate read-only);
    /// `hasVehicle` = the v2 vehicle exists (seats and cargo read-only). Both cargo figures are required, 0 allowed
    /// (DESIGN06 2.6: 0 = no parcels).
    public static func problems(_ form: DriverForm, vehicleLocked: Bool, hasVehicle: Bool) -> [DriverFormField: DriverFormProblem] {
        var out: [DriverFormField: DriverFormProblem] = [:]
        if form.fullName.trimmingCharacters(in: .whitespaces).isEmpty { out[.fullName] = .required }
        if !vehicleLocked {
            if form.carModel.trimmingCharacters(in: .whitespaces).isEmpty { out[.carModel] = .required }
            if form.carColor.trimmingCharacters(in: .whitespaces).isEmpty { out[.carColor] = .required }
            if Plate.compact(form.plate).isEmpty { out[.plate] = .required }
        }
        if !hasVehicle {
            if form.seats.trimmingCharacters(in: .whitespaces).isEmpty {
                out[.seats] = .required
            } else if let seats = positiveInt(form.seats), !Self.seats.contains(seats) {
                out[.seats] = .seatsRange
            } else if positiveInt(form.seats) == nil {
                out[.seats] = .seatsRange
            }
            for (field, text) in [(DriverFormField.cargoKg, form.cargoKg), (.cargoLitres, form.cargoLitres)] {
                if text.trimmingCharacters(in: .whitespaces).isEmpty {
                    out[field] = .required
                } else if wholeNumber(text) == nil {
                    out[field] = .notNumber
                }
            }
        }
        return out
    }
}

/// What one "Saqlash" sends, in order: the v1 PATCH (if anything changes there), then the v2 vehicle (if there is
/// none yet). After a v1 success and a v2 failure the profile has a plate, so the retry's plan is the vehicle only.
public struct DriverSavePlan: Equatable, Sendable {
    public var patch: DriverProfilePatch?
    public var vehicle: VehicleCreate?

    public var isEmpty: Bool { patch == nil && vehicle == nil }

    public static func make(form: DriverForm, profile: DriverProfileV1, hasVehicle: Bool) -> DriverSavePlan {
        let locked = VehicleLock.isLocked(profile)
        let name = form.fullName.trimmingCharacters(in: .whitespaces)
        let savedName = (profile.fullName ?? profile.user?.fullName ?? "").trimmingCharacters(in: .whitespaces)
        var plan = DriverSavePlan()
        if locked {
            // Q94: the car keys would be refused; the name is the only thing v1 still takes.
            if !name.isEmpty && name != savedName { plan.patch = DriverProfilePatch(fullName: name) }
        } else {
            plan.patch = DriverProfilePatch(fullName: name, carModel: form.carModel.trimmingCharacters(in: .whitespaces),
                                            carColor: form.carColor.trimmingCharacters(in: .whitespaces), plateNumber: Plate.display(form.plate))
        }
        // The same car registered once on the v2 side (Q94: the form never makes a second one).
        if !hasVehicle, let vehicle = vehicleCreate(form) { plan.vehicle = vehicle }
        return plan
    }

    /// Q94: this save fixes the car for good (model, colour, plate on v1, or seats and cargo on the v2 vehicle), so
    /// it needs the "Avtomobil ma'lumotlari qulflanadi" confirmation first. A name-only save does not.
    public var locksVehicle: Bool { patch?.plateNumber != nil || vehicle != nil }

    /// The v2 body, or nil while a required value is missing: plate without spaces in upper case, kg*1000 and
    /// litres*1000 (0 or empty = null: no parcels).
    public static func vehicleCreate(_ form: DriverForm) -> VehicleCreate? {
        let plate = Plate.compact(form.plate)
        let model = form.carModel.trimmingCharacters(in: .whitespaces)
        let color = form.carColor.trimmingCharacters(in: .whitespaces)
        guard !plate.isEmpty, !model.isEmpty, !color.isEmpty, let seats = DriverFormRules.positiveInt(form.seats),
              DriverFormRules.seats.contains(seats) else { return nil }
        return VehicleCreate(cargoMaxVolumeMl: DriverFormRules.cargoThousandths(form.cargoLitres),
                             cargoMaxWeightG: DriverFormRules.cargoThousandths(form.cargoKg),
                             color: color, makeModel: model, plateNumber: plate, seatCapacity: seats)
    }
}

/// The confirmation's grey summary (DESIGN06 2.2): what is about to be locked, as typed (cargo blank or 0 reads 0).
public struct LockSummary: Equatable, Sendable {
    public let model: String
    public let color: String
    public let plate: String
    public let seats: String
    public let cargoKg: String
    public let cargoLitres: String

    public init(_ form: DriverForm) {
        model = form.carModel.trimmingCharacters(in: .whitespaces)
        color = form.carColor.trimmingCharacters(in: .whitespaces)
        plate = Plate.display(form.plate)
        seats = form.seats.trimmingCharacters(in: .whitespaces)
        cargoKg = String(DriverFormRules.wholeNumber(form.cargoKg) ?? 0)
        cargoLitres = String(DriverFormRules.wholeNumber(form.cargoLitres) ?? 0)
    }
}

// MARK: - Documents

/// The five documents, in the design's order.
public enum DriverDocumentType: String, CaseIterable, Hashable, Sendable {
    case passport, selfie, license
    case carDocument = "car_document"
    case carPhoto = "car_photo"

    /// selfie and car photo are pictures only (jpg/png/webp); the others may also be a PDF.
    public var allowsPDF: Bool { self != .selfie && self != .carPhoto }

    /// The server's limit (5 MB for image-only types, 10 MB for the rest).
    public var maxMB: Int { allowsPDF ? 10 : 5 }
    public var maxBytes: Int { maxMB * 1024 * 1024 }

    public var allowedMimeTypes: Set<String> {
        let images: Set<String> = ["image/jpeg", "image/png", "image/webp"]
        return allowsPDF ? images.union(["application/pdf"]) : images
    }

    public func accepts(mimeType: String, sizeBytes: Int) -> Bool {
        allowedMimeTypes.contains(mimeType) && sizeBytes <= maxBytes && sizeBytes > 0
    }

    /// `driver.docs.fileHintImage` / `…ImageOrPdf`, with `{max}`.
    public var hintKey: String { allowsPDF ? "driver.docs.fileHintImageOrPdf" : "driver.docs.fileHintImage" }
}

public enum DocumentState: String, Hashable, Sendable {
    case missing, pending, approved, rejected

    public var tone: Tone {
        switch self {
        case .approved: .ok
        case .pending: .warn
        case .rejected: .err
        case .missing: .gray
        }
    }
}

/// One of the five rows.
public struct DocumentSlot: Hashable, Sendable {
    public let type: DriverDocumentType
    public let state: DocumentState
    public let document: DriverDocumentV1?

    /// Whether the row offers "Yuklash" / "Qayta yuklash" (DESIGN06 3.5, 3.6): never on an approved document (a
    /// re-upload would silently send it back to review), and not at all once the account was rejected or blocked
    /// (Q96: support decides; the server refuses a blocked driver anyway).
    public func canUpload(account: DriverVerification?) -> Bool {
        guard state != .approved else { return false }
        switch account {
        case .rejected?, .blocked?: return false
        default: return true
        }
    }

    /// "Yuklash" (primary) for a missing or rejected row, "Qayta yuklash" (soft) for one waiting for review.
    public var uploadLabelKey: String { state == .pending ? "driverDocs.reupload" : "driverDocs.upload" }
    public var uploadIsPrimary: Bool { state != .pending }

    /// A rejection says why (in red); without it the same photo goes back a second time.
    public var rejectionReason: String? {
        guard state == .rejected, let reason = document?.rejectionReason?.trimmingCharacters(in: .whitespaces), !reason.isEmpty else { return nil }
        return reason
    }
}

public enum DocumentSlots {
    /// One row per type in the fixed order; the last row the server sent for a type wins; no row = missing. An
    /// unknown status counts as pending (it was sent; nobody has said no).
    public static func derive(_ rows: [DriverDocumentV1]) -> [DocumentSlot] {
        DriverDocumentType.allCases.map { type in
            let row = rows.last { $0.documentType == type.rawValue }
            let state: DocumentState = row.map { DocumentState(rawValue: $0.status) ?? .pending }.map { $0 == .missing ? .pending : $0 } ?? .missing
            return DocumentSlot(type: type, state: state, document: row)
        }
    }

    /// N in "N / 5 hujjat yuborilgan": the types that have a row, whatever its state.
    public static func submitted(_ slots: [DocumentSlot]) -> Int {
        slots.filter { $0.state != .missing }.count
    }

    /// The rows the operator turned down (the checklist counts them; there is no per-document decision event).
    public static func rejected(_ slots: [DocumentSlot]) -> Int {
        slots.filter { $0.state == .rejected }.count
    }
}

// MARK: - Errors

/// A failure as a sentence: the driver-specific ones first (duplicate plate, file size with its limit, blocked),
/// then the shared `error.<CODE>` dictionary.
public enum DriverErrorText {
    public enum Sentence: Equatable, Sendable {
        case key(String, [String: String])
        /// Anything else: `LocaleStore.errorText`.
        case generic
    }

    public static func sentence(_ error: Error, documentType: DriverDocumentType? = nil) -> Sentence {
        guard let error = error as? APIError else { return .generic }
        switch error.code {
        case "PLATE_NUMBER_ALREADY_EXISTS":
            return .key("driver.error.plateTaken", [:])
        case "VALIDATION_ERROR" where field(error) == "plate_number":
            // v2 `POST /vehicles` reports a duplicate plate this way.
            return .key("driver.error.plateTaken", [:])
        case "FILE_TOO_LARGE", "DRIVER_DOCUMENT_TOO_LARGE":
            return .key("driver.error.fileTooLarge", ["max": String(documentType?.maxMB ?? 10)])
        case "DRIVER_BLOCKED":
            return .key("driver.error.blocked", [:])
        default:
            return .generic
        }
    }

    static func field(_ error: APIError) -> String? {
        if case .object(let details)? = error.details, case .string(let field)? = details["field"] { return field }
        return nil
    }
}

extension LocaleStore {
    func driverErrorText(_ error: Error, documentType: DriverDocumentType? = nil) -> String {
        switch DriverErrorText.sentence(error, documentType: documentType) {
        case .key(let key, let values): return t(key, values: values.map { ($0.key, $0.value as Any) })
        case .generic: return bannerErrorText(error)
        }
    }

    /// `t` with the fillers as a list; the key itself when it is not in the dictionary.
    func t(_ key: String, values: [(String, Any)]) -> String {
        tOrNil(key, values: values) ?? t(key)
    }
}
