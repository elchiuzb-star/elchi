import SwiftUI

/// "Haydovchi profili": the name (always editable) and the car, entered once (Q94). The first save sends the v1
/// PATCH and registers the same car as the v2 vehicle; from then on model, colour and plate are read-only (and seats
/// and cargo once the v2 vehicle exists), and Save sends the name only. The save that locks the car asks first
/// (DESIGN06 2.2), and a successful save goes back with its banner (2.12).
struct DriverProfileFormView: View {
    let driver: DriverModel
    let form: DriverProfileFormModel
    let onBack: () -> Void
    /// "O'zgartirish uchun operatorga yozish": the Help screen (its ticket form).
    var onSupport: () -> Void = {}
    @Environment(LocaleStore.self) private var strings
    @Environment(BannerCenter.self) private var banners
    @Environment(\.elchi) private var c

    var body: some View {
        @Bindable var form = form
        ScreenScaffold(title: strings.t("driverProfileForm.title"), backLabel: strings.t("common.back"), onBack: onBack) {
            switch driver.profile {
            case .loading:
                SkeletonCards(count: 3)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err)
                ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await driver.refresh() } }
            case .loaded:
                fields
            }
        } footer: {
            ElchiButton(strings.t("common.save"), loading: form.saving) {
                Task {
                    dismissKeyboard()
                    saved(await form.requestSave())
                }
            }
            .disabled(!form.canSave)
            .accessibilityIdentifier("elchi.driver.form.save")
        }
        .task {
            await driver.refresh()
            form.fill()
        }
        .onChange(of: driver.profile.value) { _, _ in form.fill() }
        .onChange(of: driver.vehicle) { _, _ in form.fill() }
        .overlay {
            if let summary = form.confirming { lockDialog(summary) }
        }
    }

    private func saved(_ outcome: DriverProfileFormModel.Saved?) {
        guard let outcome else { return }
        banners.ok(outcome == .locked ? "driver.form.savedLocked" : "driverProfileForm.saved")
        onBack()
    }

    /// Q94: "Avtomobil ma'lumotlari qulflanadi" with what is about to be locked; nothing is sent before "Ha, saqlash".
    private func lockDialog(_ summary: LockSummary) -> some View {
        DialogOverlay(dismissLabel: strings.t("driver.form.lockReview"), onDismiss: form.cancelLock) {
            VStack(alignment: .leading, spacing: 6) {
                Text(strings.t("driver.form.lockTitle")).font(ElchiFont.poppins(19, .medium)).foregroundStyle(c.text)
                    .fixedSize(horizontal: false, vertical: true).accessibilityAddTraits(.isHeader)
                Text(strings.t("driver.form.lockText")).font(ElchiFont.poppins(13.5)).foregroundStyle(c.muted).lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)
            }
            VStack(spacing: 0) {
                summaryRow(strings.t("driverProfileForm.carModel"), summary.model, first: true)
                summaryRow(strings.t("driverProfileForm.carColor"), summary.color)
                summaryRow(strings.t("driverProfileForm.plateNumber"), summary.plate, monospaced: true)
                summaryRow(strings.t("driverProfileForm.passengerSeats"), summary.seats)
                summaryRow(strings.t("offerCreate.serviceParcel"), strings.t("driver.form.cargoSummary", ("kg", summary.cargoKg), ("litres", summary.cargoLitres)))
            }
            .padding(.horizontal, 12).padding(.vertical, 4)
            .background(c.page, in: RoundedRectangle(cornerRadius: 14))
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("elchi.driver.lock.summary")
            ElchiButton(strings.t("driver.form.lockConfirm"), loading: form.saving) {
                Task { saved(await form.confirmLock()) }
            }
            .accessibilityIdentifier("elchi.driver.lock.confirm")
            ElchiButton(strings.t("driver.form.lockReview"), variant: .neutral, action: form.cancelLock)
                .accessibilityIdentifier("elchi.driver.lock.review")
        }
    }

    private func summaryRow(_ key: String, _ value: String, first: Bool = false, monospaced: Bool = false) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(key).font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
            Spacer(minLength: 8)
            Text(value).font(monospaced ? .system(size: 13, weight: .semibold, design: .monospaced) : ElchiFont.poppins(13, .semibold))
                .foregroundStyle(c.text).multilineTextAlignment(.trailing)
        }
        .padding(.vertical, 7)
        .overlay(alignment: .top) { if !first { Rectangle().fill(c.outline).frame(height: 1) } }
    }

    @ViewBuilder
    private var fields: some View {
        @Bindable var form = form
        let locked = form.vehicleLocked
        let hasVehicle = form.hasVehicle
        let lockHint = strings.t("driverProfileForm.vehicleLockedHint")
        // DESIGN06 2.1: the lock notes come first, above the name.
        if locked {
            Note(strings.t("driverProfileForm.vehicleLockedBody"), tone: .blue, title: strings.t("driverProfileForm.vehicleLockedTitle"))
        } else {
            Note(strings.t("driver.profile.lockWarning"), tone: .warn)
        }
        ElchiField(text: $form.form.fullName, label: strings.t("driverProfileForm.fullName"), error: problemText(.fullName),
                   contentType: .name)
        if locked {
            LockedField(label: strings.t("driverProfileForm.carModel"), value: form.form.carModel, hint: lockHint)
            LockedField(label: strings.t("driverProfileForm.carColor"), value: form.form.carColor, hint: lockHint)
            LockedField(label: strings.t("driverProfileForm.plateNumber"), value: form.form.plate, hint: lockHint, monospaced: true)
        } else {
            ElchiField(text: $form.form.carModel, label: strings.t("driverProfileForm.carModel"),
                       placeholder: strings.t("driverProfileForm.carModelPlaceholder"), error: problemText(.carModel))
            ElchiField(text: $form.form.carColor, label: strings.t("driverProfileForm.carColor"),
                       placeholder: strings.t("driverProfileForm.carColorPlaceholder"), error: problemText(.carColor))
            ElchiField(text: Binding(get: { form.form.plate }, set: { form.form.plate = $0.uppercased() }),
                       label: strings.t("driverProfileForm.plateNumber"), placeholder: strings.t("driverProfileForm.plateNumberPlaceholder"),
                       error: problemText(.plate) ?? plateTakenText, keyboard: .asciiCapable, monospaced: true)
                .textInputAutocapitalization(.characters)
                .autocorrectionDisabled()
        }
        if hasVehicle {
            LockedField(label: strings.t("driverProfileForm.passengerSeats"), value: form.form.seats, hint: lockHint)
            LockedField(label: strings.t("driverProfileForm.cargoKg"), value: form.form.cargoKg, hint: lockHint)
            LockedField(label: strings.t("driverProfileForm.cargoLitres"), value: form.form.cargoLitres, hint: lockHint)
        } else {
            ElchiField(text: digits(\.seats, max: 1), label: strings.t("driverProfileForm.passengerSeats"), placeholder: "4",
                       error: problemText(.seats), keyboard: .numberPad)
            ElchiField(text: digits(\.cargoKg, max: 5), label: strings.t("driverProfileForm.cargoKg"), error: problemText(.cargoKg),
                       keyboard: .numberPad)
            ElchiField(text: digits(\.cargoLitres, max: 5), label: strings.t("driverProfileForm.cargoLitres"), error: problemText(.cargoLitres),
                       keyboard: .numberPad)
        }
        // The driver's own car only (DESIGN06 2.9), like Android.
        if let vehicle = driver.vehicle {
            ElchiCard {
                CardRow(strings.t("driverProfileForm.vehicleStatus"),
                        "\(vehicle.makeModel) · \(vehicle.plateMasked) · \(strings.tOrNil("vehicleStatus.\(vehicle.verificationStatus)") ?? vehicle.verificationStatus)",
                        first: true)
            }
            .accessibilityIdentifier("elchi.driver.vehicleStatus")
        }
        if locked && driver.vehicle?.verificationStatus != "approved" {
            Text(strings.t("driverProfileForm.routesAfterReview")).font(ElchiFont.caption).foregroundStyle(c.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
        if locked {
            // DESIGN06 2.11: changes go through the operator (the Help screen's ticket form).
            ElchiButton(strings.t("driver.form.askOperator"), variant: .neutral, icon: .head, action: onSupport)
                .accessibilityIdentifier("elchi.driver.form.askOperator")
        }
    }

    /// The duplicate-plate sentence goes under the plate field (while it can still be changed).
    private var plateTakenText: String? {
        guard let error = form.saveError, !form.vehicleLocked,
              case .key("driver.error.plateTaken", _) = DriverErrorText.sentence(error) else { return nil }
        return strings.t("driver.error.plateTaken")
    }

    private func digits(_ field: WritableKeyPath<DriverForm, String>, max: Int) -> Binding<String> {
        Binding(get: { form.form[keyPath: field] }, set: { form.form[keyPath: field] = String($0.filter(\.isNumber).prefix(max)) })
    }

    private func problemText(_ field: DriverFormField) -> String? {
        guard let problem = form.problem(field) else { return nil }
        return strings.t(DriverFormRules.messageKey(field, problem))
    }
}
