import Foundation
import Observation

/// Design v3 home: "Mijozlar e'lonlari" read from every active direction (DD5, the filter's period), merged, plus the
/// "Kredit va taklif kodi" amount. Search, chips and the filter are applied on what came back (HomeListingLogic).
@MainActor @Observable
final class HomeListingsModel {
    private let api: ElchiAPI
    let directions: DirectionsModel

    /// nil until the first read; `.loaded([])` also when there is no active direction (the view tells them apart).
    private(set) var listings: Loadable<[HomeListing]>?
    var chip: HomeChip = .all
    var filter = HomeFilter()
    var query = ""

    /// The driver credit still available (minor). nil = none, programme off or not read: "Hozircha kredit yo'q".
    private(set) var creditMinor: Int?

    init(api: ElchiAPI, directions: DirectionsModel) {
        self.api = api
        self.directions = directions
    }

    /// Reads the directions, then each active one's requests for every service shown (the passenger feed only while
    /// the flag allows it). One direction failing does not hide the others; all failing shows the error.
    func load(passengerAllowed: Bool, now: Date = Date()) async {
        await directions.load()
        let active = HomeListingLogic.readable(directions.directions)
        guard !active.isEmpty else {
            if case .failed(let error) = directions.list { listings = .failed(error) } else { listings = .loaded([]) }
            return
        }
        if listings?.value == nil { listings = .loading }
        let range = DirectionFeed.range(filter.period, now: now)
        let services = HomeListingLogic.services(passengerAllowed: passengerAllowed)
        // In the driver's direction order, parcel before passenger: the merge keeps the first appearance.
        let calls = active.flatMap { direction in services.map { (directionId: direction.id, service: $0) } }
        let api = self.api
        var pages: [Int: (directionId: String, items: [DirectionRequestItemDTO])] = [:]
        var failure: Error?
        await withTaskGroup(of: (Int, String, Result<[DirectionRequestItemDTO], Error>).self) { group in
            for (offset, call) in calls.enumerated() {
                group.addTask {
                    do {
                        let page = try await api.listDirectionRequests(directionId: call.directionId, serviceType: call.service,
                                                                       dateFrom: range.from, dateTo: range.to).data
                        return (offset, call.directionId, .success(page.items))
                    } catch {
                        return (offset, call.directionId, .failure(error))
                    }
                }
            }
            for await (offset, directionId, result) in group {
                switch result {
                case .success(let items): pages[offset] = (directionId, items)
                case .failure(let error): failure = failure ?? error
                }
            }
        }
        if pages.isEmpty, let failure {
            if listings?.value == nil || listings?.value?.isEmpty == true { listings = .failed(failure) }
            return
        }
        let merged = HomeListingLogic.merge(pages.keys.sorted().compactMap { pages[$0] })
        directions.remember(merged)
        listings = .loaded(merged)
    }

    /// `GET /me/promo-balance`: the driver credit buckets only (never the client's bonus). Programme off or no
    /// bucket -> nil.
    func loadCredit() async {
        do {
            let balance = try await api.myPromoBalance().data
            let total = PromoLogic.buckets(balance, audience: "driver").reduce(0) { $0 + $1.availableMinor }
            creditMinor = total > 0 ? total : nil
        } catch {
            creditMinor = nil
        }
    }
}
