import SwiftUI
import UIKit

// MARK: - Buyurtma tafsilotlari

/// One listing of the client's (BOSQICH 03): a route map, the summary sheet (status, tracker, window, facts, photo),
/// the status notice, the drivers' offers inline (sort, counter, reject, choose), pause / resume, cancel behind a
/// confirmation sheet. The bar carries the pencil (edit) and share: the link made on this screen goes to the system
/// share sheet with the server's own text.
struct ListingDetailView: View {
    let model: ListingModel
    /// Opened for its offers (a notification, the old offers route): the body scrolls to "Haydovchi takliflari".
    var focusOffers = false
    let onBack: () -> Void
    let onEdit: () -> Void
    /// The listing and the booking the accept made (the flow opens its detail, then its chat - Q100).
    let onAccepted: (String, ClientBookingDTO) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var confirmCancel = false
    @State private var accepting: ProposalThreadDTO?

    static let offersAnchor = "elchi.listing.offers"

    var body: some View {
        ScreenScaffold(title: strings.t("listingDetail.title"), backLabel: strings.t("common.back"), onBack: onBack, banner: banner,
                       actions: barActions, initialScroll: focusOffers ? Self.offersAnchor : nil) {
            switch model.listing {
            case .loading:
                SkeletonCards(count: 3)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err)
                ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.load() } }
            case .loaded(let listing):
                content(listing)
            }
        } footer: {
            EmptyView()
        }
        .refreshable { await model.load() }
        .task { await model.load() }
        .sheet(isPresented: $confirmCancel) {
            CancelListingSheet(openOffers: model.openOffers, working: model.running == .cancel, onConfirm: {
                Task {
                    _ = await model.cancel()
                    confirmCancel = false
                }
            }, onBack: { confirmCancel = false })
        }
        .overlay {
            if let thread = accepting {
                AcceptDialog(thread: thread, listing: model.listing.value, offers: model.offers, onClose: { accepting = nil }) { onAccepted(thread.listingId, $0) }
            }
        }
    }

    private var barActions: [BarAction] {
        guard let listing = model.listing.value else { return [] }
        let actions = OwnerListingActions.of(listing.status)
        var out: [BarAction] = []
        // The design registers a pencil but draws no edit control: the pencil sits beside share (designer to confirm).
        if actions.canEdit {
            out.append(BarAction(id: "edit", systemImage: "pencil.line", label: strings.t("listingOwner.edit"), action: onEdit))
        }
        if actions.canShare {
            out.append(BarAction(id: "share", icon: .share, label: strings.t("client.share.send"), loading: model.running == .share) {
                Task { await share() }
            })
        }
        return out
    }

    /// The link already made on this screen, else a new one (the URL comes back once); then the system share sheet with
    /// the server's text, which carries the link itself.
    private func share() async {
        guard let link = await model.shareLinkForSharing() else { return }
        SystemShare.present([link.shareText])
    }

    @ViewBuilder
    private func content(_ listing: ListingDTO) -> some View {
        let actions = OwnerListingActions.of(listing.status)
        ForEach(model.warnings, id: \.code) { Note(strings.warningText($0), tone: .warn) }
        if let error = model.commandError, model.running == nil, model.failed == .share {
            Note(strings.shareErrorText(error), tone: .err)
        }

        let markers = mapMarkers(listing)
        if markers.count == 2 { hero(markers) }
        ListingSheetCard(listing: listing, model: model, overlapsMap: markers.count == 2)
        if let notice = notice(listing) { Note(strings.t(notice.key), tone: notice.tone) }

        offersSection(listing)

        if let link = model.shareLink { shareRow(link) }
        if actions.canPause || actions.canResume { pauseRow(actions) }
        if actions.canCancel {
            Button { confirmCancel = true } label: {
                Text(strings.t("listingDetail.cancel")).font(ElchiFont.poppins(14, .medium)).foregroundStyle(c.tone(.err).fg)
                    .padding(8).frame(minHeight: 44)
            }
            .buttonStyle(PressFade())
            .disabled(model.running != nil)
            .frame(maxWidth: .infinity)
        }
    }

    /// The route's two ends on a small, still map ("Yo'nalish": the listing has no distance to show - BLOCKED km).
    private func hero(_ markers: [MapMarker]) -> some View {
        ElchiMap(markers: markers, zoom: 9, interactive: false, placeholder: strings.t("routeSummary.direction"))
            .frame(height: 150)
            .clipShape(RoundedRectangle(cornerRadius: 24))
            .overlay(alignment: .bottomTrailing) {
                HStack(spacing: 6) {
                    Circle().fill(Color(hex: 0x9AA6B5)).frame(width: 8, height: 8)
                    Text(strings.t("routeSummary.direction")).font(ElchiFont.poppins(12.5, .semibold)).foregroundStyle(c.text)
                }
                .padding(.horizontal, 12).padding(.vertical, 7)
                .background(c.card, in: Capsule())
                .shadow(color: c.shadow, radius: 7, y: 4)
                .padding(.trailing, 12).padding(.bottom, 46)
            }
            .allowsHitTesting(false)
            .accessibilityHidden(true)
            .padding(.horizontal, -4)
    }

    private func mapMarkers(_ listing: ListingDTO) -> [MapMarker] {
        let ends = [listing.originPoint.map { MapMarker(GeoPoint(lat: $0.lat, lng: $0.lng), .origin) },
                    listing.destinationPoint.map { MapMarker(GeoPoint(lat: $0.lat, lng: $0.lng), .destination) }]
        return ends.compactMap { $0 }
    }

    private func notice(_ listing: ListingDTO) -> (key: String, tone: Tone)? {
        switch listing.status {
        case .paused: ("client.listing.noticePaused", .gray)
        case .expired: ("client.listing.noticeExpired", .gray)
        case .cancelled: ("client.listing.noticeCancelled", .err)
        case .fulfilled: ("client.listing.noticeFulfilled", .ok)
        default: nil
        }
    }

    @ViewBuilder
    private func offersSection(_ listing: ListingDTO) -> some View {
        let threads = model.offers.threads.value
        HStack(alignment: .firstTextBaseline) {
            Text(strings.t("listingBids.title")).font(ElchiFont.section).foregroundStyle(c.text).accessibilityAddTraits(.isHeader)
            Spacer(minLength: 8)
            if let threads {
                let open = model.openOffers
                Text(open > 0 ? strings.t("client.listing.offersSubOpen", ("count", open))
                     : strings.t(threads.isEmpty ? "client.listing.offersSubNone" : "client.listing.offersSubNoneOpen"))
                    .font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
            }
        }
        .padding(.top, 4)
        .id(Self.offersAnchor)
        switch model.offers.threads {
        case .loading:
            SkeletonCards(count: 2)
        case .failed(let error):
            Note(strings.errorText(error), tone: .err)
            ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.load() } }
        case .loaded(let threads) where threads.isEmpty:
            HStack(spacing: 12) {
                ElchiIcon.tag.image(size: 18).foregroundStyle(c.accentText)
                    .frame(width: 38, height: 38)
                    .background(c.isDark ? c.soft : Color(hex: 0xEEF4FA), in: Circle())
                Text(strings.t("client.offers.waitHint")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
            }
            .padding(14)
            .background { RoundedRectangle(cornerRadius: 18).fill(c.card).shadow(color: c.shadow, radius: 12, y: 6) }
        case .loaded(let threads):
            OffersBoard(threads: threads, listing: listing, offers: model.offers, unseen: model.unseen) { accepting = $0 }
            // Q43: who the driver is stays hidden until accept.
            Note(strings.t("listingBids.identityHidden"))
        }
    }

    /// The link made on this screen stays revocable ("Havolani bekor qilish"): the design's revoke is unbound.
    private func shareRow(_ link: ShareLinkDTO) -> some View {
        HStack(spacing: 10) {
            ElchiIcon.share.image(size: 18).foregroundStyle(c.accentText)
            VStack(alignment: .leading, spacing: 2) {
                Text(strings.t("client.share.link")).font(ElchiFont.poppins(13, .semibold)).foregroundStyle(c.text)
                if let expires = ServerTime.parse(link.expiresAt) {
                    Text(strings.t("trackingShare.validUntil", ("time", DepartureWindow.text(expires))))
                        .font(ElchiFont.caption).foregroundStyle(c.muted)
                }
            }
            Spacer(minLength: 8)
            Button { Task { await model.revokeShareLink() } } label: {
                Text(strings.t("client.share.revoke")).font(ElchiFont.poppins(13, .medium)).foregroundStyle(c.tone(.err).fg)
                    .multilineTextAlignment(.trailing)
            }
            .buttonStyle(PressFade())
            .frame(minHeight: 44)
        }
        .padding(.horizontal, 14).padding(.vertical, 8)
        .background(c.card, in: RoundedRectangle(cornerRadius: 18))
        .overlay { RoundedRectangle(cornerRadius: 18).strokeBorder(c.line, lineWidth: 1) }
    }

    /// Pause / resume stay reachable (the design draws no control for them): one compact row with its hint.
    private func pauseRow(_ actions: OwnerListingActions) -> some View {
        HStack(spacing: 12) {
            Text(strings.t(actions.canPause ? "listingOwner.pauseHint" : "client.listingDetail.resumeHint"))
                .font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
            ElchiButton(strings.t(actions.canPause ? "listingOwner.pause" : "listingOwner.resume"), variant: .neutral, size: .medium,
                        loading: model.running == .pause || model.running == .resume) {
                Task { if actions.canPause { await model.pause() } else { await model.resume() } }
            }
            .fixedSize()
            .disabled(model.running != nil)
        }
        .padding(.top, 4)
    }

    /// What the last owner command did (or why it failed), kept in sight under the top bar.
    private var banner: (text: String, tone: Tone)? {
        if let error = model.commandError, model.running == nil, model.failed != .share, model.failed != .save {
            return (strings.errorText(error), .err)
        }
        return model.notice.map { (strings.t($0, ("count", model.noticeCount)), .ok) }
    }
}

/// The detail's sheet card: "Holat" and the badge, the tracker, the window's two ends, the facts grid with the parcel
/// photo, then the comment and the expiry. No "E'lon ID": there is no short public code (BLOCKED).
private struct ListingSheetCard: View {
    let listing: ListingDTO
    let model: ListingModel
    let overlapsMap: Bool
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            let status = strings.status(.listing(listing.status))
            HStack(alignment: .center, spacing: 12) {
                Text(strings.t("driverProfile.status")).font(ElchiFont.caption).foregroundStyle(c.muted)
                Spacer(minLength: 8)
                Text(status.text).font(ElchiFont.poppins(12.5, .semibold)).foregroundStyle(c.tone(status.tone).fg)
                    .multilineTextAlignment(.trailing)
                    .padding(.horizontal, 14).padding(.vertical, 7)
                    .background(c.tone(status.tone).bg, in: RoundedRectangle(cornerRadius: 16))
            }
            .padding(.top, overlapsMap ? 4 : 0)
            .accessibilityElement(children: .combine)
            ProgressTracker(progress: ListingProgress.of(listing, hasThreads: !(model.offers.threads.value ?? []).isEmpty,
                                                         bookingStatus: model.bookingStatus), statusText: status.text)
            windowEnds
            Rectangle().fill(c.field).frame(height: 1)
            facts
            extras
        }
        .padding(.horizontal, 18).padding(.vertical, 20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background { RoundedRectangle(cornerRadius: 28).fill(c.card).shadow(color: c.shadow, radius: 12, y: 6) }
        .overlay(alignment: .top) {
            if overlapsMap { Capsule().fill(c.outline).frame(width: 44, height: 5).padding(.top, 8).accessibilityHidden(true) }
        }
        .padding(.top, overlapsMap ? -34 : 0)
    }

    private var windowEnds: some View {
        let start = ServerTime.parse(listing.departureWindowStart).map(DepartureWindow.shortText) ?? "?"
        let end = ServerTime.parse(listing.departureWindowEnd).map(DepartureWindow.shortText) ?? "?"
        let from = PlaceShort.of(strings.endAddress(stop: listing.originStop, point: listing.originPoint))
        let to = PlaceShort.of(strings.endAddress(stop: listing.destinationStop, point: listing.destinationPoint))
        return HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(strings.t("client.listing.departAt", ("time", start))).font(ElchiFont.caption).foregroundStyle(c.muted)
                Text(from).font(ElchiFont.poppins(15, .medium)).foregroundStyle(c.text)
            }
            .accessibilityElement(children: .combine)
            Spacer(minLength: 0)
            VStack(alignment: .trailing, spacing: 4) {
                Text(strings.t("client.listing.deadlineAt", ("time", end))).font(ElchiFont.caption).foregroundStyle(c.muted)
                Text(to).font(ElchiFont.poppins(15, .medium)).foregroundStyle(c.text)
            }
            .multilineTextAlignment(.trailing)
            .accessibilityElement(children: .combine)
        }
    }

    /// Two columns of facts and, for a parcel, the photo column (92 x 150). Taksi: people instead of the parcel and
    /// the full width.
    private var facts: some View {
        let parcel = listing.serviceType == .parcel
        let items: [(String, String, String?)] = [
            (strings.t("ui.from"), strings.endAddress(stop: listing.originStop, point: listing.originPoint), nil),
            (strings.t("ui.to"), strings.endAddress(stop: listing.destinationStop, point: listing.destinationPoint), nil),
            (strings.t("common.price"), strings.money(listing.totalMinor),
             parcel ? nil : strings.seatsTotal(listing.passenger?.seatCount ?? listing.quantity, unitMinor: listing.unitPriceMinor)),
            (strings.t("client.listing.views"), strings.t("client.listing.viewsCount", ("count", listing.viewCount ?? 0)), nil),
            parcel ? (strings.t("listingDetail.parcel"), strings.parcelShort(listing.parcel) ?? "—", nil)
                : (strings.t("orderForm.review.passengers"),
                   strings.t("orderForm.review.peopleCount", ("count", listing.passenger?.seatCount ?? listing.quantity)), nil),
            (strings.t("client.listing.stepOffers"), strings.t("client.listing.offersOpenShort", ("count", model.openOffers)), nil),
        ]
        return HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 16) {
                ForEach(0..<3, id: \.self) { row in
                    HStack(alignment: .top, spacing: 12) {
                        fact(items[row * 2])
                        fact(items[row * 2 + 1])
                    }
                }
            }
            if parcel { photo }
        }
    }

    private func fact(_ item: (String, String, String?), limit: Int? = 3) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(item.0).font(ElchiFont.caption).foregroundStyle(c.muted)
            // A long street address stops at three lines (the full one is the driver's after accept anyway).
            Text(item.1).font(ElchiFont.poppins(14.5, .medium)).foregroundStyle(c.text).lineSpacing(1).lineLimit(limit)
                .fixedSize(horizontal: false, vertical: true)
            if let detail = item.2 { Text(detail).font(ElchiFont.caption).foregroundStyle(c.muted) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    /// The parcel photo's signed link (Q6: short-lived - pulling to refresh fetches a new one).
    private var photo: some View {
        Group {
            if let url = model.photoURL {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image): image.resizable().scaledToFill()
                    case .failure: caption(strings.t("app.photo.reload"))
                    default: ProgressView()
                    }
                }
            } else {
                caption(strings.t("app.photo.none"))
            }
        }
        .frame(width: 92, height: 150)
        .background(c.field)
        .clipShape(RoundedRectangle(cornerRadius: 20))
        .accessibilityElement()
        .accessibilityLabel(strings.t("app.photo.alt"))
    }

    private func caption(_ text: String) -> some View {
        Text(text).font(ElchiFont.poppins(10.5)).foregroundStyle(c.muted).multilineTextAlignment(.center).padding(6)
    }

    /// Kept under the grid (the design drops them): the comment, and while the listing is live its expiry.
    @ViewBuilder
    private var extras: some View {
        let comment = listing.comment.flatMap { $0.isEmpty ? nil : $0 }
        let expires = listing.status == .published || listing.status == .paused ? ServerTime.parse(listing.expiresAt) : nil
        if comment != nil || expires != nil {
            VStack(alignment: .leading, spacing: 10) {
                Rectangle().fill(c.field).frame(height: 1)
                if let comment { fact((strings.t("listingOwner.commentLabel"), comment, nil), limit: nil) }
                if let expires {
                    fact((strings.t("client.listingDetail.expires"),
                          strings.t("client.listingDetail.until", ("date", String(DepartureWindow.shortText(expires).prefix(5)))), nil))
                }
            }
        }
    }
}

/// Five dots on a dotted line: done steps brand blue with a tick, the current one ringed; a dead listing all grey with
/// a red cross on "Takliflar". VoiceOver hears the step reached.
private struct ProgressTracker: View {
    let progress: ListingProgress
    /// Said instead of a step when the listing is closed.
    let statusText: String
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        let count = ListingProgress.stepKeys.count
        HStack(spacing: 0) {
            ForEach(0..<count, id: \.self) { index in
                dot(index)
                if index < count - 1 {
                    Line().stroke(lineColor(index), style: StrokeStyle(lineWidth: 3, lineCap: .round, dash: [0.1, 6]))
                        .frame(height: 3).padding(.horizontal, 4)
                }
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(progress.dead ? statusText : strings.t(ListingProgress.stepKeys[progress.current]))
    }

    private func done(_ index: Int) -> Bool { !progress.dead && index <= progress.current }

    private func dot(_ index: Int) -> some View {
        let cross = progress.dead && index == 1
        let fill = done(index) ? c.brand : cross ? c.tone(.err).bg : c.field
        let icon: ElchiIcon = cross ? .x : .check
        let tint = done(index) ? c.onBrand : cross ? c.tone(.err).fg : Color(hex: 0x9AA6B5)
        return icon.image(size: 13).foregroundStyle(tint)
            .frame(width: 26, height: 26)
            .background(fill, in: Circle())
            .overlay {
                if !progress.dead && index == progress.current {
                    Circle().strokeBorder(c.isDark ? c.soft : Color(hex: 0xBFE3FF), lineWidth: 3)
                }
            }
    }

    private func lineColor(_ index: Int) -> Color {
        !progress.dead && index < progress.current ? c.brand : c.outline
    }

    private struct Line: Shape {
        func path(in rect: CGRect) -> Path {
            var path = Path()
            path.move(to: CGPoint(x: 0, y: rect.midY))
            path.addLine(to: CGPoint(x: rect.maxX, y: rect.midY))
            return path
        }
    }
}

/// "Buyurtmani bekor qilasizmi?" - cancel is never one tap (design note: defect 10 fixed).
private struct CancelListingSheet: View {
    let openOffers: Int
    let working: Bool
    let onConfirm: () -> Void
    let onBack: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 4) {
                Text(strings.t("confirmDialog.cancelOrder.title")).font(ElchiFont.poppins(20, .medium, relativeTo: .title2)).foregroundStyle(c.text)
                    .accessibilityAddTraits(.isHeader)
                Text(openOffers > 0 ? strings.t("client.listingCancel.text", ("count", openOffers)) : strings.t("client.listingCancel.textNoOffers"))
                    .font(ElchiFont.secondary).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
            }
            ElchiButton(strings.t("bookingCancel.confirm"), variant: .danger, loading: working, action: onConfirm)
            ElchiButton(strings.t("confirmDialog.back"), variant: .neutral, action: onBack).disabled(working)
        }
        .padding(EdgeInsets(top: 28, leading: 20, bottom: 12, trailing: 20))
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(c.card.ignoresSafeArea())
        .presentationDetents([.height(330)])
        .presentationCornerRadius(ElchiShape.sheet)
        .presentationDragIndicator(.visible)
    }
}

/// The system share sheet over whatever is on screen (the bar's share icon creates the link first, then shares).
@MainActor
enum SystemShare {
    static func present(_ items: [Any]) {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        let scene = scenes.first { $0.activationState == .foregroundActive } ?? scenes.first
        guard var top = scene?.keyWindow?.rootViewController ?? scene?.windows.first?.rootViewController else { return }
        while let next = top.presentedViewController { top = next }
        let sheet = UIActivityViewController(activityItems: items, applicationActivities: nil)
        sheet.popoverPresentationController?.sourceView = top.view
        top.present(sheet, animated: true)
    }
}

// MARK: - E'lonni tahrirlash

/// Price, comment and the departure window. Q20: moving the window of a live listing closes its open offers - when
/// there are any, the warning says how many and the button asks for the explicit "Tushundim, saqlash". The button is
/// always tappable: what is wrong shows on tap (a red box at the top, the field's red border).
struct ListingEditView: View {
    let model: ListingModel
    let onBack: () -> Void
    let onSaved: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var form: ListingEditForm?
    @State private var priceText = ""
    @State private var editing: WindowEdge?
    /// The price or the people count is being typed: the number pad is up.
    @State private var typing = false
    /// "Saqlash" was tapped with something wrong: the errors show (and follow the form until it is right).
    @State private var showErrors = false
    @State private var scrollTop = 0

    static let commentLimit = 300
    static let priceDigits = 8

    var body: some View {
        let listing = model.listing.value
        let plan = listing.flatMap { dto in form.map { ListingPatchPlan.plan(dto, $0) } }
        let warnOffers = plan?.material == true && model.openOffers > 0
        let seatsEditable = listing.map(SeatEdit.editable) ?? false
        // Pochta: the design's sentence; Taksi keeps the longer one (it also covers the number of people, Q145).
        let offersWarning = listing?.serviceType == .parcel
            ? strings.t("client.listing.editWindowWarn", ("count", model.openOffers))
            : "\(strings.t("listingOwner.materialWarning")) \(strings.t("listingOwner.openOffers", ("count", model.openOffers)))"
        let invalid = showErrors ? plan?.invalid : nil
        ScreenScaffold(title: strings.t("listingOwner.editTitle"), backLabel: strings.t("common.back"), onBack: onBack,
                       keyboardDone: strings.t("client.keyboard.done"), scrollTop: scrollTop) {
            if form != nil {
                if let invalid { Note(strings.tOrNil("listingOwner.invalid.\(invalid)") ?? invalid, tone: .err) }
                if let error = model.commandError, model.running == nil, model.failed == .save { Note(strings.errorText(error), tone: .err) }
                ElchiField(text: $priceText,
                           label: seatsEditable ? strings.t("listingOwner.priceLabel") + strings.t("listingEdit.perSeatSuffix")
                                : strings.t("listingOwner.priceLabel"),
                           error: invalid == "price" ? "" : nil, keyboard: .numberPad, suffix: strings.t("common.soum"),
                           onFocus: { typing = $0 })
                    .onChange(of: priceText) { _, typed in
                        // Local text re-synced after every edit: SwiftUI's TextField ignores a binding that rewrites the input.
                        let digits = String(Money.soumDigits(typed).prefix(Self.priceDigits))
                        form?.priceDigits = digits
                        let formatted = Money.grouped(digits)
                        if priceText != formatted { priceText = formatted }
                    }
                ElchiField(text: Binding(get: { form?.comment ?? "" }, set: { form?.comment = String($0.prefix(Self.commentLimit)) }),
                           label: strings.t("listingOwner.commentLabel"), hint: strings.t("bookingChat.autoMaskNote"), multiline: true)
                if seatsEditable {
                    // Q145: the number of people, until a booking exists; a new number closes the open offers (Q20).
                    ElchiField(text: Binding(get: { form?.seats ?? "" }, set: { form?.seats = String($0.filter(\.isNumber).prefix(1)) }),
                               label: strings.t("listingEdit.seats"), hint: strings.t("listingEdit.seatsHint"),
                               error: invalid == "seats" ? strings.t("listingOwner.invalid.seats") : nil, keyboard: .numberPad,
                               onFocus: { typing = $0 })
                        .accessibilityIdentifier("elchi.listingEdit.seats")
                }
                let windowError = invalid?.hasPrefix("window") == true
                PickerField(label: strings.t("listingOwner.windowStart"), value: form?.windowStart.map(DepartureWindow.text),
                            placeholder: strings.t("client.routeSummary.windowPlaceholder"),
                            error: windowError && invalid != "window_order") { editing = .start }
                PickerField(label: strings.t("listingOwner.windowEnd"), value: form?.windowEnd.map(DepartureWindow.text),
                            placeholder: strings.t("client.routeSummary.windowPlaceholder"), error: windowError) { editing = .end }
                // Truthful (Q20), though the design leaves it out.
                Text(strings.t("listingOwner.nonMaterialNote")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
                    .fixedSize(horizontal: false, vertical: true)
                if warnOffers && !typing {
                    Note(offersWarning, tone: .warn)
                }
            } else {
                SkeletonCards(count: 2)
            }
        } footer: {
            // Under the number pad the warning would be out of sight: while a number is typed it sits over the button
            // it explains, above the keyboard.
            if warnOffers && typing {
                Note(offersWarning, tone: .warn).accessibilityIdentifier("elchi.listingEdit.offersWarning")
            }
            ElchiButton(strings.t(warnOffers ? "listingOwner.materialConfirm" : "common.save"), loading: model.running == .save) {
                guard let plan else { return }
                if plan.invalid != nil {
                    showErrors = true
                    scrollTop += 1
                    return
                }
                // Nothing changed: nothing to send.
                if plan.empty {
                    onBack()
                    return
                }
                Task { if await model.save(plan) { onSaved() } }
            }
        }
        .onAppear {
            model.clearNotice()
            if form == nil, let listing { start(listing) }
        }
        .onChange(of: model.listing.value?.version) { _, _ in
            // After VERSION_CONFLICT the listing was reloaded: the next save goes against the current version and the
            // form keeps what was typed.
            if form == nil, let listing = model.listing.value { start(listing) }
        }
        .task { await model.offers.reload() }
        .sheet(item: $editing) { edge in
            WindowPickerSheet(title: strings.t(edge == .start ? "listingOwner.windowStart" : "listingOwner.windowEnd"),
                              initial: (edge == .start ? form?.windowStart : form?.windowEnd) ?? DepartureWindow.suggested().start) { date in
                if edge == .start { form?.windowStart = date } else { form?.windowEnd = date }
                editing = nil
            }
        }
    }

    private func start(_ listing: ListingDTO) {
        let initial = ListingEditForm(listing: listing)
        form = initial
        priceText = Money.grouped(initial.priceDigits)
    }
}

// MARK: - Haydovchi takliflari (inline on the detail)

/// The drivers' offers on one listing: sort chips, then one card per thread (live first). A live countdown hides the
/// answers the moment an offer lapses; it ticks here only, not on the whole detail (the map stays still).
private struct OffersBoard: View {
    let threads: [ProposalThreadDTO]
    let listing: ListingDTO
    let offers: OfferThreads
    let unseen: Set<String>
    let onAccept: (ProposalThreadDTO) -> Void
    @Environment(LocaleStore.self) private var strings
    @State private var sort: OfferSort = .cheapest
    @State private var counterFor: String?
    @State private var now = Date()

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(OfferSort.allCases, id: \.self) { option in
                        Chip(strings.t(sortKey(option)), selected: sort == option, filled: true) { sort = option }
                    }
                }
            }
            // A paused listing takes no counter and no accept (`LISTING_NOT_OPEN`): said once, above the cards.
            if listing.status == .paused { Note(strings.t("client.listingBids.pausedNote"), tone: .warn) }
            let badges = OfferBadge.badges(threads, sort: sort, unseen: unseen, now: now)
            ForEach(sort.sorted(threads, now: now), id: \.id) { thread in
                OfferCard(thread: thread, listing: listing, style: .listing, offers: offers, now: now, badge: badges[thread.id],
                          counterOpen: counterFor == thread.id, onCounter: { counterFor = $0 ? thread.id : nil },
                          onAccept: { onAccept(thread) })
            }
        }
        .task { await tick() }
    }

    private func sortKey(_ sort: OfferSort) -> String {
        switch sort {
        case .cheapest: "client.listingBids.sortCheapest"
        case .fastest: "client.listingBids.sortFastest"
        case .bestRated: "client.listingBids.sortRating"
        }
    }

    private func tick() async {
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(1))
            now = Date()
        }
    }
}

// MARK: - One offer

/// One negotiation thread as the design's offer card: "Haydovchi #N", one badge, the price; a grey box with the
/// window, vehicle and rating bucket (never a score), the time left or what happened; then the answers in one row
/// (✕, "Boshqa narx · N", "Tanlash" / "Qabul qilish"). `.proposals` ("Takliflarim") puts the listing's route first.
/// The answers follow `NegotiationActions` - nothing the server would refuse is offered.
struct OfferCard: View {
    enum Style { case listing, proposals }

    let thread: ProposalThreadDTO
    let listing: ListingDTO?
    let style: Style
    let offers: OfferThreads
    let now: Date
    let badge: OfferBadge?
    let counterOpen: Bool
    let onCounter: (Bool) -> Void
    let onAccept: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(BannerCenter.self) private var banners: BannerCenter?

    var body: some View {
        let actions = NegotiationActions.of(thread, now: now)
        let closed = !actions.open && !accepted
        let shape = RoundedRectangle(cornerRadius: ElchiShape.card)
        VStack(alignment: .leading, spacing: 10) {
            header(closed: closed)
            let lines = lines(actions)
            if !lines.isEmpty {
                VStack(alignment: .leading, spacing: 3) {
                    ForEach(lines, id: \.self) { line in
                        Text(line.text).font(ElchiFont.poppins(12.5)).lineSpacing(2)
                            .foregroundStyle(line.tone.map { c.tone($0).fg } ?? (c.isDark ? c.text.opacity(0.85) : Color(hex: 0x3A4556)))
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(.horizontal, 12).padding(.vertical, 10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(c.isDark ? c.field : Color(hex: 0xF6F8FA), in: RoundedRectangle(cornerRadius: 14))
            }
            if let error = offers.errors[thread.id] { Note(strings.offerErrorText(error), tone: .err) }
            ForEach(offers.warnings[thread.id] ?? [], id: \.code) { Note(strings.warningText($0), tone: .warn) }
            if let version = thread.currentVersion, actions.open {
                answers(actions, version, paused: listing?.status == .paused)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        // The shadow on the card's shape only (on the whole stack it would fall under every inner box and button).
        .background { shape.fill(c.card).shadow(color: c.shadow, radius: 12, y: 6) }
        .overlay { shape.strokeBorder(badge == .cheapest ? c.brand : c.line, lineWidth: badge == .cheapest ? 2 : 1) }
        .opacity(closed ? 0.72 : 1)
    }

    /// The offer the booking was made from: not "closed", the agreed one.
    private var accepted: Bool { thread.state == "accepted" }

    /// Title, badge and price on one line; where a language's badge does not fit ("Встречное предложение"), the
    /// badge goes under the title instead of being cut.
    private func header(closed: Bool) -> some View {
        let title = Text(strings.driverLabel(thread)).font(ElchiFont.poppins(15, .semibold)).foregroundStyle(c.text).lineLimit(1)
        let price = Text(thread.currentVersion.map { strings.money($0.totalMinor) } ?? "").font(ElchiFont.poppins(17, .semibold)).lineLimit(1)
            .foregroundStyle(closed ? c.placeholder : c.accentText)
        let pill = badge.map { badge in
            Text(strings.t(badge.key)).font(ElchiFont.badge).lineLimit(1)
                .foregroundStyle(c.tone(badge.tone).fg)
                .padding(.horizontal, 9).padding(.vertical, 3)
                .background(c.tone(badge.tone).bg, in: Capsule())
        }
        return ViewThatFits(in: .horizontal) {
            HStack(spacing: 8) {
                title
                pill
                Spacer(minLength: 4)
                price
            }
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 8) {
                    title
                    Spacer(minLength: 4)
                    price
                }
                pill
            }
        }
        .accessibilityElement(children: .combine)
    }

    private func lines(_ actions: NegotiationActions) -> [ItemLine] {
        guard let version = thread.currentVersion else { return [] }
        var out: [ItemLine] = []
        // Threads span listings in "Takliflarim": the route comes first there; on a listing only when the driver's differs.
        if style == .proposals, let listing {
            out.append(.init(strings.route(listing)))
        } else if style == .listing, let route = strings.offerRouteIfDifferent(version, listing: listing) {
            out.append(.init(route))
        }
        let window = strings.offerWindow(version, listingStart: style == .listing ? listing?.departureWindowStart : nil)
        let summary = thread.driverSummary.map(strings.driverSummary)
        let first = [window, summary].compactMap { $0 }.joined(separator: " · ")
        if !first.isEmpty { out.append(.init(first)) }
        // ADR-0027 (Q153): the driver proposes another pickup time; accepting (or countering the price) is the consent.
        if let values = TimeProposalLine.values(version, listingStart: listing?.departureWindowStart, listingEnd: listing?.departureWindowEnd) {
            out.append(.init(strings.t("offer.timeProposal", values: values), tone: .warn))
        }
        // Taksi: the offer per seat, for the people asked for ("2 × 150 000 so'm").
        if PassengerMoney.perSeat(version.priceBasis) { out.append(.init(strings.peopleLine(version.quantity, unitMinor: version.unitPriceMinor))) }
        if actions.open, let message = version.message, !message.isEmpty { out.append(.init(message)) }
        if accepted {
            out.append(.init(strings.t("client.amendment.statusAccepted"), tone: .ok))
        } else if !actions.open {
            out.append(.init(strings.t(thread.closedReasonKey(now: now))))
        } else if actions.canWithdraw {
            out.append(.init(strings.t("client.offers.myCounterWaiting", ("price", strings.money(version.totalMinor))), tone: .blue))
        } else {
            if thread.driverCountered(now: now) {
                // "(sizniki …)" needs the client's previous version (read from the thread; without it, the price alone).
                if let mine = offers.clientPrice(thread) {
                    out.append(.init(strings.t("client.offers.driverCounter", ("price", strings.money(version.totalMinor)),
                                               ("mine", strings.money(mine))), tone: .warn))
                } else {
                    out.append(.init("\(strings.t("client.offers.badgeCounter")): \(strings.money(version.totalMinor))", tone: .warn))
                }
            }
            if let left = strings.timeLeft(version, now: now) { out.append(.init(left, tone: .warn)) }
        }
        return out
    }

    /// A paused listing takes no counter and no accept (`LISTING_NOT_OPEN`); refusing or taking back still works.
    @ViewBuilder
    private func answers(_ actions: NegotiationActions, _ version: ProposalVersionDTO, paused: Bool) -> some View {
        let busy = offers.busy == thread.id
        Group {
            if actions.theirTurn && paused {
                ElchiButton(strings.t("proposal.reject"), variant: .dangerSoft, size: .medium, loading: busy) { reject() }
            } else if actions.theirTurn {
                if counterOpen {
                    CounterForm(thread: thread, version: version, listingId: thread.listingId, offers: offers, onClose: { onCounter(false) })
                } else {
                    VStack(alignment: .leading, spacing: 10) {
                        if let quote = OfferThreads.clientQuote(version) {
                            // Only with the server's quote, unticked (Q104 explicit consent).
                            MoneyLines(rows: [
                                MoneyLines.Row(strings.t("promo.line.offerPrice"), strings.money(quote.fareMinor)),
                                MoneyLines.Row(strings.t("promo.line.bonusDiscount"), "−\(strings.money(quote.passengerDiscountMinor))", tone: .ok),
                                MoneyLines.Row(strings.t("promo.line.cashToDriver"), strings.money(quote.cashDueMinor), emphasis: true),
                            ], check: strings.t("promoScreen.useBonusShort", ("amount", strings.money(quote.passengerDiscountMinor))),
                               checked: Binding(get: { offers.useBonus[thread.id] == true }, set: { offers.useBonus[thread.id] = $0 }))
                            Text(strings.t("client.offers.bonusCovered")).font(ElchiFont.caption).foregroundStyle(c.muted)
                        }
                        actionRow(actions, busy: busy)
                    }
                }
            } else if actions.canWithdraw {
                Button {
                    Task {
                        if await offers.withdraw(thread) { banners?.show(.key("client.offers.counterWithdrawn"), tone: .info, hideAfter: .seconds(3)) }
                    }
                } label: {
                    HStack(spacing: 6) {
                        if busy { ProgressView().controlSize(.small) }
                        Text(strings.t("proposals.withdraw")).font(ElchiFont.poppins(13, .medium)).lineLimit(1)
                    }
                    .foregroundStyle(c.text)
                    .padding(.horizontal, 14).frame(height: 36)
                    .background(c.field, in: Capsule())
                    .contentShape(Capsule())
                }
                .buttonStyle(PressFade())
                .frame(maxWidth: .infinity, alignment: .trailing)
                .frame(minHeight: 44)
            }
        }
        .disabled(offers.busy != nil && !busy)
    }

    /// ✕, "Boshqa narx · N" and the primary in one row; where a language does not fit, the primary goes on its own row
    /// above the other two.
    private func actionRow(_ actions: NegotiationActions, busy: Bool) -> some View {
        let primaryTitle = strings.t(thread.driverCountered(now: now) ? "amendment.accept" : "confirmDialog.selectDriver.confirm")
        let rejectButton = Button { reject() } label: {
            Group {
                if busy { ProgressView().controlSize(.small).tint(c.tone(.err).fg) } else { ElchiIcon.x.image(size: 16) }
            }
            .foregroundStyle(c.tone(.err).fg)
            .frame(width: 42, height: 42)
            .background(c.tone(.err).bg, in: Circle())
            .frame(width: 44, height: 44)
            .contentShape(Circle())
        }
        .buttonStyle(PressFade())
        .accessibilityLabel(strings.t("proposal.reject"))
        let counter = pill(strings.t("client.offers.counterButton", ("count", actions.revisionsLeft)), weight: .medium, size: 13,
                           bg: actions.canCounter ? c.field : (c.isDark ? c.field.opacity(0.5) : Color(hex: 0xF3F5F8)),
                           fg: actions.canCounter ? c.text : Color(hex: 0x9AA6B5)) {
            guard actions.canCounter else {
                banners?.show(.key("client.offers.counterLimit"), tone: .info, hideAfter: .seconds(3))
                return
            }
            offers.clearError(thread.id)
            onCounter(true)
        }
        let primary = pill(primaryTitle, weight: .semibold, size: 13.5, bg: c.brand, fg: c.onBrand, action: onAccept)
        return ViewThatFits(in: .horizontal) {
            HStack(spacing: 8) {
                rejectButton
                counter
                primary
            }
            VStack(spacing: 8) {
                primary
                HStack(spacing: 8) { rejectButton; counter }
            }
        }
    }

    private func pill(_ title: String, weight: ElchiFont.Weight, size: CGFloat, bg: Color, fg: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(ElchiFont.poppins(size, weight, relativeTo: .subheadline)).lineLimit(1)
                .foregroundStyle(fg)
                .padding(.horizontal, 10)
                .frame(maxWidth: .infinity, minHeight: 42)
                .background(bg, in: Capsule())
                .contentShape(Capsule())
        }
        .buttonStyle(PressFade())
    }

    private func reject() {
        Task {
            guard await offers.reject(thread) else { return }
            let text = thread.driverNumber.map { strings.t("client.offers.rejectedDriver", ("number", $0)) } ?? strings.t("proposal.rejected")
            banners?.show(.text(text), tone: .info, hideAfter: .seconds(3))
        }
    }
}

/// "Boshqa narx": the client's price for this offer (a parcel request sends only the price; Taksi a price per seat).
/// Before sending, the server says what the client's own bonus would do to it - or, plainly, why there is none.
/// Tap-to-validate: an empty price or the driver's own price says so under the field.
private struct CounterForm: View {
    let thread: ProposalThreadDTO
    let version: ProposalVersionDTO
    let listingId: String
    let offers: OfferThreads
    let onClose: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(BannerCenter.self) private var banners: BannerCenter?
    @State private var priceText = ""
    @State private var digits = ""
    @State private var preview: PromoPreviewDTO?
    @State private var useBonus = false
    @State private var error: String?

    var body: some View {
        let priceMinor = Money.minor(fromSoum: digits)
        let quote = preview?.quote.flatMap { $0.passengerDiscountMinor > 0 ? $0 : nil }
        VStack(alignment: .leading, spacing: 10) {
            if let reason = preview?.noDiscountReason, quote == nil, let text = strings.tOrNil(noDiscountKey(reason)) {
                Note(text, tone: .gray, title: strings.t("promoScreen.whyNoDiscount"))
            }
            let perSeat = PassengerMoney.perSeat(version.priceBasis)
            ElchiField(text: $priceText, label: strings.t(perSeat ? "amendment.seatPriceLabel" : "listingBids.yourPrice"),
                       hint: hint(priceMinor, quote), error: error.map { strings.t($0) }, keyboard: .numberPad, suffix: strings.t("common.soum"))
                .onChange(of: priceText) { _, typed in
                    // Local text re-synced after every edit: SwiftUI's TextField ignores a binding that rewrites the input.
                    digits = String(Money.soumDigits(typed).prefix(8))
                    let formatted = Money.grouped(digits)
                    if priceText != formatted { priceText = formatted }
                    error = nil
                }
            if let quote {
                MoneyLines(rows: [
                    MoneyLines.Row(strings.t("promo.line.offerPrice"), strings.money(quote.fareMinor)),
                    MoneyLines.Row(strings.t("promo.line.bonusDiscount"), "−\(strings.money(quote.passengerDiscountMinor))", tone: .ok),
                    MoneyLines.Row(strings.t("promo.line.cashToDriver"), strings.money(quote.cashDueMinor), emphasis: true),
                ], check: strings.t("promoScreen.useBonusShort", ("amount", strings.money(quote.passengerDiscountMinor))), checked: $useBonus)
            }
            HStack(spacing: 8) {
                ElchiButton(strings.t("common.send"), size: .medium, loading: offers.busy == thread.id) {
                    if let problem = CounterCheck.error(priceMinor: priceMinor, driverUnitMinor: version.unitPriceMinor) {
                        error = problem
                        return
                    }
                    Task {
                        if await offers.counter(thread, priceMinor: priceMinor, consent: useBonus ? quote : nil) {
                            banners?.show(.text(strings.t("client.offers.counterSentPrice", ("price", strings.money(total(priceMinor))))),
                                          tone: .info, hideAfter: .seconds(3))
                            onClose()
                        }
                    }
                }
                ElchiButton(strings.t("common.cancel"), variant: .neutral, size: .medium, action: onClose)
            }
        }
        .padding(.top, 4)
        .onAppear {
            // The counter is a unit price: per seat for a passenger request, the whole price for a parcel.
            digits = String(version.unitPriceMinor / 100)
            priceText = Money.grouped(digits)
        }
        .task(id: priceMinor) {
            // Debounced: the preview follows the typed price; a new price unticks the bonus (the person agrees again).
            useBonus = false
            guard priceMinor > 0 else { preview = nil; return }
            try? await Task.sleep(for: .milliseconds(400))
            if Task.isCancelled { return }
            preview = try? await offers.promoPreview(listingId: listingId, unitPriceMinor: priceMinor, quantity: version.quantity)
        }
    }

    private func total(_ priceMinor: Int) -> Int {
        version.priceBasis == .total ? priceMinor : priceMinor * max(version.quantity, 1)
    }

    /// "Jami: 135 000 so'm" (never "the driver answers once": the driver has its own revisions).
    private func hint(_ priceMinor: Int, _ quote: ProposalPromoClientDTO?) -> String {
        let base = "\(strings.t("common.total")): \(priceMinor > 0 ? strings.money(total(priceMinor)) : "—")"
        return quote == nil ? base : "\(base) · \(strings.t("client.listingBids.bonusOptIn"))"
    }

    private func noDiscountKey(_ reason: String) -> String {
        let keys = ["service_not_eligible": "serviceNotEligible", "bonus_expired": "bonusExpired", "bonus_reserved": "bonusReserved",
                    "bonus_on_hold": "bonusOnHold", "no_campaign": "noCampaign", "client_update_required": "clientUpdateRequired",
                    "trip_terms": "tripTerms"]
        return "promo.noDiscount.\(keys[reason] ?? reason)"
    }
}

// MARK: - Haydovchini tanlash

/// "Haydovchi #3 ni tanlaysizmi?" - accepting is never one tap. The agreed total is the version's own (never
/// recomputed); bonus lines only when the person ticked the server's bonus quote.
struct AcceptDialog: View {
    let thread: ProposalThreadDTO
    /// The listing, for the time-proposal sentence (Q153) when the driver offers another pickup time.
    var listing: ListingDTO?
    let offers: OfferThreads
    let onClose: () -> Void
    let onAccepted: (ClientBookingDTO) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        let version = thread.currentVersion
        let quote = version.flatMap { offers.useBonus[thread.id] == true ? OfferThreads.clientQuote($0) : nil }
        let working = offers.busy == thread.id
        DialogOverlay(dismissLabel: strings.t("confirmDialog.back"), onDismiss: { if !working { onClose() } }) {
            VStack(alignment: .leading, spacing: 4) {
                Text(thread.driverNumber.map { strings.t("client.accept.title", ("number", $0)) } ?? strings.t("confirmDialog.selectDriver.title"))
                    .font(ElchiFont.poppins(19, .medium, relativeTo: .title2)).foregroundStyle(c.text)
                    .accessibilityAddTraits(.isHeader)
                Text(strings.t("client.accept.text")).font(ElchiFont.secondary).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
            }
            if let version, let values = TimeProposalLine.values(version, listingStart: listing?.departureWindowStart,
                                                                 listingEnd: listing?.departureWindowEnd) {
                Note(strings.t("offer.timeProposal", values: values), tone: .warn).accessibilityIdentifier("elchi.accept.timeProposal")
            }
            if let version {
                MoneyLines(rows: quote.map { quote in
                    [MoneyLines.Row(strings.t("promo.line.agreedPrice"), strings.money(version.totalMinor)),
                     MoneyLines.Row(strings.t("promo.line.bonusDiscount"), "−\(strings.money(quote.passengerDiscountMinor))", tone: .ok),
                     MoneyLines.Row(strings.t("client.offers.cashToDriverShort"), strings.money(quote.cashDueMinor), emphasis: true)]
                } ?? [MoneyLines.Row(strings.t("promo.line.agreedPrice"), strings.money(version.totalMinor), emphasis: true)])
            }
            ElchiButton(strings.t("client.accept.confirm"), loading: working) {
                Task {
                    // A refusal closes the dialog: the offer card below shows why, in its current state.
                    if let booking = await offers.accept(thread) { onAccepted(booking) } else { onClose() }
                }
            }
            ElchiButton(strings.t("confirmDialog.back"), variant: .neutral, size: .medium, action: onClose).disabled(working)
        }
        .onAppear { offers.clearError(thread.id) }
    }
}
