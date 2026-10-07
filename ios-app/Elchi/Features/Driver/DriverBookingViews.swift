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

/// One booking in the list (design 'driver-orders').
struct DriverBookingRow: View {
    let booking: DriverBookingDTO
    let onOpen: () -> Void
    @Environment(LocaleStore.self) private var strings

    var body: some View {
        let base = booking.base
        ItemCard(title: strings.route(base), icon: .pin, badge: strings.status(.booking(base.serviceType, base.serviceStatus)),
                 meta: ServerTime.parse(base.pickup.windowStart).map(strings.dayMonth),
                 right: base.serviceType == .passenger && PassengerMoney.perSeat(base.priceBasis)
                    ? strings.seatsTotal(base.quantity, unitMinor: base.unitPriceMinor) : strings.money(base.totalMinor), action: onOpen)
        .accessibilityIdentifier("elchi.driver.booking.\(booking.id)")
    }
}

// MARK: - Buyurtma tafsilotlari (driver, parcel)

/// The driver's booking (design 'driver-order-detail', parcel): header, the card (ends, client, parcel, receiver after
/// departure, cash to collect, commission), the in-transit note, then what the status allows - "Keldim", chat and
/// tracking, amendment, help (Q146 main action), cancel, rating the client - the client's reputation, and the folded
/// safety row. Nothing parcel does not have: no codes, no cash receipt, no "Mijoz kelmadi" (Q139).
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
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(\.openURL) private var openURL
    @State private var confirmCancel = false

    var body: some View {
        ScreenScaffold(title: strings.t("driverBooking.title"), backLabel: strings.t("common.back"), onBack: onBack, banner: banner) {
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

    @ViewBuilder
    private func content(_ booking: DriverBookingDTO) -> some View {
        let base = booking.base
        let actions = DriverBookingActions.of(base.serviceStatus, arrivedSent: model.arrivedSent, updatedAt: ServerTime.parse(base.updatedAt))
        ForEach(model.warnings, id: \.code) { Note(strings.warningText($0), tone: .warn) }
        let passenger = base.serviceType == .passenger
        let taxi = DriverTaxiActions.of(base.serviceStatus, arrivedSent: model.arrivedSent, noShowReview: base.noShowReview?.status)
        ItemCard(title: strings.route(base), icon: .pin, badge: strings.status(.booking(base.serviceType, base.serviceStatus)),
                 lines: base.cancelled.map { [ItemLine(strings.cancelledLine($0), tone: .err)] } ?? [],
                 meta: strings.bookingWhen(base),
                 right: passenger && PassengerMoney.perSeat(base.priceBasis) ? strings.seatsTotal(base.quantity, unitMinor: base.unitPriceMinor)
                    : strings.money(base.totalMinor))
            .accessibilityIdentifier("elchi.driver.booking.header")
        detailsCard(booking)
        if let promo = booking.promo { promoBlock(promo) }
        photo
        if actions.inTransit {
            Note(strings.t("driver.booking.inTransitNote"), tone: .blue)
        }
        if actions.canArrive {
            ElchiButton(strings.t("driverBooking.action.arrive"), icon: .pin, loading: model.arriving) { Task { await model.arrive() } }
                .accessibilityIdentifier("elchi.driver.booking.arrive")
        } else if model.arrivedSent && DriverBookingActions.preService.contains(base.serviceStatus) {
            Note(strings.t("driver.booking.arrivedSent"), tone: .ok)
        }
        if let error = model.arriveError { Note(strings.errorText(error), tone: .err) }
        if passenger {
            DriverTaxiSection(model: model.taxi, booking: booking, actions: taxi, onTrip: onTrip)
            if taxi.cash {
                CashRecordSection(model: model.cash, booking: base, dueMinor: DriverBookingMoney.cashToCollect(booking))
            }
        }
        HStack(spacing: 8) {
            ElchiButton(strings.t("driverBooking.messages"), variant: .soft, size: .pair, icon: .chat, action: onChat)
                .accessibilityIdentifier("elchi.driver.booking.chat")
            ElchiButton(strings.t("driverBooking.tracking"), variant: .soft, size: .pair, icon: .pin, action: onTracking)
        }
        if actions.canAmend {
            ElchiButton(strings.t("driverBooking.amend"), variant: .neutral, action: onAmend)
                .accessibilityIdentifier("elchi.driver.booking.amend")
        }
        if actions.canRate || base.serviceStatus == "completed" { rating(actions) }
        ElchiButton(strings.t("support.complain"), variant: .neutral, icon: .head, action: onSupport)
        // Q19/Q75: while a no-show review is pending only an operator cancels - the button is not offered.
        if actions.canCancel && !taxi.noShowPending {
            ElchiButton(strings.t("bookingCancel.button"), variant: .dangerSoft) {
                model.clearNotice()
                confirmCancel = true
            }
            .disabled(model.running != nil)
            .accessibilityIdentifier("elchi.driver.booking.cancel")
        }
        reputationCard(booking)
        // Q146: the safety report and block live apart from the help button, one tap further.
        ElchiList {
            ListRow(icon: .shield, title: strings.t("safety.menuTitle"), description: strings.t("client.bookingDetail.safetyHint"), first: true,
                    action: onSafety)
        }
        .padding(.top, 8)
    }

    // MARK: The card

    private func detailsCard(_ booking: DriverBookingDTO) -> some View {
        let base = booking.base
        return ElchiCard {
            CardRow(strings.t("driverBooking.pickupPoint"),
                    strings.endName(base.pickup.point), first: true)
            CardRow(strings.t("driverBooking.dropoffPoint"),
                    strings.endName(base.dropoff.point))
            CardRow(strings.t("safety.clientTitle"), clientName(booking))
            if base.serviceType == .passenger {
                passengerRows(booking)
            } else {
                if let parcel = strings.parcelLine(base.parcelCategory, type: nil) {
                    CardRow(strings.t("listingDetail.parcel"), parcel)
                }
                receiverRow(booking)
            }
            CardRow(strings.t("driverBooking.fare"),
                    strings.t("driverBooking.fareCash", ("amount", strings.money(DriverBookingMoney.cashToCollect(booking)))),
                    detail: strings.t("bookingDetail.fareNote"))
            if let commission = DriverBookingMoney.commission(booking) {
                CardRow(strings.t("driver.booking.commission"),
                        strings.t("driver.booking.commissionValue", ("amount", strings.money(commission.minor)), ("percent", commission.percent)))
            }
        }
        .accessibilityIdentifier("elchi.driver.booking.card")
    }

    private func clientName(_ booking: DriverBookingDTO) -> String {
        let name = booking.client?.displayName.trimmingCharacters(in: .whitespaces) ?? ""
        return name.isEmpty ? strings.t("driver.booking.clientFallback") : name
    }

    /// Taksi: the people and the per-seat price, and the client's phone with "Qo'ng'iroq" once the passenger is aboard
    /// (Q44: phones open at the start of the service); before, the grey "Xizmat boshlanganda ochiladi".
    @ViewBuilder
    private func passengerRows(_ booking: DriverBookingDTO) -> some View {
        let base = booking.base
        CardRow(strings.t("orderForm.review.passengers"), strings.peopleLine(base.quantity, unitMinor: base.unitPriceMinor),
                detail: strings.t("orderForm.review.seatNegotiated"))
        if base.contact?.phonesVisible == true, let phone = booking.client?.contactPhone, !phone.isEmpty {
            CardRow(strings.t("driverBooking.phone"), UzPhone.display(phone), trailing: strings.t("client.bookingDetail.call")) {
                if let url = DriverReveal.dialURL(phone) { openURL(url) }
            }
        } else if !BookingActions.of(booking.status).terminal {
            CardRow(strings.t("driverBooking.phone"), strings.t("driverBooking.phoneHidden"), placeholder: true)
        }
    }

    /// The receiver's name and phone with "Qo'ng'iroq" once the trip departed (Q44/Q142); before, the grey note.
    @ViewBuilder
    private func receiverRow(_ booking: DriverBookingDTO) -> some View {
        if let receiver = ReceiverReveal.of(booking) {
            let text = [receiver.name, UzPhone.display(receiver.phone)].compactMap { $0 }.joined(separator: " · ")
            CardRow(strings.t("driverBooking.receiver"), text, trailing: strings.t("client.bookingDetail.call")) {
                if let url = DriverReveal.dialURL(receiver.phone) { openURL(url) }
            }
        } else if !BookingActions.of(booking.status).terminal {
            let from = ServerTime.parse(booking.base.contact?.visibleFrom).map(DepartureWindow.shortText)
            CardRow(strings.t("driverBooking.receiver"), strings.t("driverBooking.receiverHidden"), detail: from, placeholder: true)
        }
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

    @ViewBuilder
    private var photo: some View {
        if let url = model.photoURL {
            // A short-lived signed link (Q6): pulling to refresh fetches a new one.
            AsyncImage(url: url) { phase in
                switch phase {
                case .success(let image): image.resizable().scaledToFill()
                case .failure: Text(strings.t("app.photo.reload")).font(ElchiFont.caption).foregroundStyle(c.muted)
                default: ProgressView()
                }
            }
            .frame(maxWidth: .infinity).frame(height: 150)
            .background(c.field)
            .clipShape(RoundedRectangle(cornerRadius: 18))
            .accessibilityLabel(strings.t("driverBooking.parcelPhoto"))
        }
    }

    @ViewBuilder
    private func rating(_ actions: DriverBookingActions) -> some View {
        if let outcome = model.rating {
            switch outcome {
            case .sent: Note(strings.t("bookingRating.sent"), tone: .ok)
            case .already: Note(strings.t("error.RATING_ALREADY_EXISTS"), tone: .ok)
            case .notAllowed: Note(strings.t("error.RATING_NOT_ALLOWED"), tone: .gray)
            }
        } else if actions.canRate {
            ElchiButton(strings.t("rating.rateClient"), action: onRate)
                .accessibilityIdentifier("elchi.driver.booking.rate")
            Text(strings.t("driver.booking.rateNote")).font(ElchiFont.caption).foregroundStyle(c.muted)
        }
    }

    /// "Mijoz: Aziza — Yangi · Hali baholanmagan · Bajarilgan bronlar: 2 ta" (never a made-up score).
    @ViewBuilder
    private func reputationCard(_ booking: DriverBookingDTO) -> some View {
        if let reputation = model.reputation {
            let line = ClientReputation.line(reputation)
            ElchiCard {
                CardTitle(strings.t("reputation.title"))
                CardRow("\(strings.t("safety.clientTitle")): \(clientName(booking))",
                        line.score.map { "★ \($0) · \(strings.t("reputation.count", ("count", line.ratingCount)))" }
                            ?? "\(strings.t("reputation.new")) · \(strings.t("reputation.notRated"))",
                        first: true,
                        detail: "\(strings.t("reputation.completedBookings")): \(strings.t("reputation.count", ("count", line.completed)))")
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
                SelectField(label: strings.t("bookingCancel.reasonLabel"), options: DriverCancelReason.allCases.map { ($0, strings.t($0.key)) },
                            selected: reason, placeholder: strings.t("blockReport.chooseReason")) { reason = $0 }
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
}
