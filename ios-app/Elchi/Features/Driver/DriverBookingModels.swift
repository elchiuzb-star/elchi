import Foundation
import Observation

// MARK: - Buyurtmalar (the driver's bookings)

/// `GET /me/bookings?role=driver`, cursor-paged, and one detail model per opened booking (kept for the session, like
/// the trips).
@MainActor @Observable
final class DriverBookingsModel {
    private let api: ElchiAPI
    private let keys: ActionKeys
    private let banners: BannerCenter
    private let mediaURL: @Sendable (String) -> URL?
    private let connection: TrackingConnection

    private(set) var items: Loadable<[DriverBookingDTO]> = .loading
    private(set) var nextCursor: String?
    private(set) var loadingMore = false
    var filter: DriverBookingFilter = .active
    private var details: [String: DriverBookingModel] = [:]

    static let pageSize = 30

    init(api: ElchiAPI, keys: ActionKeys, banners: BannerCenter, mediaURL: @escaping @Sendable (String) -> URL?, connection: TrackingConnection) {
        self.api = api
        self.keys = keys
        self.banners = banners
        self.mediaURL = mediaURL
        self.connection = connection
    }

    var visible: [DriverBookingDTO] { (items.value ?? []).filter { filter.includes($0.status) } }

    func load() async {
        do {
            let result = try await api.listMyBookings(role: "driver", limit: Self.pageSize)
            items = .loaded(result.data.compactMap(DriverBookingDTO.from))
            nextCursor = result.meta?.nextCursor
        } catch {
            if items.value == nil { items = .failed(error) }
        }
    }

    func loadMore() async {
        guard let cursor = nextCursor, !loadingMore else { return }
        loadingMore = true
        defer { loadingMore = false }
        guard let result = try? await api.listMyBookings(role: "driver", cursor: cursor, limit: Self.pageSize) else { return }
        let known = Set((items.value ?? []).map(\.id))
        items = .loaded((items.value ?? []) + result.data.compactMap(DriverBookingDTO.from).filter { !known.contains($0.id) })
        nextCursor = result.meta?.nextCursor
    }

    func detail(_ id: String) -> DriverBookingModel {
        if let model = details[id] { return model }
        let model = DriverBookingModel(id: id, initial: items.value?.first { $0.id == id }, api: api, keys: keys, banners: banners,
                                       mediaURL: mediaURL, connection: connection)
        model.onChange = { [weak self] dto in self?.replace(dto) }
        details[id] = model
        return model
    }

    private func replace(_ dto: DriverBookingDTO) {
        guard var list = items.value else { return }
        if let index = list.firstIndex(where: { $0.id == dto.id }) { list[index] = dto } else { list.insert(dto, at: 0) }
        items = .loaded(list)
    }
}

/// One booking as its driver sees it (parcel): the detail, the client's reputation, "Keldim", cancel, rating the
/// client, the safety report and block - and the shared chat, support chat, tracking and amendment models.
@MainActor @Observable
final class DriverBookingModel {
    let id: String
    private let api: ElchiAPI
    private let keys: ActionKeys
    private let banners: BannerCenter
    private let mediaURL: @Sendable (String) -> URL?
    var onChange: ((DriverBookingDTO) -> Void)?

    private(set) var booking: Loadable<DriverBookingDTO>
    /// `GET /users/{client}/reputation?service_type=parcel`; nil until it answers.
    private(set) var reputation: ReputationDTO?
    private(set) var running: BookingCommand?
    private(set) var arriving = false
    private(set) var commandError: Error?
    private(set) var failed: BookingCommand?
    private(set) var arriveError: Error?
    private(set) var notice: String?
    private(set) var warnings: [ApiWarning] = []
    private(set) var arrivedSent: Bool
    private(set) var rating: RatingOutcome?
    /// The stars sent from this screen session ("Baho berildi: ★★★★ (4 / 5)"); after a reload only "Baho berildi".
    private(set) var ratedStars: Int?
    private(set) var report: ReportDTO?
    private(set) var blocked = false

    let chat: BookingChatModel
    let support: SupportChatModel
    let tracking: BookingTrackingModel
    let amendments: AmendmentsModel
    /// Taksi: board / drop-off / no-show, and the cash record (driver side).
    let taxi: DriverTaxiModel
    let cash: CashRecordModel

    init(id: String, initial: DriverBookingDTO?, api: ElchiAPI, keys: ActionKeys, banners: BannerCenter,
         mediaURL: @escaping @Sendable (String) -> URL?, connection: TrackingConnection) {
        self.id = id
        self.api = api
        self.keys = keys
        self.banners = banners
        self.mediaURL = mediaURL
        booking = initial.map { .loaded($0) } ?? .loading
        arrivedSent = ArrivedSignals.sent(id)
        rating = RatedBookings.outcome(id)
        chat = BookingChatModel(bookingId: id, api: api)
        support = SupportChatModel(bookingId: id, api: api, keys: keys)
        tracking = BookingTrackingModel(bookingId: id, api: api, connection: connection)
        amendments = AmendmentsModel(bookingId: id, api: api, keys: keys)
        taxi = DriverTaxiModel(bookingId: id, api: api, keys: keys)
        cash = CashRecordModel(bookingId: id, side: "driver", api: api, keys: keys)
        amendments.onBookingChanged = { [weak self] in await self?.load() }
        cash.onChanged = { [weak self] in await self?.load() }
        taxi.onBooking = { [weak self] json in
            guard let self else { return }
            if let json, let fresh = DriverBookingDTO.from(json) { apply(fresh) } else { await load() }
        }
    }

    /// The parcel photo's signed link (Q6: short-lived - a reload fetches a fresh one).
    var photoURL: URL? { booking.value?.base.parcelPhoto.flatMap { mediaURL($0.url) } }

    var actions: DriverBookingActions? {
        booking.value.map { DriverBookingActions.of($0.status, arrivedSent: arrivedSent, updatedAt: ServerTime.parse($0.base.updatedAt)) }
    }

    func load() async {
        do {
            let json = try await api.getBooking(bookingId: id).data
            guard let dto = DriverBookingDTO.from(json) else { throw APIError(status: 200, code: APIError.server, message: "", details: nil) }
            apply(dto)
        } catch {
            if booking.value == nil { booking = .failed(error) }
        }
        if reputation == nil, let client = booking.value?.client {
            reputation = try? await api.getReputation(userId: client.id, serviceType: booking.value?.base.serviceType ?? .parcel).data
        }
        // DESIGN08 2.8 / 7.4: the contact bar's unread count and the open amendment on the detail.
        async let chatState: Void = chat.refreshState()
        async let amends: Void = amendments.load()
        _ = await (chatState, amends)
        // Taksi before boarding: when "Keldim" was recorded and how long the trip waits (the no-show gate).
        if let dto = booking.value, dto.base.serviceType == .passenger, DriverBookingActions.preService.contains(dto.status) {
            await taxi.loadGate(tripId: dto.tripId)
            if taxi.arrivedAt != nil { arrivedSent = true }
        }
    }

    private func apply(_ dto: DriverBookingDTO) {
        booking = .loaded(dto)
        onChange?(dto)
    }

    /// The chat button's red count (no server unread count: messages counted minus those seen on this phone).
    var unreadChat: Int {
        BookingDetailRules.unread(messageCount: chat.state.value?.messageCount, seen: ChatSeen.count(id))
    }

    func clearNotice() {
        notice = nil
        warnings = []
        commandError = nil
        failed = nil
        arriveError = nil
        taxi.clear()
        cash.clear()
    }

    // MARK: Keldim

    /// `arrive_at_pickup`: a signal to the client (the server records it once; the status does not change).
    func arrive() async {
        guard !arriving, let dto = booking.value else { return }
        let action = "arrive:\(dto.id)"
        arriving = true
        clearNotice()
        defer { arriving = false }
        do {
            let result = try await api.bookingAction(bookingId: dto.id, action: .arriveAtPickup,
                                                    body: BookingActionRequest(expectedVersion: dto.base.version), idempotencyKey: keys.key(action))
            keys.settle(action)
            if let fresh = DriverBookingDTO.from(result.data) { apply(fresh) }
            arrivedSent = true
            ArrivedSignals.mark(dto.id)
            taxi.arrived(at: Date())
            banners.ok("driver.booking.arrived")
        } catch {
            keys.settle(action, after: error)
            arriveError = error
            if (error as? APIError)?.code == "VERSION_CONFLICT" { await load() }
        }
    }

    // MARK: Cancel

    func cancel(reason: DriverCancelReason, comment: String) async -> Bool {
        guard running == nil, let dto = booking.value else { return false }
        let text = comment.trimmingCharacters(in: .whitespacesAndNewlines)
        let action = "cancel:\(dto.id):\(dto.base.version)"
        running = .cancel
        clearNotice()
        defer { running = nil }
        do {
            let result = try await api.cancelBooking(bookingId: dto.id, body: BookingCancel(comment: text.isEmpty ? nil : text, expectedVersion: dto.base.version,
                                                                                        reasonCode: reason.rawValue), idempotencyKey: keys.key(action))
            keys.settle(action)
            if let fresh = DriverBookingDTO.from(result.data) { apply(fresh) } else { await load() }
            notice = "bookingCancel.done"
            warnings = result.warnings
            return true
        } catch {
            keys.settle(action, after: error)
            commandError = error
            failed = .cancel
            if let code = (error as? APIError)?.code, code != APIError.network { await load() }
            return false
        }
    }

    // MARK: Rating the client

    func rate(stars: Int, comment: String) async -> Bool {
        guard running == nil, (1...5).contains(stars) else { return false }
        let text = comment.trimmingCharacters(in: .whitespacesAndNewlines)
        let action = "rate:\(id)"
        running = .rate
        commandError = nil
        failed = nil
        defer { running = nil }
        do {
            _ = try await api.createRating(bookingId: id, body: RatingCreate(comment: text.isEmpty ? nil : text, stars: stars, subjectSide: "client"),
                                           idempotencyKey: keys.key(action))
            keys.settle(action)
            ratedStars = stars
            finishRating(.sent)
            banners.ok("client.booking.rateThanks")
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

    func reportAgain() {
        report = nil
        warnings = []
    }

    func block() async -> Bool {
        guard running == nil, let client = booking.value?.client else { return false }
        let action = "block:\(client.id)"
        running = .block
        commandError = nil
        failed = nil
        defer { running = nil }
        do {
            _ = try await api.createBlock(body: BlockCreate(userId: client.id), idempotencyKey: keys.key(action))
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

extension DriverBookingModel: BookingScreenHost, SafetyHost, RatingHost {
    var bookingBase: ClientBookingDTO? { booking.value?.base }
    var side: String { "driver" }
    var counterpartyKnown: Bool { booking.value?.client != nil }
}
