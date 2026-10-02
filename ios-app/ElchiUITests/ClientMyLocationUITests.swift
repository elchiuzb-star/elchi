import XCTest

/// The client home's my-location button against a client that is already signed in. Each phase runs on its own,
/// after the shell sets the simulator up (`xcrun simctl privacy <id> reset location uz.elchi.app`, `xcrun simctl
/// location <id> set 41.2995,69.2401` or `clear`): `test01_Allow`, `test02_AlreadyAllowed`, `test03_Unavailable`
/// (permission kept; `-uiTestNoLocationFix` drops every fix), `test04_Deny` (after a reset), `test05_ColdStartAutoCentre` (permission kept, empty home). `TEST_RUNNER_MYLOC_SHOTS` = a folder for PNGs.
@MainActor
final class ClientMyLocationUITests: ClientUITestCase {
    private let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")

    private var myLocation: XCUIElement { app.buttons["elchi.map.myLocation"] }

    private func shot(_ name: String) {
        let screenshot = XCUIScreen.main.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
        if let folder = ProcessInfo.processInfo.environment["MYLOC_SHOTS"], !folder.isEmpty {
            try? screenshot.pngRepresentation.write(to: URL(fileURLWithPath: folder).appendingPathComponent("\(name).png"))
        }
    }

    private func openHome(extra: [String] = []) {
        launch(reset: false, extra: extra)
        XCTAssertTrue(myLocation.waitForExistence(timeout: 45), "no my-location button on the home map")
        XCTAssertEqual(myLocation.label, "Mening joylashuvim")
        sleep(2)
    }

    private func systemButton(_ prefix: String) -> XCUIElement {
        springboard.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", prefix)).firstMatch
    }

    func test01_Allow() {
        openHome()
        shot("01-home-no-permission")
        myLocation.tap()
        let allow = systemButton("Allow While Using")
        XCTAssertTrue(allow.waitForExistence(timeout: 10), "the tap did not ask for location")
        shot("02-system-prompt")
        allow.tap()
        sleep(3)
        shot("03-centred-on-tashkent")
    }

    func test02_AlreadyAllowed() {
        openHome()
        // No prompt and no camera move: the dot over Tashkent on the Uzbekistan view.
        XCTAssertFalse(systemButton("Allow").waitForExistence(timeout: 3))
        sleep(2)
        shot("04-relaunch-dot-no-camera-move")
        myLocation.tap()
        sleep(2)
        shot("05-tap-centres")
    }

    func test03_Unavailable() {
        openHome(extra: ["-uiTestNoLocationFix", "YES"])
        myLocation.tap()
        let locating = app.descendants(matching: .any)["elchi.map.locating"]
        XCTAssertTrue(locating.waitForExistence(timeout: 3), "no locating pill")
        shot("06-locating")
        waitFor("Joylashuvni aniqlab bo'lmadi", timeout: 15)
        shot("07-unavailable-banner")
    }

    /// Permission already given, nothing chosen: the first fix centres Tashkent once at city level by itself.
    func test05_ColdStartAutoCentre() {
        openHome()
        sleep(3)
        shot("10-cold-start-auto-centre")
    }

    func test04_Deny() {
        openHome()
        myLocation.tap()
        let deny = systemButton("Don")
        XCTAssertTrue(deny.waitForExistence(timeout: 10), "the tap did not ask for location")
        deny.tap()
        let banner = waitFor("Joylashuvga ruxsat berilmagan", timeout: 10)
        shot("08-denied-banner")
        banner.tap()
        let settings = XCUIApplication(bundleIdentifier: "com.apple.Preferences")
        XCTAssertTrue(settings.wait(for: .runningForeground, timeout: 10), "the banner did not open Settings")
        sleep(2)
        shot("09-settings-opened")
    }
}
