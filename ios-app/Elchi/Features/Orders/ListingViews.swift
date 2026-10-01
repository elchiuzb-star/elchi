import SwiftUI
import UIKit

// MARK: - Buyurtma tafsilotlari

/// One listing of the client's: the summary card, its details, the parcel photo, the offers button, the owner's
/// controls (edit, pause / resume), share links, and cancel behind a confirmation sheet.
struct ListingDetailView: View {
    let model: ListingModel
    let onBack: () -> Void
    let onEdit: () -> Void
    let onBids: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var confirmCancel = false

    var body: some View {
        ScreenScaffold(title: strings.t("listingDetail.title"), backLabel: strings.t("common.back"), onBack: onBack, banner: banner) {
            switch model.listing {
            case .loading:
                SkeletonCards(count: 3)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err)
                ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.load() } }
            case .loaded(let listing):
                content(listing)
            }
        } footer: {
            EmptyView()
        }
        .refreshable { await model.load() }
        .task { await model.load() }
        .sheet(isPresented: $confirmCancel) {
            CancelListingSheet(openOffers: model.openOffers, working: model.running == .cancel, onConfirm: {
                Task {
                    _ = await model.cancel()
                    confirmCancel = false
                }
            }, onBack: { confirmCancel = false })
        }
    }

    @ViewBuilder
    private func content(_ listing: ListingDTO) -> some View {
        let actions = OwnerListingActions.of(listing.status)
        ForEach(model.warnings, id: \.code) { Note(strings.warningText($0), tone: .warn) }

        ListingSummaryCard(listing: listing, stats: offerStats)
        details(listing)
        photo(listing)
        offersEntry(listing)

        if actions.canEdit || actions.canPause || actions.canResume {
            SectionTitle(strings.t("client.listingDetail.manage"))
            HStack(spacing: 8) {
                if actions.canEdit { ElchiButton(strings.t("listingOwner.edit"), variant: .neutral, size: .pair, icon: .file, action: onEdit) }
                if actions.canPause {
                    ElchiButton(strings.t("listingOwner.pause"), variant: .neutral, size: .pair, loading: model.running == .pause) {
                        Task { await model.pause() }
                    }
                } else if actions.canResume {
                    ElchiButton(strings.t("listingOwner.resume"), variant: .neutral, size: .pair, loading: model.running == .resume) {
                        Task { await model.resume() }
                    }
                }
            }
            .disabled(model.running != nil)
            if actions.canPause || actions.canResume {
                Text(strings.t(actions.canPause ? "listingOwner.pauseHint" : "client.listingDetail.resumeHint"))
                    .font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
            }
        }
        if actions.canShare { ShareSection(model: model) }
        if actions.canCancel {
            ElchiButton(strings.t("listingDetail.cancel"), variant: .dangerSoft) { confirmCancel = true }
                .disabled(model.running != nil)
                .padding(.top, 4)
        }
    }

    /// What the last owner command did (or why it failed), kept in sight under the top bar.
    private var banner: (text: String, tone: Tone)? {
        if let error = model.commandError, model.running == nil, model.failed != .share, model.failed != .save {
            return (strings.errorText(error), .err)
        }
        return model.notice.map { (strings.t($0), .ok) }
    }

    private var offerStats: OfferStats? {
        guard let threads = model.offers.threads.value else { return nil }
        let open = threads.filter { NegotiationActions.of($0).open }
        return OfferStats(open: open.count, newest: open.compactMap { ServerTime.parse($0.currentVersion?.createdAt) }.max())
    }

    private func details(_ listing: ListingDTO) -> some View {
        ElchiCard {
            CardRow(strings.t(listing.originStop == nil ? "listingDetail.pickupPoint" : "listingDetail.pickupStop"),
                    strings.endAddress(stop: listing.originStop, point: listing.originPoint), first: true)
            CardRow(strings.t(listing.destinationStop == nil ? "listingDetail.dropoffPoint" : "listingDetail.dropoffStop"),
                    strings.endAddress(stop: listing.destinationStop, point: listing.destinationPoint))
            CardRow(strings.t("listingDetail.departureWindow"), strings.window(listing.departureWindowStart, listing.departureWindowEnd))
            CardRow(strings.t("common.price"), strings.money(listing.totalMinor))
            if let parcel = strings.parcel(listing.parcel) { CardRow(strings.t("listingDetail.parcel"), parcel) }
            if let comment = listing.comment, !comment.isEmpty { CardRow(strings.t("listingOwner.commentLabel"), comment) }
            if let expires = ServerTime.parse(listing.expiresAt) {
                CardRow(strings.t("client.listingDetail.expires"),
                        strings.t("client.listingDetail.until", ("date", String(DepartureWindow.shortText(expires).prefix(5)))))
            }
        }
    }

    @ViewBuilder
    private func photo(_ listing: ListingDTO) -> some View {
        SectionTitle(strings.t("listingDetail.parcelPhoto"))
        if let url = model.photoURL {
            // A short-lived signed link (Q6): when it has expired, pulling to refresh fetches a new one.
            AsyncImage(url: url) { phase in
                switch phase {
                case .success(let image):
                    image.resizable().scaledToFill()
                case .failure:
                    Text(strings.t("app.photo.reload")).font(ElchiFont.caption).foregroundStyle(c.muted)
                default:
                    ProgressView()
                }
            }
            .frame(maxWidth: .infinity).frame(height: 170)
            .background(c.field)
            .clipShape(RoundedRectangle(cornerRadius: 18))
            .accessibilityLabel(strings.t("app.photo.alt"))
        } else {
            Text(strings.t("app.photo.none")).font(ElchiFont.caption).foregroundStyle(c.muted)
        }
    }

    @ViewBuilder
    private func offersEntry(_ listing: ListingDTO) -> some View {
        switch model.offers.threads {
        case .loaded(let threads) where threads.isEmpty:
            if listing.status == .published {
                Note(strings.t("listingBids.emptySubtitle"), tone: .gray, title: strings.t("listingBids.emptyTitle"))
            }
        case .loaded:
            ElchiButton(strings.t("client.listingDetail.viewOffers", ("count", model.openOffers)), action: onBids)
        case .failed(let error):
            Note(strings.errorText(error), tone: .err)
        case .loading:
            EmptyView()
        }
    }
}

/// "Buyurtmani bekor qilasizmi?" - cancel is never one tap (design note: defect 10 fixed).
private struct CancelListingSheet: View {
    let openOffers: Int
    let working: Bool
    let onConfirm: () -> Void
    let onBack: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 4) {
                Text(strings.t("confirmDialog.cancelOrder.title")).font(ElchiFont.poppins(20, .medium, relativeTo: .title2)).foregroundStyle(c.text)
                    .accessibilityAddTraits(.isHeader)
                Text(openOffers > 0 ? strings.t("client.listingCancel.text", ("count", openOffers)) : strings.t("client.listingCancel.textNoOffers"))
                    .font(ElchiFont.secondary).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
            }
            ElchiButton(strings.t("bookingCancel.confirm"), variant: .danger, loading: working, action: onConfirm)
            ElchiButton(strings.t("confirmDialog.back"), variant: .neutral, action: onBack).disabled(working)
        }
        .padding(EdgeInsets(top: 28, leading: 20, bottom: 12, trailing: 20))
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(c.card.ignoresSafeArea())
        .presentationDetents([.height(330)])
        .presentationCornerRadius(ElchiShape.sheet)
        .presentationDragIndicator(.visible)
    }
}

/// Share links: TTL in days (the API takes hours), generic or Telegram text; the URL is returned once, so it is
/// shown here with copy and the system share sheet.
private struct ShareSection: View {
    let model: ListingModel
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var copied = false

    var body: some View {
        SectionTitle(strings.t("listingShare.title"), description: strings.t("trackingShare.shareHint"))
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(ShareTTL.days, id: \.self) { days in
                    Chip(strings.t("trackingShare.ttlDays", ("count", days)), selected: model.shareDays == days, filled: true) { model.shareDays = days }
                }
            }
        }
        .accessibilityLabel(strings.t("trackingShare.ttlLabel"))
        Segmented([(ShareLinkChannel.generic, strings.t("trackingShare.channelGeneric")), (.telegram, strings.t("client.share.telegram"))],
                  selected: model.shareChannel) { model.shareChannel = $0 }
        ElchiButton(strings.t("trackingShare.create"), variant: .soft, icon: .share, loading: model.running == .share) {
            copied = false
            Task { await model.createShareLink() }
        }
        .disabled(model.running != nil)
        if let error = model.commandError, model.running == nil, model.failed == .share {
            Note(strings.shareErrorText(error), tone: .err)
        }
        if let link = model.shareLink { linkBox(link) }
    }

    private func linkBox(_ link: ShareLinkDTO) -> some View {
        ElchiCard(padding: EdgeInsets(top: 12, leading: 14, bottom: 12, trailing: 14)) {
            VStack(alignment: .leading, spacing: 10) {
                Text(strings.t("client.share.link")).font(ElchiFont.caption).foregroundStyle(c.muted)
                Text(link.url).font(.system(size: 13, design: .monospaced)).foregroundStyle(c.text).lineLimit(2).textSelection(.enabled)
                    .padding(12).frame(maxWidth: .infinity, alignment: .leading)
                    .background(c.field, in: RoundedRectangle(cornerRadius: 14))
                Text(strings.t("client.share.text")).font(ElchiFont.caption).foregroundStyle(c.muted)
                Text(link.shareText).font(ElchiFont.poppins(13)).foregroundStyle(c.text).textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                if let expires = ServerTime.parse(link.expiresAt) {
                    Text(strings.t("trackingShare.validUntil", ("time", DepartureWindow.text(expires)))).font(ElchiFont.caption).foregroundStyle(c.muted)
                }
                HStack(spacing: 8) {
                    ElchiButton(strings.t(copied ? "trackingShare.copied" : "promoScreen.copy"), variant: .soft, size: .pair, icon: .copy) {
                        UIPasteboard.general.string = link.url
                        copied = true
                    }
                    ShareLink(item: link.url, message: Text(link.shareText)) {
                        HStack(spacing: 6) {
                            ElchiIcon.share.image(size: 18)
                            Text(strings.t("client.share.send")).font(ElchiFont.buttonSmall).lineLimit(1)
                        }
                        .foregroundStyle(c.onBrand)
                        .frame(maxWidth: .infinity, minHeight: 48)
                        .background(c.brand, in: Capsule())
                    }
                }
                Text(strings.t("trackingShare.urlOnce")).font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
                ElchiButton(strings.t("client.share.revoke"), variant: .ghost, size: .medium) { Task { await model.revokeShareLink() } }
            }
        }
    }
}

// MARK: - E'lonni tahrirlash

/// Price, comment and the departure window. Q20: moving the window of a live listing closes its open offers - when
/// there are any, the warning says how many and the button asks for the explicit "Tushundim, saqlash".
struct ListingEditView: View {
    let model: ListingModel
    let onBack: () -> Void
    let onSaved: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var form: ListingEditForm?
    @State private var priceText = ""
    @State private var editing: WindowEdge?

    var body: some View {
        let listing = model.listing.value
        let plan = listing.flatMap { dto in form.map { ListingPatchPlan.plan(dto, $0) } }
        let warnOffers = plan?.material == true && model.openOffers > 0
        ScreenScaffold(title: strings.t("listingOwner.editTitle"), backLabel: strings.t("common.back"), onBack: onBack) {
            if form != nil {
                ElchiField(text: $priceText, label: strings.t("listingOwner.priceLabel"), keyboard: .numberPad)
                    .onChange(of: priceText) { _, typed in
                        // Local text re-synced after every edit: SwiftUI's TextField ignores a binding that rewrites the input.
                        let digits = Money.soumDigits(typed)
                        form?.priceDigits = digits
                        let formatted = Money.grouped(digits)
                        if priceText != formatted { priceText = formatted }
                    }
                ElchiField(text: Binding(get: { form?.comment ?? "" }, set: { form?.comment = $0 }), label: strings.t("listingOwner.commentLabel"),
                           hint: strings.t("bookingChat.autoMaskNote"), multiline: true)
                PickerField(label: strings.t("listingOwner.windowStart"), value: form?.windowStart.map(DepartureWindow.text),
                            placeholder: strings.t("client.routeSummary.windowPlaceholder"),
                            error: plan?.invalid == "window_past" || plan?.invalid == "window_incomplete") { editing = .start }
                PickerField(label: strings.t("listingOwner.windowEnd"), value: form?.windowEnd.map(DepartureWindow.text),
                            placeholder: strings.t("client.routeSummary.windowPlaceholder"), error: plan?.invalid == "window_order") { editing = .end }
                Text(strings.t("listingOwner.nonMaterialNote")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
                    .fixedSize(horizontal: false, vertical: true)
                if warnOffers {
                    Note("\(strings.t("listingOwner.materialWarning")) \(strings.t("listingOwner.openOffers", ("count", model.openOffers)))", tone: .warn)
                }
                if let invalid = plan?.invalid {
                    Note(strings.tOrNil("listingOwner.invalid.\(invalid)") ?? invalid, tone: .err)
                }
                if let error = model.commandError, model.running == nil, model.failed == .save { Note(strings.errorText(error), tone: .err) }
            } else {
                SkeletonCards(count: 2)
            }
        } footer: {
            ElchiButton(strings.t(warnOffers ? "listingOwner.materialConfirm" : "common.save"), loading: model.running == .save) {
                guard let plan else { return }
                Task { if await model.save(plan) { onSaved() } }
            }
            .disabled(plan == nil || plan?.empty == true || plan?.invalid != nil)
        }
        .onAppear {
            model.clearNotice()
            if form == nil, let listing { start(listing) }
        }
        .onChange(of: model.listing.value?.version) { _, _ in
            // After VERSION_CONFLICT the listing was reloaded: the next save goes against the current version and the
            // form keeps what was typed.
            if form == nil, let listing = model.listing.value { start(listing) }
        }
        .task { await model.offers.reload() }
        .sheet(item: $editing) { edge in
            WindowPickerSheet(title: strings.t(edge == .start ? "listingOwner.windowStart" : "listingOwner.windowEnd"),
                              initial: (edge == .start ? form?.windowStart : form?.windowEnd) ?? DepartureWindow.suggested().start) { date in
                if edge == .start { form?.windowStart = date } else { form?.windowEnd = date }
                editing = nil
            }
        }
    }

    private func start(_ listing: ListingDTO) {
        let initial = ListingEditForm(listing: listing)
        form = initial
        priceText = Money.grouped(initial.priceDigits)
    }
}

// MARK: - Haydovchi takliflari

/// The drivers' offers on one listing, sorted, with the client's answers: choose (confirmation dialog), reject,
/// another price (inline), withdraw its own counter. A live countdown hides the answers the moment an offer lapses.
struct ListingBidsView: View {
    let model: ListingModel
    let onBack: () -> Void
    /// The listing and the booking the accept made (the flow opens its detail, then its chat - Q100).
    let onAccepted: (String, ClientBookingDTO) -> Void
    @Environment(LocaleStore.self) private var strings
    @State private var sort: OfferSort = .cheapest
    @State private var counterFor: String?
    @State private var accepting: ProposalThreadDTO?
    @State private var now = Date()

    var body: some View {
        ScreenScaffold(title: strings.t("listingBids.title"), backLabel: strings.t("common.back"), onBack: onBack) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(OfferSort.allCases, id: \.self) { option in
                        Chip(strings.t(sortKey(option)), selected: sort == option, filled: true) { sort = option }
                    }
                }
            }
            if model.listing.value?.status == .paused { Note(strings.t("client.listingBids.pausedNote"), tone: .warn) }
            switch model.offers.threads {
            case .loading:
                SkeletonCards(count: 3)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err)
                ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.load() } }
            case .loaded(let threads):
                if threads.isEmpty {
                    EmptyState(icon: .pkg, title: strings.t("listingBids.emptyTitle"), description: strings.t("listingBids.emptySubtitle"))
                }
                let cheapest = OfferSort.cheapestOpenId(threads, now: now)
                ForEach(sort.sorted(threads, now: now), id: \.id) { thread in
                    OfferCard(thread: thread, listing: model.listing.value, style: .listing, offers: model.offers, now: now,
                              cheapest: thread.id == cheapest, counterOpen: counterFor == thread.id,
                              onCounter: { counterFor = $0 ? thread.id : nil }, onAccept: { accepting = thread })
                }
            }
            Note(strings.t("listingBids.identityHidden"))
        } footer: {
            EmptyView()
        }
        .refreshable { await model.load() }
        .task { await model.load() }
        .task { await tick() }
        .overlay {
            if let thread = accepting {
                AcceptDialog(thread: thread, offers: model.offers, onClose: { accepting = nil }) { onAccepted(thread.listingId, $0) }
            }
        }
    }

    private func sortKey(_ sort: OfferSort) -> String {
        switch sort {
        case .cheapest: "client.listingBids.sortCheapest"
        case .fastest: "client.listingBids.sortFastest"
        case .bestRated: "client.listingBids.sortRating"
        }
    }

    private func tick() async {
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(1))
            now = Date()
        }
    }
}

// MARK: - One offer

/// One negotiation thread as a card. `.listing` (the listing's offers screen): the driver's label and the offer's
/// places; `.proposals` ("Takliflarim"): the listing's route and whose turn it is. The answers follow
/// `NegotiationActions` - nothing the server would refuse is offered.
struct OfferCard: View {
    enum Style { case listing, proposals }

    let thread: ProposalThreadDTO
    let listing: ListingDTO?
    let style: Style
    let offers: OfferThreads
    let now: Date
    let cheapest: Bool
    let counterOpen: Bool
    let onCounter: (Bool) -> Void
    let onAccept: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        let actions = NegotiationActions.of(thread, now: now)
        let version = thread.currentVersion
        ItemCard(title: title, badge: cheapest ? (text: strings.t("client.listingBids.cheapest"), tone: Tone.ok) : nil, sub: sub(actions), lines: lines(actions),
                 right: version.map { strings.money($0.totalMinor) }, highlighted: cheapest, underline: style == .listing,
                 muted: !actions.open && !accepted) {
            if let error = offers.errors[thread.id] { Note(strings.offerErrorText(error), tone: .err).padding(.top, 6) }
            ForEach(offers.warnings[thread.id] ?? [], id: \.code) { Note(strings.warningText($0), tone: .warn).padding(.top, 6) }
            if let version, actions.open {
                answers(actions, version, paused: listing?.status == .paused).padding(.top, 8)
            }
        }
    }

    /// The offer the booking was made from: not "closed", the agreed one.
    private var accepted: Bool { thread.state == "accepted" }

    private var title: String {
        switch style {
        case .listing: strings.driverLabel(thread)
        case .proposals: listing.map(strings.route) ?? strings.driverLabel(thread)
        }
    }

    private func sub(_ actions: NegotiationActions) -> String? {
        guard let version = thread.currentVersion else { return nil }
        if accepted && style == .listing { return strings.t("status.accepted") }
        if !actions.open && style == .listing {
            return strings.t("listingBids.closed", ("status", strings.t(thread.closedStatusKey(now: now))))
        }
        switch style {
        case .listing:
            return "\(strings.endName(stop: version.pickupStop, point: version.pickupPoint)) → \(strings.endName(stop: version.dropoffStop, point: version.dropoffPoint))"
        case .proposals:
            return "\(strings.driverLabel(thread)) · \(strings.windowDays(version.pickupWindowStart, version.pickupWindowEnd))"
        }
    }

    private func lines(_ actions: NegotiationActions) -> [ItemLine] {
        guard let version = thread.currentVersion else { return [] }
        var out: [ItemLine] = []
        if style == .listing && actions.open { out.append(.init(strings.window(version.pickupWindowStart, version.pickupWindowEnd))) }
        if style == .listing, let summary = thread.driverSummary { out.append(.init(strings.driverSummary(summary))) }
        if style == .proposals {
            if accepted {
                out.append(.init(strings.t("status.accepted"), tone: .ok))
            } else if !actions.open {
                out.append(.init(strings.t("proposals.closed", ("status", strings.t(thread.closedStatusKey(now: now))))))
            } else {
                out.append(.init(strings.t(actions.theirTurn ? "negotiation.driverCountered" : "negotiation.waitingForAnswer"),
                                 tone: actions.theirTurn ? .warn : nil))
            }
        }
        if actions.open, let message = version.message, !message.isEmpty { out.append(.init(message)) }
        if actions.open && actions.canWithdraw && style == .listing { out.append(.init(strings.t("listingBids.awaitingDriver"))) }
        if actions.open, let left = strings.expiresIn(version, now: now) { out.append(.init(left, tone: .warn)) }
        return out
    }

    /// A paused listing takes no counter and no accept (`LISTING_NOT_OPEN`); refusing or taking back still works.
    @ViewBuilder
    private func answers(_ actions: NegotiationActions, _ version: ProposalVersionDTO, paused: Bool) -> some View {
        let busy = offers.busy == thread.id
        let canCounter = actions.canCounter && !paused
        VStack(spacing: 8) {
            if actions.theirTurn && paused {
                ElchiButton(strings.t("proposal.reject"), variant: .dangerSoft, size: .pair, loading: busy) {
                    Task { _ = await offers.reject(thread) }
                }
            } else if actions.theirTurn {
                if counterOpen {
                    CounterForm(thread: thread, version: version, listingId: thread.listingId, offers: offers, onClose: { onCounter(false) })
                } else {
                    if let quote = OfferThreads.clientQuote(version) {
                        MoneyLines(rows: [
                            MoneyLines.Row(strings.t("promo.line.offerPrice"), strings.money(quote.fareMinor)),
                            MoneyLines.Row(strings.t("promo.line.bonusDiscount"), "−\(strings.money(quote.passengerDiscountMinor))", tone: .ok),
                            MoneyLines.Row(strings.t("promo.line.cashToDriver"), strings.money(quote.cashDueMinor), emphasis: true),
                        ], check: strings.t("promoScreen.useBonusShort", ("amount", strings.money(quote.passengerDiscountMinor))),
                           checked: Binding(get: { offers.useBonus[thread.id] == true }, set: { offers.useBonus[thread.id] = $0 }))
                    }
                    ElchiButton(strings.t(style == .listing ? "listingBids.chooseDriver" : "proposals.acceptDriverPrice"), action: onAccept)
                    let reject = ElchiButton(strings.t("proposal.reject"), variant: .dangerSoft, size: .pair, loading: busy) {
                        Task { _ = await offers.reject(thread) }
                    }
                    if canCounter {
                        // "Boshqa narx (N marta qoldi)" is the long one: it gets the wider share of the row.
                        GeometryReader { geometry in
                            HStack(spacing: 8) {
                                reject.frame(width: (geometry.size.width - 8) * 0.38)
                                ElchiButton(strings.t("client.listingBids.counterShort", ("count", actions.revisionsLeft)), variant: .neutral,
                                            size: .pair) {
                                    offers.clearError(thread.id)
                                    onCounter(true)
                                }
                            }
                        }
                        .frame(height: ButtonSize.pair.height)
                    } else {
                        reject
                    }
                    if !actions.canCounter {
                        Text(strings.t("listingBids.noRevisionsLeft")).font(ElchiFont.caption).foregroundStyle(c.muted)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            } else if actions.canWithdraw {
                ElchiButton(strings.t("proposals.withdraw"), variant: .neutral, size: .pair, loading: busy) {
                    Task { _ = await offers.withdraw(thread) }
                }
            }
        }
        .disabled(offers.busy != nil && !busy)
    }
}

/// "Boshqa narx": the client's price for this offer (a parcel request sends only the price). Before sending, the
/// server says what the client's own bonus would do to it - or, plainly, why there is none.
private struct CounterForm: View {
    let thread: ProposalThreadDTO
    let version: ProposalVersionDTO
    let listingId: String
    let offers: OfferThreads
    let onClose: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var priceText = ""
    @State private var digits = ""
    @State private var preview: PromoPreviewDTO?
    @State private var useBonus = false

    var body: some View {
        let priceMinor = Money.minor(fromSoum: digits)
        let quote = preview?.quote.flatMap { $0.passengerDiscountMinor > 0 ? $0 : nil }
        VStack(alignment: .leading, spacing: 10) {
            if let reason = preview?.noDiscountReason, quote == nil, let text = strings.tOrNil(noDiscountKey(reason)) {
                Note(text, tone: .gray, title: strings.t("promoScreen.whyNoDiscount"))
            }
            ElchiField(text: $priceText, label: strings.t("listingBids.yourPrice"), hint: hint(priceMinor, quote), keyboard: .numberPad)
                .onChange(of: priceText) { _, typed in
                    // Local text re-synced after every edit: SwiftUI's TextField ignores a binding that rewrites the input.
                    digits = Money.soumDigits(typed)
                    let formatted = Money.grouped(digits)
                    if priceText != formatted { priceText = formatted }
                }
            if let quote {
                MoneyLines(rows: [
                    MoneyLines.Row(strings.t("promo.line.offerPrice"), strings.money(quote.fareMinor)),
                    MoneyLines.Row(strings.t("promo.line.bonusDiscount"), "−\(strings.money(quote.passengerDiscountMinor))", tone: .ok),
                    MoneyLines.Row(strings.t("promo.line.cashToDriver"), strings.money(quote.cashDueMinor), emphasis: true),
                ], check: strings.t("promoScreen.useBonusShort", ("amount", strings.money(quote.passengerDiscountMinor))), checked: $useBonus)
            }
            HStack(spacing: 8) {
                ElchiButton(strings.t("common.send"), size: .pair, loading: offers.busy == thread.id) {
                    Task {
                        if await offers.counter(thread, priceMinor: priceMinor, consent: useBonus ? quote : nil) { onClose() }
                    }
                }
                .disabled(priceMinor <= 0)
                ElchiButton(strings.t("common.cancel"), variant: .neutral, size: .pair, action: onClose)
            }
        }
        .onAppear {
            digits = String(version.totalMinor / 100)
            priceText = Money.grouped(digits)
        }
        .task(id: priceMinor) {
            // Debounced: the preview follows the typed price; a new price unticks the bonus (the person agrees again).
            useBonus = false
            guard priceMinor > 0 else { preview = nil; return }
            try? await Task.sleep(for: .milliseconds(400))
            if Task.isCancelled { return }
            preview = try? await offers.promoPreview(listingId: listingId, unitPriceMinor: priceMinor, quantity: version.quantity)
        }
    }

    private func hint(_ priceMinor: Int, _ quote: ProposalPromoClientDTO?) -> String {
        let total = version.priceBasis == .total ? priceMinor : priceMinor * max(version.quantity, 1)
        let base = "\(strings.t("common.total")): \(strings.money(total))"
        return quote == nil ? base : "\(base) · \(strings.t("client.listingBids.bonusOptIn"))"
    }

    private func noDiscountKey(_ reason: String) -> String {
        let keys = ["service_not_eligible": "serviceNotEligible", "bonus_expired": "bonusExpired", "bonus_reserved": "bonusReserved",
                    "bonus_on_hold": "bonusOnHold", "no_campaign": "noCampaign", "client_update_required": "clientUpdateRequired",
                    "trip_terms": "tripTerms"]
        return "promo.noDiscount.\(keys[reason] ?? reason)"
    }
}

// MARK: - Haydovchini tanlash

/// "Haydovchi #3 ni tanlaysizmi?" - accepting is never one tap. The agreed total is the version's own (never
/// recomputed); bonus lines only when the person ticked the server's bonus quote.
struct AcceptDialog: View {
    let thread: ProposalThreadDTO
    let offers: OfferThreads
    let onClose: () -> Void
    let onAccepted: (ClientBookingDTO) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        let version = thread.currentVersion
        let quote = version.flatMap { offers.useBonus[thread.id] == true ? OfferThreads.clientQuote($0) : nil }
        let working = offers.busy == thread.id
        DialogOverlay(dismissLabel: strings.t("confirmDialog.back"), onDismiss: { if !working { onClose() } }) {
            VStack(alignment: .leading, spacing: 4) {
                Text(thread.driverNumber.map { strings.t("client.accept.title", ("number", $0)) } ?? strings.t("confirmDialog.selectDriver.title"))
                    .font(ElchiFont.poppins(19, .medium, relativeTo: .title2)).foregroundStyle(c.text)
                    .accessibilityAddTraits(.isHeader)
                Text(strings.t("client.accept.text")).font(ElchiFont.secondary).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
            }
            if let version {
                MoneyLines(rows: quote.map { quote in
                    [MoneyLines.Row(strings.t("promo.line.agreedPrice"), strings.money(version.totalMinor)),
                     MoneyLines.Row(strings.t("promo.line.bonusDiscount"), "−\(strings.money(quote.passengerDiscountMinor))", tone: .ok),
                     MoneyLines.Row(strings.t("promo.line.cashToDriver"), strings.money(quote.cashDueMinor), emphasis: true)]
                } ?? [MoneyLines.Row(strings.t("promo.line.agreedPrice"), strings.money(version.totalMinor), emphasis: true)])
            }
            ElchiButton(strings.t("client.accept.confirm"), loading: working) {
                Task {
                    // A refusal closes the dialog: the offer card below shows why, in its current state.
                    if let booking = await offers.accept(thread) { onAccepted(booking) } else { onClose() }
                }
            }
            ElchiButton(strings.t("confirmDialog.back"), variant: .neutral, size: .medium, action: onClose).disabled(working)
        }
        .onAppear { offers.clearError(thread.id) }
    }
}
