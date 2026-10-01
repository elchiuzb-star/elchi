import SwiftUI

// MARK: - Xabarlar (bron chati)

/// The booking chat: oldest at the top, "Oldingi xabarlar" for older pages, the driver's messages on the left under
/// "Haydovchi", the client's on the right, hidden ones as the operator's line. The composer (quick replies, text,
/// send) only while the chat is writable; a closed chat stays readable. No realtime exists: the newest page is
/// polled while the screen is open and in front, and a "Yangi xabar" pill appears when something arrives while
/// the person reads further up.
struct BookingChatView: View {
    let model: BookingChatModel
    /// When the booking was made: the first line of the conversation ("Kelishuv tuzildi · 27.09, 08:12").
    let agreedAt: Date?
    let onBack: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(\.scenePhase) private var scenePhase
    @State private var draft = ""
    @State private var atBottom = true
    @State private var unseen = false
    @State private var now = Date()

    private static let bottomID = "chat-bottom"

    var body: some View {
        ScrollViewReader { proxy in
            ScreenScaffold(title: strings.t("bookingChat.title"), backLabel: strings.t("common.back"), onBack: onBack) {
                if model.olderCursor != nil {
                    Button { Task { await model.loadOlder() } } label: {
                        HStack(spacing: 6) {
                            if model.loadingOlder { ProgressView() } else { ElchiIcon.chevU.image(size: 16) }
                            Text(strings.t("bookingChat.olderMessages")).font(ElchiFont.poppins(14, .semibold))
                        }
                        .foregroundStyle(c.accentText)
                        .frame(maxWidth: .infinity, minHeight: 44)
                    }
                    .buttonStyle(.plain)
                }
                if let error = model.loadError, model.messages.isEmpty {
                    Note(strings.errorText(error), tone: .err)
                    ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.load() } }
                } else if !model.loaded {
                    SkeletonCards(count: 2)
                } else if model.messages.isEmpty && model.pending.isEmpty {
                    EmptyState(icon: .chat, title: strings.t("bookingChat.emptyTitle"), description: strings.t("bookingChat.emptySubtitle"))
                }
                if model.loaded && model.olderCursor == nil, let agreedAt, !model.messages.isEmpty || !model.pending.isEmpty {
                    ChatBubble(.system, text: "\(strings.t("notification.booking.accepted.title")) · \(DepartureWindow.shortText(agreedAt))")
                }
                ForEach(model.messages, id: \.id) { message in
                    bubble(message).id(message.id)
                }
                ForEach(model.pending) { pending(message: $0) }
                ForEach(model.warnings, id: \.code) { Note(strings.warningText($0), tone: .warn) }
                if let seconds = model.rateLimitLeft(now: now) {
                    Note(strings.t("client.chat.rateLimited", ("seconds", seconds)), tone: .warn)
                }
                if let state = model.state.value, !state.writable {
                    closedNote(state)
                }
                Color.clear.frame(height: 1).id(Self.bottomID)
                    .onAppear { atBottom = true; unseen = false }
                    .onDisappear { atBottom = false }
            } footer: {
                if model.writable { composer(proxy) }
            }
            .overlay(alignment: .bottom) {
                if unseen {
                    Button {
                        unseen = false
                        withAnimation { proxy.scrollTo(Self.bottomID, anchor: .bottom) }
                    } label: {
                        HStack(spacing: 6) {
                            ElchiIcon.chevD.image(size: 16)
                            Text(strings.t("notification.chat.message.created.title")).font(ElchiFont.poppins(13, .semibold))
                        }
                        .foregroundStyle(c.onBrand)
                        .padding(.horizontal, 16).frame(minHeight: 40)
                        .background(c.brand, in: Capsule())
                        .shadow(color: c.shadow, radius: 8, y: 4)
                    }
                    .buttonStyle(.plain)
                    .padding(.bottom, model.writable ? 170 : 24)
                }
            }
            .refreshable { await model.poll() }
            .task {
                await model.load()
                proxy.scrollTo(Self.bottomID, anchor: .bottom)
            }
            .task(id: scenePhase == .active) {
                // Polls only while this screen is open and the app is in front.
                guard scenePhase == .active else { return }
                while !Task.isCancelled {
                    try? await Task.sleep(nanoseconds: BookingChatModel.pollSeconds * 1_000_000_000)
                    if Task.isCancelled { return }
                    await model.poll()
                }
            }
            .task {
                while !Task.isCancelled {
                    try? await Task.sleep(for: .seconds(1))
                    now = Date()
                }
            }
            .onChange(of: model.arrivals) { _, _ in
                if atBottom {
                    withAnimation { proxy.scrollTo(Self.bottomID, anchor: .bottom) }
                } else {
                    unseen = true
                }
            }
            .onChange(of: model.messages.count + model.pending.count) { _, _ in
                if atBottom { withAnimation { proxy.scrollTo(Self.bottomID, anchor: .bottom) } }
            }
        }
    }

    private func bubble(_ message: ChatMessageDTO) -> some View {
        let hidden = message.moderationStatus == .hiddenByStaff
        let kind: ChatBubble.Kind = hidden ? .hidden : message.isMine ? .mine : .theirs
        let label: String? = hidden || message.isMine ? nil : strings.t(message.authorSide == .driver ? "safety.driverTitle" : "support.operator")
        return ChatBubble(kind, text: strings.chatText(message), label: label, time: strings.messageTime(message.createdAt))
    }

    /// "Yuborilmadi: “…” · Qayta urinish" - the same key again.
    @ViewBuilder
    private func pending(message: PendingMessage) -> some View {
        let text = message.text ?? message.quickReply.map { strings.tOrNil("quickReply.\($0.rawValue)") ?? $0.rawValue } ?? ""
        if message.sending {
            ChatBubble(.mine, text: text, time: strings.t("common.sending")).opacity(0.6)
        } else {
            VStack(alignment: .leading, spacing: 8) {
                Note("\(strings.t("bookingChat.notSent", ("text", "“\(text)”")))\(message.error.map { " · \(errorLine($0))" } ?? "")", tone: .err)
                HStack(spacing: 8) {
                    ElchiButton(strings.t("common.retry"), variant: .neutral, size: .pair, icon: .refresh) { Task { await model.retry(message.id) } }
                        .disabled(model.rateLimitLeft(now: now) != nil)
                    ElchiButton(strings.t("client.chat.discard"), variant: .ghost, size: .pair) { model.discard(message.id) }
                }
            }
        }
    }

    private func errorLine(_ error: Error) -> String {
        if let seconds = ChatTimeline.retryAfter(error) { return strings.t("client.chat.rateLimited", ("seconds", seconds)) }
        return strings.errorText(error)
    }

    @ViewBuilder
    private func closedNote(_ state: ChatThreadDTO) -> some View {
        if let until = ServerTime.parse(state.writableUntil) {
            ChatBubble(.system, text: "\(strings.t("chat.closesSoon")) \(DepartureWindow.shortText(until))")
        }
        Note(strings.t("chat.closedBody"), tone: .gray, title: strings.t("chat.closedTitle"))
    }

    private func composer(_ proxy: ScrollViewProxy) -> some View {
        let limited = model.rateLimitLeft(now: now) != nil
        return VStack(alignment: .leading, spacing: 8) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(ChatTimeline.clientQuickReplies, id: \.rawValue) { code in
                        Button { Task { await model.send(quickReply: code) } } label: {
                            Text(strings.t("quickReply.\(code.rawValue)")).font(ElchiFont.poppins(13, .medium)).foregroundStyle(c.softText)
                                .padding(.horizontal, 14).frame(minHeight: 36)
                                .background(c.soft, in: Capsule())
                        }
                        .buttonStyle(.plain)
                        .disabled(limited)
                    }
                }
            }
            HStack(spacing: 8) {
                TextField("", text: $draft, prompt: Text(strings.t("bookingChat.placeholder")).foregroundStyle(c.placeholder), axis: .vertical)
                    .lineLimit(1...4)
                    .font(ElchiFont.poppins(14))
                    .foregroundStyle(c.text)
                    .tint(c.brand)
                    .padding(.horizontal, 18).padding(.vertical, 12)
                    .frame(minHeight: 48)
                    .background(c.field, in: RoundedRectangle(cornerRadius: 24))
                    .accessibilityLabel(strings.t("bookingChat.placeholder"))
                Button {
                    let text = draft
                    draft = ""
                    Task { await model.send(text: text) }
                } label: {
                    ElchiIcon.send.image(size: 20).foregroundStyle(c.onBrand)
                        .frame(width: 48, height: 48)
                        .background(c.brand, in: Circle())
                }
                .buttonStyle(.plain)
                .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || limited)
                .opacity(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? 0.5 : 1)
                .accessibilityLabel(strings.t("common.send"))
            }
            Text(strings.t("bookingChat.autoMaskNote")).font(ElchiFont.poppins(11)).foregroundStyle(c.muted)
            // After the booking ends the chat stays writable for 24 h (Q83): say until when.
            if let until = ServerTime.parse(model.state.value?.writableUntil) {
                Text("\(strings.t("chat.closesSoon")) \(DepartureWindow.shortText(until))").font(ElchiFont.poppins(11)).foregroundStyle(c.muted)
            }
        }
    }
}

// MARK: - Yordam / shikoyat

/// The operator chat about this booking (Q141): the thread's status line, "Javob vaqti va'da qilinmaydi…", the
/// messages (operator replies framed in brand azure), a text composer. Nothing exists until the first message; a
/// closed thread says so and "Yangi murojaat" starts another. Polled while open. Never a support phone (Q87).
struct SupportChatView: View {
    let model: SupportChatModel
    let onBack: () -> Void
    /// "Operator bilan yozishma" when opened from "Murojaatlarim"; the booking's own button says "Yordam / shikoyat".
    var title: String?
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(\.scenePhase) private var scenePhase
    @State private var draft = ""
    @State private var startingNew = false

    private static let bottomID = "support-bottom"

    var body: some View {
        let thread = model.current
        let closed = SupportStatus.isClosed(thread)
        ScrollViewReader { proxy in
            ScreenScaffold(title: title ?? strings.t("support.complain"), backLabel: strings.t("common.back"), onBack: onBack,
                           showsFooter: !closed || startingNew) {
                switch model.thread {
                case .loading:
                    SkeletonCards(count: 2)
                case .failed(let error):
                    Note(strings.errorText(error), tone: .err)
                    ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.load() } }
                case .loaded:
                    if let thread {
                        ElchiCard {
                            CardRow(strings.t("support.statusLabel"), strings.t(SupportStatus.key(thread)), first: true,
                                    detail: strings.t("support.noPromise"))
                        }
                        ForEach(sorted(thread), id: \.id) { message in
                            let kind: ChatBubble.Kind = message.author == "me" ? .mine : message.author == "operator" ? .operatorReply : .system
                            ChatBubble(kind, text: message.text, label: message.author == "operator" ? strings.t("support.operator") : nil,
                                       time: strings.messageTime(message.createdAt))
                        }
                        if closed && !startingNew {
                            Note(strings.t("client.support.closedText"), tone: .gray, title: strings.t("chat.closedTitle"))
                            ElchiButton(strings.t("client.support.newThread"), variant: .soft, icon: .plus) { startingNew = true }
                        }
                    } else {
                        Note(strings.t("support.noPromise"), tone: .gray)
                        EmptyState(icon: .head, title: strings.t("support.threadTitle"), description: strings.t("support.emptyThread"))
                    }
                    ForEach(model.warnings, id: \.code) { Note(strings.warningText($0), tone: .warn) }
                    if let error = model.sendError, !model.sending { Note(strings.errorText(error), tone: .err) }
                }
                Color.clear.frame(height: 1).id(Self.bottomID)
            } footer: {
                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 8) {
                        TextField("", text: $draft, prompt: Text(strings.t("support.messagePlaceholder")).foregroundStyle(c.placeholder), axis: .vertical)
                            .lineLimit(1...5)
                            .font(ElchiFont.poppins(14))
                            .foregroundStyle(c.text)
                            .tint(c.brand)
                            .padding(.horizontal, 18).padding(.vertical, 12)
                            .frame(minHeight: 48)
                            .background(c.field, in: RoundedRectangle(cornerRadius: 24))
                            .accessibilityLabel(strings.t("support.draftLabel"))
                        Button {
                            let text = draft
                            Task {
                                if await model.send(text) {
                                    draft = ""
                                    startingNew = false
                                    withAnimation { proxy.scrollTo(Self.bottomID, anchor: .bottom) }
                                }
                            }
                        } label: {
                            Group {
                                if model.sending { ProgressView().tint(c.onBrand) } else { ElchiIcon.send.image(size: 20) }
                            }
                            .foregroundStyle(c.onBrand)
                            .frame(width: 48, height: 48)
                            .background(c.brand, in: Circle())
                        }
                        .buttonStyle(.plain)
                        .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.sending)
                        .opacity(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? 0.5 : 1)
                        .accessibilityLabel(strings.t("support.send"))
                    }
                    Text(strings.t("bookingChat.autoMaskNote")).font(ElchiFont.poppins(11)).foregroundStyle(c.muted)
                }
            }
            .refreshable { await model.load() }
            .task {
                await model.load()
                proxy.scrollTo(Self.bottomID, anchor: .bottom)
            }
            .task(id: scenePhase == .active) {
                guard scenePhase == .active else { return }
                while !Task.isCancelled {
                    try? await Task.sleep(nanoseconds: SupportChatModel.pollSeconds * 1_000_000_000)
                    if Task.isCancelled { return }
                    if model.current != nil && !SupportStatus.isClosed(model.current) { await model.load() }
                }
            }
            .onChange(of: model.current?.messageCount) { _, _ in
                withAnimation { proxy.scrollTo(Self.bottomID, anchor: .bottom) }
            }
        }
    }

    private func sorted(_ thread: SupportThreadDTO) -> [SupportMessageDTO] {
        (thread.messages ?? []).filter { $0.staffOnly != true }.sorted {
            (ServerTime.parse($0.createdAt) ?? .distantPast, $0.id) < (ServerTime.parse($1.createdAt) ?? .distantPast, $1.id)
        }
    }
}
