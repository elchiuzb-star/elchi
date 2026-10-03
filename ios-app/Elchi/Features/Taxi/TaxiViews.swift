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
                ElchiCard(padding: EdgeInsets(top: 14, leading: 16, bottom: 16, trailing: 16), tint: .blue) {
                    Text(strings.t("proofCode.boarding_code")).font(ElchiFont.label).foregroundStyle(c.muted)
                    Text(CodeReissue.spaced(code.code)).font(.system(size: 34, weight: .bold, design: .monospaced)).foregroundStyle(c.text)
                        .kerning(2).padding(.vertical, 6)
                        .accessibilityLabel(code.code.map(String.init).joined(separator: " "))
                        .accessibilityIdentifier("elchi.booking.code")
                    Text(strings.t("proofHint.boarding")).font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
                }
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

    private var driver: Bool { model.side == "driver" }

    var body: some View {
        let state = CashState.of(cashStatus: booking.cashStatus, receipt: booking.cashReceipt, side: model.side)
        SectionTitle(strings.t("app.cash.title"), description: strings.t("app.cash.explainer"))
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
        switch state {
        case .unpaid:
            reportForm
        case .reportedByOther(let receipt):
            answer(receipt)
        case .acknowledged:
            Note(strings.t("app.cash.bothConfirmed"), tone: .ok)
        case .contested:
            Note(strings.t("app.cash.contested"), tone: .err)
        case .reportedByMe:
            EmptyView()
        }
        if let error = model.error, model.running == nil { Note(strings.cashErrorText(error), tone: .err) }
        if let notice = model.notice, model.error == nil { Note(strings.t(notice), tone: .ok) }
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

    @ViewBuilder
    private func answer(_ receipt: CashReceiptDTO) -> some View {
        if contesting {
            ElchiField(text: $comment, label: strings.t("listingOwner.commentLabel"),
                       hint: strings.t("app.cash.commentRequired"), multiline: true)
            HStack(spacing: 8) {
                ElchiButton(strings.t("app.cash.contest"), variant: .danger, size: .pair, loading: model.running == .contest) {
                    Task { if await model.contest(receipt, comment: comment) { contesting = false } }
                }
                .disabled(comment.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                ElchiButton(strings.t("common.cancel"), variant: .neutral, size: .pair) { contesting = false }
            }
        } else {
            HStack(spacing: 8) {
                ElchiButton(strings.t("app.cash.acknowledge"), size: .pair, loading: model.running == .acknowledge) {
                    Task { _ = await model.acknowledge(receipt) }
                }
                .accessibilityIdentifier("elchi.cash.acknowledge")
                ElchiButton(strings.t("app.cash.contest"), variant: .dangerSoft, size: .pair) {
                    model.clear()
                    contesting = true
                }
                .accessibilityIdentifier("elchi.cash.contest")
            }
            .disabled(model.running != nil)
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
