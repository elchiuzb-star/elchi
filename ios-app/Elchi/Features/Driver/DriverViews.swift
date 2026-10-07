import SwiftUI

// MARK: - Tab root scaffold

/// A tab root (the prototype's `h1` top): large title, optional bell with the unread count, the app banner under it,
/// then the scrolling body on the page colour. The tab bar sits below (DriverFlow).
struct DriverTabScreen<Content: View>: View {
    /// nil: no bar (design v3 home draws its own header row in the content).
    let title: String?
    let bell: BellButton?
    /// The top-right "+" (Yo'nalishlar: add a trip).
    let plus: (label: String, action: () -> Void)?
    /// DESIGN07 0.2: a bar control at the right (Moslar: the "Takliflarim" pill).
    let trailing: AnyView?
    let content: Content
    @Environment(\.elchi) private var c
    @Environment(BannerCenter.self) private var banners: BannerCenter?
    /// The GPS bar on the trips tab while a trip runs (Stage 09).
    @Environment(\.screenAccessory) private var accessory
    @Environment(\.elchiV3) private var v3

    init(title: String?, bell: BellButton? = nil, plus: (label: String, action: () -> Void)? = nil, trailing: AnyView? = nil,
         @ViewBuilder content: () -> Content) {
        self.title = title
        self.bell = bell
        self.plus = plus
        self.trailing = trailing
        self.content = content()
    }

    var body: some View {
        VStack(spacing: 0) {
            if let title {
                HStack(spacing: 10) {
                    Text(title).font(v3 ? ElchiFont.h1V3 : ElchiFont.poppins(26, .medium, relativeTo: .title)).foregroundStyle(c.text)
                        .lineLimit(1).minimumScaleFactor(0.7)
                        .accessibilityAddTraits(.isHeader)
                    Spacer(minLength: 0)
                    if let bell { bell }
                    if let plus {
                        if v3 {
                            // Design v3: the add button is the brand circle with a navy plus.
                            Button(action: plus.action) {
                                ElchiIcon.plus.image(size: 20).foregroundStyle(c.navy)
                                    .frame(width: 44, height: 44)
                                    .background(c.brand, in: Circle())
                            }
                            .buttonStyle(PressFade())
                            .accessibilityLabel(plus.label)
                            .accessibilityIdentifier("elchi.driver.plus")
                        } else {
                            RoundIconButton(.plus, label: plus.label, action: plus.action).accessibilityIdentifier("elchi.driver.plus")
                        }
                    }
                    if let trailing { trailing }
                }
                .frame(height: 64)
                .padding(.horizontal, 16)
            }
            if let accessory { accessory }
            if let banners { BannerHost(center: banners) }
            ScrollView {
                VStack(alignment: .leading, spacing: v3 ? 14 : 12) { content }
                    .padding(EdgeInsets(top: title == nil ? 10 : 6, leading: 16, bottom: 18, trailing: 16))
            }
        }
        .background(c.page.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
    }
}

/// The notifications bell with the unread count (the prototype's red pill); VoiceOver hears the count too.
struct BellButton: View {
    let count: Int
    let more: Bool
    let action: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(\.elchiV3) private var v3

    var body: some View {
        Button(action: action) {
            ElchiIcon.bell.image(size: 20).foregroundStyle(c.text)
                .frame(width: v3 ? 48 : 44, height: v3 ? 48 : 44)
                .background(v3 ? c.iconFill : c.card, in: Circle())
                .shadow(color: v3 ? .clear : c.shadow, radius: 12, y: 6)
                .overlay(alignment: .topTrailing) {
                    if count > 0 {
                        Text(more ? "\(count)+" : "\(count)").font(ElchiFont.poppins(11, .bold)).foregroundStyle(.white)
                            .padding(.horizontal, 5)
                            .frame(minWidth: 20, minHeight: 20)
                            .background(Color(hex: 0xE0413A), in: Capsule())
                            .overlay { Capsule().strokeBorder(c.page, lineWidth: 2) }
                            .offset(x: 5, y: -5)
                    }
                }
        }
        .buttonStyle(.plain)
        .accessibilityLabel(count > 0 ? strings.t("driverHome.notificationsUnread", ("count", more ? "\(count)+" : "\(count)"))
                                      : strings.t("notifications.title"))
        .accessibilityIdentifier("elchi.driver.bell")
    }
}

// MARK: - Home (design v3: Royxat 1.x, Safar 1.x)

/// Driver home: the header row (avatar, "Balans" pill - Q22: visible before approval -, bell with a dot), "Salom,
/// {name}!" with the verification seal, then - until approved - the warning, the checklist and the next step; once
/// approved the search, the chips and "Mijozlar e'lonlari" built from the driver's directions, the work tiles and
/// "Yangi safar rejalashtirish" (the direction form, Q150). "Kredit va taklif kodi" closes the page for every status.
/// The status card and the availability switch are gone from home (the switch stays on Profil).
struct DriverHomeView: View {
    let driver: DriverModel
    let inbox: InboxModel
    let listings: HomeListingsModel
    /// The `passenger_enabled` flag (the "Yo'lovchi" chip, K7 / Q89).
    let feed: FeedModel
    /// The driver's offers: "already offered" on the cards (Safar 5.7).
    let proposals: DriverProposalsModel
    /// A referral code kept from an `elchigo.uz/r/<code>` link, waiting for the driver's tap.
    var referralCode: String? = nil
    var applyingReferral = false
    var onReferral: () -> Void = {}
    /// The referral row's X: forget the kept code (DESIGN06 1.1).
    var onForgetReferral: () -> Void = {}
    let onBell: () -> Void
    let onProfile: () -> Void
    let onDocuments: () -> Void
    let onSupport: () -> Void
    let onMatches: () -> Void
    /// The avatar: the Profil tab.
    var onProfileTab: () -> Void = {}
    /// Stage 09: "Komissiya balansi".
    var onWallet: () -> Void = {}
    /// "Kredit va taklif kodi".
    var onBonus: () -> Void = {}
    /// A card: the listing detail; "Taklif": the direction offer; an offered one: its thread.
    var onOpenListing: (String) -> Void = { _ in }
    var onOffer: (HomeListing) -> Void = { _ in }
    var onThread: (String) -> Void = { _ in }
    /// No direction yet: the add form / the directions segment.
    var onAddDirection: () -> Void = {}
    /// DESIGN07 1.1-1.3 (approved drivers): the work tiles and "Yangi safar rejalashtirish" (DriverWorkSummary).
    var work: AnyView? = nil
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(BannerCenter.self) private var banners: BannerCenter?
    @State private var filterOpen = false

    var body: some View {
        DriverTabScreen(title: nil) {
            HomeHeaderRow(initials: Initials.of(name), balance: balance, unread: inbox.unread, unreadMore: inbox.unreadMore,
                          onProfile: onProfileTab, onWallet: onWallet, onBell: onBell)
            switch driver.profile {
            case .loading:
                SkeletonCards(count: 3)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err)
                ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await driver.refresh() } }
            case .loaded(let profile):
                let status = DriverVerification(profile.verificationStatus)
                content(status, state: DriverHomeState.derive(status: status, vehicleLocked: driver.vehicleLocked,
                                                              slots: driver.documents.value.map(DocumentSlots.derive)))
            }
            HomeCreditCard(creditMinor: listings.creditMinor, onOpen: onBonus)
        }
        .refreshable {
            async let profile: Void = driver.refresh()
            async let unread: Void = inbox.refreshUnread()
            async let credit: Void = listings.loadCredit()
            _ = await (profile, unread, credit)
            if driver.status?.isApproved == true { await loadListings() }
        }
        .task {
            async let profile: Void = driver.refresh()
            async let unread: Void = inbox.refreshUnread()
            async let credit: Void = listings.loadCredit()
            _ = await (profile, unread, credit)
        }
        .task(id: "\(driver.status?.isApproved == true)|\(listings.filter.period.rawValue)") {
            guard driver.status?.isApproved == true else { return }
            await loadListings()
        }
        #if DEBUG
        // Screenshots: `-uiTestHomeFilter YES` opens the filter sheet once the list is in.
        .task(id: listings.listings?.value?.count) {
            if UserDefaults.standard.bool(forKey: "uiTestHomeFilter"), listings.listings?.value != nil { filterOpen = true }
        }
        #endif
        .sheet(isPresented: $filterOpen) {
            @Bindable var listings = listings
            HomeFilterSheet(filter: $listings.filter, resultCount: shown.count) { filterOpen = false }
        }
    }

    private func loadListings() async {
        await feed.loadFlags()
        async let read: Void = listings.load(passengerAllowed: feed.passengerAllowed)
        async let open: Void = proposals.load(.open)
        async let accepted: Void = proposals.load(.accepted)
        _ = await (read, open, accepted)
    }

    private var name: String? {
        let profile = driver.profile.value
        return [profile?.fullName, profile?.user?.fullName].compactMap { $0?.trimmingCharacters(in: .whitespaces) }.first { !$0.isEmpty }
    }

    @ViewBuilder
    private func content(_ status: DriverVerification, state: DriverHomeState) -> some View {
        let seal = HomeSeal.of(state)
        HomeGreeting(firstName: HomeListingLogic.firstName(name), seal: seal, stateWord: strings.t(state.labelKey)) {
            if let key = seal.toastKey { banners?.show(.key(key), tone: seal == .approved ? .ok : .warn) } else {
                banners?.show(.key(state.labelKey), tone: .err)
            }
        }
        if let referralCode { pendingReferral(referralCode) }
        if status.isApproved {
            listingsSection
            if let work { work }
        } else {
            // Royxat 1.6: not decided -> the design's warning; rejected / blocked -> the reason and support (Q96).
            if status.gate == .decided {
                Note(strings.t("app.driverGate.decided"), tone: .err).accessibilityIdentifier("elchi.driver.home.decided")
            } else {
                Note(strings.t("driverHome.availabilityLocked"), tone: .warn).accessibilityIdentifier("elchi.driver.home.locked")
            }
            DriverChecklistCard(steps: DriverChecklist.steps(state: state, profile: driver.profile.value, slots: driver.slots)) { target in
                switch target {
                case .form: onProfile()
                case .documents: onDocuments()
                case .gate: onMatches()
                }
            }
            ElchiButton(strings.t(driver.vehicleLocked ? "driverHome.viewProfile" : "driverHome.completeProfile"), action: onProfile)
                .accessibilityIdentifier("elchi.driver.home.profile")
            ElchiButton(strings.t("driverHome.uploadDocuments"), variant: .soft, action: onDocuments)
            if status.gate == .decided {
                ElchiButton(strings.t("app.driverGate.support"), variant: .outline, icon: .head, action: onSupport)
            }
        }
    }

    // MARK: Listings

    /// What the search, chips and filter leave, sorted.
    private var shown: [HomeListing] {
        HomeListingLogic.apply(listings.listings?.value ?? [], chip: listings.chip, filter: listings.filter, query: listings.query) {
            strings.listingSearchText($0)
        }
    }

    private var hasActiveDirection: Bool { !HomeListingLogic.readable(listings.directions.directions).isEmpty }

    @ViewBuilder
    private var listingsSection: some View {
        @Bindable var listings = listings
        let shown = shown
        HomeSearchPill(query: $listings.query, subline: subline(count: shown.count), filterCount: listings.filter.activeCount) {
            filterOpen = true
        }
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(HomeChip.shown(passengerAllowed: feed.passengerAllowed), id: \.self) { chip in
                    V3Chip(title: strings.t(chip.labelKey), selected: listings.chip == chip, height: 48) { listings.chip = chip }
                        .accessibilityIdentifier("elchi.driver.home.chip.\(chip.rawValue)")
                }
            }
            .padding(.horizontal, 16)
        }
        .padding(.horizontal, -16)
        HStack(alignment: .firstTextBaseline) {
            Text(strings.t("driver.v3reg.listingsTitle")).font(ElchiFont.poppins(19, .medium)).foregroundStyle(c.text)
                .accessibilityAddTraits(.isHeader)
            Spacer()
            Button(strings.t("driver.v3reg.seeAll"), action: onMatches)
                .font(ElchiFont.poppins(13.5, .semibold)).foregroundStyle(c.accentText)
                .frame(minHeight: 44)
                .accessibilityIdentifier("elchi.driver.home.seeAll")
        }
        .padding(.top, 2)
        switch listings.listings {
        case nil, .loading?:
            SkeletonCards(count: 2)
        case .failed(let error)?:
            Note(strings.errorText(error), tone: .err)
            ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await loadListings() } }
        case .loaded?:
            if listings.directions.list.value != nil && !hasActiveDirection {
                // No (active) direction: what a direction does, and the way to add one (Royxat 1.12).
                if listings.directions.directions.isEmpty {
                    NoDirectionsCard(onAdd: onAddDirection)
                } else {
                    Note(strings.t("dir.paused"), tone: .gray)
                    ElchiButton(strings.t("driverRoutes.title"), variant: .soft, icon: .route, action: onAddDirection)
                }
            } else if shown.isEmpty {
                Text(strings.t(HomeListingLogic.emptyKey(query: listings.query, filter: listings.filter)))
                    .font(ElchiFont.poppins(13.5)).foregroundStyle(c.muted)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 24).padding(.horizontal, 16)
                    .background(c.card, in: RoundedRectangle(cornerRadius: 22))
                    .accessibilityIdentifier("elchi.driver.home.listingsEmpty")
            } else {
                ForEach(Array(shown.prefix(HomeListingLogic.shownCount)), id: \.id) { entry in
                    HomeListingCard(entry: entry, mark: mark(entry), onOpen: { onOpenListing(entry.id) },
                                    onOffer: { onOffer(entry) }, onThread: onThread)
                }
            }
        }
    }

    private func mark(_ entry: HomeListing) -> FeedOfferMark {
        FeedOfferMark.of(listingId: entry.id, open: proposals.lists[.open]?.value, accepted: proposals.lists[.accepted]?.value,
                         versions: { proposals.versions($0) })
    }

    /// "Yo'nalishlaringiz bo'yicha · 14 kun" (the single direction's name when there is one), or "{n} ta natija · …"
    /// while searching; then the filter's choices.
    private func subline(count: Int) -> String {
        let filter = listings.filter
        var parts: [String] = []
        if !listings.query.trimmingCharacters(in: .whitespaces).isEmpty {
            parts.append(strings.t("driver.v3reg.searchResults", ("count", count)))
        } else {
            let active = HomeListingLogic.readable(listings.directions.directions)
            parts.append(active.count == 1 ? DirectionEndName.route(active[0], ru: strings.locale == .ru) : strings.t("driver.v3reg.searchScope"))
        }
        parts.append(strings.t(filter.period.labelKey))
        if filter.sort != .nearest { parts.append(strings.t(filter.sort.labelKey)) }
        if filter.minPrice != .any {
            parts.append(strings.t("driver.v3reg.priceFrom", ("amount", Money.grouped(String(filter.minPrice.minor / 100)))))
        }
        if filter.exactOnly { parts.append(strings.t("match.exact")) }
        return parts.joined(separator: " · ")
    }

    /// "Taklif kodi saqlandi: …" / "Tasdiqlash uchun bosing" (the design's first row); the tap sends it as the
    /// driver's, the X forgets it.
    private func pendingReferral(_ code: String) -> some View {
        HStack(spacing: 10) {
            Button(action: onReferral) {
                HStack(spacing: 10) {
                    ElchiIcon.tag.image(size: 18).foregroundStyle(c.accentText)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(strings.t("link.referralSaved", ("code", code))).font(ElchiFont.poppins(13, .semibold)).foregroundStyle(c.text)
                        Text(strings.t(applyingReferral ? "common.loading" : "client.order.promoTap")).font(ElchiFont.poppins(12))
                            .foregroundStyle(c.accentText)
                    }
                    Spacer(minLength: 0)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(PressFade())
            .disabled(applyingReferral)
            .accessibilityIdentifier("elchi.driver.pendingReferral")
            Button(action: onForgetReferral) {
                ElchiIcon.x.image(size: 14).foregroundStyle(c.text)
                    .frame(width: 30, height: 30)
                    .background(c.card, in: Circle())
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(applyingReferral)
            .accessibilityLabel(strings.t("common.close"))
            .accessibilityIdentifier("elchi.driver.pendingReferral.close")
        }
        .padding(.leading, 14).padding(.trailing, 4).padding(.vertical, 3)
        .background(c.isDark ? Color(hex: 0x0E2A45) : Color(hex: 0xEAF5FF), in: RoundedRectangle(cornerRadius: 18))
    }

    /// "—" while the balance loads or when it failed: never a zero nobody measured.
    private var balance: String {
        driver.wallet.value.map { strings.money($0.availableMinor) } ?? "—"
    }
}

/// A label, a value in its tone's colour (the state is also in the words) and a hint (the prototype's status card).
struct StatusCard: View {
    let label: String
    let value: String
    let tone: Tone
    let hint: String?
    @Environment(\.elchi) private var c

    var body: some View {
        ElchiCard(padding: EdgeInsets(top: 14, leading: 16, bottom: 14, trailing: 16)) {
            VStack(alignment: .leading, spacing: 3) {
                Text(label).font(ElchiFont.caption).foregroundStyle(c.muted)
                Text(value).font(ElchiFont.poppins(16, .semibold)).foregroundStyle(c.tone(tone).fg)
                if let hint {
                    Text(hint).font(ElchiFont.caption).foregroundStyle(c.muted).lineSpacing(2).fixedSize(horizontal: false, vertical: true)
                }
            }
            .accessibilityElement(children: .combine)
        }
        .accessibilityIdentifier("elchi.driver.status")
    }
}

/// The three onboarding steps (DESIGN06 1.7): a numbered circle (green check when done, red cross when turned
/// down), the title, the sub-line (red when documents were rejected) and a chevron; each row opens its step.
struct DriverChecklistCard: View {
    let steps: [ChecklistStep]
    let onOpen: (ChecklistStep.Target) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        VStack(spacing: 0) {
            ForEach(steps, id: \.number) { step in
                Button { onOpen(step.target) } label: { row(step) }
                    .buttonStyle(PressFade())
                    .accessibilityIdentifier("elchi.driver.checklist.\(step.number)")
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 4)
        .background(c.card, in: RoundedRectangle(cornerRadius: ElchiShape.card))
        .shadow(color: c.shadow.opacity(0.8), radius: 12, y: 6)
    }

    private func row(_ step: ChecklistStep) -> some View {
        let ok = c.tone(.ok), err = c.tone(.err)
        let detail = text(step.detail)
        let redDetail = step.mark == .failed && step.target == .documents
        return HStack(spacing: 12) {
            Group {
                switch step.mark {
                case .done: ElchiIcon.check.image(size: 13)
                case .failed: ElchiIcon.x.image(size: 12)
                case .todo: Text("\(step.number)").font(ElchiFont.poppins(12, .bold))
                }
            }
            .foregroundStyle(step.mark == .done ? ok.fg : step.mark == .failed ? err.fg : c.muted)
            .frame(width: 26, height: 26)
            .background(step.mark == .done ? ok.bg : step.mark == .failed ? err.bg : c.field, in: Circle())
            VStack(alignment: .leading, spacing: 1) {
                Text(strings.t(step.titleKey)).font(ElchiFont.poppins(14, .semibold)).foregroundStyle(c.text)
                Text(detail).font(ElchiFont.caption).foregroundStyle(redDetail ? err.fg : c.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
            ElchiIcon.chevR.image(size: 16).foregroundStyle(c.placeholder)
        }
        .padding(.vertical, 12)
        .overlay(alignment: .top) { if step.number > 1 { Rectangle().fill(c.field).frame(height: 1) } }
        .contentShape(Rectangle())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(step.number). \(strings.t(step.titleKey)), \(detail)")
        .accessibilityAddTraits(.isButton)
    }

    private func text(_ detail: ChecklistStep.Detail) -> String {
        switch detail {
        case .text(let value): return value
        case .key(let key, let values):
            // `disputeStatus.rejected` is lower-case ("rad etildi"); a sub-line starts with a capital.
            let line = strings.t(key, values: values.map { ($0.key, $0.value as Any) })
            return line.prefix(1).uppercased() + line.dropFirst()
        }
    }
}

extension LocaleStore {
    /// The account state in words (DESIGN06 1.5): "To'ldirilmagan" / "Ko'rib chiqilmoqda" / … from what was sent.
    func homeStateLabel(_ state: DriverHomeState) -> String { t(state.labelKey) }

    /// The verification status in words: `app.driverVerification.*` or `status.*`, never the raw code.
    func verificationLabel(_ status: DriverVerification) -> String {
        tOrNil(status.labelKey) ?? tOrNil("status.\(status.raw)") ?? t("app.driverVerification.pending")
    }
}

// MARK: - Verification gate (Q96)

/// Why the driver cannot take work yet and what to do (web `DriverVerificationGate`): new / pending point back to
/// documents and profile; rejected / blocked were decided, so only support helps.
struct VerificationGateView: View {
    let status: DriverVerification
    /// The derived word for "Holat: …" (DESIGN06 4.1); the server's word when not known.
    var state: DriverHomeState? = nil
    /// "Profilni ko'rish" once the car is locked (4.2).
    var vehicleLocked = false
    let onDocuments: () -> Void
    let onProfile: () -> Void
    let onSupport: () -> Void
    @Environment(LocaleStore.self) private var strings

    var body: some View {
        let decided = status.gate == .decided
        let word = state.map(strings.homeStateLabel) ?? strings.verificationLabel(status)
        let text = strings.t("app.driverGate.status", ("status", word)) + ". "
            + strings.t(decided ? "app.driverGate.decided" : "app.driverGate.pending")
        Note(text, tone: decided ? .err : .warn, title: strings.t("app.driverGate.title"))
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("elchi.driver.gate")
        if decided {
            ElchiButton(strings.t("app.driverGate.support"), variant: .soft, icon: .head, action: onSupport)
        } else {
            ElchiButton(strings.t("app.driverGate.documents"), action: onDocuments)
            ElchiButton(strings.t(vehicleLocked ? "driverHome.viewProfile" : "app.driverGate.profile"), variant: .soft, action: onProfile)
        }
    }
}

/// Routes / Matches before approval (Orders stays open, DESIGN06 0.3): the gate until approved, then a calm "coming next" (Stage 08 fills them).
struct DriverGatedTab: View {
    let tab: DriverTab
    let driver: DriverModel
    let onDocuments: () -> Void
    let onProfile: () -> Void
    let onSupport: () -> Void
    @Environment(LocaleStore.self) private var strings

    var body: some View {
        DriverTabScreen(title: strings.t(tab == .matches ? "driverFeed.title" : tab.labelKey)) {
            switch driver.profile {
            case .loading:
                SkeletonCards(count: 2)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err)
                ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await driver.loadProfile() } }
            case .loaded(let profile):
                let status = DriverVerification(profile.verificationStatus)
                if status.gate != nil {
                    VerificationGateView(status: status, state: driver.homeState, vehicleLocked: driver.vehicleLocked,
                                         onDocuments: onDocuments, onProfile: onProfile, onSupport: onSupport)
                } else {
                    EmptyState(icon: tab.icon, title: strings.t("driver.tab.nextStage"))
                }
            }
        }
        .refreshable { await driver.refresh() }
        .task { await driver.refresh() }
    }
}

// MARK: - Locked field

/// A read-only form field (Q94): the value on the darker locked fill with a lock icon, and the hint under it.
struct LockedField: View {
    let label: String
    let value: String
    let hint: String
    var monospaced = false
    @Environment(\.elchi) private var c

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label).font(ElchiFont.label).foregroundStyle(c.text)
            HStack(spacing: 10) {
                Text(value.isEmpty ? "—" : value)
                    .font(monospaced ? .system(size: 15, design: .monospaced) : ElchiFont.body)
                    .foregroundStyle(c.text)
                    .lineLimit(1)
                Spacer(minLength: 0)
                ElchiIcon.lock.image(size: 18).foregroundStyle(c.muted)
            }
            .padding(.horizontal, 16)
            .frame(minHeight: 52)
            .background(c.isDark ? Color(hex: 0x20252D) : Color(hex: 0xE9EDF2), in: RoundedRectangle(cornerRadius: ElchiShape.field))
            .opacity(0.85)
            Text(hint).font(ElchiFont.caption).foregroundStyle(c.muted)
        }
        .accessibilityElement(children: .combine)
    }
}
