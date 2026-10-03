import Foundation
import Observation

/// Which booking command is running (one at a time).
enum BookingCommand: Equatable {
    case cancel, grant, revokeGrant, rate, report, block, complete
}

/// How rating the driver ended: sent now, or the server said it is done or closed (`RATING_ALREADY_EXISTS`,
/// `RATING_NOT_ALLOWED`) - either way there is nothing more to rate.
enum RatingOutcome: String, Equatable {
    case sent, already, notAllowed
}

/// Where the booking's live-location socket is and how to authenticate on it (the token goes in the subscribe
/// message, never in the URL).
struct TrackingConnection: Sendable {
    let socketURL: URL?
    let accessToken: @Sendable () -> String?
}

/// Stage 04: one booking of the client's - the detail (driver and vehicle, the driver's reputation, the receiver
/// from the client's own listing, the photo), cancel, the recipient tracking link, rating, the safety report and
/// block - and the models of its chat, support chat, live tracking and amendments. Kept for the session by
/// `ClientOrdersModel`, like a listing's model.
@MainActor @Observable
final class BookingModel {
    let id: String
    private let api: ElchiAPI
    private let keys: ActionKeys
    private weak var orders: ClientOrdersModel?
    private let mediaURL: @Sendable (String) -> URL?

    private(set) var booking: Loadable<ClientBookingDTO>
    /// `GET /users/{driver}/reputation?service_type=parcel`; nil until it answers (the card then shows no line).
    private(set) var reputation: ReputationDTO?
    /// The receiver as the client typed it on its request (`listing.parcel.receiver`).
    private(set) var receiver: ContactDetails?
    private(set) var parcelType: ParcelType?

    private(set) var running: BookingCommand?
    private(set) var commandError: Error?
    private(set) var failed: BookingCommand?
    private(set) var notice: String?
    private(set) var warnings: [ApiWarning] = []

    // Recipient link (the URL comes back once: kept for this screen only).
    var grantMinutes = TrackingTTL.defaultMinutes
    private(set) var grant: TrackingGrantDTO?

    private(set) var rating: RatingOutcome?
    /// The stars sent from this screen session ("Baho berildi: ★★★★ (4 / 5)"); the booking DTO has no rating, so after
    /// a reload only "Baho berildi" is known.
    private(set) var ratedStars: Int?
    /// The stars tapped on the detail's "Haydovchini baholang" card: the rating screen opens with them chosen.
    var ratingDraft = 0
    private(set) var report: ReportDTO?
    /// Blocked from this phone, or found among the client's blocks (`GET /blocks`): "Haydovchi bloklangan."
    private(set) var blocked = false
    private var blocksChecked = false

    let chat: BookingChatModel
    let support: SupportChatModel
    let tracking: BookingTrackingModel
    let amendments: AmendmentsModel
    /// Taksi: the boarding code and its reissue, and the cash record (client side).
    let code: BoardingCodeModel
    let cash: CashRecordModel

    init(id: String, initial: ClientBookingDTO?, api: ElchiAPI, keys: ActionKeys, orders: ClientOrdersModel,
         mediaURL: @escaping @Sendable (String) -> URL?, connection: TrackingConnection) {
        self.id = id
        self.api = api
        self.keys = keys
        self.orders = orders
        self.mediaURL = mediaURL
        booking = initial.map { .loaded($0) } ?? .loading
        rating = RatedBookings.outcome(id)
        chat = BookingChatModel(bookingId: id, api: api)
        support = SupportChatModel(bookingId: id, api: api, keys: keys)
        tracking = BookingTrackingModel(bookingId: id, api: api, connection: connection)
        amendments = AmendmentsModel(bookingId: id, api: api, keys: keys)
        code = BoardingCodeModel(bookingId: id, api: api, keys: keys)
        cash = CashRecordModel(bookingId: id, side: "client", api: api, keys: keys)
        amendments.onBookingChanged = { [weak self] in await self?.load() }
        cash.onChanged = { [weak self] in await self?.load() }
    }

    /// The parcel photo's signed link, resolved (Q6: short-lived - a reload fetches a fresh one).
    var photoURL: URL? { booking.value?.parcelPhoto.flatMap { mediaURL($0.url) } }

    /// The recipient link the server returned (it may be a path on the API host).
    var grantURL: URL? { grant?.url.flatMap(mediaURL) }

    /// The booking, then (once) the driver's reputation and the receiver from the client's own listing.
    func load() async {
        do {
            let json = try await api.getBooking(bookingId: id).data
            guard let dto = ClientBookingDTO.from(json) else { throw APIError(status: 200, code: APIError.server, message: "", details: nil) }
            apply(dto)
        } catch {
            if booking.value == nil { booking = .failed(error) }
        }
        guard let dto = booking.value else { return }
        async let reputation: Void = loadReputation(dto)
        async let receiver: Void = loadReceiver(dto)
        async let codes: Void = loadCode(dto)
        async let chatState: Void = chat.refreshState()
        async let blocks: Void = loadBlocks(dto)
        _ = await (reputation, receiver, codes, chatState, blocks)
    }

    /// The chat button's red count (no server unread count: messages counted minus those seen on this phone).
    var unreadChat: Int {
        BookingDetailRules.unread(messageCount: chat.state.value?.messageCount, seen: ChatSeen.count(id))
    }

    /// Once per screen model: is this driver among the client's blocks?
    private func loadBlocks(_ dto: ClientBookingDTO) async {
        guard !blocksChecked, !blocked, let driver = dto.driver else { return }
        guard let blocks = try? await api.listBlocks().data else { return }
        blocksChecked = true
        if blocks.contains(where: { $0.userId == driver.id }) { blocked = true }
    }

    /// Taksi: the boarding code while the passenger is still to board (the endpoint is empty afterwards).
    private func loadCode(_ dto: ClientBookingDTO) async {
        guard ClientTaxiActions.of(dto).showCode else { return }
        await code.load()
    }

    private func apply(_ dto: ClientBookingDTO) {
        booking = .loaded(dto)
        orders?.replace(dto)
    }

    private func loadReputation(_ dto: ClientBookingDTO) async {
        guard reputation == nil, let driver = dto.driver else { return }
        reputation = try? await api.getReputation(userId: driver.id, serviceType: dto.serviceType).data
    }

    private func loadReceiver(_ dto: ClientBookingDTO) async {
        guard receiver == nil, let listingId = dto.listingIds?.request,
              let listing = await orders?.listingDTO(listingId) else { return }
        receiver = listing.parcel?.receiver
        parcelType = listing.parcel?.parcelType
    }

    func clearNotice() {
        notice = nil
        warnings = []
        commandError = nil
        failed = nil
    }

    /// Opened afresh from the list: earlier results are not news any more, and the link was for that screen.
    func reset() {
        clearNotice()
        cash.clear()
        grant = nil
    }

    // MARK: Taksi: "Manzilga yetib keldim"

    /// The passenger confirms the arrival (`complete`, from `arrived`): the booking ends and rating opens. Without it
    /// the booking waits for an operator.
    func complete() async -> Bool {
        guard running == nil, let dto = booking.value, ClientTaxiActions.of(dto).canComplete else { return false }
        let action = "complete:\(dto.id):\(dto.version)"
        running = .complete
        clearNotice()
        defer { running = nil }
        do {
            let result = try await api.bookingAction(bookingId: dto.id, action: .complete, body: BookingActionRequest(expectedVersion: dto.version),
                                                    idempotencyKey: keys.key(action))
            keys.settle(action)
            if let fresh = ClientBookingDTO.from(result.data) { apply(fresh) } else { await load() }
            notice = "client.taxi.completed"
            return true
        } catch {
            keys.settle(action, after: error)
            commandError = error
            failed = .complete
            if let code = (error as? APIError)?.code, code != APIError.network { await load() }
            return false
        }
    }

    // MARK: Cancel

    func cancel(reason: BookingCancelReason, comment: String) async -> Bool {
        guard running == nil, let dto = booking.value else { return false }
        let text = comment.trimmingCharacters(in: .whitespacesAndNewlines)
        let action = "cancel:\(dto.id):\(dto.version)"
        running = .cancel
        clearNotice()
        defer { running = nil }
        do {
            let result = try await api.cancelBooking(bookingId: dto.id, body: BookingCancel(comment: text.isEmpty ? nil : text, expectedVersion: dto.version,
                                                                                        reasonCode: reason.rawValue), idempotencyKey: keys.key(action))
            keys.settle(action)
            if let fresh = ClientBookingDTO.from(result.data) { apply(fresh) } else { await load() }
            notice = "bookingCancel.done"
            warnings = result.warnings
            return true
        } catch {
            keys.settle(action, after: error)
            commandError = error
            failed = .cancel
            // The booking moved on (another phone, the driver, the operator): show where it is now.
            if let code = (error as? APIError)?.code, code != APIError.network { await load() }
            return false
        }
    }

    // MARK: Recipient link

    /// The bar's share icon: the link made on this screen again (the URL comes back once), else a new one with the
    /// default lifetime (1 hour). Nil when the server refused (the error is in `commandError`).
    func trackingLinkForSharing() async -> URL? {
        if let url = grantURL { return url }
        await createGrant()
        return grantURL
    }

    func createGrant() async {
        guard running == nil, booking.value != nil else { return }
        let minutes = TrackingTTL.clamp(grantMinutes)
        let action = "grant:\(id):\(minutes)"
        running = .grant
        commandError = nil
        failed = nil
        defer { running = nil }
        do {
            let result = try await api.createTrackingGrant(bookingId: id, body: TrackingGrantCreate(scope: .recipientLink, ttlMinutes: minutes),
                                                           idempotencyKey: keys.key(action))
            keys.settle(action)
            grant = result.data
        } catch {
            keys.settle(action, after: error)
            commandError = error
            failed = .grant
        }
    }

    func revokeGrant() async {
        guard let grant, running == nil else { return }
        running = .revokeGrant
        defer { running = nil }
        do {
            _ = try await api.revokeTrackingGrant(bookingId: id, grantId: grant.id)
            self.grant = nil
            notice = "trackingShare.revoked"
        } catch {
            commandError = error
            failed = .grant
        }
    }

    // MARK: Rating

    /// Done (sent, or the server says it is already rated / closed) returns true: the screen goes back.
    func rate(stars: Int, comment: String) async -> Bool {
        guard running == nil, (1...5).contains(stars) else { return false }
        let text = comment.trimmingCharacters(in: .whitespacesAndNewlines)
        let action = "rate:\(id)"
        running = .rate
        commandError = nil
        failed = nil
        defer { running = nil }
        do {
            _ = try await api.createRating(bookingId: id, body: RatingCreate(comment: text.isEmpty ? nil : text, stars: stars, subjectSide: "driver"),
                                           idempotencyKey: keys.key(action))
            keys.settle(action)
            finishRating(.sent)
            ratedStars = stars
            return true
        } catch {
            keys.settle(action, after: error)
            switch (error as? APIError)?.code {
            case "RATING_ALREADY_EXISTS"?: finishRating(.already); return true
            case "RATING_NOT_ALLOWED"?: finishRating(.notAllowed); return true
            default:
                commandError = error
                failed = .rate
                return false
            }
        }
    }

    private func finishRating(_ outcome: RatingOutcome) {
        rating = outcome
        RatedBookings.save(id, outcome)
    }

    // MARK: Safety

    func sendReport(reason: ReportReasonCode, details: String) async -> Bool {
        guard running == nil else { return false }
        let text = details.trimmingCharacters(in: .whitespacesAndNewlines)
        let action = "report:\(id):\(reason.rawValue):\(text)"
        running = .report
        commandError = nil
        failed = nil
        defer { running = nil }
        do {
            let result = try await api.createReport(body: ReportCreate(details: text.isEmpty ? nil : text, reasonCode: reason, subjectId: id,
                                                                       subjectType: .booking), idempotencyKey: keys.key(action))
            keys.settle(action)
            report = result.data
            warnings = result.warnings
            return true
        } catch {
            keys.settle(action, after: error)
            commandError = error
            failed = .report
            return false
        }
    }

    /// A new report after the "sent" note (the form starts empty again).
    func reportAgain() {
        report = nil
        warnings = []
    }

    func block() async -> Bool {
        guard running == nil, let driver = booking.value?.driver else { return false }
        let action = "block:\(driver.id)"
        running = .block
        commandError = nil
        failed = nil
        defer { running = nil }
        do {
            _ = try await api.createBlock(body: BlockCreate(userId: driver.id), idempotencyKey: keys.key(action))
            keys.settle(action)
            blocked = true
            return true
        } catch {
            keys.settle(action, after: error)
            commandError = error
            failed = .block
            return false
        }
    }
}

/// The server does not say whether the client has rated a booking; after a rating (or its refusal) the booking is
/// remembered on this phone so the detail shows "Baho berildi" instead of the button.
enum RatedBookings {
    private static func key(_ id: String) -> String { "elchi.rated.\(id)" }

    static func outcome(_ id: String) -> RatingOutcome? {
        UserDefaults.standard.string(forKey: key(id)).flatMap(RatingOutcome.init(rawValue:))
    }

    static func save(_ id: String, _ outcome: RatingOutcome) {
        UserDefaults.standard.set(outcome.rawValue, forKey: key(id))
    }
}

// MARK: - Amendments

/// "Shartlarni o'zgartirish": the history (newest first) and the client's proposals and answers. A parcel is one
/// consignment, so only the price changes (Q145); one open amendment at a time, two hours to answer.
@MainActor @Observable
final class AmendmentsModel {
    let bookingId: String
    private let api: ElchiAPI
    private let keys: ActionKeys
    /// After an accept the booking's terms changed: the detail reloads.
    var onBookingChanged: (@MainActor () async -> Void)?

    private(set) var items: Loadable<[AmendmentDTO]> = .loading
    /// "new" while a proposal is sent, else the amendment whose answer is in flight.
    private(set) var busy: String?
    private(set) var error: Error?
    /// Which action `error` belongs to ("new" or an amendment id).
    private(set) var errorFor: String?
    private(set) var notice: String?
    /// The new unit price an accepted amendment set (`client.booking.amendAcceptedPrice` says it).
    private(set) var noticePrice: Int?
    private(set) var warnings: [ApiWarning] = []

    init(bookingId: String, api: ElchiAPI, keys: ActionKeys) {
        self.bookingId = bookingId
        self.api = api
        self.keys = keys
    }

    func load() async {
        do {
            items = .loaded(try await api.listAmendments(bookingId: bookingId, limit: 20).data)
        } catch {
            if items.value == nil { items = .failed(error) }
        }
    }

    func clear() {
        error = nil
        errorFor = nil
        notice = nil
        noticePrice = nil
        warnings = []
    }

    /// A new price against the booking version the person saw; `reason` is required (the driver reads it).
    func propose(booking: ClientBookingDTO, priceMinor: Int, reason: String) async -> Bool {
        let text = reason.trimmingCharacters(in: .whitespacesAndNewlines)
        guard busy == nil, priceMinor > 0, !text.isEmpty else { return false }
        let action = "amend:\(booking.id):\(booking.version):\(priceMinor):\(text)"
        let ok = await run("new", action: action, notice: "amendment.sent") { api, key in
            try await api.createAmendment(bookingId: booking.id, body: AmendmentCreate(changes: AmendmentChanges(unitPriceMinor: priceMinor),
                                                                                    expectedVersion: booking.version, reason: text),
                                          idempotencyKey: key).warnings
        }
        if !ok, let code = (error as? APIError)?.code, ["VERSION_CONFLICT", "AMENDMENT_CONFLICT", "INVALID_STATE_TRANSITION"].contains(code) {
            await onBookingChanged?()
        }
        return ok
    }

    func accept(_ amendment: AmendmentDTO) async {
        let ok = await run(amendment.id, action: "amend-accept:\(amendment.id):\(amendment.version)", notice: "client.booking.amendAcceptedPrice") { api, key in
            try await api.acceptAmendment(amendmentId: amendment.id, body: AmendmentAccept(expectedVersion: amendment.version),
                                          idempotencyKey: key).warnings
        }
        if ok {
            noticePrice = amendment.newUnitPriceMinor
            await onBookingChanged?()
        }
    }

    func reject(_ amendment: AmendmentDTO) async {
        _ = await run(amendment.id, action: "amend-reject:\(amendment.id):\(amendment.version)", notice: "proposal.rejected") { api, key in
            try await api.rejectAmendment(amendmentId: amendment.id, body: AmendmentDecision(expectedVersion: amendment.version),
                                          idempotencyKey: key).warnings
        }
    }

    func withdraw(_ amendment: AmendmentDTO) async {
        _ = await run(amendment.id, action: "amend-withdraw:\(amendment.id):\(amendment.version)", notice: "amendment.withdrawn") { api, key in
            try await api.withdrawAmendment(amendmentId: amendment.id, body: AmendmentDecision(expectedVersion: amendment.version),
                                            idempotencyKey: key).warnings
        }
    }

    private func run(_ target: String, action: String, notice noticeKey: String,
                     _ send: (ElchiAPI, String) async throws -> [ApiWarning]) async -> Bool {
        guard busy == nil else { return false }
        busy = target
        clear()
        defer { busy = nil }
        do {
            warnings = try await send(api, keys.key(action))
            keys.settle(action)
            notice = noticeKey
            await load()
            return true
        } catch {
            keys.settle(action, after: error)
            self.error = error
            errorFor = target
            // Refused because it changed meanwhile (expired, answered, withdrawn): show its current state.
            if (error as? APIError)?.code != APIError.network { await load() }
            return false
        }
    }
}
