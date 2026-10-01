import SwiftUI

// MARK: - Shared screen states (the design's "Umumiy holatlar")

/// Loading: grey placeholder cards (the design's skeleton).
public struct LoadingState: View {
    let count: Int
    public init(count: Int = 3) { self.count = count }

    public var body: some View { SkeletonCards(count: count) }
}

/// Empty list: the parcel icon and one line ("Hozircha buyurtmalar yo'q"), optionally a second.
public struct EmptyListState: View {
    let title: String
    let description: String?
    let icon: ElchiIcon

    public init(_ title: String, description: String? = nil, icon: ElchiIcon = .pkg) {
        self.title = title
        self.description = description
        self.icon = icon
    }

    public var body: some View { EmptyState(icon: icon, title: title, description: description) }
}

/// Not found (someone else's, or gone): the search icon, "Ma'lumot topilmadi" and a back button.
public struct NotFoundState: View {
    let title: String
    let backLabel: String
    let onBack: () -> Void

    public init(title: String, backLabel: String, onBack: @escaping () -> Void) {
        self.title = title
        self.backLabel = backLabel
        self.onBack = onBack
    }

    public var body: some View {
        VStack(spacing: 4) {
            EmptyState(icon: .search, title: title)
            ElchiButton(backLabel, variant: .neutral, size: .medium, action: onBack)
        }
        .accessibilityIdentifier("elchi.state.notFound")
    }
}
