import SwiftUI
import UIKit

// MARK: - Buyurtma tafsilotlari (bron)

/// One booking of the client's, BOSQICH 04 ("Elchi Bron"): the bar's share (the tracking link straight into the
/// system share sheet) and help icons; the map hero (opens tracking); the sheet card - status, the five-step tracker,
/// created / planned arrival, the facts grid (with the parcel photo), the fare note; the status notices; the Taksi
/// boarding code; the driver and vehicle card (Q43/Q44/Q64 - kept, designer to confirm); the promo money; the Taksi
/// cash record and "Manzilga yetib keldim"; the rating card (completed only); amend (confirmed only); "Yordam /
/// shikoyat" (Q146: the main support action); the safety row; "Bronni bekor qilish" as red text. The driver bar is
/// fixed at the bottom: call (only when the server shows phones) and chat with the unseen count.
struct BookingDetailView: View {
    let model: BookingModel
    let onBack: () -> Void
    let onChat: () -> Void
    let onTracking: () -> Void
    let onAmend: () -> Void
    let onRate: () -> Void
    let onSupport: () -> Void
    let onSafety: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(\.openURL) private var openURL
    @Environment(BannerCenter.self) private var banners: BannerCenter?
    @State private var confirmCancel = false
    @State private var confirmComplete = false
    @State private var sharing = false

    var body: some View {
        ScreenScaffold(title: strings.t("listingDetail.title"), backLabel: strings.t("common.back"), onBack: onBack, banner: banner,
                       actions: barActions, plainFooter: true) {
            switch model.booking {
            case .loading:
                SkeletonCards(count: 3)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err)
                ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.load() } }
            case .loaded(let booking):
                content(booking)
            }
        } footer: {
            if let booking = model.booking.value, let driver = booking.driver { driverBar(booking, driver) }
        }
        .refreshable { await model.load() }
        // Also on the way back from chat, tracking, amendments, rating: the booking may have moved on.
        .onAppear { Task { await model.load() } }
        .sheet(isPresented: $confirmCancel) {
            CancelBookingSheet(model: model) { confirmCancel = false }
        }
        .overlay {
            if confirmComplete {
                TaxiCompleteDialog(working: model.running == .complete, onConfirm: {
                    Task {
                        if await model.complete() { banners?.ok("client.taxi.completed") }
                        confirmComplete = false
                    }
                }, onClose: { confirmComplete = false })
            }
        }
    }

    /// A failed complete stays in sight under the bar (a cancel's refusal is said on its sheet, the rest are toasts).
    private var banner: (text: String, tone: Tone)? {
        if let error = model.commandError, model.running == nil, model.failed == .complete { return (strings.errorText(error), .err) }
        return nil
    }

    /// Share (while the booking is still on its way, design `s < 3`) and help (a shortcut - the full-width "Yordam /
    /// shikoyat" button stays the main support action, Q146).
    private var barActions: [BarAction] {
        guard let booking = model.booking.value else { return [] }
        var out: [BarAction] = []
        if BookingDetailRules.canShare(booking.serviceStatus, service: booking.serviceType) {
            out.append(BarAction(id: "share", icon: .share, label: strings.t("client.booking.shareTracking"), loading: sharing) {
                Task { await share() }
            })
        }
        out.append(BarAction(id: "support", icon: .head, label: strings.t("support.complain"), action: onSupport))
        return out
    }

    /// The link made on this screen again, else a new one (1 hour); then the system share sheet ("Elchi kuzatuv").
    /// A refusal (too early, finished) is a toast.
    private func share() async {
        guard !sharing else { return }
        sharing = true
        defer { sharing = false }
        banners?.clearError()
        guard let url = await model.trackingLinkForSharing() else {
            if let error = model.commandError, model.failed == .grant {
                banners?.show(.text(strings.grantErrorText(error)), tone: .err)
            }
            return
        }
        SystemShare.present([TrackingLinkItem(url: url, title: strings.t("client.booking.shareSheetTitle"))])
    }

    @ViewBuilder
    private func content(_ booking: ClientBookingDTO) -> some View {
        let actions = BookingActions.of(booking.serviceStatus)
        let taxi = ClientTaxiActions.of(booking)
        ForEach(model.warnings, id: \.code) { Note(strings.warningText($0), tone: .warn) }

        BookingMapHero(markers: markers(booking), live: BookingDetailRules.liveDot(booking.serviceStatus),
                       label: strings.t("bookingTracking.title"), accessibility: strings.t("client.booking.openTracking"), action: onTracking)
        BookingSheetCard(booking: booking, model: model)
        ForEach(Array(BookingDetailRules.notices(booking, blocked: model.blocked).enumerated()), id: \.offset) { _, notice in
            BookingNoticeBox(text: noticeText(notice), tone: notice.tone)
        }
        if taxi.showCode { BoardingCodeSection(model: model.code) }
        driverCard(booking)
        if let promo = booking.promo { promoBlock(promo) }
        if taxi.cash { CashRecordSection(model: model.cash, booking: booking, dueMinor: booking.cashDueMinor) }
        if taxi.canComplete {
            ElchiButton(strings.t("client.taxi.complete"), icon: .checkC) {
                model.clearNotice()
                confirmComplete = true
            }
            .disabled(model.running != nil)
            .accessibilityIdentifier("elchi.taxi.complete")
        }
        if actions.canRate { rating(booking) }
        if actions.canAmend {
            ElchiButton(strings.t("amendment.title"), variant: .neutral, size: .medium, action: onAmend)
                .accessibilityIdentifier("elchi.booking.amend")
        }
        // Q146: help is the main support action - a full-width button, not only the bar's icon.
        ElchiButton(strings.t("support.complain"), variant: .neutral, size: .medium, icon: .head, action: onSupport)
            .accessibilityIdentifier("elchi.booking.support")
        if let grant = model.grant, let url = model.grantURL { linkRow(grant, url) }
        // Apart from help (Q146): the safety report and block, one tap further.
        SafetyEntryRow(title: strings.t("safety.menuTitle"), action: onSafety)
            .padding(.top, 4)
        if actions.canCancel {
            Button {
                model.clearNotice()
                confirmCancel = true
            } label: {
                Text(strings.t("bookingCancel.button")).font(ElchiFont.poppins(14, .medium)).foregroundStyle(c.tone(.err).fg)
                    .padding(.horizontal, 16).frame(minHeight: 44)
            }
            .buttonStyle(PressFade())
            .disabled(model.running != nil)
            .frame(maxWidth: .infinity)
            .accessibilityIdentifier("elchi.booking.cancel")
        }
    }

    /// Both ends on the hero when they are map points (a verified stop carries no coordinates).
    private func markers(_ booking: ClientBookingDTO) -> [MapMarker] {
        [booking.pickup.point.map { MapMarker(GeoPoint(lat: $0.lat, lng: $0.lng), .origin) },
         booking.dropoff.point.map { MapMarker(GeoPoint(lat: $0.lat, lng: $0.lng), .destination) }].compactMap { $0 }
    }

    private func noticeText(_ notice: BookingDetailRules.Notice) -> String {
        switch notice {
        case .onTheWay: strings.t("client.booking.noticeOnTheWay")
        case .delivered: strings.t("client.booking.noticeDelivered")
        case .arrived: strings.t("client.booking.noticeArrived")
        case .cancelled(let cancelled): strings.cancelledLine(cancelled)
        case .noShowPending: strings.t("bookingCancel.reviewPending")
        case .blocked: strings.t("client.booking.driverBlocked")
        }
    }

    // MARK: Driver bar

    private func driverBar(_ booking: ClientBookingDTO, _ driver: ClientBookingDTO.Driver) -> some View {
        let phone = BookingDetailRules.phone(booking)
        let reputation = model.reputation.map { reputation -> String in
            guard reputation.ratingCount > 0, let average = reputation.averageRating else { return strings.t("ratingBucket.new_verified") }
            return "★ " + String(format: "%.1f", average).replacingOccurrences(of: ".", with: ",")
        }
        let plate = DriverReveal.of(booking)?.plate ?? driver.vehicle.plateMasked
        let line = [strings.t("safety.driverTitle"), reputation, "\(driver.vehicle.makeModel) \(plate)"].compactMap { $0 }.joined(separator: " · ")
        var open = false
        if case .visible = phone { open = true }
        return DriverContactBar(name: driver.displayName, line: line, phoneOpen: open, unread: model.unreadChat,
                                callLabel: strings.t("client.legacy.call"), chatLabel: strings.t("bookingChat.title"),
                                onCall: { call(phone, service: booking.serviceType) }, onChat: onChat)
    }

    private func call(_ phone: BookingDetailRules.Phone, service: ServiceType) {
        if case .visible(let number) = phone, let url = DriverReveal.dialURL(number) {
            openURL(url)
        } else if let key = BookingDetailRules.callRefusalKey(phone, service: service) {
            banners?.show(.key(key), tone: .info, hideAfter: .seconds(3))
        }
    }

    // MARK: Driver and vehicle

    /// Kept (Q43/Q44/Q64; the design's `driverRows` are defined but not drawn - designer to confirm): name and
    /// reputation, vehicle, the plate with when the full one opens, the phone (open, opens later, or closed).
    @ViewBuilder
    private func driverCard(_ booking: ClientBookingDTO) -> some View {
        if let driver = booking.driver, let reveal = DriverReveal.of(booking) {
            let phone = BookingDetailRules.phone(booking)
            ElchiCard {
                CardTitle(strings.t("client.bookingDetail.driverCard"),
                          badge: reveal.phone != nil ? (strings.t("client.bookingDetail.contactOpen"), .ok) : nil)
                CardRow(strings.t("safety.driverTitle"), driver.displayName, detail: model.reputation.map(strings.reputationLine))
                CardRow(strings.t("addRoute.vehicle"), strings.vehicleName(driver.vehicle), detail: strings.vehicleClassLine(driver.vehicle))
                // A finished or cancelled booking never opens the full plate: no promise of it then.
                CardRow(strings.t("driverProfileForm.plateNumber"), reveal.plate,
                        detail: reveal.plateFull ? strings.t("client.bookingDetail.plateOpen")
                            : BookingActions.of(booking.serviceStatus).terminal ? nil : strings.t("client.bookingDetail.plateLater"))
                switch phone {
                case .visible(let number):
                    CardRow(strings.t("driverBooking.phone"), UzPhone.display(number), trailing: strings.t("client.bookingDetail.call")) {
                        if let url = DriverReveal.dialURL(number) { openURL(url) }
                    }
                case .locked:
                    // A passenger's service starts at boarding (Q44), a parcel's when the trip departs (Q142).
                    CardRow(strings.t("driverBooking.phone"),
                            strings.t(booking.serviceType == .passenger ? "driverBooking.phoneHidden" : "client.bookingDetail.phoneLater"),
                            detail: strings.t("client.bookingDetail.phoneChatOnly"), placeholder: true)
                case .closed:
                    // Over (and past the 24 h after it, Q44): the server hides the phones again.
                    CardRow(strings.t("driverBooking.phone"), strings.t("client.booking.phoneClosed"), placeholder: true)
                }
            }
            .accessibilityIdentifier("elchi.booking.driverCard")
        }
    }

    private func promoBlock(_ promo: BookingPromoClientDTO) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            MoneyLines(title: strings.t("promoScreen.moneyTitle"), rows: [
                MoneyLines.Row(strings.t("promo.line.agreedPrice"), strings.money(promo.fareMinor)),
                MoneyLines.Row(strings.t("promo.line.bonusDiscount"), "−\(strings.money(promo.passengerDiscountMinor))", tone: .ok),
                MoneyLines.Row(strings.t("client.booking.finalPrice"), strings.money(promo.cashDueMinor), emphasis: true),
            ])
            Text(strings.t("promoScreen.clientCovers")).font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
        }
    }

    // MARK: Rating

    /// Completed: the star card until rated (a star opens the rating screen with it chosen), then "Baho berildi" -
    /// with the stars when they were sent from this screen session (the booking DTO carries no rating).
    @ViewBuilder
    private func rating(_ booking: ClientBookingDTO) -> some View {
        if let outcome = model.rating {
            switch outcome {
            case .sent:
                if let stars = model.ratedStars {
                    Note(strings.t("client.booking.ratedStars", ("stars", BookingDetailRules.starsText(stars))), tone: .ok)
                } else {
                    Note(strings.t("client.bookingDetail.rated"), tone: .ok)
                }
            case .already: Note(strings.t("error.RATING_ALREADY_EXISTS"), tone: .ok, title: strings.t("client.bookingDetail.rated"))
            case .notAllowed: Note(strings.t("error.RATING_NOT_ALLOWED"), tone: .gray)
            }
        } else if BookingDetailRules.showsRatingCard(booking.serviceStatus, rated: false) {
            RateDriverCard(title: strings.t("rating.titleDriver"), starLabel: { strings.t("bookingRating.starsAria", ("value", $0)) }) { stars in
                model.ratingDraft = stars
                onRate()
            }
        }
    }

    // MARK: Tracking link

    /// The link shared from the bar stays revocable here ("Havolani bekor qilish": the design's revoke is unbound),
    /// with a copy button; the lifetime is the default hour (the design drops the chips).
    private func linkRow(_ grant: TrackingGrantDTO, _ url: URL) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                ElchiIcon.share.image(size: 18).foregroundStyle(c.accentText)
                VStack(alignment: .leading, spacing: 2) {
                    Text(strings.t("trackingShare.trackingTitle")).font(ElchiFont.poppins(13, .semibold)).foregroundStyle(c.text)
                    if let expires = ServerTime.parse(grant.expiresAt) {
                        Text(strings.t("trackingShare.validUntil", ("time", DepartureWindow.text(expires))))
                            .font(ElchiFont.caption).foregroundStyle(c.muted)
                    }
                }
                Spacer(minLength: 0)
            }
            Text(url.absoluteString).font(.system(size: 12, design: .monospaced)).foregroundStyle(c.muted).lineLimit(1).truncationMode(.middle)
                .textSelection(.enabled)
            HStack(spacing: 16) {
                Button {
                    UIPasteboard.general.string = url.absoluteString
                    banners?.show(.key("client.booking.trackingLinkCopied"), tone: .ok, hideAfter: .seconds(3))
                } label: {
                    Text(strings.t("promoScreen.copy")).font(ElchiFont.poppins(13, .medium)).foregroundStyle(c.accentText).frame(minHeight: 36)
                }
                .buttonStyle(PressFade())
                Spacer(minLength: 0)
                Button {
                    Task {
                        await model.revokeGrant()
                        if model.grant == nil { banners?.ok("trackingShare.revoked") }
                    }
                } label: {
                    Text(strings.t("client.share.revoke")).font(ElchiFont.poppins(13, .medium)).foregroundStyle(c.tone(.err).fg).frame(minHeight: 36)
                }
                .buttonStyle(PressFade())
                .disabled(model.running == .revokeGrant)
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 10)
        .background(c.card, in: RoundedRectangle(cornerRadius: 18))
        .overlay { RoundedRectangle(cornerRadius: 18).strokeBorder(c.line, lineWidth: 1) }
        .accessibilityIdentifier("elchi.booking.link")
    }
}

// MARK: - The sheet card

/// "Holat" and the badge, the five dots, when it was made and (only when the booking says it) the planned arrival
/// with the two places, the facts grid (Pochta with the photo column), and the fare note (Q103: the money never goes
/// through the app). No "Bron ID": there is no short public code (BLOCKED).
private struct BookingSheetCard: View {
    let booking: ClientBookingDTO
    let model: BookingModel
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        let status = strings.status(.clientBooking(booking.serviceType, booking.serviceStatus))
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .center, spacing: 12) {
                Text(strings.t("support.statusLabel")).font(ElchiFont.caption).foregroundStyle(c.muted)
                Spacer(minLength: 8)
                Text(status.text).font(ElchiFont.poppins(12.5, .semibold)).foregroundStyle(c.tone(status.tone).fg)
                    .multilineTextAlignment(.trailing)
                    .padding(.horizontal, 14).padding(.vertical, 7)
                    .background(c.tone(status.tone).bg, in: RoundedRectangle(cornerRadius: 16))
            }
            .padding(.top, 4)
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("elchi.booking.status")
            if let tracker = BookingDetailRules.tracker(booking.serviceStatus, service: booking.serviceType) {
                BookingStepDots(tracker: tracker, label: trackerLabel(tracker, statusText: status.text))
            }
            ends
            Rectangle().fill(c.field).frame(height: 1)
            facts
            Text(strings.t("bookingDetail.fareNote")).font(ElchiFont.caption).foregroundStyle(c.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 18).padding(.vertical, 20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background { RoundedRectangle(cornerRadius: 28).fill(c.card).shadow(color: c.shadow, radius: 12, y: 6) }
        .overlay(alignment: .top) { Capsule().fill(c.outline).frame(width: 44, height: 5).padding(.top, 8).accessibilityHidden(true) }
        .padding(.top, -34)
    }

    private func trackerLabel(_ tracker: BookingDetailRules.Tracker, statusText: String) -> String {
        guard let current = tracker.current else { return statusText }
        let keys = booking.serviceType == .passenger ? PassengerStatus.ladder : StatusLadder.keys
        return keys.indices.contains(current) ? strings.t(keys[current]) : statusText
    }

    /// "Yaratilgan, 26 sen" / "Taxminan, 27 sen" (only from `dropoff.planned_arrival_at` - never an ETA) and the
    /// two places' short names.
    private var ends: some View {
        let created = ServerTime.parse(booking.createdAt)
        let planned = ServerTime.parse(booking.dropoff.plannedArrivalAt)
        let from = PlaceShort.of(strings.endAddress(booking.pickup.point))
        let to = PlaceShort.of(strings.endAddress(booking.dropoff.point))
        return HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(created.map { strings.t("client.booking.createdAt", ("date", strings.dayMonth($0))) } ?? strings.t("ui.from"))
                    .font(ElchiFont.caption).foregroundStyle(c.muted)
                Text(from).font(ElchiFont.poppins(15, .medium)).foregroundStyle(c.text)
            }
            .accessibilityElement(children: .combine)
            Spacer(minLength: 0)
            VStack(alignment: .trailing, spacing: 4) {
                Text(planned.map { strings.t("client.booking.plannedArrival", ("date", strings.dayMonth($0))) } ?? strings.t("ui.to"))
                    .font(ElchiFont.caption).foregroundStyle(c.muted)
                Text(to).font(ElchiFont.poppins(15, .medium)).foregroundStyle(c.text)
            }
            .multilineTextAlignment(.trailing)
            .accessibilityElement(children: .combine)
        }
    }

    /// Pochta: from, to, receiver (name, phone under it), final price, quantity and size, weight - with the photo
    /// column. Taksi: from, to, final price (n × unit under it), people, pickup window (the passenger's name is not in
    /// the DTO - BLOCKED, the cell is dropped).
    private var facts: some View {
        let parcel = booking.serviceType == .parcel
        let price = (strings.t("client.booking.finalPrice"), strings.money(booking.cashDueMinor),
                     parcel || !PassengerMoney.perSeat(booking.priceBasis) ? nil : strings.seatsTotal(booking.quantity, unitMinor: booking.unitPriceMinor))
        var items: [(String, String, String?)] = [
            (strings.t("ui.from"), strings.endAddress(booking.pickup.point), nil),
            (strings.t("ui.to"), strings.endAddress(booking.dropoff.point), nil),
        ]
        if parcel {
            let receiver = model.receiver
            items.append((strings.t("driverBooking.receiver"), receiver?.name ?? "—", receiver.map { UzPhone.display($0.phone) }))
            items.append(price)
            let pieces = strings.t("client.booking.quantityPieces", ("count", booking.quantity))
            let size = booking.parcelCategory.map(strings.name)
            items.append((strings.t("amendment.quantityLabel"), [pieces, size].compactMap { $0 }.joined(separator: " · "),
                          model.parcelType.map(strings.parcelTypeName)))
            items.append((strings.t("client.booking.weight"),
                          booking.parcelCategory.map { strings.t("client.booking.weightUpTo", ("weight", BookingDetailRules.weightText(grams: $0.maxWeightG))) } ?? "—",
                          nil))
        } else {
            items.append(price)
            items.append((strings.t("client.taxi.seats"), strings.t("seatPicker.peopleCount", ("count", booking.quantity)), nil))
            items.append((strings.t("driverBid.pickupWindow"), strings.bookingWhen(booking) ?? "—", nil))
        }
        let rows = stride(from: 0, to: items.count, by: 2).map { Array(items[$0..<min($0 + 2, items.count)]) }
        return HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 16) {
                ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                    HStack(alignment: .top, spacing: 12) {
                        fact(row[0])
                        if row.count > 1 { fact(row[1]) } else { Color.clear.frame(maxWidth: .infinity, maxHeight: 1) }
                    }
                }
            }
            if parcel { photo }
        }
    }

    private func fact(_ item: (String, String, String?)) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(item.0).font(ElchiFont.caption).foregroundStyle(c.muted)
            Text(item.1).font(ElchiFont.poppins(14.5, .medium)).foregroundStyle(c.text).lineSpacing(1).lineLimit(3)
                .fixedSize(horizontal: false, vertical: true)
            if let detail = item.2 { Text(detail).font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true) }
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
}

// MARK: - Bronni bekor qilish

/// "Bronni bekor qilasizmi?" - the policy (the full sentence: the server's summary is the authority, so the design's
/// short "Pilot davrida jarima yo'q." is not used), "Sabab" as the design's chips (single choice, the first chosen),
/// an optional comment (≤ 200, contacts are masked), "Ha, bekor qilish" / "Bronni saqlash". A refusal stays on the
/// sheet, said for this booking; success closes it with the toast.
private struct CancelBookingSheet: View {
    let model: BookingModel
    let onClose: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(BannerCenter.self) private var banners: BannerCenter?
    @State private var reason: BookingCancelReason = .plansChanged
    @State private var comment = ""

    var body: some View {
        let working = model.running == .cancel
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(strings.t("bookingCancel.title")).font(ElchiFont.poppins(20, .medium, relativeTo: .title2)).foregroundStyle(c.text)
                        .accessibilityAddTraits(.isHeader)
                    Text(strings.t("bookingCancel.body")).font(ElchiFont.secondary).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
                }
                Text(strings.t("bookingCancel.reasonLabel")).font(ElchiFont.label).foregroundStyle(c.text)
                FlowLayout(spacing: 8) {
                    ForEach(BookingCancelReason.allCases, id: \.self) { option in
                        reasonChip(option)
                    }
                }
                .accessibilityElement(children: .contain)
                .accessibilityLabel(strings.t("bookingCancel.reasonLabel"))
                ElchiField(text: $comment, placeholder: strings.t("bookingCancel.commentLabel"), hint: strings.t("bookingChat.autoMaskNote"), multiline: true)
                    .onChange(of: comment) { _, typed in if typed.count > 200 { comment = String(typed.prefix(200)) } }
                if let error = model.commandError, model.failed == .cancel, !working { Note(strings.cancelErrorText(error), tone: .err) }
                HStack(spacing: 8) {
                    ElchiButton(strings.t("bookingCancel.confirm"), variant: .danger, size: .pair, loading: working) {
                        Task {
                            if await model.cancel(reason: reason, comment: comment) {
                                banners?.ok("client.booking.cancelledToast")
                                onClose()
                            }
                        }
                    }
                    .accessibilityIdentifier("elchi.cancel.confirm")
                    ElchiButton(strings.t("bookingCancel.keep"), variant: .neutral, size: .pair, action: onClose).disabled(working)
                        .accessibilityIdentifier("elchi.cancel.keep")
                }
            }
            .padding(EdgeInsets(top: 28, leading: 20, bottom: 12, trailing: 20))
        }
        .scrollDismissesKeyboard(.interactively)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(c.card.ignoresSafeArea())
        .presentationDetents([.height(480), .large])
        .presentationCornerRadius(ElchiShape.sheet)
        .presentationDragIndicator(.visible)
        .onAppear { model.clearNotice() }
    }

    /// The design's chip: the chosen one dark-filled (navy, white text), the others outlined on the card.
    private func reasonChip(_ option: BookingCancelReason) -> some View {
        let selected = option == reason
        return Button { reason = option } label: {
            Text(strings.t(option.key)).font(ElchiFont.poppins(13, .medium))
                .foregroundStyle(selected ? Color.white : c.text)
                .padding(.horizontal, 14).padding(.vertical, 9)
                .frame(minHeight: 40)
                .background(selected ? (c.isDark ? Color(hex: 0x1B3563) : c.navy) : c.card, in: Capsule())
                .overlay { Capsule().strokeBorder(selected ? Color.clear : c.line, lineWidth: 1) }
        }
        .buttonStyle(PressFade())
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
        .accessibilityIdentifier("elchi.cancel.reason.\(option.rawValue)")
    }
}

