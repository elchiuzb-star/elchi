import Foundation
import Observation

/// "Kuzatuv": the booking's live location (K8). The WebSocket pushes the tracking view about every 5 s; while it is
/// down the screen polls HTTP every 15 s and reconnects with backoff (5 -> 60 s). Close codes: 4401 = the token is
/// stale (one HTTP call refreshes it, then one retry), 4403 = the window is closed (poll until it opens), 4404 = no
/// such booking (stop). Everything stops when the screen leaves or the app goes to the background (the view's task
/// is cancelled). No ETA is shown: the pilot has none and the app never invents one.
@MainActor @Observable
final class BookingTrackingModel {
    let bookingId: String
    private let api: ElchiAPI
    private let connection: TrackingConnection

    /// The last tracking view (from the socket or HTTP).
    private(set) var tracking: BookingTrackingDTO?
    /// Why live location is not shown: `parcel_not_picked_up`, `booking_finished`, `trip_finished`,
    /// `not_yet_open`, or `feature_off` (the corridor has no live tracking).
    private(set) var closedReason: String?
    private(set) var error: Error?
    private(set) var loaded = false
    /// A point arrived on the socket and the socket is still open.
    private(set) var socketLive = false

    static let pollSeconds: UInt64 = 15

    init(bookingId: String, api: ElchiAPI, connection: TrackingConnection) {
        self.bookingId = bookingId
        self.api = api
        self.connection = connection
    }

    /// The window is known to be closed (a socket would only be closed with 4403).
    var windowClosed: Bool { closedReason != nil }

    // MARK: Running

    /// Runs until cancelled: the socket loop and, alongside it, HTTP polling whenever the socket is not live.
    func run() async {
        await poll()
        await withTaskGroup(of: Void.self) { group in
            group.addTask { await self.pollLoop() }
            group.addTask { await self.socketLoop() }
        }
        socketLive = false
    }

    private func pollLoop() async {
        while !Task.isCancelled {
            try? await Task.sleep(nanoseconds: Self.pollSeconds * 1_000_000_000)
            if Task.isCancelled { return }
            if !socketLive { await poll() }
        }
    }

    private func socketLoop() async {
        guard let url = connection.socketURL else { return } // no socket address: HTTP polling alone
        var attempt = 0
        var refreshed = false
        while !Task.isCancelled {
            if windowClosed {
                // 4403 or a closed window over HTTP: the poller tells when it opens.
                try? await Task.sleep(nanoseconds: Self.pollSeconds * 1_000_000_000)
                continue
            }
            guard let token = connection.accessToken() else { return }
            let stream = TrackingStream(url: url)
            let code = await stream.run(bookingId: bookingId, accessToken: token) { [weak self] event in
                await self?.receive(event)
            }
            socketLive = false
            if Task.isCancelled { return }
            switch code {
            case 4401:
                // The token went stale: an authenticated HTTP call refreshes it, then one more try.
                if refreshed { return }
                refreshed = true
                await poll()
                continue
            case 4403:
                await poll()
                continue
            case 4404:
                return
            default:
                break
            }
            try? await Task.sleep(nanoseconds: UInt64(TrackingSocket.backoff(attempt: attempt) * 1_000_000_000))
            attempt += 1
        }
    }

    private func receive(_ event: TrackingStream.Event) {
        switch event {
        case .point(let dto):
            socketLive = true
            apply(dto)
        case .stale(let freshness):
            if let current = tracking, LiveFreshness.rank(freshness) > LiveFreshness.rank(current.freshness) {
                var copy = current
                copy.freshness = freshness
                tracking = copy
            }
        }
    }

    /// One HTTP read. `TRACKING_WINDOW_NOT_OPEN` is a state (not an error): its reason becomes the grey note.
    func poll() async {
        do {
            let dto = try await api.getBookingTracking(bookingId: bookingId).data
            // A slower HTTP answer never overwrites what the live socket already showed.
            if socketLive { return }
            apply(dto)
            error = nil
        } catch let failure as APIError where failure.code == "TRACKING_WINDOW_NOT_OPEN" {
            if case .string(let reason)? = failure.details?["reason"] { closedReason = reason } else { closedReason = "not_yet_open" }
            error = nil
        } catch let failure as APIError where failure.code == "FEATURE_DISABLED" {
            closedReason = "feature_off"
            error = nil
        } catch {
            self.error = error
        }
        loaded = true
    }

    private func apply(_ dto: BookingTrackingDTO) {
        // Never step back to an older point (two answers can cross).
        if let old = tracking?.lastPoint.flatMap({ ServerTime.parse($0.capturedAt) }),
           let new = dto.lastPoint.flatMap({ ServerTime.parse($0.capturedAt) }), new < old { return }
        tracking = dto
        closedReason = dto.window.isOpen ? nil : dto.window.reason.rawValue
        loaded = true
    }

    /// The freshness to show at `now`: the server's bucket, only ever made worse by the point's age on this phone.
    func freshness(now: Date) -> TrackingFreshness {
        guard let tracking else { return .noData }
        return LiveFreshness.effective(server: tracking.freshness, capturedAt: tracking.lastPoint.flatMap { ServerTime.parse($0.capturedAt) },
                                       now: now)
    }
}

/// One K8 WebSocket connection (URLSessionWebSocketTask): subscribe with the access token in the first frame (never
/// in the URL), then deliver pushes until the server closes. Returns the close code (0 when none came back).
struct TrackingStream: Sendable {
    enum Event: Sendable {
        case point(BookingTrackingDTO)
        case stale(TrackingFreshness)
    }

    let url: URL

    private struct Frame: Decodable {
        let type: String
        let data: JSONValue?
    }

    private struct Subscribe: Encodable {
        let action = "subscribe"
        let bookingId: String
        let accessToken: String

        enum CodingKeys: String, CodingKey {
            case action
            case bookingId = "booking_id"
            case accessToken = "access_token"
        }
    }

    func run(bookingId: String, accessToken: String, onEvent: @escaping @Sendable (Event) async -> Void) async -> Int {
        let task = URLSession.shared.webSocketTask(with: url)
        return await withTaskCancellationHandler {
            task.resume()
            do {
                let subscribe = try JSONEncoder().encode(Subscribe(bookingId: bookingId, accessToken: accessToken))
                try await task.send(.string(String(decoding: subscribe, as: UTF8.self)))
                while !Task.isCancelled {
                    let message = try await task.receive()
                    let data: Data
                    switch message {
                    case .string(let text): data = Data(text.utf8)
                    case .data(let bytes): data = bytes
                    @unknown default: continue
                    }
                    if let event = Self.decode(data) { await onEvent(event) }
                }
            } catch {
                // The server closed (the close code says why) or the network dropped (no code).
            }
            let code = task.closeCode.rawValue
            task.cancel(with: .goingAway, reason: nil)
            return code
        } onCancel: {
            task.cancel(with: .goingAway, reason: nil)
        }
    }

    static func decode(_ data: Data) -> Event? {
        guard let frame = try? JSONDecoder().decode(Frame.self, from: data) else { return nil }
        switch frame.type {
        case "tracking.point":
            return (try? frame.data?.decode(BookingTrackingDTO.self)).flatMap { $0 }.map(Event.point)
        case "tracking.stale":
            if case .string(let raw)? = frame.data?["freshness"] {
                return (try? JSONDecoder().decode(TrackingFreshness.self, from: Data("\"\(raw)\"".utf8))).map(Event.stale)
            }
            return nil
        default:
            return nil
        }
    }
}
