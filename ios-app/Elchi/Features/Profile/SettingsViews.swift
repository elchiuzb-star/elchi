import SwiftUI

// MARK: - Sozlamalar

/// Appearance (Yorug' / Qorong'i / Tizim, live), language (live; the map's labels follow on the next launch), the
/// account list and sign-out. No notification toggles (Q82: there is no push yet).
struct SettingsView: View {
    let leading: ElchiIcon
    let onLeading: () -> Void
    let onHelp: () -> Void
    let onDeleteAccount: () -> Void
    let onLogout: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(ThemeStore.self) private var theme
    @Environment(\.elchi) private var c
    @Environment(\.openURL) private var openURL
    @Environment(BannerCenter.self) private var banners: BannerCenter?

    static let privacyURL = URL(string: "https://www.elchigo.uz/privacy")!

    var body: some View {
        ScreenScaffold(title: strings.t("settingsScreen.title"), leading: leading,
                       backLabel: strings.t(leading == .menu ? "nav.menu" : "common.back"), onBack: onLeading) {
            SectionTitle(strings.t("settingsScreen.appearance"))
            HStack(alignment: .top, spacing: 8) {
                tile(.light, .sun, "client.settings.themeLight")
                tile(.dark, .moon, "client.settings.themeDark")
                tile(.system, .monitor, "client.settings.themeSystem")
            }
            .fixedSize(horizontal: false, vertical: true)
            SectionTitle(strings.t("settings.language"), description: strings.t("settings.languageHint"))
            Segmented(AppLocale.allCases.map { ($0, $0.label) }, selected: strings.locale) { locale in
                guard locale != strings.locale else { return }
                strings.set(locale)
                toast(strings.t("client.settings.languageChanged", ("name", locale.label)))
            }
            Text(strings.t("client.settings.mapLanguageNote")).font(ElchiFont.caption).foregroundStyle(c.muted)
            SectionTitle(strings.t("settingsScreen.account"))
            ElchiList {
                ListRow(icon: .head, title: strings.t("support.title"), first: true, action: onHelp)
                ListRow(icon: .shield, title: strings.t("settingsScreen.privacy")) { openURL(Self.privacyURL) }
                ListRow(icon: .trash, title: strings.t("client.settings.deleteAccount"), danger: true, dangerChevron: true, action: onDeleteAccount)
            }
            ElchiList {
                ListRow(icon: .logout, title: strings.t("settingsScreen.logout"), danger: true, first: true, action: onLogout)
            }
            Text(strings.t("client.settings.version", ("version", strings.appVersion)))
                .font(ElchiFont.poppins(11)).foregroundStyle(c.muted)
                .frame(maxWidth: .infinity).padding(.top, 4)
        } footer: {
            EmptyView()
        }
    }

    private func tile(_ mode: ThemeMode, _ icon: ElchiIcon, _ key: String) -> some View {
        ChoiceTile(icon: icon, title: strings.t(key), hint: strings.t("\(key)Hint"), selected: theme.mode == mode) {
            guard theme.mode != mode else { return }
            theme.set(mode)
            toast(strings.t("client.settings.themeChanged", ("name", strings.t(key))))
        }
    }

    /// The design's short confirmations ("Mavzu: Qorong'i", "Til: O'zbekcha").
    private func toast(_ text: String) {
        banners?.show(.text(text), tone: .info, hideAfter: .seconds(2))
    }
}

// MARK: - Akkauntni o'chirish

/// Store requirement: what goes, what stays (anonymised), when (at once - the server does not wait 30 days), an explicit
/// tick before the danger button, then a confirm dialog. A refusal lists what is still open (with "Buyurtmalarga
/// o'tish" when bookings or orders hold it); success signs out with a notice.
struct AccountDeleteView: View {
    let model: AccountDeleteModel
    let onBack: () -> Void
    /// "Buyurtmalarga o'tish" inside the refusal when open bookings / orders hold the deletion (nil: no such link).
    var onOrders: (() -> Void)?
    let onDeleted: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @State private var confirming = false

    var body: some View {
        @Bindable var model = model
        ScreenScaffold(title: strings.t("client.accountDelete.title"), backLabel: strings.t("common.back"), onBack: onBack) {
            Note(strings.t("client.accountDelete.warn"), tone: .warn)
            ElchiCard {
                CardRow(strings.t("client.accountDelete.deletedLabel"), strings.t("client.accountDelete.deletedValue"), first: true)
                CardRow(strings.t("client.accountDelete.keptLabel"), strings.t("client.accountDelete.keptValue"))
                CardRow(strings.t("client.accountDelete.whenLabel"), strings.t("client.accountDelete.whenValue"))
            }
            if let blockers = model.blockers {
                VStack(alignment: .leading, spacing: 6) {
                    Text(strings.t("client.accountDelete.blockedTitle")).font(ElchiFont.poppins(14, .semibold))
                    ForEach(Array(blockers.enumerated()), id: \.offset) { _, blocker in
                        HStack(alignment: .top, spacing: 8) {
                            Text("•")
                            Text(line(blocker)).fixedSize(horizontal: false, vertical: true)
                        }
                        .font(ElchiFont.poppins(13))
                    }
                    if let onOrders, DeletionBlocker.leadsToOrders(blockers) {
                        Button(action: onOrders) {
                            Text(strings.t("client.settings.goToOrders")).font(ElchiFont.poppins(13, .semibold)).underline()
                                .frame(minHeight: 36)
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("elchi.accountDelete.orders")
                    }
                }
                .foregroundStyle(c.tone(.err).noteText)
                .padding(14)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(c.tone(.err).bg, in: RoundedRectangle(cornerRadius: ElchiShape.note))
                .accessibilityElement(children: .contain)
            }
            if let error = model.error { Note(strings.errorText(error), tone: .err) }
            CheckRow(strings.t("client.v3.deleteCheck"), on: $model.confirmed, danger: true)
        } footer: {
            ElchiButton(strings.t("client.accountDelete.submit"), variant: .danger, loading: model.submitting) { confirming = true }
                .disabled(!model.confirmed)
                .accessibilityIdentifier("elchi.accountDelete.submit")
            ElchiButton(strings.t("confirmDialog.back"), variant: .neutral, size: .medium, action: onBack)
        }
        .overlay {
            // "Akkaunt o'chirilsinmi?" with the app's own "when" (at once, cannot be restored - never "30 kun").
            if confirming {
                DialogOverlay(dismissLabel: strings.t("confirmDialog.back")) { confirming = false } content: {
                    Heading(strings.t("client.settings.deleteConfirmTitle"), subtitle: strings.t("client.accountDelete.whenValue"))
                    HStack(spacing: 10) {
                        ElchiButton(strings.t("client.settings.deleteConfirmYes"), variant: .danger, size: .pair) {
                            confirming = false
                            Task { if await model.submit() { onDeleted() } }
                        }
                        .accessibilityIdentifier("elchi.accountDelete.confirm")
                        ElchiButton(strings.t("confirmDialog.back"), variant: .neutral, size: .pair) { confirming = false }
                    }
                }
            }
        }
    }

    private func line(_ blocker: DeletionBlocker) -> String {
        switch blocker {
        case .known(let key, let count): strings.t(key, ("count", count))
        case .other: strings.t("client.accountDelete.blocked.other")
        }
    }
}

// MARK: - Chiqish

/// "Chiqasizmi?" before signing out (drawer, profile and settings). "Qolish" and the scrim keep the session.
struct LogoutDialog: View {
    let onLogout: () -> Void
    let onStay: () -> Void
    @Environment(LocaleStore.self) private var strings

    var body: some View {
        DialogOverlay(dismissLabel: strings.t("client.logout.stay"), onDismiss: onStay) {
            Heading(strings.t("client.logout.confirmTitle"), subtitle: strings.t("client.logout.confirmText"))
            HStack(spacing: 10) {
                ElchiButton(strings.t("nav.logout"), variant: .danger, size: .pair, action: onLogout)
                    .accessibilityIdentifier("elchi.logout.confirm")
                ElchiButton(strings.t("client.logout.stay"), variant: .neutral, size: .pair, action: onStay)
            }
        }
    }
}
