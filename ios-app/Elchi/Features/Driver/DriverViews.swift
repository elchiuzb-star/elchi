import SwiftUI

// MARK: - Tab root scaffold

/// A tab root (the prototype's `h1` top): large title, optional bell with the unread count, the app banner under it,
/// then the scrolling body on the page colour. The tab bar sits below (DriverFlow).
struct DriverTabScreen<Content: View>: View {
    let title: String
    let bell: BellButton?
    /// The top-right "+" (Yo'nalishlar: add a trip).
    let plus: (label: String, action: () -> Void)?
    let content: Content
    @Environment(\.elchi) private var c
    @Environment(BannerCenter.self) private var banners: BannerCenter?

    init(title: String, bell: BellButton? = nil, plus: (label: String, action: () -> Void)? = nil, @ViewBuilder content: () -> Content) {
        self.title = title
        self.bell = bell
        self.plus = plus
        self.content = content()
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                Text(title).font(ElchiFont.poppins(26, .medium, relativeTo: .title)).foregroundStyle(c.text)
                    .lineLimit(1).minimumScaleFactor(0.7)
                    .accessibilityAddTraits(.isHeader)
                Spacer(minLength: 0)
                if let bell { bell }
                if let plus {
                    RoundIconButton(.plus, label: plus.label, action: plus.action).accessibilityIdentifier("elchi.driver.plus")
                }
            }
            .frame(height: 64)
            .padding(.horizontal, 16)
            if let banners { BannerHost(center: banners) }
            ScrollView {
                VStack(alignment: .leading, spacing: 12) { content }
                    .padding(EdgeInsets(top: 6, leading: 16, bottom: 18, trailing: 16))
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

    var body: some View {
        Button(action: action) {
            ElchiIcon.bell.image(size: 20).foregroundStyle(c.text)
                .frame(width: 44, height: 44)
                .background(c.card, in: Circle())
                .shadow(color: c.shadow, radius: 12, y: 6)
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

// MARK: - Home

/// Driver home: balance (Q22: visible before approval), the verification status in words (never the raw code), the
/// availability switch (locked until approved) and the next step. Not built here: the saved-referral-code row (needs
/// referral deep links, Q107) and the GPS bar (Stage 09).
struct DriverHomeView: View {
    let driver: DriverModel
    let inbox: InboxModel
    /// A referral code kept from an `elchigo.uz/r/<code>` link, waiting for the driver's tap.
    var referralCode: String? = nil
    var applyingReferral = false
    var onReferral: () -> Void = {}
    let onBell: () -> Void
    let onProfile: () -> Void
    let onDocuments: () -> Void
    let onSupport: () -> Void
    let onMatches: () -> Void
    /// Stage 08: "Takliflarim" (the offers the driver sent).
    var onProposals: () -> Void = {}
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        let approved = driver.status?.isApproved == true
        DriverTabScreen(title: strings.t(approved ? "clientProfile.home" : "driverHome.completeProfileTitle"),
                        bell: BellButton(count: inbox.unread, more: inbox.unreadMore, action: onBell)) {
            if let referralCode { pendingReferral(referralCode) }
            switch driver.profile {
            case .loading:
                SkeletonCards(count: 3)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err)
                ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await driver.refresh() } }
            case .loaded(let profile):
                content(DriverVerification(profile.verificationStatus))
            }
        }
        .refreshable {
            await driver.refresh()
            await inbox.refreshUnread()
        }
        .task {
            await driver.refresh()
            await inbox.refreshUnread()
        }
    }

    @ViewBuilder
    private func content(_ status: DriverVerification) -> some View {
        ElchiList {
            ListRow(icon: .wallet, title: strings.t("driverHome.commissionBalance"), description: balance, chevron: false, first: true, action: nil)
        }
        .accessibilityIdentifier("elchi.driver.balance")
        StatusCard(label: strings.t("driver.home.verificationLabel"), value: strings.verificationLabel(status), tone: status.tone,
                   hint: strings.t(status.isApproved ? "driverHome.approvedHint" : "driverHome.onboardingHint"))
        availability(status)
        if status.isApproved {
            ElchiButton(strings.t("driverHome.viewMatchingOrders"), variant: .soft, icon: .radar, action: onMatches)
            ElchiButton(strings.t("proposals.title"), variant: .outline, icon: .tag, action: onProposals)
                .accessibilityIdentifier("elchi.driver.home.proposals")
        } else {
            ElchiButton(strings.t("driverHome.completeProfile"), action: onProfile)
            ElchiButton(strings.t("driverHome.uploadDocuments"), variant: .soft, action: onDocuments)
            if status.gate == .decided {
                ElchiButton(strings.t("app.driverGate.support"), variant: .outline, icon: .head, action: onSupport)
            }
        }
    }

    /// "Taklif kodi saqlandi: … — tasdiqlash uchun bosing" (the design's first row); the tap sends it as the driver's.
    private func pendingReferral(_ code: String) -> some View {
        ElchiList {
            ListRow(icon: .tag, title: strings.t("driverHome.pendingReferral", ("code", code)),
                    trailing: applyingReferral ? strings.t("common.loading") : nil, highlighted: true, first: true,
                    action: applyingReferral ? nil : onReferral)
        }
        .accessibilityIdentifier("elchi.driver.pendingReferral")
    }

    /// "—" while the balance loads or when it failed: never a zero nobody measured.
    private var balance: String {
        driver.wallet.value.map { strings.money($0.availableMinor) } ?? "—"
    }

    private func availability(_ status: DriverVerification) -> some View {
        let isOn = driver.isAvailable
        let enabled = DriverAvailability.canToggle(status: status, isOn: isOn) && driver.availabilityPending == nil
        return ToggleRow(strings.t("driverHome.availabilityTitle"),
                         description: strings.t(DriverAvailability.subtitleKey(status: status, isOn: isOn)),
                         isOn: Binding(get: { driver.isAvailable }, set: { on in Task { await driver.setAvailability(on) } }))
            .disabled(!enabled)
            .opacity(enabled || driver.availabilityPending != nil ? 1 : 0.6)
            .accessibilityIdentifier("elchi.driver.availability")
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

extension LocaleStore {
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
    let onDocuments: () -> Void
    let onProfile: () -> Void
    let onSupport: () -> Void
    @Environment(LocaleStore.self) private var strings

    var body: some View {
        let decided = status.gate == .decided
        let text = strings.t("app.driverGate.status", ("status", strings.verificationLabel(status))) + ". "
            + strings.t(decided ? "app.driverGate.decided" : "app.driverGate.pending")
        Note(text, tone: decided ? .err : .warn, title: strings.t("app.driverGate.title"))
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("elchi.driver.gate")
        if decided {
            ElchiButton(strings.t("app.driverGate.support"), variant: .soft, icon: .head, action: onSupport)
        } else {
            ElchiButton(strings.t("app.driverGate.documents"), action: onDocuments)
            ElchiButton(strings.t("app.driverGate.profile"), variant: .soft, action: onProfile)
        }
    }
}

/// Routes / Matches / Orders in Stage 07: the gate until approved, then a calm "coming next" (Stage 08 fills them).
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
                    VerificationGateView(status: status, onDocuments: onDocuments, onProfile: onProfile, onSupport: onSupport)
                } else {
                    EmptyState(icon: tab.icon, title: strings.t("driver.tab.nextStage"))
                }
            }
        }
        .refreshable { await driver.loadProfile() }
        .task { await driver.loadProfile() }
    }
}

// MARK: - Profile tab (menu)

/// Who is signed in (name, phone, verification badge) and the menu. The client's profile screen (its account badge,
/// order figures and the client bonus) is not shown to a driver; the driver's credit screen is Stage 09.
struct DriverProfileMenu: View {
    enum Action { case form, documents, notifications, help, threads, safety, settings, logout }

    let driver: DriverModel
    let session: Session
    let onAction: (Action) -> Void
    @Environment(LocaleStore.self) private var strings

    var body: some View {
        DriverTabScreen(title: strings.t("driverProfile.title")) {
            let profile = driver.profile.value
            let name = [profile?.fullName, profile?.user?.fullName, session.user.fullName]
                .compactMap { $0?.trimmingCharacters(in: .whitespaces) }.first { !$0.isEmpty }
            let phone = UzPhone.display(session.user.phone)
            let status = driver.status
            AvatarCard(initials: Initials.of(name), name: name ?? phone, phone: name == nil ? nil : phone,
                       badge: status.map { (strings.verificationLabel($0), $0.tone) })
            SectionTitle(strings.t("driver.profile.menuTitle"))
            ElchiList {
                row(.car, "driverProfileForm.title",
                    VehicleLock.isLocked(profile) ? "driverProfileForm.vehicleLockedTitle" : "driverProfile.action.editHint", .form, first: true)
                row(.file, "driverProfile.action.documents", "driverProfile.action.documentsHint", .documents)
                row(.bell, "notifications.title", "clientProfile.notificationsHint", .notifications)
                row(.head, "driverProfile.action.support", "driverProfile.action.supportHint", .help)
                row(.chat, "support.myThreads", "support.myThreadsHint", .threads)
                row(.block, "safety.centerTitle", "safety.centerDescription", .safety)
                row(.settings, "driverProfile.action.settings", "driverProfile.action.settingsHint", .settings)
                ListRow(icon: .logout, title: strings.t("driverProfile.action.logout"), description: strings.t("driverProfile.action.logoutHint"),
                        danger: true) { onAction(.logout) }
                    .accessibilityIdentifier("elchi.driver.menu.logout")
            }
        }
        .refreshable { await driver.loadProfile() }
        .task { await driver.loadProfile() }
    }

    private func row(_ icon: ElchiIcon, _ title: String, _ hint: String, _ action: Action, first: Bool = false) -> some View {
        ListRow(icon: icon, title: strings.t(title), description: strings.t(hint), first: first) { onAction(action) }
            .accessibilityIdentifier("elchi.driver.menu.\(action)")
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
