import CoreLocation
import UIKit

/// CoreLocation behind `LocationSource`. Created on the main thread, so the manager calls its delegate there; the
/// delegate methods are `nonisolated` (the protocol is) and step onto the main actor with `assumeIsolated`.
///
/// Settings for a vehicle in motion: best accuracy, every fix (`distanceFilter = none`), automotive navigation, never
/// paused automatically. Background delivery (`allowsBackgroundLocationUpdates`, with the system's blue location
/// indicator) only with "Always": with "While using" the updates stop in the background and the bar says so.
@MainActor
final class CoreLocationSource: NSObject, LocationSource, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var updating = false
    /// The last permission state passed on: CoreLocation repeats the callback without a change.
    private var reported: (LocationAuthorization, Bool)?

    var onFix: ((GeoFix) -> Void)?
    var onAuthorizationChange: (() -> Void)?

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBest
        manager.distanceFilter = kCLDistanceFilterNone
        manager.activityType = .automotiveNavigation
        manager.pausesLocationUpdatesAutomatically = false
        UIDevice.current.isBatteryMonitoringEnabled = true
    }

    var authorization: LocationAuthorization {
        switch manager.authorizationStatus {
        case .notDetermined: .notDetermined
        case .restricted: .restricted
        case .denied: .denied
        case .authorizedAlways: .always
        case .authorizedWhenInUse: .whenInUse
        @unknown default: .denied
        }
    }

    var precise: Bool { manager.accuracyAuthorization == .fullAccuracy }

    func requestWhenInUse() { manager.requestWhenInUseAuthorization() }

    func requestAlways() { manager.requestAlwaysAuthorization() }

    func start(background: Bool) {
        // Only legal with the `location` background mode (project.yml) - and only asked for with Always.
        manager.allowsBackgroundLocationUpdates = background
        manager.showsBackgroundLocationIndicator = background
        if !updating {
            updating = true
            manager.startUpdatingLocation()
        }
    }

    func stop() {
        updating = false
        manager.stopUpdatingLocation()
        manager.allowsBackgroundLocationUpdates = false
    }

    /// A standing phone may go quiet: restarting the updates makes CoreLocation deliver a current fix.
    func refresh() {
        guard updating else { return }
        manager.stopUpdatingLocation()
        manager.startUpdatingLocation()
    }

    /// Battery for the point and the bar's low-battery line (unknown on the simulator: -1 -> nil).
    static func battery() -> BatteryState? {
        let device = UIDevice.current
        guard device.batteryLevel >= 0 else { return nil }
        return BatteryState(pct: Int((device.batteryLevel * 100).rounded()),
                            charging: device.batteryState == .charging || device.batteryState == .full)
    }

    // MARK: CLLocationManagerDelegate

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        let fixes = locations.map(Self.fix)
        MainActor.assumeIsolated {
            for fix in fixes { onFix?(fix) }
        }
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        MainActor.assumeIsolated {
            let now = (authorization, precise)
            if let reported, reported == now { return }
            reported = now
            onAuthorizationChange?()
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        // `locationUnknown` is transient (the updates keep running); a denial arrives as an authorization change.
    }

    nonisolated private static func fix(_ location: CLLocation) -> GeoFix {
        let mock = location.sourceInformation?.isSimulatedBySoftware ?? false
        return GeoFix(lat: location.coordinate.latitude, lng: location.coordinate.longitude,
                      accuracy: location.horizontalAccuracy,
                      speed: location.speed >= 0 ? location.speed : nil,
                      heading: location.course >= 0 ? location.course : nil,
                      timestamp: location.timestamp, isMock: mock)
    }
}
