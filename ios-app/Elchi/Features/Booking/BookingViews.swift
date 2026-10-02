import SwiftUI
import UIKit

// MARK: - Buyurtma tafsilotlari (bron)

/// One booking of the client's (parcel): the header card, driver and vehicle (Q43/Q44/Q64 reveal rules), money, the
/// parcel, chat and tracking, the recipient link, then what the status allows - amend (confirmed only), rate
/// (completed only), help (Q146: the main support action), cancel - and, apart from them, the safety row.
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
    @State private var confirmCancel = false
    @State private var confirmComplete = false

    var body: some View {
        ScreenScaffold(title: strings.t("listingDetail.title"), backLabel: strings.t("common.back"), onBack: onBack, banner: banner) {
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
            EmptyView()
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
                        _ = await model.complete()
                        confirmComplete = false
                    }
                }, onClose: { confirmComplete = false })
            }
        }
    }

    /// What the last command did (or why it failed), kept in sight under the top bar.
    private var banner: (text: String, tone: Tone)? {
        if let error = model.commandError, model.running == nil, model.failed == .cancel { return (strings.cancelErrorText(error), .err) }
        if let error = model.commandError, model.running == nil, model.failed == .complete { return (strings.errorText(error), .err) }
        return model.notice.map { (strings.t($0), .ok) }
    }

    @ViewBuilder
    private func content(_ booking: ClientBookingDTO) -> some View {
        let actions = BookingActions.of(booking.serviceStatus)
        let taxi = ClientTaxiActions.of(booking)
        ForEach(model.warnings, id: \.code) { Note(strings.warningText($0), tone: .warn) }

        ItemCard(title: strings.route(booking), icon: .pin, badge: strings.status(.booking(booking.serviceType, booking.serviceStatus)),
                 lines: booking.cancelled.map { [ItemLine(strings.cancelledLine($0), tone: .err)] } ?? [],
                 meta: strings.bookingWhen(booking), right: strings.bookingPrice(booking))
            .accessibilityIdentifier("elchi.booking.header")
        // Q7: the driver reported a no-show; an operator reviews it and only an operator cancels meanwhile.
        if taxi.noShowPending { Note(strings.t("bookingCancel.reviewPending"), tone: .warn) }
        driverCard(booking)
        if taxi.showCode { BoardingCodeSection(model: model.code) }
        if let promo = booking.promo { promoBlock(promo) }
        fareCard(booking)
        if taxi.cash { CashRecordSection(model: model.cash, booking: booking, dueMinor: booking.cashDueMinor) }
        if taxi.canComplete {
            ElchiButton(strings.t("client.taxi.complete"), icon: .checkC) {
                model.clearNotice()
                confirmComplete = true
            }
            .disabled(model.running != nil)
            .accessibilityIdentifier("elchi.taxi.complete")
        }
        photo
        HStack(spacing: 8) {
            ElchiButton(strings.t("bookingDetail.messages"), variant: .soft, size: .pair, icon: .chat, action: onChat)
            ElchiButton(strings.t("bookingDetail.tracking"), variant: .soft, size: .pair, icon: .pin, action: onTracking)
        }
        if actions.canShareTracking { TrackingShareSection(model: model) }
        if actions.canAmend {
            ElchiButton(strings.t("amendment.title"), variant: .neutral, action: onAmend)
        }
        if actions.canRate { rating }
        ElchiButton(strings.t("support.complain"), variant: .neutral, icon: .head, action: onSupport)
        if actions.canCancel {
            ElchiButton(strings.t("bookingCancel.button"), variant: .dangerSoft) {
                model.clearNotice()
                confirmCancel = true
            }
            .disabled(model.running != nil)
        }
        // Q146: the safety report and block live apart from the help button, one tap further.
        ElchiList {
            ListRow(icon: .shield, title: strings.t("safety.menuTitle"), description: strings.t("client.bookingDetail.safetyHint"), first: true,
                    action: onSafety)
        }
        .padding(.top, 8)
    }

    // MARK: Driver and vehicle

    @ViewBuilder
    private func driverCard(_ booking: ClientBookingDTO) -> some View {
        if let driver = booking.driver, let reveal = DriverReveal.of(booking) {
            ElchiCard {
                CardTitle(strings.t("client.bookingDetail.driverCard"),
                          badge: reveal.phone != nil ? (strings.t("client.bookingDetail.contactOpen"), .ok) : nil)
                CardRow(strings.t("safety.driverTitle"), driver.displayName, detail: model.reputation.map(strings.reputationLine))
                CardRow(strings.t("addRoute.vehicle"), strings.vehicleName(driver.vehicle), detail: strings.vehicleClassLine(driver.vehicle))
                // A finished or cancelled booking never opens the full plate: no promise of it then.
                CardRow(strings.t("driverProfileForm.plateNumber"), reveal.plate,
                        detail: reveal.plateFull ? strings.t("client.bookingDetail.plateOpen")
                            : BookingActions.of(booking.serviceStatus).terminal ? nil : strings.t("client.bookingDetail.plateLater"))
                if let phone = reveal.phone {
                    CardRow(strings.t("driverBooking.phone"), UzPhone.display(phone), trailing: strings.t("client.bookingDetail.call")) {
                        if let url = DriverReveal.dialURL(phone) { openURL(url) }
                    }
                } else if !BookingActions.of(booking.serviceStatus).terminal {
                    // A passenger's service starts at boarding (Q44), a parcel's when the trip departs (Q142).
                    CardRow(strings.t("driverBooking.phone"),
                            strings.t(booking.serviceType == .passenger ? "driverBooking.phoneHidden" : "client.bookingDetail.phoneLater"),
                            detail: strings.t("client.bookingDetail.phoneChatOnly"), placeholder: true)
                }
            }
        }
    }

    private func promoBlock(_ promo: BookingPromoClientDTO) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            MoneyLines(title: strings.t("promoScreen.moneyTitle"), rows: [
                MoneyLines.Row(strings.t("promo.line.agreedPrice"), strings.money(promo.fareMinor)),
                MoneyLines.Row(strings.t("promo.line.bonusDiscount"), "−\(strings.money(promo.passengerDiscountMinor))", tone: .ok),
                MoneyLines.Row(strings.t("promo.line.cashToDriver"), strings.money(promo.cashDueMinor), emphasis: true),
            ])
            Text(strings.t("promoScreen.clientCovers")).font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
        }
    }

    private func fareCard(_ booking: ClientBookingDTO) -> some View {
        ElchiCard {
            CardRow(strings.t("bookingDetail.fare"), strings.t("bookingDetail.fareCash", ("amount", strings.money(booking.cashDueMinor))), first: true,
                    detail: strings.t("bookingDetail.fareNote"))
            if booking.serviceType == .passenger {
                // "2 kishi · 2 × 150 000 so'm": the agreed people and the per-seat price.
                CardRow(strings.t("orderForm.review.passengers"), strings.peopleLine(booking.quantity, unitMinor: booking.unitPriceMinor),
                        detail: strings.t("orderForm.review.seatNegotiated"))
            }
            if let parcel = strings.parcelLine(booking.parcelCategory, type: model.parcelType) {
                CardRow(strings.t("listingDetail.parcel"), parcel)
            }
            if let receiver = model.receiver {
                CardRow(strings.t("driverBooking.receiver"), "\(receiver.name) · \(UzPhone.display(receiver.phone))")
            }
        }
    }

    @ViewBuilder
    private var photo: some View {
        if let url = model.photoURL {
            // A short-lived signed link (Q6): when it has expired, pulling to refresh fetches a new one.
            AsyncImage(url: url) { phase in
                switch phase {
                case .success(let image):
                    image.resizable().scaledToFill()
                case .failure:
                    Text(strings.t("app.photo.reload")).font(ElchiFont.caption).foregroundStyle(c.muted)
                default:
                    ProgressView()
                }
            }
            .frame(maxWidth: .infinity).frame(height: 150)
            .background(c.field)
            .clipShape(RoundedRectangle(cornerRadius: 18))
            .accessibilityLabel(strings.t("app.photo.alt"))
        }
    }

    @ViewBuilder
    private var rating: some View {
        if let outcome = model.rating {
            switch outcome {
            case .sent: Note(strings.t("client.bookingDetail.rated"), tone: .ok)
            case .already: Note(strings.t("error.RATING_ALREADY_EXISTS"), tone: .ok, title: strings.t("client.bookingDetail.rated"))
            case .notAllowed: Note(strings.t("error.RATING_NOT_ALLOWED"), tone: .gray)
            }
        } else {
            ElchiButton(strings.t("rating.rateDriver"), action: onRate)
        }
    }
}

// MARK: - Bronni bekor qilish

/// "Bronni bekor qilasizmi?" - reason (the design's four), an optional comment (contacts are masked), "Ha, bekor
/// qilish" / "Bronni saqlash". A refusal stays on the sheet, said for this booking.
private struct CancelBookingSheet: View {
    let model: BookingModel
    let onClose: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var reason: BookingCancelReason = .plansChanged
    @State private var comment = ""

    var body: some View {
        let working = model.running == .cancel
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(strings.t("bookingCancel.title")).font(ElchiFont.poppins(20, .medium, relativeTo: .title2)).foregroundStyle(c.text)
                        .accessibilityAddTraits(.isHeader)
                    Text(strings.t("bookingCancel.body")).font(ElchiFont.secondary).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
                }
                SelectField(label: strings.t("bookingCancel.reasonLabel"), options: BookingCancelReason.allCases.map { ($0, strings.t($0.key)) },
                            selected: reason, placeholder: strings.t("blockReport.chooseReason")) { reason = $0 }
                ElchiField(text: $comment, label: strings.t("bookingCancel.commentLabel"), hint: strings.t("bookingChat.autoMaskNote"), multiline: true)
                if let error = model.commandError, model.failed == .cancel, !working { Note(strings.cancelErrorText(error), tone: .err) }
                HStack(spacing: 8) {
                    ElchiButton(strings.t("bookingCancel.confirm"), variant: .danger, size: .pair, loading: working) {
                        Task { if await model.cancel(reason: reason, comment: comment) { onClose() } }
                    }
                    ElchiButton(strings.t("bookingCancel.keep"), variant: .neutral, size: .pair, action: onClose).disabled(working)
                }
            }
            .padding(EdgeInsets(top: 28, leading: 20, bottom: 12, trailing: 20))
        }
        .scrollDismissesKeyboard(.interactively)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(c.card.ignoresSafeArea())
        .presentationDetents([.height(500), .large])
        .presentationCornerRadius(ElchiShape.sheet)
        .presentationDragIndicator(.visible)
        .onAppear { model.clearNotice() }
    }
}

// MARK: - Yaqinlaringiz bilan kuzatuv

/// The recipient link: lifetime chips (15 minutes to 24 hours), "Havola yaratish", then the link once - with copy,
/// the share sheet and revoke. The link shows only the vehicle's state and last location (no name, phone, address).
private struct TrackingShareSection: View {
    let model: BookingModel
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var copied = false

    var body: some View {
        SectionTitle(strings.t("tracking.shareTitle"), description: strings.t("trackingShare.trackingHint"))
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(TrackingTTL.minutes, id: \.self) { minutes in
                    Chip(label(minutes), selected: model.grantMinutes == minutes, filled: true) { model.grantMinutes = minutes }
                }
            }
        }
        .accessibilityLabel(strings.t("trackingShare.ttlLabel"))
        ElchiButton(strings.t("trackingShare.create"), variant: .soft, icon: .share, loading: model.running == .grant) {
            copied = false
            Task { await model.createGrant() }
        }
        .disabled(model.running != nil)
        if let error = model.commandError, model.running == nil, model.failed == .grant {
            Note(strings.grantErrorText(error), tone: .err)
        }
        if let grant = model.grant, let url = model.grantURL { linkBox(grant, url) }
    }

    private func label(_ minutes: Int) -> String {
        minutes < 60 ? strings.t("trackingShare.ttlMinutes", ("count", minutes)) : strings.t("trackingShare.ttlHours", ("count", minutes / 60))
    }

    private func linkBox(_ grant: TrackingGrantDTO, _ url: URL) -> some View {
        ElchiCard(padding: EdgeInsets(top: 12, leading: 14, bottom: 12, trailing: 14)) {
            VStack(alignment: .leading, spacing: 10) {
                Text(strings.t("trackingShare.trackingTitle")).font(ElchiFont.caption).foregroundStyle(c.muted)
                Text(url.absoluteString).font(.system(size: 13, design: .monospaced)).foregroundStyle(c.text).lineLimit(2).textSelection(.enabled)
                    .padding(12).frame(maxWidth: .infinity, alignment: .leading)
                    .background(c.field, in: RoundedRectangle(cornerRadius: 14))
                if let from = ServerTime.parse(grant.validFrom), from > Date() {
                    Text(strings.t("client.trackingShare.validFrom", ("time", DepartureWindow.shortText(from)))).font(ElchiFont.caption).foregroundStyle(c.muted)
                }
                if let expires = ServerTime.parse(grant.expiresAt) {
                    Text(strings.t("trackingShare.validUntil", ("time", DepartureWindow.text(expires)))).font(ElchiFont.caption).foregroundStyle(c.muted)
                }
                HStack(spacing: 8) {
                    ElchiButton(strings.t(copied ? "trackingShare.copied" : "promoScreen.copy"), variant: .soft, size: .pair, icon: .copy) {
                        UIPasteboard.general.string = url.absoluteString
                        copied = true
                    }
                    ShareLink(item: url) {
                        HStack(spacing: 6) {
                            ElchiIcon.share.image(size: 18)
                            Text(strings.t("client.share.send")).font(ElchiFont.buttonSmall).lineLimit(1)
                        }
                        .foregroundStyle(c.onBrand)
                        .frame(maxWidth: .infinity, minHeight: 48)
                        .background(c.brand, in: Capsule())
                    }
                }
                Text(strings.t("trackingShare.urlOnce")).font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
                ElchiButton(strings.t("client.share.revoke"), variant: .ghost, size: .medium, loading: model.running == .revokeGrant) {
                    Task { await model.revokeGrant() }
                }
            }
        }
    }
}
