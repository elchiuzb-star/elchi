import Foundation
import Observation

// MARK: - Notifications

/// "Bildirishnomalar" (N4, Q82: the only delivery channel in the pilot) and the unread dot on the menu. The v2 inbox
/// has no unread-count or read-all endpoint: the dot is the first page of unread items, asked when home appears and
/// when the drawer opens (no timer).
@MainActor @Observable
final class InboxModel {
    private let api: ElchiAPI

    private(set) var items: Loadable<[NotificationDTO]> = .loading
    private(set) var cursor: String?
    private(set) var loadingMore = false
    /// Unread items as last seen (the first unread page), and whether there are more than that.
    private(set) var unread = 0
    private(set) var unreadMore = false

    static let pageSize = 30

    init(api: ElchiAPI) { self.api = api }

    func load() async {
        do {
            let page = try await api.listNotifications(limit: Self.pageSize)
            items = .loaded(page.data)
            cursor = page.meta?.nextCursor
        } catch {
            if items.value == nil { items = .failed(error) }
        }
        await refreshUnread()
    }

    /// "Yana yuklash": the next older page.
    func loadMore() async {
        guard let cursor, !loadingMore, let current = items.value else { return }
        loadingMore = true
        defer { loadingMore = false }
        guard let page = try? await api.listNotifications(cursor: cursor, limit: Self.pageSize) else { return }
        items = .loaded(current + page.data.filter { item in !current.contains { $0.id == item.id } })
        self.cursor = page.meta?.nextCursor
    }

    /// The dot and count on the menu. A failure keeps what was known.
    func refreshUnread() async {
        guard let page = try? await api.listNotifications(unread: true, limit: Self.pageSize) else { return }
        unread = Inbox.unreadCount(page.data)
        unreadMore = page.meta?.nextCursor != nil
    }

    /// Tapping an unread item marks it read (errors are ignored: the row is updated here either way).
    func markRead(_ item: NotificationDTO) {
        guard !item.isRead, var list = items.value, let index = list.firstIndex(where: { $0.id == item.id }) else { return }
        list[index].isRead = true
        items = .loaded(list)
        unread = max(0, unread - 1)
        let api = api
        Task { _ = try? await api.readNotification(notificationId: item.id) }
    }

    /// "Hammasini o'qilgan deb belgilash": v2 has no read-all, so every loaded unread row is marked one by one (at most
    /// a page; a failure is ignored - the row is read here either way and the count is asked again after).
    func readAll() async {
        guard var list = items.value else { return }
        let unreadRows = list.filter { !$0.isRead }.prefix(Self.pageSize)
        guard !unreadRows.isEmpty else { return }
        for index in list.indices where !list[index].isRead { list[index].isRead = true }
        items = .loaded(list)
        unread = 0
        unreadMore = false
        let api = api
        await withTaskGroup(of: Void.self) { group in
            for row in unreadRows { group.addTask { _ = try? await api.readNotification(notificationId: row.id) } }
        }
        await refreshUnread()
    }

    /// The listing a negotiation belongs to, for a `/proposals/{id}` link.
    func listingId(ofProposal id: String) async -> String? {
        try? await api.getProposal(threadId: id).data.listingId
    }
}

// MARK: - Profile

/// "Profil": the avatar block, figures derived from v2 (first pages, limit 50) and the name form. The name goes
/// through v1 and then `/auth/me` into the stored session, so the drawer and home show it at once.
@MainActor @Observable
final class ProfileModel {
    private let api: ElchiAPI
    private let profileAPI: ClientProfileAPI
    private let auth: AuthAPI
    private let sessions: SessionStorage

    /// nil inside `.failed` means "—" on every figure (never zeros).
    private(set) var stats: Loadable<ProfileStats> = .loading
    var name: String
    private(set) var saving = false
    /// `clientProfile.updated`, or the failure sentence.
    private(set) var saveResult: Result<Void, Error>?

    static let pageSize = 50

    init(api: ElchiAPI, profileAPI: ClientProfileAPI, auth: AuthAPI, sessions: SessionStorage) {
        self.api = api
        self.profileAPI = profileAPI
        self.auth = auth
        self.sessions = sessions
        name = sessions.current()?.user.fullName ?? ""
    }

    func loadStats() async {
        do {
            async let listings = api.listMyListings(kind: .request, serviceType: .parcel, limit: Self.pageSize)
            async let bookings = api.listMyBookings(role: "client", limit: Self.pageSize)
            async let threads = api.listMyProposals(state: "open", limit: Self.pageSize)
            let (l, b, t) = try await (listings, bookings, threads)
            stats = .loaded(ProfileStats.derive(listings: l.data, bookings: b.data.compactMap(ClientBookingDTO.from), threads: t.data))
        } catch {
            if stats.value == nil { stats = .failed(error) }
        }
    }

    var canSave: Bool {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        return !trimmed.isEmpty && trimmed != (sessions.current()?.user.fullName ?? "") && !saving
    }

    func clearResult() { saveResult = nil }

    func save() async {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !saving else { return }
        saving = true
        saveResult = nil
        defer { saving = false }
        do {
            let profile = try await profileAPI.updateName(trimmed)
            name = profile.fullName ?? trimmed
            // The stored session carries the name the drawer and home show: re-read it from the server (or, if that
            // read fails, keep the name the server just stored).
            if let session = sessions.current() {
                let user = (try? await auth.me())
                    ?? AuthUser(id: session.user.id, phone: session.user.phone, fullName: name, role: session.user.role, status: session.user.status)
                sessions.save(Session(accessToken: session.accessToken, refreshToken: session.refreshToken, user: user))
                name = user.fullName ?? name
            }
            saveResult = .success(())
        } catch {
            saveResult = .failure(error)
        }
    }
}

// MARK: - Bonus

/// "Bonuslar va taklif kodi" (ADR-0023, Q101-Q103): the client's discount rights (never money), the referral code and
/// the code entry, read-only campaigns. With `promotions_enabled` off the code, entry and campaigns go and one
/// sentence says the programme is off; the balance still shows. Joining offers is out of this stage (Q131/Q147).
@MainActor @Observable
final class BonusModel {
    private let api: ElchiAPI
    private let keys: ActionKeys

    private(set) var balance: Loadable<PromoBalanceDTO> = .loading
    private(set) var code: ReferralCodeDTO?
    private(set) var codeError: Error?
    private(set) var referrals: Loadable<MyReferralsDTO> = .loading
    /// `403 FEATURE_DISABLED` from any programme call.
    private(set) var programOff = false
    private(set) var loadedCode = false

    var entered = "" { didSet { if entered != oldValue { entered = ReferralCode.typed(entered); enterError = nil } } }
    private(set) var entering = false
    private(set) var enterError: Error?
    private(set) var accepted = false

    /// The code kept from an `elchigo.uz/r/<code>` link: it fills the field and goes after a final server answer.
    private let links: DeepLinkCenter?
    /// `client` (Stage 05: the passenger bonus) or `driver` (Stage 09: the driver credit).
    let audience: String

    init(api: ElchiAPI, keys: ActionKeys, links: DeepLinkCenter? = nil, audience: String = "client") {
        self.api = api
        self.keys = keys
        self.links = links
        self.audience = audience
    }

    func load() async {
        if entered.isEmpty, let kept = links?.referralCode { entered = kept }
        async let balance: Void = loadBalance()
        async let code: Void = loadCode()
        async let referrals: Void = loadReferrals()
        _ = await (balance, code, referrals)
    }

    private func loadBalance() async {
        do {
            balance = .loaded(try await api.myPromoBalance().data)
        } catch {
            if balance.value == nil { balance = .failed(error) }
        }
    }

    /// The code is the client's own and stable; asking again returns the same one (one key per screen visit).
    private func loadCode() async {
        let action = "referral-code"
        do {
            code = try await api.myReferralCode(idempotencyKey: keys.key(action)).data
            keys.settle(action)
            codeError = nil
        } catch {
            keys.settle(action, after: error)
            if PromoLogic.isProgramOff(error) { programOff = true } else { codeError = error }
        }
        loadedCode = true
    }

    private func loadReferrals() async {
        do {
            referrals = .loaded(try await api.myReferrals().data)
            // Already attributed (the first attribution is final): a kept link code has nothing left to do.
            if hasAttribution, links?.referralCode != nil {
                links?.forgetReferral()
                entered = ""
            }
        } catch {
            if PromoLogic.isProgramOff(error) { programOff = true }
            if referrals.value == nil { referrals = .failed(error) }
        }
    }

    var buckets: [PromoBucketDTO] { balance.value.map { PromoLogic.buckets($0, audience: audience) } ?? [] }

    /// The entry field goes once a code has been accepted for this person (the first attribution is final).
    var hasAttribution: Bool { referrals.value?.attributions.contains { $0.audience == audience } == true || accepted }

    var normalized: String? { ReferralCode.normalize(entered) }

    func submitCode() async {
        guard let code = normalized, !entering else { return }
        let action = "attribute:\(audience):\(code)"
        entering = true
        enterError = nil
        defer { entering = false }
        do {
            _ = try await api.attribute(body: AttributionRequest(audience: audience, code: code), idempotencyKey: keys.key(action))
            keys.settle(action)
            accepted = true
            entered = ""
            links?.forgetReferral()
            await loadReferrals()
        } catch {
            keys.settle(action, after: error)
            if PromoLogic.isProgramOff(error) { programOff = true } else { enterError = error }
            // Invalid / not eligible / already attributed is final for the kept code; off, offline or 5xx is not.
            if code == links?.referralCode, ReferralOutcome.decision(error) == .forget { links?.forgetReferral() }
        }
    }
}

// MARK: - Safety centre

/// "Bloklanganlar va shikoyatlarim": the people the client blocked and the reports it sent. Unblocking is honest:
/// the backend's DELETE currently refuses every call (`IDEMPOTENCY_KEY_REQUIRED` although a key is sent), so a failure
/// keeps the row and says why - never a faked success.
@MainActor @Observable
final class SafetyCenterModel {
    private let api: ElchiAPI
    private let keys: ActionKeys

    private(set) var blocks: Loadable<[BlockDTO]> = .loading
    private(set) var reports: Loadable<[ReportDTO]> = .loading
    private(set) var reportsCursor: String?
    private(set) var loadingMore = false
    private(set) var unblocking: String?
    private(set) var unblockErrors: [String: Error] = [:]

    static let pageSize = 20

    init(api: ElchiAPI, keys: ActionKeys) {
        self.api = api
        self.keys = keys
    }

    func load() async {
        async let blocks: Void = loadBlocks()
        async let reports: Void = loadReports()
        _ = await (blocks, reports)
    }

    private func loadBlocks() async {
        do {
            blocks = .loaded(try await api.listBlocks().data)
        } catch {
            if blocks.value == nil { blocks = .failed(error) }
        }
    }

    private func loadReports() async {
        do {
            let page = try await api.listMyReports(limit: Self.pageSize)
            reports = .loaded(page.data)
            reportsCursor = page.meta?.nextCursor
        } catch {
            if reports.value == nil { reports = .failed(error) }
        }
    }

    func loadMoreReports() async {
        guard let cursor = reportsCursor, !loadingMore, let current = reports.value else { return }
        loadingMore = true
        defer { loadingMore = false }
        guard let page = try? await api.listMyReports(cursor: cursor, limit: Self.pageSize) else { return }
        reports = .loaded(current + page.data.filter { item in !current.contains { $0.id == item.id } })
        reportsCursor = page.meta?.nextCursor
    }

    func unblock(_ block: BlockDTO) async {
        guard unblocking == nil else { return }
        let action = "unblock:\(block.userId)"
        unblocking = block.userId
        unblockErrors[block.userId] = nil
        defer { unblocking = nil }
        do {
            _ = try await api.deleteBlock(blockedUserId: block.userId, idempotencyKey: keys.key(action))
            keys.settle(action)
            if case .loaded(let list) = blocks { blocks = .loaded(list.filter { $0.userId != block.userId }) }
        } catch {
            keys.settle(action, after: error)
            unblockErrors[block.userId] = error
        }
    }
}

// MARK: - Support

/// "Yordam": who can be reached (S13 - in the pilot nobody by phone, Q87), a ticket form and the client's tickets.
/// Contacts fail quietly: a missing answer reads as "no line", which is also the truthful pilot answer.
@MainActor @Observable
final class SupportModel {
    private let api: ElchiAPI
    private let keys: ActionKeys

    private(set) var contacts: SupportContactsDTO?
    private(set) var tickets: Loadable<[SupportTicketDTO]> = .loading
    var draft = "" { didSet { if draft != oldValue { sendError = nil; sent = false } } }
    private(set) var sending = false
    private(set) var sendError: Error?
    private(set) var sent = false

    init(api: ElchiAPI, keys: ActionKeys) {
        self.api = api
        self.keys = keys
    }

    func load() async {
        async let contacts: Void = loadContacts()
        async let tickets: Void = loadTickets()
        _ = await (contacts, tickets)
    }

    private func loadContacts() async {
        contacts = try? await api.supportContacts().data
    }

    private func loadTickets() async {
        do {
            tickets = .loaded(try await api.listMyTickets(limit: 20).data)
        } catch {
            if tickets.value == nil { tickets = .failed(error) }
        }
    }

    /// The phone to call, only when the server says a line is available (Q87).
    var phone: String? {
        guard let contacts, contacts.available, let phone = contacts.phone, !phone.isEmpty else { return nil }
        return phone
    }

    var canSend: Bool { SupportText.canSend(draft) && !sending }

    func send() async {
        let message = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard SupportText.canSend(message), !sending else { return }
        let action = "ticket:\(message)"
        sending = true
        sendError = nil
        defer { sending = false }
        do {
            let ticket = try await api.createSupportTicket(body: SupportTicketCreate(bookingId: nil, kind: .support, message: String(message.prefix(4000))),
                                                           idempotencyKey: keys.key(action)).data
            keys.settle(action)
            draft = ""
            sent = true
            if case .loaded(let list) = tickets { tickets = .loaded([ticket] + list.filter { $0.id != ticket.id }) } else { await loadTickets() }
        } catch {
            keys.settle(action, after: error)
            sendError = error
        }
    }
}

/// "Murojaatlarim": the client's operator chats (one per booking it asked about), newest first.
@MainActor @Observable
final class SupportThreadsModel {
    private let api: ElchiAPI
    private(set) var threads: Loadable<[SupportThreadDTO]> = .loading

    init(api: ElchiAPI) { self.api = api }

    func load() async {
        do {
            let list = try await api.listMySupportThreads(limit: 50).data
            threads = .loaded(list.sorted { (ServerTime.parse($0.createdAt) ?? .distantPast) > (ServerTime.parse($1.createdAt) ?? .distantPast) })
        } catch {
            if threads.value == nil { threads = .failed(error) }
        }
    }
}

// MARK: - Account deletion

/// "Akkauntni o'chirish": `DELETE /me` after an explicit tick. The server anonymises at once and revokes every token;
/// `409 ACCOUNT_DELETION_BLOCKED` lists what is still open.
@MainActor @Observable
final class AccountDeleteModel {
    private let api: ElchiAPI
    private let keys: ActionKeys

    var confirmed = false
    private(set) var submitting = false
    private(set) var blockers: [DeletionBlocker]?
    private(set) var error: Error?

    init(api: ElchiAPI, keys: ActionKeys) {
        self.api = api
        self.keys = keys
    }

    /// True when the account is gone.
    func submit() async -> Bool {
        guard confirmed, !submitting else { return false }
        let action = "delete-me"
        submitting = true
        blockers = nil
        error = nil
        defer { submitting = false }
        do {
            _ = try await api.deleteMe(body: AccountDeletionRequest(), idempotencyKey: keys.key(action))
            keys.settle(action)
            return true
        } catch let apiError as APIError where apiError.code == "ACCOUNT_DELETION_BLOCKED" {
            keys.settle(action, after: apiError)
            blockers = DeletionBlocker.lines(apiError.details)
            return false
        } catch {
            keys.settle(action, after: error)
            self.error = error
            return false
        }
    }
}
