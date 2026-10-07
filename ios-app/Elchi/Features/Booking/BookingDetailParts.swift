import LinkPresentation
import SwiftUI
import UIKit

// MARK: - BOSQICH 04 ("Elchi Bron"): the booking detail's pieces

/// The detail's map hero (150 pt): both ends when the booking has map points, else a quiet sketch of a route between
/// two dots (stops carry no coordinates - BLOCKED: no route geometry, so no polyline). The "Kuzatuv" pill's dot is
/// green only while the service runs; the whole hero opens tracking ("Kuzatuvni ochish").
struct BookingMapHero: View {
    let markers: [MapMarker]
    let live: Bool
    let label: String
    let accessibility: String
    let action: () -> Void
    @Environment(\.elchi) private var c

    var body: some View {
        Button(action: action) {
            ZStack(alignment: .bottomTrailing) {
                Group {
                    if markers.count == 2 {
                        ElchiMap(markers: markers, zoom: 9, interactive: false, placeholder: label)
                    } else {
                        RouteSketch()
                    }
                }
                .allowsHitTesting(false)
                HStack(spacing: 6) {
                    Circle().fill(live ? Color(hex: 0x1E8E4E) : Color(hex: 0x9AA6B5)).frame(width: 8, height: 8)
                    Text(label).font(ElchiFont.poppins(12.5, .semibold)).foregroundStyle(c.text)
                }
                .padding(.horizontal, 12).padding(.vertical, 7)
                .background(c.card, in: Capsule())
                .shadow(color: c.shadow, radius: 7, y: 4)
                .padding(.trailing, 12).padding(.bottom, 46)
            }
            .frame(height: 150)
            .frame(maxWidth: .infinity)
            .clipShape(RoundedRectangle(cornerRadius: 24))
            .contentShape(RoundedRectangle(cornerRadius: 24))
        }
        .buttonStyle(PressFade())
        .padding(.horizontal, -4)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibility)
        .accessibilityAddTraits(.isButton)
        .accessibilityIdentifier("elchi.booking.mapHero")
    }
}

/// Two ends joined by a curve on the map's grey: a picture of "from here to there", not a road.
struct RouteSketch: View {
    @Environment(\.elchi) private var c

    var body: some View {
        Canvas { context, size in
            let w = size.width, h = size.height
            // Faint "streets" so the surface reads as a map placeholder.
            var grid = Path()
            for i in 1..<6 {
                let x = w * CGFloat(i) / 6
                grid.move(to: CGPoint(x: x, y: 0)); grid.addLine(to: CGPoint(x: x - 30, y: h))
            }
            for i in 1..<4 {
                let y = h * CGFloat(i) / 4
                grid.move(to: CGPoint(x: 0, y: y)); grid.addLine(to: CGPoint(x: w, y: y - 12))
            }
            context.stroke(grid, with: .color(c.isDark ? Color.white.opacity(0.06) : Color.white.opacity(0.9)), lineWidth: 6)
            let start = CGPoint(x: w * 0.11, y: h * 0.62), end = CGPoint(x: w * 0.89, y: h * 0.22)
            var road = Path()
            road.move(to: start)
            road.addCurve(to: end, control1: CGPoint(x: w * 0.42, y: h * 0.62), control2: CGPoint(x: w * 0.55, y: h * 0.18))
            context.stroke(road, with: .color(Color(hex: 0x0070D6)), style: StrokeStyle(lineWidth: 5, lineCap: .round))
            context.fill(Path(ellipseIn: CGRect(x: start.x - 9, y: start.y - 9, width: 18, height: 18)), with: .color(.white))
            context.stroke(Path(ellipseIn: CGRect(x: start.x - 7, y: start.y - 7, width: 14, height: 14)), with: .color(c.brand), lineWidth: 4)
            context.fill(Path(ellipseIn: CGRect(x: end.x - 9, y: end.y - 9, width: 18, height: 18)), with: .color(c.pin))
        }
        .background(c.isDark ? Color(hex: 0x1E2128) : Color(hex: 0xE9EDF1))
    }
}

/// Five dots on a dotted line under the badge (the tracking ladder's steps): reached ones azure with a tick, the
/// current one ringed; a cancelled booking all grey with a red cross on the second dot.
struct BookingStepDots: View {
    let tracker: BookingDetailRules.Tracker
    /// What VoiceOver hears (the current step, or the status when cancelled).
    let label: String
    @Environment(\.elchi) private var c

    var body: some View {
        let count = BookingDetailRules.Tracker.count
        HStack(spacing: 0) {
            ForEach(0..<count, id: \.self) { index in
                dot(index)
                if index < count - 1 {
                    DotLine().stroke(lineColor(index), style: StrokeStyle(lineWidth: 3, lineCap: .round, dash: [0.1, 6]))
                        .frame(height: 3).padding(.horizontal, 4)
                }
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(label)
        .accessibilityIdentifier("elchi.booking.tracker")
    }

    private func done(_ index: Int) -> Bool { tracker.current.map { index <= $0 } ?? false }

    private func dot(_ index: Int) -> some View {
        let cross = tracker.cancelled && index == 1
        let fill = done(index) ? c.brand : cross ? c.tone(.err).bg : c.field
        let tint = done(index) ? c.onBrand : cross ? c.tone(.err).fg : Color(hex: 0x9AA6B5)
        return (cross ? ElchiIcon.x : ElchiIcon.check).image(size: 13).foregroundStyle(tint)
            .frame(width: 26, height: 26)
            .background(fill, in: Circle())
            .overlay {
                if tracker.current == index { Circle().strokeBorder(c.isDark ? c.soft : Color(hex: 0xBFE3FF), lineWidth: 3) }
            }
    }

    private func lineColor(_ index: Int) -> Color {
        tracker.current.map { index < $0 } == true ? c.brand : c.outline
    }

    private struct DotLine: Shape {
        func path(in rect: CGRect) -> Path {
            var path = Path()
            path.move(to: CGPoint(x: 0, y: rect.midY))
            path.addLine(to: CGPoint(x: rect.maxX, y: rect.midY))
            return path
        }
    }
}

/// One coloured box under the sheet card (design `notices`).
struct BookingNoticeBox: View {
    let text: String
    let tone: Tone

    var body: some View {
        Note(text, tone: tone)
            .accessibilityIdentifier("elchi.booking.notice")
    }
}

/// The fixed bar at the bottom of the detail: the driver's initials, first name, "Haydovchi · ★ 4,7 · Cobalt 01 A
/// ••• KA", the round call button (azure only while the server shows phones - Q44/Q142; grey says when it opens) and
/// the chat button with the red count of messages not seen on this phone.
struct DriverContactBar: View {
    let name: String
    let line: String
    let phoneOpen: Bool
    let unread: Int
    let callLabel: String
    let chatLabel: String
    let onCall: () -> Void
    let onChat: () -> Void
    @Environment(\.elchi) private var c

    var body: some View {
        HStack(spacing: 12) {
            Text(BookingDetailRules.initials(name)).font(ElchiFont.poppins(16, .semibold)).foregroundStyle(c.softText)
                .frame(width: 52, height: 52)
                .background(c.soft, in: Circle())
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 1) {
                Text(name).font(ElchiFont.poppins(16, .medium)).foregroundStyle(c.text).lineLimit(1)
                Text(line).font(ElchiFont.caption).foregroundStyle(c.muted).lineLimit(1)
            }
            .accessibilityElement(children: .combine)
            Spacer(minLength: 0)
            Button(action: onCall) {
                ElchiIcon.phone.image(size: 22).foregroundStyle(phoneOpen ? c.onBrand : Color(hex: 0x8A96A6))
                    .frame(width: 52, height: 52)
                    .background(phoneOpen ? c.brand : c.field, in: Circle())
            }
            .buttonStyle(PressFade())
            .accessibilityLabel(callLabel)
            .accessibilityIdentifier("elchi.booking.call")
            Button(action: onChat) {
                ElchiIcon.chat.image(size: 22).foregroundStyle(c.text)
                    .frame(width: 52, height: 52)
                    .background(c.card, in: Circle())
                    .overlay { Circle().strokeBorder(c.line, lineWidth: 1) }
                    .overlay(alignment: .topTrailing) {
                        if unread > 0 {
                            Text(unread > 99 ? "99+" : "\(unread)").font(ElchiFont.poppins(11, .bold)).foregroundStyle(.white)
                                .padding(.horizontal, 5)
                                .frame(minWidth: 20, minHeight: 20)
                                .background(Color(hex: 0xE0413A), in: Capsule())
                                .overlay { Capsule().strokeBorder(c.card, lineWidth: 2) }
                                .offset(x: 2, y: -2)
                        }
                    }
            }
            .buttonStyle(PressFade())
            .accessibilityLabel(chatLabel)
            .accessibilityValue(unread > 0 ? "\(unread)" : "")
            .accessibilityIdentifier("elchi.booking.chat")
        }
        .padding(8)
        .background(c.card, in: Capsule())
        .shadow(color: c.shadow, radius: 12, y: 6)
    }
}

/// "Haydovchini baholang" with five small stars: a tap opens the rating screen with that many chosen.
struct RateDriverCard: View {
    let title: String
    let starLabel: (Int) -> String
    let onStar: (Int) -> Void
    @Environment(\.elchi) private var c

    var body: some View {
        HStack(spacing: 10) {
            Text(title).font(ElchiFont.poppins(14, .medium)).foregroundStyle(c.text).lineLimit(1).minimumScaleFactor(0.8)
                .layoutPriority(1)
            Spacer(minLength: 0)
            HStack(spacing: 2) {
                ForEach(1...5, id: \.self) { star in
                    Button { onStar(star) } label: {
                        Image(systemName: "star.fill").resizable().scaledToFit()
                            .foregroundStyle(c.isDark ? Color(hex: 0x3A3F48) : Color(hex: 0xD5DCE5))
                            .frame(width: 24, height: 24)
                            .frame(width: 30, height: 44)
                    }
                    .buttonStyle(PressFade())
                    .accessibilityLabel(starLabel(star))
                }
            }
        }
        .padding(EdgeInsets(top: 4, leading: 16, bottom: 4, trailing: 10))
        .background(c.card, in: RoundedRectangle(cornerRadius: 20))
        .shadow(color: c.shadow.opacity(0.7), radius: 12, y: 6)
        .accessibilityIdentifier("elchi.booking.rateCard")
    }
}

/// "Xavfsizlik haqida xabar berish": a white row with the shield in a pale circle and a chevron (design), apart from
/// "Yordam / shikoyat" (Q146).
struct SafetyEntryRow: View {
    let title: String
    let action: () -> Void
    @Environment(\.elchi) private var c

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                ElchiIcon.shield.image(size: 18).foregroundStyle(c.accentText)
                    .frame(width: 38, height: 38)
                    .background(c.isDark ? c.soft : Color(hex: 0xEEF4FA), in: Circle())
                Text(title).font(ElchiFont.poppins(14, .semibold)).foregroundStyle(c.text).multilineTextAlignment(.leading)
                Spacer(minLength: 0)
                ElchiIcon.chevR.image(size: 16).foregroundStyle(Color(hex: 0x9AA6B5))
            }
            .padding(.horizontal, 14).padding(.vertical, 12)
            .background(c.card, in: RoundedRectangle(cornerRadius: 22))
            .shadow(color: c.shadow, radius: 12, y: 6)
            .contentShape(RoundedRectangle(cornerRadius: 22))
        }
        .buttonStyle(PressFade())
        .accessibilityIdentifier("elchi.booking.safety")
    }
}

// MARK: - The tracking link in the system share sheet

/// The share sheet's item: the bare link (the design's "Posilkani kuzating" does not fit Taksi - dropped) with the
/// title "Elchi kuzatuv" in the sheet's header and as a mail subject.
final class TrackingLinkItem: NSObject, UIActivityItemSource {
    let url: URL
    let title: String

    init(url: URL, title: String) {
        self.url = url
        self.title = title
    }

    func activityViewControllerPlaceholderItem(_ activityViewController: UIActivityViewController) -> Any { url }

    func activityViewController(_ activityViewController: UIActivityViewController, itemForActivityType activityType: UIActivity.ActivityType?) -> Any? {
        url
    }

    func activityViewController(_ activityViewController: UIActivityViewController, subjectForActivityType activityType: UIActivity.ActivityType?) -> String {
        title
    }

    func activityViewControllerLinkMetadata(_ activityViewController: UIActivityViewController) -> LPLinkMetadata? {
        let metadata = LPLinkMetadata()
        metadata.title = title
        metadata.originalURL = url
        metadata.url = url
        return metadata
    }
}
