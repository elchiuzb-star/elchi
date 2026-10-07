import SwiftUI

// MARK: - Kuzatuv

/// "Kuzatuv": the status ladder from `service_status` (times only where the booking has them), then live location:
/// the state in words (fresh / delayed / lost / none - re-aged on this phone, never better than the server said),
/// the map (placeholder without a key, then the coordinates), the last point's time, accuracy and source. When the
/// window is closed, the reason as a grey note. No ETA: the pilot has none.
struct BookingTrackingView<Host: BookingScreenHost>: View {
    let booking: Host
    let onBack: () -> Void
    /// The driver's own title ("Kuzatuv (siz yuborayotgan)", DESIGN08 11.1); nil = the client's "Kuzatuv".
    var title: String?
    /// The driver's note above the live section (what the client sees and when this phone sends, DESIGN08 11.2).
    var note: String?
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c
    @Environment(\.scenePhase) private var scenePhase
    @Environment(BannerCenter.self) private var banners: BannerCenter?
    @State private var now = Date()

    private var model: BookingTrackingModel { booking.tracking }

    var body: some View {
        ScreenScaffold(title: title ?? strings.t("bookingTracking.title"), backLabel: strings.t("common.back"), onBack: onBack,
                       actions: [BarAction(id: "refresh", icon: .refresh, label: strings.t("support.refresh")) {
                           Task {
                               await refresh()
                               banners?.show(.key("client.booking.refreshed"), tone: .info, hideAfter: .seconds(2))
                           }
                       }]) {
            if let note { Note(note, tone: .blue).accessibilityIdentifier("elchi.tracking.driverNote") }
            if let dto = booking.bookingBase { ladder(dto) }
            SectionTitle(strings.t("bookingTracking.liveTitle"))
            live
        } footer: {
            EmptyView()
        }
        .refreshable { await refresh() }
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

    private func refresh() async {
        await booking.load()
        await model.poll()
    }

    @ViewBuilder
    private func ladder(_ dto: ClientBookingDTO) -> some View {
        SectionTitle(strings.t("bookingTracking.progressTitle"))
        let created = ServerTime.parse(dto.createdAt)
        let steps = StatusLadder.cancelledSteps(status: dto.serviceStatus, createdAt: created, cancelledAt: ServerTime.parse(dto.cancelled?.at))
            ?? StatusLadder.steps(status: dto.serviceStatus, createdAt: created, service: dto.serviceType)
        if steps.isEmpty {
            // Off the ladder (returned, delivery failed, …): the status itself.
            let status = strings.status(.clientBooking(dto.serviceType, dto.serviceStatus))
            ItemCard(title: strings.t("client.tracking.offLadder", ("status", status.text)), badge: status)
        } else {
            StepLadder(steps.map { step in
                let state: StepLadder.Step.State = switch step.state {
                case .done: .done
                case .current: .current
                case .ahead: .ahead
                case .failed: .failed
                }
                return StepLadder.Step(strings.t(step.key), detail: step.at.map(DepartureWindow.shortText), state: state)
            }, doneLabel: strings.t("client.tracking.stepDone"), currentLabel: strings.t("client.tracking.stepCurrent"))
        }
    }

    @ViewBuilder
    private var live: some View {
        if let reason = model.closedReason {
            closedCard(reason)
        } else if let tracking = model.tracking {
            let freshness = model.freshness(now: now)
            let point = tracking.lastPoint
            let stale = freshness != .fresh
            ElchiMap(markers: point.map { [MapMarker(GeoPoint(lat: $0.lat, lng: $0.lng), stale ? .vehicleStale : .vehicle)] } ?? [],
                     focus: point.map { GeoPoint(lat: $0.lat, lng: $0.lng) }, zoom: 13, interactive: false, placeholder: strings.t("client.map.unavailable"))
                .frame(height: 230)
                .clipShape(RoundedRectangle(cornerRadius: 20))
                .overlay(alignment: .topLeading) { liveBadge(freshness).padding(12) }
            if let point {
                Text(pointLine(point, freshness: freshness)).font(ElchiFont.caption).foregroundStyle(c.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            note(freshness, point)
            if let point, !MapAvailability.shared.isAvailable {
                CardRowCoordinates(text: GeoPoint(lat: point.lat, lng: point.lng).text, label: strings.t("client.tracking.coordinates"))
            }
        } else if let error = model.error {
            Note(strings.errorText(error), tone: .err)
            ElchiButton(strings.t("common.retry"), variant: .ghost, size: .medium, icon: .refresh) { Task { await model.poll() } }
        } else {
            SkeletonCards(count: 1)
        }
    }

    /// The design's closed-window card: a grey pin, a title (not started / closed / cancelled) and the server's reason
    /// in words. The window is the server's (Taksi opens 30 minutes before pickup) - never guessed from the status.
    private func closedCard(_ reason: String) -> some View {
        let status = booking.bookingBase?.serviceStatus
        let cancelled = status == "cancelled" || status == "no_show"
        return VStack(spacing: 10) {
            ElchiIcon.pin.image(size: 26).foregroundStyle(c.muted)
                .frame(width: 56, height: 56)
                .background(c.isDark ? c.field : Color(hex: 0xE4E9EF), in: Circle())
            Text(strings.t(TrackingCard.closedTitleKey(reason: reason, bookingStatus: status))).font(ElchiFont.poppins(15, .semibold))
                .foregroundStyle(c.text).multilineTextAlignment(.center)
            Text(cancelled ? "\(strings.t("client.tracking.liveClosed"))." : strings.trackingClosedText(reason))
                .font(ElchiFont.poppins(13)).foregroundStyle(c.muted).multilineTextAlignment(.center).lineSpacing(3)
                .frame(maxWidth: 280).fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 16).padding(.vertical, 26)
        .frame(maxWidth: .infinity)
        .background(c.card, in: RoundedRectangle(cornerRadius: ElchiShape.card))
        .shadow(color: c.shadow, radius: 12, y: 6)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("elchi.tracking.closed")
    }

    /// The map's corner pill in the design's short words: "Jonli" only while the point is fresh, then "Kechikmoqda",
    /// "Aloqa uzilgan", "Joylashuv yo'q".
    private func liveBadge(_ freshness: TrackingFreshness) -> some View {
        let (color, key): (Color, String) = switch freshness {
        case .fresh: (Color(hex: 0x1E8E4E), "publicTracking.fresh")
        case .delayed: (Color(hex: 0xE0A100), "publicTracking.delayed")
        case .lost: (Color(hex: 0xD64545), "publicTracking.lost")
        default: (Color(hex: 0x9AA6B5), "publicTracking.noData")
        }
        return HStack(spacing: 6) {
            Circle().fill(color).frame(width: 8, height: 8)
            Text(strings.t(key)).font(ElchiFont.poppins(12, .semibold)).foregroundStyle(Color(hex: 0x0E1B33))
        }
        .padding(.horizontal, 12).padding(.vertical, 6)
        .background(.white, in: Capsule())
        .shadow(color: .black.opacity(0.15), radius: 4, y: 2)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("elchi.tracking.pill")
    }

    /// Under the map: delayed with the point's real age (warn), lost (err), no point yet (grey). Fresh says nothing more.
    @ViewBuilder
    private func note(_ freshness: TrackingFreshness, _ point: TrackingLastPointDTO?) -> some View {
        switch TrackingCard.note(freshness, capturedAt: point.flatMap { ServerTime.parse($0.capturedAt) }, now: now) {
        case .none:
            EmptyView()
        case .delayed(let minutes):
            Note(strings.t("client.tracking.delayedNote", ("time", strings.t("app.duration.minutes", ("minutes", minutes)))), tone: .warn)
        case .lost:
            Note(strings.t("client.tracking.lostNote"), tone: .err)
        case .noData:
            Note(strings.t("liveTracking.noPoint"), tone: .gray)
        }
    }

    /// `Oxirgi nuqta: 11:42 · ±12 m · Manba: haydovchining telefoni. So'nggi 30 soniya ichida yangilangan.` - while
    /// fresh, then the channel (socket or 15 s polling).
    private func pointLine(_ point: TrackingLastPointDTO, freshness: TrackingFreshness) -> String {
        let time = ServerTime.parse(point.capturedAt).map(strings.clock) ?? "?"
        var line = strings.t("client.tracking.lastPointLine", ("time", time), ("accuracy", point.accuracyM))
        if point.lowAccuracy { line += " (\(strings.t("bookingTracking.lowAccuracy")))" }
        let tail = freshness == .fresh ? strings.t("client.tracking.freshLine")
            : model.socketLive ? strings.t("client.tracking.liveChannel") : strings.t("liveTracking.polling")
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
