import SwiftUI

// MARK: - Header (Royxat 1.1, Safar 1.1)

/// The home's top row instead of an h1 bar: initials avatar (-> Profil), the navy "Balans" pill (-> Komissiya balansi)
/// and the 52 pt grey bell with a dot while something is unread (the count stays in the spoken label).
struct HomeHeaderRow: View {
    let initials: String?
    /// "—" while unread or failed: never a zero nobody measured.
    let balance: String
    let unread: Int
    let unreadMore: Bool
    let onProfile: () -> Void
    let onWallet: () -> Void
    let onBell: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        HStack(spacing: 10) {
            Button(action: onProfile) {
                Group {
                    if let initials {
                        Text(initials).font(ElchiFont.poppins(17, .semibold))
                    } else {
                        ElchiIcon.user.image(size: 22)
                    }
                }
                .foregroundStyle(c.softText)
                .frame(width: 52, height: 52)
                .background(c.soft, in: Circle())
            }
            .buttonStyle(PressFade())
            .accessibilityLabel(strings.t("app.nav.profile"))
            .accessibilityIdentifier("elchi.driver.home.avatar")
            Spacer(minLength: 0)
            Button(action: onWallet) {
                HStack(spacing: 8) {
                    ElchiIcon.wallet.image(size: 18).foregroundStyle(c.navy)
                        .frame(width: 40, height: 40)
                        .background(c.brand, in: Circle())
                    VStack(alignment: .leading, spacing: 0) {
                        Text(strings.t("driver.v3reg.balanceLabel")).font(ElchiFont.poppins(10.5)).foregroundStyle(Color(hex: 0x9FB6D6))
                        Text(balance).font(ElchiFont.poppins(14, .semibold)).foregroundStyle(.white).monospacedDigit().lineLimit(1)
                    }
                }
                .padding(.leading, 6).padding(.trailing, 14)
                .frame(height: 52)
                .background(c.navyBar, in: Capsule())
                .shadow(color: Color(hex: 0x0E2350, opacity: c.isDark ? 0 : 0.25), radius: 10, y: 8)
            }
            .buttonStyle(PressFade())
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(strings.t("driverHome.commissionBalance"))
            .accessibilityValue(balance)
            .accessibilityAddTraits(.isButton)
            .accessibilityIdentifier("elchi.driver.balance")
            Button(action: onBell) {
                ElchiIcon.bell.image(size: 22).foregroundStyle(c.text)
                    .frame(width: 52, height: 52)
                    .background(c.iconFill, in: Circle())
                    .overlay(alignment: .topTrailing) {
                        if unread > 0 {
                            Circle().fill(Color(hex: 0xE0413A)).frame(width: 8, height: 8)
                                .overlay { Circle().strokeBorder(c.iconFill, lineWidth: 2).frame(width: 12, height: 12) }
                                .offset(x: -15, y: 14)
                        }
                    }
            }
            .buttonStyle(PressFade())
            .accessibilityLabel(unread > 0 ? strings.t("driverHome.notificationsUnread", ("count", unreadMore ? "\(unread)+" : "\(unread)"))
                                           : strings.t("notifications.title"))
            .accessibilityIdentifier("elchi.driver.bell")
        }
    }
}

/// "Salom, {name}!" with the round seal (green check approved, amber alert pending, red alert decided); a tap says
/// the state in words.
struct HomeGreeting: View {
    let firstName: String?
    let seal: HomeSeal
    /// The derived word (DESIGN06 1.5) - the decided seal's label and toast.
    let stateWord: String
    let onSeal: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        let tone = c.tone(seal.tone)
        HStack(spacing: 8) {
            Text(firstName.map { strings.t("driver.v3reg.greeting", ("name", $0)) } ?? strings.t("driver.v3reg.greetingNoName"))
                .font(ElchiFont.poppins(27, .semibold, relativeTo: .title)).foregroundStyle(c.text)
                .lineLimit(1).minimumScaleFactor(0.7)
                .accessibilityAddTraits(.isHeader)
            Button(action: onSeal) {
                (seal == .approved ? ElchiIcon.check : ElchiIcon.alert).image(size: 15).foregroundStyle(tone.fg)
                    .frame(width: 26, height: 26)
                    .background(tone.bg, in: Circle())
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(PressFade())
            .padding(.horizontal, -9)
            .accessibilityLabel(seal == .decided ? stateWord : strings.t(seal.labelKey))
            .accessibilityIdentifier("elchi.driver.home.seal")
            Spacer(minLength: 0)
        }
        .accessibilityIdentifier("elchi.driver.home.greeting")
    }
}

// MARK: - Search, chips, filter (Royxat 1.8-1.10)

struct HomeSearchPill: View {
    @Binding var query: String
    let subline: String
    let filterCount: Int
    let onFilter: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        HStack(spacing: 12) {
            ElchiIcon.search.image(size: 22).foregroundStyle(c.muted)
            VStack(alignment: .leading, spacing: 1) {
                TextField("", text: $query, prompt: Text(strings.t("driver.v3reg.searchPlaceholder")).foregroundStyle(c.placeholder))
                    .font(ElchiFont.poppins(15, .semibold)).foregroundStyle(c.text)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                    .submitLabel(.search)
                    .accessibilityLabel(strings.t("driver.v3reg.searchA11y"))
                    .accessibilityIdentifier("elchi.driver.home.search")
                Text(subline).font(ElchiFont.poppins(12)).foregroundStyle(c.placeholder).lineLimit(1)
                    .accessibilityIdentifier("elchi.driver.home.searchSub")
            }
            if !query.isEmpty {
                Button { query = "" } label: {
                    ElchiIcon.x.image(size: 12).foregroundStyle(c.muted)
                        .frame(width: 28, height: 28)
                        .background(c.field, in: Circle())
                        .frame(width: 44, height: 44)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(strings.t("driver.v3reg.clear"))
            }
            Button(action: onFilter) {
                ElchiIcon.sliders.image(size: 20).foregroundStyle(filterCount > 0 ? .white : c.text)
                    .frame(width: 52, height: 52)
                    .background(filterCount > 0 ? c.primaryV3 : c.page, in: Circle())
                    .overlay(alignment: .topTrailing) {
                        if filterCount > 0 {
                            Text("\(filterCount)").font(ElchiFont.poppins(10, .bold)).foregroundStyle(c.navy)
                                .padding(.horizontal, 4)
                                .frame(minWidth: 16, minHeight: 16)
                                .background(c.brand, in: Capsule())
                                .offset(x: -6, y: 6)
                        }
                    }
            }
            .buttonStyle(PressFade())
            .accessibilityLabel(strings.t("driver.v3reg.filter"))
            .accessibilityValue(filterCount > 0 ? "\(filterCount)" : "")
            .accessibilityIdentifier("elchi.driver.home.filter")
        }
        .padding(.leading, 18).padding(.trailing, 6)
        .frame(height: 64)
        .background(c.card, in: Capsule())
        .shadow(color: c.softShadow, radius: 12, y: 6)
    }
}

/// A v3 pill choice (chips, filter options): navy with white text when chosen, white with a hairline otherwise.
struct V3Chip: View {
    let title: String
    let selected: Bool
    var height: CGFloat = 40
    let action: () -> Void
    @Environment(\.elchi) private var c

    var body: some View {
        Button(action: action) {
            Text(title).font(ElchiFont.poppins(height >= 48 ? 14.5 : 13.5, .medium)).lineLimit(1)
                .foregroundStyle(selected ? c.onPrimaryV3 : c.text)
                .padding(.horizontal, height >= 48 ? 22 : 16)
                .frame(height: height)
                .background(selected ? c.primaryV3 : c.card, in: Capsule())
                .overlay { Capsule().strokeBorder(selected ? .clear : c.line, lineWidth: 1) }
                .frame(minHeight: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(PressFade())
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

/// The filter sheet: period (the DD5 range), sort, minimum price, exact only; the footer says how many show.
struct HomeFilterSheet: View {
    @Binding var filter: HomeFilter
    let resultCount: Int
    let onClose: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text(strings.t("driver.v3reg.filter")).font(ElchiFont.titleV3).foregroundStyle(c.text).accessibilityAddTraits(.isHeader)
                Spacer()
                Button(strings.t("driver.v3reg.clear")) { filter = HomeFilter() }
                    .font(ElchiFont.poppins(14, .semibold)).foregroundStyle(c.accentText)
                    .frame(minHeight: 44)
                    .accessibilityIdentifier("elchi.homeFilter.reset")
            }
            group(strings.t("driver.v3reg.filterPeriod")) {
                ForEach(DirectionFeedDay.allCases, id: \.self) { day in
                    V3Chip(title: strings.t(day.labelKey), selected: filter.period == day) { filter.period = day }
                        .accessibilityIdentifier("elchi.homeFilter.period.\(day.rawValue)")
                }
            }
            group(strings.t("driver.v3reg.filterSort")) {
                ForEach(HomeSort.allCases, id: \.self) { sort in
                    V3Chip(title: strings.t(sort.labelKey), selected: filter.sort == sort) { filter.sort = sort }
                        .accessibilityIdentifier("elchi.homeFilter.sort.\(sort.rawValue)")
                }
            }
            group(strings.t("common.price")) {
                ForEach(HomeMinPrice.allCases, id: \.self) { price in
                    V3Chip(title: priceLabel(price), selected: filter.minPrice == price) { filter.minPrice = price }
                        .accessibilityIdentifier("elchi.homeFilter.price.\(price.rawValue)")
                }
            }
            Toggle(isOn: $filter.exactOnly) {
                VStack(alignment: .leading, spacing: 1) {
                    Text(strings.t("driver.v3reg.exactOnly")).font(ElchiFont.poppins(14, .semibold)).foregroundStyle(c.text)
                    Text(strings.t("driver.v3reg.exactOnlyHint")).font(ElchiFont.caption).foregroundStyle(c.muted)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .tint(c.brand)
            .padding(.horizontal, 14).padding(.vertical, 12)
            .overlay { RoundedRectangle(cornerRadius: 18).strokeBorder(c.line, lineWidth: 1) }
            .accessibilityIdentifier("elchi.homeFilter.exact")
            Spacer(minLength: 8)
            ElchiButton(resultCount > 0 ? strings.t("driver.v3reg.showCount", ("count", resultCount)) : strings.t("driver.v3reg.noResults"),
                        action: onClose)
                .accessibilityIdentifier("elchi.homeFilter.apply")
        }
        .padding(.horizontal, 16).padding(.top, 24).padding(.bottom, 12)
        .background(c.card.ignoresSafeArea())
        .presentationDetents([.fraction(0.75), .large])
        .presentationDragIndicator(.visible)
        .presentationCornerRadius(ElchiShape.sheet)
        .elchiV3()
    }

    private func group<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(ElchiFont.label).foregroundStyle(c.muted)
            FlowLayout(spacing: 8) { content() }
        }
    }

    private func priceLabel(_ price: HomeMinPrice) -> String {
        guard price != .any else { return strings.t("driver.v3reg.priceAny") }
        return strings.t("driver.v3reg.priceFrom", ("amount", Money.grouped(String(price.minor / 100))))
    }
}

// MARK: - Listings (Royxat 1.12, Safar 1.7)

/// One client request on the home: kind icon, route, day + window, price + unit; the info chip, the match tag, and
/// "Taklif" (or "Taklifni ko'rish" once offered). The card opens the listing detail.
struct HomeListingCard: View {
    let entry: HomeListing
    /// The driver's own offer on it (Safar 5.7 join), if any.
    let mark: FeedOfferMark
    let onOpen: () -> Void
    let onOffer: () -> Void
    let onThread: (String) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        let listing = entry.listing
        let perPerson = HomeListingLogic.perPerson(listing)
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 12) {
                ListingKindIcon.of(listing).image(size: 18).foregroundStyle(c.accentText)
                    .frame(width: 40, height: 40)
                    .background(c.iconTint, in: Circle())
                VStack(alignment: .leading, spacing: 2) {
                    Text(strings.route(listing)).font(ElchiFont.poppins(16, .semibold)).foregroundStyle(c.text).lineLimit(2)
                    Text(strings.span(listing.departureWindowStart, listing.departureWindowEnd)).font(ElchiFont.poppins(12.5))
                        .foregroundStyle(c.muted).lineLimit(1)
                }
                Spacer(minLength: 4)
                VStack(alignment: .trailing, spacing: 1) {
                    Text(strings.money(HomeListingLogic.shownPriceMinor(listing))).font(ElchiFont.poppins(15, .semibold)).foregroundStyle(c.text)
                        .lineLimit(1)
                    Text(perPerson ? strings.t("driver.v3reg.perPerson") : strings.t("common.total").lowercased())
                        .font(ElchiFont.poppins(11)).foregroundStyle(c.muted)
                }
            }
            HStack(spacing: 6) {
                if let info = strings.listingInfo(listing) {
                    Text(info).font(ElchiFont.poppins(12, .medium)).foregroundStyle(c.tone(.gray).noteText).lineLimit(1)
                        .padding(.horizontal, 10).padding(.vertical, 6)
                        .background(c.page, in: Capsule())
                        .layoutPriority(-1)
                }
                if let tag = strings.matchTag(entry.item) {
                    Text(tag.text).font(ElchiFont.poppins(12, .semibold)).foregroundStyle(c.tone(tag.tone).fg).lineLimit(1)
                        .padding(.horizontal, 10).padding(.vertical, 6)
                        .background(c.tone(tag.tone).bg, in: Capsule())
                        .fixedSize()
                }
                Spacer(minLength: 4)
                if let thread = mark.threadId ?? entry.item.myThreadId {
                    smallButton(strings.t("driver.feed.viewOffer"), navy: false) { onThread(thread) }
                        .accessibilityIdentifier("elchi.home.listing.viewOffer.\(listing.id)")
                } else {
                    smallButton(strings.t("driver.v3reg.offer"), navy: true, action: onOffer)
                        .accessibilityIdentifier("elchi.home.listing.offer.\(listing.id)")
                }
            }
        }
        .padding(16)
        .background(c.card, in: RoundedRectangle(cornerRadius: ElchiShape.cardV3))
        .shadow(color: c.softShadow, radius: 12, y: 6)
        .contentShape(RoundedRectangle(cornerRadius: ElchiShape.cardV3))
        .onTapGesture(perform: onOpen)
        .accessibilityElement(children: .contain)
        .accessibilityAction(named: Text(strings.t("driver.v3trip.openListing")), onOpen)
        .accessibilityIdentifier("elchi.home.listing.\(listing.id)")
    }

    private func smallButton(_ title: String, navy: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(ElchiFont.poppins(13, .medium)).lineLimit(1)
                .foregroundStyle(navy ? c.onPrimaryV3 : c.text)
                .padding(.horizontal, 13)
                .frame(height: 38)
                .background(navy ? c.primaryV3 : c.field, in: Capsule())
                .frame(minHeight: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(PressFade())
        .fixedSize()
    }
}

/// "Kredit va taklif kodi" + the credit still available (never said as money one can take out) and the gift.
struct HomeCreditCard: View {
    let creditMinor: Int?
    let onOpen: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        Button(action: onOpen) {
            HStack(spacing: 14) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(strings.t("driverProfile.action.bonus")).font(ElchiFont.poppins(20, .medium)).foregroundStyle(c.text)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(creditMinor.map { strings.t("driver.v3reg.creditAmount", ("amount", strings.money($0))) } ?? strings.t("driver.bonus.noCreditTitle"))
                        .font(ElchiFont.poppins(15, .semibold)).foregroundStyle(c.accentText)
                }
                Spacer(minLength: 0)
                ElchiIcon.gift.image(size: 22).foregroundStyle(c.accentText)
                    .frame(width: 48, height: 48)
                    .background(c.field, in: Circle())
            }
            .padding(18)
            .background(c.card, in: RoundedRectangle(cornerRadius: 30))
            .shadow(color: c.softShadow, radius: 12, y: 6)
            .contentShape(Rectangle())
        }
        .buttonStyle(PressFade())
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
        .accessibilityIdentifier("elchi.driver.home.credit")
    }
}

extension LocaleStore {
    /// The info chip: the parcel category's name only (Q140: no numbers), "{n} kishi" for people, else the parcel type.
    func listingInfo(_ listing: ListingPublicDTO) -> String? {
        if listing.serviceType == .passenger { return t("seatPicker.peopleCount", ("count", max(listing.quantity, 1))) }
        if let category = listing.parcelCategory { return name(category) }
        return listing.parcelType.map(parcelTypeName)
    }

    /// The match tag (Q158 words): "Aniq yo'nalish" / "Yo'l yo'nalishida"; another time is "Vaqti boshqa" (amber).
    func matchTag(_ item: DirectionRequestItemDTO) -> (text: String, tone: Tone)? {
        if item.fit == "time_differs" { return (t("match.reason.time_differs"), .warn) }
        switch item.matchType {
        case .exact: return (t("match.exact"), .ok)
        case .onRoute: return (t("match.on_route"), .blue)
        default: return nil
        }
    }

    /// What the home search looks in: both ends (both languages) and the info line.
    func listingSearchText(_ entry: HomeListing) -> String {
        let listing = entry.listing
        let names = [listing.originPoint, listing.destinationPoint].compactMap { $0 }.flatMap { point in
            [point.district?.nameUz, point.address].compactMap { $0 }
        }
        return (names + [route(listing), listingInfo(listing) ?? "", parcelLine(listing) ?? ""]).joined(separator: " ")
    }
}
