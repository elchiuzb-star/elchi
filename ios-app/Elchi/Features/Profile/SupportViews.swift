import SwiftUI

// MARK: - Yordam

/// "Yordam": the support card (a phone only when the server has a line - never in the pilot, Q87; no hours, no reply
/// times), a ticket form, the tickets sent ("Yuborilgan murojaatlar": they have no replies, so no thread screen),
/// "Murojaatlarim" with "Hammasi (N)" and the newest operator chat (BOSQICH 05; the row when there is none yet) and
/// the FAQ with the first answer open.
struct SupportView: View {
    let model: SupportModel
    /// The operator chats ("Murojaatlarim"): the newest one and the count.
    let threads: SupportThreadsModel
    let leading: ElchiIcon
    let onLeading: () -> Void
    /// Whose questions the FAQ answers: `support.faq*` (client) or `driver.faq*` (the driver flow, Stage 07).
    var faqPrefix = "support.faq"
    let onThreads: () -> Void
    let onOpenThread: (String) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(\.openURL) private var openURL

    var body: some View {
        @Bindable var model = model
        ScreenScaffold(title: strings.t("support.title"), leading: leading, backLabel: strings.t(leading == .menu ? "nav.menu" : "common.back"),
                       onBack: onLeading) {
            if let phone = model.phone {
                ElchiCard {
                    CardTitle(strings.t("support.cardTitle"))
                    CardRow(strings.t("auth.phoneTitle"), UzPhone.display(phone), trailing: strings.t("client.bookingDetail.call")) {
                        if let url = DriverReveal.dialURL(phone) { openURL(url) }
                    }
                }
            } else {
                Note(strings.t("support.noPhoneLine"), tone: .blue, title: strings.t("support.cardTitle"))
            }
            SectionTitle(strings.t("support.newTicket"))
            ElchiField(text: $model.draft, placeholder: strings.t("support.messagePlaceholder"),
                       hint: SupportText.showsMinHint(model.draft) ? strings.t("client.help.minChars") : nil, multiline: true)
            if model.sent { Note(strings.t("support.ticketSent"), tone: .ok) }
            if let error = model.sendError { Note(strings.errorText(error), tone: .err) }
            ElchiButton(strings.t("support.send"), variant: .primary, size: .medium, loading: model.sending) {
                Task {
                    await model.send()
                    if model.sent { dismissKeyboard() }
                }
            }
            .disabled(!model.canSend)
            SectionTitle(strings.t("client.help.ticketsTitle"))
            tickets
            threadsSection
            SectionTitle(strings.t("support.faqTitle"))
            FaqList((1...4).map { (strings.t("\(faqPrefix)\($0)Question"), strings.t(SupportText.faqAnswerKey(prefix: faqPrefix, index: $0))) })
        } footer: {
            EmptyView()
        }
        .refreshable { await reload() }
        .task { await reload() }
    }

    private func reload() async {
        async let support: Void = model.load()
        async let chats: Void = threads.load()
        _ = await (support, chats)
    }

    /// "Murojaatlarim" + "Hammasi (N)" over the newest chat; with none (or not loaded) the row into the list.
    @ViewBuilder
    private var threadsSection: some View {
        if let list = threads.threads.value, let newest = list.first {
            SectionTitle(strings.t("support.myThreads"), action: strings.t("client.help.allThreads", ("count", list.count)), onAction: onThreads)
                .accessibilityIdentifier("elchi.support.threads")
            SupportThreadCard(thread: newest) { onOpenThread(newest.id) }
        } else {
            ElchiList {
                ListRow(icon: .chat, title: strings.t("support.myThreads"), description: strings.t("support.myThreadsHint"), first: true,
                        action: onThreads)
                    .accessibilityIdentifier("elchi.support.threads")
            }
        }
    }

    @ViewBuilder
    private var tickets: some View {
        switch model.tickets {
        case .loading:
            SkeletonCards(count: 1)
        case .failed(let error):
            Note(strings.errorText(error), tone: .err)
        case .loaded(let list) where list.isEmpty:
            Text(strings.t("support.noThreadsTitle")).font(ElchiFont.caption).foregroundStyle(c.muted)
        case .loaded(let list):
            ForEach(list, id: \.id) { ticket in
                let title = SupportText.firstLine(ticket.message)
                ItemCard(title: title.isEmpty ? strings.t("support.newTicket") : title,
                         badge: (strings.tOrNil("client.support.ticket.\(ticket.status.rawValue)") ?? ticket.status.rawValue,
                                 SupportText.ticketTone(ticket.status)),
                         sub: strings.dateOnly(ticket.createdAt))
            }
        }
    }
}

// MARK: - Murojaatlarim

/// The client's operator chats; each opens the Stage 04 support chat by thread id.
struct SupportThreadsView: View {
    let model: SupportThreadsModel
    let onBack: () -> Void
    let onOpen: (String) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(BannerCenter.self) private var banners: BannerCenter?

    var body: some View {
        ScreenScaffold(title: strings.t("support.myThreads"), backLabel: strings.t("common.back"), onBack: onBack,
                       actions: [BarAction(id: "refresh", icon: .refresh, label: strings.t("support.refresh")) {
                           Task {
                               await model.load()
                               if !model.failedLast { banners?.show(.key("client.booking.refreshed"), tone: .info, hideAfter: .seconds(2)) }
                           }
                       }]) {
            switch model.threads {
            case .loading:
                SkeletonCards(count: 3)
            case .failed(let error):
                Note(strings.errorText(error), tone: .err)
                ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.load() } }
            case .loaded(let list) where list.isEmpty:
                EmptyState(icon: .head, title: strings.t("support.noThreadsTitle"), description: strings.t("support.noThreadsHint"))
            case .loaded(let list):
                ForEach(list, id: \.id) { thread in
                    SupportThreadCard(thread: thread) { onOpen(thread.id) }
                }
                // BOSQICH 05: where a booking's chat comes from, under the list too.
                Note(strings.t("support.noThreadsHint"), tone: .gray)
            }
        } footer: {
            EmptyView()
        }
        .refreshable { await model.load() }
        .task { await model.load() }
    }
}

/// One operator chat as a card: "Operator bilan yozishma", its status badge, "N ta xabar · date".
struct SupportThreadCard: View {
    let thread: SupportThreadDTO
    let action: () -> Void
    @Environment(LocaleStore.self) private var strings

    var body: some View {
        ItemCard(title: strings.t("support.threadTitle"),
                 badge: (strings.t(SupportStatus.key(thread)), SupportText.threadTone(thread)),
                 sub: strings.t("support.threadMeta", ("count", thread.messageCount), ("date", strings.dateOnly(thread.createdAt) ?? "")),
                 action: action)
    }
}

// MARK: - Bloklanganlar va shikoyatlarim

/// Web `BlockAndReportPanel`: who the client blocked (with an honest "Chiqarish") and the reports it sent.
struct SafetyCenterView: View {
    let model: SafetyCenterModel
    /// The client's confirm says what unblocking means for its listings; the driver's has no such line.
    var clientCopy = true
    let onBack: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(BannerCenter.self) private var banners: BannerCenter?
    @State private var confirming: BlockDTO?

    var body: some View {
        ScreenScaffold(title: strings.t("safety.centerTitle"), backLabel: strings.t("common.back"), onBack: onBack) {
            Note(strings.t("safety.centerDescription"), tone: .gray)
            SectionTitle(strings.t("client.safety.blocksTitle"))
            blocks
            SectionTitle(strings.t("blockReport.myReportsTitle"))
            reports
        } footer: {
            EmptyView()
        }
        .refreshable { await model.load() }
        .task { await model.load() }
        .overlay {
            if let block = confirming {
                // BOSQICH 05: unblocking is not destructive - the primary button. No name (the block has only an id).
                DialogOverlay(dismissLabel: strings.t("common.cancel")) { confirming = nil } content: {
                    Heading(strings.t("client.profile.unblockTitle"), subtitle: clientCopy ? strings.t("client.profile.unblockText") : nil)
                    HStack(spacing: 10) {
                        ElchiButton(strings.t("blockReport.unblock"), variant: .primary, size: .pair) {
                            confirming = nil
                            Task {
                                if await model.unblock(block) {
                                    banners?.show(.key("client.profile.unblocked"), tone: .ok, hideAfter: .seconds(3))
                                }
                            }
                        }
                        .accessibilityIdentifier("elchi.unblock.confirm")
                        ElchiButton(strings.t("confirmDialog.back"), variant: .neutral, size: .pair) { confirming = nil }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var blocks: some View {
        switch model.blocks {
        case .loading:
            SkeletonCards(count: 1)
        case .failed(let error):
            Note(strings.errorText(error), tone: .err)
        case .loaded(let list) where list.isEmpty:
            Text(strings.t("blockReport.blocksEmpty")).font(ElchiFont.secondary).foregroundStyle(c.muted)
        case .loaded(let list):
            ElchiList {
                ForEach(Array(list.enumerated()), id: \.element.id) { index, block in
                    HStack(spacing: 12) {
                        ElchiIcon.user.image(size: 18).foregroundStyle(c.accentText)
                            .frame(width: 38, height: 38)
                            .background(c.isDark ? Color(hex: 0x1D2A3A) : Color(hex: 0xEEF4FA), in: Circle())
                        VStack(alignment: .leading, spacing: 1) {
                            Text(strings.t("blockReport.subject.user")).font(ElchiFont.poppins(14, .semibold)).foregroundStyle(c.text)
                            Text(strings.blockedAt(block.createdAt)).font(ElchiFont.caption).foregroundStyle(c.muted)
                        }
                        .accessibilityElement(children: .combine)
                        Spacer(minLength: 0)
                        Button { confirming = block } label: {
                            Group {
                                if model.unblocking == block.userId { ProgressView() } else {
                                    Text(strings.t("blockReport.unblockShort")).font(ElchiFont.poppins(13, .semibold))
                                        .lineLimit(1).fixedSize()
                                }
                            }
                            .foregroundStyle(c.tone(.err).fg)
                            .padding(.horizontal, 14)
                            .frame(minHeight: 44)
                        }
                        .buttonStyle(.plain)
                        .disabled(model.unblocking != nil)
                    }
                    .padding(.horizontal, 14).padding(.vertical, 8)
                    .overlay(alignment: .top) { if index > 0 { Rectangle().fill(c.field).frame(height: 1) } }
                    if let error = model.unblockErrors[block.userId] {
                        Note(strings.t("client.safety.unblockFailed", ("error", strings.errorText(error))), tone: .err)
                            .padding(.horizontal, 10).padding(.bottom, 10)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var reports: some View {
        switch model.reports {
        case .loading:
            SkeletonCards(count: 2)
        case .failed(let error):
            Note(strings.errorText(error), tone: .err)
        case .loaded(let list) where list.isEmpty:
            Text(strings.t("blockReport.myReportsEmpty")).font(ElchiFont.secondary).foregroundStyle(c.muted)
        case .loaded(let list):
            ForEach(list, id: \.id) { report in
                let subject = strings.tOrNil("blockReport.subject.\(report.subjectType.rawValue)") ?? report.subjectType.rawValue
                ItemCard(title: strings.tOrNil("blockReport.reason.\(report.reasonCode.rawValue)") ?? report.reasonCode.rawValue,
                         badge: (strings.tOrNil("blockReport.status.\(report.status.rawValue)") ?? report.status.rawValue, ReportTone.of(report.status)),
                         sub: [subject, strings.dateOnly(report.createdAt)].compactMap { $0 }.joined(separator: " · "))
            }
            if model.reportsCursor != nil {
                ElchiButton(strings.t("blockReport.loadMore"), variant: .ghost, size: .medium, icon: .refresh, loading: model.loadingMore) {
                    Task { await model.loadMoreReports() }
                }
            }
        }
    }
}
