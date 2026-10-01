import Observation
import SwiftUI

// MARK: - Pure rules

/// The profile's figures: the v2 reputation (parcel) for the rating and completed bookings - "Yangi" while nobody
/// rated, never an invented score (§8.2) - and the legacy v1 total labelled as such.
public enum DriverProfileStats {
    public struct Values: Equatable, Sendable {
        /// nil = "Yangi".
        public let rating: String?
        /// nil = not known yet ("—").
        public let completed: Int?
        public let legacyTotal: Int?
    }

    public static func make(reputation: ReputationDTO?, profile: DriverProfileV1?) -> Values {
        let rating: String? = reputation.flatMap { rep in
            guard rep.ratingCount > 0, let average = rep.averageRating else { return nil }
            return String(format: "%.1f", average).replacingOccurrences(of: ".", with: ",")
        }
        return Values(rating: rating, completed: reputation?.completedBookings, legacyTotal: profile?.totalOrders)
    }

    /// "Yo'nalish": trips still ahead or running (planned, boarding, in progress, interrupted).
    public static func routesCount(_ trips: [TripDTO]) -> Int {
        trips.filter { ["planned", "boarding", "in_progress", "interrupted"].contains($0.status.rawValue) }.count
    }
}

/// The profile's quick actions in the design's order.
public enum DriverProfileAction: String, CaseIterable, Sendable {
    case form, documents, routes, proposals, bonus, orders, threads, safety, help, settings, logout

    var icon: ElchiIcon {
        switch self {
        case .form: .user
        case .documents: .file
        case .routes: .route
        case .proposals: .tag
        case .bonus: .tag
        case .orders: .clip
        case .threads: .chat
        case .safety: .block
        case .help: .head
        case .settings: .settings
        case .logout: .logout
        }
    }

    var titleKey: String {
        switch self {
        case .form: "driverProfileForm.title"
        case .documents: "driverProfile.action.documents"
        case .routes: "driverProfile.action.routes"
        case .proposals: "driverProfile.action.proposals"
        case .bonus: "driverProfile.action.bonus"
        case .orders: "driverProfile.action.orders"
        case .threads: "support.myThreads"
        case .safety: "safety.centerTitle"
        case .help: "driverProfile.action.support"
        case .settings: "driverProfile.action.settings"
        case .logout: "driverProfile.action.logout"
        }
    }

    var hintKey: String? {
        switch self {
        case .form: "driver.profile.editHint"
        case .documents: "driverProfile.action.documentsHint"
        case .routes: "driverProfile.action.routesHint"
        case .proposals: "driverProfile.action.proposalsHint"
        case .bonus: "driverProfile.action.bonusHint"
        case .orders: "driverProfile.action.ordersHint"
        case .threads: "support.myThreadsHint"
        case .safety: nil
        case .help: "driverProfile.action.supportHint"
        case .settings: "driver.profile.settingsHint"
        case .logout: "driverProfile.action.logoutHint"
        }
    }
}

// MARK: - Model

/// What the profile reads besides the v1 profile: the v2 id (`GET /me`) for the reputation, and the complaints count.
@MainActor @Observable
final class DriverProfileStatsModel {
    private let api: ElchiAPI
    private(set) var reputation: ReputationDTO?
    private(set) var reports: Int?
    private var userId: String?

    init(api: ElchiAPI) { self.api = api }

    func load() async {
        if userId == nil { userId = try? await api.getMe().data.id }
        async let reputation: Void = loadReputation()
        async let reports: Void = loadReports()
        _ = await (reputation, reports)
    }

    private func loadReputation() async {
        guard let userId else { return }
        if let fresh = try? await api.getReputation(userId: userId, serviceType: .parcel).data { reputation = fresh }
    }

    private func loadReports() async {
        if let list = try? await api.listMyReports(limit: 100).data { reports = list.count }
    }
}

// MARK: - Profil tab

/// The full driver profile (design 'driver-profile'): who, the figures, availability, the car, status / routes /
/// complaints, and the quick actions.
struct DriverProfileView: View {
    let driver: DriverModel
    let stats: DriverProfileStatsModel
    let trips: TripsModel
    let session: Session
    let onAction: (DriverProfileAction) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        DriverTabScreen(title: strings.t("driverProfile.title")) {
            let profile = driver.profile.value
            let name = [profile?.fullName, profile?.user?.fullName, session.user.fullName]
                .compactMap { $0?.trimmingCharacters(in: .whitespaces) }.first { !$0.isEmpty }
            let phone = UzPhone.display(session.user.phone)
            let status = driver.status
            AvatarCard(initials: Initials.of(name), name: name ?? phone, phone: name == nil ? nil : phone, badges: badges(profile, status))
                .accessibilityIdentifier("elchi.driver.profile.header")
            let values = DriverProfileStats.make(reputation: stats.reputation, profile: profile)
            StatTiles([(strings.t("driverProfile.rating"), values.rating.map { "★ \($0)" } ?? strings.t("reputation.new")),
                       (strings.t("driverProfile.completed"), values.completed.map(String.init) ?? "—"),
                       (strings.t("driver.profile.totalLegacy"), values.legacyTotal.map(String.init) ?? "—")])
                .accessibilityIdentifier("elchi.driver.profile.stats")
            if let status { availability(status) }
            ElchiCard {
                CardRow(strings.t("driverProfile.vehicle"), vehicleLine(profile), first: true)
            }
            StatTiles([(strings.t("driverProfile.status"), status.map(strings.verificationLabel) ?? "—"),
                       (strings.t("driverProfile.routes"), trips.trips.value.map { "\(DriverProfileStats.routesCount($0))" } ?? "—"),
                       (strings.t("driver.profile.complaints"), stats.reports.map(String.init) ?? "—")])
            SectionTitle(strings.t("driverProfile.quickActions"))
            ElchiList {
                ForEach(Array(DriverProfileAction.allCases.enumerated()), id: \.element) { index, action in
                    ListRow(icon: action.icon, title: strings.t(action.titleKey), description: action.hintKey.map { strings.t($0) },
                            danger: action == .logout, first: index == 0) { onAction(action) }
                        .accessibilityIdentifier("elchi.driver.menu.\(action.rawValue)")
                }
            }
        }
        .refreshable { await load() }
        .task { await load() }
    }

    /// The verification status and availability, both in words (never the raw codes).
    private func badges(_ profile: DriverProfileV1?, _ status: DriverVerification?) -> [(text: String, tone: Tone)] {
        var out: [(text: String, tone: Tone)] = []
        if let status { out.append((strings.verificationLabel(status), status.tone)) }
        if profile != nil {
            out.append(driver.isAvailable ? (strings.t("driverProfile.active"), .blue) : (strings.t("driverProfile.inactive"), .gray))
        }
        return out
    }

    private func load() async {
        async let profile: Void = driver.loadProfile()
        async let figures: Void = stats.load()
        async let list: Void = trips.load()
        _ = await (profile, figures, list)
    }

    private func vehicleLine(_ profile: DriverProfileV1?) -> String {
        let parts = [profile?.carModel, profile?.carColor, profile?.plateNumber].compactMap { $0?.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        return parts.isEmpty ? strings.t("driverProfile.noVehicle") : parts.joined(separator: " / ")
    }

    private func availability(_ status: DriverVerification) -> some View {
        let enabled = DriverAvailability.canToggle(status: status, isOn: driver.isAvailable) && driver.availabilityPending == nil
        return ToggleRow(strings.t("driverProfile.availabilityTitle"),
                         description: strings.t(DriverAvailability.subtitleKey(status: status, isOn: driver.isAvailable)),
                         isOn: Binding(get: { driver.isAvailable }, set: { on in Task { await driver.setAvailability(on) } }))
            .disabled(!enabled)
            .opacity(enabled || driver.availabilityPending != nil ? 1 : 0.6)
            .accessibilityIdentifier("elchi.driver.profile.availability")
    }
}
