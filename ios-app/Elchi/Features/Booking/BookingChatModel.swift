import Foundation
import Observation

// MARK: - Booking chat

/// A message the client wrote that the server has not stored yet: sending, or refused with the reason. A retry sends
/// it again under the same Idempotency-Key (its `id`), so a message that did arrive is never stored twice.
struct PendingMessage: Identifiable {
    let id: String
    let text: String?
    let quickReply: QuickReplyCode?
    var sending: Bool
    var error: Error?
}

/// "Xabarlar": the booking chat (Q100 - the only chat the client opens). No realtime exists: the screen polls the
/// newest page while it is open; older pages come on request. `writable=false` = closed, read only.
@MainActor @Observable
final class BookingChatModel {
    let bookingId: String
    private let api: ElchiAPI

    private(set) var state: Loadable<ChatThreadDTO> = .loading
    /// Oldest first, each message once.
    private(set) var messages: [ChatMessageDTO] = []
    private(set) var pending: [PendingMessage] = []
    private(set) var loaded = false
    private(set) var loadError: Error?
    /// The cursor of the next older page (`meta.next_cursor`), nil when the first message is on screen.
    private(set) var olderCursor: String?
    private(set) var loadingOlder = false
    /// What the server said about the last message sent (`CONTACT_INFO_MASKED`).
    private(set) var warnings: [ApiWarning] = []
    /// `RATE_LIMITED`: sending waits until then.
    private(set) var rateLimitedUntil: Date?
    /// Bumped whenever a poll brings messages from the driver the phone did not have ("Yangi xabar").
    private(set) var arrivals = 0

    static let pageSize = 30
    static let pollSeconds: UInt64 = 12

    init(bookingId: String, api: ElchiAPI) {
        self.bookingId = bookingId
        self.api = api
    }

    /// The thread's state first (the composer is drawn only for a writable chat), then the newest page.
    func load() async {
        async let state: Void = loadState()
        async let page: Void = loadNewest(first: !loaded)
        _ = await (state, page)
    }

    private func loadState() async {
        do {
            state = .loaded(try await api.getBookingChatState(bookingId: bookingId).data)
        } catch {
            if state.value == nil { state = .failed(error) }
        }
    }

    private func loadNewest(first: Bool) async {
        do {
            let page = try await api.listBookingMessages(bookingId: bookingId, limit: Self.pageSize)
            let fresh = ChatTimeline.newFromOthers(messages, page.data)
            messages = ChatTimeline.merge(messages, page.data)
            if first { olderCursor = page.meta?.nextCursor }
            loaded = true
            loadError = nil
            if !first && fresh > 0 { arrivals += 1 }
        } catch {
            if !loaded { loadError = error }
        }
    }

    /// One poll: the newest page and the thread state (it closes 24 h after the booking ends).
    func poll() async {
        async let state: Void = loadState()
        async let page: Void = loadNewest(first: false)
        _ = await (state, page)
    }

    /// "Oldingi xabarlar".
    func loadOlder() async {
        guard let cursor = olderCursor, !loadingOlder else { return }
        loadingOlder = true
        defer { loadingOlder = false }
        if let page = try? await api.listBookingMessages(bookingId: bookingId, cursor: cursor, limit: Self.pageSize) {
            messages = ChatTimeline.merge(messages, page.data)
            olderCursor = page.meta?.nextCursor
        }
    }

    var writable: Bool { state.value?.writable == true }

    /// Seconds left of a rate limit, nil when sending is allowed.
    func rateLimitLeft(now: Date = Date()) -> Int? {
        guard let until = rateLimitedUntil, until > now else { return nil }
        return Int(until.timeIntervalSince(now).rounded(.up))
    }

    func send(text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        await enqueue(PendingMessage(id: UUID().uuidString, text: String(trimmed.prefix(1000)), quickReply: nil, sending: true))
    }

    func send(quickReply: QuickReplyCode) async {
        await enqueue(PendingMessage(id: UUID().uuidString, text: nil, quickReply: quickReply, sending: true))
    }

    /// "Qayta urinish" on a refused message: the same key again.
    func retry(_ id: String) async {
        guard let index = pending.firstIndex(where: { $0.id == id }), !pending[index].sending else { return }
        pending[index].sending = true
        pending[index].error = nil
        await deliver(id)
    }

    func discard(_ id: String) {
        pending.removeAll { $0.id == id }
    }

    private func enqueue(_ message: PendingMessage) async {
        pending.append(message)
        await deliver(message.id)
    }

    private func deliver(_ id: String) async {
        guard let message = pending.first(where: { $0.id == id }) else { return }
        do {
            let result = try await api.postBookingMessage(bookingId: bookingId,
                                                          body: ChatMessageCreate(quickReplyCode: message.quickReply, text: message.text),
                                                          idempotencyKey: message.id)
            pending.removeAll { $0.id == id }
            messages = ChatTimeline.merge(messages, [result.data])
            warnings = result.warnings
            rateLimitedUntil = nil
        } catch {
            if let index = pending.firstIndex(where: { $0.id == id }) {
                pending[index].sending = false
                pending[index].error = error
            }
            if let seconds = ChatTimeline.retryAfter(error) { rateLimitedUntil = Date().addingTimeInterval(TimeInterval(seconds)) }
            // Closed meanwhile (the booking ended and 24 h passed): the screen turns read-only.
            if (error as? APIError)?.code == "CHAT_CLOSED" { await loadState() }
        }
    }
}

// MARK: - Support chat

/// "Yordam / shikoyat" (Q141/Q146): the client's own operator chat about a booking - one open thread per booking
/// and requester, text only. Nothing exists until the first message; a closed thread stays readable and "Yangi
/// murojaat" opens a new one. No phone, no promised reply time (Q87). Opened from the booking (by booking id) or from
/// "Murojaatlarim" and a notification (by thread id; the booking is then read from the thread).
@MainActor @Observable
final class SupportChatModel {
    /// Known from the start when opened from the booking, from the thread otherwise.
    private(set) var bookingId: String?
    /// The thread this screen follows when opened by id; moves to the new one after "Yangi murojaat".
    private var threadId: String?
    private let api: ElchiAPI
    private let keys: ActionKeys

    /// `nil` inside `.loaded` = no thread yet.
    private(set) var thread: Loadable<SupportThreadDTO?> = .loading
    private(set) var sending = false
    private(set) var sendError: Error?
    private(set) var warnings: [ApiWarning] = []

    static let pollSeconds: UInt64 = 15

    init(bookingId: String, api: ElchiAPI, keys: ActionKeys) {
        self.bookingId = bookingId
        self.api = api
        self.keys = keys
    }

    init(threadId: String, api: ElchiAPI, keys: ActionKeys) {
        self.threadId = threadId
        self.api = api
        self.keys = keys
    }

    func load() async {
        do {
            let current: SupportThreadDTO? = if let threadId {
                try await api.getSupportThread(threadId: threadId).data
            } else if let bookingId {
                try await api.getBookingSupportThread(bookingId: bookingId).data
            } else {
                nil
            }
            // A poll never replaces a thread with an older answer (a send may have finished meanwhile).
            if let known = thread.value ?? nil, let current, known.id == current.id, current.version < known.version { return }
            if bookingId == nil { bookingId = current?.bookingId }
            thread = .loaded(current)
        } catch {
            if thread.value == nil { thread = .failed(error) }
        }
    }

    var current: SupportThreadDTO? { thread.value ?? nil }

    /// The first message opens the thread (idempotent open-or-return); later ones go to it. After a closed thread,
    /// the next message opens a new one for the same booking.
    func send(_ text: String) async -> Bool {
        let body = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !body.isEmpty, !sending else { return false }
        let open = current.flatMap { SupportStatus.isClosed($0) ? nil : $0 }
        guard let target = open?.id ?? bookingId else { return false }
        let action = "support:\(target):\(open == nil ? "new" : "reply"):\(body)"
        sending = true
        sendError = nil
        defer { sending = false }
        do {
            let key = keys.key(action)
            let result = if let open {
                try await api.postSupportMessage(threadId: open.id, body: SupportMessageCreate(text: String(body.prefix(4000))), idempotencyKey: key)
            } else {
                try await api.openSupportThread(bookingId: target, body: SupportThreadOpen(text: String(body.prefix(4000))), idempotencyKey: key)
            }
            keys.settle(action)
            thread = .loaded(result.data)
            if threadId != nil { threadId = result.data.id }
            warnings = result.warnings
            return true
        } catch {
            keys.settle(action, after: error)
            sendError = error
            if (error as? APIError)?.code == "SUPPORT_THREAD_CLOSED" { await load() }
            return false
        }
    }
}
