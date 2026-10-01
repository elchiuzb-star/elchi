import SwiftUI

// MARK: - What the shared booking screens need

/// A booking as the shared screens (amendments, tracking) read it, from either side: the client's `BookingModel`
/// (Stage 04) and the driver's `DriverBookingModel` (Stage 09). The common part of both DTOs is `ClientBookingDTO`.
@MainActor
protocol BookingScreenHost: AnyObject, Sendable {
    var bookingBase: ClientBookingDTO? { get }
    var amendments: AmendmentsModel { get }
    var tracking: BookingTrackingModel { get }
    /// "client" or "driver": whose amendments are "mine".
    var side: String { get }
    func load() async
}

/// The safety menu (Q146): a report about this booking and blocking the other side.
@MainActor
protocol SafetyHost: AnyObject, Sendable {
    var report: ReportDTO? { get }
    var warnings: [ApiWarning] { get }
    var commandError: Error? { get }
    var failed: BookingCommand? { get }
    var running: BookingCommand? { get }
    /// The booking names the other side (it can be blocked).
    var counterpartyKnown: Bool { get }
    var blocked: Bool { get }
    func sendReport(reason: ReportReasonCode, details: String) async -> Bool
    func reportAgain()
    func block() async -> Bool
}

/// Rating the other side after completion.
@MainActor
protocol RatingHost: AnyObject, Sendable {
    var commandError: Error? { get }
    var failed: BookingCommand? { get }
    var running: BookingCommand? { get }
    func rate(stars: Int, comment: String) async -> Bool
}

/// The sentences that differ between the client's and the driver's safety and rating screens.
struct BookingSideTexts {
    let safetyNote: String
    let blockedNote: String
    let blockConfirmTitle: String
    let ratingTitle: String

    static let client = BookingSideTexts(safetyNote: "client.safety.note", blockedNote: "client.safety.blocked",
                                         blockConfirmTitle: "client.safety.blockConfirmTitle", ratingTitle: "rating.titleDriver")
    static let driver = BookingSideTexts(safetyNote: "safety.sectionHint", blockedNote: "driver.safety.blocked",
                                         blockConfirmTitle: "driver.safety.blockConfirmTitle", ratingTitle: "rating.titleClient")
}

extension BookingModel: BookingScreenHost, SafetyHost, RatingHost {
    var bookingBase: ClientBookingDTO? { booking.value }
    var side: String { "client" }
    var counterpartyKnown: Bool { booking.value?.driver != nil }
}

// MARK: - A line under the top bar (the driver's GPS bar)

private struct ScreenAccessoryKey: EnvironmentKey {
    nonisolated(unsafe) static let defaultValue: AnyView? = nil
}

extension EnvironmentValues {
    /// Drawn by `ScreenScaffold` under its top bar and banner: the driver's GPS bar on the screens of a running trip.
    var screenAccessory: AnyView? {
        get { self[ScreenAccessoryKey.self] }
        set { self[ScreenAccessoryKey.self] = newValue }
    }
}
