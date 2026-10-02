import Foundation
import Testing
@testable import Elchi

/// The client map's my-location button: permission only on tap, centring on a fresh fix, waiting for the first fix
/// (with a 10 s timeout that an older wait cannot fire), denial, updates only while the home is visible, the dot.
struct MyLocationTests {
    static let t0 = Date(timeIntervalSince1970: 1_790_000_000)
    static let tashkent = GeoPoint(lat: 41.2995, lng: 69.2401)

    static func fix(_ seconds: TimeInterval = 0, accuracy: Double = 20) -> UserLocationFix {
        UserLocationFix(point: tashkent, accuracy: accuracy, timestamp: t0.addingTimeInterval(seconds))
    }

    static func state(_ auth: MyLocationAuth, visible: Bool = true) -> MyLocationState {
        var state = MyLocationState()
        state.auth = auth
        state.visible = visible
        return state
    }

    @Test func nothingIsAskedOrMovedUntilATap() {
        var state = MyLocationState()
        #expect(MyLocationLogic.reduce(&state, .appear).isEmpty)
        #expect(MyLocationLogic.reduce(&state, .authorization(.notDetermined)).isEmpty)
        #expect(!state.updating && !state.showsDot && !state.locating)
    }

    @Test func firstTapAsksOnceThenAllowWaitsAndCentresOnTheFirstFix() {
        var state = Self.state(.notDetermined)
        #expect(MyLocationLogic.reduce(&state, .tap(now: Self.t0)) == [.requestPermission])
        // A second tap while the prompt is up asks nothing more.
        #expect(MyLocationLogic.reduce(&state, .tap(now: Self.t0)).isEmpty)
        #expect(MyLocationLogic.reduce(&state, .authorization(.authorized)) == [.startTimer(attempt: 1)])
        #expect(state.locating && state.updating && !state.askedPermission)
        #expect(MyLocationLogic.reduce(&state, .fix(Self.fix(), now: Self.t0.addingTimeInterval(0))) == [.centre(Self.fix())])
        #expect(!state.locating && state.showsDot)
    }

    @Test func denyingInThePromptShowsTheSettingsBanner() {
        var state = Self.state(.notDetermined)
        _ = MyLocationLogic.reduce(&state, .tap(now: Self.t0))
        #expect(MyLocationLogic.reduce(&state, .authorization(.denied)) == [.showDenied])
        #expect(!state.locating && !state.updating && !state.askedPermission)
        // Later taps go straight to the banner: iOS does not ask twice.
        #expect(MyLocationLogic.reduce(&state, .tap(now: Self.t0)) == [.showDenied])
    }

    @Test func aDenialNotCausedByATapIsSilentAndHidesTheDot() {
        var state = Self.state(.authorized)
        _ = MyLocationLogic.reduce(&state, .fix(Self.fix(), now: Self.t0.addingTimeInterval(0)))
        #expect(state.showsDot)
        #expect(MyLocationLogic.reduce(&state, .authorization(.denied)).isEmpty)
        #expect(!state.showsDot && state.fix == nil)
    }

    @Test func alreadyAllowedShowsTheDotButNeverMovesTheCameraByItself() {
        var state = Self.state(.authorized)
        #expect(state.updating)
        #expect(MyLocationLogic.reduce(&state, .fix(Self.fix(), now: Self.t0.addingTimeInterval(0))).isEmpty)
        #expect(state.showsDot)
        #expect(MyLocationLogic.reduce(&state, .tap(now: Self.t0.addingTimeInterval(5))) == [.centre(Self.fix())])
    }

    @Test func aStaleFixWaitsForACurrentOne() {
        var state = Self.state(.authorized)
        _ = MyLocationLogic.reduce(&state, .fix(Self.fix(), now: Self.t0.addingTimeInterval(0)))
        let later = Self.t0.addingTimeInterval(MyLocationLogic.freshness + 1)
        #expect(MyLocationLogic.reduce(&state, .tap(now: later)) == [.startTimer(attempt: 1)])
        #expect(state.locating && state.showsDot)
        // Tapping again while waiting does not restart the wait.
        #expect(MyLocationLogic.reduce(&state, .tap(now: later)).isEmpty)
        #expect(MyLocationLogic.reduce(&state, .fix(Self.fix(200), now: Self.t0.addingTimeInterval(200))) == [.centre(Self.fix(200))])
    }

    @Test func aCachedOldFixWhileWaitingMovesTheDotButNotTheCamera() {
        var state = Self.state(.authorized)
        _ = MyLocationLogic.reduce(&state, .tap(now: Self.t0))
        let now = Self.t0.addingTimeInterval(MyLocationLogic.freshness + 60)
        #expect(MyLocationLogic.reduce(&state, .fix(Self.fix(), now: now)).isEmpty)
        #expect(state.locating && state.showsDot)
    }

    @Test func noFixWithinTheTimeoutSaysSo() {
        var state = Self.state(.authorized)
        _ = MyLocationLogic.reduce(&state, .tap(now: Self.t0))
        #expect(MyLocationLogic.reduce(&state, .timeout(attempt: 1)) == [.showUnavailable])
        #expect(!state.locating)
        // A fix arriving afterwards draws the dot but does not jump the camera.
        #expect(MyLocationLogic.reduce(&state, .fix(Self.fix(), now: Self.t0.addingTimeInterval(0))).isEmpty)
        #expect(state.showsDot)
    }

    @Test func anOlderWaitsTimerCannotEndTheCurrentWait() {
        var state = Self.state(.authorized)
        _ = MyLocationLogic.reduce(&state, .tap(now: Self.t0))
        _ = MyLocationLogic.reduce(&state, .disappear)
        _ = MyLocationLogic.reduce(&state, .appear)
        #expect(MyLocationLogic.reduce(&state, .tap(now: Self.t0)) == [.startTimer(attempt: 2)])
        #expect(MyLocationLogic.reduce(&state, .timeout(attempt: 1)).isEmpty)
        #expect(state.locating)
        #expect(MyLocationLogic.reduce(&state, .timeout(attempt: 2)) == [.showUnavailable])
    }

    @Test func leavingTheHomeStopsUpdatesAndTheWaitButKeepsTheDot() {
        var state = Self.state(.authorized)
        _ = MyLocationLogic.reduce(&state, .fix(Self.fix(-500), now: Self.t0.addingTimeInterval(-500)))
        _ = MyLocationLogic.reduce(&state, .tap(now: Self.t0))
        #expect(MyLocationLogic.reduce(&state, .disappear).isEmpty)
        #expect(!state.updating && !state.locating && state.showsDot)
        // A fix that slips in after leaving does not move the camera later.
        #expect(MyLocationLogic.reduce(&state, .fix(Self.fix(), now: Self.t0.addingTimeInterval(0))).isEmpty)
        _ = MyLocationLogic.reduce(&state, .appear)
        #expect(state.updating)
    }

    @Test func approximateFixesGetAWiderView() {
        #expect(MyLocationLogic.zoom(accuracy: 15) == 14)
        #expect(MyLocationLogic.zoom(accuracy: 3000) == 12)
    }

    // MARK: The one automatic centring (Android parity)

    static func emptyHome() -> MyLocationState {
        var state = Self.state(.authorized)
        _ = MyLocationLogic.reduce(&state, .homeEmpty(true))
        return state
    }

    @Test func theFirstFixOnAnEmptyHomeCentresTheCityOnce() {
        var state = Self.emptyHome()
        #expect(MyLocationLogic.reduce(&state, .fix(Self.fix(), now: Self.t0)) == [.autoCentre(Self.fix())])
        #expect(MyLocationLogic.reduce(&state, .fix(Self.fix(10), now: Self.t0.addingTimeInterval(10))).isEmpty)
        #expect(MyLocationLogic.autoCentreZoom == 11)
    }

    @Test func noAutomaticCentringAfterTheMapWasMoved() {
        var state = Self.emptyHome()
        _ = MyLocationLogic.reduce(&state, .mapMovedByUser)
        #expect(MyLocationLogic.reduce(&state, .fix(Self.fix(), now: Self.t0)).isEmpty)
        #expect(state.showsDot)
    }

    @Test func noAutomaticCentringWithAPlaceChosenEvenIfItIsClearedLater() {
        var state = Self.state(.authorized)
        _ = MyLocationLogic.reduce(&state, .homeEmpty(false))
        #expect(MyLocationLogic.reduce(&state, .fix(Self.fix(), now: Self.t0)).isEmpty)
        var cleared = Self.emptyHome()
        _ = MyLocationLogic.reduce(&cleared, .homeEmpty(false))
        _ = MyLocationLogic.reduce(&cleared, .homeEmpty(true))
        #expect(MyLocationLogic.reduce(&cleared, .fix(Self.fix(), now: Self.t0)).isEmpty)
    }

    @Test func aFirstFixAbroadKeepsTheCountryViewAndSpendsTheCentring() {
        var state = Self.emptyHome()
        let almaty = UserLocationFix(point: GeoPoint(lat: 43.238, lng: 76.889), accuracy: 20, timestamp: Self.t0)
        #expect(MyLocationLogic.reduce(&state, .fix(almaty, now: Self.t0)).isEmpty)
        #expect(MyLocationLogic.reduce(&state, .fix(Self.fix(), now: Self.t0)).isEmpty)
    }

    @Test func aCachedOldFixDoesNotCentreButAFreshOneStillCan() {
        var state = Self.emptyHome()
        let now = Self.t0.addingTimeInterval(MyLocationLogic.freshness + 30)
        #expect(MyLocationLogic.reduce(&state, .fix(Self.fix(), now: now)).isEmpty)
        #expect(MyLocationLogic.reduce(&state, .fix(Self.fix(200), now: Self.t0.addingTimeInterval(200))) == [.autoCentre(Self.fix(200))])
    }

    @Test func aTapCentringSpendsTheAutomaticOne() {
        var state = MyLocationState()
        state.visible = true
        _ = MyLocationLogic.reduce(&state, .homeEmpty(true))
        _ = MyLocationLogic.reduce(&state, .tap(now: Self.t0))
        _ = MyLocationLogic.reduce(&state, .authorization(.authorized))
        #expect(MyLocationLogic.reduce(&state, .fix(Self.fix(), now: Self.t0)) == [.centre(Self.fix())])
        #expect(MyLocationLogic.reduce(&state, .fix(Self.fix(5), now: Self.t0.addingTimeInterval(5))).isEmpty)
    }

    @Test func uzbekistanBoundingBox() {
        #expect(MyLocationLogic.insideUzbekistan(Self.tashkent))
        #expect(MyLocationLogic.insideUzbekistan(GeoPoint(lat: 42.46, lng: 59.6)))   // Nukus
        #expect(!MyLocationLogic.insideUzbekistan(GeoPoint(lat: 55.75, lng: 37.62))) // Moscow
        #expect(!MyLocationLogic.insideUzbekistan(GeoPoint(lat: 43.238, lng: 76.889))) // Almaty
    }
}
