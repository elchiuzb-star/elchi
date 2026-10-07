import SwiftUI

// MARK: - Eski buyurtmalar (v1 archive list)

/// BOSQICH 10: the client's v1 orders on their own screen, from the drawer (menu) or from the row on Buyurtmalar
/// (back). The grey note says what is still possible (the design's "faqat o'qish uchun" is not true while v1 lets a
/// started order finish), chips filter the loaded pages on the device (`GET /client/orders` takes one status), and a
/// filtered list shorter than a screen asks for older pages. Cards: route, status, `number · day`, price, and the
/// bids line while drivers can still bid.
struct LegacyListView: View {
    let model: ClientOrdersModel
    let leading: ElchiIcon
    let onLeading: () -> Void
    let onOpen: (Int) -> Void
    @Environment(LocaleStore.self) private var strings
    @State private var filter: LegacyFilter = .all

    var body: some View {
        ScreenScaffold(title: strings.t("orders.legacy"), leading: leading, backLabel: strings.t(leading == .menu ? "nav.menu" : "common.back"),
                       onBack: onLeading) {
            Note(strings.t("client.v3archive.listNote"), tone: .gray)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(LegacyFilter.allCases, id: \.self) { chip in
                        Chip(strings.t(chip.labelKey), selected: filter == chip, filled: true) { filter = chip }
                            .accessibilityIdentifier("elchi.legacy.filter.\(chip.rawValue)")
                    }
                }
                .padding(.vertical, 2)
            }
            switch model.legacy {
            case .loading:
                LoadingState()
            case .failed(let error):
                Note(strings.bannerErrorText(error), tone: .err)
                ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.refreshLegacy() } }
            case .loaded(let all):
                let rows = filter.apply(all)
                if rows.isEmpty && !model.legacyHasMore {
                    EmptyListState(strings.t("orders.empty"))
                }
                ForEach(rows) { order in card(order) }
                if filter == .all ? model.legacyHasMore : LegacyFilter.wantsMore(filtered: rows.count, hasMore: model.legacyHasMore) {
                    // The end of the list (or a filtered list still shorter than a screen) reads the next page; the
                    // marker asks again after each.
                    ProgressView().frame(maxWidth: .infinity).padding(.vertical, 8)
                        .task(id: "\(all.count)-\(filter.rawValue)") { await model.loadMoreLegacy() }
                } else if model.legacyHasMore {
                    // A filtered list that already fills a screen: older pages on request.
                    ElchiButton(strings.t("blockReport.loadMore"), variant: .ghost, size: .medium, icon: .refresh,
                                loading: model.loadingMoreLegacy) { Task { await model.loadMoreLegacy() } }
                }
            }
        } footer: {
            EmptyView()
        }
        .refreshable { await model.refreshLegacy() }
        .task { if model.legacy.value == nil { await model.refreshLegacy() } }
    }

    private func card(_ order: LegacyOrder) -> some View {
        // Bids matter only while the order still takes them.
        let bids = LegacyActions.bidsOpen(order.status) ? order.bidsCount ?? 0 : 0
        return ItemCard(title: strings.route(order), badge: strings.status(.legacy(order.status)),
                        lines: bids > 0 ? [ItemLine(strings.t("app.orderCard.bids", ("count", bids)))] : [],
                        meta: LegacyListMeta.line(orderNumber: order.orderNumber, createdAt: order.createdAt),
                        right: order.priceMinor.map(strings.money),
                        action: { onOpen(order.id) })
            .accessibilityIdentifier("elchi.legacy.\(order.id)")
    }
}
