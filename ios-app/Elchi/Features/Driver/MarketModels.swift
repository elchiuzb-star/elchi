import Foundation
import Observation

// MARK: - Trips (Yo'nalishlar)

/// The driver's private trip plans (Q138: never shown to clients): the list, the commands (shared by the list and the
/// detail), and one detail model per opened trip.
@MainActor @Observable
final class TripsModel {
    private let api: ElchiAPI
    private let banners: BannerCenter
    private let keys: ActionKeys

    private(set) var trips: Loadable<[TripDTO]> = .loading
    /// The trip whose command is in flight.
    private(set) var running: String?
    /// The last refusal per trip, shown on its card and detail (the boarding window, unresolved bookings…).
    private(set) var refusals: [String: Error] = [:]
    private var details: [String: TripDetailModel] = [:]
    /// Stage 09 GPS: runs before a command is sent (the last points go out before `complete`).
    var beforeCommand: (@MainActor (TripCommand, TripDTO) async -> Void)?
    /// Stage 09 GPS: runs after the server accepted a command (publishing starts on boarding / departure, ends with
    /// the trip).
    var afterCommand: (@MainActor (TripCommand, TripDTO) async -> Void)?
    /// Every time the list was read (the GPS resumes a running trip on app start).
    var onLoaded: (@MainActor ([TripDTO]) async -> Void)?

    init(api: ElchiAPI, banners: BannerCenter, keys: ActionKeys) {
        self.api = api
        self.banners = banners
        self.keys = keys
    }

    func load() async {
        do {
            let list = try await api.listMyTrips(limit: 50).data
            trips = .loaded(list)
            await onLoaded?(list)
        } catch {
            if trips.value == nil { trips = .failed(error) }
        }
    }

    /// The running trip that should be publishing (boarding / in progress / interrupted), if any.
    var trackable: TripDTO? { trips.value.flatMap(GpsPoints.trackableTrip) }

    /// The trips an offer can be made from (planned, cutoff ahead), freshly read.
    func offerable(now: Date = Date()) async -> [TripDTO] {
        await load()
        return TripList.offerable(trips.value ?? [], now: now)
    }

    func detail(_ id: String) -> TripDetailModel {
        if let model = details[id] { return model }
        let model = TripDetailModel(id: id, api: api, initial: trips.value?.first { $0.id == id })
        details[id] = model
        return model
    }

    func added(_ trip: TripDTO) {
        var list = trips.value ?? []
        list.removeAll { $0.id == trip.id }
        list.append(trip)
        trips = .loaded(list)
    }

    private func replace(_ trip: TripDTO) {
        if var list = trips.value, let index = list.firstIndex(where: { $0.id == trip.id }) {
            list[index] = trip
            trips = .loaded(list)
        }
        details[trip.id]?.replace(trip)
    }

    func clearRefusal(_ id: String) { refusals[id] = nil }

    /// One command with its own Idempotency-Key (`trip:{id}:{action}:{version}`). Success: the new state and "Safar
    /// holati yangilandi". A refusal stays on the trip (the boarding window says when it opens); an unresolved booking
    /// or a version conflict reads the trip again.
    @discardableResult
    func run(_ command: TripCommand, on trip: TripDTO, reason: String? = nil) async -> Bool {
        guard running == nil else { return false }
        banners.clearError()
        refusals[trip.id] = nil
        running = trip.id
        defer { running = nil }
        let action = "trip:\(trip.id):\(command.rawValue):\(trip.version)"
        let text = reason?.trimmingCharacters(in: .whitespacesAndNewlines)
        await beforeCommand?(command, trip)
        do {
            let updated = try await api.tripAction(tripId: trip.id, action: command.rawValue,
                                                   body: TripActionRequest(expectedVersion: trip.version, reason: text?.isEmpty == false ? text : nil),
                                                   idempotencyKey: keys.key(action)).data
            keys.settle(action)
            replace(updated)
            banners.ok("driverRoutes.tripStatusUpdated")
            await afterCommand?(command, updated)
            await details[trip.id]?.load()
            return true
        } catch {
            keys.settle(action, after: error)
            refusals[trip.id] = error
            if TripRefusal.of(error).refreshes {
                await load()
                await details[trip.id]?.load()
            }
            return false
        }
    }
}

/// One trip: the header (status, times, vehicle, cutoff), its stops, free capacity per segment and the manifest.
@MainActor @Observable
final class TripDetailModel {
    let id: String
    private let api: ElchiAPI

    private(set) var trip: Loadable<TripDTO>
    private(set) var availability: Loadable<TripAvailabilityDTO> = .loading
    private(set) var manifest: Loadable<TripManifestDTO> = .loading

    init(id: String, api: ElchiAPI, initial: TripDTO?) {
        self.id = id
        self.api = api
        trip = initial.map { .loaded($0) } ?? .loading
    }

    func replace(_ trip: TripDTO) { self.trip = .loaded(trip) }

    func load() async {
        async let trip: Void = loadTrip()
        async let availability: Void = loadAvailability()
        async let manifest: Void = loadManifest()
        _ = await (trip, availability, manifest)
    }

    private func loadTrip() async {
        do {
            // `GET /trips/{id}` is typed as a union (owner / public view); the owner gets the full TripDTO.
            trip = .loaded(try await api.getTrip(tripId: id).data.decode(TripDTO.self))
        } catch {
            if trip.value == nil { trip = .failed(error) }
        }
    }

    private func loadAvailability() async {
        do {
            availability = .loaded(try await api.getTripAvailability(tripId: id).data)
        } catch {
            if availability.value == nil { availability = .failed(error) }
        }
    }

    private func loadManifest() async {
        do {
            manifest = .loaded(try await api.getTripManifest(tripId: id).data)
        } catch {
            if manifest.value == nil { manifest = .failed(error) }
        }
    }
}

// MARK: - Planning a trip

/// "Yo'nalish qo'shish": an approved vehicle, a corridor, one of its operator-approved routes (optionally found by a
/// stop it passes), the departure, seats and cargo within the vehicle's limits.
@MainActor @Observable
final class AddTripModel {
    private let api: ElchiAPI
    private let keys: ActionKeys

    var form = TripPlanForm()
    private(set) var corridors: Loadable<[CorridorDTO]> = .loading
    private(set) var routes: Loadable<[RouteVersionDTO]>?
    /// The stop the routes are filtered by ("Jizzax orqali o'tadigan marshrutlar").
    private(set) var stopFilter: StopDTO?
    private(set) var stopResults: [StopDTO] = []
    private(set) var saving = false
    private(set) var attempted = false
    private(set) var error: Error?
    /// `VEHICLE_NOT_ELIGIBLE {field, vehicle_limit}`: the field the server refused, marked until it changes.
    private(set) var refused: (field: TripPlanField, limit: Int)?

    init(api: ElchiAPI, keys: ActionKeys) {
        self.api = api
        self.keys = keys
    }

    /// Starts over (a new "+" press): nothing chosen, the vehicle preselected when there is exactly one approved.
    func reset(vehicles: [VehicleDTO]) {
        form = TripPlanForm()
        routes = nil
        stopFilter = nil
        stopResults = []
        attempted = false
        error = nil
        refused = nil
        // A first suggestion (tomorrow 09:00 Tashkent), changed with the picker.
        form.start = DepartureWindow.suggested().start
        if vehicles.count == 1, let only = vehicles.first { chooseVehicle(only) }
    }

    func loadCorridors() async {
        do {
            corridors = .loaded(try await api.listCorridors().data)
        } catch {
            if corridors.value == nil { corridors = .failed(error) }
        }
    }

    func chooseVehicle(_ vehicle: VehicleDTO) {
        form.vehicleId = vehicle.id
        let values = TripPlan.prefill(vehicle)
        form.seats = values.seats
        form.cargoKg = values.cargoKg
        form.cargoLitres = values.cargoLitres
        refused = nil
    }

    func chooseCorridor(_ id: String) async {
        guard form.corridorId != id else { return }
        form.corridorId = id
        form.routeId = nil
        stopFilter = nil
        stopResults = []
        routes = .loading
        do {
            let list = try await api.listCorridorRoutes(corridorId: id).data
            guard form.corridorId == id else { return }
            routes = .loaded(list)
            if list.count == 1 { form.routeId = list[0].id }
        } catch {
            if form.corridorId == id { routes = .failed(error) }
        }
    }

    var shownRoutes: [RouteVersionDTO] { TripPlan.routesThrough(routes?.value ?? [], stopId: stopFilter?.id) }

    func searchStops(_ query: String) async {
        let text = query.trimmingCharacters(in: .whitespaces)
        guard text.count >= 2 else { stopResults = []; return }
        stopResults = (try? await api.searchStops(q: text, limit: 8).data) ?? []
    }

    /// Keeps the routes through that stop; the chosen route stays only if it passes it (or the only one left is taken).
    func filter(by stop: StopDTO?) {
        stopFilter = stop
        stopResults = []
        guard stop != nil else { return }
        let through = shownRoutes
        if !through.contains(where: { $0.id == form.routeId }) { form.routeId = through.count == 1 ? through[0].id : nil }
    }

    func problems(vehicle: VehicleDTO?) -> [TripPlanField: TripPlanProblem] {
        var out = TripPlan.problems(form, vehicle: vehicle)
        if let refused { out[refused.field] = .overLimit(refused.limit) }
        return out
    }

    func clearRefused(_ field: TripPlanField) { if refused?.field == field { refused = nil } }

    /// Sends the plan once everything checks out. The new trip, or nil (the form says why).
    func save(vehicle: VehicleDTO?) async -> TripDTO? {
        attempted = true
        error = nil
        guard problems(vehicle: vehicle).isEmpty, let route = routes?.value?.first(where: { $0.id == form.routeId }),
              let body = TripPlan.body(form, route: route) else { return nil }
        saving = true
        defer { saving = false }
        let action = "trip.create:\(body.vehicleId):\(body.routeVersionId):\(body.plannedStartAt)"
        do {
            let trip = try await api.createTrip(body: body, idempotencyKey: keys.key(action)).data
            keys.settle(action)
            return trip
        } catch {
            keys.settle(action, after: error)
            refused = TripPlan.refusedField(error)
            self.error = error
            return nil
        }
    }
}

// MARK: - Feed (Moslar)

/// The matching requests: the remembered filter (per driver), the passenger switch (only when the flag is on), the
/// pages, and the region / district lists the filter is chosen from.
@MainActor @Observable
final class FeedModel {
    private let api: ElchiAPI
    private let market: MarketAPI
    private let storageKey: String

    var filter: FeedFilter {
        didSet {
            guard filter != oldValue else { return }
            if let data = try? JSONEncoder().encode(filter) { UserDefaults.standard.set(data, forKey: storageKey) }
        }
    }
    /// `flags.passenger_enabled`: without it the feed is parcel only (no segmented control).
    private(set) var passengerAllowed = false
    private(set) var items: Loadable<[FeedItemDTO]>?
    private(set) var nextCursor: String?
    private(set) var degraded: [String] = []
    private(set) var loadingMore = false
    private var loadedQuery: FeedQuery?

    private(set) var regions: Loadable<[RegionDTO]> = .loading
    private(set) var districts: [String: Loadable<[DistrictDTO]>] = [:]
    /// Every district by id (the saved routes name their ends with it).
    private(set) var districtNames: [String: DistrictDTO] = [:]

    init(api: ElchiAPI, market: MarketAPI, userId: Int) {
        self.api = api
        self.market = market
        storageKey = "elchi.driver.feedFilter.\(userId)"
        filter = UserDefaults.standard.data(forKey: storageKey).flatMap { try? JSONDecoder().decode(FeedFilter.self, from: $0) } ?? FeedFilter()
    }

    var query: FeedQuery? { FeedQuery.make(filter, passengerAllowed: passengerAllowed) }

    func loadFlags() async {
        if let flags = try? await api.effectiveFlags().data.flags { passengerAllowed = flags.passengerEnabled }
    }

    /// The first page for the current filter (a refresh keeps the shown items until the answer comes).
    func load() async {
        guard let query else {
            items = nil
            return
        }
        if loadedQuery != query { items = .loading }
        do {
            let page = try await market.feed(query)
            guard self.query == query else { return }
            loadedQuery = query
            items = .loaded(page.data)
            nextCursor = page.meta.nextCursor
            degraded = page.meta.degraded ?? []
        } catch {
            if self.query == query, items?.value == nil || loadedQuery != query { items = .failed(error) }
        }
    }

    func loadMore() async {
        guard let query, let cursor = nextCursor, !loadingMore, let current = items?.value else { return }
        loadingMore = true
        defer { loadingMore = false }
        guard let page = try? await market.feed(query, cursor: cursor), self.query == query else { return }
        items = .loaded(FeedGroups.appending(page.data, to: current))
        nextCursor = page.meta.nextCursor
    }

    func item(_ listingId: String) -> FeedItemDTO? { items?.value?.first { $0.listing.id == listingId } }

    private var offers: [String: OfferModel] = [:]

    /// The offer screen's model for a request in the feed (kept while the driver goes to plan a trip and back).
    func offer(_ listingId: String, keys: ActionKeys) -> OfferModel? {
        if let model = offers[listingId] { return model }
        guard let item = item(listingId) else { return nil }
        let model = OfferModel(listing: item.listing, api: api, keys: keys)
        offers[listingId] = model
        return model
    }

    /// A request opened from a link (Stage 10): a fresh offer screen for the listing the server just returned.
    func offer(opening listing: ListingPublicDTO, keys: ActionKeys) {
        offers[listing.id] = OfferModel(listing: listing, api: api, keys: keys)
    }

    /// A fresh offer screen next time (after sending, or when the feed item changed).
    func forgetOffer(_ listingId: String) { offers[listingId] = nil }

    func loadRegions() async {
        guard regions.value == nil else { return }
        do { regions = .loaded(try await api.listRegions().data) } catch { regions = .failed(error) }
    }

    func loadDistricts(_ region: RegionDTO) async {
        guard districts[region.id]?.value == nil else { return }
        districts[region.id] = .loading
        do {
            let list = try await api.listDistricts(regionId: region.id, limit: 500).data
            districts[region.id] = .loaded(list)
            for district in list { districtNames[district.id] = district }
        } catch {
            districts[region.id] = .failed(error)
        }
    }

    /// All districts at once, for naming saved routes.
    func loadAllDistricts() async {
        guard districtNames.isEmpty, let list = try? await api.listDistricts(limit: 500).data else { return }
        for district in list { districtNames[district.id] = district }
    }

    func setEnd(_ end: FeedEnd, origin: Bool) {
        if origin { filter.origin = end } else { filter.destination = end }
    }
}

// MARK: - Saved routes

@MainActor @Observable
final class SavedRoutesModel {
    private let api: ElchiAPI
    private let banners: BannerCenter
    private let keys: ActionKeys

    private(set) var list: Loadable<[SavedSearchDTO]> = .loading
    private(set) var saving = false
    private(set) var deleting: String?
    private(set) var error: Error?

    init(api: ElchiAPI, banners: BannerCenter, keys: ActionKeys) {
        self.api = api
        self.banners = banners
        self.keys = keys
    }

    func load() async {
        do {
            list = .loaded(try await api.listMySavedSearches(limit: 50).data)
        } catch {
            if list.value == nil { list = .failed(error) }
        }
    }

    func save(_ filter: FeedFilter, passengerAllowed: Bool) async {
        guard let body = SavedRoute.body(filter, passengerAllowed: passengerAllowed), !saving else { return }
        saving = true
        error = nil
        defer { saving = false }
        let ends = [body.originRegionId, body.originDistrictId, body.destinationRegionId, body.destinationDistrictId].map { $0 ?? "-" }
        let action = "saved.create:\(body.serviceType.rawValue):\(ends.joined(separator: ":"))"
        do {
            _ = try await api.createSavedSearch(body: body, idempotencyKey: keys.key(action))
            keys.settle(action)
            banners.ok("savedSearches.saved")
            await load()
        } catch {
            keys.settle(action, after: error)
            self.error = error
        }
    }

    func delete(_ id: String) async {
        guard deleting == nil else { return }
        deleting = id
        error = nil
        defer { deleting = nil }
        do {
            _ = try await api.deleteSavedSearch(savedSearchId: id)
            banners.ok("savedSearches.deleted")
            await load()
        } catch {
            self.error = error
        }
    }
}

// MARK: - The offer ("Narx taklif qiling")

/// One request the driver is pricing: the rival board (hidden when the endpoint is closed), the trip, the pickup
/// window, the price and the commission estimate. Sending never holds a seat or money.
@MainActor @Observable
final class OfferModel {
    private let api: ElchiAPI
    private let keys: ActionKeys

    /// nil = the board is closed for this listing (404, Q95) and is not shown.
    private(set) var board: Loadable<RivalBoard>? = .loading
    private(set) var trips: Loadable<[TripDTO]> = .loading
    private(set) var tripId: String?
    /// The pickup window: computed from the trip, or the driver's adjustment inside the request's window.
    var window: (start: Date, end: Date)?
    var priceDigits: String
    private(set) var quote: Loadable<app__modules__wallet__schemas__FeeQuoteDTO>?
    private(set) var sending = false
    private(set) var error: Error?

    init(listing: ListingPublicDTO, api: ElchiAPI, keys: ActionKeys) {
        self.listing = listing
        self.api = api
        self.keys = keys
        priceDigits = String(listing.unitPriceMinor / 100)
    }

    /// The request being priced: a feed item's listing, or (Stage 10, `elchi://listings/{id}`) the public DTO from
    /// `GET /listings/{id}` - the offer screen reads nothing else.
    let listing: ListingPublicDTO
    var trip: TripDTO? { trips.value?.first { $0.id == tripId } }
    var priceMinor: Int { Money.minor(fromSoum: priceDigits) }
    var totalMinor: Int { OfferBody.totalMinor(listing: listing, unitPriceMinor: priceMinor) }
    /// The request's own window (the bounds the driver may adjust the pickup window within).
    var requestWindow: (start: Date, end: Date)? {
        guard let start = ServerTime.parse(listing.departureWindowStart), let end = ServerTime.parse(listing.departureWindowEnd) else { return nil }
        return (start, end)
    }

    func loadBoard() async {
        do {
            board = .loaded(RivalBoard.of(try await api.listListingOffers(listingId: listing.id, limit: 50).data))
        } catch {
            // Q95: a closed board (flag / corridor -> 404) is simply not shown; sending is never blocked by it.
            if let error = error as? APIError, error.status == 404 || error.code == "NOT_FOUND" { board = nil } else if board?.value == nil { board = .failed(error) }
        }
    }

    func setTrips(_ list: [TripDTO]) {
        trips = .loaded(list)
        if tripId == nil || !list.contains(where: { $0.id == tripId }) {
            choose(PickupWindow.preselect(list, listing: listing)?.id ?? (list.count == 1 ? list[0].id : nil))
        }
    }

    func choose(_ id: String?) {
        tripId = id
        error = nil
        window = trip.flatMap { PickupWindow.of(trip: $0, listing: listing) }
    }

    /// `GET /commission/quote` for the typed total (the view debounces it 400 ms); a failure says "unavailable" and
    /// never blocks sending.
    func loadQuote(totalMinor: Int) async {
        guard totalMinor > 0 else { quote = nil; return }
        quote = .loading
        do {
            quote = .loaded(try await api.commissionQuote(serviceType: listing.serviceType, totalMinor: totalMinor).data)
        } catch {
            quote = .failed(error)
        }
    }

    enum Outcome {
        case sent(ProposalThreadDTO, [ApiWarning])
        /// The driver already has an open offer on this request: that thread opens instead.
        case existing(String)
    }

    /// Sends the offer at `unitPriceMinor` (the typed price, or the client's for "Mijoz narxiga roziman").
    func send(unitPriceMinor: Int, message: String?) async -> Outcome? {
        guard let tripId, let window, unitPriceMinor > 0, !sending else { return nil }
        sending = true
        error = nil
        defer { sending = false }
        let body = OfferBody.make(listing: listing, tripId: tripId, window: window, unitPriceMinor: unitPriceMinor, message: message)
        let action = "offer:\(listing.id):\(tripId):\(unitPriceMinor):\(body.pickupWindowStart):\(body.pickupWindowEnd)"
        do {
            let result = try await api.submitProposal(listingId: listing.id, body: body, idempotencyKey: keys.key(action))
            keys.settle(action)
            return .sent(result.data, result.warnings)
        } catch {
            keys.settle(action, after: error)
            if let id = MarketErrorText.openThread(error) { return .existing(id) }
            self.error = error
            return nil
        }
    }
}

// MARK: - Takliflarim

/// "Takliflarim": the driver's negotiations by tab (open / accepted / closed).
@MainActor @Observable
final class DriverProposalsModel {
    private let api: ElchiAPI
    private let banners: BannerCenter
    private let keys: ActionKeys

    var tab: ProposalTab = .open
    private(set) var lists: [ProposalTab: Loadable<[ProposalThreadDTO]>] = [:]
    private var threads: [String: DriverThreadModel] = [:]

    init(api: ElchiAPI, banners: BannerCenter, keys: ActionKeys) {
        self.api = api
        self.banners = banners
        self.keys = keys
    }

    func load(_ tab: ProposalTab? = nil) async {
        let tab = tab ?? self.tab
        do {
            lists[tab] = .loaded(try await api.listMyProposals(state: tab.rawValue, limit: 50).data)
        } catch {
            if lists[tab]?.value == nil { lists[tab] = .failed(error) }
        }
    }

    /// How many offers are still open (the Buyurtmalar entry's count); nil until known.
    var openCount: Int? { lists[.open]?.value?.count }

    func thread(_ id: String, initial: ProposalThreadDTO? = nil) -> DriverThreadModel {
        if let model = threads[id] {
            if let initial { model.replace(initial) }
            return model
        }
        let model = DriverThreadModel(id: id, initial: initial, api: api, banners: banners, keys: keys)
        model.onChanged = { [weak self] in
            await self?.load(.open)
            await self?.load(.accepted)
            await self?.load(.closed)
        }
        threads[id] = model
        return model
    }
}

/// One negotiation from the driver's side: history, and the answers its turn allows (accept / reject / counter on the
/// client's counter; withdraw on the driver's own pending version).
@MainActor @Observable
final class DriverThreadModel {
    let id: String
    private let api: ElchiAPI
    private let banners: BannerCenter
    private let keys: ActionKeys
    var onChanged: (@MainActor () async -> Void)?

    private(set) var thread: Loadable<ProposalThreadDTO>
    private(set) var busy: String?
    private(set) var error: Error?
    private(set) var warnings: [ApiWarning] = []
    /// The listing as the driver may read it (public view): names, and a terms version should the server ever add it.
    private(set) var listingJSON: JSONValue?
    /// A terms version the server named in `PROPOSAL_CHANGED` (the driver confirms the accept again with it).
    private(set) var learnedTerms: Int?
    /// After `PROPOSAL_CHANGED` on accept: the thread was read again and the driver must confirm once more.
    private(set) var confirmAgain = false

    init(id: String, initial: ProposalThreadDTO?, api: ElchiAPI, banners: BannerCenter, keys: ActionKeys) {
        self.id = id
        self.api = api
        self.banners = banners
        self.keys = keys
        thread = initial.map { .loaded($0) } ?? .loading
    }

    var listing: ListingPublicDTO? { try? listingJSON?.decode(ListingPublicDTO.self) }

    func replace(_ thread: ProposalThreadDTO) {
        if self.thread.value?.versions != nil && thread.versions == nil { return } // keep the detail's history
        self.thread = .loaded(thread)
    }

    func load() async {
        do {
            let fresh = try await api.getProposal(threadId: id).data
            thread = .loaded(fresh)
            if listingJSON == nil { listingJSON = try? await api.getListing(listingId: fresh.listingId).data }
        } catch {
            if thread.value == nil { thread = .failed(error) }
        }
    }

    func clear() {
        error = nil
        warnings = []
    }

    /// The advice the offer was sent with (`PRICE_OUTSIDE_REFERENCE`, `CONTACT_INFO_MASKED`): shown on the thread.
    func adopt(_ warnings: [ApiWarning]) { self.warnings = warnings }

    /// Accepts the client's current version at the listing terms version the driver can know (see `ListingTerms`).
    /// Returns the booking id. On `PROPOSAL_CHANGED` the thread is read again and the driver confirms once more.
    func accept() async -> String? {
        guard let thread = thread.value, let version = thread.currentVersion, busy == nil else { return nil }
        let terms = ListingTerms.version(listingJSON: listingJSON, learned: learnedTerms)
        var ack: PromoDriverAckInput?
        if case .driver(let quote)? = version.promoQuote {
            ack = PromoDriverAckInput(cashToCollectMinor: quote.cashToCollectMinor, commissionChargedMinor: quote.commissionChargedMinor)
        }
        let action = "accept:\(thread.id):\(version.id):\(terms)"
        busy = "accept"
        clear()
        defer { busy = nil }
        do {
            let result = try await api.acceptProposal(threadId: thread.id,
                                                      body: AcceptRequest(expectedListingTermsVersion: terms, promoDriverAck: ack, proposalVersionId: version.id),
                                                      idempotencyKey: keys.key(action))
            keys.settle(action)
            confirmAgain = false
            await load()
            await onChanged?()
            if case .string(let id)? = result.data["id"] { return id }
            return self.thread.value?.bookingId
        } catch {
            keys.settle(action, after: error)
            self.error = error
            if let current = ListingTerms.current(from: error) {
                learnedTerms = current
                confirmAgain = true
            }
            await afterRefusal(error)
            return nil
        }
    }

    func reject() async -> Bool {
        guard let version = thread.value?.currentVersion else { return false }
        return await run("reject", key: "reject:\(id):\(version.revision)") { api, key in
            try await api.rejectProposal(threadId: self.id, body: ProposalDecision(expectedRevision: version.revision), idempotencyKey: key).warnings
        }
    }

    func withdraw() async -> Bool {
        guard let version = thread.value?.currentVersion else { return false }
        return await run("withdraw", key: "withdraw:\(id):\(version.revision)") { api, key in
            try await api.withdrawProposal(threadId: self.id, body: ProposalDecision(expectedRevision: version.revision), idempotencyKey: key).warnings
        }
    }

    /// A new price on the client's counter, at the current pickup window.
    func counter(priceMinor: Int) async -> Bool {
        guard let version = thread.value?.currentVersion, priceMinor > 0 else { return false }
        return await run("counter", key: "counter:\(id):\(version.revision):\(priceMinor)") { api, key in
            try await api.counterProposal(threadId: self.id,
                                          body: ProposalCounter(expectedRevision: version.revision, pickupWindowEnd: version.pickupWindowEnd,
                                                                pickupWindowStart: version.pickupWindowStart, unitPriceMinor: priceMinor),
                                          idempotencyKey: key).warnings
        }
    }

    private func run(_ name: String, key action: String, _ send: (ElchiAPI, String) async throws -> [ApiWarning]) async -> Bool {
        guard busy == nil else { return false }
        busy = name
        clear()
        defer { busy = nil }
        do {
            warnings = try await send(api, keys.key(action))
            keys.settle(action)
            await load()
            await onChanged?()
            return true
        } catch {
            keys.settle(action, after: error)
            self.error = error
            await afterRefusal(error)
            return false
        }
    }

    /// The thread moved on under the driver (a new counter, expiry, the listing changed or was booked): show what is
    /// current, so the decision is made again.
    private func afterRefusal(_ error: Error) async {
        guard let error = error as? APIError, error.code != APIError.network else { return }
        await load()
        await onChanged?()
    }
}
