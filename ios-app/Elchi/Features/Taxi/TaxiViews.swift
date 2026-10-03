import SwiftUI

// MARK: - Chiqish kodi (client)

/// The boarding code, big and monospaced, with "tell it to the driver as you get in", "Yangi kod olish" and its limits
/// (Q75). A refused reissue says how long to wait, counting down.
struct BoardingCodeSection: View {
    let model: BoardingCodeModel
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var now = Date()

    var body: some View {
        if let code = model.code {
            VStack(alignment: .leading, spacing: 10) {
                // The design's dark code card: "Chiqish kodi", the six digits spaced wide, the hint under them.
                VStack(alignment: .leading, spacing: 6) {
                    Text(strings.t("proofCode.boarding_code")).font(ElchiFont.caption).foregroundStyle(Color(hex: 0x9FB6D6))
                    Text(CodeReissue.spaced(code.code)).font(.system(size: 30, weight: .semibold, design: .monospaced)).foregroundStyle(.white)
                        .kerning(9).padding(.vertical, 2)
                        .accessibilityLabel(code.code.map(String.init).joined(separator: " "))
                        .accessibilityIdentifier("elchi.booking.code")
                    Text(strings.t("proofHint.boarding")).font(ElchiFont.caption).foregroundStyle(Color(hex: 0xC9D6E8))
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(c.isDark ? Color(hex: 0x1B3563) : Color(hex: 0x0E2350), in: RoundedRectangle(cornerRadius: 22))
                let waitText = model.wait.flatMap { strings.reissueWaitText($0, now: now) }
                ElchiButton(strings.t("reissue.button"), variant: .neutral, icon: .refresh, loading: model.reissuing) {
                    Task { await model.reissue() }
                }
                .disabled(waitText != nil)
                .accessibilityIdentifier("elchi.booking.reissue")
                if let waitText {
                    Note(waitText, tone: .warn)
                } else if model.reissued {
                    Note(strings.t("reissue.done"), tone: .ok)
                }
                if let error = model.reissueError { Note(strings.errorText(error), tone: .err) }
                Text(strings.t("reissue.hint")).font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
            }
            .task(id: model.wait?.until) {
                // The wait sentence counts down; the button comes back by itself.
                while model.wait != nil, !Task.isCancelled {
                    now = Date()
                    try? await Task.sleep(for: .seconds(1))
                }
            }
        } else if let error = model.loadError {
            Note(strings.errorText(error), tone: .err)
        }
    }
}

// MARK: - Naqd to'lov qaydi (both sides)

/// "Naqd to'lov qaydi" (design 'cash-ack'): the agreed amount, then by state - record it (the amount prefilled with
/// what is due; a note when it differs), "the other side's confirmation is awaited", "Tasdiqlayman" / "Rozi emasman"
/// (with a comment for the operator), both confirmed, or contested.
struct CashRecordSection: View {
    let model: CashRecordModel
    let booking: ClientBookingDTO
    let dueMinor: Int
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var amountText = ""
    @State private var note = ""
    @State private var contesting = false
    @State private var comment = ""
    @Environment(BannerCenter.self) private var banners: BannerCenter?

    private var driver: Bool { model.side == "driver" }

    var body: some View {
        let state = CashState.of(cashStatus: booking.cashStatus, receipt: booking.cashReceipt, side: model.side)
        SectionTitle(strings.t("app.cash.title"), description: strings.t("app.cash.explainer"))
        if case .reportedByOther(let receipt) = state, !contesting {
            decideCard(receipt)
        } else {
            amountCard(state)
        }
        switch state {
        case .unpaid:
            reportForm
        case .reportedByOther(let receipt):
            if contesting { contestForm(receipt) }
        case .acknowledged:
            Note(strings.t("app.cash.bothConfirmed"), tone: .ok)
        case .contested:
            Note(strings.t("app.cash.contested"), tone: .err)
        case .reportedByMe:
            EmptyView()
        }
        if let error = model.error, model.running == nil { Note(strings.cashErrorText(error), tone: .err) }
        // The two answers have their toast and the state's own note; only the record's notice stays inline.
        if let notice = model.notice, model.error == nil, state != .acknowledged, state != .contested { Note(strings.t(notice), tone: .ok) }
    }

    /// The design's "Naqd to'lovni tasdiqlang" card: the amount the other side recorded, "Rozi emasman" / "Tasdiqlayman".
    private func decideCard(_ receipt: CashReceiptDTO) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(strings.t("client.booking.cashConfirmTitle")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
                Spacer(minLength: 8)
                Text(strings.money(receipt.amountMinor)).font(ElchiFont.poppins(15, .semibold)).foregroundStyle(c.text)
            }
            .accessibilityElement(children: .combine)
            Text(strings.t("app.cash.reportedByOther", ("amount", strings.money(receipt.amountMinor)), ("date", when(receipt))))
                .font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 8) {
                pill(strings.t("app.cash.contest"), bg: c.tone(.err).bg, fg: c.tone(.err).fg, loading: false) {
                    model.clear()
                    contesting = true
                }
                .accessibilityIdentifier("elchi.cash.contest")
                pill(strings.t("app.cash.acknowledge"), bg: c.brand, fg: c.onBrand, loading: model.running == .acknowledge) {
                    Task {
                        if await model.acknowledge(receipt), !driver { banners?.ok("client.booking.cashConfirmed") }
                    }
                }
                .accessibilityIdentifier("elchi.cash.acknowledge")
            }
            .disabled(model.running != nil)
        }
        .padding(EdgeInsets(top: 12, leading: 16, bottom: 12, trailing: 12))
        .background(c.card, in: RoundedRectangle(cornerRadius: 20))
        .shadow(color: c.shadow.opacity(0.7), radius: 12, y: 6)
    }

    private func pill(_ title: String, bg: Color, fg: Color, loading: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Group {
                if loading { ProgressView().tint(fg) } else { Text(title).font(ElchiFont.poppins(13, .semibold)).lineLimit(1) }
            }
            .foregroundStyle(fg)
            .frame(maxWidth: .infinity, minHeight: 44)
            .background(bg, in: Capsule())
            .contentShape(Capsule())
        }
        .buttonStyle(PressFade())
    }

    @ViewBuilder
    private func amountCard(_ state: CashState) -> some View {
        ElchiCard {
            CardRow(strings.t(booking.promo != nil ? "app.cash.dueLabel" : "app.cash.agreedLabel"), strings.money(dueMinor), first: true, strong: true)
            switch state {
            case .reportedByMe(let receipt):
                line(strings.t("app.cash.reportedByMe", ("amount", strings.money(receipt.amountMinor)), ("date", when(receipt))),
                     detail: strings.t("app.cash.awaitingOther"))
            case .reportedByOther(let receipt):
                line(strings.t("app.cash.reportedByOther", ("amount", strings.money(receipt.amountMinor)), ("date", when(receipt))), detail: nil)
            default:
                EmptyView()
            }
        }
        .accessibilityIdentifier("elchi.cash.card")
    }

    /// One sentence row under the amount ("Ikkinchi tomon qayd qildi: 300 000 so'm · 27.09, 14:20").
    private func line(_ text: String, detail: String?) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Rectangle().fill(c.field).frame(height: 1)
            VStack(alignment: .leading, spacing: 2) {
                Text(text).font(ElchiFont.poppins(14, .medium)).foregroundStyle(c.text).fixedSize(horizontal: false, vertical: true)
                if let detail { Text(detail).font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true) }
            }
            .padding(.vertical, 10)
            .accessibilityElement(children: .combine)
        }
    }

    private func when(_ receipt: CashReceiptDTO) -> String {
        ServerTime.parse(receipt.reportedAt).map(DepartureWindow.shortText) ?? ""
    }

    @ViewBuilder
    private var reportForm: some View {
        let amount = Money.minor(fromSoum: amountText)
        let needsNote = CashRecord.noteRequired(amountMinor: amount, dueMinor: dueMinor)
        ElchiField(text: $amountText, label: strings.t(driver ? "app.cash.receivedField" : "app.cash.givenField"), keyboard: .numberPad)
            .onChange(of: amountText) { _, typed in
                let formatted = Money.grouped(Money.soumDigits(typed))
                if amountText != formatted { amountText = formatted }
            }
            .onAppear { if amountText.isEmpty { amountText = Money.grouped(String(dueMinor / 100)) } }
        if needsNote {
            ElchiField(text: $note, label: strings.t("listingOwner.commentLabel"), hint: strings.t("app.cash.noteRequired"), multiline: true)
        }
        ElchiButton(strings.t(driver ? "app.cash.markReceived" : "app.cash.markGiven"), loading: model.running == .report) {
            Task {
                if await model.report(version: booking.version, amountMinor: amount, dueMinor: dueMinor, note: note) { note = "" }
            }
        }
        .disabled(!CashRecord.canReport(amountMinor: amount, dueMinor: dueMinor, note: note) || model.running != nil)
        .accessibilityIdentifier("elchi.cash.report")
    }

    /// "Rozi emasman" needs a comment (Q78: the operator reads it) - the design's one-tap contest is not followed.
    @ViewBuilder
    private func contestForm(_ receipt: CashReceiptDTO) -> some View {
        ElchiField(text: $comment, label: strings.t("listingOwner.commentLabel"),
                   hint: strings.t("app.cash.commentRequired"), multiline: true)
        HStack(spacing: 8) {
            ElchiButton(strings.t("app.cash.contest"), variant: .danger, size: .pair, loading: model.running == .contest) {
                Task {
                    if await model.contest(receipt, comment: comment) {
                        contesting = false
                        if !driver { banners?.ok("client.booking.cashContestSent") }
                    }
                }
            }
            .disabled(comment.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            .accessibilityIdentifier("elchi.cash.contestSend")
            ElchiButton(strings.t("common.cancel"), variant: .neutral, size: .pair) { contesting = false }
        }
    }
}

// MARK: - Manzilga yetib keldim (client)

/// "Manzilga yetib keldingizmi?" - the passenger's own completion is never one tap.
struct TaxiCompleteDialog: View {
    let working: Bool
    let onConfirm: () -> Void
    let onClose: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        DialogOverlay(dismissLabel: strings.t("confirmDialog.back"), onDismiss: { if !working { onClose() } }) {
            VStack(alignment: .leading, spacing: 4) {
                Text(strings.t("client.taxi.completeConfirmTitle")).font(ElchiFont.poppins(19, .medium, relativeTo: .title2)).foregroundStyle(c.text)
                    .accessibilityAddTraits(.isHeader)
                Text(strings.t("client.taxi.completeHint")).font(ElchiFont.secondary).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
            }
            ElchiButton(strings.t("client.taxi.complete"), loading: working, action: onConfirm)
                .accessibilityIdentifier("elchi.taxi.completeConfirm")
            ElchiButton(strings.t("confirmDialog.back"), variant: .neutral, size: .medium, action: onClose).disabled(working)
        }
    }
}

// MARK: - The driver's passenger block

/// What the driver does with a passenger before and during the ride: the boarding code from the passenger and
/// "Yo'lovchini chiqardim" (awaiting pickup), "Mijoz kelmadi" with when it opens (Q7), "Yo'lovchini tushirdim"
/// (aboard). Refusals are said in their own words; `TRIP_NOT_STARTED` links to the trip.
struct DriverTaxiSection: View {
    let model: DriverTaxiModel
    let booking: DriverBookingDTO
    let actions: DriverTaxiActions
    let onTrip: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var now = Date()
    @State private var noShowSheet = false

    var body: some View {
        @Bindable var model = model
        let version = booking.base.version
        if actions.canBoard {
            ElchiField(text: $model.code, label: strings.t("driverBooking.boardingCode"), placeholder: strings.t("driverBooking.codePlaceholder"),
                       hint: strings.t("driverBooking.codeFromPassenger"), keyboard: .numberPad, contentType: .oneTimeCode, monospaced: true)
                .onChange(of: model.code) { _, typed in
                    let digits = BoardRefusal.digits(typed)
                    if digits != typed { model.code = digits }
                }
                .accessibilityIdentifier("elchi.driver.taxi.code")
            ElchiButton(strings.t("driverBooking.action.board"), loading: model.running == .board) {
                Task { _ = await model.board(version: version) }
            }
            .disabled(!BoardRefusal.validCode(model.code) || model.running != nil)
            .accessibilityIdentifier("elchi.driver.taxi.board")
            if let error = model.error, model.failed == .board {
                Note(strings.boardErrorText(error), tone: .err)
                if BoardRefusal.of(error) == .tripNotStarted {
                    ElchiButton(strings.t("tripAction.start_boarding"), variant: .soft, size: .medium, icon: .route, action: onTrip)
                }
            }
        }
        if actions.showNoShow { noShow(version: version) }
        if actions.noShowPending { Note(strings.t("driver.noShow.pending"), tone: .warn) }
        if actions.canDropOff {
            ElchiButton(strings.t("driverBooking.action.dropOff"), loading: model.running == .dropOff) {
                Task { _ = await model.dropOff(version: version) }
            }
            .disabled(model.running != nil)
            .accessibilityIdentifier("elchi.driver.taxi.dropOff")
            if let error = model.error, model.failed == .dropOff { Note(strings.errorText(error), tone: .err) }
        }
        if let notice = model.notice, model.error == nil, notice != "driverBooking.statusUpdated" { Note(strings.t(notice), tone: .ok) }
    }

    @ViewBuilder
    private func noShow(version: Int) -> some View {
        let unlocks = model.unlocksAt(windowStart: ServerTime.parse(booking.base.pickup.windowStart))
        let open = unlocks.map { now >= $0 } ?? false
        ElchiButton(strings.t("driver.noShow.button"), variant: .neutral, icon: .clock) {
            model.clear()
            noShowSheet = true
        }
        .disabled(!open || model.running != nil)
        .accessibilityIdentifier("elchi.driver.taxi.noShow")
        Group {
            if let unlocks, !open {
                // When it opens: "Kutish vaqti hali tugamadi: 14:20 dan keyin urinib ko'ring."
                Text(strings.t("driver.noShow.reason.wait_time_not_elapsed", ("time", strings.clockOrDay(unlocks))))
            } else if unlocks == nil {
                Text(strings.t("driver.noShow.reason.arrival_not_recorded"))
            }
        }
        .font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
        Text(strings.t("driver.noShow.hint")).font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
        if let error = model.error, model.failed == .noShow, !noShowSheet { Note(strings.noShowErrorText(error, unlocksAt: unlocks), tone: .err) }
        Color.clear.frame(height: 0)
            .task(id: unlocks) {
                // The button opens by itself when the wait is over.
                while !Task.isCancelled {
                    now = Date()
                    try? await Task.sleep(for: .seconds(5))
                }
            }
            .sheet(isPresented: $noShowSheet) {
                NoShowSheet(model: model, version: version, unlocksAt: unlocks) { noShowSheet = false }
                    .environment(\.screenAccessory, nil)
            }
    }
}

/// "Mijoz bilan qanday bog'lanishga urindingiz?" - chat and / or call (at least one), then "Xabar yuborish". The
/// operator decides (Q7); a refusal stays on the sheet with its reason.
struct NoShowSheet: View {
    let model: DriverTaxiModel
    let version: Int
    let unlocksAt: Date?
    let onClose: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var channels: Set<NoShowChannel> = [.chat]

    var body: some View {
        let working = model.running == .noShow
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 4) {
                Text(strings.t("driver.noShow.button")).font(ElchiFont.poppins(20, .medium, relativeTo: .title2)).foregroundStyle(c.text)
                    .accessibilityAddTraits(.isHeader)
                Text(strings.t("driver.noShow.contactTitle")).font(ElchiFont.secondary).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
            }
            VStack(spacing: 8) {
                ForEach(NoShowChannel.allCases, id: \.self) { channel in
                    CheckRow(strings.t(channel.labelKey), on: Binding(get: { channels.contains(channel) }, set: { on in
                        if on { channels.insert(channel) } else { channels.remove(channel) }
                    }))
                    .accessibilityIdentifier("elchi.noShow.\(channel.rawValue)")
                }
            }
            if let error = model.error, model.failed == .noShow, !working {
                Note(strings.noShowErrorText(error, unlocksAt: unlocksAt), tone: .err)
            }
            HStack(spacing: 8) {
                ElchiButton(strings.t("driver.noShow.confirm"), variant: .danger, size: .pair, loading: working) {
                    Task { if await model.reportNoShow(version: version, channels: channels) { onClose() } }
                }
                .disabled(channels.isEmpty)
                .accessibilityIdentifier("elchi.noShow.send")
                ElchiButton(strings.t("confirmDialog.back"), variant: .neutral, size: .pair, action: onClose).disabled(working)
            }
            Text(strings.t("driver.noShow.hint")).font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
        }
        .padding(EdgeInsets(top: 28, leading: 20, bottom: 12, trailing: 20))
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(c.card.ignoresSafeArea())
        .presentationDetents([.height(440), .large])
        .presentationCornerRadius(ElchiShape.sheet)
        .presentationDragIndicator(.visible)
    }
}
