import Foundation

// MARK: - Contract values (app/contracts/tracking.py, mirrored like the web `gpsOutbox.ts`)

/// The numbers the server and the web publisher use (spec §10.3-§10.4, Q148). A fix becomes a contract point, waits
/// in a persistent queue under a per-session `seq`, leaves in batches of at most 100 and is removed only by the ACK.
public enum GpsContract {
    public static let maxPointsPerBatch = 100
    public static let queueMaxPoints = 20_000
    public static let queueMaxAge: TimeInterval = 24 * 3600
    public static let maxAccuracyM = 10_000.0
    public static let maxSpeedMps = 100
    /// §10.3 targets: moving ~10 s, standing 30 s (app configuration, not an OS guarantee).
    public static let movingIntervalS: TimeInterval = 10
    public static let waitingIntervalS: TimeInterval = 30
    public static let movingSpeedMps = 1.0
    public static let movingDistanceM = 25.0
    /// A long offline stretch drains over several flushes.
    public static let maxBatchesPerFlush = 20
    /// A standing phone may stop reporting: after this long without a fix the publisher asks for one.
    public static let heartbeatAfterS: TimeInterval = 25
    /// No position for longer than this is a gap worth telling the driver about.
    public static let gapThresholdS: TimeInterval = 90
    /// At or below this level (not charging) iOS Low Power Mode is likely to slow location down.
    public static let lowBatteryPct = 20
    /// "Sending" only while the last fix is at most this old (the viewer's "fresh" bucket).
    public static let freshFixS: TimeInterval = 30
    /// A visible app with no position for this long gets the "check GPS" hint.
    public static let stalledAfterS: TimeInterval = 60
    /// Accuracy worse than this is low confidence (the bar says so).
    public static let lowAccuracyM = 100
    /// Trip statuses in which the server accepts a writer session (`rules.PUBLISHABLE_TRIP_STATUSES`).
    public static let publishableTripStatuses: Set<String> = ["boarding", "in_progress", "interrupted"]
}

/// One position as the phone reported it (CoreLocation, already unwrapped).
public struct GeoFix: Equatable, Sendable {
    public var lat: Double
    public var lng: Double
    /// Horizontal accuracy in metres (negative = invalid on iOS).
    public var accuracy: Double
    /// m/s; nil or negative when unknown.
    public var speed: Double?
    /// Degrees; nil or negative when unknown.
    public var heading: Double?
    /// When the fix was taken (device clock).
    public var timestamp: Date
    /// Battery 0-100 at the time of the fix, when known.
    public var battery: Int?
    /// iOS 15+: `CLLocationSourceInformation.isSimulatedBySoftware`; false where the OS cannot tell (never a claim
    /// that the fix was checked, Q149).
    public var isMock: Bool

    public init(lat: Double, lng: Double, accuracy: Double, speed: Double? = nil, heading: Double? = nil, timestamp: Date,
                battery: Int? = nil, isMock: Bool = false) {
        self.lat = lat
        self.lng = lng
        self.accuracy = accuracy
        self.speed = speed
        self.heading = heading
        self.timestamp = timestamp
        self.battery = battery
        self.isMock = isMock
    }
}

public enum GpsPoints {
    /// `captured_at` with its offset (`…Z`), milliseconds kept.
    static func stamp(_ date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: date)
    }

    /// The contract point for one fix, or nil when the server would refuse it as `invalid` (one bad field fails the
    /// whole batch with 422, so such a fix is skipped here - never "corrected" into another place). Optional fields
    /// the phone could not measure are left out.
    public static func point(_ fix: GeoFix, seq: Int) -> TrackingPointIn? {
        guard seq >= 0, fix.lat.isFinite, fix.lng.isFinite, (-90...90).contains(fix.lat), (-180...180).contains(fix.lng),
              fix.lat != 0 || fix.lng != 0 else { return nil }
        guard fix.accuracy.isFinite, fix.accuracy >= 0, fix.accuracy <= GpsContract.maxAccuracyM else { return nil }
        guard fix.timestamp.timeIntervalSince1970 > 0 else { return nil }
        var point = TrackingPointIn(accuracyM: Int(fix.accuracy.rounded()), capturedAt: stamp(fix.timestamp), isMock: fix.isMock,
                                    lat: fix.lat, lng: fix.lng, seq: seq)
        if let speed = fix.speed, speed.isFinite, speed >= 0 {
            let rounded = Int(speed.rounded())
            if rounded <= GpsContract.maxSpeedMps { point.speedMps = rounded }
        }
        if let heading = fix.heading, heading.isFinite, heading >= 0 { point.headingDeg = Int(heading.rounded()) % 360 }
        if let battery = fix.battery, (0...100).contains(battery) { point.batteryPct = battery }
        return point
    }

    /// Great-circle distance in metres (the server's `rules.distance_m`).
    public static func distanceM(_ a: GeoFix, _ b: GeoFix) -> Double {
        let rad = Double.pi / 180
        let dphi = (b.lat - a.lat) * rad
        let dlmb = (b.lng - a.lng) * rad
        let h = pow(sin(dphi / 2), 2) + cos(a.lat * rad) * cos(b.lat * rad) * pow(sin(dlmb / 2), 2)
        return 2 * 6_371_008.8 * asin(min(1, sqrt(h)))
    }

    /// Sampling: the OS may report every second; the queue keeps one fix per ~10 s while moving (>= 1 m/s or >= 25 m
    /// since the last kept one) and per ~30 s while standing. An older fix than the last kept one is dropped.
    public static func shouldRecord(previous: GeoFix?, next: GeoFix) -> Bool {
        guard let previous else { return true }
        let elapsed = next.timestamp.timeIntervalSince(previous.timestamp)
        guard elapsed > 0 else { return false }
        let moving = (next.speed.map { $0.isFinite && $0 >= GpsContract.movingSpeedMps } ?? false)
            || distanceM(previous, next) >= GpsContract.movingDistanceM
        return elapsed >= (moving ? GpsContract.movingIntervalS : GpsContract.waitingIntervalS)
    }

    /// The driver's trip that should be publishing now: a running one, the earliest planned start first.
    public static func trackableTrip(_ trips: [TripDTO]) -> TripDTO? {
        trips.filter { GpsContract.publishableTripStatuses.contains($0.status.rawValue) }
            .sorted { (ServerTime.parse($0.plannedStartAt) ?? .distantFuture) < (ServerTime.parse($1.plannedStartAt) ?? .distantFuture) }
            .first
    }
}

// MARK: - The queue

/// The persistent outbox of one session: points wait here across network failures and restarts and leave only when
/// the server answered for them. Points the queue had to drop (too old, over the limit, refused) are counted so the
/// bar can say that history is missing (§10.4).
public struct GpsOutbox: Codable, Equatable, Sendable {
    public var tripId: String
    public var sessionId: String
    public var nextSeq: Int
    public var points: [TrackingPointIn]
    public var dropped: Int

    public init(tripId: String, sessionId: String, nextSeq: Int = 0, points: [TrackingPointIn] = [], dropped: Int = 0) {
        self.tripId = tripId
        self.sessionId = sessionId
        self.nextSeq = nextSeq
        self.points = points
        self.dropped = dropped
    }

    /// At most 24 hours and 20 000 points; the oldest go first and are counted.
    public mutating func prune(now: Date) {
        let cutoff = now.addingTimeInterval(-GpsContract.queueMaxAge)
        var kept = points.filter { (ServerTime.parse($0.capturedAt) ?? .distantPast) >= cutoff }
        if kept.count > GpsContract.queueMaxPoints { kept = Array(kept.suffix(GpsContract.queueMaxPoints)) }
        dropped += points.count - kept.count
        points = kept
    }

    /// Adds one fix under the next `seq`; a fix the contract would refuse is skipped without using a `seq`.
    @discardableResult
    public mutating func enqueue(_ fix: GeoFix, now: Date) -> Bool {
        guard let point = GpsPoints.point(fix, seq: nextSeq) else { return false }
        nextSeq += 1
        points.append(point)
        prune(now: now)
        return true
    }

    public func nextBatch() -> [TrackingPointIn] { Array(points.prefix(GpsContract.maxPointsPerBatch)) }

    /// Removes what the server answered for: accepted and duplicate points are stored; rejected ones would be
    /// rejected again on every retry, so they leave too and count as missing history.
    public mutating func apply(_ ack: PointsBatchAck) {
        let answered = Set(ack.acceptedSeqs + ack.duplicateSeqs + ack.rejected.map(\.seq))
        guard !answered.isEmpty else { return }
        points.removeAll { answered.contains($0.seq) }
        dropped += ack.rejected.count
    }

    /// A batch the server refused as a whole (422): exactly those points go, so one bad point cannot block the queue.
    public mutating func drop(_ batch: [TrackingPointIn]) {
        let seqs = Set(batch.map(\.seq))
        let before = points.count
        points.removeAll { seqs.contains($0.seq) }
        dropped += before - points.count
    }

    /// Points an earlier session could not take move into this session of the same trip, renumbered in capture order
    /// (`seq` is per session); the points themselves are unchanged (web `adoptPoints`).
    public mutating func adopt(_ earlier: GpsOutbox, now: Date) {
        let ordered = earlier.points.enumerated().sorted { a, b in
            let da = ServerTime.parse(a.element.capturedAt) ?? .distantPast, db = ServerTime.parse(b.element.capturedAt) ?? .distantPast
            return da != db ? da < db : a.offset < b.offset
        }.map(\.element)
        for var point in ordered {
            point.seq = nextSeq
            nextSeq += 1
            points.append(point)
        }
        dropped += earlier.dropped
        prune(now: now)
    }
}

// MARK: - Storage

/// Where the outbox lives between launches.
public protocol OutboxStore: Sendable {
    func load() -> GpsOutbox?
    func save(_ outbox: GpsOutbox)
    func clear()
}

/// A JSON file in Application Support (excluded from backups). A corrupt file is discarded, never half-trusted.
public struct FileOutboxStore: OutboxStore {
    let url: URL

    public init(url: URL? = nil) {
        if let url {
            self.url = url
        } else {
            let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
                ?? FileManager.default.temporaryDirectory
            self.url = base.appendingPathComponent("elchi-gps-outbox.json")
        }
    }

    public func load() -> GpsOutbox? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        guard let outbox = try? JSONDecoder().decode(GpsOutbox.self, from: data),
              outbox.points.allSatisfy({ $0.seq >= 0 }) else {
            clear()
            return nil
        }
        return outbox
    }

    public func save(_ outbox: GpsOutbox) {
        guard let data = try? JSONEncoder().encode(outbox) else { return }
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        var target = url
        do {
            try data.write(to: target, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
            var values = URLResourceValues()
            values.isExcludedFromBackup = true
            try? target.setResourceValues(values)
        } catch {
            // Disk full: the queue still lives in memory for as long as the process does.
        }
    }

    public func clear() { try? FileManager.default.removeItem(at: url) }
}

/// Tests and previews.
public final class MemoryOutboxStore: OutboxStore, @unchecked Sendable {
    private let lock = NSLock()
    private var stored: GpsOutbox?

    public init(_ outbox: GpsOutbox? = nil) { stored = outbox }

    public func load() -> GpsOutbox? { lock.withLock { stored } }
    public func save(_ outbox: GpsOutbox) { lock.withLock { stored = outbox } }
    public func clear() { lock.withLock { stored = nil } }
}
