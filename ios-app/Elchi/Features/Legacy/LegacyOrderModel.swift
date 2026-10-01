import Foundation
import Observation

/// One v1 order's archive screens: the detail, its bids, and the commands left to it (choose a driver, confirm the
/// delivery, rate, cancel, report a problem). Results and refusals go to the app's banner; the orders list is told
/// when the order changed. One model per order for the session (created from its list row).
@MainActor @Observable
final class LegacyOrderModel {
    let id: Int
    private let api: LegacyOrdersAPI
    private let banners: BannerCenter
    private let mediaURL: @Sendable (String) -> URL?
    private weak var orders: ClientOrdersModel?

    private(set) var order: Loadable<LegacyOrderDetail> = .loading
    /// The order is not the client's or no longer exists (404 / 403).
    private(set) var notFound = false
    private(set) var bids: Loadable<[LegacyBid]> = .loading
    /// The command in flight (one at a time).
    private(set) var running: LegacyCommand?
    /// The bid whose "Tanlash" is in flight.
    private(set) var selecting: Int?
    /// Rated in this session: v1 has no "rated" flag on the order, so the entry goes once the rating is sent.
    private(set) var rated = false

    init(id: Int, api: LegacyOrdersAPI, banners: BannerCenter, mediaURL: @escaping @Sendable (String) -> URL?, orders: ClientOrdersModel) {
        self.id = id
        self.api = api
        self.banners = banners
        self.mediaURL = mediaURL
        self.orders = orders
    }

    var actions: LegacyActions? { order.value.map { LegacyActions.of($0.status, rated: rated) } }

    /// The cargo photo's signed link (short-lived: a reload mints a fresh one).
    var photoURL: URL? { order.value?.cargoPhotoUrl.flatMap { $0.isEmpty ? nil : mediaURL($0) } }

    // MARK: Loading

    /// The detail (again on every return from a sub-screen). A failed refresh keeps what was shown and says why in
    /// the banner; 404/403 is the not-found state.
    func load() async {
        do {
            let detail = try await api.order(id)
            order = .loaded(detail)
            notFound = false
            orders?.legacyChanged(detail)
        } catch {
            if LegacyErrors.notFound(error) {
                notFound = true
            } else {
                if order.value == nil { order = .failed(error) }
                banners.error(error)
            }
        }
    }

    func loadBids() async {
        do {
            bids = .loaded(try await api.bids(id))
        } catch {
            if LegacyErrors.notFound(error) { notFound = true }
            if bids.value == nil { bids = .failed(error) }
        }
    }

    /// Everything the bids screen shows: the order's status (open or closed) and its bids.
    func loadBidsScreen() async {
        async let detail: Void = load()
        async let list: Void = loadBids()
        _ = await (detail, list)
    }

    // MARK: Commands

    /// "Tanlash" after the confirm sheet. `BID_NOT_ACTIVE` reloads the list so the person picks again.
    func select(_ bid: LegacyBid) async -> Bool {
        guard running == nil else { return false }
        selecting = bid.id
        defer { selecting = nil }
        let done = await run(.select, ok: "listingBids.driverChosen") { api, id in try await api.selectDriver(id, bidId: bid.id) }
        if !done { await loadBidsScreen() }
        return done
    }

    func confirmDelivery() async -> Bool {
        await run(.confirm, ok: "legacyOrder.confirmed") { api, id in try await api.confirm(id) }
    }

    /// A repeated rating (409 `ALREADY_EXISTS`) counts as sent: the server keeps the first.
    func rate(stars: Int, comment: String) async -> Bool {
        guard (1...5).contains(stars) else { return false }
        let text = comment.trimmingCharacters(in: .whitespacesAndNewlines)
        let done = await run(.rate, ok: "legacyOrder.ratingSent", accept: LegacyErrors.alreadyRated) { api, id in
            try await api.rate(id, stars: stars, comment: text.isEmpty ? nil : text)
        }
        if done { rated = true }
        return done
    }

    /// `reason` is the stored text (Uzbek, like the web client), not the person's language.
    func cancel(reason: String) async -> Bool {
        await run(.cancel, ok: "confirmDialog.cancelOrder.done") { api, id in try await api.cancel(id, reason: reason) }
    }

    func dispute(_ reason: LegacyDisputeReason, comment: String) async -> Bool {
        let text = comment.trimmingCharacters(in: .whitespacesAndNewlines)
        return await run(.dispute, ok: "legacyOrder.dispute.opened") { api, id in
            try await api.openDispute(id, reason: reason, comment: text.isEmpty ? nil : text)
        }
    }

    /// One command: the loading line while it runs, the ok banner and a fresh detail after it, the refusal said for
    /// the client otherwise (and the detail reloaded, since a refusal usually means the order moved on).
    private func run(_ command: LegacyCommand, ok: String, accept: (Error) -> Bool = { _ in false },
                     _ send: (LegacyOrdersAPI, Int) async throws -> Void) async -> Bool {
        guard running == nil else { return false }
        running = command
        banners.clearError()
        defer { running = nil }
        do {
            try await banners.whileLoading { try await send(api, id) }
        } catch let error where accept(error) {
            // Counts as done.
        } catch {
            if let key = LegacyErrors.key(error, for: command) { banners.show(.key(key), tone: .err) } else { banners.error(error) }
            if (error as? APIError)?.code != APIError.network { await load() }
            return false
        }
        banners.ok(ok)
        await load()
        await orders?.refreshLegacy()
        return true
    }
}
