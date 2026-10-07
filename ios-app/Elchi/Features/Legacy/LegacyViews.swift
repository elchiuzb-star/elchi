import SwiftUI

// MARK: - Buyurtma tafsilotlari (v1 archive)

/// One v1 order (Q4): the archive note, the order card, addresses, the client's own contacts, the cargo photo, the
/// driver (phone from `accepted` on, v1's own rule), the map points, then what the status still allows. Never create,
/// edit or publish. Refreshed on every return from its sub-screens.
struct LegacyOrderDetailView: View {
    let model: LegacyOrderModel
    let onBack: () -> Void
    let onBids: () -> Void
    let onRate: () -> Void
    /// "Muammo haqida xabar berish" (USER DECISION, Q141): Yordam with a ticket about this order; no dispute form.
    let onReport: (LegacyOrderDetail) -> Void
    /// Cancelled: back to the refreshed list.
    let onCancelled: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(\.openURL) private var openURL
    @State private var sheet: Sheet?

    private enum Sheet: String, Identifiable {
        case confirm, cancel, map
        var id: String { rawValue }
    }

    var body: some View {
        ScreenScaffold(title: strings.t("orders.detailTitle"), backLabel: strings.t("common.back"), onBack: onBack) {
            if model.notFound {
                NotFoundState(title: strings.t("driverProfile.notFound"), description: strings.t("client.v3archive.notFoundHint"),
                              backLabel: strings.t("common.back"), onBack: onBack)
            } else {
                switch model.order {
                case .loading:
                    Note(strings.t("client.legacy.archiveNote"), tone: .gray)
                    LoadingState()
                case .failed(let error):
                    Note(strings.bannerErrorText(error), tone: .err)
                    ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.load() } }
                case .loaded(let order):
                    content(order)
                }
            }
        } footer: {
            EmptyView()
        }
        .refreshable { await model.load() }
        .onAppear { Task { await model.load() } }
        .sheet(item: $sheet) { which in
            if let order = model.order.value {
                switch which {
                case .confirm: confirmSheet
                case .cancel: cancelSheet(order)
                case .map: LegacyMapSheet(order: order)
                }
            }
        }
    }

    @ViewBuilder
    private func content(_ order: LegacyOrderDetail) -> some View {
        let actions = LegacyActions.of(order.status, rated: model.rated)
        Note(strings.t("client.legacy.archiveNote"), tone: .gray)
        // BOSQICH 10 2.2: one line "number · dd.MM.yyyy", no icon (as Android and the design).
        ItemCard(title: strings.route(order), badge: strings.status(.legacy(order.status)),
                 meta: LegacyListMeta.line(orderNumber: order.orderNumber, createdAt: order.createdAt), right: order.priceMinor.map(strings.money))
        // BOSQICH 10 2.3: "Olib ketish" / "Yetkazish", like Android and the design.
        ElchiCard {
            CardRow(strings.t("routeSummary.pickup"), strings.legacyPlace(order.pickupAddress, order.fromDistrict), first: true)
            CardRow(strings.t("routeSummary.dropoff"), strings.legacyPlace(order.dropoffAddress, order.toDistrict))
        }
        parties(order)
        photo
        driver(order)
        if order.pickup != nil || order.dropoff != nil {
            // BOSQICH 10 2.4: a white pill with the pin.
            ElchiButton(strings.t("orders.mapPoints"), variant: .neutral, size: .medium, icon: .pin) { sheet = .map }
                .accessibilityHint(strings.markedLine(order))
                .accessibilityIdentifier("elchi.legacy.mapPoints")
        }
        if let stars = model.ratedStars {
            // BOSQICH 10 2.8: what was just sent, for this session (v1 has no rating field to show it later).
            Note(strings.t("client.v3archive.ratedNote", ("stars", "\(String(repeating: "★", count: stars)) (\(stars) / 5)")), tone: .ok)
        }
        if actions.viewBids {
            ElchiButton(bidsLabel(order), variant: .soft, icon: .tag, action: onBids)
        }
        if actions.confirm {
            ElchiButton(strings.t("orders.confirmDelivered"), icon: .checkC) { sheet = .confirm }
                .disabled(model.running != nil)
        }
        if actions.rate {
            ElchiButton(strings.t("rating.rateDriver"), action: onRate)
        }
        if actions.report && actions.cancel {
            // The design's pair: report (neutral) and cancel (danger), side by side.
            HStack(spacing: 8) {
                ElchiButton(strings.t("orders.reportProblem"), variant: .neutral, size: .pair) { onReport(order) }
                ElchiButton(strings.t("common.cancel"), variant: .dangerSoft, size: .pair) { sheet = .cancel }
                    .accessibilityLabel(strings.t("orders.cancel"))
                    .frame(width: 128) // the report label is the long one: it gets the rest of the row
            }
            .disabled(model.running != nil)
        } else if actions.report {
            ElchiButton(strings.t("orders.reportProblem"), variant: .neutral, icon: .alert) { onReport(order) }
        } else if actions.cancel {
            ElchiButton(strings.t("orders.cancel"), variant: .dangerSoft) { sheet = .cancel }
                .disabled(model.running != nil)
        }
    }

    private func bidsLabel(_ order: LegacyOrderDetail) -> String {
        let count = order.bidsCount ?? 0
        return count > 0 ? strings.t("client.listingDetail.viewOffers", ("count", count)) : strings.t("orders.viewBids")
    }

    @ViewBuilder
    private func parties(_ order: LegacyOrderDetail) -> some View {
        let comment = order.comment?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if order.senderPhone != nil || order.receiverPhone != nil || !comment.isEmpty {
            ElchiCard {
                CardRow(strings.t("orderForm.review.sender"), order.senderPhone.map(UzPhone.display) ?? strings.t("orderForm.review.noPhone"),
                        first: true, placeholder: order.senderPhone == nil)
                CardRow(strings.t("orderForm.review.receiver"), order.receiverPhone.map(UzPhone.display) ?? strings.t("orderForm.review.noPhone"),
                        placeholder: order.receiverPhone == nil)
                if !comment.isEmpty { CardRow(strings.t("listingOwner.commentLabel"), comment) }
            }
        }
    }

    @ViewBuilder
    private var photo: some View {
        if let url = model.photoURL {
            // A short-lived signed link (Q6): when it has expired, pulling to refresh fetches a new one.
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
            .accessibilityLabel(strings.t("app.photo.alt"))
        }
    }

    /// Name, car and plate, the rating (none shown for an unrated driver - never an invented number), and the phone
    /// with "Qo'ng'iroq qilish" once the driver is chosen.
    @ViewBuilder
    private func driver(_ order: LegacyOrderDetail) -> some View {
        if let driver = order.assignedDriver {
            ElchiCard {
                CardRow(strings.t("safety.driverTitle"), driver.fullName ?? "—", first: true, detail: strings.legacyRatingLine(driver.rating))
                if let car = strings.legacyCar(driver.carModel, driver.plateNumber) {
                    CardRow(strings.t("addRoute.vehicle"), car)
                }
                if LegacyPhone.visible(order.status), let phone = driver.phone, !phone.isEmpty {
                    CardRow(strings.t("driverBooking.phone"), UzPhone.display(phone), trailing: strings.t("client.legacy.call")) {
                        if let url = LegacyPhone.dialURL(phone) { openURL(url) }
                    }
                }
            }
        }
    }

    // MARK: Sheets

    private var confirmSheet: some View {
        LegacyConfirmSheet(title: strings.t("confirmDialog.confirmDelivery.title"), text: strings.t("confirmDialog.confirmDelivery.text"),
                           confirm: strings.t("client.legacy.confirmDeliveryYes"), variant: .primary, working: model.running == .confirm,
                           onConfirm: {
                               Task {
                                   if await model.confirmDelivery() {
                                       sheet = nil
                                       onRate()
                                   }
                               }
                           }, onBack: { sheet = nil })
    }

    private func cancelSheet(_ order: LegacyOrderDetail) -> some View {
        LegacyConfirmSheet(title: strings.t("confirmDialog.cancelOrder.title"), text: strings.t(LegacyActions.of(order.status).cancelTextKey),
                           confirm: strings.t("bookingCancel.confirm"), variant: .danger, working: model.running == .cancel,
                           onConfirm: {
                               // The stored reason is Uzbek text whatever the app's language (the web client's too).
                               let reason = strings.uzbek("client.legacy.cancelReason")
                               Task {
                                   if await model.cancel(reason: reason) {
                                       sheet = nil
                                       onCancelled()
                                   } else {
                                       sheet = nil
                                   }
                               }
                           }, onBack: { sheet = nil })
    }
}

// MARK: - Confirm sheet

/// The v1 ConfirmSheet: a question, one line, the action and "Ortga". The action spins while it runs; the result (or
/// the refusal) is said by the app's banner.
struct LegacyConfirmSheet: View {
    let title: String
    let text: String
    let confirm: String
    let variant: ButtonVariant
    let working: Bool
    let onConfirm: () -> Void
    let onBack: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 6) {
                Text(title).font(ElchiFont.poppins(20, .medium, relativeTo: .title2)).foregroundStyle(c.text)
                    .accessibilityAddTraits(.isHeader)
                Text(text).font(ElchiFont.secondary).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
            }
            ElchiButton(confirm, variant: variant, loading: working, action: onConfirm)
                .accessibilityIdentifier("elchi.sheet.confirm")
            ElchiButton(strings.t("confirmDialog.back"), variant: .neutral, action: onBack).disabled(working)
                .accessibilityIdentifier("elchi.sheet.back")
            Spacer(minLength: 0)
        }
        .padding(EdgeInsets(top: 28, leading: 20, bottom: 12, trailing: 20))
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(c.card.ignoresSafeArea())
        .presentationDetents([.height(280)])
        .presentationCornerRadius(ElchiShape.sheet)
        .presentationDragIndicator(.visible)
        .interactiveDismissDisabled(working)
    }
}

// MARK: - Xarita nuqtalari

/// The two ends on a small still map (origin ring, destination pin, fitted; one point: centred on it) - v1 has no
/// route line (Q159: no invented geometry). BOSQICH 10: "Olib ketish" / "Yetkazish" tabs (a missing end has none), a
/// grey card with the chosen end's address and coordinates, one "open in Yandex" button that follows the tab (the
/// dropoff keeps the route from here, the old app's behaviour), then "Yopish".
struct LegacyMapSheet: View {
    let order: LegacyOrderDetail
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(\.openURL) private var openURL
    @Environment(\.dismiss) private var dismiss
    @State private var selected: LegacyMapPoints.End?

    var body: some View {
        let markers = [order.pickup.map { MapMarker($0, .origin) }, order.dropoff.map { MapMarker($0, .destination) }].compactMap { $0 }
        let ends = LegacyMapPoints.ends(pickup: order.pickup, dropoff: order.dropoff)
        let end = selected.flatMap { ends.contains($0) ? $0 : nil } ?? ends.first
        VStack(alignment: .leading, spacing: 14) {
            Text(strings.t("mapSheet.title")).font(ElchiFont.poppins(20, .medium, relativeTo: .title2)).foregroundStyle(c.text)
                .accessibilityAddTraits(.isHeader)
            ElchiMap(markers: markers, focus: markers.count == 1 ? markers[0].point : nil, zoom: 14, interactive: false,
                     placeholder: strings.markedLine(order))
                .frame(height: 190)
                .clipShape(RoundedRectangle(cornerRadius: 20))
                .accessibilityIdentifier("elchi.legacy.map")
            if ends.count > 1 {
                Segmented(ends.map { ($0, strings.t($0 == .pickup ? "routeSummary.pickup" : "routeSummary.dropoff")) },
                          selected: end ?? .pickup) { selected = $0 }
                    .accessibilityIdentifier("elchi.legacy.mapTabs")
            }
            if let end, let point = end == .pickup ? order.pickup : order.dropoff {
                VStack(alignment: .leading, spacing: 4) {
                    Text(strings.t(end == .pickup ? "orderForm.review.pickupPlace" : "orderForm.review.dropoffPlace"))
                        .font(ElchiFont.caption).foregroundStyle(c.muted)
                    Text(end == .pickup ? strings.legacyPlace(order.pickupAddress, order.fromDistrict)
                                        : strings.legacyPlace(order.dropoffAddress, order.toDistrict))
                        .font(ElchiFont.poppins(14, .semibold)).foregroundStyle(c.text).fixedSize(horizontal: false, vertical: true)
                    Text(LegacyMapPoints.coordinates(point)).font(.system(size: 12.5, design: .monospaced)).foregroundStyle(c.muted)
                        .textSelection(.enabled)
                }
                .padding(.horizontal, 14).padding(.vertical, 12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(c.field, in: RoundedRectangle(cornerRadius: 16))
                .accessibilityElement(children: .combine)
                if end == .pickup {
                    ElchiButton(strings.t("mapSheet.openPickup"), variant: .soft, icon: .pin) { openURL(YandexMapLinks.point(point)) }
                } else {
                    ElchiButton(strings.t("client.v3archive.openDropoff"), variant: .soft, icon: .nav) { openURL(YandexMapLinks.route(to: point)) }
                }
            }
            ElchiButton(strings.t("common.close"), variant: .neutral) { dismiss() }
                .accessibilityIdentifier("elchi.legacy.mapClose")
            Spacer(minLength: 0)
        }
        .padding(EdgeInsets(top: 28, leading: 20, bottom: 12, trailing: 20))
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(c.card.ignoresSafeArea())
        .presentationDetents([.height(ends.count > 1 ? 640 : 580), .large])
        .presentationCornerRadius(ElchiShape.sheet)
        .presentationDragIndicator(.visible)
    }
}

// MARK: - Haydovchi takliflari (v1)

/// The bids on a v1 order, cheapest first: name, car · plate · rating, price and "Tanlash" (confirm sheet). Closed
/// once the order has left bidding; empty says so; a refused choice reloads the list.
struct LegacyBidsView: View {
    let model: LegacyOrderModel
    let onBack: () -> Void
    /// A driver was chosen: back to the detail (it reloads and shows the driver and the phone).
    let onSelected: () -> Void
    @Environment(LocaleStore.self) private var strings
    @State private var choosing: LegacyBid?

    var body: some View {
        ScreenScaffold(title: strings.t("listingBids.title"), backLabel: strings.t("common.back"), onBack: onBack) {
            if model.notFound {
                NotFoundState(title: strings.t("driverProfile.notFound"), description: strings.t("client.v3archive.notFoundHint"),
                              backLabel: strings.t("common.back"), onBack: onBack)
            } else if let order = model.order.value, !LegacyActions.bidsOpen(order.status) {
                Note(strings.t("client.legacy.archiveNote"), tone: .gray)
                Note(strings.t("client.legacy.bidsClosed"), tone: .gray)
            } else {
                Note(strings.t("client.legacy.archiveNote"), tone: .gray)
                switch model.bids {
                case .loading:
                    LoadingState()
                case .failed(let error):
                    Note(strings.bannerErrorText(error), tone: .err)
                    ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.loadBidsScreen() } }
                case .loaded(let bids):
                    if bids.isEmpty {
                        if model.order.value?.status == "published" {
                            EmptyState(icon: .tag, title: strings.t("orders.noBids"), description: strings.t("orders.noBidsHint"))
                        } else {
                            EmptyState(icon: .tag, title: strings.t("listingBids.emptyTitle"), description: strings.t("listingBids.emptySubtitle"))
                        }
                    }
                    ForEach(bids) { bid in row(bid) }
                }
            }
        } footer: {
            EmptyView()
        }
        .refreshable { await model.loadBidsScreen() }
        .task { await model.loadBidsScreen() }
        .sheet(item: $choosing) { bid in
            // BOSQICH 10 4.3: who and for how much, then "Ha, tanlayman".
            LegacyConfirmSheet(title: strings.t("confirmDialog.selectDriver.title"),
                               text: strings.t("client.v3archive.selectDriverText", ("name", bid.driver?.fullName ?? "—"),
                                               ("price", bid.priceMinor.map(strings.money) ?? "—")),
                               confirm: strings.t("client.accept.confirm"), variant: .primary, working: model.selecting == bid.id,
                               onConfirm: {
                                   Task {
                                       let done = await model.select(bid)
                                       choosing = nil
                                       if done { onSelected() }
                                   }
                               }, onBack: { choosing = nil })
        }
    }

    private func row(_ bid: LegacyBid) -> some View {
        let line = strings.legacyBidLine(bid)
        return ItemCard(title: bid.driver?.fullName ?? "—", icon: .user, sub: line.text, right: bid.priceMinor.map(strings.money)) {
            ElchiButton(strings.t("confirmDialog.selectDriver.confirm"), size: .medium, loading: model.selecting == bid.id) { choosing = bid }
                .disabled(model.running != nil)
                .padding(.top, 6)
        }
        .accessibilityElement(children: .contain)
        .accessibilityHint(line.spoken)
    }
}

// MARK: - Haydovchini baholang (v1)

struct LegacyRatingView: View {
    let model: LegacyOrderModel
    let onBack: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var stars = 0
    @State private var comment = ""

    var body: some View {
        ScreenScaffold(title: strings.t("rating.titleDriver"), backLabel: strings.t("common.back"), onBack: onBack) {
            Note(strings.t("client.legacy.archiveNote"), tone: .gray)
            if let name = model.order.value?.assignedDriver?.fullName {
                Text(name).font(ElchiFont.poppins(18, .medium, relativeTo: .title3)).foregroundStyle(c.text)
                    .multilineTextAlignment(.center).frame(maxWidth: .infinity).padding(.top, 12)
                    .accessibilityAddTraits(.isHeader)
            }
            StarsInput(value: $stars) { strings.t("legacyOrder.stars", ("value", $0)) }
            Text(strings.t("legacyOrder.ratingHint")).font(ElchiFont.caption).foregroundStyle(c.muted).frame(maxWidth: .infinity)
            ElchiField(text: $comment, label: strings.t("legacyOrder.ratingComment"), hint: strings.t("bookingChat.autoMaskNote"), multiline: true)
                // BOSQICH 10 5.5: the design's 300-character cap.
                .onChange(of: comment) { _, value in if value.count > 300 { comment = String(value.prefix(300)) } }
        } footer: {
            ElchiButton(strings.t("legacyOrder.ratingSubmit"), loading: model.running == .rate) {
                Task { if await model.rate(stars: stars, comment: comment) { onBack() } }
            }
            .disabled(stars == 0 || model.running != nil)
            ElchiButton(strings.t("legacyOrder.later"), variant: .ghost, size: .medium, action: onBack)
        }
    }
}

// MARK: - Wording

extension LocaleStore {
    /// `Toshkent shahri → Samarqand viloyati` (v1 city names are Uzbek only).
    func route(_ order: LegacyOrderDetail) -> String {
        "\(order.fromCity?.nameUz ?? order.fromDistrict?.nameUz ?? "?") → \(order.toCity?.nameUz ?? order.toDistrict?.nameUz ?? "?")"
    }

    /// The street address, else the district, else "not marked".
    func legacyPlace(_ address: String?, _ district: LegacyOrder.District?) -> String {
        if let address, !address.trimmingCharacters(in: .whitespaces).isEmpty { return address }
        if let district { return (locale == .ru ? district.nameRu : nil) ?? district.nameUz ?? "—" }
        return "—"
    }

    /// `Olib ketish joyi belgilangan · Yetkazish joyi belgilanmagan`.
    func markedLine(_ order: LegacyOrderDetail) -> String {
        [t(order.pickup != nil ? "orders.pickupMarked" : "orders.pickupNotMarked"),
         t(order.dropoff != nil ? "orders.dropoffMarked" : "orders.dropoffNotMarked")].joined(separator: " · ")
    }

    /// `Nexia 3 · 10 C 207 TA`.
    func legacyCar(_ model: String?, _ plate: String?) -> String? {
        let parts = [model, plate].compactMap { $0?.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// `★ 4,6`, or "Hali baholanmagan".
    func legacyRatingLine(_ rating: JSONValue?) -> String {
        LegacyRating.text(rating).map { "★ \($0)" } ?? t("listingBids.noRatingsYet")
    }

    /// A bid's second line as shown (`Nexia 3 · 10 C 207 TA · ★ 4,6`) and as spoken (`Reyting: 4,6`).
    func legacyBidLine(_ bid: LegacyBid) -> (text: String, spoken: String) {
        let rating = LegacyRating.text(bid.driver?.rating)
        let parts = [legacyCar(bid.driver?.carModel, bid.driver?.plateNumber), Optional(legacyRatingLine(bid.driver?.rating))].compactMap { $0 }
        return (parts.joined(separator: " · "), rating.map { t("legacyOrder.rating", ("rating", $0)) } ?? t("listingBids.noRatingsYet"))
    }

    /// A dictionary sentence in Uzbek whatever the app's language (text the server stores as it is).
    func uzbek(_ key: String) -> String {
        Bundle.main.path(forResource: "uz", ofType: "lproj").flatMap(Bundle.init(path:))?
            .localizedString(forKey: key, value: nil, table: nil) ?? t(key)
    }
}
