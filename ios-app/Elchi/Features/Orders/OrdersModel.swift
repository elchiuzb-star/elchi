import Foundation
import Observation

/// Offers on one listing, as the orders list summarises them: how many are open and when the newest one came.
struct OfferStats: Hashable, Sendable {
    let open: Int
    let newest: Date?
}

/// Stage 03, signed in as a client: the orders screen (bookings, the client's listings, legacy v1 orders) and the
/// models behind a listing's detail, edit and offers screens. One instance per signed-in client; a listing's model
/// lives for the session and is reset each time the listing is opened from the list.
@MainActor @Observable
final class ClientOrdersModel {
    private let api: ElchiAPI
    private let legacyAPI: LegacyOrdersAPI
    /// The app's banner: legacy (v1) results and refusals are said there.
    let banners: BannerCenter
    /// Resolves the signed photo links the API returns as paths on its own host.
    let mediaURL: @Sendable (String) -> URL?
    let keys = ActionKeys()

    private(set) var bookings: Loadable<[ClientBookingDTO]> = .loading
    private(set) var listings: Loadable<[ListingDTO]> = .loading
    private(set) var legacy: Loadable<[LegacyOrder]> = .loading
    private(set) var stats: [String: OfferStats] = [:]
    private var bookingsCursor: String?
    private var listingsCursor: String?
    /// The next v1 page to ask for, or nil when the last one was read (v1 pages by number, not cursor).
    private var legacyNextPage: Int?
    /// v1 rows per page (a UI test shrinks it to show paging with a handful of orders).
    var legacyPageSize = LegacyOrdersAPI.pageSize
    /// All the client's v1 orders (`pagination.total`), for "Eski buyurtmalar (N)"; nil until the first page.
    private(set) var legacyTotal: Int?
    private(set) var loadingMoreLegacy = false
    /// Bumped by every `loadMore`, so the list's end marker asks again while pages remain.
    private(set) var pageMarker = 0
    private(set) var loadingMore = false
    /// The last refresh failed for a section that still shows what it had: the list says it may be out of date.
    private(set) var stale = false
    /// A short ok strip on the orders screen after something finished elsewhere ("Haydovchi tanlandi").
    var banner: String?

    private var details: [String: ListingModel] = [:]
    private var bookingModels: [String: BookingModel] = [:]
    private var legacyModels: [Int: LegacyOrderModel] = [:]
    private let connection: TrackingConnection
    let proposals: ProposalsModel

    /// How many listings get their offers counted: the visible top of the list, in parallel.
    static let statsLimit = 10

    init(api: ElchiAPI, legacyAPI: LegacyOrdersAPI, mediaURL: @escaping @Sendable (String) -> URL?, banners: BannerCenter = BannerCenter(),
         connection: TrackingConnection = TrackingConnection(socketURL: nil, accessToken: { nil })) {
        self.api = api
        self.legacyAPI = legacyAPI
        self.banners = banners
        self.mediaURL = mediaURL
        self.connection = connection
        proposals = ProposalsModel(api: api, keys: keys)
        proposals.attach(self)
    }

    // MARK: List

    /// Everything on the orders screen, each section on its own: one failing never blanks the others.
    func refresh() async {
        async let bookings = loadBookings()
        async let listings = loadListings()
        async let legacy = loadLegacy()
        let fresh = await [bookings, listings, legacy]
        stale = fresh.contains(false)
    }

    /// Each loader answers whether its section is now current; a section that had data keeps it on failure.
    private func loadBookings() async -> Bool {
        do {
            let page = try await api.listMyBookings(role: "client", limit: 30)
            bookings = .loaded(page.data.compactMap(ClientBookingDTO.from))
            bookingsCursor = page.meta?.nextCursor
            return true
        } catch {
            if bookings.value == nil { bookings = .failed(error) }
            return false
        }
    }

    private func loadListings() async -> Bool {
        do {
            let page = try await api.listMyListings(limit: 30)
            listings = .loaded(page.data)
            listingsCursor = page.meta?.nextCursor
            await loadStats(page.data)
            return true
        } catch {
            if listings.value == nil { listings = .failed(error) }
            return false
        }
    }

    /// The first v1 page (the rest come with `loadMore`). A failure keeps the rows shown and says why in the banner
    /// (offline, too many requests).
    private func loadLegacy(announce: Bool = true) async -> Bool {
        do {
            let page = try await legacyAPI.clientOrders(page: 1, limit: legacyPageSize)
            legacy = .loaded(page.items)
            legacyNextPage = page.hasMore ? 2 : nil
            legacyTotal = page.pagination?.total ?? (page.hasMore ? nil : page.items.count)
        } catch let error as APIError where error.status == 403 {
            legacy = .loaded([]) // not a v1 client: there is simply no history to show
            legacyNextPage = nil
            legacyTotal = 0
        } catch {
            if legacy.value == nil { legacy = .failed(error) }
            // The screen went away mid-load (e.g. a link pushed a listing over the list at once): the cancelled
            // request is not "Internet aloqasi yo'q".
            if announce && !Task.isCancelled { banners.error(error) }
            return false
        }
        return true
    }

    /// The drawer's "Eski buyurtmalar" row shows only for a client with v1 orders: the first page is read once,
    /// quietly, when the client flow starts (a failure just leaves the row out until the orders screen loads it).
    func ensureLegacy() async {
        guard legacy.value == nil else { return }
        _ = await loadLegacy(announce: false)
    }

    /// The archive list's next v1 page (BOSQICH 10: the chips filter the loaded pages, so a short filtered list asks
    /// for more). A failure stops paging until pull to refresh.
    func loadMoreLegacy() async {
        guard !loadingMoreLegacy, let next = legacyNextPage, let current = legacy.value else { return }
        loadingMoreLegacy = true
        defer { loadingMoreLegacy = false }
        if let page = try? await legacyAPI.clientOrders(page: next, limit: legacyPageSize) {
            legacy = .loaded(Self.appending(page.items, to: legacy.value ?? current))
            legacyNextPage = page.hasMore ? next + 1 : nil
            if let total = page.pagination?.total { legacyTotal = total }
        } else {
            legacyNextPage = nil
        }
    }

    var legacyHasMore: Bool { legacyNextPage != nil }

    /// How many v1 orders the client has: the server's total, else the rows loaded.
    var legacyCount: Int { legacyTotal ?? legacy.value?.count ?? 0 }

    /// Just the legacy section again (after a v1 command: its row's status changed).
    func refreshLegacy() async {
        _ = await loadLegacy()
    }

    /// The DTO has no offer count: ask each live listing at the top of the list for its open threads, in parallel.
    /// A listing whose call fails just shows no count.
    private func loadStats(_ listings: [ListingDTO]) async {
        let live = listings.filter { $0.status == .published || $0.status == .paused }.prefix(Self.statsLimit)
        let api = api
        let results = await withTaskGroup(of: (String, OfferStats?).self) { group in
            for listing in live {
                group.addTask {
                    guard let threads = try? await api.listListingProposals(listingId: listing.id, state: "open", limit: 100).data else {
                        return (listing.id, nil)
                    }
                    let newest = threads.compactMap { ServerTime.parse($0.currentVersion?.createdAt) }.max()
                    return (listing.id, OfferStats(open: threads.count, newest: newest))
                }
            }
            var out: [(String, OfferStats?)] = []
            for await result in group { out.append(result) }
            return out
        }
        for (id, value) in results { stats[id] = value }
    }

    /// The next page of whichever list has one, when its last row comes on screen.
    func loadMore() async {
        guard !loadingMore, hasMore else { return }
        loadingMore = true
        defer {
            loadingMore = false
            pageMarker += 1
        }
        if let cursor = listingsCursor, let current = listings.value,
           let page = try? await api.listMyListings(cursor: cursor, limit: 30) {
            listings = .loaded(current + page.data.filter { item in !current.contains { $0.id == item.id } })
            listingsCursor = page.meta?.nextCursor
        }
        if let cursor = bookingsCursor, let current = bookings.value,
           let page = try? await api.listMyBookings(role: "client", cursor: cursor, limit: 30) {
            let more = page.data.compactMap(ClientBookingDTO.from)
            bookings = .loaded(current + more.filter { item in !current.contains { $0.id == item.id } })
            bookingsCursor = page.meta?.nextCursor
        }
        // v1 pages are read by the archive screen itself (BOSQICH 10: the orders list shows one row for them).
    }

    var hasMore: Bool { bookingsCursor != nil || listingsCursor != nil }

    /// A v1 page after the ones shown: rows already listed (the list moved while paging) are not repeated.
    static func appending(_ page: [LegacyOrder], to current: [LegacyOrder]) -> [LegacyOrder] {
        let known = Set(current.map(\.id))
        return current + page.filter { !known.contains($0.id) }
    }

    /// Nothing in any section (and nothing still loading or failed): the empty state.
    var isEmpty: Bool {
        bookings.value?.isEmpty == true && listings.value?.isEmpty == true && legacy.value?.isEmpty == true
    }

    // MARK: Listings

    /// The model behind one listing's screens; created from the list row (shown at once), then refreshed.
    func listing(_ id: String) -> ListingModel {
        if let model = details[id] { return model }
        let model = ListingModel(id: id, initial: listings.value?.first { $0.id == id }, api: api, keys: keys, orders: self)
        details[id] = model
        return model
    }

    /// A listing changed on its own screen: the list shows the new state without a reload.
    func replace(_ listing: ListingDTO) {
        guard var items = listings.value, let index = items.firstIndex(where: { $0.id == listing.id }) else { return }
        items[index] = listing
        listings = .loaded(items)
    }

    func updateStats(_ listingId: String, threads: [ProposalThreadDTO], now: Date = Date()) {
        let open = threads.filter { NegotiationActions.of($0, now: now).open }
        stats[listingId] = OfferStats(open: open.count, newest: open.compactMap { ServerTime.parse($0.currentVersion?.createdAt) }.max())
    }

    /// A booking was just made: the list is reloaded so it shows at the top, and the listing's screens are dropped.
    func accepted(listingId: String, banner: String) async {
        details[listingId] = nil
        self.banner = banner
        await refresh()
    }

    // MARK: Legacy (v1) orders

    /// The model behind one v1 order's screens, for the session.
    func legacyOrder(_ id: Int) -> LegacyOrderModel {
        if let model = legacyModels[id] { return model }
        let model = LegacyOrderModel(id: id, api: legacyAPI, banners: banners, mediaURL: mediaURL, orders: self)
        legacyModels[id] = model
        return model
    }

    /// A v1 order was re-read: its row shows the new status and bid count without a reload.
    func legacyChanged(_ detail: LegacyOrderDetail) {
        guard var items = legacy.value, let index = items.firstIndex(where: { $0.id == detail.id }) else { return }
        let row = items[index]
        guard row.status != detail.status || row.bidsCount != detail.bidsCount else { return }
        items[index] = row.with(status: detail.status, bidsCount: detail.bidsCount, finalPrice: detail.finalPrice)
        legacy = .loaded(items)
    }

    // MARK: Bookings

    /// The model behind one booking's screens; created from the list row or the accept answer (shown at once), then
    /// refreshed.
    func booking(_ id: String, initial: ClientBookingDTO? = nil) -> BookingModel {
        if let model = bookingModels[id] { return model }
        let model = BookingModel(id: id, initial: initial ?? bookings.value?.first { $0.id == id }, api: api, keys: keys, orders: self,
                                 mediaURL: mediaURL, connection: connection)
        bookingModels[id] = model
        return model
    }

    /// A booking changed on its own screens: the list shows its new state without a reload.
    func replace(_ booking: ClientBookingDTO) {
        guard var items = bookings.value, let index = items.firstIndex(where: { $0.id == booking.id }) else { return }
        items[index] = booking
        bookings = .loaded(items)
    }

    /// The terms version accept needs, from the list or the server.
    func listingDTO(_ id: String) async -> ListingDTO? {
        if let model = details[id], let listing = model.listing.value { return listing }
        if let listing = listings.value?.first(where: { $0.id == id }) { return listing }
        guard let json = try? await api.getListing(listingId: id).data else { return nil }
        return try? json.decode(ListingDTO.self)
    }
}

// MARK: - One listing

/// Which owner command is running (one at a time).
enum OwnerCommand: Equatable {
    case pause, resume, cancel, save, share
}

/// A listing's detail, edit, share and offers - the owner's side of Q20 and the auction.
@MainActor @Observable
final class ListingModel {
    let id: String
    private let api: ElchiAPI
    private let keys: ActionKeys
    private weak var orders: ClientOrdersModel?

    private(set) var listing: Loadable<ListingDTO>
    let offers: OfferThreads
    /// The parcel photo's signed link, resolved (Q6: short-lived - a reload fetches a fresh one).
    var photoURL: URL? { listing.value?.parcel?.photo.flatMap { orders?.mediaURL($0.url) } }

    private(set) var running: OwnerCommand?
    private(set) var commandError: Error?
    /// Which command `commandError` belongs to (the share section and the edit screen show only their own).
    private(set) var failed: OwnerCommand?
    /// What the last command said: an ok sentence key (with `{count}` = `noticeCount`), plus any server warnings
    /// (masked contacts, Q43).
    private(set) var notice: String?
    private(set) var noticeCount = 0
    private(set) var warnings: [ApiWarning] = []

    /// The share link made on this screen (the URL comes back only once): the bar's share icon sends it again rather
    /// than spending another of the five active links.
    private(set) var shareLink: ShareLinkDTO?

    /// Offers this phone shows for the first time since the listing was opened ("Yangi").
    private(set) var unseen: Set<String> = []

    init(id: String, initial: ListingDTO?, api: ElchiAPI, keys: ActionKeys, orders: ClientOrdersModel) {
        self.id = id
        self.api = api
        self.keys = keys
        self.orders = orders
        listing = initial.map { .loaded($0) } ?? .loading
        offers = OfferThreads(api: api, keys: keys) {
            try await api.listListingProposals(listingId: id, limit: 100).data
        }
        offers.onChanged = { [weak orders, weak self] threads in
            orders?.updateStats(id, threads: threads)
            self?.noteSeen(threads)
        }
        // A refused answer can mean the listing itself moved on (edited, booked, closed): show its current state too.
        offers.onRefused = { [weak self] in await self?.reloadListing() }
        offers.termsVersion = { [weak self] _ in self?.listing.value?.termsVersion }
    }

    func load() async {
        async let listing: Void = reloadListing()
        async let threads: Void = offers.reload()
        _ = await (listing, threads)
    }

    func reloadListing() async {
        do {
            let json = try await api.getListing(listingId: id).data
            let dto = try json.decode(ListingDTO.self)
            listing = .loaded(dto)
            orders?.replace(dto)
        } catch {
            if listing.value == nil { listing = .failed(error) }
        }
    }

    var openOffers: Int {
        offers.threads.value?.filter { NegotiationActions.of($0).open }.count ?? 0
    }

    /// The booking made from this listing, when the orders list has it (the tracker's "Yo'lda" / "Yakunlandi").
    var bookingStatus: String? {
        orders?.bookings.value?.first { $0.listingIds?.request == id }?.serviceStatus
    }

    /// New driver versions become "Yangi" for as long as the screen is open, and are remembered as shown.
    private func noteSeen(_ threads: [ProposalThreadDTO]) {
        unseen.formUnion(OfferSeen.fresh(threads, seen: OfferSeen.load(id)))
        OfferSeen.remember(threads.filter { NegotiationActions.of($0).open }, listingId: id)
    }

    func clearNotice() {
        notice = nil
        noticeCount = 0
        warnings = []
        commandError = nil
        failed = nil
    }

    /// Opened afresh from the list: earlier results are not news any more, and the share URL was for that screen.
    func reset() {
        clearNotice()
        shareLink = nil
        unseen = []
        offers.useBonus = [:]
    }

    // MARK: Pause / resume / cancel

    func pause() async { await command(.pause, key: "listingOwner.paused") { api, dto, key in
        try await api.pauseListing(listingId: dto.id, body: ListingCommand(expectedVersion: dto.version), idempotencyKey: key)
    } }

    func resume() async { await command(.resume, key: "listingOwner.resumed") { api, dto, key in
        try await api.resumeListing(listingId: dto.id, body: ListingCommand(expectedVersion: dto.version), idempotencyKey: key)
    } }

    /// Closes the listing and refuses its open offers (`listing_closed`); bookings are untouched.
    func cancel() async -> Bool {
        await command(.cancel, key: "listingDetail.cancelled") { api, dto, key in
            try await api.cancelListing(listingId: dto.id, body: ListingCancel(expectedVersion: dto.version, reasonCode: "client_changed_plan"),
                                        idempotencyKey: key)
        }
        return commandError == nil
    }

    @discardableResult
    private func command(_ kind: OwnerCommand, key noticeKey: String,
                         _ send: (ElchiAPI, ListingDTO, String) async throws -> APIResult<ListingDTO>) async -> Bool {
        guard running == nil, let dto = listing.value else { return false }
        let action = "\(kind):\(dto.id):\(dto.version)"
        running = kind
        clearNotice()
        defer { running = nil }
        do {
            let result = try await send(api, dto, keys.key(action))
            keys.settle(action)
            listing = .loaded(result.data)
            orders?.replace(result.data)
            notice = noticeKey
            warnings = result.warnings
            await offers.reload()
            return true
        } catch {
            keys.settle(action, after: error)
            commandError = error
            failed = kind
            // Someone (this person on another phone) changed it: show the current state and let them decide again.
            if (error as? APIError)?.code == "VERSION_CONFLICT" || (error as? APIError)?.code == "LISTING_NOT_OPEN" { await reloadListing() }
            return false
        }
    }

    // MARK: Edit

    /// Sends the planned PATCH against the version the person saw. `VERSION_CONFLICT` reloads the listing and asks
    /// again (the form keeps what was typed).
    func save(_ plan: ListingPatchPlan) async -> Bool {
        guard running == nil, let dto = listing.value, plan.invalid == nil, !plan.empty else { return false }
        // Q20: a material edit closes the open offers; the toast says how many went.
        let closing = plan.material ? openOffers : 0
        running = .save
        clearNotice()
        defer { running = nil }
        do {
            let result = try await api.patchListing(listingId: dto.id, body: plan.body(expectedVersion: dto.version))
            listing = .loaded(result.data)
            orders?.replace(result.data)
            notice = closing > 0 ? "client.listing.savedClosed" : "listingOwner.saved"
            noticeCount = closing
            warnings = result.warnings
            await offers.reload()
            return true
        } catch {
            commandError = error
            failed = .save
            if (error as? APIError)?.code == "VERSION_CONFLICT" { await reloadListing() }
            return false
        }
    }

    // MARK: Share

    /// The bar's share icon: the link already made on this screen while it is still valid, else a new generic one for
    /// two days (the design's default). nil = refused (`commandError`: five active links, a closed listing).
    func shareLinkForSharing(now: Date = Date()) async -> ShareLinkDTO? {
        if let link = shareLink, (ServerTime.parse(link.expiresAt) ?? .distantFuture) > now { return link }
        guard running == nil, let dto = listing.value else { return nil }
        let hours = ShareTTL.hours(days: ShareTTL.defaultDays)
        let action = "share:\(dto.id):\(ShareLinkChannel.generic.rawValue):\(hours)"
        running = .share
        commandError = nil
        failed = nil
        defer { running = nil }
        do {
            let result = try await api.createShareLink(listingId: dto.id, body: ShareLinkCreate(channel: .generic, ttlHours: hours),
                                                       idempotencyKey: keys.key(action))
            keys.settle(action)
            shareLink = result.data
            return result.data
        } catch {
            keys.settle(action, after: error)
            commandError = error
            failed = .share
            return nil
        }
    }

    func revokeShareLink() async {
        guard let link = shareLink else { return }
        do {
            _ = try await api.revokeShareLink(shareLinkId: link.id)
            shareLink = nil
            notice = "trackingShare.revoked"
        } catch {
            commandError = error
            failed = .share
        }
    }
}

// MARK: - Offers (one listing's, or all of the client's)

/// Negotiation threads and the client's answers to them: counter, reject, withdraw, accept. Shared by the listing's
/// offers screen and "Takliflarim"; the owner of the list decides how to load it.
@MainActor @Observable
final class OfferThreads {
    private let api: ElchiAPI
    private let keys: ActionKeys
    private let fetch: @MainActor () async throws -> [ProposalThreadDTO]
    /// Called after every reload (stats, the listing's own state).
    var onChanged: (@MainActor ([ProposalThreadDTO]) async -> Void)?
    /// After the server refused an answer (the thread has already been reloaded).
    var onRefused: (@MainActor () async -> Void)?
    /// The listing's `terms_version` accept must send (Q54).
    var termsVersion: (@MainActor (String) async -> Int?)?

    private(set) var threads: Loadable<[ProposalThreadDTO]> = .loading
    /// The thread whose command is in flight.
    private(set) var busy: String?
    private(set) var errors: [String: Error] = [:]
    /// Advisory answers to a counter (`PRICE_OUTSIDE_REFERENCE`, Q90) - shown, never blocking.
    private(set) var warnings: [String: [ApiWarning]] = [:]
    /// "Bonusni ishlataman" ticks, per thread; always start unticked (no pre-filled consent).
    var useBonus: [String: Bool] = [:]
    /// The client's own last price on a thread the driver has countered, keyed `thread:revision` ("(sizniki …)"): the
    /// list leaves `versions` out, so it is read from the thread itself, once per driver revision.
    private(set) var clientPrices: [String: Int] = [:]

    init(api: ElchiAPI, keys: ActionKeys, fetch: @escaping @MainActor () async throws -> [ProposalThreadDTO]) {
        self.api = api
        self.keys = keys
        self.fetch = fetch
    }

    func reload() async {
        do {
            let list = try await fetch()
            threads = .loaded(list)
            await onChanged?(list)
            await loadClientPrices(list)
        } catch {
            if threads.value == nil { threads = .failed(error) }
        }
    }

    /// The client's previous price on a driver's counter, when known.
    func clientPrice(_ thread: ProposalThreadDTO) -> Int? {
        thread.currentVersion.flatMap { clientPrices["\(thread.id):\($0.revision)"] }
    }

    private func loadClientPrices(_ list: [ProposalThreadDTO]) async {
        for thread in list where thread.driverCountered() {
            guard let revision = thread.currentVersion?.revision, clientPrices["\(thread.id):\(revision)"] == nil,
                  let full = try? await api.getProposal(threadId: thread.id).data else { continue }
            let mine = (full.versions ?? []).filter { $0.authorSide == .client && $0.revision < revision }.max { $0.revision < $1.revision }
            if let mine { clientPrices["\(thread.id):\(revision)"] = mine.totalMinor }
        }
    }

    /// What the client's own bonus would do to a price it is about to send (reserves nothing).
    func promoPreview(listingId: String, unitPriceMinor: Int, quantity: Int) async throws -> PromoPreviewDTO {
        try await api.promoPreview(listingId: listingId, unitPriceMinor: unitPriceMinor, quantity: quantity).data
    }

    func clearError(_ threadId: String) {
        errors[threadId] = nil
        warnings[threadId] = nil
    }

    /// The client's bonus quote on this version, when the server offers one (never in dev: promotions are off).
    static func clientQuote(_ version: ProposalVersionDTO) -> ProposalPromoClientDTO? {
        if case .client(let quote)? = version.promoQuote, quote.passengerDiscountMinor > 0 { return quote }
        return nil
    }

    // MARK: Commands

    /// A new price on the driver's version (for a parcel request only the price, plus the bonus consent when ticked).
    func counter(_ thread: ProposalThreadDTO, priceMinor: Int, consent: ProposalPromoClientDTO?) async -> Bool {
        guard let version = thread.currentVersion, priceMinor > 0 else { return false }
        let promo = consent.map { ProposalPromoConsent(cashDueMinor: $0.cashDueMinor, passengerBonusMinor: $0.passengerDiscountMinor) }
        return await run(thread, action: "counter:\(thread.id):\(version.revision):\(priceMinor)") { api, key in
            try await api.counterProposal(threadId: thread.id, body: ProposalCounter(expectedRevision: version.revision, promoConsent: promo,
                                                                                   unitPriceMinor: priceMinor), idempotencyKey: key).warnings
        }
    }

    func reject(_ thread: ProposalThreadDTO) async -> Bool {
        guard let version = thread.currentVersion else { return false }
        return await run(thread, action: "reject:\(thread.id):\(version.revision)") { api, key in
            try await api.rejectProposal(threadId: thread.id, body: ProposalDecision(expectedRevision: version.revision), idempotencyKey: key).warnings
        }
    }

    func withdraw(_ thread: ProposalThreadDTO) async -> Bool {
        guard let version = thread.currentVersion else { return false }
        return await run(thread, action: "withdraw:\(thread.id):\(version.revision)") { api, key in
            try await api.withdrawProposal(threadId: thread.id, body: ProposalDecision(expectedRevision: version.revision), idempotencyKey: key).warnings
        }
    }

    /// Accept the driver's current version at the listing terms the client saw. One key per `accept:{thread}:{version}`
    /// until a definite answer. Returns the new booking.
    func accept(_ thread: ProposalThreadDTO) async -> ClientBookingDTO? {
        guard let version = thread.currentVersion, busy == nil else { return nil }
        guard let terms = await termsVersion?(thread.listingId) else {
            errors[thread.id] = APIError(status: 0, code: APIError.server, message: "", details: nil)
            return nil
        }
        let consent = useBonus[thread.id] == true ? Self.clientQuote(version) : nil
        let body = AcceptRequest(expectedListingTermsVersion: terms,
                                 promoConsent: consent.map { PromoConsentInput(cashDueMinor: $0.cashDueMinor, passengerBonusMinor: $0.passengerDiscountMinor) },
                                 proposalVersionId: version.id)
        let action = "accept:\(thread.id):\(version.id)"
        busy = thread.id
        clearError(thread.id)
        defer { busy = nil }
        do {
            let result = try await api.acceptProposal(threadId: thread.id, body: body, idempotencyKey: keys.key(action))
            keys.settle(action)
            return ClientBookingDTO.from(result.data)
        } catch {
            keys.settle(action, after: error)
            errors[thread.id] = error
            await afterRefusal(error, thread)
            return nil
        }
    }

    private func run(_ thread: ProposalThreadDTO, action: String,
                     _ send: (ElchiAPI, String) async throws -> [ApiWarning]) async -> Bool {
        guard busy == nil else { return false }
        busy = thread.id
        clearError(thread.id)
        defer { busy = nil }
        do {
            let warnings = try await send(api, keys.key(action))
            keys.settle(action)
            if !warnings.isEmpty { self.warnings[thread.id] = warnings }
            await reload()
            return true
        } catch {
            keys.settle(action, after: error)
            errors[thread.id] = error
            await afterRefusal(error, thread)
            return false
        }
    }

    /// The thread moved on under the person (a counter from the driver, an expiry, the listing changed or was
    /// booked, a stale bonus quote): show the current state so they decide again. The bonus tick never survives.
    private func afterRefusal(_ error: Error, _ thread: ProposalThreadDTO) async {
        guard let error = error as? APIError, error.code != APIError.network else { return }
        if error.code == "PROMO_QUOTE_STALE" { useBonus[thread.id] = false }
        await reload()
        await onRefused?()
    }
}

// MARK: - Takliflarim

/// Every negotiation the client is a party to (`GET /me/proposals`), with the listing each belongs to.
@MainActor @Observable
final class ProposalsModel {
    let offers: OfferThreads
    private(set) var listings: [String: ListingDTO] = [:]
    private weak var orders: ClientOrdersModel?

    init(api: ElchiAPI, keys: ActionKeys) {
        offers = OfferThreads(api: api, keys: keys) { try await api.listMyProposals(limit: 50).data }
        offers.onChanged = { [weak self] threads in await self?.loadListings(for: threads) }
        offers.termsVersion = { [weak self] listingId in
            await self?.orders?.listingDTO(listingId)?.termsVersion
        }
    }

    /// The orders model supplies the listings (and their terms versions) the threads belong to.
    func attach(_ orders: ClientOrdersModel) { self.orders = orders }

    func load() async { await offers.reload() }

    private func loadListings(for threads: [ProposalThreadDTO]) async {
        for id in Set(threads.map(\.listingId)) where listings[id] == nil {
            if let listing = await orders?.listingDTO(id) { listings[id] = listing }
        }
    }
}
