import SwiftUI
import UIKit

/// "Komissiya balansi" (design 'driver-income'): the available balance with what it is (and is not - the fare), the
/// four tiles, the 7-day captured-commission chart, the top-up request (no invented bank details: the operator gives
/// them in Help), the requests and the transactions.
struct WalletView: View {
    let model: WalletModel
    let onBack: () -> Void
    let onHelp: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var amountShown = ""

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
                HStack {
                    Text(strings.t("income.capturedTitle")).font(ElchiFont.poppins(15, .semibold)).foregroundStyle(c.text)
                    Spacer()
                    Text(strings.t("income.period.daily")).font(ElchiFont.caption).foregroundStyle(c.muted)
                }
                if WalletLogic.chartIsEmpty(bars) {
                    Text(strings.t("income.chartEmpty")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
                        .frame(maxWidth: .infinity, minHeight: 80)
                } else {
                    HStack(alignment: .bottom, spacing: 8) {
                        ForEach(bars, id: \.day) { bar in
                            VStack(spacing: 4) {
                                RoundedRectangle(cornerRadius: 6).fill(bar.minor > 0 ? c.brand : c.field)
                                    .frame(height: max(4, CGFloat(bar.minor) / CGFloat(top) * 90))
                                Text(strings.dayMonth(bar.day)).font(ElchiFont.poppins(9)).foregroundStyle(c.muted).lineLimit(1)
                                    .minimumScaleFactor(0.7)
                            }
                            .frame(maxWidth: .infinity)
                            .accessibilityElement(children: .ignore)
                            .accessibilityLabel("\(strings.dayMonth(bar.day)): \(strings.money(bar.minor))")
                        }
                    }
                    .frame(height: 112, alignment: .bottom)
                }
                Text(strings.t("income.chartNote")).font(ElchiFont.poppins(11)).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
            }
        }
        .accessibilityIdentifier("elchi.wallet.chart")
    }

    // MARK: Top-up

    @ViewBuilder
    private var topupForm: some View {
        @Bindable var model = model
        SectionTitle(strings.t("income.topupTitle"), description: strings.t("income.topupNote"))
        Note(strings.t("driver.wallet.requisitesNote"), tone: .blue)
        ElchiButton(strings.t("driverProfile.action.support"), variant: .outline, size: .medium, icon: .head, action: onHelp)
        ElchiField(text: $amountShown, label: strings.t("income.amountLabel"), placeholder: "100 000",
                   error: model.attempted && model.body == nil ? strings.t("driver.wallet.amountInvalid") : nil, keyboard: .numberPad)
            .onChange(of: amountShown) { _, typed in
                let digits = Money.soumDigits(typed)
                model.amountText = digits
                let formatted = Money.grouped(digits)
                if amountShown != formatted { amountShown = formatted }
            }
            .onChange(of: model.amountText) { _, digits in if digits.isEmpty && !amountShown.isEmpty { amountShown = "" } }
            .accessibilityIdentifier("elchi.wallet.amount")
        VStack(alignment: .leading, spacing: 6) {
            Text(strings.t("driver.wallet.methodLabel")).font(ElchiFont.label).foregroundStyle(c.text)
            Segmented(WalletLogic.methods.map { ($0, strings.t("driver.wallet.method.\($0)")) }, selected: model.method) { model.method = $0 }
        }
        ElchiField(text: $model.payerReference, label: strings.t("driver.wallet.payerReference"))
        ElchiField(text: $model.note, label: strings.t("driver.wallet.noteLabel"), multiline: true)
        if let error = model.sendError { Note(strings.errorText(error), tone: .err) }
        ElchiButton(strings.t("income.topupSend"), loading: model.sending) {
            UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
            Task { await model.submit() }
        }
        .disabled(model.sending)
        .accessibilityIdentifier("elchi.wallet.submit")
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
                                .compactMap { $0 }.joined(separator: " · "))
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
