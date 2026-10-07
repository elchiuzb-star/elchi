import SwiftUI

// MARK: - Buyurtmalar tab

/// "Takliflarim" on top (Stage 08), then the driver's bookings: route, status (parcel wording), pickup date and the
/// agreed total; Faol / Tarix; more pages at the bottom.
struct DriverOrdersTab: View {
    let proposals: DriverProposalsModel
    let bookings: DriverBookingsModel
    let onProposals: () -> Void
    let onOpen: (String) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        DriverTabScreen(title: strings.t("driverOrders.title")) {
            ElchiList {
                ListRow(icon: .tag, title: strings.t("proposals.title"), description: strings.t("proposals.emptyDriver"),
                        trailing: proposals.openCount.map { $0 > 0 ? "\($0)" : nil } ?? nil, first: true, action: onProposals)
                    .accessibilityIdentifier("elchi.driver.proposals")
            }
            Segmented(DriverBookingFilter.allCases.map { ($0, strings.t($0.labelKey)) }, selected: bookings.filter) { bookings.filter = $0 }
            switch bookings.items {
            case .loading:
                SkeletonCards(count: 3)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err)
                ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await bookings.load() } }
            case .loaded:
                let list = bookings.visible
                if list.isEmpty {
                    EmptyState(icon: .clip, title: strings.t("driverOrders.empty"), description: strings.t("driverOrders.emptyHint"))
                }
                ForEach(list) { booking in
                    DriverBookingRow(booking: booking) { onOpen(booking.id) }
                }
                if bookings.nextCursor != nil {
                    ElchiButton(strings.t("blockReport.loadMore"), variant: .ghost, size: .medium, loading: bookings.loadingMore) {
                        Task { await bookings.loadMore() }
                    }
                }
            }
        }
        .refreshable {
            async let list: Void = bookings.load()
            async let offers: Void = proposals.load(.open)
            _ = await (list, offers)
        }
        .task {
            async let list: Void = bookings.load()
            async let offers: Void = proposals.load(.open)
            _ = await (list, offers)
        }
    }
}

/// One booking in the list (design v3 'orders'): a pin for a passenger, a package for a parcel; "Yo'lovchi · 2 kishi ·
/// 27 sen" / "Pochta · 27 sen" (no client name); the short badge ("Kelmadi · ko'rikda" while a no-show report waits);
/// "2 × 150 000 so'm" for a per-seat passenger booking, else the total. Finished rows are a little quieter.
struct DriverBookingRow: View {
    let booking: DriverBookingDTO
    let onOpen: () -> Void
    @Environment(LocaleStore.self) private var strings

    var body: some View {
        let base = booking.base
        let passenger = base.serviceType == .passenger
        let service = passenger
            ? "\(strings.t("client.taxi.passenger")) · \(strings.t("orderForm.review.peopleCount", ("count", base.quantity)))"
            : strings.t("driverFeed.modeParcel")
        let day = ServerTime.parse(base.pickup.windowStart).map(strings.dayMonth)
        ItemCard(title: strings.route(base), icon: passenger ? .pin : .pkg, badge: strings.status(DriverBookingBadge.of(base, short: true)),
                 meta: [service, day].compactMap { $0 }.joined(separator: " · "),
                 right: DriverBookingLayout.showsSeatPrice(booking)
                    ? strings.seatsTotal(base.quantity, unitMinor: base.unitPriceMinor) : strings.money(base.totalMinor), action: onOpen)
        .opacity(BookingActions.of(base.serviceStatus).terminal ? 0.75 : 1)
        .accessibilityIdentifier("elchi.driver.booking.\(booking.id)")
    }
}

// MARK: - Buyurtma tafsilotlari (driver)

/// The driver's booking in the client's design-04 layout (BOSQICH 08 v3): the map hero (opens tracking; the pill from
/// this phone's tracker), the sheet card (status, the five dots, the ends, the facts, the cash and commission lines),
/// the notices (cancelled, on its way, arrived, no GPS, the open amendment), then the actions in the design's order -
/// "Keldim" (kept: the no-show needs it, Q7), the passenger block (code, "Mijoz kelmadi", "Manzilga yetib keldik"),
/// the cash record, amend, "Yordam / shikoyat" (Q146), cancel, rating, the client's reputation and the folded safety
/// row - and the fixed contact bar: call (only when the server shows a phone, Q44/Q142) and chat with the unseen count.
/// Parcel keeps what it has: no codes, no cash record, no "Mijoz kelmadi" (Q139).
struct DriverBookingDetailView: View {
    let model: DriverBookingModel
    let onBack: () -> Void
    let onChat: () -> Void
    let onTracking: () -> Void
    let onAmend: () -> Void
    let onRate: () -> Void
    let onSupport: () -> Void
    let onSafety: () -> Void
    /// Taksi: `TRIP_NOT_STARTED` on board - the trip, to start boarding.
    var onTrip: () -> Void = {}
    /// This phone's GPS publisher: whether the client sees the car is decided from it, never from the server.
    var tracker: DriverTracker?
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(\.openURL) private var openURL
    @Environment(BannerCenter.self) private var banners: BannerCenter?
    @State private var confirmCancel = false

    var body: some View {
        ScreenScaffold(title: strings.t("driverBooking.title"), backLabel: strings.t("common.back"), onBack: onBack, banner: banner,
                       plainFooter: true) {
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
            if let booking = model.booking.value { contactBar(booking) }
        }
        .refreshable { await model.load() }
        .onAppear { Task { await model.load() } }
        .sheet(isPresented: $confirmCancel) {
            DriverCancelSheet(model: model) { confirmCancel = false }
                .environment(\.screenAccessory, nil)
        }
    }

    private var banner: (text: String, tone: Tone)? {
        if let error = model.commandError, model.running == nil, model.failed == .cancel {
            return (DriverCancelReason.refusalKey(error).map { strings.t($0) } ?? strings.errorText(error), .err)
        }
        return model.notice.map { (strings.t($0), .ok) }
    }

    /// The trip's location goes out from this phone right now.
    private func sending(_ booking: DriverBookingDTO) -> Bool { tracker?.isRunning(booking.tripId) ?? false }

    @ViewBuilder
    private func content(_ booking: DriverBookingDTO) -> some View {
        let base = booking.base
        let actions = DriverBookingActions.of(base.serviceStatus, arrivedSent: model.arrivedSent, updatedAt: ServerTime.parse(base.updatedAt))
        let passenger = base.serviceType == .passenger
        let taxi = DriverTaxiActions.of(base.serviceStatus, arrivedSent: model.arrivedSent, noShowReview: base.noShowReview?.status)
        let amend = DriverBookingLayout.amendNotice(model.amendments.items.value)
        ForEach(model.warnings, id: \.code) { Note(strings.warningText($0), tone: .warn) }
        let chip = DriverBookingLayout.chip(status: base.serviceStatus, sending: sending(booking))
        DriverMapHero(markers: markers(base), chip: chip, label: strings.t(chip.key),
                      accessibility: strings.t("driver.v3bkg.trackingTitle"), action: onTracking)
        DriverBookingSheet(booking: booking, photoURL: model.photoURL)
        notices(booking, actions: actions, amend: amend)
        if let promo = booking.promo { promoBlock(promo) }
        if actions.canArrive {
            ElchiButton(strings.t("driverBooking.action.arrive"), icon: .pin, loading: model.arriving) { Task { await model.arrive() } }
                .accessibilityIdentifier("elchi.driver.booking.arrive")
        }
        if let error = model.arriveError { Note(strings.errorText(error), tone: .err) }
        if passenger {
            DriverTaxiSection(model: model.taxi, booking: booking, actions: taxi, onTrip: onTrip)
            if taxi.cash {
                CashRecordSection(model: model.cash, booking: base, dueMinor: DriverBookingMoney.cashToCollect(booking))
            }
        }
        // 7.4: while the client has not answered the driver's new price, no second one is offered.
        if actions.canAmend, !isPending(amend) {
            ElchiButton(strings.t("driverBooking.amend"), variant: .neutral, size: .medium, action: onAmend)
                .accessibilityIdentifier("elchi.driver.booking.amend")
        }
        // Q146: help is the main support action.
        ElchiButton(strings.t("support.complain"), variant: .neutral, size: .medium, icon: .head, action: onSupport)
            .accessibilityIdentifier("elchi.driver.booking.support")
        // Q19/Q75: while a no-show review is pending only an operator cancels - the button is not offered.
        if actions.canCancel && !taxi.noShowPending {
            ElchiButton(strings.t("bookingCancel.button"), variant: .dangerSoft, size: .medium) {
                model.clearNotice()
                confirmCancel = true
            }
            .disabled(model.running != nil)
            .accessibilityIdentifier("elchi.driver.booking.cancel")
        }
        if actions.canRate || base.serviceStatus == "completed" { rating(actions) }
        reputationCard(booking)
        // Q146: the safety report and block live apart from the help button, one tap further.
        SafetyEntryRow(title: strings.t("safety.menuTitle"), action: onSafety)
            .padding(.top, 4)
    }

    private func isPending(_ notice: DriverBookingLayout.AmendNotice?) -> Bool {
        if case .pending? = notice { return true }
        return false
    }

    /// The coloured boxes under the sheet, in the design's order.
    @ViewBuilder
    private func notices(_ booking: DriverBookingDTO, actions: DriverBookingActions, amend: DriverBookingLayout.AmendNotice?) -> some View {
        let base = booking.base
        if let cancelled = base.cancelled, base.serviceStatus == "cancelled" || base.serviceStatus == "no_show" {
            BookingNoticeBox(text: strings.cancelledLine(cancelled), tone: .err)
        }
        if actions.inTransit {
            Note(strings.t("driver.booking.inTransitNote"), tone: .blue)
        }
        if DriverBookingLayout.arrivedNote(base.serviceType, base.serviceStatus) {
            Note(strings.t("driver.v3bkg.arrivedNote"), tone: .ok)
                .accessibilityIdentifier("elchi.driver.booking.arrivedNote")
        }
        if model.arrivedSent && !actions.canArrive && DriverBookingActions.preService.contains(base.serviceStatus)
            && base.noShowReview?.status != "pending" {
            Note(strings.t("driver.booking.arrivedSent"), tone: .ok)
        }
        if DriverBookingLayout.gpsOffWarning(status: base.serviceStatus, sending: sending(booking)) {
            Note(strings.t("driver.v3bkg.gpsOffWarn"), tone: .warn)
                .accessibilityIdentifier("elchi.driver.booking.gpsOff")
        }
        switch amend {
        case .pending(let amendment, let reason)?:
            // `AmendmentDTO` has no reason (BLOCKED): the one sent from this phone, else the sentence without it.
            Group {
                if let reason = reason ?? model.amendments.sentReason {
                    Note(strings.t("driver.v3bkg.amendPending", ("price", amendPrice(amendment, base)), ("reason", reason)), tone: .blue)
                } else {
                    Note("\(strings.t("amendment.newTotal", ("total", amendPrice(amendment, base)))). \(strings.t("client.amendment.openExists"))",
                         tone: .blue, title: strings.t("amendment.sent"))
                }
            }
            .accessibilityIdentifier("elchi.driver.booking.amendPending")
        case .accepted(let amendment)? where !BookingActions.of(base.serviceStatus).terminal:
            Note(strings.t("driver.v3bkg.amendAccepted", ("price", amendPrice(amendment, base))), tone: .ok)
        default:
            EmptyView()
        }
    }

    /// "2 × 160 000 so'm" for a per-seat passenger booking, else the new total.
    private func amendPrice(_ amendment: AmendmentDTO, _ base: ClientBookingDTO) -> String {
        base.serviceType == .passenger && PassengerMoney.perSeat(base.priceBasis)
            ? strings.seatsTotal(amendment.newQuantity, unitMinor: amendment.newUnitPriceMinor) : strings.money(amendment.newTotalMinor)
    }

    private func markers(_ base: ClientBookingDTO) -> [MapMarker] {
        [base.pickup.point.map { MapMarker(GeoPoint(lat: $0.lat, lng: $0.lng), .origin) },
         base.dropoff.point.map { MapMarker(GeoPoint(lat: $0.lat, lng: $0.lng), .destination) }].compactMap { $0 }
    }

    // MARK: Contact bar

    /// The client's initials and first name; "Yo'lovchi · 2 kishi · raqam yopiq" (or the phone) - for a parcel the
    /// receiver's phone once the trip departed (Q142; the sender's never, Q44). Grey call = a toast saying when.
    private func contactBar(_ booking: DriverBookingDTO) -> some View {
        let base = booking.base
        let phone = DriverBookingLayout.phone(booking)
        var parts: [String]
        if base.serviceType == .passenger {
            parts = [strings.t("client.taxi.passenger"), strings.t("orderForm.review.peopleCount", ("count", base.quantity))]
        } else {
            parts = [strings.t("driverFeed.modeParcel")]
        }
        switch phone {
        case .visible(let number):
            parts.append(base.serviceType == .parcel ? "\(strings.t("driverBooking.receiver")): \(UzPhone.display(number))" : UzPhone.display(number))
        case .locked, .closed:
            parts.append(strings.t("driver.v3bkg.phoneClosedShort"))
        }
        var open = false
        if case .visible = phone { open = true }
        return DriverContactBar(name: clientName(booking), line: parts.joined(separator: " · "), phoneOpen: open, unread: model.unreadChat,
                                callLabel: strings.t("client.bookingDetail.call"), chatLabel: strings.t("bookingChat.title"),
                                onCall: { call(phone, service: base.serviceType) }, onChat: onChat)
    }

    private func call(_ phone: DriverBookingLayout.Phone, service: ServiceType) {
        if case .visible(let number) = phone, let url = DriverReveal.dialURL(number) {
            openURL(url)
        } else if let key = DriverBookingLayout.callRefusalKey(phone, service: service) {
            banners?.show(.key(key), tone: .info, hideAfter: .seconds(3))
        }
    }

    private func clientName(_ booking: DriverBookingDTO) -> String {
        let name = booking.client?.displayName.trimmingCharacters(in: .whitespaces) ?? ""
        return name.isEmpty ? strings.t("driver.booking.clientFallback") : name
    }

    private func promoBlock(_ promo: BookingPromoDriverDTO) -> some View {
        MoneyLines(title: strings.t("promoScreen.moneyTitle"), rows: [
            MoneyLines.Row(strings.t("promo.line.agreedPrice"), strings.money(promo.fareMinor)),
            MoneyLines.Row(strings.t("promo.line.cashFromClient"), strings.money(promo.cashToCollectMinor), emphasis: true),
            MoneyLines.Row(strings.t("promo.line.discountCovered"), strings.money(promo.passengerDiscountCoveredMinor)),
            MoneyLines.Row(strings.t("commissionPreview.title"), strings.money(promo.baseCommissionMinor)),
            MoneyLines.Row(strings.t("promo.line.creditToUse"), "−\(strings.money(promo.driverCreditMinor))", tone: .ok),
            MoneyLines.Row(strings.t("promo.line.chargedFromBalance"), strings.money(promo.commissionChargedMinor)),
            MoneyLines.Row(strings.t("promo.line.youKeep"), strings.money(promo.driverKeepsMinor), emphasis: true),
        ])
    }

    /// Navy "Mijozni baholash" once completed (7 days); after it "Baho berildi: ★★★★ (4 / 5)" with the stars just
    /// sent, or plain "Baho berildi" after a reload.
    @ViewBuilder
    private func rating(_ actions: DriverBookingActions) -> some View {
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
        } else if actions.canRate {
            ElchiButton(strings.t("rating.rateClient"), action: onRate)
                .accessibilityIdentifier("elchi.driver.booking.rate")
            Text(strings.t("driver.booking.rateNote")).font(ElchiFont.caption).foregroundStyle(c.muted)
        }
    }

    /// "Reyting" - "Mijoz: Aziza" with "Yangi" (or "★ 4,9 · 14 ta") on the right, "Hali baholanmagan · Bajarilgan
    /// bronlar: 2 ta" under it (never a made-up score, §9).
    @ViewBuilder
    private func reputationCard(_ booking: DriverBookingDTO) -> some View {
        if let reputation = model.reputation {
            let line = ClientReputation.line(reputation)
            let completed = "\(strings.t("reputation.completedBookings")): \(strings.t("reputation.count", ("count", line.completed)))"
            ElchiCard {
                CardTitle(strings.t("reputation.title"))
                CardRow("\(strings.t("driver.booking.clientTitle")): \(clientName(booking))",
                        line.score.map { "★ \($0) · \(strings.t("reputation.count", ("count", line.ratingCount)))" } ?? strings.t("reputation.new"),
                        first: true,
                        detail: line.score == nil ? "\(strings.t("reputation.notRated")) · \(completed)" : completed)
            }
            .accessibilityIdentifier("elchi.driver.booking.reputation")
        }
    }
}

// MARK: - Bronni bekor qilish (driver)

/// "Bronni bekor qilasizmi?" with the driver's four reasons, an optional comment, "Ha, bekor qilish" / "Bronni
/// saqlash"; a refusal stays on the sheet (`bookingCancel.refused.*`).
struct DriverCancelSheet: View {
    let model: DriverBookingModel
    let onClose: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var reason: DriverCancelReason = .tripChanged
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
                // DESIGN08 8.2: the reasons as wrap chips (the first chosen), as on Android and the client's sheet.
                Text(strings.t("bookingCancel.reasonLabel")).font(ElchiFont.label).foregroundStyle(c.text)
                FlowLayout(spacing: 8) {
                    ForEach(DriverCancelReason.allCases, id: \.self) { option in reasonChip(option) }
                }
                .accessibilityElement(children: .contain)
                .accessibilityLabel(strings.t("bookingCancel.reasonLabel"))
                ElchiField(text: $comment, label: strings.t("bookingCancel.commentLabel"), hint: strings.t("bookingChat.autoMaskNote"), multiline: true)
                if let error = model.commandError, model.failed == .cancel, !working {
                    Note(DriverCancelReason.refusalKey(error).map { strings.t($0) } ?? strings.errorText(error), tone: .err)
                }
                HStack(spacing: 8) {
                    ElchiButton(strings.t("bookingCancel.confirm"), variant: .danger, size: .pair, loading: working) {
                        Task { if await model.cancel(reason: reason, comment: comment) { onClose() } }
                    }
                    .accessibilityIdentifier("elchi.driver.cancel.confirm")
                    ElchiButton(strings.t("bookingCancel.keep"), variant: .neutral, size: .pair, action: onClose).disabled(working)
                }
            }
            .padding(EdgeInsets(top: 28, leading: 20, bottom: 12, trailing: 20))
        }
        .scrollDismissesKeyboard(.interactively)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(c.card.ignoresSafeArea())
        .presentationDetents([.height(520), .large])
        .presentationCornerRadius(ElchiShape.sheet)
        .presentationDragIndicator(.visible)
        .onAppear { model.clearNotice() }
    }

    /// The chosen chip dark-filled (navy, white text), the others outlined on the card.
    private func reasonChip(_ option: DriverCancelReason) -> some View {
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
        .accessibilityIdentifier("elchi.driver.cancel.reason.\(option.rawValue)")
    }
}
