import SwiftUI
import UIKit

// MARK: - Shartlarni o'zgartirish

/// The current agreement, a new price with a reason (a parcel is one consignment: only the price changes), and the
/// history with the answers the client may give. A change takes effect only once the other side accepts it.
struct AmendmentView<Host: BookingScreenHost>: View {
    let booking: Host
    let onBack: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var priceText = ""
    @State private var digits = ""
    @State private var reason = ""
    @State private var now = Date()
    /// Set by a tap on "Taklif yuborish" with something missing (tap to validate, design).
    @State private var problem: AmendmentForm.Problem?

    private var model: AmendmentsModel { booking.amendments }

    var body: some View {
        ScreenScaffold(title: strings.t("amendment.title"), backLabel: strings.t("common.back"), onBack: onBack, banner: banner) {
            if let dto = booking.bookingBase {
                ElchiCard {
                    CardRow(strings.t("amendment.currentTerms"),
                            "\(dto.quantity) × \(strings.money(dto.unitPriceMinor)) = \(strings.money(dto.totalMinor))", first: true,
                            detail: strings.t("amendment.takesEffectNote"))
                }
                ForEach(model.warnings, id: \.code) { Note(strings.warningText($0), tone: .warn) }
                if AmendmentActions.amendable(dto.serviceStatus, side: booking.side) {
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
        guard let notice = model.notice else { return nil }
        return (strings.t(notice, ("price", model.noticePrice.map(strings.money) ?? "")), .ok)
    }

    /// An open amendment blocks a new one (one at a time): the form says so instead of letting the server refuse.
    private func openOne(_ dto: ClientBookingDTO) -> AmendmentDTO? {
        model.items.value?.first { AmendmentActions.of($0, bookingStatus: dto.serviceStatus, now: now, side: booking.side).open }
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
        let passenger = dto.serviceType == .passenger
        // Q145: the quantity stays as agreed after the booking (D9) - only the price changes, by agreement.
        Note(passenger ? strings.t("amendment.seatsFixed", ("count", dto.quantity)) : strings.t("amendment.parcelQuantityFixed"), tone: .gray)
        // Taksi: "Bir kishi uchun narx (so'm)" (the per-seat price), Pochta "Narx (so'm)"; the current price as the example.
        ElchiField(text: $priceText, label: strings.t(PassengerMoney.perSeat(dto.priceBasis) ? "routeSummary.pricePerPerson" : "amendment.priceLabel"),
                   placeholder: Money.grouped(String(dto.unitPriceMinor / 100)),
                   error: problem == .priceMissing || problem == .noChange ? problem.map { strings.t($0.key) } : nil,
                   keyboard: .numberPad, suffix: strings.t("common.soum"))
            .onChange(of: priceText) { _, typed in
                // Local text re-synced after every edit: SwiftUI's TextField ignores a binding that rewrites the input.
                digits = String(Money.soumDigits(typed).prefix(AmendmentForm.maxPriceDigits))
                let formatted = Money.grouped(digits)
                if priceText != formatted { priceText = formatted }
                if problem == .priceMissing || problem == .noChange { problem = nil }
            }
        ElchiField(text: $reason, label: strings.t("common.reason"),
                   placeholder: strings.t(passenger ? "amendment.reasonPlaceholder" : "client.booking.amendReasonPlaceholder"),
                   hint: strings.t("amendment.reasonHint"), error: problem == .reasonShort ? strings.t(AmendmentForm.Problem.reasonShort.key) : nil)
            .onChange(of: reason) { _, typed in
                if typed.count > AmendmentForm.maxReason { reason = String(typed.prefix(AmendmentForm.maxReason)) }
                if problem == .reasonShort { problem = nil }
            }
        // "Yangi jami: —" until a price is typed (design).
        Text(strings.t("amendment.newTotal", ("total", priceMinor > 0 ? strings.money(total) : "—"))).font(ElchiFont.poppins(14, .semibold))
            .foregroundStyle(c.text)
        if let error = model.error, model.errorFor == "new", model.busy == nil { Note(strings.amendmentErrorText(error), tone: .err) }
        ElchiButton(strings.t("amendment.submit"), loading: model.busy == "new") {
            UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
            if let found = AmendmentForm.validate(priceMinor: priceMinor, currentUnitMinor: dto.unitPriceMinor, reason: reason) {
                problem = found
                return
            }
            problem = nil
            Task {
                if await model.propose(booking: dto, priceMinor: priceMinor, reason: reason) {
                    priceText = ""
                    digits = ""
                    reason = ""
                }
            }
        }
        .disabled(model.busy != nil)
        .accessibilityIdentifier("elchi.amend.submit")
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
                let actions = AmendmentActions.of(amendment, bookingStatus: dto.serviceStatus, now: now, side: booking.side)
                let busy = model.busy == amendment.id
                ItemCard(title: "\(amendment.newQuantity) × \(strings.money(amendment.newUnitPriceMinor))",
                         badge: strings.status(AmendmentActions.status(amendment, bookingStatus: dto.serviceStatus, now: now, side: booking.side)),
                         sub: strings.t(amendment.authorSide == booking.side ? "amendment.mine" : "amendment.theirs"),
                         lines: reasonLine(amendment), right: strings.money(amendment.newTotalMinor)) {
                    if let error = model.error, model.errorFor == amendment.id, model.busy == nil {
                        Note(strings.amendmentErrorText(error), tone: .err).padding(.top, 6)
                    }
                    if actions.canAccept {
                        HStack(spacing: 8) {
                            ElchiButton(strings.t("amendment.accept"), size: .pair, loading: busy) { Task { await model.accept(amendment) } }
                                .accessibilityIdentifier("elchi.amend.accept")
                            ElchiButton(strings.t("proposal.reject"), variant: .dangerSoft, size: .pair) { Task { await model.reject(amendment) } }
                                .disabled(busy)
                        }
                        .padding(.top, 8)
                    } else if actions.canWithdraw {
                        ElchiButton(strings.t("client.booking.amendWithdraw"), variant: .neutral, size: .pair, loading: busy) { Task { await model.withdraw(amendment) } }
                            .accessibilityIdentifier("elchi.amend.withdraw")
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
           AmendmentActions.amendable(booking.bookingBase?.serviceStatus ?? "", side: booking.side) {
            lines.append(ItemLine(strings.t("client.amendment.expiresIn", ("time", strings.duration(hours: left.hours, minutes: left.minutes))), tone: .warn))
        }
        return lines
    }
}

// MARK: - Xavfsizlik

/// "Xavfsizlik" (Q146: apart from "Yordam / shikoyat"): the explanation note, a report about this booking - the
/// eight server reason codes as the design's radio list, the first chosen - with optional details (contacts are
/// masked), and the red "Bloklash" behind a confirmation ("Jasur bloklansinmi?" / "Bu bron davom etadi."). Unblock is
/// not offered (BLOCKED: the server's DELETE is not usable yet).
struct SafetyView<Host: SafetyHost>: View {
    let booking: Host
    var texts = BookingSideTexts.client
    let onBack: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(BannerCenter.self) private var banners: BannerCenter?
    @State private var reason: ReportReasonCode = ReportReasonCode.allCases.first ?? .other
    @State private var details = ""
    @State private var confirmBlock = false

    var body: some View {
        ScreenScaffold(title: strings.t("safety.section"), backLabel: strings.t("common.back"), onBack: onBack) {
            Note(strings.t(texts.safetyNote), tone: .gray)
            SectionTitle(strings.t("safety.reportTitle"))
            if booking.report != nil {
                Note(strings.t(texts == .client ? "client.booking.reportSentShort" : "blockReport.sentNote"), tone: .ok,
                     title: strings.t("blockReport.sentTitle"))
                ForEach(booking.warnings, id: \.code) { Note(strings.warningText($0), tone: .warn) }
                ElchiButton(strings.t("blockReport.reportAgain"), variant: .ghost, size: .medium) {
                    details = ""
                    booking.reportAgain()
                }
            } else {
                VStack(spacing: 8) {
                    ForEach(ReportReasonCode.allCases, id: \.self) { code in
                        RadioRow(title: strings.tOrNil("blockReport.reason.\(code.rawValue)") ?? code.rawValue, selected: reason == code) { reason = code }
                            .accessibilityIdentifier("elchi.safety.reason.\(code.rawValue)")
                    }
                }
                .accessibilityElement(children: .contain)
                .accessibilityLabel(strings.t("common.reason"))
                ElchiField(text: $details, label: strings.t("blockReport.detailsLabel"), hint: strings.t("blockReport.detailsHint"), multiline: true)
                    .onChange(of: details) { _, typed in if typed.count > 300 { details = String(typed.prefix(300)) } }
                if let error = booking.commandError, booking.failed == .report, booking.running == nil {
                    Note(strings.errorText(error), tone: .err)
                }
                ElchiButton(strings.t("common.send"), loading: booking.running == .report) {
                    Task { if await booking.sendReport(reason: reason, details: details) { banners?.ok("blockReport.sentTitle") } }
                }
                .disabled(booking.running != nil)
                .accessibilityIdentifier("elchi.safety.send")
            }

            if !booking.counterpartyKnown {
                Note(strings.t("safety.counterpartyMissing"), tone: .gray)
            } else if booking.blocked {
                Note(strings.t(texts.blockedNote), tone: .ok)
            } else {
                if let error = booking.commandError, booking.failed == .block, booking.running == nil {
                    Note(strings.errorText(error), tone: .err)
                }
                ElchiButton(strings.t("blockReport.block"), variant: .dangerSoft, icon: .block) { confirmBlock = true }
                    .disabled(booking.running != nil)
                    .padding(.top, 8)
                    .accessibilityIdentifier("elchi.safety.block")
            }
        } footer: {
            EmptyView()
        }
        .overlay {
            if confirmBlock {
                DialogOverlay(dismissLabel: strings.t("confirmDialog.back"), onDismiss: { if booking.running != .block { confirmBlock = false } }) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(blockTitle).font(ElchiFont.poppins(19, .medium, relativeTo: .title2)).foregroundStyle(c.text)
                            .accessibilityAddTraits(.isHeader)
                        Text(strings.t(booking.counterpartyName != nil ? "client.booking.blockKeepsBooking" : "blockReport.blockNote"))
                            .font(ElchiFont.secondary).foregroundStyle(c.muted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    ElchiButton(strings.t("client.safety.blockConfirm"), variant: .danger, loading: booking.running == .block) {
                        Task {
                            if await booking.block(), let name = booking.counterpartyName {
                                banners?.show(.text(strings.t("client.booking.blockedName", ("name", name))), tone: .ok)
                            }
                            confirmBlock = false
                        }
                    }
                    ElchiButton(strings.t("confirmDialog.back"), variant: .neutral, size: .medium) { confirmBlock = false }
                        .disabled(booking.running == .block)
                        .accessibilityIdentifier("elchi.safety.blockBack")
                }
            }
        }
    }

    /// "Jasur bloklansinmi?" with the first name when the booking names the driver; the side's generic title else.
    private var blockTitle: String {
        if let name = booking.counterpartyName { return strings.t("client.booking.blockConfirmName", ("name", name)) }
        return strings.t(texts.blockConfirmTitle)
    }
}

/// One choice of the design's radio list: a card with a ring (azure and thick when chosen) and the label.
struct RadioRow: View {
    let title: String
    let selected: Bool
    let action: () -> Void
    @Environment(\.elchi) private var c

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Circle().strokeBorder(selected ? c.brand : c.outline, lineWidth: selected ? 6 : 2).frame(width: 20, height: 20)
                Text(title).font(ElchiFont.poppins(14, .medium)).foregroundStyle(c.text).multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 14).padding(.vertical, 12)
            .frame(minHeight: 48)
            .background(selected ? (c.isDark ? c.soft : Color(hex: 0xF0F8FF)) : c.card, in: RoundedRectangle(cornerRadius: 16))
            .overlay { RoundedRectangle(cornerRadius: 16).strokeBorder(selected ? c.brand : c.line, lineWidth: selected ? 2 : 1) }
            .contentShape(RoundedRectangle(cornerRadius: 16))
        }
        .buttonStyle(PressFade())
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
    }
}

// MARK: - Haydovchini baholang

/// Five stars with the word under them ("Yulduzni bosing", then Yomon ... A'lo), an optional comment (moderated before
/// it is published; contacts masked), "Bahoni yuborish" - grey until a star is chosen but tappable ("Avval 1 dan 5
/// gacha yulduz tanlang") - and "Keyinroq". Done - or already rated, or no longer allowed - goes back to the booking,
/// which then says so. Stars tapped on the detail's card come chosen.
struct RatingView<Host: RatingHost>: View {
    let booking: Host
    var texts = BookingSideTexts.client
    let onBack: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(BannerCenter.self) private var banners: BannerCenter?
    @State private var stars = 0
    @State private var comment = ""

    var body: some View {
        let client = texts == .client
        ScreenScaffold(title: strings.t(texts.ratingTitle), backLabel: strings.t("common.back"), onBack: onBack) {
            Text(strings.t("bookingRating.prompt")).font(ElchiFont.poppins(18, .medium, relativeTo: .title3)).foregroundStyle(c.text)
                .multilineTextAlignment(.center).frame(maxWidth: .infinity).padding(.top, 12)
                .accessibilityAddTraits(.isHeader)
            StarsInput(value: $stars) { strings.t("bookingRating.starsAria", ("value", $0)) }
            Text(strings.t(BookingDetailRules.starLabelKey(stars))).font(ElchiFont.poppins(14, .semibold))
                .foregroundStyle(stars > 0 ? c.accentText : c.placeholder)
                .frame(maxWidth: .infinity)
                .accessibilityIdentifier("elchi.rating.label")
            ElchiField(text: $comment, label: strings.t(client ? "client.booking.rateCommentOptional" : "bookingRating.commentLabel"),
                       placeholder: client ? strings.t("client.booking.rateCommentPlaceholder") : nil, multiline: true)
                .onChange(of: comment) { _, typed in if typed.count > 300 { comment = String(typed.prefix(300)) } }
            Text(strings.t("bookingRating.moderationNote")).font(ElchiFont.caption).foregroundStyle(c.muted)
                .fixedSize(horizontal: false, vertical: true)
            if let error = booking.commandError, booking.failed == .rate, booking.running == nil {
                Note(strings.errorText(error), tone: .err)
            }
        } footer: {
            ElchiButton(strings.t("bookingRating.submit"), loading: booking.running == .rate, dimmed: stars == 0) {
                guard stars > 0 else {
                    banners?.show(.key("client.booking.ratePickStars"), tone: .warn, hideAfter: .seconds(3))
                    return
                }
                Task {
                    if await booking.rate(stars: stars, comment: comment) {
                        if client { banners?.ok("client.booking.rateThanks") }
                        onBack()
                    }
                }
            }
            .disabled(booking.running != nil)
            .accessibilityIdentifier("elchi.rating.submit")
            ElchiButton(strings.t("bookingRating.later"), variant: .ghost, size: .medium, action: onBack)
        }
        .onAppear { if stars == 0 { stars = booking.initialStars } }
    }
}
