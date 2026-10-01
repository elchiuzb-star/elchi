import SwiftUI

/// "Haydovchi profili": the name (always editable) and the car, entered once (Q94). The first save sends the v1
/// PATCH and registers the same car as the v2 vehicle; from then on model, colour and plate are read-only (and seats
/// and cargo once the v2 vehicle exists), and Save sends the name only.
struct DriverProfileFormView: View {
    let driver: DriverModel
    let form: DriverProfileFormModel
    let onBack: () -> Void
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
                    let saved = await form.save()
                    dismissKeyboard()
                    if saved { banners.ok("driverProfileForm.saved") }
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
    }

    @ViewBuilder
    private var fields: some View {
        @Bindable var form = form
        let locked = form.vehicleLocked
        let hasVehicle = form.hasVehicle
        let lockHint = strings.t("driverProfileForm.vehicleLockedHint")
        ElchiField(text: $form.form.fullName, label: strings.t("driverProfileForm.fullName"), error: problemText(.fullName),
                   contentType: .name)
        if locked {
            Note(strings.t("driverProfileForm.vehicleLockedBody"), tone: .blue, title: strings.t("driverProfileForm.vehicleLockedTitle"))
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
            // Under the car's own fields, where the design puts it (and above the fold).
            Note(strings.t("driver.profile.lockWarning"), tone: .warn)
        }
        if hasVehicle {
            LockedField(label: strings.t("driverProfileForm.passengerSeats"), value: form.form.seats, hint: lockHint)
            LockedField(label: strings.t("driverProfileForm.cargoKg"), value: form.form.cargoKg, hint: lockHint)
            LockedField(label: strings.t("driverProfileForm.cargoLitres"), value: form.form.cargoLitres, hint: lockHint)
        } else {
            ElchiField(text: digits(\.seats, max: 1), label: strings.t("driverProfileForm.passengerSeats"), error: problemText(.seats),
                       keyboard: .numberPad)
            ElchiField(text: digits(\.cargoKg, max: 5), label: strings.t("driverProfileForm.cargoKg"), error: problemText(.cargoKg),
                       keyboard: .numberPad)
            ElchiField(text: digits(\.cargoLitres, max: 5), label: strings.t("driverProfileForm.cargoLitres"), error: problemText(.cargoLitres),
                       keyboard: .numberPad)
        }
        ForEach(driver.vehicles ?? [], id: \.id) { vehicle in
            ElchiCard {
                CardRow(strings.t("driverProfileForm.vehicleStatus"),
                        "\(vehicle.makeModel) · \(vehicle.plateMasked) · \(strings.tOrNil("vehicleStatus.\(vehicle.verificationStatus)") ?? vehicle.verificationStatus)",
                        first: true)
            }
            .accessibilityIdentifier("elchi.driver.vehicleStatus")
        }
        if locked && !(driver.vehicles ?? []).contains(where: { $0.verificationStatus == "approved" }) {
            Text(strings.t("driverProfileForm.routesAfterReview")).font(ElchiFont.caption).foregroundStyle(c.muted)
                .fixedSize(horizontal: false, vertical: true)
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
        switch form.problem(field) {
        case .required?: strings.t("driver.form.required")
        case .seatsRange?: strings.t("listingOwner.invalid.seats")
        case .positive?: strings.t("driver.form.positiveNumber")
        case nil: nil
        }
    }
}
