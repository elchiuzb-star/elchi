import SwiftUI
import UIKit

// MARK: - Shartlarni o'zgartirish

/// The current agreement, a new price with a reason (a parcel is one consignment: only the price changes), and the
/// history with the answers the client may give. A change takes effect only once the other side accepts it.
struct AmendmentView: View {
    let booking: BookingModel
    let onBack: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var priceText = ""
    @State private var digits = ""
    @State private var reason = ""
    @State private var now = Date()

    private var model: AmendmentsModel { booking.amendments }

    var body: some View {
        ScreenScaffold(title: strings.t("amendment.title"), backLabel: strings.t("common.back"), onBack: onBack, banner: banner) {
            if let dto = booking.booking.value {
                ElchiCard {
                    CardRow(strings.t("amendment.currentTerms"),
                            "\(dto.quantity) × \(strings.money(dto.unitPriceMinor)) = \(strings.money(dto.totalMinor))", first: true,
                            detail: strings.t("amendment.takesEffectNote"))
                }
                ForEach(model.warnings, id: \.code) { Note(strings.warningText($0), tone: .warn) }
                if BookingActions.of(dto.serviceStatus).canAmend {
                    form(dto)
                } else {
                    Note(strings.t("client.amendment.onlyConfirmed"), tone: .gray)
                }
                history(dto)
            } else {
                SkeletonCards(count: 2)
            }
        } footer: {
            EmptyView()
        }
        .refreshable { await load() }
        .task { await load() }
        .task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                now = Date()
            }
        }
        .onAppear { model.clear() }
    }

    private func load() async {
        async let amendments: Void = model.load()
        async let detail: Void = booking.load()
        _ = await (amendments, detail)
    }

    private var banner: (text: String, tone: Tone)? {
        model.notice.map { (strings.t($0), .ok) }
    }

    /// An open amendment blocks a new one (one at a time): the form says so instead of letting the server refuse.
    private func openOne(_ dto: ClientBookingDTO) -> AmendmentDTO? {
        model.items.value?.first { AmendmentActions.of($0, bookingStatus: dto.serviceStatus, now: now).open }
    }

    @ViewBuilder
    private func form(_ dto: ClientBookingDTO) -> some View {
        SectionTitle(strings.t("amendment.proposeTitle"))
        if openOne(dto) != nil {
            // One open amendment at a time: the form waits until it is answered, withdrawn or expired.
            Note(strings.t("client.amendment.openExists"), tone: .warn)
        } else {
            fields(dto)
        }
    }

    @ViewBuilder
    private func fields(_ dto: ClientBookingDTO) -> some View {
        let priceMinor = Money.minor(fromSoum: digits)
        let total = dto.quantity > 1 ? priceMinor * dto.quantity : priceMinor
        Note(strings.t("amendment.parcelQuantityFixed"), tone: .gray)
        ElchiField(text: $priceText, label: strings.t("amendment.priceLabel"), keyboard: .numberPad)
            .onChange(of: priceText) { _, typed in
                // Local text re-synced after every edit: SwiftUI's TextField ignores a binding that rewrites the input.
                digits = Money.soumDigits(typed)
                let formatted = Money.grouped(digits)
                if priceText != formatted { priceText = formatted }
            }
        ElchiField(text: $reason, label: strings.t("common.reason"), placeholder: strings.t("amendment.reasonPlaceholder"),
                   hint: strings.t("amendment.reasonHint"))
        if priceMinor > 0 {
            Text(strings.t("amendment.newTotal", ("total", strings.money(total)))).font(ElchiFont.poppins(14, .semibold)).foregroundStyle(c.text)
        }
        if let error = model.error, model.errorFor == "new", model.busy == nil { Note(strings.amendmentErrorText(error), tone: .err) }
        ElchiButton(strings.t("amendment.submit"), loading: model.busy == "new") {
            UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
            Task {
                if await model.propose(booking: dto, priceMinor: priceMinor, reason: reason) {
                    priceText = ""
                    digits = ""
                    reason = ""
                }
            }
        }
        .disabled(priceMinor <= 0 || reason.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                  || priceMinor == dto.unitPriceMinor || model.busy != nil)
    }

    @ViewBuilder
    private func history(_ dto: ClientBookingDTO) -> some View {
        SectionTitle(strings.t("client.amendment.history"))
        switch model.items {
        case .loading:
            SkeletonCards(count: 1)
        case .failed(let error):
            Note(strings.errorText(error), tone: .err)
        case .loaded(let items):
            if items.isEmpty {
                Text(strings.t("amendment.empty")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
            }
            ForEach(items, id: \.id) { amendment in
                let actions = AmendmentActions.of(amendment, bookingStatus: dto.serviceStatus, now: now)
                let busy = model.busy == amendment.id
                ItemCard(title: "\(amendment.newQuantity) × \(strings.money(amendment.newUnitPriceMinor))",
                         badge: strings.status(AmendmentActions.status(amendment, bookingStatus: dto.serviceStatus, now: now)),
                         sub: strings.t(amendment.authorSide == "client" ? "amendment.mine" : "amendment.theirs"),
                         lines: reasonLine(amendment), right: strings.money(amendment.newTotalMinor)) {
                    if let error = model.error, model.errorFor == amendment.id, model.busy == nil {
                        Note(strings.amendmentErrorText(error), tone: .err).padding(.top, 6)
                    }
                    if actions.canAccept {
                        HStack(spacing: 8) {
                            ElchiButton(strings.t("amendment.accept"), size: .pair, loading: busy) { Task { await model.accept(amendment) } }
                            ElchiButton(strings.t("proposal.reject"), variant: .dangerSoft, size: .pair) { Task { await model.reject(amendment) } }
                                .disabled(busy)
                        }
                        .padding(.top, 8)
                    } else if actions.canWithdraw {
                        ElchiButton(strings.t("amendment.withdraw"), variant: .neutral, size: .pair, loading: busy) { Task { await model.withdraw(amendment) } }
                            .padding(.top, 8)
                    }
                }
                .disabled(model.busy != nil && !busy)
            }
        }
    }

    /// The reason the author gave, and until when the other side may answer.
    private func reasonLine(_ amendment: AmendmentDTO) -> [ItemLine] {
        var lines: [ItemLine] = []
        if case .string(let text)? = amendment.changes["reason"], !text.isEmpty { lines.append(ItemLine(text)) }
        if amendment.status == "proposed", let expires = ServerTime.parse(amendment.expiresAt), let left = Countdown.left(until: expires, now: now),
           booking.booking.value?.serviceStatus == "confirmed" {
            lines.append(ItemLine(strings.t("client.amendment.expiresIn", ("time", strings.duration(hours: left.hours, minutes: left.minutes))), tone: .warn))
        }
        return lines
    }
}

// MARK: - Xavfsizlik haqida xabar berish

/// The safety menu (Q146: apart from "Yordam / shikoyat"): a report about this booking (the eight reason codes,
/// optional details - contacts are masked), and block, behind a confirmation. Unblocking is not offered here.
struct SafetyView: View {
    let booking: BookingModel
    let onBack: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var reason: ReportReasonCode = .offPlatformContact
    @State private var details = ""
    @State private var confirmBlock = false

    var body: some View {
        ScreenScaffold(title: strings.t("safety.menuTitle"), backLabel: strings.t("common.back"), onBack: onBack) {
            Note(strings.t("client.safety.note"), tone: .gray)
            SectionTitle(strings.t("safety.reportTitle"))
            if booking.report != nil {
                Note(strings.t("blockReport.sentNote"), tone: .ok, title: strings.t("blockReport.sentTitle"))
                ForEach(booking.warnings, id: \.code) { Note(strings.warningText($0), tone: .warn) }
                ElchiButton(strings.t("blockReport.reportAgain"), variant: .ghost, size: .medium) {
                    details = ""
                    booking.reportAgain()
                }
            } else {
                SelectField(label: strings.t("common.reason"),
                            options: ReportReasonCode.allCases.map { ($0, strings.tOrNil("blockReport.reason.\($0.rawValue)") ?? $0.rawValue) },
                            selected: reason, placeholder: strings.t("blockReport.chooseReason")) { reason = $0 }
                ElchiField(text: $details, label: strings.t("blockReport.detailsLabel"), hint: strings.t("blockReport.detailsHint"), multiline: true)
                if let error = booking.commandError, booking.failed == .report, booking.running == nil {
                    Note(strings.errorText(error), tone: .err)
                }
                ElchiButton(strings.t("common.send"), loading: booking.running == .report) {
                    Task { _ = await booking.sendReport(reason: reason, details: details) }
                }
                .disabled(booking.running != nil)
            }

            SectionTitle(strings.t("blockReport.blockTitle"), description: strings.t("blockReport.blockNote"))
            if booking.booking.value?.driver == nil {
                Note(strings.t("safety.counterpartyMissing"), tone: .gray)
            } else if booking.blocked {
                Note(strings.t("client.safety.blocked"), tone: .ok)
            } else {
                if let error = booking.commandError, booking.failed == .block, booking.running == nil {
                    Note(strings.errorText(error), tone: .err)
                }
                ElchiButton(strings.t("blockReport.block"), variant: .dangerSoft, icon: .block) { confirmBlock = true }
                    .disabled(booking.running != nil)
            }
        } footer: {
            EmptyView()
        }
        .overlay {
            if confirmBlock {
                DialogOverlay(dismissLabel: strings.t("confirmDialog.back"), onDismiss: { if booking.running != .block { confirmBlock = false } }) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(strings.t("client.safety.blockConfirmTitle")).font(ElchiFont.poppins(19, .medium, relativeTo: .title2)).foregroundStyle(c.text)
                            .accessibilityAddTraits(.isHeader)
                        Text(strings.t("blockReport.blockNote")).font(ElchiFont.secondary).foregroundStyle(c.muted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    ElchiButton(strings.t("client.safety.blockConfirm"), variant: .danger, loading: booking.running == .block) {
                        Task {
                            _ = await booking.block()
                            confirmBlock = false
                        }
                    }
                    ElchiButton(strings.t("confirmDialog.back"), variant: .neutral, size: .medium) { confirmBlock = false }
                        .disabled(booking.running == .block)
                }
            }
        }
    }
}

// MARK: - Haydovchini baholang

/// Five stars, an optional comment (moderated before it is published; contacts masked), "Bahoni yuborish" and
/// "Keyinroq". Done - or already rated, or no longer allowed - goes back to the booking, which then says so.
struct RatingView: View {
    let booking: BookingModel
    let onBack: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var stars = 0
    @State private var comment = ""

    var body: some View {
        ScreenScaffold(title: strings.t("rating.titleDriver"), backLabel: strings.t("common.back"), onBack: onBack) {
            Text(strings.t("bookingRating.prompt")).font(ElchiFont.poppins(18, .medium, relativeTo: .title3)).foregroundStyle(c.text)
                .multilineTextAlignment(.center).frame(maxWidth: .infinity).padding(.top, 12)
                .accessibilityAddTraits(.isHeader)
            StarsInput(value: $stars) { strings.t("bookingRating.starsAria", ("value", $0)) }
            ElchiField(text: $comment, label: strings.t("bookingRating.commentLabel"), multiline: true)
            Text(strings.t("bookingRating.moderationNote")).font(ElchiFont.caption).foregroundStyle(c.muted)
                .fixedSize(horizontal: false, vertical: true)
            if let error = booking.commandError, booking.failed == .rate, booking.running == nil {
                Note(strings.errorText(error), tone: .err)
            }
        } footer: {
            ElchiButton(strings.t("bookingRating.submit"), loading: booking.running == .rate) {
                Task { if await booking.rate(stars: stars, comment: comment) { onBack() } }
            }
            .disabled(stars == 0 || booking.running != nil)
            ElchiButton(strings.t("bookingRating.later"), variant: .ghost, size: .medium, action: onBack)
        }
    }
}
