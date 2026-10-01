import SwiftUI

#if canImport(YandexMapsMobile)
import YandexMapsMobile

/// Starts MapKit once, with the configured key (never a geocoder key: those stay on the server).
@MainActor
enum YandexMapKit {
    private static var started = false

    static func startIfNeeded() {
        guard !started, let key = MapAvailability.apiKey else { return }
        started = true
        YMKMapKit.setApiKey(key)
        // Map labels follow the app language. MapKit takes the locale once per process, so a language switch in the
        // app reaches the map on the next launch.
        let appLocale = UserDefaults.standard.string(forKey: "elchi.locale") == "ru" ? "ru_RU" : "uz_UZ"
        YMKMapKit.setLocale(appLocale)
        YMKMapKit.sharedInstance().onStart()
    }
}

/// Yandex MapKit (lite) behind `ElchiMap`: camera, the markers, the route polyline, camera-idle callback.
/// `onLoaded` fires once the map has drawn its tiles: MapKit's own "loaded" (which waits for the labels too and can
/// take half a minute on a cold start) or, sooner, a tiny copy of the view that shows more than the empty grid.
/// If neither arrives within 30 s (typically an invalid key or no network), `onFailed` swaps in the placeholder;
/// the probe keeps going, slower, so a map that loads late still replaces it.
struct ElchiMapEngine: UIViewRepresentable {
    static let compiled = true

    let markers: [MapMarker]
    let polyline: [GeoPoint]
    let focus: GeoPoint?
    let zoom: Float
    /// Screen space (points) covered by overlays: the camera fits routes into the rest (MapKit focusRect).
    let insets: EdgeInsets
    let interactive: Bool
    /// Bumped by the recentre button: the last camera (the fit) is applied again.
    let recentre: Int
    let onIdle: ((GeoPoint) -> Void)?
    let onLoaded: () -> Void
    let onFailed: () -> Void
    @Environment(\.elchi) private var c

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> YMKMapView {
        YandexMapKit.startIfNeeded()
        // The Apple-silicon simulator renders MapKit through Vulkan (as Yandex's own demo does).
        #if targetEnvironment(simulator) && arch(arm64)
        let view = YMKMapView(frame: .zero, vulkanPreferred: true, transparencySupport: false)!
        #else
        let view = YMKMapView(frame: .zero)!
        #endif
        let map = view.mapWindow.map
        map.isRotateGesturesEnabled = false
        map.isTiltGesturesEnabled = false
        // Before any place is chosen the map opens over Uzbekistan, not the whole world.
        map.move(with: YMKCameraPosition(target: YMKPoint(latitude: 41.3, longitude: 64.6), zoom: 5.2, azimuth: 0, tilt: 0))
        map.addCameraListener(with: context.coordinator)
        map.setMapLoadedListenerWith(context.coordinator)
        view.mapWindow.addSizeChangedListener(with: context.coordinator)
        context.coordinator.onLoaded = onLoaded
        context.coordinator.onFailed = onFailed
        context.coordinator.recentre = recentre
        context.coordinator.watchLoad(view)
        return view
    }

    func updateUIView(_ view: YMKMapView, context: Context) {
        let coordinator = context.coordinator
        coordinator.onIdle = onIdle
        coordinator.onLoaded = onLoaded
        coordinator.onFailed = onFailed
        coordinator.viewWidth = view.bounds.width
        let map = view.mapWindow.map
        map.isScrollGesturesEnabled = interactive
        map.isZoomGesturesEnabled = interactive
        if coordinator.insets != insets {
            // The sheet's height arrives after the first layout: re-fit the current content into the new visible area.
            coordinator.insets = insets
            coordinator.refit(view.mapWindow)
        }
        if coordinator.recentre != recentre {
            coordinator.recentre = recentre
            coordinator.refit(view.mapWindow, animated: true)
        }
        map.isNightModeEnabled = c.isDark
        let content = Coordinator.Content(markers: markers, polyline: polyline, focus: focus, dark: c.isDark)
        guard content != coordinator.content else { return }
        coordinator.content = content
        // Android's palette: the destination takes the route card's pin colour (navy, the text colour when dark);
        // fills and the route's outline take the card surface, so nothing glows white on the night map.
        coordinator.draw(on: view.mapWindow, zoom: zoom,
                         colours: .init(brand: UIColor(c.brand), pin: UIColor(c.pin), surface: UIColor(c.card)))
    }

    /// MapKit calls its listeners on the main thread; the conformances are marked `@preconcurrency` because the
    /// Objective-C protocols carry no isolation of their own.
    @MainActor
    final class Coordinator: NSObject, @preconcurrency YMKMapCameraListener, @preconcurrency YMKMapLoadedListener,
        @preconcurrency YMKMapSizeChangedListener {
        struct Content: Equatable {
            let markers: [MapMarker]
            let polyline: [GeoPoint]
            let focus: GeoPoint?
            /// The marker colours follow the theme, so a theme switch redraws them.
            let dark: Bool
        }

        struct Colours {
            let brand, pin, surface: UIColor
        }

        var content: Content?
        var onIdle: ((GeoPoint) -> Void)?
        var onLoaded: (() -> Void)?
        var onFailed: (() -> Void)?
        var insets = EdgeInsets()
        var recentre = 0
        /// The view's width in points; MapKit measures in physical pixels, so pixels ÷ points gives the scale.
        var viewWidth: CGFloat = 0
        private var lastCamera: ((YMKMap, Bool) -> Void)?
        private var loaded = false
        private var objects: [YMKMapObject] = []
        /// A camera move requested while the map view still had no size. MapKit asserts (and aborts the app) when
        /// asked to fit a geometry into a zero-sized window, so the move waits for the first real layout.
        private var pendingCamera: ((YMKMap) -> Void)?

        func onMapWindowSizeChanged(with mapWindow: YMKMapWindow, newWidth: Int, newHeight: Int) {
            guard newWidth > 0, newHeight > 0 else { return }
            applyFocusRect(mapWindow)
            guard let pending = pendingCamera else { return }
            pendingCamera = nil
            pending(mapWindow.map)
        }

        /// The visible part of the map, in physical pixels: everything minus the overlays' insets.
        func refit(_ window: YMKMapWindow, animated: Bool = false) {
            guard window.width() > 0, window.height() > 0 else { return }
            applyFocusRect(window)
            lastCamera?(window.map, animated)
        }

        private func applyFocusRect(_ window: YMKMapWindow) {
            let (w, h) = (CGFloat(window.width()), CGFloat(window.height()))
            let scale = viewWidth > 0 ? w / viewWidth : 3
            let top = insets.top * scale, bottom = insets.bottom * scale
            // Yandex's terms require the logo to stay visible: bottom-left, just above the sheet. Padding is in pixels.
            window.map.logo.setAlignmentWith(YMKLogoAlignment(horizontalAlignment: .left, verticalAlignment: .bottom))
            window.map.logo.setPaddingWith(YMKLogoPadding(horizontalPadding: UInt(12 * scale),
                                                          verticalPadding: UInt(max(0, bottom) + 12 * scale)))
            guard w > 0, h - top - bottom > 40 * scale else { window.focusRect = nil; return }
            window.focusRect = YMKScreenRect(topLeft: YMKScreenPoint(x: 0, y: Float(top)),
                                             bottomRight: YMKScreenPoint(x: Float(w), y: Float(h - bottom)))
        }

        /// Until the map is drawn: a tiny copy of the view every second (every 3 s once 30 s have passed without
        /// tiles, when the placeholder takes over). An empty grid has a handful of colours, drawn tiles dozens
        /// (measured on the simulator, cold cache: grid 5-11, drawn 18-64; MapKit's own "loaded" came ~2 s later).
        func watchLoad(_ view: YMKMapView) {
            Task { @MainActor [weak self, weak view] in
                let start = ContinuousClock.now
                var late = false
                while let self, !self.loaded {
                    if !late && ContinuousClock.now - start >= .seconds(30) {
                        late = true
                        self.onFailed?()
                    }
                    try? await Task.sleep(for: .seconds(late ? 3 : 1))
                    guard let view, !self.loaded else { return }
                    if let pixels = Self.probe(view), MapCamera.looksDrawn(pixels) { self.markLoaded() }
                }
            }
        }

        private func markLoaded() {
            guard !loaded else { return }
            loaded = true
            onLoaded?()
        }

        /// The view drawn into a 24 x 48 bitmap, or nil while it is off screen or has no size.
        private static func probe(_ view: UIView) -> [UInt32]? {
            guard view.window != nil, view.bounds.width > 0, view.bounds.height > 0 else { return nil }
            let (width, height) = (24, 48)
            var pixels = [UInt32](repeating: 0, count: width * height)
            let drawn = pixels.withUnsafeMutableBytes { buffer -> Bool in
                guard let context = CGContext(data: buffer.baseAddress, width: width, height: height, bitsPerComponent: 8,
                                              bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
                                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return false }
                context.translateBy(x: 0, y: CGFloat(height))
                context.scaleBy(x: CGFloat(width) / view.bounds.width, y: -CGFloat(height) / view.bounds.height)
                UIGraphicsPushContext(context)
                defer { UIGraphicsPopContext() }
                return view.drawHierarchy(in: view.bounds, afterScreenUpdates: false)
            }
            return drawn ? pixels : nil
        }

        func onMapLoaded(with statistics: YMKMapLoadStatistics) { markLoaded() }

        func onCameraPositionChanged(with map: YMKMap, cameraPosition: YMKCameraPosition,
                                     cameraUpdateReason: YMKCameraUpdateReason, finished: Bool) {
            guard finished else { return }
            onIdle?(GeoPoint(lat: cameraPosition.target.latitude, lng: cameraPosition.target.longitude))
        }

        func draw(on window: YMKMapWindow, zoom: Float, colours: Colours) {
            guard let content else { return }
            let map = window.map
            let collection = map.mapObjects
            for object in objects { collection.remove(with: object) }
            objects = []
            let points = content.polyline.map { YMKPoint(latitude: $0.lat, longitude: $0.lng) }
            if points.count > 1 {
                let line = collection.addPolyline(with: YMKPolyline(points: points))
                line.setStrokeColorWith(colours.brand)
                line.strokeWidth = 5
                line.outlineColor = colours.surface
                line.outlineWidth = 1.5
                objects.append(line)
            }
            for marker in content.markers {
                let placemark = collection.addPlacemark()
                placemark.geometry = YMKPoint(latitude: marker.point.lat, longitude: marker.point.lng)
                // The destination pin's tip is the point; the round markers sit centred on it.
                let anchor = CGPoint(x: 0.5, y: marker.kind == .destination ? 1 : 0.5)
                placemark.setIconWith(Self.icon(marker.kind, colours: colours), style: YMKIconStyle(
                    anchor: NSValue(cgPoint: anchor), rotationType: nil, zIndex: nil, flat: nil, visible: nil, scale: nil, opacity: 1, tappableArea: nil))
                objects.append(placemark)
            }
            let all = content.polyline + content.markers.map(\.point)
            var camera: ((YMKMap, Bool) -> Void)?
            if Set(all).count > 1, let box = MapCamera.bounds(all) {
                // Two places a street apart get at least ~1 km of map around them, not a building-level zoom.
                let geometry = YMKGeometry(boundingBox: YMKBoundingBox(
                    southWest: YMKPoint(latitude: box.southWest.lat, longitude: box.southWest.lng),
                    northEast: YMKPoint(latitude: box.northEast.lat, longitude: box.northEast.lng)))
                camera = { map, animated in
                    let fitted = map.cameraPosition(with: geometry)
                    Self.move(map, to: YMKCameraPosition(target: fitted.target, zoom: max(fitted.zoom - 0.9, MapCamera.minFitZoom),
                                                         azimuth: 0, tilt: 0), animated: animated)
                }
            } else if let focus = content.focus ?? all.first {
                camera = { map, animated in
                    Self.move(map, to: YMKCameraPosition(target: YMKPoint(latitude: focus.lat, longitude: focus.lng), zoom: zoom,
                                                         azimuth: 0, tilt: 0), animated: animated)
                }
            }
            guard let camera else { return }
            lastCamera = camera
            if window.width() > 0 && window.height() > 0 {
                pendingCamera = nil
                applyFocusRect(window)
                camera(map, false)
            } else {
                pendingCamera = { camera($0, false) }
            }
        }

        private static func move(_ map: YMKMap, to position: YMKCameraPosition, animated: Bool) {
            if animated {
                map.move(with: position, animation: YMKAnimation(type: .smooth, duration: 0.4), cameraCallback: nil)
            } else {
                map.move(with: position)
            }
        }

        /// Android's marker bitmaps, in points: origin = surface disc with a brand ring, destination = teardrop pin
        /// (pin colour) with a surface hole, car = dot with a white rim and a soft halo (grey once stale).
        private static func icon(_ kind: MapMarker.Kind, colours: Colours) -> UIImage {
            switch kind {
            case .origin:
                return UIGraphicsImageRenderer(size: CGSize(width: 22, height: 22)).image { context in
                    let cg = context.cgContext
                    colours.surface.setFill()
                    cg.fillEllipse(in: CGRect(x: 0, y: 0, width: 22, height: 22))
                    let stroke: CGFloat = 4.5, r = 11 - stroke / 2 - 1
                    colours.brand.setStroke()
                    cg.setLineWidth(stroke)
                    cg.strokeEllipse(in: CGRect(x: 11 - r, y: 11 - r, width: 2 * r, height: 2 * r))
                }
            case .destination:
                return UIGraphicsImageRenderer(size: CGSize(width: 26, height: 34)).image { context in
                    let cg = context.cgContext
                    let r: CGFloat = 13
                    colours.pin.setFill()
                    cg.fillEllipse(in: CGRect(x: 0, y: 0, width: 2 * r, height: 2 * r))
                    cg.move(to: CGPoint(x: r * 0.25, y: r * 1.5))
                    cg.addLine(to: CGPoint(x: r, y: 34))
                    cg.addLine(to: CGPoint(x: r * 1.75, y: r * 1.5))
                    cg.closePath()
                    cg.fillPath()
                    colours.surface.setFill()
                    let hole = r * 0.38
                    cg.fillEllipse(in: CGRect(x: r - hole, y: r - hole, width: 2 * hole, height: 2 * hole))
                }
            case .vehicle, .vehicleStale:
                let colour = kind == .vehicle ? colours.brand : UIColor(red: 0x9A / 255, green: 0xA6 / 255, blue: 0xB5 / 255, alpha: 1)
                return UIGraphicsImageRenderer(size: CGSize(width: 30, height: 30)).image { context in
                    let cg = context.cgContext
                    func disc(_ radius: CGFloat, _ fill: UIColor) {
                        fill.setFill()
                        cg.fillEllipse(in: CGRect(x: 15 - radius, y: 15 - radius, width: 2 * radius, height: 2 * radius))
                    }
                    disc(15, colour.withAlphaComponent(60 / 255))
                    disc(15 * 0.55, .white)
                    disc(15 * 0.4, colour)
                }
            }
        }
    }
}

#else

/// Built without the MapKit package (see project.yml, MAPKIT): `ElchiMap` always shows its placeholder.
struct ElchiMapEngine: View {
    static let compiled = false

    let markers: [MapMarker]
    let polyline: [GeoPoint]
    let focus: GeoPoint?
    let zoom: Float
    let insets: EdgeInsets
    let interactive: Bool
    let recentre: Int
    let onIdle: ((GeoPoint) -> Void)?
    let onLoaded: () -> Void
    let onFailed: () -> Void

    var body: some View { EmptyView() }
}

#endif
