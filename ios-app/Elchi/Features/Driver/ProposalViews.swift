import SwiftUI

// MARK: - Takliflarim

/// Open · Accepted · Closed. Each card: route, window, current price, whose turn it is, the countdown (the list is
/// read again when one runs out).
struct DriverProposalsView: View {
    let model: DriverProposalsModel
    let onBack: () -> Void
    let onOpen: (ProposalThreadDTO) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(BannerCenter.self) private var banners: BannerCenter?
    @State private var now = Date()
    @State private var refreshing = false

    var body: some View {
        ScreenScaffold(title: strings.t("proposals.title"), backLabel: strings.t("common.back"), onBack: onBack,
                       actions: [BarAction(id: "refresh", icon: .refresh, label: strings.t("proposal.refresh"), loading: refreshing) {
                           Task {
                               refreshing = true
                               await model.load()
                               refreshing = false
                               banners?.ok("client.booking.refreshed")
                           }
                       }]) {
            Segmented(ProposalTab.allCases.map { ($0, strings.t($0.labelKey)) }, selected: model.tab) { tab in
                model.tab = tab
                Task { await model.load(tab) }
            }
            switch model.lists[model.tab] ?? .loading {
            case .loading:
                SkeletonCards(count: 3)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err)
                ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.load() } }
            case .loaded(let list) where list.isEmpty:
                EmptyState(icon: .tag, title: strings.t("proposals.empty"), description: strings.t("proposals.emptyDriver"))
            case .loaded(let list):
                ForEach(list, id: \.id) { thread in
                    ProposalCard(thread: thread, versions: model.versions(thread.id), now: now) { onOpen(thread) }
                }
            }
        } footer: {
            EmptyView()
        }
        .refreshable { await model.load() }
        .task { await model.load() }
        .task { await tick() }
    }

    /// Every 20 s: the countdowns move; an offer that just ran out sends the list back to the server.
    private func tick() async {
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(20))
            let before = now
            now = Date()
            let lapsed = (model.lists[model.tab]?.value ?? []).contains { thread in
                guard let expires = ServerTime.parse(thread.currentVersion?.expiresAt) else { return false }
                return expires > before && expires <= now
            }
            if lapsed { await model.load() }
        }
    }
}

/// DESIGN07 8.1 / 8.2: route, window, the current price and a status badge; then the status sentence (the client's
/// counter with both prices when the history is known) and the countdown while open. Countered cards are outlined,
/// withdrawn / run-out ones faded.
struct ProposalCard: View {
    let thread: ProposalThreadDTO
    var versions: [ProposalVersionDTO]? = nil
    let now: Date
    let onOpen: () -> Void
    @Environment(LocaleStore.self) private var strings

    var body: some View {
        let version = thread.currentVersion
        let badge = ProposalBadge.of(thread, now: now)
        let actions = DriverNegotiation.of(thread, now: now)
        var lines: [ItemLine] = []
        if let line = ProposalLine.of(thread, versions: versions, now: now) {
            lines.append(ItemLine(strings.proposalLine(line), tone: badge == .countered ? .warn : nil))
        }
        if actions.open, let version, let left = strings.driverExpiresIn(version, now: now) { lines.append(ItemLine(left, tone: .warn)) }
        return ItemCard(title: version.map(strings.route) ?? thread.listingId, icon: .pin, badge: (strings.t(badge.key), badge.tone),
                        sub: version.map { strings.span($0.pickupWindowStart, $0.pickupWindowEnd) }, lines: lines,
                        right: version.map { strings.money($0.totalMinor) }, highlighted: badge.outlined, muted: badge.faded,
                        action: onOpen)
            .opacity(badge.faded ? 0.7 : 1)
            .accessibilityIdentifier("elchi.proposal.\(thread.id)")
    }
}

extension LocaleStore {
    func proposalLine(_ line: ProposalLine) -> String {
        switch line {
        case .key(let key): t(key)
        case .clientCounter(let price, let mine): t("driver.offer.clientCounterLine", ("price", money(price)), ("mine", money(mine)))
        case .myCounter(let price): t("driver.offer.myCounterLine", ("price", money(price)))
        }
    }
}

// MARK: - One negotiation

/// The thread from the driver's side: the current offer and its countdown, the history of versions, and the answers
/// the turn allows. Accepting makes the booking (its screens are Stage 09).
struct DriverThreadView: View {
    let model: DriverThreadModel
    let onBack: () -> Void
    /// Stage 09: the booking an accepted thread became.
    var onOpenBooking: ((String) -> Void)? = nil
    /// Q100 / DESIGN07 8.7: the driver accepted the client's price - the booking's chat opens.
    var onAccepted: (String) -> Void = { _ in }
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(BannerCenter.self) private var banners: BannerCenter?
    @State private var refreshing = false
    /// The counter's price was empty or the client's own (DESIGN07 8.5).
    @State private var counterProblem: String?
    @State private var now = Date()
    @State private var countering = false
    @State private var priceText = ""
    @State private var priceDigits = ""
    @State private var confirmWithdraw = false
    @State private var confirmAccept = false
    @State private var bookingId: String?

    var body: some View {
        ScreenScaffold(title: strings.t("proposals.title"), backLabel: strings.t("common.back"), onBack: onBack,
                       actions: [BarAction(id: "refresh", icon: .refresh, label: strings.t("proposal.refresh"), loading: refreshing) {
                           Task {
                               refreshing = true
                               await model.load()
                               refreshing = false
                               banners?.ok("client.booking.refreshed")
                           }
                       }]) {
            switch model.thread {
            case .loading:
                SkeletonCards(count: 2)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err)
                ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.load() } }
            case .loaded(let thread):
                content(thread)
            }
        } footer: {
            EmptyView()
        }
        .refreshable { await model.load() }
        .task { await model.load() }
        .task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(20))
                let before = now
                now = Date()
                if let expires = ServerTime.parse(model.thread.value?.currentVersion?.expiresAt), expires > before, expires <= now { await model.load() }
            }
        }
        .overlay {
            if confirmWithdraw { withdrawDialog }
            if confirmAccept, let thread = model.thread.value { acceptDialog(thread) }
        }
    }

    @ViewBuilder
    private func content(_ thread: ProposalThreadDTO) -> some View {
        let actions = DriverNegotiation.of(thread, now: now)
        let badge = ProposalBadge.of(thread, now: now)
        if let version = thread.currentVersion {
            ItemCard(title: strings.route(version), icon: .pin, badge: (strings.t(badge.key), badge.tone),
                     sub: strings.span(version.pickupWindowStart, version.pickupWindowEnd),
                     lines: [badge == .accepted ? nil : ProposalLine.of(thread, now: now).map { ItemLine(strings.proposalLine($0), tone: badge == .countered ? .warn : nil) },
                             actions.open ? strings.driverExpiresIn(version, now: now).map { ItemLine($0, tone: .warn) } : nil,
                             version.message.flatMap { $0.isEmpty ? nil : ItemLine($0) }].compactMap { $0 },
                     right: strings.money(version.totalMinor), highlighted: badge.outlined)
                .accessibilityIdentifier("elchi.thread.current")
            // The money only while it can still happen (or did): a withdrawn or expired offer costs nothing.
            if actions.open || thread.state == "accepted" { money(version) }
        }
        if let error = model.error {
            Note(model.confirmAgain ? strings.t("client.listingBids.termsChanged") : strings.marketErrorText(error), tone: .err)
                .accessibilityIdentifier("elchi.thread.error")
        }
        ForEach(model.warnings, id: \.code) { Note(strings.priceWarningText($0), tone: .warn) }
        if thread.state == "accepted" || thread.bookingId != nil {
            // The booking exists (Stage 09): its screen and chat are one tap away; never the old "next stage" text.
            Note(strings.t("driver.offer.acceptedLine"), tone: .ok)
                .accessibilityIdentifier("elchi.thread.booked")
            if let id = bookingId ?? thread.bookingId, let onOpenBooking {
                ElchiButton(strings.t("driverBooking.title"), variant: .soft, icon: .clip) { onOpenBooking(id) }
                    .accessibilityIdentifier("elchi.thread.openBooking")
            }
        }
        if actions.open { answers(actions, thread) }
        history(thread)
    }

    /// With a driver promo quote (off in dev): what the driver collects, is charged and keeps. Otherwise the plain
    /// commission estimate the version carries (driver side only, Q103).
    @ViewBuilder
    private func money(_ version: ProposalVersionDTO) -> some View {
        if case .driver(let quote)? = version.promoQuote {
            MoneyLines(title: strings.t("proposals.ifYouAccept"), rows: [
                MoneyLines.Row(strings.t("promo.line.offerPrice"), strings.money(quote.fareMinor)),
                MoneyLines.Row(strings.t("promo.line.cashFromClient"), strings.money(quote.cashToCollectMinor), emphasis: true),
                MoneyLines.Row(strings.t("promo.line.discountCovered"), strings.money(quote.passengerDiscountCoveredMinor)),
                MoneyLines.Row(strings.t("commissionPreview.title"), strings.money(quote.baseCommissionMinor)),
                MoneyLines.Row(strings.t("promo.line.creditToUse"), "−\(strings.money(quote.driverCreditMinor))", tone: .ok),
                MoneyLines.Row(strings.t("promo.line.chargedFromBalance"), strings.money(quote.commissionChargedMinor)),
                MoneyLines.Row(strings.t("promo.line.youKeep"), strings.money(quote.driverKeepsMinor), emphasis: true),
            ])
            Text(strings.t("promoScreen.driverCovers")).font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
        } else if let fee = version.feeQuote {
            ElchiCard {
                CardRow(strings.t("commissionPreview.title"),
                        strings.t("commissionPreview.line", ("amount", strings.money(fee.commissionMinor)), ("percent", OfferBody.percent(bps: fee.feeBps)),
                                  ("total", strings.money(version.totalMinor))),
                        first: true, detail: strings.t("commissionPreview.note"))
            }
        }
    }

    @ViewBuilder
    private func answers(_ actions: DriverNegotiation, _ thread: ProposalThreadDTO) -> some View {
        let busy = model.busy
        if actions.driversTurn {
            if countering {
                ElchiField(text: $priceText, label: strings.t("proposals.newPrice"),
                           placeholder: thread.currentVersion.map { Money.grouped(String($0.unitPriceMinor / 100)) }, error: counterProblem.map { strings.t($0) },
                           keyboard: .numberPad)
                    .onChange(of: priceText) { _, typed in
                        counterProblem = nil
                        priceDigits = Money.soumDigits(typed)
                        let formatted = Money.grouped(priceDigits)
                        if priceText != formatted { priceText = formatted }
                    }
                HStack(spacing: 8) {
                    ElchiButton(strings.t("common.send"), size: .pair, loading: busy == "counter") {
                        let price = Money.minor(fromSoum: priceDigits)
                        if let problem = DriverCounterCheck.problemKey(priceMinor: price, clientUnitMinor: thread.currentVersion?.unitPriceMinor ?? 0) {
                            counterProblem = problem
                            return
                        }
                        Task { if await model.counter(priceMinor: price) { countering = false } }
                    }
                    .disabled(busy != nil)
                    .accessibilityIdentifier("elchi.thread.counterSend")
                    ElchiButton(strings.t("common.cancel"), variant: .neutral, size: .pair) { countering = false }
                }
            } else {
                ElchiButton(model.confirmAgain ? strings.t("common.confirm") : strings.t("proposals.acceptClientPrice"), loading: busy == "accept") {
                    model.clear()
                    confirmAccept = true
                }
                .disabled(busy != nil)
                .accessibilityIdentifier("elchi.thread.accept")
                HStack(spacing: 8) {
                    ElchiButton(strings.t("proposal.reject"), variant: .dangerSoft, size: .pair, loading: busy == "reject") {
                        Task { _ = await model.reject() }
                    }
                    .accessibilityIdentifier("elchi.thread.reject")
                    if actions.canCounter {
                        ElchiButton(strings.t("client.listingBids.counterShort", ("count", actions.revisionsLeft)), variant: .neutral, size: .pair) {
                            model.clear()
                            // Empty, the client's price as the placeholder-like hint: the same price would only spend a revision.
                            priceDigits = ""
                            priceText = ""
                            counterProblem = nil
                            countering = true
                        }
                        .accessibilityIdentifier("elchi.thread.counter")
                    }
                }
                .disabled(busy != nil)
                if !actions.canCounter {
                    Text(strings.t("proposals.noRevisionsLeft")).font(ElchiFont.caption).foregroundStyle(c.muted)
                }
            }
        } else if actions.canWithdraw {
            ElchiButton(strings.t("proposals.withdraw"), variant: .neutral, loading: busy == "withdraw") { confirmWithdraw = true }
                .disabled(busy != nil)
                .accessibilityIdentifier("elchi.thread.withdraw")
        }
    }

    /// Who wrote each version, its price and window, when, and what became of it.
    @ViewBuilder
    private func history(_ thread: ProposalThreadDTO) -> some View {
        let versions = (thread.versions ?? thread.currentVersion.map { [$0] } ?? []).sorted { $0.revision > $1.revision }
        if !versions.isEmpty {
            ElchiCard {
                CardTitle(strings.t("client.amendment.history"))
                ForEach(versions, id: \.id) { version in
                    let who = version.authorSide == .driver ? strings.t("client.bookingDetail.bySideClient") : strings.t("dispute.side.client")
                    let when = ServerTime.parse(version.createdAt).map(DepartureWindow.shortText) ?? ""
                    let state = version.status == .active ? nil : strings.tOrNil("proposalStatus.\(version.status.rawValue)")
                    CardRow("\(who) · \(when)", strings.money(version.totalMinor),
                            detail: [strings.span(version.pickupWindowStart, version.pickupWindowEnd), state].compactMap { $0 }.joined(separator: " · "))
                }
            }
            .accessibilityIdentifier("elchi.thread.history")
        }
    }

    private var withdrawDialog: some View {
        DialogOverlay(dismissLabel: strings.t("confirmDialog.back"), onDismiss: { confirmWithdraw = false }) {
            Text(strings.t("proposals.withdraw")).font(ElchiFont.poppins(19, .medium, relativeTo: .title2)).foregroundStyle(c.text)
            Text(strings.t("driverBid.noHoldNote")).font(ElchiFont.secondary).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
            ElchiButton(strings.t("proposals.withdraw"), variant: .danger, loading: model.busy == "withdraw") {
                Task {
                    _ = await model.withdraw()
                    confirmWithdraw = false
                }
            }
            .accessibilityIdentifier("elchi.thread.withdrawConfirm")
            ElchiButton(strings.t("confirmDialog.back"), variant: .neutral, size: .medium) { confirmWithdraw = false }
        }
    }

    /// Accepting is never one tap: the agreed total (the version's own, never recomputed) and that a booking is made.
    private func acceptDialog(_ thread: ProposalThreadDTO) -> some View {
        DialogOverlay(dismissLabel: strings.t("confirmDialog.back"), onDismiss: { if model.busy == nil { confirmAccept = false } }) {
            Text(strings.t("proposals.acceptClientPrice")).font(ElchiFont.poppins(19, .medium, relativeTo: .title2)).foregroundStyle(c.text)
            Text(strings.t("client.accept.text")).font(ElchiFont.secondary).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
            if let version = thread.currentVersion {
                MoneyLines(rows: [MoneyLines.Row(strings.t("promo.line.agreedPrice"), strings.money(version.totalMinor), emphasis: true)])
            }
            ElchiButton(strings.t("common.confirm"), loading: model.busy == "accept") {
                Task {
                    bookingId = await model.accept()
                    confirmAccept = false
                    // Q100: the booking's chat opens straight away.
                    if case .bookingChat(let id) = AcceptNext.after(bookingId: bookingId) {
                        banners?.ok("driver.offer.clientPriceAccepted")
                        onAccepted(id)
                    }
                }
            }
            .accessibilityIdentifier("elchi.thread.acceptConfirm")
            ElchiButton(strings.t("confirmDialog.back"), variant: .neutral, size: .medium) { confirmAccept = false }.disabled(model.busy != nil)
        }
    }
}
