import SwiftUI

// MARK: - Tab root scaffold

/// A tab root (the prototype's `h1` top): large title, optional bell with the unread count, the app banner under it,
/// then the scrolling body on the page colour. The tab bar sits below (DriverFlow).
struct DriverTabScreen<Content: View>: View {
    let title: String
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

    init(title: String, bell: BellButton? = nil, plus: (label: String, action: () -> Void)? = nil, trailing: AnyView? = nil,
         @ViewBuilder content: () -> Content) {
        self.title = title
        self.bell = bell
        self.plus = plus
        self.trailing = trailing
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
                if let trailing { trailing }
            }
            .frame(height: 64)
            .padding(.horizontal, 16)
            if let accessory { accessory }
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
/// availability switch (locked until approved) and the next step. The balance row opens "Komissiya balansi" (Stage 09).
struct DriverHomeView: View {
    let driver: DriverModel
    let inbox: InboxModel
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
    /// Stage 08: "Takliflarim" (the offers the driver sent).
    var onProposals: () -> Void = {}
    /// Stage 09: "Komissiya balansi".
    var onWallet: () -> Void = {}
    /// DESIGN07 1.1-1.3 (approved drivers): the work summary under the home's own blocks (DriverWorkSummary).
    var work: AnyView? = nil
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
                let status = DriverVerification(profile.verificationStatus)
                content(status, state: DriverHomeState.derive(status: status, vehicleLocked: driver.vehicleLocked,
                                                              slots: driver.documents.value.map(DocumentSlots.derive)))
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
    private func content(_ status: DriverVerification, state: DriverHomeState) -> some View {
        ElchiList {
            ListRow(icon: .wallet, title: strings.t("driverHome.commissionBalance"), description: balance, first: true, action: onWallet)
        }
        .accessibilityIdentifier("elchi.driver.balance")
        StatusCard(label: strings.t("driver.home.verificationLabel"), value: strings.t(state.labelKey), tone: state.tone,
                   hint: strings.t(state.hintKey))
        if !status.isApproved {
            DriverChecklistCard(steps: DriverChecklist.steps(state: state, profile: driver.profile.value, slots: driver.slots)) { target in
                switch target {
                case .form: onProfile()
                case .documents: onDocuments()
                case .gate: onMatches()
                }
            }
        }
        availability(status)
        if status.isApproved {
            ElchiButton(strings.t("driverHome.viewMatchingOrders"), variant: .soft, icon: .radar, action: onMatches)
            ElchiButton(strings.t("proposals.title"), variant: .outline, icon: .tag, action: onProposals)
                .accessibilityIdentifier("elchi.driver.home.proposals")
        } else {
            ElchiButton(strings.t(driver.vehicleLocked ? "driverHome.viewProfile" : "driverHome.completeProfile"), action: onProfile)
                .accessibilityIdentifier("elchi.driver.home.profile")
            ElchiButton(strings.t("driverHome.uploadDocuments"), variant: .soft, action: onDocuments)
            if status.gate == .decided {
                ElchiButton(strings.t("app.driverGate.support"), variant: .outline, icon: .head, action: onSupport)
            }
        }
        if status.isApproved, let work { work }
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
