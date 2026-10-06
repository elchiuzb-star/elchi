import Foundation
import Observation

// MARK: - Yo'nalishlarim + the direction feed

/// ADR-0027: the driver's directions ("where from -> where to"), the one whose requests are on the Moslar tab, the
/// add form, and one offer model per request opened from the feed.
@MainActor @Observable
final class DirectionsModel {
    private let api: ElchiAPI
    private let banners: BannerCenter
    private let keys: ActionKeys

    private(set) var list: Loadable<[DriverDirectionDTO]> = .loading
    /// The direction whose requests the feed shows (`dir.feedPick` when there are several).
    var activeId: String?
    var day: DirectionFeedDay = .today
    private(set) var feed: Loadable<DirectionRequestsDTO>?
    /// The direction whose pause / resume / archive is in flight.
    private(set) var running: String?

    var form = DirectionForm()
    private(set) var saving = false
    /// `dir.noRoad` / `dir.exists` under the form: a product answer, not an error look.
    private(set) var formNotice: String?
    private(set) var formError: Error?

    private var offers: [String: DirectionOfferModel] = [:]

    init(api: ElchiAPI, banners: BannerCenter, keys: ActionKeys) {
        self.api = api
        self.banners = banners
        self.keys = keys
    }

    /// The live directions (archived ones never show).
    var directions: [DriverDirectionDTO] { DirectionFeed.live(list.value ?? []) }
    var active: DriverDirectionDTO? { directions.first { $0.id == activeId } }

    func load() async {
        do {
            let fresh = try await api.listMyDriverDirections().data
            list = .loaded(fresh)
            activeId = DirectionFeed.pick(fresh, current: activeId)
        } catch {
            if list.value == nil { list = .failed(error) }
        }
    }

    /// Q151: the requests along the chosen direction, for one service and the day chips' range.
    func loadFeed(service: ServiceType, now: Date = Date()) async {
        guard let id = activeId else {
            feed = nil
            return
        }
        let range = DirectionFeed.range(day, now: now)
        if feed?.value?.directionId != id { feed = .loading }
        do {
            let page = try await api.listDirectionRequests(directionId: id, serviceType: service, dateFrom: range.from, dateTo: range.to).data
            guard activeId == id else { return }
            feed = .loaded(page)
        } catch {
            if activeId == id, feed?.value?.directionId != id { feed = .failed(error) }
        }
    }

    /// Pause / resume / archive (`PATCH {expected_version, status}`); "Yo'nalish yangilandi" / "Yo'nalish o'chirildi".
    func setStatus(_ direction: DriverDirectionDTO, to status: String) async {
        guard running == nil else { return }
        running = direction.id
        defer { running = nil }
        do {
            _ = try await api.patchDriverDirection(directionId: direction.id,
                                                   body: DriverDirectionPatch(expectedVersion: direction.version, status: status))
            banners.ok(status == "archived" ? "dir.archived" : "dir.updated")
            await load()
        } catch {
            banners.error(error)
            // A version conflict: what is current now, so the next tap is made on it.
            await load()
        }
    }

    // MARK: The add form

    func resetForm() {
        form = DirectionForm()
        formNotice = nil
        formError = nil
    }

    func clearFormAnswer() {
        formNotice = nil
        formError = nil
    }

    /// `POST /driver-directions`. Added -> the list is read again and the new one is the feed's direction.
    func create() async -> DirectionCreateOutcome? {
        guard let body = form.body, let action = form.action, !saving else { return nil }
        saving = true
        clearFormAnswer()
        defer { saving = false }
        do {
            let created = try await api.createDriverDirection(body: body, idempotencyKey: keys.key(action)).data
            keys.settle(action)
            activeId = created.id
            await load()
            return .added
        } catch {
            keys.settle(action, after: error)
            if DirectionAnswer.isNoRoad(error) {
                formNotice = "dir.noRoad"
                return .notice("dir.noRoad")
            }
            if DirectionAnswer.isDuplicate(error) {
                formNotice = "dir.exists"
                return .notice("dir.exists")
            }
            formError = error
            return .failed
        }
    }

    // MARK: Offers

    func item(_ listingId: String) -> DirectionRequestItemDTO? { feed?.value?.items.first { $0.listing.id == listingId } }

    /// The offer screen's model for a request in the direction feed (a fresh one each time the card is tapped).
    func offer(_ listingId: String) -> DirectionOfferModel? {
        if let model = offers[listingId] { return model }
        guard let item = item(listingId), let directionId = activeId ?? feed?.value?.directionId else { return nil }
        let model = DirectionOfferModel(item: item, directionId: directionId, api: api, keys: keys)
        offers[listingId] = model
        return model
    }

    func forgetOffer(_ listingId: String) { offers[listingId] = nil }
}

// MARK: - The offer from a direction

/// One request priced from a direction: no trip picker and no window - the server takes, re-times or plans the trip
/// (Q152). The rival board (Q95), the commission estimate (never blocking) and design-07's price behaviour stay.
@MainActor @Observable
final class DirectionOfferModel {
    private let api: ElchiAPI
    private let keys: ActionKeys
    let item: DirectionRequestItemDTO
    let directionId: String

    /// nil = the board is closed for this listing (404, Q95) and is not shown.
    private(set) var board: Loadable<RivalBoard>? = .loading
    var priceDigits: String
    private(set) var quote: Loadable<app__modules__wallet__schemas__FeeQuoteDTO>?
    private(set) var sending = false
    /// The car's ETA from a `TIME_WINDOW_CONFLICT`: the next send is a time proposal at it.
    private(set) var conflictEta: String?
    private(set) var refusal: DirectionOfferRefusal?

    init(item: DirectionRequestItemDTO, directionId: String, api: ElchiAPI, keys: ActionKeys) {
        self.item = item
        self.directionId = directionId
        self.api = api
        self.keys = keys
        priceDigits = String(item.listing.unitPriceMinor / 100)
    }

    var listing: ListingPublicDTO { item.listing }
    var priceMinor: Int { Money.minor(fromSoum: priceDigits) }
    var totalMinor: Int { OfferBody.totalMinor(listing: listing, unitPriceMinor: priceMinor) }
    /// The time this offer proposes (a request at another time, or after a conflict); nil for an ordinary offer.
    var proposeAt: String? { DirectionOffer.proposeAt(item: item, conflictEta: conflictEta) }

    func loadBoard() async {
        do {
            board = .loaded(RivalBoard.of(try await api.listListingOffers(listingId: listing.id, limit: 50).data))
        } catch {
            if let error = error as? APIError, error.status == 404 || error.code == "NOT_FOUND" { board = nil } else if board?.value == nil { board = .failed(error) }
        }
    }

    func loadQuote(totalMinor: Int) async {
        guard totalMinor > 0 else { quote = nil; return }
        quote = .loading
        do {
            quote = .loaded(try await api.commissionQuote(serviceType: listing.serviceType, totalMinor: totalMinor).data)
        } catch {
            quote = .failed(error)
        }
    }

    func clearRefusal() { refusal = nil }

    /// `POST /driver-directions/{id}/offers` at `unitPriceMinor`. The same request reuses its Idempotency-Key on a retry
    /// (no answer / 5xx); a conflict with the car's ETA turns the button into "propose HH:MM" (Q153).
    func send(unitPriceMinor: Int, message: String?) async -> DirectionOfferDTO? {
        guard unitPriceMinor > 0, !sending else { return nil }
        sending = true
        refusal = nil
        defer { sending = false }
        let pickupAt = proposeAt
        let body = DirectionOffer.body(listingId: listing.id, unitPriceMinor: unitPriceMinor, message: message, pickupAt: pickupAt)
        let action = DirectionOffer.action(directionId: directionId, body: body)
        do {
            let result = try await api.offerFromDirection(directionId: directionId, body: body, idempotencyKey: keys.key(action)).data
            keys.settle(action)
            return result
        } catch {
            keys.settle(action, after: error)
            let answer = DirectionOfferRefusal.of(error, hadPickupAt: pickupAt != nil)
            if case .proposeTime(let eta) = answer { conflictEta = eta } else { refusal = answer }
            return nil
        }
    }
}
