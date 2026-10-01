import SwiftUI
import UIKit

/// Puts the keyboard away once a form was sent, so what the server answered is on screen.
@MainActor
func dismissKeyboard() {
    UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
}

// MARK: - Bildirishnomalar

/// The inbox (N4): newest first, unread rows framed and marked "Yangi", "Yana yuklash" for older pages. The words
/// are the app's (the server sends keys). Tapping marks an item read and opens where its link leads.
struct NotificationsView: View {
    let model: InboxModel
    let leading: ElchiIcon
    let onLeading: () -> Void
    let onOpen: (InboxTarget) -> Void
    @Environment(LocaleStore.self) private var strings

    var body: some View {
        ScreenScaffold(title: strings.t("notifications.title"), leading: leading, backLabel: strings.t(leading == .menu ? "nav.menu" : "common.back"),
                       onBack: onLeading) {
            switch model.items {
            case .loading:
                SkeletonCards(count: 3)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err)
                ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.load() } }
            case .loaded(let items) where items.isEmpty:
                EmptyState(icon: .bell, title: strings.t("notifications.empty"), description: strings.t("client.notifications.emptyHint"))
            case .loaded(let items):
                ForEach(items, id: \.id) { item in
                    let body = strings.inboxBody(item)
                    ItemCard(title: strings.inboxTitle(item), badge: item.isRead ? nil : (strings.t("client.notifications.new"), .err),
                             sub: body.isEmpty ? nil : body, meta: strings.inboxTime(item.createdAt), highlighted: !item.isRead,
                             action: {
                                 model.markRead(item)
                                 if let target = Inbox.target(item.link) { onOpen(target) }
                             })
                }
                if model.cursor != nil {
                    ElchiButton(strings.t("blockReport.loadMore"), variant: .ghost, size: .medium, icon: .refresh, loading: model.loadingMore) {
                        Task { await model.loadMore() }
                    }
                }
            }
        } footer: {
            EmptyView()
        }
        .refreshable { await model.load() }
        .task { await model.load() }
    }
}

// MARK: - Profil

/// Who is signed in, what the client's orders look like (from v2), the name form and the quick actions in the design's
/// order. No "Nizolarim" (Q141: there are no dispute screens).
struct ProfileView: View {
    let model: ProfileModel
    let session: Session
    let onMenu: () -> Void
    let onAction: (ProfileAction) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    enum ProfileAction { case orders, proposals, bonus, notifications, threads, safety, help, settings, home, logout }

    var body: some View {
        @Bindable var model = model
        ScreenScaffold(title: strings.t("clientProfile.title"), leading: .menu, backLabel: strings.t("nav.menu"), onBack: onMenu) {
            let name = session.user.fullName.flatMap { $0.isEmpty ? nil : $0 }
            AvatarCard(initials: Initials.of(name), name: name ?? UzPhone.display(session.user.phone),
                       phone: name == nil ? nil : UzPhone.display(session.user.phone),
                       badge: (strings.t("clientProfile.accountBadge"), .ok))
            stats
            SectionTitle(strings.t("clientProfile.personalTitle"))
            ElchiField(text: $model.name, label: strings.t("clientProfile.fullName"), placeholder: strings.t("clientProfile.fullNamePlaceholder"),
                       contentType: .name)
            switch model.saveResult {
            case .success?: Note(strings.t("clientProfile.updated"), tone: .ok)
            case .failure(let error)?: Note(strings.t("client.profile.nameSaveFailed", ("error", strings.errorText(error))), tone: .err)
            case nil: EmptyView()
            }
            ElchiButton(strings.t("common.save"), variant: .soft, size: .medium, loading: model.saving) {
                Task {
                    await model.save()
                    if case .success? = model.saveResult { dismissKeyboard() }
                }
            }
            .disabled(!model.canSave)
            SectionTitle(strings.t("clientProfile.quickActions"))
            ElchiList {
                row(.pkg, "clientProfile.myOrders", "clientProfile.myOrdersHint", .orders, first: true)
                row(.tag, "clientProfile.myProposals", "client.profile.myProposalsHint", .proposals)
                row(.gift, "clientProfile.bonus", "clientProfile.bonusHint", .bonus)
                row(.bell, "notifications.title", "clientProfile.notificationsHint", .notifications)
                row(.file, "support.myThreads", "support.myThreadsHint", .threads)
                row(.block, "safety.centerTitle", "safety.centerDescription", .safety)
                row(.head, "clientProfile.help", "clientProfile.helpHint", .help)
                row(.settings, "clientProfile.settings", "clientProfile.settingsHint", .settings)
                row(.home, "clientProfile.home", "clientProfile.homeHint", .home)
                ListRow(icon: .logout, title: strings.t("clientProfile.logout"), description: strings.t("clientProfile.logoutHint"),
                        danger: true) { onAction(.logout) }
            }
        } footer: {
            EmptyView()
        }
        .refreshable { await model.loadStats() }
        .task { await model.loadStats() }
        .onChange(of: model.name) { _, _ in if model.saveResult != nil && !model.saving { model.clearResult() } }
    }

    private func row(_ icon: ElchiIcon, _ title: String, _ hint: String, _ action: ProfileAction, first: Bool = false) -> some View {
        ListRow(icon: icon, title: strings.t(title), description: strings.t(hint), first: first) { onAction(action) }
    }

    /// Jami / Faol / Taklif, then "Buyurtmalar holati". "—" when the figures could not be loaded (never zeros).
    @ViewBuilder
    private var stats: some View {
        let figures = model.stats.value
        let dash = "—"
        StatTiles([
            (strings.t("client.profile.statTotal"), figures.map { "\($0.total)" } ?? dash),
            (strings.t("clientProfile.statActive"), figures.map { "\($0.active)" } ?? dash),
            (strings.t("clientProfile.statBids"), figures.map { "\($0.offers)" } ?? dash),
        ])
        .redacted(reason: model.stats.value == nil && !isFailed ? .placeholder : [])
        ElchiCard {
            CardTitle(strings.t("clientProfile.ordersTitle"))
            CardRow(strings.t("client.profile.statCompleted"), figures.map { "\($0.completed)" } ?? dash)
            CardRow(strings.t("clientProfile.latestOrder"),
                    figures.map { $0.latest.map { strings.tOrNil($0.key) ?? $0.raw } ?? dash } ?? dash)
        }
    }

    private var isFailed: Bool {
        if case .failed = model.stats { return true }
        return false
    }
}

// MARK: - Bonuslar va taklif kodi

/// Mirrors the web `BonusScreen` for the client: the bonus is a discount right, never money (Q102/Q103); no
/// commission, rates or formulas. With the programme off, one sentence and the balance only.
struct BonusView: View {
    let model: BonusModel
    let onBack: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var copied = false

    var body: some View {
        @Bindable var model = model
        let driver = model.audience == "driver"
        ScreenScaffold(title: strings.t(driver ? "promoScreen.titleDriver" : "promoScreen.titleClient"), backLabel: strings.t("common.back"),
                       onBack: onBack) {
            Note(strings.t(driver ? "promoScreen.creditNotMoney" : "promoScreen.bonusNotMoney"), tone: .warn)
            SectionTitle(strings.t(driver ? "promoScreen.myCredit" : "promoScreen.myBonuses"))
            balance
            if model.programOff {
                Note(strings.t(PromoLogic.programOffKey(hasBuckets: !model.buckets.isEmpty)), tone: .gray)
            } else {
                SectionTitle(strings.t("promoScreen.myCode"))
                codeCard
                Text(strings.t("promoScreen.rewardNote")).font(ElchiFont.caption).foregroundStyle(c.muted)
                if model.accepted { Note(strings.t("promoScreen.codeAccepted"), tone: .ok) }
                if !model.hasAttribution && model.referrals.value != nil {
                    SectionTitle(strings.t("promoScreen.enterCode"))
                    ElchiField(text: $model.entered, label: strings.t("promoScreen.friendCode"), placeholder: strings.t("promoScreen.codeExample"),
                               hint: strings.t("promoScreen.codeOnce"),
                               error: !model.entered.isEmpty && model.entered.count == ReferralCode.length && model.normalized == nil
                                   ? strings.t("promoScreen.codeFormat") : nil,
                               keyboard: .asciiCapable, monospaced: true)
                        .textInputAutocapitalization(.characters)
                        .autocorrectionDisabled()
                    if model.entered.count < ReferralCode.length {
                        Text(strings.t("promoScreen.codeFormat")).font(ElchiFont.caption).foregroundStyle(c.muted)
                    }
                    if let error = model.enterError { Note(strings.errorText(error), tone: .err) }
                    ElchiButton(strings.t("promoScreen.confirmCode"), variant: .soft, size: .medium, loading: model.entering) {
                        Task { await model.submitCode() }
                    }
                    .disabled(model.normalized == nil)
                }
                SectionTitle(strings.t("promoScreen.myCampaigns"))
                campaigns
            }
        } footer: {
            EmptyView()
        }
        .refreshable { await model.load() }
        .task { await model.load() }
    }

    @ViewBuilder
    private var balance: some View {
        switch model.balance {
        case .loading:
            SkeletonCards(count: 1)
        case .failed(let error):
            Note(strings.errorText(error), tone: .err)
            ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.load() } }
        case .loaded:
            if model.buckets.isEmpty {
                EmptyState(icon: .gift, title: strings.t(model.audience == "driver" ? "driver.bonus.noCreditTitle" : "promoScreen.noBonusTitle"),
                           description: strings.t(model.audience == "driver" ? "driver.bonus.noCreditSubtitle" : "promoScreen.noBonusSubtitle"))
            } else {
                ForEach(model.buckets, id: \.self) { bucket in
                    ElchiCard {
                        CardTitle(strings.bucketTitle(bucket))
                        ForEach(Array(PromoLogic.rows(bucket).enumerated()), id: \.offset) { _, row in
                            CardRow(strings.t(row.key), strings.money(row.minor),
                                    detail: row.minor > 0 ? row.hintKey.map { strings.t($0) } : nil)
                        }
                        if let expiry = strings.dateOnly(bucket.nextExpiryAt) {
                            CardRow(strings.t("promoScreen.nextExpiry", ("date", "")).trimmingCharacters(in: CharacterSet(charactersIn: ": ")), expiry)
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var codeCard: some View {
        if let code = model.code {
            ElchiCard(padding: EdgeInsets(top: 14, leading: 16, bottom: 14, trailing: 16)) {
                VStack(alignment: .center, spacing: 10) {
                    Text(code.code).font(.system(size: 26, weight: .bold, design: .monospaced)).tracking(4)
                        .foregroundStyle(c.text).textSelection(.enabled)
                        .accessibilityLabel(code.code.map(String.init).joined(separator: " "))
                    if PromoLogic.showsLink(code), let url = code.shareUrl {
                        // The driver shows the link as a QR to the person next to them (web BonusScreen role=driver).
                        if model.audience == "driver", let qr = QRCode.image(url) {
                            Image(uiImage: qr).interpolation(.none).resizable().scaledToFit().frame(width: 180, height: 180)
                                .padding(10).background(.white, in: RoundedRectangle(cornerRadius: 12))
                                .accessibilityLabel(strings.t("promoScreen.qrAria"))
                        }
                        Text(url).font(ElchiFont.poppins(13)).foregroundStyle(c.accentText).multilineTextAlignment(.center)
                        if model.audience == "driver" {
                            Text(strings.t("promoScreen.qrNote")).font(ElchiFont.caption).foregroundStyle(c.muted).multilineTextAlignment(.center)
                        }
                    } else {
                        Text(strings.t("promoScreen.linkNotReady")).font(ElchiFont.caption).foregroundStyle(c.muted)
                            .multilineTextAlignment(.center)
                    }
                    HStack(spacing: 8) {
                        ElchiButton(strings.t(copied ? "promoScreen.copied" : "promoScreen.copy"), variant: .soft, size: .pair,
                                    icon: copied ? .check : .copy) {
                            UIPasteboard.general.string = PromoLogic.showsLink(code) ? (code.shareUrl ?? code.code) : code.code
                            copied = true
                        }
                        ShareLink(item: PromoLogic.showsLink(code) ? (code.shareUrl ?? code.code) : code.code) {
                            HStack(spacing: 8) {
                                ElchiIcon.share.image(size: 18)
                                Text(strings.t("client.share.send")).font(ElchiFont.buttonSmall)
                            }
                            .foregroundStyle(c.text)
                            .frame(maxWidth: .infinity, minHeight: 48)
                            .background(c.field, in: Capsule())
                        }
                    }
                }
                .frame(maxWidth: .infinity)
            }
        } else if let error = model.codeError {
            Note(strings.errorText(error), tone: .err)
        } else if !model.loadedCode {
            SkeletonCards(count: 1)
        }
    }

    @ViewBuilder
    private var campaigns: some View {
        switch model.referrals {
        case .loading:
            SkeletonCards(count: 1)
        case .failed(let error):
            Note(strings.errorText(error), tone: .err)
        case .loaded(let referrals):
            if referrals.enrollments.isEmpty {
                Note(strings.t("promoScreen.noCampaigns"), tone: .gray)
            } else {
                ForEach(referrals.enrollments, id: \.id) { item in
                    let role = strings.t(item.side == "referee" ? "promoScreen.youAreInvited" : "promoScreen.youInvited")
                    ItemCard(title: item.campaignName, sub: "\(role) · \(strings.enrollmentStatus(item))",
                             lines: [ItemLine(strings.t("promoScreen.deadline", ("date", strings.dateOnly(item.qualificationDeadline) ?? "")))])
                }
            }
            let invited = [referrals.invited.attributed, referrals.invited.qualifying, referrals.invited.qualified,
                           referrals.invited.expired, referrals.invited.rejected].compactMap { $0 }.reduce(0, +)
            Text(strings.t("promoScreen.invitedCount", ("count", invited))).font(ElchiFont.caption).foregroundStyle(c.muted)
        }
    }
}
