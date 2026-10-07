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
    /// The client's "Hammasini o'qilgan deb belgilash" (one read call per loaded unread row: v2 has no read-all).
    var readAll = false
    let onOpen: (InboxTarget) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        ScreenScaffold(title: strings.t("notifications.title"), leading: leading, backLabel: strings.t(leading == .menu ? "nav.menu" : "common.back"),
                       onBack: onLeading,
                       actions: [BarAction(id: "refresh", icon: .refresh, label: strings.t("support.refresh")) { Task { await model.load() } }]) {
            switch model.items {
            case .loading:
                SkeletonCards(count: 3)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err)
                ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.load() } }
            case .loaded(let items) where items.isEmpty:
                EmptyState(icon: .bell, title: strings.t("notifications.empty"))
            case .loaded(let items):
                if readAll && items.contains(where: { !$0.isRead }) {
                    Button { Task { await model.readAll() } } label: {
                        Text(strings.t("client.inbox.readAll")).font(ElchiFont.poppins(13, .semibold)).foregroundStyle(c.accentText)
                            .padding(.vertical, 2).frame(minHeight: 36)
                    }
                    .buttonStyle(PressFade())
                    .frame(maxWidth: .infinity, alignment: .trailing)
                    .accessibilityIdentifier("elchi.inbox.readAll")
                }
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

/// Who is signed in, what the client's orders look like (from v2), the name form and the six quick actions of Profil
/// v3 (no hints). No "Nizolarim" (Q141: there are no dispute screens).
struct ProfileView: View {
    let model: ProfileModel
    let session: Session
    /// Unread notifications: a red dot on the "Bildirishnomalar" row's bell.
    var unread = 0
    let onMenu: () -> Void
    let onAction: (ProfileAction) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    enum ProfileAction { case bonus, notifications, threads, safety, help, logout }

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
                       error: model.nameTooShort ? strings.t("clientProfile.nameMinChars", uz: "Kamida 2 ta harf kiriting.", ru: "Введите не менее 2 букв.") : nil, contentType: .name)
            switch model.saveResult {
            case .success?: Note(strings.t("clientProfile.updated"), tone: .ok)
            case .failure(let error)?: Note(strings.t("client.profile.nameSaveFailed", ("error", strings.errorText(error))), tone: .err)
            case nil: EmptyView()
            }
            ElchiButton(strings.t("common.save"), variant: model.canSave ? .primary : .neutral, size: .medium, loading: model.saving) {
                Task {
                    await model.save()
                    if case .success? = model.saveResult { dismissKeyboard() }
                }
            }
            .disabled(!model.canSave)
            SectionTitle(strings.t("clientProfile.quickActions"))
            // Profil v3: six rows, no hints. Buyurtmalar, Takliflarim, Sozlamalar and Bosh sahifa live in the drawer.
            ElchiList {
                row(.gift, "clientProfile.bonus", .bonus, first: true)
                ListRow(icon: .bell, title: strings.t("notifications.title"), dot: unread > 0) { onAction(.notifications) }
                    .accessibilityValue(unread > 0 ? strings.t("client.notifications.new") : "")
                row(.file, "support.myThreads", .threads)
                row(.block, "safety.centerTitle", .safety)
                row(.head, "clientProfile.help", .help)
                ListRow(icon: .logout, title: strings.t("clientProfile.logout"), danger: true) { onAction(.logout) }
            }
        } footer: {
            EmptyView()
        }
        .refreshable { await model.loadStats() }
        .task { await model.loadStats() }
        .onChange(of: model.name) { _, _ in if model.saveResult != nil && !model.saving { model.clearResult() } }
    }

    private func row(_ icon: ElchiIcon, _ title: String, _ action: ProfileAction, first: Bool = false) -> some View {
        ListRow(icon: icon, title: strings.t(title), first: first) { onAction(action) }
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
                    figures.map { $0.latest.map { strings.tOrNil($0.key) ?? $0.raw } ?? dash } ?? dash,
                    valueTone: figures?.latest.flatMap { ProfileStats.latestTone($0) })
        }
    }

    private var isFailed: Bool {
        if case .failed = model.stats { return true }
        return false
    }
}

// MARK: - Bonuslar va taklif kodi

/// Mirrors the web `BonusScreen` for the client: the bonus is a discount right, never money (Q102/Q103); no
/// commission, rates or formulas, no reward amounts (Q131/Q147). With the programme off and nothing on the balance the
/// client sees one centred sentence (BOSQICH 05); off with a balance, the note and that balance. The driver flow
/// (Stage 09: the driver credit, a QR of the link) keeps its own layout.
struct BonusView: View {
    let model: BonusModel
    let onBack: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(BannerCenter.self) private var banners: BannerCenter?
    @State private var copied = false

    private var driver: Bool { model.audience == "driver" }

    var body: some View {
        ScreenScaffold(title: strings.t(driver ? "promoScreen.titleDriver" : "promoScreen.titleClient"), backLabel: strings.t("common.back"),
                       onBack: onBack) {
            switch driver ? PromoLogic.ScreenState.on : state {
            case .loading:
                SkeletonCards(count: 2)
            case .offOnly:
                offState
            case .offWithBalance, .on:
                content
            }
        } footer: {
            EmptyView()
        }
        .refreshable { await model.load() }
        .task { await model.load() }
    }

    private var state: PromoLogic.ScreenState {
        var settled = model.balance.value != nil
        if case .failed(let error) = model.balance, PromoLogic.isProgramOff(error) { settled = true }
        return PromoLogic.screenState(programOff: model.programOff, balanceLoaded: settled, hasBuckets: !model.buckets.isEmpty)
    }

    /// "Taklif dasturi hozircha ishlamayapti." alone, centred, with the grey gift.
    private var offState: some View {
        VStack(spacing: 10) {
            ElchiIcon.gift.image(size: 28).foregroundStyle(c.muted)
                .frame(width: 64, height: 64)
                .background(c.isDark ? Color(hex: 0x243244) : Color(hex: 0xE4E9EF), in: Circle())
            Text(strings.t("promoScreen.programOff")).font(ElchiFont.poppins(16, .semibold)).foregroundStyle(c.text)
                .multilineTextAlignment(.center)
            Text(strings.t("client.bonus.programOffHint")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
                .multilineTextAlignment(.center).frame(maxWidth: 280)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 50).padding(.horizontal, 16)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("elchi.bonus.off")
    }

    @ViewBuilder
    private var content: some View {
        @Bindable var model = model
        Note(strings.t(driver ? "promoScreen.creditNotMoney" : "client.v3.bonusNotMoney"), tone: .warn)
        SectionTitle(strings.t(driver ? "promoScreen.myCredit" : "promoScreen.myBonuses"))
        balance
        if model.programOff {
            Note(strings.t(PromoLogic.programOffKey(hasBuckets: !model.buckets.isEmpty)), tone: .gray)
        } else {
            SectionTitle(strings.t("promoScreen.myCode"))
            if driver { driverCodeCard } else { codeCard }
            // Profil v3 5.3: the client's caption under the code is gone; the driver keeps it (DESIGN09 3.6, spec E).
            if driver { Text(strings.t("promoScreen.rewardNote")).font(ElchiFont.caption).foregroundStyle(c.muted) }
            if model.accepted {
                Note(strings.t("promoScreen.codeOnce"), tone: .ok,
                     title: model.acceptedCode.map { strings.t("client.bonus.codeAcceptedValue", ("code", $0)) })
            }
            if !model.hasAttribution && model.referrals.value != nil {
                SectionTitle(strings.t("promoScreen.enterCode"))
                ElchiField(text: $model.entered, label: strings.t("promoScreen.friendCode"), placeholder: strings.t("promoScreen.codeExample"),
                           // Profil v3 5.5: no hint under the client's field (only the error); the driver keeps it.
                           hint: driver ? strings.t("promoScreen.codeOnce") : nil, error: model.entryErrorKey.map { strings.t($0) },
                           keyboard: .asciiCapable, monospaced: true)
                    .textInputAutocapitalization(.characters)
                    .autocorrectionDisabled()
                if let error = model.enterError { Note(strings.errorText(error), tone: .err) }
                ElchiButton(strings.t("promoScreen.confirmCode"), variant: .soft, size: .medium, loading: model.entering) {
                    Task { await model.submitCode() }
                }
                .disabled(!model.canSubmitCode)
            }
            SectionTitle(strings.t("promoScreen.myCampaigns"))
            campaigns
        }
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
                EmptyState(icon: .gift, title: strings.t(driver ? "driver.bonus.noCreditTitle" : "promoScreen.noBonusTitle"),
                           description: strings.t(driver ? "driver.bonus.noCreditSubtitle" : "promoScreen.noBonusSubtitle"))
            } else {
                ForEach(model.buckets, id: \.self) { bucket in
                    ElchiCard {
                        CardTitle(strings.bucketTitle(bucket))
                        ForEach(Array(PromoLogic.rows(bucket).enumerated()), id: \.offset) { index, row in
                            // "Ishlatish mumkin" green and bold (BOSQICH 05).
                            CardRow(strings.t(row.key), strings.money(row.minor),
                                    detail: row.minor > 0 ? row.hintKey.map { strings.t($0) } : nil,
                                    strong: index == 0, valueTone: index == 0 ? .ok : nil)
                        }
                        if let expiry = strings.dateOnly(bucket.nextExpiryAt) {
                            CardRow(strings.t("client.bonus.nextExpiryLabel"), expiry)
                        }
                    }
                }
            }
        }
    }

    /// The client's code card (BOSQICH 05): dark navy, "Kod", the code large and spaced, the link when configured,
    /// "Kodni nusxalash" (the code only) and "Havolani ulashish" (the link, else the code).
    @ViewBuilder
    private var codeCard: some View {
        if let code = model.code {
            let navy = c.isDark ? Color(hex: 0x132B57) : Color(hex: 0x0E2350)
            VStack(alignment: .leading, spacing: 10) {
                Text(strings.t("client.bonus.codeLabel")).font(ElchiFont.poppins(12)).foregroundStyle(Color(hex: 0x9FB6D6))
                Text(code.code).font(.system(size: 28, weight: .semibold, design: .monospaced)).tracking(4)
                    .foregroundStyle(.white).textSelection(.enabled).lineLimit(1).minimumScaleFactor(0.7)
                    .accessibilityLabel(code.code.map(String.init).joined(separator: " "))
                if PromoLogic.showsLink(code), let url = code.shareUrl {
                    Text(url).font(.system(size: 12.5, design: .monospaced)).foregroundStyle(Color(hex: 0xC9D6E8))
                } else {
                    Text(strings.t("promoScreen.linkNotReady")).font(ElchiFont.caption).foregroundStyle(Color(hex: 0xC9D6E8))
                }
                HStack(spacing: 8) {
                    Button {
                        UIPasteboard.general.string = PromoLogic.copyText(code)
                        banners?.show(.text(strings.t("client.bonus.codeCopied", ("code", code.code))), tone: .info, hideAfter: .seconds(3))
                    } label: {
                        Text(strings.t("client.bonus.copyCode")).font(ElchiFont.poppins(13.5, .medium)).lineLimit(1).minimumScaleFactor(0.8)
                            .foregroundStyle(Color(hex: 0x0E2350))
                            .frame(maxWidth: .infinity, minHeight: 44)
                            .background(c.brand, in: Capsule())
                    }
                    .buttonStyle(PressFade())
                    .accessibilityIdentifier("elchi.bonus.copy")
                    ShareLink(item: PromoLogic.shareText(code)) {
                        // "Havolani ulashish" only when there is a link; otherwise the code goes out under "Ulashish".
                        Text(strings.t(PromoLogic.showsLink(code) ? "client.bonus.shareLink" : "client.share.send")).font(ElchiFont.poppins(13.5, .medium)).lineLimit(1).minimumScaleFactor(0.8)
                            .foregroundStyle(.white)
                            .frame(maxWidth: .infinity, minHeight: 44)
                            .background(Color(hex: 0x1C3A70), in: Capsule())
                    }
                }
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(navy, in: RoundedRectangle(cornerRadius: ElchiShape.card))
        } else if let error = model.codeError {
            Note(strings.errorText(error), tone: .err)
        } else if !model.loadedCode {
            SkeletonCards(count: 1)
        }
    }

    /// The driver's card (Stage 09): the link as a QR for the person next to them.
    @ViewBuilder
    private var driverCodeCard: some View {
        if let code = model.code {
            ElchiCard(padding: EdgeInsets(top: 14, leading: 16, bottom: 14, trailing: 16)) {
                VStack(alignment: .center, spacing: 10) {
                    Text(code.code).font(.system(size: 26, weight: .bold, design: .monospaced)).tracking(4)
                        .foregroundStyle(c.text).textSelection(.enabled)
                        .accessibilityLabel(code.code.map(String.init).joined(separator: " "))
                    if PromoLogic.showsLink(code), let url = code.shareUrl {
                        if let qr = QRCode.image(url) {
                            Image(uiImage: qr).interpolation(.none).resizable().scaledToFit().frame(width: 180, height: 180)
                                .padding(10).background(.white, in: RoundedRectangle(cornerRadius: 12))
                                .accessibilityLabel(strings.t("promoScreen.qrAria"))
                        }
                        // DESIGN09 3.4 NICE: the link in a grey box.
                        Text(url).font(.system(size: 12.5, design: .monospaced)).foregroundStyle(c.accentText).multilineTextAlignment(.center)
                            .textSelection(.enabled)
                            .padding(.horizontal, 12).padding(.vertical, 10).frame(maxWidth: .infinity)
                            .background(c.field, in: RoundedRectangle(cornerRadius: 12))
                        Text(strings.t("promoScreen.qrNote")).font(ElchiFont.caption).foregroundStyle(c.muted).multilineTextAlignment(.center)
                    } else {
                        Text(strings.t("promoScreen.linkNotReady")).font(ElchiFont.caption).foregroundStyle(c.muted)
                            .multilineTextAlignment(.center)
                    }
                    HStack(spacing: 8) {
                        ElchiButton(strings.t(copied ? "promoScreen.copied" : "promoScreen.copy"), variant: .soft, size: .pair,
                                    icon: copied ? .check : .copy) {
                            UIPasteboard.general.string = PromoLogic.shareText(code)
                            copied = true
                            // DESIGN09 3.5: "Havola nusxalandi" when a link went to the clipboard (the code alone: the label only).
                            if PromoLogic.showsLink(code) {
                                banners?.show(.key("driver.v3wallet.linkCopied"), tone: .ok, hideAfter: .seconds(3))
                            }
                        }
                        ShareLink(item: PromoLogic.shareText(code)) {
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

    /// "3 / 10 safar" and a bar; services still being checked are said in grey and never counted as done.
    private func progressBlock(_ progress: PromoLogic.Progress) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(strings.t(progress.key, ("done", progress.done), ("required", progress.required)))
                .font(ElchiFont.poppins(13, .semibold)).foregroundStyle(c.text)
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(c.field)
                    Capsule().fill(c.brand).frame(width: max(progress.fraction > 0 ? 8 : 0, geo.size.width * progress.fraction))
                }
            }
            .frame(height: 8)
            .accessibilityHidden(true)
            if progress.inReview {
                Text(strings.t("promo.progress.inReviewHint")).font(ElchiFont.caption).foregroundStyle(c.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.top, 6)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("elchi.bonus.progress")
    }

    /// Each campaign: its name and status badge, whose side the person is on, and "Kodim orqali qo'shilganlar: N ta ·
    /// Shart muddati: …" (the count only on the inviter's side).
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
                let invited = [referrals.invited.attributed, referrals.invited.qualifying, referrals.invited.qualified,
                               referrals.invited.expired, referrals.invited.rejected].compactMap { $0 }.reduce(0, +)
                ForEach(referrals.enrollments, id: \.id) { item in
                    let referee = item.side == "referee"
                    let deadline = strings.t("promoScreen.deadline", ("date", strings.dateOnly(item.qualificationDeadline) ?? ""))
                    ItemCard(title: item.campaignName, badge: (strings.enrollmentStatus(item), PromoLogic.enrollmentTone(item)),
                             sub: strings.t(referee ? "promoScreen.youAreInvited" : "promoScreen.youInvited"),
                             meta: referee ? deadline : "\(strings.t("promoScreen.invitedCount", ("count", invited))) · \(deadline)") {
                        // DESIGN09 3.9: the referee's own progress only (never the inviter's view of someone else).
                        if let progress = PromoLogic.progress(item) { progressBlock(progress) }
                    }
                }
            }
        }
    }
}
