import PhotosUI
import SwiftUI

// BOSQICH 02 ("Elchi Buyurtma Yaratish"): Pochta goes home -> route (1 / 3) -> contact (2 / 3) -> review (3 / 3);
// Taksi goes home -> review (1 / 1). Every step validates on tap (a red list at the top, red borders), and a step
// opened from the review's pencil saves with "Saqlash va qaytish" and goes back to the review.

/// "Jami" with the total and the line under it (route step).
struct TotalCard: View {
    let total: String
    let note: String
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        let ink = c.isDark ? c.tone(.blue).noteText : Color(hex: 0x0B3E73)
        VStack(alignment: .leading, spacing: 2) {
            Text(strings.t("common.total")).font(ElchiFont.caption).foregroundStyle(ink)
            Text(total).font(ElchiFont.poppins(18, .semibold)).foregroundStyle(c.text)
            Text(note).font(ElchiFont.caption).foregroundStyle(ink)
        }
        .padding(.horizontal, 16).padding(.vertical, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(c.isDark ? Color(hex: 0x0E2A45) : Color(hex: 0xEAF5FF), in: RoundedRectangle(cornerRadius: 18))
        .accessibilityElement(children: .combine)
    }
}

// MARK: - Step 1: route (Pochta)

/// Both places (with "O'zgartirish"), the server's estimate, the departure window tiles (Tashkent) and the price
/// stepper. "Saqlash" stays tappable: with something missing it lists what at the top.
struct RouteSummaryView: View {
    @Bindable var model: ParcelRequestModel
    let editing: Bool
    let onBack: () -> Void
    let onChange: (EndSide) -> Void
    let onSave: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var edge: WindowEdge?
    @State private var showErrors = false
    @State private var scrollTop = 0
    /// While the price is typed the "Jami" card under it stays above the number pad.
    @State private var priceFocused = false
    private static let totalID = "route.total"

    var body: some View {
        let blockers = model.routeBlockers
        let shown = showErrors ? blockers : []
        ScreenScaffold(title: strings.t("routeSummary.direction"), backLabel: strings.t("common.back"), onBack: onBack,
                       keepVisible: priceFocused ? Self.totalID : nil, keyboardDone: strings.t("client.keyboard.done"),
                       step: OrderStep.position(.route, mode: model.mode).map { ($0.index, $0.total) }, scrollTop: scrollTop) {
            if !shown.isEmpty { ErrorList(lines: shown.map { strings.t($0.key) }) }
            ElchiCard {
                endRow(.pickup, key: "routeSummary.pickup", first: true)
                endRow(.dropoff, key: "routeSummary.dropoff", first: false)
            }
            if let preview = model.preview {
                ElchiCard(tint: .blue) {
                    CardRow(strings.t("routeSummary.estimatedRoute"), strings.routeFigures(distanceM: preview.legDistanceM, durationS: preview.legDurationS),
                            first: true, strong: true)
                }
            }
            VStack(alignment: .leading, spacing: 6) {
                BlockLabel(text: strings.t("orderForm.review.window"))
                WindowTiles(start: model.windowStart, end: model.windowEnd, errorStart: shown.contains(where: \.marksStart),
                            errorEnd: shown.contains(where: \.marksEnd), onCard: true) { edge = $0 }
                Text(strings.windowHint(start: model.windowStart, end: model.windowEnd)).font(ElchiFont.caption).foregroundStyle(c.muted)
            }
            VStack(alignment: .leading, spacing: 6) {
                BlockLabel(text: strings.t("common.price"))
                PriceStepper(digits: $model.priceDigits, label: strings.t("common.price"), error: shown.contains(.price), onCard: true,
                             onFocus: { priceFocused = $0 })
                Text(strings.t("client.order.priceStepHint")).font(ElchiFont.caption).foregroundStyle(c.muted)
            }
            TotalCard(total: model.priceMinor > 0 ? strings.money(model.priceMinor) : "—", note: strings.t("routeSummary.driversSendOffers"))
                .accessibilityIdentifier("elchi.route.total")
                .id(Self.totalID)
        } footer: {
            ElchiButton(strings.t(editing ? "client.order.saveAndReturn" : "common.save"), dimmed: !blockers.isEmpty) {
                if blockers.isEmpty {
                    onSave()
                } else {
                    showErrors = true
                    scrollTop += 1
                }
            }
            .accessibilityIdentifier("elchi.route.save")
        }
        .onAppear { model.suggestWindowIfEmpty() }
        .sheet(item: $edge) { edge in
            DepartureWindowSheet(edge: edge, start: model.windowStart, end: model.windowEnd) { start, end in
                model.windowStart = start
                model.windowEnd = end
                self.edge = nil
            }
        }
    }

    @ViewBuilder
    private func endRow(_ side: EndSide, key: String, first: Bool) -> some View {
        if let end = model.end(side) {
            CardRow(strings.t(key), strings.place(end), first: first, detail: strings.area(end), trailing: strings.t("app.route.change")) { onChange(side) }
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

// MARK: - Step 2: contact (Pochta)

/// "Jo'natma ma'lumotlari": sender and receiver as contact cards (the sender prefilled from the account), what is
/// sent and how big (sheets; sizes only from the server catalogue, Q140), the photo inline, the prohibited-items list
/// in a sheet, the comment. Phones stay hidden from drivers until an offer is accepted (Q43).
struct ContactsView: View {
    @Bindable var model: ParcelRequestModel
    let editing: Bool
    let onBack: () -> Void
    let onContinue: () -> Void
    /// A short confirmation over the screen ("Qabul qiluvchi: Dilnoza").
    let toast: (String) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    enum Sheet: String, Identifiable {
        case sender, receiver, type, size, ban
        var id: String { rawValue }
    }

    @State private var sheet: Sheet?
    @State private var showErrors = false
    @State private var scrollTop = 0
    @State private var askSource = false
    @State private var showGallery = false
    @State private var showCamera = false
    @State private var galleryItem: PhotosPickerItem?
    @State private var unreadable = false

    var body: some View {
        let blockers = model.contactBlockers
        let shown = showErrors ? blockers : []
        ScreenScaffold(title: strings.t("client.order.contactTitle"), backLabel: strings.t("common.back"), onBack: onBack,
                       keyboardDone: strings.t("client.keyboard.done"),
                       step: OrderStep.position(.contact, mode: model.mode).map { ($0.index, $0.total) }, scrollTop: scrollTop) {
            if !shown.isEmpty { ErrorList(lines: shown.map { strings.t($0.key) }) }
            ContactCard(label: strings.t("orderForm.review.sender"), name: model.contacts.senderName, phone: model.contacts.senderPhone,
                        error: shown.contains(.senderName) || shown.contains(.senderPhone)) { sheet = .sender }
                .accessibilityIdentifier("elchi.contact.sender")
            ContactCard(label: strings.t("orderForm.review.receiver"), name: model.contacts.receiverName, phone: model.contacts.receiverPhone,
                        error: shown.contains(.receiverName) || shown.contains(.receiverPhone)) { sheet = .receiver }
                .accessibilityIdentifier("elchi.contact.receiver")
            VStack(alignment: .leading, spacing: 6) {
                BlockLabel(text: strings.t("client.order.parcelSection"))
                VStack(spacing: 0) {
                    selectRow(strings.t("client.order.typeRow"), value: model.parcelType.map(strings.parcelTypeName), detail: nil,
                              error: shown.contains(.type), first: true) { sheet = .type }
                        .accessibilityIdentifier("elchi.parcel.type")
                    selectRow(strings.t("client.order.sizeRow"), value: model.selectedCategory.map(strings.name),
                              detail: model.selectedCategory.map(strings.limits), error: shown.contains(.size), first: false) { sheet = .size }
                        .accessibilityIdentifier("elchi.parcel.size")
                }
                .background(c.card, in: RoundedRectangle(cornerRadius: 18))
                .clipShape(RoundedRectangle(cornerRadius: 18))
                .shadow(color: c.shadow.opacity(0.6), radius: 12, y: 6)
            }
            if model.catalog.value?.confirmed == false {
                Note(strings.t("parcelCategory.unconfirmed"), tone: .warn)
            }
            VStack(alignment: .leading, spacing: 6) {
                BlockLabel(text: strings.t("orderForm.photoTitle"))
                photoTile(error: shown.contains(.photo))
                photoStatus
            }
            Button { sheet = .ban } label: {
                HStack(spacing: 6) {
                    ElchiIcon.alert.image(size: 16)
                    Text(strings.t("client.order.banLink")).font(ElchiFont.poppins(13.5, .semibold))
                }
                .foregroundStyle(c.accentText)
                .frame(minHeight: 36)
                .contentShape(Rectangle())
            }
            .buttonStyle(PressFade())
            .accessibilityIdentifier("elchi.parcel.banLink")
            NoteField(text: $model.contacts.comment)
            Note(strings.t("orderForm.phonesHidden"))
        } footer: {
            ElchiButton(strings.t(editing ? "client.order.saveAndReturn" : "common.continue"), dimmed: !blockers.isEmpty) {
                if blockers.isEmpty {
                    onContinue()
                } else {
                    showErrors = true
                    scrollTop += 1
                }
            }
            // Q140: without a confirmed catalogue there is no size to choose, so the step cannot finish (as before).
            .disabled(model.catalog.value?.confirmed == false)
            .accessibilityIdentifier("elchi.contact.continue")
        }
        .task { await model.loadParcelCatalog() }
        .sheet(item: $sheet) { which in sheetView(which) }
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

    // MARK: Rows

    private func selectRow(_ key: String, value: String?, detail: String?, error: Bool, first: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Text(key).font(ElchiFont.poppins(13)).foregroundStyle(c.muted).frame(width: 62, alignment: .leading)
                VStack(alignment: .leading, spacing: 0) {
                    Text(value ?? strings.t("client.order.choose")).font(ElchiFont.poppins(15, value == nil ? .regular : .semibold))
                        .foregroundStyle(value == nil ? c.placeholder : c.text).lineLimit(1)
                    if let detail { Text(detail).font(ElchiFont.caption).foregroundStyle(c.muted) }
                }
                Spacer(minLength: 0)
                ElchiIcon.chevD.image(size: 16).foregroundStyle(c.placeholder)
            }
            .padding(.horizontal, 14).padding(.vertical, 8)
            .frame(minHeight: 54)
            .overlay(alignment: .leading) { if error { Rectangle().fill(c.tone(.err).fg.opacity(0.75)).frame(width: 3) } }
            .overlay(alignment: .top) { if !first { Rectangle().fill(c.field).frame(height: 1) } }
            .contentShape(Rectangle())
        }
        .buttonStyle(PressFade())
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
    }

    // MARK: Photo

    @ViewBuilder
    private func photoTile(error: Bool) -> some View {
        if let image = model.photo.image {
            HStack(spacing: 12) {
                Image(uiImage: image).resizable().scaledToFill()
                    .frame(width: 64, height: 64)
                    .clipShape(RoundedRectangle(cornerRadius: 14))
                    .accessibilityLabel(strings.t("orderForm.photoAlt"))
                VStack(alignment: .leading, spacing: 2) {
                    switch model.photo {
                    case .uploading:
                        HStack(spacing: 6) {
                            ProgressView().controlSize(.small)
                            Text(strings.t("app.photo.loading")).font(ElchiFont.poppins(13, .semibold)).foregroundStyle(c.muted)
                        }
                    case .failed:
                        Text(strings.t("app.photo.reload")).font(ElchiFont.poppins(13, .semibold)).foregroundStyle(c.tone(.err).fg)
                    default:
                        HStack(spacing: 6) {
                            ElchiIcon.checkC.image(size: 14)
                            Text(strings.t("orderForm.photoReady")).font(ElchiFont.poppins(13, .semibold))
                        }
                        .foregroundStyle(c.tone(.ok).noteText)
                    }
                    Text(strings.t("client.order.photoDriverSees")).font(ElchiFont.caption).foregroundStyle(c.muted).lineLimit(1)
                }
                Spacer(minLength: 0)
                Button { askSource = true } label: {
                    ElchiIcon.refresh.image(size: 18).foregroundStyle(c.softText)
                        .frame(width: 40, height: 40).background(c.soft, in: Circle())
                }
                .buttonStyle(PressFade())
                .accessibilityLabel(strings.t("client.order.photoReplaceShort"))
                Button { model.removePhoto() } label: {
                    ElchiIcon.trash.image(size: 16).foregroundStyle(c.tone(.err).fg)
                        .frame(width: 40, height: 40).background(c.tone(.err).bg, in: Circle())
                }
                .buttonStyle(PressFade())
                .accessibilityLabel(strings.t("common.delete"))
                .accessibilityIdentifier("elchi.photo.delete")
            }
            .padding(8)
            .background(c.card, in: RoundedRectangle(cornerRadius: 18))
            .shadow(color: c.shadow.opacity(0.6), radius: 12, y: 6)
        } else {
            Button { askSource = true } label: {
                HStack(spacing: 12) {
                    ElchiIcon.camera.image(size: 20).foregroundStyle(c.accentText)
                        .frame(width: 40, height: 40).background(c.soft, in: Circle())
                    VStack(alignment: .leading, spacing: 1) {
                        Text(strings.t("orderForm.uploadPhoto")).font(ElchiFont.poppins(14, .semibold)).foregroundStyle(c.text)
                        Text(strings.t("client.order.photoDriverSees")).font(ElchiFont.caption).foregroundStyle(c.muted)
                    }
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 14).padding(.vertical, 10)
                .frame(minHeight: 62)
                .background(c.isDark ? Color(hex: 0x0F2233) : Color(hex: 0xF4FAFF), in: RoundedRectangle(cornerRadius: 18))
                .overlay {
                    RoundedRectangle(cornerRadius: 18)
                        .strokeBorder(error ? c.tone(.err).fg.opacity(0.75) : c.brand, style: StrokeStyle(lineWidth: 2, dash: [7, 5]))
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(PressFade())
            .accessibilityElement(children: .combine)
            .accessibilityAddTraits(.isButton)
            .accessibilityIdentifier("elchi.photo.add")
        }
    }

    @ViewBuilder
    private var photoStatus: some View {
        if unreadable {
            Note(strings.t("client.photo.unreadable"), tone: .err)
        }
        if case .failed(_, let error) = model.photo {
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

    // MARK: Sheets

    @ViewBuilder
    private func sheetView(_ which: Sheet) -> some View {
        switch which {
        case .sender, .receiver:
            let sender = which == .sender
            ContactPickerSheet(title: strings.t(sender ? "client.order.pickSender" : "client.order.pickReceiver"),
                               meName: model.user.fullName ?? "", mePhone: UzPhone.localDigits(fromE164: model.user.phone),
                               currentPhone: sender ? model.contacts.senderPhone : model.contacts.receiverPhone) { name, phone in
                if sender {
                    model.contacts.senderName = name
                    model.contacts.senderPhone = phone
                } else {
                    model.contacts.receiverName = name
                    model.contacts.receiverPhone = phone
                }
                sheet = nil
                toast(strings.t(sender ? "client.order.pickedSender" : "client.order.pickedReceiver", ("name", name)))
            }
        case .type:
            OptionSheet(title: strings.t("orderForm.parcelType"),
                        options: ParcelType.allCases.map { .init(id: $0.rawValue, icon: nil, title: strings.parcelTypeName($0), detail: nil,
                                                                 selected: model.parcelType == $0) }) { id in
                model.parcelType = ParcelType.allCases.first { $0.rawValue == id }
                sheet = nil
            }
        case .size:
            sizeSheet
        case .ban:
            BanSheet(model: model) { sheet = nil }
        }
    }

    @ViewBuilder
    private var sizeSheet: some View {
        let catalog = model.catalog.value
        let options: [OptionSheet<AnyView>.Option] = (catalog?.items ?? []).map {
            .init(id: $0.id, icon: $0.icon, title: strings.name($0), detail: strings.limits($0), selected: model.categoryId == $0.id,
                  enabled: catalog?.confirmed == true)
        }
        OptionSheet(title: strings.t("parcelCategory.label"), options: options,
                    note: catalog?.synthetic == true ? strings.t("parcelCategory.synthetic") : nil, onPick: { id in
                        model.categoryId = id
                        sheet = nil
                    }) {
            AnyView(sizeState)
        }
    }

    @ViewBuilder
    private var sizeState: some View {
        switch model.catalog {
        case .loading:
            Text(strings.t("parcelCategory.loading")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
            SkeletonCards(count: 2)
        case .failed:
            Note(strings.t("parcelCategory.loadFailed"), tone: .err)
            ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.retryParcelCatalog() } }
        case .loaded(let catalog):
            if !catalog.confirmed { Note(strings.t("parcelCategory.unconfirmed"), tone: .warn) }
        }
    }
}

/// "Taqiqlangan jo'natmalar" (7.6): the approved list with its label and date, or its honest state (unconfirmed,
/// failed, empty), and "Tushunarli".
struct BanSheet: View {
    let model: ParcelRequestModel
    let onClose: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 10) {
                    Text(strings.t("parcelPolicy.title")).font(ElchiFont.poppins(19, .medium)).foregroundStyle(c.text).accessibilityAddTraits(.isHeader)
                    Spacer(minLength: 0)
                    if let badge {
                        Text(badge).font(ElchiFont.badge).foregroundStyle(c.accentText).lineLimit(1)
                            .padding(.horizontal, 10).padding(.vertical, 4).background(c.soft, in: Capsule())
                    }
                }
                content
                ElchiButton(strings.t("client.order.banOk"), variant: .neutral, size: .pair, action: onClose).padding(.top, 4)
            }
            .padding(EdgeInsets(top: 24, leading: 16, bottom: 28, trailing: 16))
        }
        .background(c.card.ignoresSafeArea())
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
        .presentationCornerRadius(ElchiShape.sheet)
    }

    private var badge: String? {
        guard let policy = model.policy.value, policy.approved else { return nil }
        let date = policy.effectiveFrom.map(strings.day)
        if let label = policy.label, let date { return strings.t("client.order.banSince", ("label", label), ("date", date)) }
        return policy.label ?? policy.effectiveFrom.map { strings.t("parcelPolicy.effectiveFrom", ("date", strings.day($0))) }
    }

    @ViewBuilder
    private var content: some View {
        switch model.policy {
        case .loading:
            SkeletonCards(count: 1)
        case .failed:
            Note(strings.t("parcelPolicy.loadFailed"), tone: .err)
        case .loaded(let policy):
            if !policy.approved {
                Note(strings.t("parcelPolicy.unconfirmed"), tone: .warn)
            } else if (policy.items ?? []).isEmpty {
                Text(strings.t("parcelPolicy.empty")).font(ElchiFont.caption).foregroundStyle(c.muted)
            } else {
                ForEach(policy.items ?? [], id: \.code) { item in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(strings.tOrNil("parcelPolicy.category.\(item.category)") ?? item.category).font(ElchiFont.caption).foregroundStyle(c.muted)
                        Text(item.title).font(ElchiFont.poppins(14, .medium)).foregroundStyle(c.text)
                        if let detail = detail(item) { Text(detail).font(ElchiFont.caption).foregroundStyle(c.muted) }
                    }
                    .padding(.vertical, 10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .overlay(alignment: .top) { Rectangle().fill(c.field).frame(height: 1) }
                    .accessibilityElement(children: .combine)
                }
            }
        }
    }

    private func detail(_ item: ParcelPolicyItemDTO) -> String? {
        let applies = item.appliesTo.flatMap { strings.tOrNil("parcelPolicy.appliesTo.\($0)") }
        let source: String? = item.sourceRef.map { ref in
            item.sourceCheckedOn.map { strings.t("parcelPolicy.sourceChecked", ("source", ref), ("date", strings.day($0))) }
                ?? strings.t("parcelPolicy.source", ("source", ref))
        }
        let parts = [applies, source].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }
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

// MARK: - Review

/// "Buyurtmani tekshiring": every answer on one card, each with a pencil back to its step (the step then saves with
/// "Saqlash va qaytish" and returns here), then publish (create the draft + publish it) or "Tahrirlash".
struct ReviewView: View {
    let model: ParcelRequestModel
    let onBack: () -> Void
    /// The step to open for an edit (`.route` is the home itself for Taksi).
    let onEdit: (OrderStep) -> Void
    let onPublished: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        let taxi = model.mode == .passenger
        ScreenScaffold(title: strings.t("orderForm.review.title"), backLabel: strings.t("common.back"), onBack: onBack,
                       step: OrderStep.position(.review, mode: model.mode).map { ($0.index, $0.total) }) {
            if let pickup = model.pickup, let dropoff = model.dropoff {
                VStack(spacing: 0) {
                    row("routeSummary.direction", "\(strings.name(pickup.region)) → \(strings.name(dropoff.region))",
                        detail: model.preview?.corridorName, edit: .route, first: true)
                    row("orderForm.review.pickupPlace", strings.place(pickup), detail: strings.areaDetail(pickup), edit: .route)
                    row(taxi ? "client.taxi.dropoffPlace" : "orderForm.review.dropoffPlace", strings.place(dropoff),
                        detail: strings.areaDetail(dropoff), edit: .route)
                    if let preview = model.preview {
                        row("routeSummary.estimatedRoute", strings.routeFigures(distanceM: preview.legDistanceM, durationS: preview.legDurationS))
                    }
                    if let start = model.windowStart, let end = model.windowEnd {
                        row("orderForm.review.window", strings.windowLine(start: start, end: end), edit: .route)
                    }
                    if taxi { taxiRows } else { parcelRows }
                }
                .padding(.horizontal, 16).padding(.vertical, 4)
                .background(c.card, in: RoundedRectangle(cornerRadius: ElchiShape.card))
                .shadow(color: c.shadow.opacity(0.8), radius: 12, y: 6)
            }
            if model.listingCreate == nil {
                Note(strings.t(taxi ? "orderForm.review.incompletePassenger" : "orderForm.review.incompleteParcel"), tone: .err)
            }
            if let error = model.publishError {
                Note(strings.errorText(error), tone: .err)
            }
        } footer: {
            ElchiButton(strings.t(model.publishing ? "client.order.publishing" : "orderForm.review.publish")) {
                Task { if await model.publish() { onPublished() } }
            }
            .disabled(model.listingCreate == nil || model.publishing)
            .accessibilityIdentifier("elchi.review.publish")
            ElchiButton(strings.t("listingOwner.edit"), variant: .ghost, size: .medium) { onEdit(.route) }
                .disabled(model.publishing)
        }
    }

    @ViewBuilder
    private var taxiRows: some View {
        let count = model.seatCount ?? 1
        row("client.taxi.seats", TaxiSeats.isWholeCabin(count) ? strings.t("client.taxi.wholeCabinSeats")
                : strings.t("orderForm.review.peopleCount", ("count", count)), edit: .route)
        row("common.price", "\(strings.seatsTotal(count, unitMinor: model.priceMinor)) = \(strings.money(model.passengerTotalMinor))",
            detail: strings.t("orderForm.review.driversSendOffers"), edit: .route)
        let user = model.user
        row("client.taxi.passenger", user.fullName.flatMap { $0.isEmpty ? nil : $0 } ?? UzPhone.display(user.phone),
            detail: strings.t("client.taxi.accountData", ("phone", UzPhone.display(user.phone))))
    }

    /// The parcel's own rows: price, what is sent, both people, the photo, the comment.
    @ViewBuilder
    private var parcelRows: some View {
        row("common.price", strings.money(model.priceMinor), detail: strings.t("orderForm.review.driversSendOffers"), edit: .route)
        row("orderForm.review.parcel", model.parcelType.map(strings.parcelTypeName) ?? "—",
            detail: model.selectedCategory.map { "\(strings.name($0)) · \(strings.limits($0))" }, edit: .contact)
        row("orderForm.review.sender", model.contacts.senderName, detail: UzPhone.display(UzPhone.e164(model.contacts.senderPhone)), edit: .contact)
        row("orderForm.review.receiver", model.contacts.receiverName,
            detail: UzPhone.display(UzPhone.e164(model.contacts.receiverPhone)), edit: .contact)
        row("orderForm.photoTitle", strings.t(model.photoFileId == nil ? "client.order.photoNotUploaded" : "orderForm.review.uploaded"), edit: .contact)
        let comment = model.contacts.comment.trimmingCharacters(in: .whitespacesAndNewlines)
        if !comment.isEmpty { row("listingOwner.commentLabel", NoteText.masked(comment), edit: .contact) }
    }

    private func row(_ key: String, _ value: String, detail: String? = nil, edit: OrderStep? = nil, first: Bool = false) -> some View {
        VStack(spacing: 0) {
            if !first { Rectangle().fill(c.field).frame(height: 1) }
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(strings.t(key)).font(ElchiFont.caption).foregroundStyle(c.muted)
                    Text(value.isEmpty ? "—" : value).font(ElchiFont.poppins(14, .medium)).foregroundStyle(c.text).lineSpacing(2)
                        .fixedSize(horizontal: false, vertical: true)
                    if let detail, !detail.isEmpty {
                        Text(detail).font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
                    }
                }
                .accessibilityElement(children: .combine)
                Spacer(minLength: 0)
                if let edit {
                    Button { onEdit(edit) } label: {
                        Image(systemName: "pencil").font(.system(size: 13, weight: .semibold)).foregroundStyle(c.text)
                            .frame(width: 32, height: 32).background(c.field, in: Circle())
                            .frame(width: 44, height: 44).contentShape(Circle())
                    }
                    .buttonStyle(PressFade())
                    .disabled(model.publishing)
                    .accessibilityLabel("\(strings.t("listingOwner.edit")): \(strings.t(key))")
                    .accessibilityIdentifier("elchi.review.edit.\(key)")
                }
            }
            .padding(.vertical, 7)
        }
    }
}

// MARK: - Published

/// Done: what happens next, the summary (route, window, total), one note per server warning, then the orders list or a
/// new request of the same service.
struct SuccessView: View {
    let model: ParcelRequestModel
    let onOrders: () -> Void
    let onNewOrder: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(spacing: 14) {
                    VStack(spacing: 12) {
                        ElchiIcon.checkC.image(size: 40).foregroundStyle(c.tone(.ok).fg)
                            .frame(width: 84, height: 84).background(c.tone(.ok).bg, in: Circle())
                        Text(strings.t("orderForm.success.title")).font(ElchiFont.poppins(26, .medium)).foregroundStyle(c.text)
                            .accessibilityAddTraits(.isHeader)
                        Text("\(strings.t("orderForm.success.waiting")). \(strings.t("orderForm.success.notify")).")
                            .font(ElchiFont.secondary).foregroundStyle(c.muted).lineSpacing(3).frame(maxWidth: 300)
                    }
                    .multilineTextAlignment(.center)
                    .padding(.top, 40).padding(.bottom, 10)
                    if let published = model.published, let from = published.fromRegion, let to = published.toRegion {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("\(strings.name(from)) → \(strings.name(to))").font(ElchiFont.poppins(15, .semibold)).foregroundStyle(c.text)
                            Text(summaryLine(published)).font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
                        }
                        .padding(.horizontal, 16).padding(.vertical, 12)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(c.card, in: RoundedRectangle(cornerRadius: 18))
                        .shadow(color: c.shadow.opacity(0.8), radius: 12, y: 6)
                        .accessibilityElement(children: .combine)
                        .accessibilityIdentifier("elchi.success.summary")
                    }
                    ForEach(model.published?.warnings ?? [], id: \.code) { warning in
                        Note(strings.warningText(warning), tone: .warn)
                    }
                }
                .padding(EdgeInsets(top: 12, leading: 16, bottom: 20, trailing: 16))
            }
            VStack(spacing: 4) {
                ElchiButton(strings.t("orderForm.success.toOrders"), action: onOrders)
                ElchiButton(strings.t("client.order.newOrder"), variant: .ghost, size: .medium, action: onNewOrder)
            }
            .padding(EdgeInsets(top: 12, leading: 16, bottom: 4, trailing: 16))
            .background(c.card.ignoresSafeArea(edges: .bottom))
            .overlay(alignment: .top) { Rectangle().fill(c.line).frame(height: 1) }
        }
        .background(c.page.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
        .navigationBarBackButtonHidden()
    }

    private func summaryLine(_ published: PublishedRequest) -> String {
        let total = strings.money(published.totalMinor)
        guard let start = published.windowStart, let end = published.windowEnd else { return total }
        return "\(strings.windowLine(start: start, end: end)) · \(total)"
    }
}

