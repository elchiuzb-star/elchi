import SwiftUI
import UIKit

// MARK: - What the bar says (pure)

/// One sentence of the bar: a dictionary key and its `{name}` fillers (already formatted).
public struct GpsLine: Equatable, Sendable {
    public let key: String
    public let values: [String: String]

    public init(_ key: String, _ values: [String: String] = [:]) {
        self.key = key
        self.values = values
    }
}

/// The driver's GPS status (design 'gps-bar', web `DriverTrackingBar.tsx`). It says exactly what is happening:
/// "sending" only while this phone gave a position in the last 30 s; waiting and lost points are counted; background
/// delivery is claimed only while it is really configured (Always granted, updates running with background on).
public struct GpsBarContent: Equatable, Sendable {
    public enum Dot: Equatable, Sendable { case gray, green, amber, red }
    public enum Action: Equatable, Sendable { case start, stop, retry, takeOver }

    public let dot: Dot
    public let title: GpsLine
    public let notes: [GpsLine]
    public let action: Action?

    var primaryAction: Bool { action != nil && action != .stop }

    static let errorKeys = [
        "FEATURE_DISABLED": "driverTracking.error.disabled",
        "INVALID_STATE_TRANSITION": "driverTracking.error.notRunning",
        APIError.network: "driverTracking.error.network",
    ]

    /// nil = nothing to say (no running trip and no publisher that ended with a reason worth reading).
    public static func make(_ state: TrackerSnapshot, tripId: String?, now: Date, clock: (Date) -> String) -> GpsBarContent? {
        let quietEnd = state.phase == .ended && (state.endReason == .stopped || state.endReason == .tripFinished)
        if tripId == nil && (state.phase == .idle || quietEnd) { return nil }
        var dot = Dot.gray
        var title: GpsLine
        var notes: [GpsLine] = []
        var action: Action?
        switch state.phase {
        case .idle:
            title = GpsLine("driverTracking.idle")
            notes.append(GpsLine("driverTracking.idleHint"))
            if state.authorization == .denied || state.authorization == .restricted { notes.append(GpsLine("driver.gps.permissionHint")) }
            action = .start
        case .starting:
            title = GpsLine("driverTracking.starting")
        case .active:
            let age = state.lastFixAt.map { now.timeIntervalSince($0) }
            let sending = age.map { $0 <= GpsContract.freshFixS } ?? false
            dot = sending ? .green : .amber
            if sending {
                title = GpsLine("driverTracking.sending")
            } else if let last = state.lastFixAt {
                title = GpsLine("driverTracking.waitingFix", ["time": clock(last)])
            } else {
                title = GpsLine("driverTracking.waitingFirstFix")
            }
            if let sent = state.lastSentAt { notes.append(GpsLine("driverTracking.lastSent", ["time": clock(sent)])) }
            if let accuracy = state.lastAccuracyM, accuracy > GpsContract.lowAccuracyM {
                notes.append(GpsLine("driverTracking.lowAccuracy", ["meters": "\(accuracy)"]))
            }
            if state.queued > 0 && state.offline { notes.append(GpsLine("driverTracking.queuedOffline", ["count": "\(state.queued)"])) }
            if !state.inBackground, let age, age > GpsContract.stalledAfterS { notes.append(GpsLine("driverTracking.stalled")) }
            if let gap = state.lastGap {
                notes.append(GpsLine(gap.background ? "driverTracking.gapBackground" : "driverTracking.gapNoFix",
                                     ["from": clock(gap.from), "to": clock(gap.to)]))
            }
            if let battery = state.battery, !battery.charging, battery.pct <= GpsContract.lowBatteryPct {
                notes.append(GpsLine("driverTracking.lowBattery", ["pct": "\(battery.pct)"]))
            }
            notes.append(contentsOf: backgroundLines(state))
            action = .stop
        case .permissionDenied:
            dot = .red
            title = GpsLine("driverTracking.permissionDenied")
            notes.append(GpsLine("driver.gps.permissionHint"))
            action = .retry
        case .unavailable:
            dot = .red
            title = GpsLine("driver.gps.unavailable")
        case .error:
            dot = .red
            title = GpsLine(errorKeys[state.errorCode ?? ""] ?? "driverTracking.error.generic")
            action = .retry
        case .ended:
            let key: String = switch state.endReason {
            case .superseded: "driverTracking.superseded"
            case .unauthorized: "driverTracking.unauthorized"
            case .closed: "driverTracking.closed"
            default: "driverTracking.stopped"
            }
            title = GpsLine(key)
            if tripId != nil { action = state.endReason == .superseded ? .takeOver : .start }
        }
        if state.dropped > 0 { notes.append(GpsLine("driverTracking.dropped", ["count": "\(state.dropped)"])) }
        return GpsBarContent(dot: dot, title: title, notes: notes, action: action)
    }

    /// The native lines about the background and precision (never "GPS faol" without it being true).
    static func backgroundLines(_ state: TrackerSnapshot) -> [GpsLine] {
        var lines: [GpsLine] = []
        if state.backgroundUpdates && state.authorization == .always {
            lines.append(GpsLine("driver.gps.backgroundOn"))
        } else if state.authorization == .whenInUse {
            lines.append(GpsLine(state.askedAlways ? "driver.gps.backgroundDenied" : "driver.gps.backgroundPermission"))
        }
        if !state.precise { lines.append(GpsLine("driver.gps.preciseOff")) }
        return lines
    }
}

extension LocaleStore {
    /// A bar line in the active language, with its `{name}` fillers.
    func line(_ line: GpsLine) -> String {
        let values = line.values.sorted { $0.key < $1.key }.map { ($0.key, $0.value as Any) }
        return tOrNil(line.key, values: values) ?? t(line.key)
    }
}

// MARK: - The bar

/// The GPS bar under a screen's top bar: dot, title, notes and one action. Shown on the trips list (active trip),
/// trip detail and the booking detail / chat of an active trip.
struct GpsBarView: View {
    let tracker: DriverTracker
    /// The running trip this screen is about (nil = only an ended publisher's reason).
    let tripId: String?
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(\.openURL) private var openURL
    @State private var now = Date()

    var body: some View {
        if let content = GpsBarContent.make(tracker.snapshot, tripId: tripId, now: now, clock: strings.clockSeconds) {
            HStack(alignment: .top, spacing: 12) {
                Circle().fill(color(content.dot)).frame(width: 10, height: 10).padding(.top, 5)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 3) {
                    Text(strings.line(content.title)).font(ElchiFont.poppins(13, .semibold)).foregroundStyle(c.text)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("elchi.gps.title")
                    ForEach(Array(content.notes.enumerated()), id: \.offset) { _, note in
                        Text(strings.line(note)).font(ElchiFont.poppins(11)).foregroundStyle(c.muted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: 0)
                if let action = content.action {
                    Button { run(action) } label: {
                        Text(strings.t(label(action))).font(ElchiFont.poppins(12, .semibold)).lineLimit(1)
                            .foregroundStyle(content.primaryAction ? c.onBrand : c.text)
                            .padding(.horizontal, 12).frame(minHeight: 34)
                            .background(content.primaryAction ? c.brand : c.card, in: RoundedRectangle(cornerRadius: 10))
                            .overlay { if !content.primaryAction { RoundedRectangle(cornerRadius: 10).strokeBorder(c.line) } }
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("elchi.gps.action")
                }
            }
            .padding(.horizontal, 16).padding(.vertical, 10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(c.card)
            .overlay(alignment: .bottom) { Rectangle().fill(c.line).frame(height: 1) }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("elchi.gps.bar")
            .task(id: tracker.snapshot.phase == .active) {
                // "Sending" turns into "waiting" when the phone goes quiet: re-read the clock every few seconds.
                while !Task.isCancelled {
                    now = Date()
                    try? await Task.sleep(for: .seconds(5))
                }
            }
        }
    }

    private func label(_ action: GpsBarContent.Action) -> String {
        switch action {
        case .start: "driverTracking.start"
        case .stop: "driverTracking.stop"
        case .retry: "driverTracking.retry"
        case .takeOver: "driverTracking.takeOver"
        }
    }

    private func run(_ action: GpsBarContent.Action) {
        switch action {
        case .stop:
            Task { await tracker.stop() }
        case .retry where tracker.snapshot.authorization == .denied || tracker.snapshot.authorization == .restricted:
            // iOS asks only once: after a denial the switch is in Settings.
            if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
        default:
            if let trip = tripId ?? tracker.snapshot.tripId { Task { await tracker.start(trip) } }
        }
    }

    private func color(_ dot: GpsBarContent.Dot) -> Color {
        switch dot {
        case .gray: Color(hex: 0x9AA6B5)
        case .green: Color(hex: 0x1E8E4E)
        case .amber: Color(hex: 0xE0A100)
        case .red: Color(hex: 0xD64545)
        }
    }
}

extension LocaleStore {
    /// `11:42:08` (Tashkent wall clock) - the bar's "oxirgi yuborilgan" time.
    nonisolated func clockSeconds(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = DepartureWindow.timeZone
        formatter.dateFormat = "HH:mm:ss"
        return formatter.string(from: date)
    }
}
