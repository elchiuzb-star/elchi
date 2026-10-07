import SwiftUI

/// "E'lon tafsiloti" (Safar v3 §6): one request opened from the direction feed or the home list, read from memory
/// (no extra request). The header (kind, route, window, match, "Mijoz narxi"), the driver's own offer, the rows
/// (Olib ketish, Yetkazish, Sana, Vaqt oralig'i, Jo'natma, the car's ETA), the rival board (Q95), and the footer:
/// "Taklif yuborish" - or, once offered, "Taklifni ko'rish" (the thread, Q100). Not shown: the usual price band (no
/// driver endpoint) and the parcel photo (Q6: the assigned driver only).
struct DriverListingDetailView: View {
    let model: DirectionOfferModel
    let mark: FeedOfferMark
    let onBack: () -> Void
    let onOffer: () -> Void
    let onThread: (String) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        let item = model.item
        let listing = model.listing
        let thread = mark.threadId ?? item.myThreadId
        ScreenScaffold(title: strings.t("driver.v3trip.listingTitle"), backLabel: strings.t("common.back"), onBack: onBack) {
            header(item)
            if let banner = mineText {
                Text(banner).font(ElchiFont.poppins(13.5, .semibold)).foregroundStyle(c.softText)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 16).padding(.vertical, 12)
                    .background(c.soft, in: RoundedRectangle(cornerRadius: 18))
                    .accessibilityIdentifier("elchi.listing.mine")
            }
            ElchiCard {
                ForEach(Array(rows(item).enumerated()), id: \.offset) { index, row in
                    CardRow(row.0, row.1, first: index == 0)
                }
            }
            .accessibilityIdentifier("elchi.listing.rows")
            if listing.serviceType == .parcel {
                Text(strings.t("driver.v3trip.photoAfterBooking")).font(ElchiFont.caption).foregroundStyle(c.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            RivalBoardCard(board: model.board)
        } footer: {
            if let thread {
                ElchiButton(strings.t("driver.feed.viewOffer"), variant: .neutral) { onThread(thread) }
                    .accessibilityIdentifier("elchi.listing.viewOffer")
            } else {
                BrandButton(title: strings.t("driverFeed.sendOffer"), action: onOffer)
                    .accessibilityIdentifier("elchi.listing.offer")
            }
        }
        .task { await model.loadBoard() }
    }

    private func header(_ item: DirectionRequestItemDTO) -> some View {
        let listing = item.listing
        let perSeat = PassengerMoney.perSeat(listing.priceBasis)
        return VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 12) {
                ListingKindIcon.of(listing).image(size: 20).foregroundStyle(c.accentText)
                    .frame(width: 44, height: 44)
                    .background(c.iconTint, in: Circle())
                VStack(alignment: .leading, spacing: 2) {
                    Text(strings.route(listing)).font(ElchiFont.poppins(17, .semibold)).foregroundStyle(c.text)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(strings.span(listing.departureWindowStart, listing.departureWindowEnd)).font(ElchiFont.poppins(12.5)).foregroundStyle(c.muted)
                }
            }
            HStack(alignment: .center, spacing: 10) {
                if let tag = strings.matchTag(item) {
                    Text(tag.text).font(ElchiFont.poppins(12, .semibold)).foregroundStyle(c.tone(tag.tone).fg).lineLimit(1)
                        .padding(.horizontal, 12).padding(.vertical, 5)
                        .background(c.tone(tag.tone).bg, in: Capsule())
                }
                Spacer(minLength: 0)
                VStack(alignment: .trailing, spacing: 0) {
                    Text(strings.t("driver.v3trip.clientPriceLabel")).font(ElchiFont.poppins(11.5)).foregroundStyle(c.muted)
                    Text(strings.money(listing.totalMinor)).font(ElchiFont.poppins(22, .semibold)).foregroundStyle(c.text).lineLimit(1)
                    if perSeat {
                        Text(strings.seatsTotal(max(listing.quantity, 1), unitMinor: listing.unitPriceMinor)).font(ElchiFont.caption)
                            .foregroundStyle(c.muted)
                    }
                }
                .accessibilityElement(children: .combine)
            }
        }
        .padding(16)
        .background(c.card, in: RoundedRectangle(cornerRadius: 22))
        .shadow(color: c.softShadow, radius: 12, y: 6)
        .accessibilityIdentifier("elchi.listing.header")
    }

    /// Safar 6.2: "Sizning taklifingiz: {price}" / "Mijoz qabul qildi" (the price is not on the accepted mark).
    private var mineText: String? {
        switch mark {
        case .offered(_, let total): strings.t("offerBid.yourOffer", ("price", strings.money(total)))
        case .countered: strings.t("negotiation.clientCountered")
        case .accepted: strings.t("driver.feed.clientAccepted")
        case .none: model.item.myThreadId == nil ? nil : strings.t("dir.card.myOffer")
        }
    }

    private func rows(_ item: DirectionRequestItemDTO) -> [(String, String)] {
        let listing = item.listing
        var out: [(String, String)] = [
            (strings.t("routeSummary.pickup"), strings.placeText(listing.originPoint)),
            (strings.t("routeSummary.dropoff"), strings.placeText(listing.destinationPoint)),
        ]
        if let start = ServerTime.parse(listing.departureWindowStart) {
            out.append((strings.t("publicShare.date"), strings.dayMonth(start)))
        }
        out.append((strings.t("driver.v3trip.timeWindow"),
                    "\(DirectionFeed.clock(listing.departureWindowStart)) – \(DirectionFeed.clock(listing.departureWindowEnd))"))
        if listing.serviceType == .passenger {
            out.append((strings.t("client.taxi.seats"), strings.t("seatPicker.peopleCount", ("count", max(listing.quantity, 1)))))
        } else if let parcel = strings.parcelLine(listing) {
            out.append((strings.t("tripDetail.parcel"), parcel))
        }
        if let eta = item.pickupEta {
            out.append((strings.t("driverBid.pickupWindow"), DirectionFeed.dayClock(eta)))
        }
        if item.fit == "no_trip", let departure = item.suggestedDepartureAt {
            out.append((strings.t("tripDetail.departure"), DirectionFeed.dayClock(departure)))
        }
        return out
    }
}

/// The design's brand button (azure with navy text): the feed's and the listing detail's "Taklif yuborish".
struct BrandButton: View {
    let title: String
    var height: CGFloat = 56
    let action: () -> Void
    @Environment(\.elchi) private var c

    var body: some View {
        Button(action: action) {
            Text(title).font(height >= 56 ? ElchiFont.button : ElchiFont.buttonSmall).lineLimit(1)
                .foregroundStyle(c.onBrand)
                .frame(maxWidth: .infinity).frame(height: height)
                .background(c.brand, in: Capsule())
                .contentShape(Capsule())
        }
        .buttonStyle(PressFade())
    }
}
