import CoreLocation
import Observation
import UIKit

/// The client map's "you are here" (Q-myloc): a dot with an accuracy halo while the home is on screen and location is
/// allowed, and a round button that asks for When-In-Use on its first tap only (never at launch), then moves the
/// camera to the person. Nothing here is sent anywhere, and the driver's trip GPS (`CoreLocationSource`) is separate.

/// One position from CoreLocation, as the map draws it.
public struct UserLocationFix: Equatable, Sendable {
    public let point: GeoPoint
    /// Horizontal accuracy in metres (the halo's radius); large with reduced ("approximate") accuracy.
    public let accuracy: Double
    public let timestamp: Date

    public init(point: GeoPoint, accuracy: Double, timestamp: Date) {
        self.point = point
        self.accuracy = accuracy
        self.timestamp = timestamp
    }
}

/// A camera move the map performs once (a new `id` for each tap that ends on the person).
public struct MapCameraRequest: Equatable, Sendable {
    public let id: Int
    public let point: GeoPoint
    public let zoom: Float
}

public enum MyLocationAuth: Equatable, Sendable {
    /// Never asked: the first tap asks.
    case notDetermined
    /// Denied, or restricted by the device: only Settings can change it.
    case denied
    /// While using (or Always, from the driver's side of the same app); reduced accuracy counts too.
    case authorized
}

/// The button's state machine, without CoreLocation or MapKit, so every path can be tested.
public struct MyLocationState: Equatable, Sendable {
    public var auth: MyLocationAuth = .notDetermined
    /// The latest position; kept while the home is hidden so the dot does not blink when it comes back.
    public var fix: UserLocationFix?
    /// The home is on screen: only then does CoreLocation run.
    public var visible = false
    /// The first tap asked iOS; the system prompt is up.
    public var askedPermission = false
    /// A tap is waiting for the first fix ("Joylashuv aniqlanmoqda…").
    public var locating = false
    /// Bumped by every wait, so a timer from an earlier wait cannot end the current one.
    public var attempt = 0
    /// No place is chosen on the home: the one automatic centring (on the first fix) is still possible.
    public var homeEmpty = false
    /// The automatic centring has happened, or can no longer happen: the person moved the map, a place was chosen,
    /// a tap centred, or the first fix came (inside Uzbekistan or not).
    public var autoCentreSpent = false

    public init() {}

    /// CoreLocation delivers fixes only while this is true.
    public var updating: Bool { visible && auth == .authorized }
    /// The dot (and its halo) is drawn.
    public var showsDot: Bool { auth == .authorized && fix != nil }
}

public enum MyLocationEvent: Equatable, Sendable {
    case appear, disappear
    case tap(now: Date)
    case authorization(MyLocationAuth)
    case fix(UserLocationFix, now: Date)
    case timeout(attempt: Int)
    /// A place is chosen (false) or none is (true).
    case homeEmpty(Bool)
    /// The person panned or zoomed the map.
    case mapMovedByUser
}

public enum MyLocationEffect: Equatable, Sendable {
    /// Show the system When-In-Use prompt.
    case requestPermission
    /// Start the 10 s wait for a fix.
    case startTimer(attempt: Int)
    /// Animate the camera to the person.
    case centre(UserLocationFix)
    /// The one automatic centring of an empty home: city level, not animated away from anything the person chose.
    case autoCentre(UserLocationFix)
    /// Banner `client.map.locationDenied`, tapping it opens Settings.
    case showDenied
    /// Banner `client.map.locationUnavailable`.
    case showUnavailable
}

public enum MyLocationLogic {
    /// How long a tap waits for a fix before saying it could not find one.
    public static let timeout: Duration = .seconds(10)
    /// A fix older than this is not centred on: the tap waits for a current one.
    public static let freshness: TimeInterval = 120

    /// Street level for a precise fix; a wider view when the fix is approximate (reduced accuracy is kilometres).
    public static func zoom(accuracy: Double) -> Float {
        accuracy > 1000 ? 12 : 14
    }

    /// The automatic centring's zoom: the city around the person (Android's value).
    public static let autoCentreZoom: Float = 11

    /// Uzbekistan's bounding box, roughly: a first fix outside it (abroad, a VPN-less tourist) keeps the country view.
    public static func insideUzbekistan(_ point: GeoPoint) -> Bool {
        (37.1...45.6).contains(point.lat) && (55.9...73.2).contains(point.lng)
    }

    public static func reduce(_ state: inout MyLocationState, _ event: MyLocationEvent) -> [MyLocationEffect] {
        switch event {
        case .appear:
            state.visible = true
            return []
        case .disappear:
            // Off screen nothing waits: no late camera jump or banner when the person comes back.
            state.visible = false
            state.locating = false
            return []
        case .tap(let now):
            switch state.auth {
            case .notDetermined:
                guard !state.askedPermission else { return [] }
                state.askedPermission = true
                return [.requestPermission]
            case .denied:
                return [.showDenied]
            case .authorized:
                if let fix = state.fix, now.timeIntervalSince(fix.timestamp) <= freshness {
                    state.locating = false
                    state.autoCentreSpent = true
                    return [.centre(fix)]
                }
                return wait(&state)
            }
        case .authorization(let auth):
            let asked = state.askedPermission
            state.auth = auth
            switch auth {
            case .notDetermined:
                return []
            case .denied:
                state.askedPermission = false
                state.locating = false
                state.fix = nil
                // Said "no" in the prompt the tap opened: say where to change it.
                return asked ? [.showDenied] : []
            case .authorized:
                state.askedPermission = false
                guard asked else { return [] }
                // Allowed in the prompt: the tap goes on to the person (no fix can exist yet).
                if let fix = state.fix {
                    state.autoCentreSpent = true
                    return [.centre(fix)]
                }
                return wait(&state)
            }
        case .fix(let fix, let now):
            state.fix = fix
            // CoreLocation may hand over a cached, old position first: the dot shows it, nothing moves on it.
            guard now.timeIntervalSince(fix.timestamp) <= freshness else { return [] }
            if state.locating {
                state.locating = false
                state.autoCentreSpent = true
                return [.centre(fix)]
            }
            // Already allowed and nothing chosen yet: the first current fix centres the city once, if it is in
            // Uzbekistan and the person has not moved the map. Once a place is chosen the camera never moves alone.
            guard !state.autoCentreSpent, state.homeEmpty, state.visible, state.auth == .authorized else { return [] }
            state.autoCentreSpent = true
            return insideUzbekistan(fix.point) ? [.autoCentre(fix)] : []
        case .homeEmpty(let empty):
            state.homeEmpty = empty
            if !empty { state.autoCentreSpent = true }
            return []
        case .mapMovedByUser:
            state.autoCentreSpent = true
            return []
        case .timeout(let attempt):
            guard state.locating, attempt == state.attempt else { return [] }
            state.locating = false
            return [.showUnavailable]
        }
    }

    private static func wait(_ state: inout MyLocationState) -> [MyLocationEffect] {
        if state.locating { return [] }
        state.locating = true
        state.attempt += 1
        return [.startTimer(attempt: state.attempt)]
    }
}

/// CoreLocation behind `MyLocationState`: its own When-In-Use manager (not the driver's tracker), running only while
/// the home is visible and location is allowed. Created on the main thread, so the delegate is called there.
@MainActor @Observable
public final class MyLocationModel: NSObject, CLLocationManagerDelegate {
    public private(set) var state = MyLocationState()
    /// The last camera move asked of the map.
    public private(set) var camera: MapCameraRequest?
    @ObservationIgnored var onDenied: (() -> Void)?
    @ObservationIgnored var onUnavailable: (() -> Void)?
    /// A tap ended on the person (not the automatic first centring): the client home fills an empty "Qayerdan" from it.
    @ObservationIgnored var onCentred: ((UserLocationFix) -> Void)?
    /// Made on the first appearance, not in `init`: SwiftUI may build (and drop) this model with every redraw.
    @ObservationIgnored private var manager: CLLocationManager?
    @ObservationIgnored private var running = false
    @ObservationIgnored private var timer: Task<Void, Never>?

    public override init() {
        super.init()
    }

    public func appear() {
        if manager == nil {
            let manager = CLLocationManager()
            manager.desiredAccuracy = kCLLocationAccuracyNearestTenMeters
            manager.distanceFilter = 10
            manager.activityType = .other
            state.auth = Self.auth(manager.authorizationStatus)
            // Setting the delegate also brings the current authorization (`locationManagerDidChangeAuthorization`).
            manager.delegate = self
            self.manager = manager
        }
        send(.appear)
    }

    public func disappear() { send(.disappear) }
    public func tap() { send(.tap(now: Date())) }
    public func homeEmpty(_ empty: Bool) {
        guard empty != state.homeEmpty || !empty && !state.autoCentreSpent else { return }
        send(.homeEmpty(empty))
    }
    /// Called on every camera change a gesture makes: only the first one is news.
    public func mapMovedByUser() {
        guard !state.autoCentreSpent else { return }
        send(.mapMovedByUser)
    }

    func send(_ event: MyLocationEvent) {
        let effects = MyLocationLogic.reduce(&state, event)
        if state.updating != running {
            running = state.updating
            if running { manager?.startUpdatingLocation() } else { manager?.stopUpdatingLocation() }
        }
        if !state.locating { timer?.cancel() }
        for effect in effects {
            switch effect {
            case .requestPermission:
                manager?.requestWhenInUseAuthorization()
            case .startTimer(let attempt):
                timer?.cancel()
                timer = Task { [weak self] in
                    try? await Task.sleep(for: MyLocationLogic.timeout)
                    guard !Task.isCancelled else { return }
                    self?.send(.timeout(attempt: attempt))
                }
            case .centre(let fix):
                camera = MapCameraRequest(id: (camera?.id ?? 0) + 1, point: fix.point, zoom: MyLocationLogic.zoom(accuracy: fix.accuracy))
                onCentred?(fix)
            case .autoCentre(let fix):
                camera = MapCameraRequest(id: (camera?.id ?? 0) + 1, point: fix.point, zoom: MyLocationLogic.autoCentreZoom)
            case .showDenied:
                onDenied?()
            case .showUnavailable:
                onUnavailable?()
            }
        }
    }

    nonisolated static func auth(_ status: CLAuthorizationStatus) -> MyLocationAuth {
        switch status {
        case .notDetermined: .notDetermined
        case .authorizedWhenInUse, .authorizedAlways: .authorized
        case .denied, .restricted: .denied
        @unknown default: .denied
        }
    }

    // MARK: CLLocationManagerDelegate

    public nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let auth = Self.auth(manager.authorizationStatus)
        MainActor.assumeIsolated {
            guard auth != state.auth || state.askedPermission else { return }
            send(.authorization(auth))
        }
    }

    public nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        #if DEBUG
        // UI tests: a phone that never finds itself (the simulator always has a position), for the 10 s timeout.
        if UserDefaults.standard.bool(forKey: "uiTestNoLocationFix") { return }
        #endif
        guard let last = locations.last(where: { $0.horizontalAccuracy >= 0 }) else { return }
        let fix = UserLocationFix(point: GeoPoint(lat: last.coordinate.latitude, lng: last.coordinate.longitude),
                                  accuracy: last.horizontalAccuracy, timestamp: last.timestamp)
        MainActor.assumeIsolated { send(.fix(fix, now: Date())) }
    }

    public nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        // `locationUnknown` is transient (the updates keep running, the 10 s timer covers a fix that never comes);
        // a denial arrives as an authorization change.
    }
}
