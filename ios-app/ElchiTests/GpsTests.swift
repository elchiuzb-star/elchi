import Foundation
import Testing
@testable import Elchi

/// Stage 09 GPS (Q148): fix -> contract point (mock flag, integer accuracy, speed / heading bounds), sampling, the
/// persistent outbox (cap / prune / drop counting, batches of <= 100, removal only by ACK, renumbering into a new
/// session), the publisher's state machine against a fake server and location source (session, offline -> drain,
/// superseded, refused batch, leftovers, permission) and the bar's lines for every state.
enum GpsFixture {
    static let t0 = Date(timeIntervalSince1970: 1_790_000_000)

    static func fix(_ seconds: TimeInterval, lat: Double = 41.3, lng: Double = 69.2, accuracy: Double = 8, speed: Double? = 12,
                    heading: Double? = 90, mock: Bool = false) -> GeoFix {
        GeoFix(lat: lat, lng: lng, accuracy: accuracy, speed: speed, heading: heading, timestamp: t0.addingTimeInterval(seconds), isMock: mock)
    }

    static func ack(_ accepted: [Int], duplicate: [Int] = [], rejected: [Int] = [], status: TrackingSessionStatus = .active) -> PointsBatchAck {
        PointsBatchAck(acceptedSeqs: accepted, duplicateSeqs: duplicate,
                       rejected: rejected.map { PointRejectionDTO(reason: .tooOld, seq: $0) }, sessionStatus: status)
    }

    static func outbox(points: Int, start: TimeInterval = 0, step: TimeInterval = 10) -> GpsOutbox {
        var box = GpsOutbox(tripId: "trp_1", sessionId: "trs_1")
        for index in 0..<points { box.enqueue(fix(start + Double(index) * step), now: t0.addingTimeInterval(start + Double(index) * step)) }
        return box
    }
}

struct GpsPointTests {
    @Test func mapsAFixToTheContract() throws {
        let point = try #require(GpsPoints.point(GpsFixture.fix(0, accuracy: 7.6, speed: 13.4, heading: 359.7, mock: true), seq: 4))
        #expect(point.seq == 4)
        #expect(point.accuracyM == 8)
        #expect(point.speedMps == 13)
        #expect(point.headingDeg == 0) // 360 wraps
        #expect(point.isMock == true)
        #expect(point.capturedAt.hasSuffix("Z"))
        #expect(point.batteryPct == nil)
    }

    @Test func leavesOutWhatThePhoneCouldNotMeasure() throws {
        let point = try #require(GpsPoints.point(GpsFixture.fix(0, speed: -1, heading: -1), seq: 0))
        #expect(point.speedMps == nil && point.headingDeg == nil)
        let fast = try #require(GpsPoints.point(GpsFixture.fix(0, speed: 120), seq: 0))
        #expect(fast.speedMps == nil) // over the contract's 100 m/s: left out, never clamped into a lie
        var withBattery = GpsFixture.fix(0)
        withBattery.battery = 18
        #expect(GpsPoints.point(withBattery, seq: 0)?.batteryPct == 18)
        withBattery.battery = 140
        #expect(GpsPoints.point(withBattery, seq: 0)?.batteryPct == nil)
    }

    @Test func skipsFixesTheServerWouldRefuse() {
        #expect(GpsPoints.point(GpsFixture.fix(0, lat: 91), seq: 0) == nil)
        #expect(GpsPoints.point(GpsFixture.fix(0, lng: .nan), seq: 0) == nil)
        #expect(GpsPoints.point(GpsFixture.fix(0, accuracy: -1), seq: 0) == nil) // iOS: invalid
        #expect(GpsPoints.point(GpsFixture.fix(0, accuracy: 10_001), seq: 0) == nil)
        #expect(GpsPoints.point(GpsFixture.fix(0, lat: 0, lng: 0), seq: 0) == nil) // no coordinates
    }

    @Test func samplesTenSecondsMovingThirtyStanding() {
        let first = GpsFixture.fix(0)
        #expect(GpsPoints.shouldRecord(previous: nil, next: first))
        #expect(!GpsPoints.shouldRecord(previous: first, next: GpsFixture.fix(9)))
        #expect(GpsPoints.shouldRecord(previous: first, next: GpsFixture.fix(10)))
        let standing = GpsFixture.fix(0, speed: 0)
        #expect(!GpsPoints.shouldRecord(previous: standing, next: GpsFixture.fix(20, speed: 0)))
        #expect(GpsPoints.shouldRecord(previous: standing, next: GpsFixture.fix(30, speed: 0)))
        // No speed reading but 25+ m moved: moving cadence.
        #expect(GpsPoints.shouldRecord(previous: standing, next: GpsFixture.fix(12, lat: 41.3003, speed: nil)))
        #expect(!GpsPoints.shouldRecord(previous: first, next: GpsFixture.fix(-5))) // replayed older fix
    }
}

struct GpsOutboxTests {
    @Test func seqGrowsAndRefusedFixesUseNone() {
        var box = GpsOutbox(tripId: "trp_1", sessionId: "trs_1")
        let first = box.enqueue(GpsFixture.fix(0), now: GpsFixture.t0)
        let refused = box.enqueue(GpsFixture.fix(10, lat: 95), now: GpsFixture.t0)
        let third = box.enqueue(GpsFixture.fix(20), now: GpsFixture.t0)
        #expect(first && !refused && third)
        #expect(box.points.map(\.seq) == [0, 1])
        #expect(box.nextSeq == 2)
    }

    @Test func batchesHoldAtMostAHundred() {
        let box = GpsFixture.outbox(points: 250)
        #expect(box.nextBatch().count == 100)
        #expect(box.nextBatch().first?.seq == 0)
    }

    @Test func onlyTheAckRemovesAndRejectionsCount() {
        var box = GpsFixture.outbox(points: 5)
        box.apply(GpsFixture.ack([0, 1], duplicate: [2], rejected: [3]))
        #expect(box.points.map(\.seq) == [4])
        #expect(box.dropped == 1)
        box.apply(GpsFixture.ack([]))
        #expect(box.points.count == 1)
    }

    @Test func prunesOlderThanADayAndCountsIt() {
        var box = GpsFixture.outbox(points: 3, step: 3600)
        box.prune(now: GpsFixture.t0.addingTimeInterval(24 * 3600 + 1800))
        #expect(box.points.map(\.seq) == [1, 2])
        #expect(box.dropped == 1)
    }

    @Test func capsAtTwentyThousandOldestFirst() {
        var box = GpsOutbox(tripId: "trp_1", sessionId: "trs_1")
        let now = GpsFixture.t0.addingTimeInterval(30_000)
        box.points = (0..<20_005).map { GpsPoints.point(GpsFixture.fix(Double($0)), seq: $0)! }
        box.nextSeq = 20_005
        box.prune(now: now)
        #expect(box.points.count == 20_000)
        #expect(box.points.first?.seq == 5)
        #expect(box.dropped == 5)
    }

    @Test func aRefusedBatchIsDroppedAndCounted() {
        var box = GpsFixture.outbox(points: 4)
        box.drop(Array(box.points.prefix(3)))
        #expect(box.points.map(\.seq) == [3])
        #expect(box.dropped == 3)
    }

    @Test func leftoversAreRenumberedInCaptureOrder() {
        var earlier = GpsFixture.outbox(points: 3)
        earlier.points.swapAt(0, 2) // stored out of order
        earlier.dropped = 2
        var fresh = GpsOutbox(tripId: "trp_1", sessionId: "trs_2")
        fresh.enqueue(GpsFixture.fix(100), now: GpsFixture.t0.addingTimeInterval(100))
        fresh.adopt(earlier, now: GpsFixture.t0.addingTimeInterval(100))
        #expect(fresh.points.map(\.seq) == [0, 1, 2, 3])
        #expect(Array(fresh.points.dropFirst().map(\.capturedAt)) == earlier.points.map(\.capturedAt).sorted())
        #expect(fresh.nextSeq == 4)
        #expect(fresh.dropped == 2)
    }

    @Test func fileStoreRoundTripsAndDiscardsGarbage() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("gps-\(UUID().uuidString).json")
        let store = FileOutboxStore(url: url)
        let box = GpsFixture.outbox(points: 3)
        store.save(box)
        #expect(store.load() == box)
        try Data("{nope".utf8).write(to: url)
        #expect(store.load() == nil)
        #expect(!FileManager.default.fileExists(atPath: url.path))
    }

    @Test func trackableTripIsTheEarliestRunningOne() {
        let trips = [MarketFixture.trip(id: "a", status: .planned), MarketFixture.trip(id: "b", status: .inProgress, start: MarketFixture.at(2026, 10, 2, 10)),
                     MarketFixture.trip(id: "c", status: .boarding, start: MarketFixture.at(2026, 10, 2, 9))]
        #expect(GpsPoints.trackableTrip(trips)?.id == "c")
        #expect(GpsPoints.trackableTrip([MarketFixture.trip(status: .completed)]) == nil)
    }
}

// MARK: - The publisher

@MainActor
final class FakeLocation: LocationSource {
    var authorization: LocationAuthorization
    var precise = true
    var onFix: ((GeoFix) -> Void)?
    var onAuthorizationChange: (() -> Void)?
    private(set) var started: [Bool] = []
    private(set) var stopped = 0
    private(set) var askedWhenInUse = 0
    private(set) var askedAlways = 0
    private(set) var refreshed = 0

    init(_ authorization: LocationAuthorization = .whenInUse) { self.authorization = authorization }

    func requestWhenInUse() { askedWhenInUse += 1 }
    func requestAlways() { askedAlways += 1 }
    func start(background: Bool) { started.append(background) }
    func stop() { stopped += 1 }
    func refresh() { refreshed += 1 }

    func deliver(_ fix: GeoFix) { onFix?(fix) }

    func change(to authorization: LocationAuthorization) {
        self.authorization = authorization
        onAuthorizationChange?()
    }
}

actor FakeTrackingServer: TrackingTransport {
    enum Mode { case ok, offline, refuse(APIError), superseded }

    private(set) var created: [TrackingSessionCreate] = []
    private(set) var batches: [(session: String, seqs: [Int])] = []
    private(set) var closed: [String] = []
    private var mode: Mode = .ok
    private var next = 1

    func set(_ mode: Mode) { self.mode = mode }

    func create(_ body: TrackingSessionCreate, idempotencyKey: String) async throws -> TrackingSessionDTO {
        created.append(body)
        defer { next += 1 }
        return TrackingSessionDTO(id: "trs_\(next)", recommendedIntervalS: 10, startedAt: "2026-10-01T10:00:00Z", status: .active)
    }

    func send(sessionId: String, _ body: PointsBatchIn) async throws -> PointsBatchAck {
        switch mode {
        case .offline: throw APIError(status: 0, code: APIError.network, message: "", details: nil)
        case .refuse(let error): throw error
        case .superseded: throw APIError(status: 409, code: "TRACKING_SESSION_SUPERSEDED", message: "", details: nil)
        case .ok:
            batches.append((sessionId, body.points.map(\.seq)))
            return GpsFixture.ack(body.points.map(\.seq))
        }
    }

    func close(sessionId: String, idempotencyKey: String) async throws { closed.append(sessionId) }

    var acceptedCount: Int { batches.reduce(0) { $0 + $1.seqs.count } }
}

@MainActor
final class TestClock {
    var now = GpsFixture.t0
}

@MainActor
struct DriverTrackerTests {
    let server = FakeTrackingServer()
    let location: FakeLocation
    let store = MemoryOutboxStore()
    let clock = TestClock()
    let defaults = UserDefaults(suiteName: "gps-tests-\(UUID().uuidString)")!

    init() { location = FakeLocation(.whenInUse) }

    func tracker(battery: BatteryState? = nil) -> DriverTracker {
        let clock = clock
        return DriverTracker(transport: server, store: store, location: location, deviceId: "ios-test", appVersion: "ios/2.0.0 (1)",
                             defaults: defaults, now: { clock.now }, battery: { battery }, autoTick: false)
    }

    /// One fix at `seconds` after t0, with the clock there too.
    func feed(_ tracker: DriverTracker, _ seconds: TimeInterval, speed: Double? = 12) async {
        clock.now = GpsFixture.t0.addingTimeInterval(seconds)
        location.deliver(GpsFixture.fix(seconds, speed: speed))
        await settle()
    }

    func settle() async {
        for _ in 0..<5 { await Task.yield() }
    }

    /// Lets the spawned work (a permission answer opening the session) run, up to a bound.
    func waitUntil(_ condition: () -> Bool) async {
        for _ in 0..<500 where !condition() { await Task.yield() }
    }

    @Test func opensAnIosSessionAndSendsTheFirstFixAtOnce() async {
        let tracker = tracker()
        await tracker.start("trp_1")
        let created = await server.created
        #expect(created.count == 1)
        #expect(created.first?.platform == .ios && created.first?.deviceId == "ios-test" && created.first?.tripId == "trp_1")
        #expect(tracker.snapshot.phase == .active && tracker.snapshot.sessionId == "trs_1")
        #expect(location.started == [false]) // While using: no background delivery
        #expect(location.askedAlways == 1 && tracker.snapshot.askedAlways)
        await feed(tracker, 0)
        await tracker.flush()
        #expect(await server.acceptedCount == 1)
        #expect(tracker.snapshot.queued == 0 && tracker.snapshot.lastSentAt != nil)
    }

    @Test func alwaysTurnsOnBackgroundDelivery() async {
        location.authorization = .always
        let tracker = tracker()
        await tracker.start("trp_1")
        #expect(location.started == [true])
        #expect(tracker.snapshot.backgroundUpdates)
        #expect(location.askedAlways == 0)
    }

    @Test func offlineQueuesThenDrainsAndOnlyTheAckRemoves() async {
        let tracker = tracker()
        await tracker.start("trp_1")
        await feed(tracker, 0)
        await tracker.flush()
        await server.set(.offline)
        for second in stride(from: 10.0, through: 60, by: 10) { await feed(tracker, second) }
        await tracker.tick()
        #expect(tracker.snapshot.offline)
        #expect(tracker.snapshot.queued == 6)
        #expect(store.load()?.points.count == 6) // persisted while offline
        await server.set(.ok)
        await tracker.tick()
        #expect(!tracker.snapshot.offline)
        #expect(tracker.snapshot.queued == 0)
        #expect(await server.acceptedCount == 7)
        #expect(store.load()?.points.isEmpty == true)
    }

    @Test func sampleHoldsTooFrequentFixesForTheNextTick() async {
        let tracker = tracker()
        await tracker.start("trp_1")
        await feed(tracker, 0)
        await feed(tracker, 3)
        await feed(tracker, 6)
        #expect(tracker.snapshot.queued + (await server.acceptedCount) == 1)
        clock.now = GpsFixture.t0.addingTimeInterval(10)
        await tracker.tick() // the newest held fix goes in on the tick
        #expect(await server.acceptedCount == 2)
    }

    @Test func supersededStopsAndOffersTakeOver() async {
        let tracker = tracker()
        await tracker.start("trp_1")
        await server.set(.superseded)
        await feed(tracker, 0)
        await tracker.flush()
        #expect(tracker.snapshot.phase == .ended && tracker.snapshot.endReason == .superseded)
        let bar = GpsBarContent.make(tracker.snapshot, tripId: "trp_1", now: clock.now, clock: { _ in "12:00:00" })
        #expect(bar?.title.key == "driverTracking.superseded" && bar?.action == .takeOver)
        #expect(location.stopped >= 1)
    }

    @Test func aRefusedBatchIsDroppedNotRetried() async {
        let tracker = tracker()
        await tracker.start("trp_1")
        await server.set(.refuse(APIError(status: 422, code: "VALIDATION_ERROR", message: "", details: nil)))
        await feed(tracker, 0)
        await tracker.flush()
        #expect(tracker.snapshot.queued == 0 && tracker.snapshot.dropped == 1)
        #expect(tracker.snapshot.phase == .active)
    }

    @Test func leftoversGoToTheirSessionFirstThenMoveRenumbered() async {
        var leftover = GpsFixture.outbox(points: 3)
        leftover.sessionId = "trs_old"
        store.save(leftover)
        await server.set(.offline) // the old session cannot take them now
        let tracker = tracker()
        clock.now = GpsFixture.t0.addingTimeInterval(100)
        await tracker.start("trp_1")
        #expect(tracker.snapshot.queued == 3)
        #expect(store.load()?.sessionId == "trs_1")
        #expect(store.load()?.points.map(\.seq) == [0, 1, 2])
        await server.set(.ok)
        await tracker.flush()
        let batches = await server.batches
        #expect(batches.last?.session == "trs_1")
        #expect(tracker.snapshot.queued == 0)
    }

    @Test func leftoversDeliveredToTheOldSessionDoNotMove() async {
        var leftover = GpsFixture.outbox(points: 2)
        leftover.sessionId = "trs_old"
        store.save(leftover)
        let tracker = tracker()
        await tracker.start("trp_1")
        let batches = await server.batches
        #expect(batches.first?.session == "trs_old" && batches.first?.seqs == [0, 1])
        #expect(tracker.snapshot.queued == 0)
    }

    @Test func deniedPermissionOpensNoSession() async {
        location.authorization = .denied
        let tracker = tracker()
        await tracker.start("trp_1")
        #expect(tracker.snapshot.phase == .permissionDenied)
        #expect(await server.created.isEmpty)
        let bar = GpsBarContent.make(tracker.snapshot, tripId: "trp_1", now: clock.now, clock: { _ in "" })
        #expect(bar?.title.key == "driverTracking.permissionDenied" && bar?.action == .retry && bar?.dot == .red)
    }

    @Test func asksWhileUsingFirstAndOpensOnceAllowed() async {
        location.authorization = .notDetermined
        let tracker = tracker()
        await tracker.start("trp_1")
        #expect(location.askedWhenInUse == 1 && tracker.snapshot.phase == .starting)
        location.change(to: .whenInUse)
        await waitUntil { tracker.snapshot.phase == .active }
        #expect(tracker.snapshot.phase == .active)
        #expect(await server.created.count == 1)
    }

    @Test func permissionFixedInSettingsResumes() async {
        location.authorization = .denied
        let tracker = tracker()
        await tracker.start("trp_1")
        location.change(to: .always)
        await waitUntil { tracker.snapshot.phase == .active }
        #expect(tracker.snapshot.phase == .active)
        #expect(location.started.last == true)
    }

    @Test func stopFlushesClosesAndForgets() async {
        let tracker = tracker()
        await tracker.start("trp_1")
        await feed(tracker, 0)
        await tracker.stop()
        #expect(await server.closed == ["trs_1"])
        #expect(tracker.snapshot.endReason == .stopped)
        #expect(store.load() == nil)
        #expect(GpsBarContent.make(tracker.snapshot, tripId: nil, now: clock.now, clock: { _ in "" }) == nil)
    }

    @Test func completeFlushesFirstThenEndsQuietly() async {
        let tracker = tracker()
        await tracker.start("trp_1")
        await feed(tracker, 0)
        await feed(tracker, 10)
        await tracker.flushBeforeComplete("trp_1")
        #expect(await server.acceptedCount == 2)
        tracker.tripEnded("trp_1")
        #expect(tracker.snapshot.phase == .ended && tracker.snapshot.endReason == .tripFinished)
        #expect(await server.closed.isEmpty) // the server closes it with the trip
    }

    @Test func aBackgroundGapIsNamed() async {
        let tracker = tracker()
        await tracker.start("trp_1")
        await feed(tracker, 0)
        tracker.setBackground(true)
        tracker.setBackground(false)
        await feed(tracker, 200)
        #expect(tracker.snapshot.gapCount == 1)
        #expect(tracker.snapshot.lastGap?.background == true)
    }

    @Test func heartbeatAsksForAFixAfterQuiet() async {
        let tracker = tracker()
        await tracker.start("trp_1")
        await feed(tracker, 0)
        clock.now = GpsFixture.t0.addingTimeInterval(26)
        await tracker.tick()
        #expect(location.refreshed == 1)
        await tracker.tick()
        #expect(location.refreshed == 1) // once per quiet stretch
    }
}

// MARK: - The bar

struct GpsBarTests {
    let now = GpsFixture.t0.addingTimeInterval(100)
    let clock: (Date) -> String = { _ in "11:42:08" }

    func active(_ edit: (inout TrackerSnapshot) -> Void = { _ in }) -> TrackerSnapshot {
        var state = TrackerSnapshot()
        state.phase = .active
        state.tripId = "trp_1"
        state.authorization = .whenInUse
        state.lastFixAt = GpsFixture.t0.addingTimeInterval(95)
        state.lastSentAt = GpsFixture.t0.addingTimeInterval(96)
        edit(&state)
        return state
    }

    func keys(_ state: TrackerSnapshot) -> [String] {
        GpsBarContent.make(state, tripId: "trp_1", now: now, clock: clock)?.notes.map(\.key) ?? []
    }

    @Test func idleOffersStart() throws {
        let bar = try #require(GpsBarContent.make(TrackerSnapshot(), tripId: "trp_1", now: now, clock: clock))
        #expect(bar.title.key == "driverTracking.idle" && bar.action == .start)
        #expect(bar.notes.map(\.key) == ["driverTracking.idleHint"])
        #expect(GpsBarContent.make(TrackerSnapshot(), tripId: nil, now: now, clock: clock) == nil)
    }

    @Test func sendingOnlyWithAFreshFix() throws {
        let sending = try #require(GpsBarContent.make(active(), tripId: "trp_1", now: now, clock: clock))
        #expect(sending.title.key == "driverTracking.sending" && sending.dot == .green && sending.action == .stop)
        #expect(sending.notes.first == GpsLine("driverTracking.lastSent", ["time": "11:42:08"]))
        let quiet = try #require(GpsBarContent.make(active { $0.lastFixAt = GpsFixture.t0 }, tripId: "trp_1", now: now, clock: clock))
        #expect(quiet.title.key == "driverTracking.waitingFix" && quiet.dot == .amber)
        #expect(quiet.notes.map(\.key).contains("driverTracking.stalled"))
        let none = try #require(GpsBarContent.make(active { $0.lastFixAt = nil }, tripId: "trp_1", now: now, clock: clock))
        #expect(none.title.key == "driverTracking.waitingFirstFix")
    }

    @Test func saysQueuedAccuracyBatteryAndDropped() {
        let lines = keys(active {
            $0.offline = true
            $0.queued = 12
            $0.lastAccuracyM = 140
            $0.battery = BatteryState(pct: 18, charging: false)
            $0.dropped = 3
        })
        #expect(lines.contains("driverTracking.queuedOffline"))
        #expect(lines.contains("driverTracking.lowAccuracy"))
        #expect(lines.contains("driverTracking.lowBattery"))
        #expect(lines.last == "driverTracking.dropped")
        #expect(!keys(active { $0.battery = BatteryState(pct: 18, charging: true) }).contains("driverTracking.lowBattery"))
        #expect(!keys(active { $0.queued = 4 }).contains("driverTracking.queuedOffline")) // queued but online: still going out
    }

    @Test func backgroundIsClaimedOnlyWhenItIsReal() {
        #expect(keys(active()).contains("driver.gps.backgroundPermission"))
        #expect(keys(active { $0.askedAlways = true }).contains("driver.gps.backgroundDenied"))
        let always = keys(active { $0.authorization = .always; $0.backgroundUpdates = true })
        #expect(always.contains("driver.gps.backgroundOn"))
        // Always granted but updates not (yet) running with background on: no claim.
        #expect(!keys(active { $0.authorization = .always; $0.backgroundUpdates = false }).contains("driver.gps.backgroundOn"))
        #expect(keys(active { $0.precise = false }).contains("driver.gps.preciseOff"))
    }

    @Test func endedStatesSayWhy() {
        func ended(_ reason: TrackerEndReason) -> GpsBarContent? {
            var state = TrackerSnapshot()
            state.phase = .ended
            state.endReason = reason
            return GpsBarContent.make(state, tripId: "trp_1", now: now, clock: clock)
        }
        #expect(ended(.closed)?.title.key == "driverTracking.closed")
        #expect(ended(.unauthorized)?.title.key == "driverTracking.unauthorized")
        #expect(ended(.stopped)?.title.key == "driverTracking.stopped" && ended(.stopped)?.action == .start)
        var error = TrackerSnapshot()
        error.phase = .error
        error.errorCode = "FEATURE_DISABLED"
        #expect(GpsBarContent.make(error, tripId: "trp_1", now: now, clock: clock)?.title.key == "driverTracking.error.disabled")
        error.errorCode = APIError.network
        #expect(GpsBarContent.make(error, tripId: "trp_1", now: now, clock: clock)?.title.key == "driverTracking.error.network")
    }

    @MainActor @Test func everyBarKeyHasASentence() {
        let strings = LocaleStore()
        let keys = ["driverTracking.idle", "driverTracking.idleHint", "driverTracking.starting", "driverTracking.sending",
                    "driverTracking.waitingFix", "driverTracking.waitingFirstFix", "driverTracking.lastSent", "driverTracking.lowAccuracy",
                    "driverTracking.queuedOffline", "driverTracking.stalled", "driverTracking.gapBackground", "driverTracking.gapNoFix",
                    "driverTracking.lowBattery", "driverTracking.permissionDenied", "driverTracking.dropped", "driverTracking.superseded",
                    "driverTracking.closed", "driverTracking.unauthorized", "driverTracking.stopped", "driverTracking.takeOver",
                    "driver.gps.backgroundOn", "driver.gps.backgroundPermission", "driver.gps.backgroundDenied", "driver.gps.preciseOff",
                    "driver.gps.permissionHint", "driver.gps.unavailable"]
        for key in keys { #expect(strings.line(GpsLine(key)) != key, "no sentence for \(key)") }
    }
}
