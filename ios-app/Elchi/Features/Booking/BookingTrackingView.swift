import SwiftUI

// MARK: - Kuzatuv

/// "Kuzatuv": the status ladder from `service_status` (times only where the booking has them), then live location:
/// the state in words (fresh / delayed / lost / none - re-aged on this phone, never better than the server said),
/// the map (placeholder without a key, then the coordinates), the last point's time, accuracy and source. When the
/// window is closed, the reason as a grey note. No ETA: the pilot has none.
struct BookingTrackingView: View {
    let booking: BookingModel
    let onBack: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(\.scenePhase) private var scenePhase
    @State private var now = Date()

    private var model: BookingTrackingModel { booking.tracking }

    var body: some View {
        ScreenScaffold(title: strings.t("bookingTracking.title"), backLabel: strings.t("common.back"), onBack: onBack) {
            if let dto = booking.booking.value { ladder(dto) }
            SectionTitle(strings.t("bookingTracking.liveTitle"))
            live
        } footer: {
            EmptyView()
        }
        .refreshable {
            await booking.load()
            await model.poll()
        }
        .task(id: scenePhase == .active) {
            // Socket + polling only while this screen is open and the app is in front.
            guard scenePhase == .active else { return }
            await model.run()
        }
        .task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                now = Date()
            }
        }
    }

    @ViewBuilder
    private func ladder(_ dto: ClientBookingDTO) -> some View {
        SectionTitle(strings.t("bookingTracking.progressTitle"), description: strings.t("bookingTracking.progressHint"))
        let steps = StatusLadder.steps(status: dto.serviceStatus, createdAt: ServerTime.parse(dto.createdAt))
        if steps.isEmpty {
            // Off the ladder (cancelled, returned, …): the status itself, and when it was cancelled.
            let status = strings.status(.booking(dto.serviceType, dto.serviceStatus))
            ItemCard(title: strings.t("client.tracking.offLadder", ("status", status.text)), badge: status,
                     lines: dto.cancelled.map { [ItemLine(strings.cancelledLine($0))] } ?? [])
        } else {
            StepLadder(steps.map { step in
                let state: StepLadder.Step.State = switch step.state {
                case .done: .done
                case .current: .current
                case .ahead: .ahead
                }
                return StepLadder.Step(strings.t(step.key), detail: step.at.map(DepartureWindow.shortText), state: state)
            }, doneLabel: strings.t("client.tracking.stepDone"), currentLabel: strings.t("client.tracking.stepCurrent"))
        }
    }

    @ViewBuilder
    private var live: some View {
        if let reason = model.closedReason {
            Note(strings.trackingClosedText(reason), tone: .gray)
        } else if let tracking = model.tracking {
            let freshness = model.freshness(now: now)
            let point = tracking.lastPoint
            let stale = freshness != .fresh
            ElchiMap(markers: point.map { [MapMarker(GeoPoint(lat: $0.lat, lng: $0.lng), stale ? .vehicleStale : .vehicle)] } ?? [],
                     focus: point.map { GeoPoint(lat: $0.lat, lng: $0.lng) }, zoom: 13, interactive: false, placeholder: strings.t("client.map.unavailable"))
                .frame(height: 220)
                .clipShape(RoundedRectangle(cornerRadius: 20))
                .overlay(alignment: .topLeading) { liveBadge(freshness).padding(12) }
            state(freshness, point)
            if let point {
                Text(pointLine(point, freshness: freshness)).font(ElchiFont.caption).foregroundStyle(c.muted)
                    .fixedSize(horizontal: false, vertical: true)
                if !MapAvailability.shared.isAvailable {
                    CardRowCoordinates(text: GeoPoint(lat: point.lat, lng: point.lng).text, label: strings.t("client.tracking.coordinates"))
                }
            }
        } else if let error = model.error {
            Note(strings.errorText(error), tone: .err)
            ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.poll() } }
        } else {
            SkeletonCards(count: 1)
        }
    }

    /// The map's corner pill: "Jonli" only while the point is fresh; otherwise the state in words.
    private func liveBadge(_ freshness: TrackingFreshness) -> some View {
        let color: Color = switch freshness {
        case .fresh: Color(hex: 0x1E8E4E)
        case .delayed: Color(hex: 0xE0A100)
        case .lost: Color(hex: 0xD64545)
        default: Color(hex: 0x9AA6B5)
        }
        return HStack(spacing: 6) {
            Circle().fill(color).frame(width: 8, height: 8)
            Text(strings.t("trackingFreshness.\(freshness.rawValue)")).font(ElchiFont.poppins(12, .semibold)).foregroundStyle(Color(hex: 0x0E1B33))
        }
        .padding(.horizontal, 12).padding(.vertical, 6)
        .background(.white, in: Capsule())
        .shadow(color: .black.opacity(0.15), radius: 4, y: 2)
        .accessibilityElement(children: .combine)
    }

    private func state(_ freshness: TrackingFreshness, _ point: TrackingLastPointDTO?) -> some View {
        let level: LiveStateRow.Level = switch freshness {
        case .fresh: .live
        case .delayed: .delayed
        case .lost: .lost
        default: .none
        }
        let line: String = switch freshness {
        case .fresh: strings.t("client.tracking.freshLine")
        case .delayed: strings.t("liveTracking.delayedHint")
        case .lost: strings.t("liveTracking.lostHint")
        default: strings.t("liveTracking.noPoint")
        }
        return LiveStateRow(level, title: strings.t("liveTracking.freshness.\(freshness.rawValue)"), lines: [line])
    }

    /// `Oxirgi nuqta: 11:42 · ±12 m · Manba: haydovchining telefoni. Har 15 soniyada yangilanadi.`
    private func pointLine(_ point: TrackingLastPointDTO, freshness: TrackingFreshness) -> String {
        let time = ServerTime.parse(point.capturedAt).map(strings.clock) ?? "?"
        var line = strings.t("client.tracking.lastPointLine", ("time", time), ("accuracy", point.accuracyM))
        if point.lowAccuracy { line += " (\(strings.t("bookingTracking.lowAccuracy")))" }
        let tail = model.socketLive ? strings.t("client.tracking.liveChannel") : strings.t("liveTracking.polling")
        return "\(line). \(tail)"
    }
}

/// The last point's coordinates when no map can be drawn.
private struct CardRowCoordinates: View {
    let text: String
    let label: String

    var body: some View {
        ElchiCard {
            CardRow(label, text, first: true)
        }
    }
}
