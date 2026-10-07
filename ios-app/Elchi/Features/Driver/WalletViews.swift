import SwiftUI
import UIKit

/// "Komissiya balansi" (design 'driver-income'): the available balance with what it is (and is not - the fare), the
/// four tiles, the 7-day captured-commission chart, the top-up request (no invented bank details: the operator gives
/// them in Help), the requests and the transactions.
struct WalletView: View {
    let model: WalletModel
    let onBack: () -> Void
    let onHelp: () -> Void
    /// The session phone: "To'lov maqsadi: 90 777 11 22" (DESIGN09 2.7).
    var phone: String?
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(BannerCenter.self) private var banners: BannerCenter?
    @State private var amountShown = ""
    /// DESIGN09 2.14: "{amount} so'rov yuborilsinmi?" before the request reaches finance.
    @State private var confirming = false
    /// DESIGN09 2.4: the bar tapped (its value shown above it).
    @State private var pickedBar: Date?

    var body: some View {
        ScreenScaffold(title: strings.t("income.title"), backLabel: strings.t("common.back"), onBack: onBack) {
            switch model.wallet {
            case .loading:
                SkeletonCards(count: 2)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err)
                ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.load() } }
            case .loaded(let wallet):
                balance(wallet)
            }
            if let tiles = model.tiles { tileGrid(tiles) }
            chart
            topupForm
            requests
            transactions
        } footer: {
            EmptyView()
        }
        .refreshable { await model.load() }
        .task { await model.load() }
        .overlay {
            if confirming, let body = model.body { confirmDialog(body) }
        }
    }

    private func confirmDialog(_ body: TopupCreate) -> some View {
        DialogOverlay(dismissLabel: strings.t("confirmDialog.back"), onDismiss: { confirming = false }) {
            Heading(strings.t("driver.v3wallet.confirmTitle", ("amount", strings.money(body.amountMinor))),
                    subtitle: strings.t("driver.v3wallet.confirmText"))
            HStack(spacing: 10) {
                ElchiButton(strings.t("driver.v3wallet.confirmYes"), size: .pair) {
                    confirming = false
                    Task { await model.submit() }
                }
                .accessibilityIdentifier("elchi.wallet.confirm")
                ElchiButton(strings.t("confirmDialog.back"), variant: .neutral, size: .pair) { confirming = false }
            }
        }
        .accessibilityIdentifier("elchi.wallet.confirmDialog")
    }

    private func balance(_ wallet: WalletDTO) -> some View {
        ElchiCard(padding: EdgeInsets(top: 16, leading: 16, bottom: 16, trailing: 16)) {
            VStack(alignment: .leading, spacing: 4) {
                Text(strings.t("income.available")).font(ElchiFont.poppins(13, .semibold)).foregroundStyle(c.muted)
                Text(strings.money(wallet.availableMinor)).font(ElchiFont.poppins(30, .bold)).foregroundStyle(c.text)
                    .accessibilityIdentifier("elchi.wallet.available")
                Text(strings.t("income.balanceNote")).font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
            }
            .accessibilityElement(children: .combine)
        }
    }

    private func tileGrid(_ tiles: WalletLogic.Tiles) -> some View {
        VStack(spacing: 8) {
            StatTiles([(strings.t("income.held"), strings.money(tiles.heldMinor)),
                       (strings.t("income.reversed"), strings.money(tiles.reversedMinor))])
            StatTiles([(strings.t("income.topups"), strings.money(tiles.topupsMinor)),
                       (strings.t("income.pendingTopups"), strings.money(tiles.pendingTopupsMinor))])
        }
        .accessibilityIdentifier("elchi.wallet.tiles")
    }

    // MARK: Chart

    @ViewBuilder
    private var chart: some View {
        let bars = model.chart
        let top = max(bars.map(\.minor).max() ?? 0, 1)
        ElchiCard(padding: EdgeInsets(top: 14, leading: 16, bottom: 14, trailing: 16)) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 10) {
                    Text(strings.t("income.capturedTitle")).font(ElchiFont.poppins(15, .semibold)).foregroundStyle(c.text)
                        .lineLimit(2).minimumScaleFactor(0.85)
                    Spacer(minLength: 0)
                    Segmented(WalletLogic.Period.allCases.map { ($0, strings.t($0.labelKey)) }, selected: model.period) {
                        model.period = $0
                        pickedBar = nil
                    }
                    .frame(width: 150)
                    .accessibilityIdentifier("elchi.wallet.period")
                }
                if WalletLogic.chartIsEmpty(bars) {
                    Text(strings.t("income.chartEmpty")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
                        .frame(maxWidth: .infinity, minHeight: 80)
                } else {
                    HStack(alignment: .bottom, spacing: 8) {
                        ForEach(bars, id: \.day) { bar in
                            let picked = pickedBar == bar.day
                            VStack(spacing: 4) {
                                if picked {
                                    Text(strings.money(bar.minor)).font(ElchiFont.poppins(9, .semibold)).foregroundStyle(c.text)
                                        .lineLimit(1).minimumScaleFactor(0.5)
                                }
                                RoundedRectangle(cornerRadius: 6).fill(bar.minor > 0 ? (picked ? c.navy : c.brand) : c.field)
                                    .frame(height: max(4, CGFloat(bar.minor) / CGFloat(top) * 90))
                                Text(barLabel(bar.day)).font(ElchiFont.poppins(9)).foregroundStyle(c.muted).lineLimit(1)
                                    .minimumScaleFactor(0.7)
                            }
                            .frame(maxWidth: .infinity)
                            .contentShape(Rectangle())
                            .onTapGesture { pickedBar = picked ? nil : bar.day }
                            .accessibilityElement(children: .ignore)
                            .accessibilityLabel("\(barLabel(bar.day)): \(strings.money(bar.minor))")
                        }
                    }
                    .frame(height: 126, alignment: .bottom)
                }
                Text(strings.t("income.chartNote")).font(ElchiFont.poppins(11)).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
            }
        }
        .accessibilityIdentifier("elchi.wallet.chart")
    }

    /// dd MMM for the rolling 7 days (not weekdays), the short month name for the 6 months.
    private func barLabel(_ day: Date) -> String {
        guard model.period == .monthly else { return strings.dayMonth(day) }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: strings.locale == .ru ? "ru_RU" : "uz_Latn_UZ")
        formatter.timeZone = DepartureWindow.timeZone
        formatter.dateFormat = "LLL"
        return formatter.string(from: day)
    }

    // MARK: Top-up

    @ViewBuilder
    private var topupForm: some View {
        @Bindable var model = model
        SectionTitle(strings.t("income.topupTitle"), description: strings.t("income.topupNote"))
        Note(strings.t("driver.wallet.requisitesNote"), tone: .blue)
        if let purpose = WalletLogic.paymentPurposePhone(phone) { paymentPurpose(purpose) }
        ElchiButton(strings.t("driverProfile.action.support"), variant: .outline, size: .medium, icon: .head, action: onHelp)
        ElchiField(text: $amountShown, label: strings.t("income.amountLabel"), placeholder: "100 000",
                   hint: WalletLogic.largeAmount(model.amountText) ? strings.t("driver.v3wallet.largeAmount") : nil,
                   error: model.attempted && model.body == nil ? strings.t("driver.wallet.amountInvalid") : nil, keyboard: .numberPad,
                   suffix: strings.t("common.soum"))
            .onChange(of: amountShown) { _, typed in
                let digits = Money.soumDigits(typed)
                model.amountText = digits
                let formatted = Money.grouped(digits)
                if amountShown != formatted { amountShown = formatted }
            }
            .onChange(of: model.amountText) { _, digits in if digits.isEmpty && !amountShown.isEmpty { amountShown = "" } }
            .accessibilityIdentifier("elchi.wallet.amount")
        presets
        VStack(alignment: .leading, spacing: 6) {
            Text(strings.t("driver.wallet.methodLabel")).font(ElchiFont.label).foregroundStyle(c.text)
            Segmented(WalletLogic.methods.map { ($0, strings.t("driver.wallet.method.\($0)")) }, selected: model.method) { model.method = $0 }
        }
        ElchiField(text: $model.payerReference, label: strings.t("driver.wallet.payerReference"))
        ElchiField(text: $model.note, label: strings.t("driver.wallet.noteLabel"), multiline: true)
        if let error = model.sendError { Note(strings.errorText(error), tone: .err) }
        ElchiButton(strings.t("income.topupSend"), loading: model.sending) {
            UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
            confirming = true
        }
        // DESIGN09 2.14: grey until the amount is valid (as on Android), then a confirmation.
        .disabled(model.body == nil || model.sending)
        .accessibilityIdentifier("elchi.wallet.submit")
    }

    /// "To'lov maqsadi: 90 777 11 22" with a copy action (the driver's own phone - real, not invented requisites).
    private func paymentPurpose(_ purpose: String) -> some View {
        HStack(spacing: 10) {
            Text(strings.t("driver.v3wallet.paymentPurpose", ("phone", purpose))).font(ElchiFont.poppins(13.5, .medium)).foregroundStyle(c.text)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
            Button {
                UIPasteboard.general.string = purpose
                banners?.show(.key("promoScreen.copied"), tone: .ok, hideAfter: .seconds(2))
            } label: {
                Text(strings.t("promoScreen.copy")).font(ElchiFont.poppins(13, .semibold)).foregroundStyle(c.accentText)
                    .padding(.horizontal, 12).frame(minHeight: 36)
                    .background(c.field, in: Capsule())
            }
            .buttonStyle(PressFade())
        }
        .accessibilityIdentifier("elchi.wallet.purpose")
    }

    /// 50 000 / 100 000 / 200 000 / 500 000 - the chosen one navy.
    private var presets: some View {
        HStack(spacing: 8) {
            ForEach(WalletLogic.presetsSoum, id: \.self) { soum in
                let digits = String(soum)
                let selected = model.amountText == digits
                Button {
                    model.amountText = digits
                    amountShown = Money.grouped(digits)
                } label: {
                    Text(Money.grouped(digits)).font(ElchiFont.poppins(12.5, .medium)).lineLimit(1).minimumScaleFactor(0.8)
                        .foregroundStyle(selected ? Color.white : c.text)
                        .frame(maxWidth: .infinity, minHeight: 38)
                        .background(selected ? (c.isDark ? Color(hex: 0x1B3563) : c.navy) : c.card, in: Capsule())
                        .overlay { Capsule().strokeBorder(selected ? Color.clear : c.line, lineWidth: 1) }
                }
                .buttonStyle(PressFade())
                .accessibilityLabel(strings.money(soum * 100))
                .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
            }
        }
        .accessibilityIdentifier("elchi.wallet.presets")
    }

    // MARK: Lists

    @ViewBuilder
    private var requests: some View {
        SectionTitle(strings.t("income.requestsTitle"))
        switch model.topups {
        case .loading:
            SkeletonCards(count: 1)
        case .failed(let error):
            Note(strings.errorText(error), tone: .err)
        case .loaded(let list) where list.isEmpty:
            EmptyState(icon: .wallet, title: strings.t("income.requestsEmpty"), description: strings.t("income.requestsEmptyHint"))
        case .loaded(let list):
            ForEach(list, id: \.id) { topup in
                ItemCard(title: strings.money(topup.amountMinor), badge: strings.status(WalletLogic.status(topup.status)),
                         sub: [strings.dateOnly(topup.createdAt), strings.t("driver.wallet.method.\(topup.method)")].compactMap { $0 }
                            .joined(separator: " · "))
                    .accessibilityIdentifier("elchi.wallet.topup.\(topup.id)")
            }
        }
    }

    @ViewBuilder
    private var transactions: some View {
        SectionTitle(strings.t("driver.wallet.transactionsTitle"))
        if let error = model.linesError, model.lines.isEmpty {
            Note(strings.errorText(error), tone: .err)
        } else if !model.linesLoaded {
            SkeletonCards(count: 1)
        } else if model.lines.isEmpty {
            Text(strings.t("driver.wallet.transactionsEmpty")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
        } else {
            ElchiCard {
                ForEach(Array(model.lines.enumerated()), id: \.element.transactionId) { index, line in
                    CardRow(strings.t(WalletLogic.kindKey(line)),
                            "\(WalletLogic.sign(line))\(strings.money(line.amountMinor))", first: index == 0,
                            detail: [ServerTime.parse(line.occurredAt).map(DepartureWindow.shortText),
                                     strings.t("driver.wallet.balanceAfter", ("amount", strings.money(line.balanceAfterMinor)))]
                                .compactMap { $0 }.joined(separator: " · "),
                            valueTone: line.direction == "credit" ? .ok : .err)
                }
            }
            if model.nextCursor != nil {
                ElchiButton(strings.t("blockReport.loadMore"), variant: .ghost, size: .medium, loading: model.loadingMore) {
                    Task { await model.loadMore() }
                }
            }
        }
    }
}
