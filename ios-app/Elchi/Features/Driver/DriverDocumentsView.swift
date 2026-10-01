import PhotosUI
import SwiftUI
import UniformTypeIdentifiers

/// "Hujjatlar": five named slots, so the screen says which document it wants before the camera opens and which one
/// it was afterwards (§17.1). Each row: name, what it is, its state, the reason when rejected, the file limit, and
/// upload / re-upload (camera, gallery, and a PDF where the type allows one).
struct DriverDocumentsView: View {
    let driver: DriverModel
    let mediaURL: (String) -> URL?
    let onBack: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(BannerCenter.self) private var banners
    @Environment(\.elchi) private var c
    @Environment(\.openURL) private var openURL
    /// The slot the source choice (and then the picker) is for.
    @State private var target: DriverDocumentType?
    @State private var askSource = false
    @State private var showGallery = false
    @State private var showCamera = false
    @State private var showFiles = false
    @State private var galleryItem: PhotosPickerItem?

    var body: some View {
        ScreenScaffold(title: strings.t("driverDocs.title"), backLabel: strings.t("common.back"), onBack: onBack) {
            switch driver.documents {
            case .loading:
                SkeletonCards(count: 4)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err)
                ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await driver.loadDocuments() } }
            case .loaded:
                let slots = driver.slots
                ElchiCard(padding: EdgeInsets(top: 14, leading: 16, bottom: 14, trailing: 16)) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(strings.t("driverDocs.submittedCount", ("submitted", DocumentSlots.submitted(slots)),
                                       ("total", DriverDocumentType.allCases.count)))
                            .font(ElchiFont.poppins(15, .semibold)).foregroundStyle(c.text)
                        Text(strings.t("driverDocs.intro")).font(ElchiFont.caption).foregroundStyle(c.muted).lineSpacing(2)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .accessibilityElement(children: .combine)
                }
                .accessibilityIdentifier("elchi.driver.docs.count")
                ForEach(slots, id: \.type) { slot in row(slot) }
            }
        } footer: {
            EmptyView()
        }
        .refreshable { await driver.loadDocuments() }
        .task { await driver.loadDocuments() }
        .confirmationDialog(target.map { strings.t("docType.\($0.rawValue)") } ?? "", isPresented: $askSource, titleVisibility: .visible) {
            if UIImagePickerController.isSourceTypeAvailable(.camera) {
                Button(strings.t("client.photo.camera")) { showCamera = true }
            }
            Button(strings.t("client.photo.gallery")) { openGallery() }
            if target?.allowsPDF == true {
                Button(strings.t("driver.docs.pdf")) { openFiles() }
            }
            Button(strings.t("common.cancel"), role: .cancel) {}
        }
        .photosPicker(isPresented: $showGallery, selection: $galleryItem, matching: .images)
        .onChange(of: galleryItem) { _, item in
            guard let item, let type = target else { return }
            galleryItem = nil
            Task {
                if let data = try? await item.loadTransferable(type: Data.self), let image = UIImage(data: data) {
                    await send(image: image, type: type)
                } else {
                    banners.show(.key("client.photo.unreadable"), tone: .err)
                }
            }
        }
        .fullScreenCover(isPresented: $showCamera) {
            CameraPicker { image in
                showCamera = false
                if let image, let type = target { Task { await send(image: image, type: type) } }
            }
            .ignoresSafeArea()
        }
        .fileImporter(isPresented: $showFiles, allowedContentTypes: [.pdf]) { result in
            guard let type = target, case .success(let url) = result else { return }
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            guard let data = try? Data(contentsOf: url) else {
                banners.show(.key("client.photo.unreadable"), tone: .err)
                return
            }
            Task { await driver.upload(type, file: .pdf(data)) }
        }
    }

    private func row(_ slot: DocumentSlot) -> some View {
        let uploading = driver.uploading == slot.type
        var lines: [ItemLine] = []
        if let reason = slot.rejectionReason {
            lines.append(ItemLine(strings.t("driverDocs.rejectionReason", ("reason", reason)), tone: .err))
        }
        lines.append(ItemLine(strings.t(slot.type.hintKey, ("max", slot.type.maxMB))))
        return ItemCard(title: strings.t("docType.\(slot.type.rawValue)"), icon: .camera,
                        badge: (strings.tOrNil("docState.\(slot.state.rawValue)") ?? slot.state.rawValue, slot.state.tone),
                        sub: strings.t("docHint.\(slot.type.rawValue)"), lines: lines) {
            HStack(spacing: 8) {
                if uploading {
                    ProgressView()
                    Text(strings.t("driver.docs.uploading")).font(ElchiFont.poppins(13, .medium)).foregroundStyle(c.muted)
                    Spacer(minLength: 0)
                } else {
                    ElchiButton(strings.t(slot.state == .missing ? "driverDocs.upload" : "driverDocs.reupload"),
                                variant: slot.state == .rejected ? .primary : .soft, size: .medium, icon: .upload) { pick(slot.type) }
                        .disabled(driver.uploading != nil)
                        .accessibilityIdentifier("elchi.driver.docs.\(slot.type.rawValue)")
                    if let link = slot.document?.fileUrl, let url = mediaURL(link) {
                        // The signed file as it was sent (a picture or the PDF), in the browser.
                        Button { openURL(url) } label: {
                            ElchiIcon.eye.image(size: 18).foregroundStyle(c.accentText)
                                .frame(width: 44, height: 44)
                                .background(c.field, in: Circle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel(strings.t("docType.\(slot.type.rawValue)"))
                    }
                }
            }
            .padding(.top, 4)
        }
    }

    private func pick(_ type: DriverDocumentType) {
        banners.clearError()
        target = type
        askSource = true
    }

    private func send(image: UIImage, type: DriverDocumentType) async {
        let prepared = await Task.detached(priority: .userInitiated) { DocumentFile.image(image, maxBytes: type.maxBytes) }.value
        guard let prepared else {
            banners.show(.template("driver.error.fileTooLarge", values: ["max": String(type.maxMB)]), tone: .err)
            return
        }
        await driver.upload(type, file: prepared)
    }

    private func openGallery() {
        #if DEBUG
        // UI tests cannot drive the system photo picker reliably: they get a generated picture instead.
        if ProcessInfo.processInfo.arguments.contains("-uiTestFakePhoto"), let type = target {
            Task { await send(image: TestFiles.photo(), type: type) }
            return
        }
        #endif
        showGallery = true
    }

    private func openFiles() {
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("-uiTestFakePhoto"), let type = target {
            Task { await driver.upload(type, file: .pdf(TestFiles.pdf())) }
            return
        }
        #endif
        showFiles = true
    }
}

#if DEBUG
/// Generated files for UI tests (the system pickers cannot be driven reliably).
enum TestFiles {
    static func photo() -> UIImage {
        UIGraphicsImageRenderer(size: CGSize(width: 1200, height: 800)).image { context in
            UIColor(red: 0.90, green: 0.94, blue: 0.98, alpha: 1).setFill()
            context.fill(CGRect(x: 0, y: 0, width: 1200, height: 800))
            UIColor(red: 0.20, green: 0.35, blue: 0.60, alpha: 1).setFill()
            context.fill(CGRect(x: 120, y: 160, width: 420, height: 480))
            UIColor(red: 0.55, green: 0.60, blue: 0.68, alpha: 1).setFill()
            for row in 0..<6 { context.fill(CGRect(x: 620, y: 200 + row * 70, width: 460, height: 28)) }
        }
    }

    static func pdf() -> Data {
        UIGraphicsPDFRenderer(bounds: CGRect(x: 0, y: 0, width: 595, height: 842)).pdfData { context in
            context.beginPage()
            ("ELCHI test document" as NSString).draw(at: CGPoint(x: 72, y: 72), withAttributes: [.font: UIFont.systemFont(ofSize: 24)])
        }
    }
}
#endif
