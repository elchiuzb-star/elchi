import Foundation
import Observation
import os

// MARK: - What the tracker needs from the outside

/// The phone's location permission in the tracker's words.
public enum LocationAuthorization: String, Equatable, Sendable {
    case notDetermined, denied, restricted, whenInUse, always

    var granted: Bool { self == .whenInUse || self == .always }
}

/// The position source (CoreLocation in the app, a fake in tests). Main-actor: the manager reports on the main thread.
@MainActor
public protocol LocationSource: AnyObject {
    var authorization: LocationAuthorization { get }
    /// Precise location is on (`accuracyAuthorization == .fullAccuracy`).
    var precise: Bool { get }
    var onFix: ((GeoFix) -> Void)? { get set }
    /// Permission or precision changed (Settings, the system prompt).
    var onAuthorizationChange: (() -> Void)? { get set }
    func requestWhenInUse()
    func requestAlways()
    /// Starts (or reconfigures) updates; `background` = keep them while the app is in the background (Always only).
    func start(background: Bool)
    func stop()
    /// Asks for a fresh fix now (a standing phone may stop reporting).
    func refresh()
}

/// K1/K2/K3 (the generated calls in the app, a fake in tests).
public protocol TrackingTransport: Sendable {
    func create(_ body: TrackingSessionCreate, idempotencyKey: String) async throws -> TrackingSessionDTO
    func send(sessionId: String, _ body: PointsBatchIn) async throws -> PointsBatchAck
    func close(sessionId: String, idempotencyKey: String) async throws
}

/// The generated v2 calls.
struct APITrackingTransport: TrackingTransport {
    let api: ElchiAPI

    func create(_ body: TrackingSessionCreate, idempotencyKey: String) async throws -> TrackingSessionDTO {
        try await api.createTrackingSession(body: body, idempotencyKey: idempotencyKey).data
    }

    func send(sessionId: String, _ body: PointsBatchIn) async throws -> PointsBatchAck {
        #if DEBUG
        // Offline drill on the simulator (the backend must not be stopped): `defaults write uz.elchi.app
        // elchiDebugGpsOffline -bool YES` makes K2 fail like a dead network; K1/K3 and the rest of the app still work.
        if UserDefaults.standard.bool(forKey: "elchiDebugGpsOffline") {
            throw APIError(status: 0, code: APIError.network, message: "debug offline", details: nil)
        }
        #endif
        return try await api.ingestTrackingPoints(sessionId: sessionId, body: body).data
    }

    func close(sessionId: String, idempotencyKey: String) async throws {
        _ = try await api.closeTrackingSession(sessionId: sessionId, idempotencyKey: idempotencyKey)
    }
}

public struct BatteryState: Equatable, Sendable {
    public let pct: Int
    public let charging: Bool
}

// MARK: - State

public enum TrackerPhase: Equatable, Sendable {
    case idle, starting, active, permissionDenied, unavailable, error, ended
}

/// Why a publisher is no longer running.
public enum TrackerEndReason: Equatable, Sendable {
    case stopped, superseded, closed, tripFinished, unauthorized
}

/// A stretch without any fix: the app was in the background (without Always) or the phone gave no position.
public struct TrackerGap: Equatable, Sendable {
    public let from: Date
    public let to: Date
    public let background: Bool
}

public struct TrackerSnapshot: Equatable, Sendable {
    public var phase: TrackerPhase = .idle
    public var tripId: String?
    public var sessionId: String?
    /// Points waiting for the server's ACK.
    public var queued = 0
    /// Points that will never reach the server (queue limits, refusals) - missing history, said out loud.
    public var dropped = 0
    public var lastFixAt: Date?
    public var lastAccuracyM: Int?
    /// Device time of the last ACK.
    public var lastSentAt: Date?
    /// The app is in the background.
    public var inBackground = false
    /// The last send failed for a transient reason (no network, 5xx); points are kept.
    public var offline = false
    public var authorization: LocationAuthorization = .notDetermined
    public var precise = true
    /// The "Always" question was asked once on this phone (iOS asks it at most once).
    public var askedAlways = false
    /// Updates were started with background delivery (Always granted): the only state in which the bar may say that
    /// the location goes out with the app in the background.
    public var backgroundUpdates = false
    public var battery: BatteryState?
    public var lastGap: TrackerGap?
    public var gapCount = 0
    public var errorCode: String?
    public var endReason: TrackerEndReason?

    public init() {}
}

// MARK: - The publisher

/// The driver's native GPS publisher (spec §10.3, Q148), a port of the web `driverTracker.ts` with background delivery:
///
/// - `start(trip)`: deliver what an earlier run left on disk to its own session, open a new writer session (K1, a
///   restarted app gets a new one), move the leftovers into it (renumbered), then record fixes into the outbox and
///   send every `recommended_interval_s` (and from the location callbacks, so a backgrounded app keeps sending).
/// - `stop()`: last flush, K3, forget the outbox. `flushBeforeComplete()` before the trip's `complete`;
///   `tripEnded()` after it (the server closes the session itself).
/// - The server may end the session: another device took over (`superseded`) or the trip ended (`closed`).
///
/// Nothing is invented: "sending" needs a real fix in the last 30 s; queued and dropped points are counted.
@MainActor @Observable
public final class DriverTracker {
    public private(set) var snapshot = TrackerSnapshot()

    private let transport: TrackingTransport
    private let store: OutboxStore
    private let location: LocationSource
    private let now: @MainActor () -> Date
    private let batteryReader: @MainActor () -> BatteryState?
    private let deviceId: String
    private let appVersion: String
    private let defaults: UserDefaults
    private let autoTick: Bool
    private let log = Logger(subsystem: "uz.elchi.app", category: "gps")

    private var outbox: GpsOutbox?
    private var lastRecorded: GeoFix?
    private var pendingFix: GeoFix?
    private var intervalS: TimeInterval = 10
    private var ticker: Task<Void, Never>?
    private var flushTask: Task<Void, Never>?
    private var lastFlushStart: Date?
    private var heartbeatAt: Date?
    private var backgroundSinceLastFix = false
    /// Waiting for the answer to the permission prompt before the session opens.
    private var awaitingPermission = false
    /// The server said the batch is too large: send smaller ones (halved, at least 1).
    private var batchLimit = GpsContract.maxPointsPerBatch
    /// Bumped on every start/stop, so a late answer from an older run cannot touch the current one.
    private var generation = 0

    static let askedAlwaysKey = "elchi.gps.askedAlways"

    public init(transport: TrackingTransport, store: OutboxStore, location: LocationSource, deviceId: String, appVersion: String,
                defaults: UserDefaults = .standard, now: @escaping @MainActor () -> Date = { Date() },
                battery: @escaping @MainActor () -> BatteryState? = { nil }, autoTick: Bool = true) {
        self.transport = transport
        self.store = store
        self.location = location
        self.deviceId = deviceId
        self.appVersion = appVersion
        self.defaults = defaults
        self.now = now
        self.batteryReader = battery
        self.autoTick = autoTick
        snapshot.askedAlways = defaults.bool(forKey: Self.askedAlwaysKey)
        readPermission()
        location.onFix = { [weak self] fix in self?.onFix(fix) }
        location.onAuthorizationChange = { [weak self] in self?.permissionChanged() }
    }

    // MARK: Commands

    /// This trip is being published (or is on its way to be).
    public func isRunning(_ tripId: String? = nil) -> Bool {
        let running = snapshot.phase == .starting || snapshot.phase == .active
        return running && (tripId == nil || snapshot.tripId == tripId)
    }

    public func start(_ tripId: String) async {
        if isRunning(tripId) { return }
        if isRunning() { await stop() }
        generation += 1
        let generation = generation
        var fresh = TrackerSnapshot()
        fresh.authorization = snapshot.authorization
        fresh.precise = snapshot.precise
        fresh.askedAlways = snapshot.askedAlways
        fresh.battery = batteryReader()
        fresh.inBackground = snapshot.inBackground
        fresh.phase = .starting
        fresh.tripId = tripId
        snapshot = fresh
        readPermission()
        switch snapshot.authorization {
        case .denied, .restricted:
            snapshot.phase = .permissionDenied
        case .notDetermined:
            // The system asks; the session opens once the answer is "allow" (see `permissionChanged`).
            awaitingPermission = true
            location.requestWhenInUse()
        case .whenInUse, .always:
            await open(tripId, generation: generation)
        }
    }

    /// The driver ends publishing: deliver what is queued, close the session, forget the outbox.
    public func stop() async {
        let sessionId = snapshot.sessionId
        let wasActive = snapshot.phase == .active
        if wasActive { await flush() }
        teardown()
        generation += 1
        if wasActive, let sessionId {
            // The server closes the session with the trip anyway; the local stop stands either way.
            try? await transport.close(sessionId: sessionId, idempotencyKey: UUID().uuidString)
        }
        store.clear()
        outbox = nil
        snapshot.phase = .ended
        snapshot.endReason = .stopped
        snapshot.queued = 0
        snapshot.offline = false
    }

    /// Right before the trip's `complete`: the last points go out while the session still accepts them.
    public func flushBeforeComplete(_ tripId: String) async {
        guard snapshot.phase == .active, snapshot.tripId == tripId else { return }
        await flush()
    }

    /// The trip was completed or cancelled: the server closed the session with it.
    public func tripEnded(_ tripId: String) {
        guard snapshot.tripId == tripId, snapshot.phase != .idle else { return }
        end(.tripFinished)
    }

    /// Sign-out: back to the untouched state. Queued points stay on disk for the next start on this phone.
    public func reset() {
        teardown()
        generation += 1
        outbox = nil
        awaitingPermission = false
        var fresh = TrackerSnapshot()
        fresh.authorization = snapshot.authorization
        fresh.precise = snapshot.precise
        fresh.askedAlways = snapshot.askedAlways
        snapshot = fresh
    }

    /// The app went to the background or came back (scene phase).
    public func setBackground(_ background: Bool) {
        guard snapshot.inBackground != background else { return }
        snapshot.inBackground = background
        if background { backgroundSinceLastFix = true }
        snapshot.battery = batteryReader()
        if !background {
            readPermission()
            if snapshot.phase == .active { Task { await flush() } }
        }
    }

    /// One sampling / heartbeat / send round (the ticker calls it; tests call it directly).
    public func tick() async {
        guard snapshot.phase == .active else { return }
        snapshot.battery = batteryReader()
        recordPending()
        heartbeat()
        await flush()
    }

    // MARK: Opening a session

    private func open(_ tripId: String, generation: Int) async {
        awaitingPermission = false
        // What an earlier run left belongs to that run's session: deliver it there first, while it is still the active
        // one (the K1 below supersedes it). What it could not take moves to the new session of the same trip.
        var leftover: GpsOutbox?
        if let stored = store.load() { leftover = await drainLeftover(stored) }
        guard generation == self.generation else { return }
        let session: TrackingSessionDTO
        do {
            session = try await transport.create(TrackingSessionCreate(appVersion: appVersion, deviceId: deviceId, platform: .ios, tripId: tripId),
                                                 idempotencyKey: UUID().uuidString)
        } catch {
            guard generation == self.generation else { return }
            snapshot.phase = .error
            snapshot.errorCode = (error as? APIError)?.code ?? APIError.network
            log.error("K1 failed: \(self.snapshot.errorCode ?? "?", privacy: .public)")
            if let leftover { store.save(leftover) }
            return
        }
        guard generation == self.generation else { return }
        var fresh = GpsOutbox(tripId: tripId, sessionId: session.id)
        if let leftover, leftover.tripId == tripId, !leftover.points.isEmpty || leftover.dropped > 0 {
            fresh.adopt(leftover, now: now())
            log.info("adopted \(leftover.points.count) leftover points into \(session.id, privacy: .public)")
        }
        outbox = fresh
        lastRecorded = nil
        pendingFix = nil
        batchLimit = GpsContract.maxPointsPerBatch
        intervalS = TimeInterval(max(5, session.recommendedIntervalS))
        persist()
        snapshot.phase = .active
        snapshot.sessionId = session.id
        snapshot.errorCode = nil
        syncQueue()
        log.info("K1 session \(session.id, privacy: .public) trip \(tripId, privacy: .public) interval \(Int(self.intervalS))s")
        configureUpdates()
        // Ask for "Always" once, after "While using" (iOS shows its own upgrade question).
        if snapshot.authorization == .whenInUse && !snapshot.askedAlways {
            snapshot.askedAlways = true
            defaults.set(true, forKey: Self.askedAlwaysKey)
            location.requestAlways()
        }
        backgroundSinceLastFix = snapshot.inBackground
        if !(outbox?.points.isEmpty ?? true) { Task { await flush() } }
        startTicker(generation: generation)
    }

    private func configureUpdates() {
        let background = snapshot.authorization == .always
        snapshot.backgroundUpdates = background
        location.start(background: background)
    }

    private func startTicker(generation: Int) {
        ticker?.cancel()
        guard autoTick else { return }
        let interval = intervalS
        ticker = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(interval))
                guard !Task.isCancelled, let self, self.generation == generation else { return }
                await self.tick()
            }
        }
    }

    // MARK: Permission

    private func readPermission() {
        snapshot.authorization = location.authorization
        snapshot.precise = location.precise
    }

    private func permissionChanged() {
        let before = snapshot.authorization
        readPermission()
        let state = snapshot.authorization
        log.info("permission \(before.rawValue, privacy: .public) -> \(state.rawValue, privacy: .public)")
        switch snapshot.phase {
        case .starting where awaitingPermission:
            if state.granted, let tripId = snapshot.tripId {
                Task { await open(tripId, generation: generation) }
            } else if state == .denied || state == .restricted {
                awaitingPermission = false
                snapshot.phase = .permissionDenied
            }
        case .active:
            if !state.granted {
                // Revoked mid-trip: queued points still go out, then publishing stops and says why.
                let generation = generation
                Task {
                    await flush()
                    guard generation == self.generation else { return }
                    teardown()
                    snapshot.phase = .permissionDenied
                }
            } else if state != before {
                configureUpdates() // While using -> Always: background delivery on (and back)
            }
        case .permissionDenied:
            // Fixed in Settings: pick up where the denial stopped us.
            if state.granted, let tripId = snapshot.tripId { Task { await start(tripId) } }
        default:
            break
        }
    }

    // MARK: Fixes

    private func onFix(_ incoming: GeoFix) {
        guard snapshot.phase == .active, outbox != nil else { return }
        heartbeatAt = nil
        var fix = incoming
        let previous = snapshot.lastFixAt
        snapshot.lastFixAt = previous.map { max($0, fix.timestamp) } ?? fix.timestamp
        snapshot.lastAccuracyM = fix.accuracy.isFinite && fix.accuracy >= 0 ? Int(fix.accuracy.rounded()) : nil
        // The background (without Always), GPS switched off, Low Power Mode: the history really has a hole - name it.
        if let previous, fix.timestamp.timeIntervalSince(previous) > GpsContract.gapThresholdS {
            snapshot.lastGap = TrackerGap(from: previous, to: fix.timestamp, background: backgroundSinceLastFix)
            snapshot.gapCount += 1
        }
        backgroundSinceLastFix = snapshot.inBackground
        let battery = batteryReader()
        snapshot.battery = battery
        fix.battery = battery?.pct
        if !GpsPoints.shouldRecord(previous: lastRecorded, next: fix) {
            // Too soon after the last kept fix - but it may be the car's final position before it stops. Keep the
            // newest; the next tick records it.
            if lastRecorded == nil || fix.timestamp > lastRecorded!.timestamp { pendingFix = fix }
            return
        }
        record(fix)
    }

    private func record(_ fix: GeoFix) {
        guard var box = outbox else { return }
        pendingFix = nil
        let first = lastRecorded == nil
        guard box.enqueue(fix, now: now()) else { return } // a fix the contract would refuse: skipped, not sent
        outbox = box
        lastRecorded = fix
        persist()
        syncQueue()
        // The first point goes out at once; afterwards the callbacks also drive sending (a backgrounded app's timer
        // is not something to rely on).
        let due = lastFlushStart.map { now().timeIntervalSince($0) >= intervalS } ?? true
        if first || due { Task { await flush() } }
    }

    private func recordPending() {
        if let pending = pendingFix, lastRecorded == nil || pending.timestamp > lastRecorded!.timestamp {
            record(pending)
        } else {
            pendingFix = nil
        }
    }

    /// One fresh-fix request when the phone has been quiet for 25 s (a standing car still reports every ~30 s).
    private func heartbeat() {
        let current = now()
        if let last = snapshot.lastFixAt, current.timeIntervalSince(last) < GpsContract.heartbeatAfterS { return }
        if let asked = heartbeatAt, current.timeIntervalSince(asked) < GpsContract.heartbeatAfterS { return }
        heartbeatAt = current
        location.refresh()
    }

    // MARK: Sending

    /// Sends queued batches until the queue is empty, the server ends the session, or the network fails. One at a time.
    public func flush() async {
        if let flushTask { return await flushTask.value }
        let task = Task { await flushOnce() }
        flushTask = task
        await task.value
        flushTask = nil
    }

    private func flushOnce() async {
        let generation = generation
        lastFlushStart = now()
        for _ in 0..<GpsContract.maxBatchesPerFlush {
            guard var box = outbox, generation == self.generation else { return }
            box.prune(now: now())
            outbox = box
            let batch = Array(box.points.prefix(batchLimit))
            if batch.isEmpty {
                syncQueue()
                return
            }
            let ack: PointsBatchAck
            do {
                ack = try await transport.send(sessionId: box.sessionId, PointsBatchIn(points: batch))
            } catch {
                guard generation == self.generation, var current = outbox else { return }
                if let reason = Self.sessionEnd(error) {
                    log.info("K2 session ended: \(String(describing: reason), privacy: .public)")
                    end(reason)
                    return
                }
                if Self.transient(error) {
                    snapshot.offline = true
                    syncQueue()
                    log.info("K2 offline, queued \(current.points.count)")
                    return
                }
                if (error as? APIError)?.code == "TRACKING_BATCH_TOO_LARGE", batch.count > 1 {
                    batchLimit = max(1, batch.count / 2)
                    continue
                }
                // 422 and friends: this batch will never be accepted; drop it so it cannot block the rest.
                current.drop(batch)
                outbox = current
                persist()
                syncQueue()
                log.error("K2 refused batch of \(batch.count): \((error as? APIError)?.code ?? "?", privacy: .public)")
                continue
            }
            guard generation == self.generation, var current = outbox else { return }
            current.apply(ack)
            outbox = current
            persist()
            snapshot.lastSentAt = now()
            snapshot.offline = false
            syncQueue()
            log.info("K2 ack accepted=\(ack.acceptedSeqs.count) duplicate=\(ack.duplicateSeqs.count) rejected=\(ack.rejected.count) queued=\(current.points.count) bg=\(self.snapshot.inBackground)")
            if ack.sessionStatus != .active {
                end(ack.sessionStatus == .superseded ? .superseded : .closed)
                return
            }
        }
    }

    /// Best effort: an earlier run's points go to that run's session. Returns what is still undelivered.
    private func drainLeftover(_ leftover: GpsOutbox) async -> GpsOutbox {
        var box = leftover
        box.prune(now: now())
        for _ in 0..<GpsContract.maxBatchesPerFlush where !box.points.isEmpty {
            let batch = box.nextBatch()
            do {
                let ack = try await transport.send(sessionId: box.sessionId, PointsBatchIn(points: batch))
                box.apply(ack)
                log.info("leftover ack accepted=\(ack.acceptedSeqs.count) duplicate=\(ack.duplicateSeqs.count) left=\(box.points.count)")
                if ack.sessionStatus != .active { break }
            } catch {
                if !Self.transient(error) && Self.sessionEnd(error) == nil {
                    box.drop(batch)
                    continue
                }
                break
            }
        }
        return box
    }

    /// A failure after which retrying the same request is pointless.
    nonisolated static func sessionEnd(_ error: Error) -> TrackerEndReason? {
        guard let error = error as? APIError else { return nil }
        if error.code == "TRACKING_SESSION_SUPERSEDED" { return .superseded }
        if error.code == "TRACKING_SESSION_CLOSED" || error.status == 404 { return .closed }
        if error.status == 401 { return .unauthorized }
        return nil
    }

    nonisolated static func transient(_ error: Error) -> Bool {
        guard let error = error as? APIError else { return true }
        return error.code == APIError.network || error.status >= 500 || error.status == 429 || error.status == 408 || error.status == 0
    }

    // MARK: Ending

    private func end(_ reason: TrackerEndReason) {
        teardown()
        generation += 1
        store.clear()
        let dropped = (outbox?.dropped ?? 0) + (outbox?.points.count ?? 0)
        outbox = nil
        snapshot.phase = .ended
        snapshot.endReason = reason
        snapshot.queued = 0
        snapshot.dropped = dropped
        snapshot.offline = false
    }

    private func teardown() {
        location.stop()
        ticker?.cancel()
        ticker = nil
        snapshot.backgroundUpdates = false
        heartbeatAt = nil
    }

    private func persist() {
        if let outbox { store.save(outbox) }
    }

    private func syncQueue() {
        snapshot.queued = outbox?.points.count ?? 0
        snapshot.dropped = outbox?.dropped ?? 0
    }
}

// MARK: - Install id

/// A random, non-identifying id for this install (K1 `device_id`, at most 128 characters); not a secret.
enum InstallId {
    private static let key = "elchi.installId"

    static func current(_ defaults: UserDefaults = .standard) -> String {
        if let known = defaults.string(forKey: key), !known.isEmpty { return known }
        let fresh = "ios-\(UUID().uuidString.lowercased())"
        defaults.set(fresh, forKey: key)
        return fresh
    }

    static var appVersion: String {
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0"
        let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "0"
        return "ios/\(version) (\(build))"
    }
}
