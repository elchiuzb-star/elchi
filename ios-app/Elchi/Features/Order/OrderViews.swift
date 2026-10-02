import PhotosUI
import SwiftUI

// MARK: - Step 1: route summary

enum WindowEdge: String, Identifiable {
    case start, end
    var id: String { rawValue }
}

/// Both places (with "O'zgartirish"), the server's route figures and districts, the departure window (Tashkent) and
/// the price. "Saqlash" stays grey while anything is missing, and the missing things are listed under it.
struct RouteSummaryView: View {
    @Bindable var model: ParcelRequestModel
    let onBack: () -> Void
    let onChange: (EndSide) -> Void
    let onSave: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var priceText = ""
    @State private var editing: WindowEdge?
    @State private var availability = MapAvailability.shared
    /// While the price is typed the "Jami" card under it stays above the number pad.
    @State private var priceFocused = false
    private static let totalID = "route.total"

    var body: some View {
        let blockers = model.routeBlockers
        ScreenScaffold(title: strings.t("routeSummary.direction"), backLabel: strings.t("common.back"), onBack: onBack,
                       keepVisible: priceFocused ? Self.totalID : nil, keyboardDone: strings.t("client.keyboard.done")) {
            ElchiCard {
                endRow(.pickup, key: "routeSummary.pickup", first: true)
                endRow(.dropoff, key: "routeSummary.dropoff", first: false)
            }
            if let preview = model.preview {
                ElchiCard {
                    CardRow(strings.t("routeSummary.estimatedRoute"), strings.routeFigures(distanceM: preview.legDistanceM, durationS: preview.legDurationS),
                            first: true, detail: "\(strings.t("routeSummary.driverProposesTimeLine1")) \(strings.t("routeSummary.driverProposesTimeLine2"))")
                }
                if availability.isAvailable {
                    ElchiMap(markers: markers, polyline: model.routeLeg, interactive: false, placeholder: strings.t("client.map.unavailable"))
                        .frame(height: 220)
                        .clipShape(RoundedRectangle(cornerRadius: 20))
                }
                if let districts = preview.districtsOnRoute, !districts.isEmpty {
                    ElchiCard {
                        CardRow(strings.t("routeSummary.districtsTitle"), districts.joined(separator: " - "), first: true,
                                detail: strings.t("routeSummary.districtsHint"))
                    }
                }
            }
            PickerField(label: strings.t("listingOwner.windowStart"), value: model.windowStart.map(DepartureWindow.text),
                        placeholder: strings.t("client.routeSummary.windowPlaceholder"),
                        error: blockers.contains(.windowStart) || blockers.contains(.windowPast)) { editing = .start }
            PickerField(label: strings.t("listingOwner.windowEnd"), value: model.windowEnd.map(DepartureWindow.text),
                        placeholder: strings.t("client.routeSummary.windowPlaceholder"), hint: strings.t("routeSummary.windowHint"),
                        error: blockers.contains(.windowEnd) || blockers.contains(.endAfterStart)) { editing = .end }
            let taxi = model.mode == .passenger
            if taxi {
                // Taksi (design 'seat-picker'): how many people, on a cabin picture - only the count is booked.
                SeatPickerView(selected: $model.seats)
            }
            ElchiField(text: $priceText, label: strings.t(taxi ? "routeSummary.pricePerPerson" : "listingOwner.priceLabel"), keyboard: .numberPad,
                       onFocus: { priceFocused = $0 })
                .onChange(of: priceText) { _, typed in
                    model.priceDigits = Money.soumDigits(typed)
                    let formatted = Money.grouped(model.priceDigits)
                    if priceText != formatted { priceText = formatted }
                }
            ElchiCard(tint: .blue) {
                if taxi {
                    CardRow(strings.t("common.total"), strings.money(model.passengerTotalMinor), first: true,
                            detail: "\(strings.seatsTotal(model.seats.count, unitMinor: model.priceMinor)) · \(strings.t("routeSummary.driversSendOffers"))",
                            strong: true)
                } else {
                    CardRow(strings.t("common.total"), strings.money(model.priceMinor), first: true, detail: strings.t("routeSummary.driversSendOffers"),
                            strong: true)
                }
            }
            .accessibilityIdentifier("elchi.route.total")
            .id(Self.totalID)
        } footer: {
            ElchiButton(strings.t("common.save"), action: onSave).disabled(!blockers.isEmpty)
            if !blockers.isEmpty {
                Note(blockers.map { strings.t($0.key) }.joined(separator: " · "), tone: .err)
            }
        }
        .onAppear {
            model.suggestWindowIfEmpty()
            priceText = Money.grouped(model.priceDigits)
        }
        .sheet(item: $editing) { edge in
            WindowPickerSheet(title: strings.t(edge == .start ? "listingOwner.windowStart" : "listingOwner.windowEnd"),
                              initial: (edge == .start ? model.windowStart : model.windowEnd) ?? DepartureWindow.suggested().start) { date in
                if edge == .start { model.windowStart = date } else { model.windowEnd = date }
                editing = nil
            }
        }
    }

    private var markers: [MapMarker] {
        [model.pickup.map { MapMarker($0.point, .origin) }, model.dropoff.map { MapMarker($0.point, .destination) }].compactMap { $0 }
    }

    @ViewBuilder
    private func endRow(_ side: EndSide, key: String, first: Bool) -> some View {
        if let end = model.end(side) {
            CardRow(strings.t(key), strings.address(end), first: first, detail: strings.area(end), trailing: strings.t("app.route.change")) { onChange(side) }
        } else {
            CardRow(strings.t(key), strings.t("app.route.noAddress"), first: first, trailing: strings.t("app.route.change"), placeholder: true) {
                onChange(side)
            }
        }
    }
}

/// Date and time in Asia/Tashkent, whatever zone the phone is in (also the listing edit screen's picker).
struct WindowPickerSheet: View {
    let title: String
    let onDone: (Date) -> Void
    @State private var date: Date
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    init(title: String, initial: Date, onDone: @escaping (Date) -> Void) {
        self.title = title
        self.onDone = onDone
        _date = State(initialValue: initial)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(title).font(ElchiFont.section).foregroundStyle(c.text)
            DatePicker(title, selection: $date, in: Date()..., displayedComponents: [.date, .hourAndMinute])
                .datePickerStyle(.graphical)
                .labelsHidden()
                .tint(c.brand)
                .environment(\.timeZone, DepartureWindow.timeZone)
                .environment(\.locale, Locale(identifier: strings.locale == .ru ? "ru_RU" : "uz_UZ"))
            Text(DepartureWindow.text(date)).font(ElchiFont.bodyStrong).foregroundStyle(c.text).frame(maxWidth: .infinity)
            ElchiButton(strings.t("common.confirm")) { onDone(date) }
        }
        .padding(20)
        .background(c.card.ignoresSafeArea())
        .presentationDetents([.large])
    }
}

// MARK: - Step 2: contacts

/// Sender (prefilled from the signed-in person) and receiver. Phones are hidden from drivers until an offer is
/// accepted (Q43) - the note says so.
struct ContactsView: View {
    @Bindable var model: ParcelRequestModel
    let onBack: () -> Void
    let onContinue: () -> Void
    @Environment(LocaleStore.self) private var strings

    var body: some View {
        ScreenScaffold(title: strings.t("orderForm.contactTitle"), backLabel: strings.t("common.back"), onBack: onBack) {
            if let pickup = model.pickup, let dropoff = model.dropoff {
                ElchiCard(tint: .field) {
                    CardRow(strings.t("routeSummary.direction"), "\(strings.title(pickup)) → \(strings.title(dropoff))", first: true)
                }
            }
            ElchiField(text: $model.contacts.senderName, label: strings.t("orderForm.senderName"), contentType: .name)
            PhoneField(label: strings.t("orderForm.senderPhone"), digits: $model.contacts.senderPhone)
            ElchiField(text: $model.contacts.receiverName, label: strings.t("orderForm.receiverName"))
            PhoneField(label: strings.t("orderForm.receiverPhone"), digits: $model.contacts.receiverPhone)
            ElchiField(text: $model.contacts.comment, label: strings.t("listingOwner.commentLabel"), multiline: true)
            Note(strings.t("orderForm.phonesHidden"))
        } footer: {
            ElchiButton(strings.t("common.continue"), action: onContinue).disabled(!model.contacts.isComplete)
        }
    }
}

/// `+998 | 90 123 45 67`: fixed prefix, digits formatted as typed (the sign-in phone field's behaviour).
private struct PhoneField: View {
    let label: String
    @Binding var digits: String
    @Environment(\.elchi) private var c
    @State private var text = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label).font(ElchiFont.label).foregroundStyle(c.text)
            HStack(spacing: 10) {
                Text("+998").font(ElchiFont.bodyStrong).foregroundStyle(c.text)
                Rectangle().fill(c.outline).frame(width: 1, height: 22)
                // Local text re-synced after every edit: SwiftUI's TextField ignores a binding that rewrites the input.
                TextField("", text: $text, prompt: Text("__ ___ __ __").foregroundStyle(c.placeholder))
                    .onChange(of: text) { _, typed in
                        digits = UzPhone.localDigits(typed)
                        let formatted = UzPhone.formatLocal(digits)
                        if text != formatted { text = formatted }
                    }
                    .font(.system(size: 15, design: .monospaced))
                    .foregroundStyle(c.text)
                    .keyboardType(.phonePad)
                    .textContentType(.telephoneNumber)
                    .tint(c.brand)
                    .accessibilityLabel(label)
            }
            .padding(.horizontal, 16)
            .frame(minHeight: 52)
            .background(c.field, in: RoundedRectangle(cornerRadius: ElchiShape.field))
        }
        .onAppear { text = UzPhone.formatLocal(digits) }
    }
}

// MARK: - Step 3: parcel

/// What is sent (type) and how big (a category from the server catalogue only, Q140 - never typed numbers), plus
/// the prohibited-items list with its honest states.
struct ParcelView: View {
    @Bindable var model: ParcelRequestModel
    let onBack: () -> Void
    let onContinue: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        ScreenScaffold(title: strings.t("orderForm.parcelTitle"), backLabel: strings.t("common.back"), onBack: onBack) {
            SectionTitle(strings.t("orderForm.parcelType"))
            OptionGrid(ParcelType.allCases.map { ($0, strings.parcelTypeName($0)) }, selected: model.parcelType) { model.parcelType = $0 }
            SectionTitle(strings.t("parcelCategory.label"), description: strings.t("parcelCategory.hint"))
            categories
            policySection
        } footer: {
            ElchiButton(strings.t("common.continue"), action: onContinue).disabled(!model.parcelReady)
        }
        .task { await model.loadParcelCatalog() }
    }

    @ViewBuilder
    private var categories: some View {
        switch model.catalog {
        case .loading:
            Text(strings.t("parcelCategory.loading")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
            SkeletonCards(count: 2)
        case .failed:
            Note(strings.t("parcelCategory.loadFailed"), tone: .err)
            ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.retryParcelCatalog() } }
        case .loaded(let catalog):
            if !catalog.confirmed { Note(strings.t("parcelCategory.unconfirmed"), tone: .warn) }
            VStack(spacing: 8) {
                ForEach(catalog.items ?? [], id: \.id) { item in
                    RadioCard(icon: item.icon, title: strings.name(item), detail: strings.limits(item), selected: model.categoryId == item.id) {
                        model.categoryId = item.id
                    }
                    .disabled(!catalog.confirmed)
                }
            }
            if catalog.synthetic == true { Note(strings.t("parcelCategory.synthetic"), tone: .warn) }
        }
    }

    @ViewBuilder
    private var policySection: some View {
        switch model.policy {
        case .loading:
            SkeletonCards(count: 1)
        case .failed:
            SectionTitle(strings.t("parcelPolicy.title"))
            Note(strings.t("parcelPolicy.loadFailed"), tone: .err)
        case .loaded(let policy):
            if !policy.approved {
                SectionTitle(strings.t("parcelPolicy.title"))
                Note(strings.t("parcelPolicy.unconfirmed"), tone: .warn)
            } else {
                ElchiCard {
                    HStack(spacing: 8) {
                        Text(strings.t("parcelPolicy.title")).font(ElchiFont.poppins(15, .semibold)).foregroundStyle(c.text).lineLimit(1)
                        Spacer(minLength: 0)
                        if let badge = policyBadge(policy) { Badge(badge, tone: .blue) }
                    }
                    .padding(.top, 12).padding(.bottom, 4)
                    let items = policy.items ?? []
                    if items.isEmpty {
                        Text(strings.t("parcelPolicy.empty")).font(ElchiFont.caption).foregroundStyle(c.muted).padding(.vertical, 10)
                    }
                    ForEach(items, id: \.code) { item in
                        CardRow(strings.tOrNil("parcelPolicy.category.\(item.category)") ?? item.category, item.title, detail: policyDetail(item))
                    }
                }
            }
        }
    }

    private func policyBadge(_ policy: ParcelPolicyDTO) -> String? {
        let parts = [policy.label, policy.effectiveFrom.map { strings.t("parcelPolicy.effectiveFrom", ("date", strings.day($0))) }].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private func policyDetail(_ item: ParcelPolicyItemDTO) -> String? {
        let applies = item.appliesTo.flatMap { strings.tOrNil("parcelPolicy.appliesTo.\($0)") }
        let source: String? = item.sourceRef.map { ref in
            item.sourceCheckedOn.map { strings.t("parcelPolicy.sourceChecked", ("source", ref), ("date", strings.day($0))) }
                ?? strings.t("parcelPolicy.source", ("source", ref))
        }
        let parts = [applies, source].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }
}

// MARK: - Step 4: photo

/// One parcel photo (camera or gallery), uploaded at once. The web client requires it and so does the design.
struct PhotoView: View {
    let model: ParcelRequestModel
    let onBack: () -> Void
    let onContinue: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var askSource = false
    @State private var showGallery = false
    @State private var showCamera = false
    @State private var galleryItem: PhotosPickerItem?
    @State private var unreadable = false

    var body: some View {
        ScreenScaffold(title: strings.t("orderForm.photoTitle"), backLabel: strings.t("common.back"), onBack: onBack) {
            UploadBox(title: strings.t(model.photo.image == nil ? "orderForm.uploadPhoto" : "client.photo.replace"),
                      description: strings.t("orderForm.uploadPhotoHint")) { askSource = true }
            if let image = model.photo.image {
                Image(uiImage: image).resizable().scaledToFill()
                    .frame(maxWidth: .infinity).frame(height: 180)
                    .clipShape(RoundedRectangle(cornerRadius: 18))
                    .accessibilityLabel(strings.t("orderForm.photoAlt"))
            }
            status
        } footer: {
            ElchiButton(strings.t("orderForm.reviewOrder"), action: onContinue).disabled(model.photoFileId == nil)
        }
        .confirmationDialog(strings.t("orderForm.uploadPhoto"), isPresented: $askSource, titleVisibility: .visible) {
            if UIImagePickerController.isSourceTypeAvailable(.camera) {
                Button(strings.t("client.photo.camera")) { showCamera = true }
            }
            Button(strings.t("client.photo.gallery")) { openGallery() }
            Button(strings.t("common.cancel"), role: .cancel) {}
        }
        .photosPicker(isPresented: $showGallery, selection: $galleryItem, matching: .images)
        .onChange(of: galleryItem) { _, item in
            guard let item else { return }
            galleryItem = nil
            Task {
                if let data = try? await item.loadTransferable(type: Data.self), let image = UIImage(data: data) {
                    unreadable = false
                    await model.setPhoto(image)
                } else {
                    unreadable = true
                }
            }
        }
        .fullScreenCover(isPresented: $showCamera) {
            CameraPicker { image in
                showCamera = false
                if let image { Task { await model.setPhoto(image) } }
            }
            .ignoresSafeArea()
        }
    }

    @ViewBuilder
    private var status: some View {
        if unreadable {
            Note(strings.t("client.photo.unreadable"), tone: .err)
        }
        switch model.photo {
        case .none:
            EmptyView()
        case .uploading:
            HStack(spacing: 8) {
                ProgressView()
                Text(strings.t("app.photo.loading")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
            }
        case .uploaded:
            HStack(spacing: 6) {
                ElchiIcon.checkC.image(size: 14)
                Text(strings.t("orderForm.photoReady")).font(ElchiFont.label)
            }
            .foregroundStyle(c.onBrand)
            .padding(.horizontal, 14).padding(.vertical, 8)
            .background(c.brand, in: Capsule())
            .accessibilityElement(children: .combine)
        case .failed(_, let error):
            Note(strings.errorText(error), tone: .err)
            ElchiButton(strings.t("app.photo.reload"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.retryPhoto() } }
        }
    }

    private func openGallery() {
        #if DEBUG
        // UI tests cannot drive the system photo picker reliably: they get a generated photo instead.
        if ProcessInfo.processInfo.arguments.contains("-uiTestFakePhoto") {
            Task { await model.setPhoto(Self.testPhoto()) }
            return
        }
        #endif
        showGallery = true
    }

    #if DEBUG
    private static func testPhoto() -> UIImage {
        UIGraphicsImageRenderer(size: CGSize(width: 1200, height: 900)).image { context in
            UIColor(red: 0.85, green: 0.93, blue: 1, alpha: 1).setFill()
            context.fill(CGRect(x: 0, y: 0, width: 1200, height: 900))
            UIColor(red: 0.55, green: 0.40, blue: 0.25, alpha: 1).setFill()
            context.fill(CGRect(x: 350, y: 250, width: 500, height: 400))
        }
    }
    #endif
}

/// The system camera (UIKit): SwiftUI has no camera picker of its own. Also the driver documents' camera.
struct CameraPicker: UIViewControllerRepresentable {
    let onDone: (UIImage?) -> Void

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ controller: UIImagePickerController, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(onDone: onDone) }

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let onDone: (UIImage?) -> Void
        init(onDone: @escaping (UIImage?) -> Void) { self.onDone = onDone }

        func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            onDone(info[.originalImage] as? UIImage)
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) { onDone(nil) }
    }
}

// MARK: - Step 5: review

/// Everything on one card, then publish (create the draft + publish it) or go back to edit.
struct ReviewView: View {
    let model: ParcelRequestModel
    let onBack: () -> Void
    let onEdit: () -> Void
    let onPublished: () -> Void
    @Environment(LocaleStore.self) private var strings

    var body: some View {
        ScreenScaffold(title: strings.t("orderForm.review.title"), backLabel: strings.t("common.back"), onBack: onBack) {
            if let pickup = model.pickup, let dropoff = model.dropoff {
                ElchiCard {
                    CardRow(strings.t("routeSummary.direction"), "\(strings.title(pickup)) → \(strings.title(dropoff))", first: true,
                            detail: model.preview?.corridorName)
                    CardRow(strings.t("orderForm.review.pickupPlace"), strings.address(pickup), detail: strings.area(pickup))
                    CardRow(strings.t("orderForm.review.dropoffPlace"), strings.address(dropoff), detail: strings.area(dropoff))
                    if let preview = model.preview {
                        CardRow(strings.t("routeSummary.estimatedRoute"), strings.routeFigures(distanceM: preview.legDistanceM, durationS: preview.legDurationS))
                        if let districts = preview.districtsOnRoute, !districts.isEmpty {
                            CardRow(strings.t("home.routeDistricts"), districts.joined(separator: " - "), detail: strings.t("orderForm.review.districtsDetail"))
                        }
                    }
                    if let start = model.windowStart, let end = model.windowEnd {
                        CardRow(strings.t("orderForm.review.window"), "\(DepartureWindow.shortText(start)) - \(DepartureWindow.shortText(end))")
                    }
                    if model.mode == .passenger {
                        CardRow(strings.t("orderForm.review.passengers"), strings.t("orderForm.review.peopleCount", ("count", model.seats.count)),
                                detail: strings.t("orderForm.review.seatNegotiated"))
                        let perPerson = strings.t("orderForm.review.perPersonDetail", ("count", model.seats.count), ("price", strings.money(model.priceMinor)))
                        CardRow(strings.t("common.price"), strings.money(model.passengerTotalMinor),
                                detail: "\(perPerson) · \(strings.t("orderForm.review.driversSendOffers"))")
                    } else {
                        parcelRows
                    }
                }
            }
            if model.listingCreate == nil {
                Note(strings.t(model.mode == .passenger ? "orderForm.review.incompletePassenger" : "orderForm.review.incompleteParcel"), tone: .err)
            }
            if let error = model.publishError {
                Note(strings.errorText(error), tone: .err)
            }
        } footer: {
            ElchiButton(strings.t("orderForm.review.publish"), loading: model.publishing) {
                Task { if await model.publish() { onPublished() } }
            }
            .disabled(model.listingCreate == nil)
            ElchiButton(strings.t("listingOwner.edit"), variant: .ghost, size: .medium, action: onEdit)
        }
    }

    /// The parcel's own rows: price, what is sent, both people, the photo, the comment.
    @ViewBuilder
    private var parcelRows: some View {
        CardRow(strings.t("common.price"), strings.money(model.priceMinor), detail: strings.t("orderForm.review.driversSendOffers"))
        if let type = model.parcelType {
            CardRow(strings.t("orderForm.review.parcel"), strings.parcelTypeName(type),
                    detail: model.selectedCategory.map { "\(strings.name($0)) · \(strings.limits($0))" })
        }
        CardRow(strings.t("orderForm.review.sender"), model.contacts.senderName, detail: UzPhone.display(UzPhone.e164(model.contacts.senderPhone)))
        CardRow(strings.t("orderForm.review.receiver"), model.contacts.receiverName,
                detail: UzPhone.display(UzPhone.e164(model.contacts.receiverPhone)))
        CardRow(strings.t("orderForm.photoTitle"), strings.t(model.photoFileId == nil ? "app.photo.none" : "orderForm.review.uploaded"))
        let comment = model.contacts.comment.trimmingCharacters(in: .whitespacesAndNewlines)
        if !comment.isEmpty { CardRow(strings.t("listingOwner.commentLabel"), comment) }
    }
}

// MARK: - Published

/// Done: what happens next, and one note per server warning (never a raw code).
struct SuccessView: View {
    let model: ParcelRequestModel
    let onDone: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        VStack(spacing: 0) {
            Banner(strings.t("orderForm.success.title"), tone: .ok)
            ScrollView {
                VStack(spacing: 12) {
                    EmptyState(icon: .checkC, title: strings.t("orderForm.success.title"),
                               description: "\(strings.t("orderForm.success.waiting")). \(strings.t("orderForm.success.notify")).")
                    ForEach(model.published?.warnings ?? [], id: \.code) { warning in
                        Note(strings.warningText(warning), tone: .warn)
                    }
                }
                .padding(EdgeInsets(top: 40, leading: 20, bottom: 20, trailing: 20))
            }
            ElchiButton(strings.t("orderForm.success.toOrders"), action: onDone)
                .padding(EdgeInsets(top: 12, leading: 16, bottom: 6, trailing: 16))
                .background(c.card.ignoresSafeArea(edges: .bottom))
                .overlay(alignment: .top) { Rectangle().fill(c.line).frame(height: 1) }
        }
        .background(c.page.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
        .navigationBarBackButtonHidden()
    }
}
