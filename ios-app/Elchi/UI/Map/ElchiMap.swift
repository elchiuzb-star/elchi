import Observation
import SwiftUI

/// Whether a real map can be drawn. The key comes from the gitignored `Config/Secrets.xcconfig` via Info.plist; the
/// SDK is the official Yandex MapKit (lite). Without a key, without the SDK, or once MapKit could not load tiles
/// (an invalid key), every map in the app is the calm placeholder and the flow goes on without it.
@MainActor @Observable
public final class MapAvailability {
    public static let shared = MapAvailability()

    /// The MapKit key, or nil when none is configured (an unfilled template counts as none).
    public nonisolated static let apiKey: String? = {
        let raw = (Bundle.main.object(forInfoDictionaryKey: "ElchiMapKitKey") as? String ?? "").trimmingCharacters(in: .whitespaces)
        return raw.isEmpty || raw.hasPrefix("your-") || raw.hasPrefix("$(") ? nil : raw
    }()

    /// Set when the last map did not finish loading within 30 s (no tiles: bad key, blocked network). The next map
    /// starts on the placeholder instead of waiting again, and still replaces it the moment it does load. Kept in
    /// memory only: a slow start must not hide the map on the next launch.
    public private(set) var failed = false

    /// Built with the SDK and given a key: a map is worth trying (it may still turn out not to load).
    public static var configured: Bool { ElchiMapEngine.compiled && apiKey != nil }

    public var isAvailable: Bool { Self.configured && !failed }

    func markFailed() { failed = true }
    func markLoaded() { failed = false }
}

/// Camera and load-probe rules that need no MapKit, so they can be tested (Android `cameraBounds`, `looksDrawn`).
public enum MapCamera {
    /// The box the camera frames for `points`: their bounds, grown around the centre to at least `minSpan` degrees
    /// each way so two places a street apart are not framed at building level. Nil for no points.
    public static func bounds(_ points: [GeoPoint], minSpan: Double = 0.01) -> (southWest: GeoPoint, northEast: GeoPoint)? {
        guard let first = points.first else { return nil }
        var (minLat, maxLat, minLng, maxLng) = (first.lat, first.lat, first.lng, first.lng)
        for p in points.dropFirst() {
            minLat = min(minLat, p.lat); maxLat = max(maxLat, p.lat)
            minLng = min(minLng, p.lng); maxLng = max(maxLng, p.lng)
        }
        let halfLat = max(maxLat - minLat, minSpan) / 2, halfLng = max(maxLng - minLng, minSpan) / 2
        let lat = (minLat + maxLat) / 2, lng = (minLng + maxLng) / 2
        return (GeoPoint(lat: lat - halfLat, lng: lng - halfLng), GeoPoint(lat: lat + halfLat, lng: lng + halfLng))
    }

    /// A fitted camera never zooms out past the whole-country view.
    public static let minFitZoom: Float = 3

    /// True when a small copy of the map shows drawn tiles rather than MapKit's empty loading grid (background, grid
    /// lines and a few markers or a route over it). Colours are compared at 4 bits per channel (any byte order) so
    /// antialiasing and scaling noise do not count.
    public static func looksDrawn(_ pixels: [UInt32]) -> Bool {
        Set(pixels.map { ($0 >> 4) & 0x0F0F_0F0F }).count >= drawnMinColours
    }

    static let drawnMinColours = 16
}

/// A marker drawn on the map: the origin ring or the destination pin (the route card's symbols), or the driver's
/// last point (brand while fresh, grey once it is old - a stale point is never drawn as live).
public struct MapMarker: Hashable, Sendable {
    public enum Kind: Hashable, Sendable { case origin, destination, vehicle, vehicleStale }
    public let point: GeoPoint
    public let kind: Kind

    public init(_ point: GeoPoint, _ kind: Kind) {
        self.point = point
        self.kind = kind
    }
}

/// The one map component. Home: both ends and the confirmed road. Point picker: a fixed centre pin over a camera
/// the person moves; `onIdle` reports the centre each time the camera stops. Until the tiles are drawn a calm
/// surface with a spinner stands in (the centre pin waits for the tiles too); after 30 s without them - and from the
/// start once a map has failed - `MapPlaceholder`, replaced the moment the map does load.
public struct ElchiMap: View {
    let markers: [MapMarker]
    let polyline: [GeoPoint]
    let focus: GeoPoint?
    let zoom: Float
    let centrePin: Bool
    /// False for the small preview maps inside a scrolling screen: no pan or zoom, the page scrolls instead.
    let interactive: Bool
    /// When set, a button with this label frames the markers and the road again after a person has panned away.
    let recentreLabel: String?
    /// The client home's "you are here": the dot and the my-location button (nil on every other map).
    let myLocation: MyLocationControl?
    let onIdle: ((GeoPoint) -> Void)?
    let placeholder: String
    /// Space a sheet covers at the bottom, so the placeholder's words sit in the part of the map that is visible.
    let placeholderInset: CGFloat
    @State private var availability = MapAvailability.shared
    @State private var loaded = false
    @State private var timedOut = false
    @State private var recentre = 0

    public init(markers: [MapMarker] = [], polyline: [GeoPoint] = [], focus: GeoPoint? = nil, zoom: Float = 12,
                centrePin: Bool = false, interactive: Bool = true, recentreLabel: String? = nil,
                myLocation: MyLocationControl? = nil, placeholder: String,
                placeholderInset: CGFloat = 0, onIdle: ((GeoPoint) -> Void)? = nil) {
        self.markers = markers
        self.polyline = polyline
        self.focus = focus
        self.zoom = zoom
        self.centrePin = centrePin
        self.interactive = interactive
        self.recentreLabel = recentreLabel
        self.myLocation = myLocation
        self.placeholder = placeholder
        self.placeholderInset = placeholderInset
        self.onIdle = onIdle
    }

    public var body: some View {
        if MapAvailability.configured {
            ZStack {
                // The bottom sheet (placeholderInset) and the floating top buttons cover the map; routes fit the rest.
                ElchiMapEngine(markers: markers, polyline: polyline, focus: focus, zoom: zoom,
                               insets: EdgeInsets(top: placeholderInset > 0 ? 120 : 0, leading: 0, bottom: placeholderInset, trailing: 0),
                               interactive: interactive, recentre: recentre,
                               userFix: myLocation.flatMap { $0.model.state.showsDot ? $0.model.state.fix : nil },
                               cameraRequest: myLocation?.model.camera,
                               onUserGesture: myLocation.map { control in { control.model.mapMovedByUser() } },
                               onIdle: onIdle,
                               onLoaded: {
                                   loaded = true
                                   timedOut = false
                                   availability.markLoaded()
                               },
                               onFailed: {
                                   timedOut = true
                                   availability.markFailed()
                               })
                if loaded {
                    if centrePin { CentrePin().allowsHitTesting(false) }
                    // Right end of the row just above the sheet (the Yandex logo holds the left end): my location at the
                    // bottom, always there; "show the route again" stacked above it once there is a route to frame.
                    VStack(alignment: .trailing, spacing: 12) {
                        if let recentreLabel, !markers.isEmpty {
                            RoundIconButton(myLocation == nil ? .locate : .route, label: recentreLabel) { recentre += 1 }
                                .accessibilityIdentifier("elchi.map.recentre")
                        }
                        if let myLocation { MyLocationButton(control: myLocation) }
                    }
                    .padding(.trailing, 16)
                    .padding(.bottom, placeholderInset + 12)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomTrailing)
                } else if timedOut || availability.failed {
                    MapPlaceholder(text: placeholder, bottomInset: placeholderInset)
                } else {
                    MapLoading(bottomInset: placeholderInset)
                }
            }
        } else {
            MapPlaceholder(text: placeholder, bottomInset: placeholderInset)
        }
    }
}

/// What the map needs for "you are here": the model and the two sentences it shows.
public struct MyLocationControl {
    let model: MyLocationModel
    let label: String
    let locatingLabel: String

    public init(model: MyLocationModel, label: String, locatingLabel: String) {
        self.model = model
        self.label = label
        self.locatingLabel = locatingLabel
    }
}

/// The round crosshair button; while a tap waits for the first fix a small pill above it says so (above, not beside:
/// beside it a Russian sentence on a 375 pt phone would reach the Yandex logo, which must stay visible).
struct MyLocationButton: View {
    let control: MyLocationControl
    @Environment(\.elchi) private var c

    var body: some View {
        VStack(alignment: .trailing, spacing: 10) {
            if control.model.state.locating {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small).tint(c.muted)
                    Text(control.locatingLabel).font(ElchiFont.poppins(12.5, .medium)).foregroundStyle(c.text).lineLimit(1)
                }
                .padding(.horizontal, 14).frame(height: 36)
                .background(c.card, in: Capsule())
                .shadow(color: c.shadow, radius: 12, y: 6)
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier("elchi.map.locating")
                .transition(.opacity)
                .onAppear { AccessibilityNotification.Announcement(control.locatingLabel).post() }
            }
            RoundIconButton(.locate, label: control.label) { control.model.tap() }
                .accessibilityIdentifier("elchi.map.myLocation")
        }
        .animation(.easeOut(duration: 0.2), value: control.model.state.locating)
    }
}

/// Until the first tiles are drawn MapKit shows a bare grid; the placeholder's surface with a quiet spinner (in the
/// part the sheet leaves free) reads better.
struct MapLoading: View {
    let bottomInset: CGFloat
    @Environment(\.elchi) private var c

    var body: some View {
        ProgressView()
            .tint(c.muted)
            .accessibilityIdentifier("elchi.map.loading")
            .padding(.bottom, bottomInset)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(MapPlaceholder.surface(c))
    }
}

/// Field-coloured surface with a pin and one line: the map is simply not shown, nothing is broken.
public struct MapPlaceholder: View {
    let text: String
    let bottomInset: CGFloat
    @Environment(\.elchi) private var c

    public init(text: String, bottomInset: CGFloat = 0) {
        self.text = text
        self.bottomInset = bottomInset
    }

    public var body: some View {
        VStack(spacing: 10) {
            ElchiIcon.pin.image(size: 26).foregroundStyle(c.muted)
                .frame(width: 56, height: 56)
                .background(c.card, in: Circle())
            Text(text).font(ElchiFont.poppins(13, .medium)).foregroundStyle(c.muted).multilineTextAlignment(.center)
        }
        .padding(24)
        .padding(.bottom, bottomInset)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Self.surface(c))
        .accessibilityElement(children: .combine)
    }

    static func surface(_ c: ElchiColors) -> Color { c.isDark ? Color(hex: 0x1C1F25) : Color(hex: 0xE9EDF1) }
}

/// The picker's pin (design: azure head, navy dot and stem, soft shadow), its tip on the map centre.
struct CentrePin: View {
    @Environment(\.elchi) private var c

    var body: some View {
        VStack(spacing: 0) {
            Circle().fill(c.brand)
                .overlay { Circle().strokeBorder(.white, lineWidth: 4) }
                .overlay { Circle().fill(c.navy).frame(width: 12, height: 12) }
                .frame(width: 40, height: 40)
            // The stem takes the pin colour, so it stays visible on the night map.
            Rectangle().fill(c.pin).frame(width: 3, height: 30)
            Ellipse().fill(c.pin.opacity(0.3)).frame(width: 18, height: 8).offset(y: -4)
        }
        .offset(y: -37) // the stem's foot sits on the centre
        .accessibilityHidden(true)
    }
}
