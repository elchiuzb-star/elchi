import Foundation
import Testing
@testable import Elchi

/// Design v3 home (Royxat 1.4-1.12, Safar 1.2-1.7) and trip detail (Safar 4.1, 4.5, 4.6): the merged "Mijozlar
/// e'lonlari" list, its chips / search / filter / sort, the greeting's first name and seal, the kind icon, and the trip
/// detail's stretch rows and title.
struct HomeListingLogicTests {
    private func item(_ id: String, match: MatchType = .exact, fit: String = "fits_trip", start: Date = MarketFixture.at(2026, 10, 7, 9),
                      service: ServiceType = .parcel, unit: Int = 12_000_000, basis: PriceBasis = .total, quantity: Int = 1) -> DirectionRequestItemDTO {
        DirectionRequestItemDTO(fit: fit, listing: MarketFixture.listing(id: id, start: start, end: start.addingTimeInterval(9 * 3600), basis: basis,
                                                                         quantity: quantity, service: service, unit: unit),
                                matchType: match)
    }

    private let now = MarketFixture.at(2026, 10, 7, 8)

    private func ids(_ list: [HomeListing]) -> [String] { list.map(\.id) }

    @Test func mergeKeepsTheFirstAppearanceAndItsDirection() {
        let merged = HomeListingLogic.merge([("dir_1", [item("a"), item("b")]), ("dir_2", [item("b"), item("c")])])
        #expect(ids(merged) == ["a", "b", "c"])
        #expect(merged.map(\.directionId) == ["dir_1", "dir_1", "dir_2"])
    }

    @Test func onlyActiveDirectionsAreRead() {
        let list = [DirectionFixture.direction("d1"), DirectionFixture.direction("d2", status: "paused"), DirectionFixture.direction("d3")]
        #expect(HomeListingLogic.readable(list).map(\.id) == ["d1", "d3"])
    }

    @Test func passengerIsReadOnlyWhileTheFlagAllowsIt() {
        #expect(HomeListingLogic.services(passengerAllowed: false) == [.parcel])
        #expect(HomeListingLogic.services(passengerAllowed: true) == [.parcel, .passenger])
        #expect(HomeChip.shown(passengerAllowed: false) == [.all, .parcel, .today])
        #expect(HomeChip.shown(passengerAllowed: true) == [.all, .parcel, .passenger, .today])
    }

    @Test func chipsFilterByServiceAndToday() {
        let list = HomeListingLogic.merge([("d", [
            item("p", start: MarketFixture.at(2026, 10, 7, 9)),
            item("x", start: MarketFixture.at(2026, 10, 8, 9), service: .passenger, basis: .perSeat, quantity: 2),
        ])])
        let text: (HomeListing) -> String = { $0.id }
        #expect(ids(HomeListingLogic.apply(list, chip: .all, filter: HomeFilter(), query: "", now: now, text: text)) == ["p", "x"])
        #expect(ids(HomeListingLogic.apply(list, chip: .parcel, filter: HomeFilter(), query: "", now: now, text: text)) == ["p"])
        #expect(ids(HomeListingLogic.apply(list, chip: .passenger, filter: HomeFilter(), query: "", now: now, text: text)) == ["x"])
        #expect(ids(HomeListingLogic.apply(list, chip: .today, filter: HomeFilter(), query: "", now: now, text: text)) == ["p"])
        // 00:30 Tashkent on the 8th: the 8th's request is "today", the 7th's is not.
        let lateNow = MarketFixture.at(2026, 10, 8, 0, 30)
        #expect(ids(HomeListingLogic.apply(list, chip: .today, filter: HomeFilter(), query: "", now: lateNow, text: text)) == ["x"])
    }

    @Test func searchIgnoresCaseAndApostrophes() {
        let list = HomeListingLogic.merge([("d", [item("a"), item("b")])])
        let names = ["a": "Chilonzor → Farg'ona", "b": "Sergeli → Buxoro"]
        let text: (HomeListing) -> String = { names[$0.id] ?? "" }
        #expect(ids(HomeListingLogic.apply(list, chip: .all, filter: HomeFilter(), query: "fargona", now: now, text: text)) == ["a"])
        #expect(ids(HomeListingLogic.apply(list, chip: .all, filter: HomeFilter(), query: "BUX", now: now, text: text)) == ["b"])
        #expect(ids(HomeListingLogic.apply(list, chip: .all, filter: HomeFilter(), query: "  ", now: now, text: text)) == ["a", "b"])
    }

    @Test func exactOnlyAndMinimumPrice() {
        let list = HomeListingLogic.merge([("d", [
            item("cheap", unit: 9_000_000), item("mid", match: .onRoute, unit: 12_000_000), item("dear", unit: 16_000_000),
        ])])
        let text: (HomeListing) -> String = { $0.id }
        var filter = HomeFilter()
        filter.exactOnly = true
        #expect(ids(HomeListingLogic.apply(list, chip: .all, filter: filter, query: "", now: now, text: text)) == ["cheap", "dear"])
        filter = HomeFilter()
        filter.minPrice = .from100k
        #expect(ids(HomeListingLogic.apply(list, chip: .all, filter: filter, query: "", now: now, text: text)) == ["mid", "dear"])
        filter.minPrice = .from150k
        #expect(ids(HomeListingLogic.apply(list, chip: .all, filter: filter, query: "", now: now, text: text)) == ["dear"])
    }

    @Test func sortsByDateCheapOrDearKeepingTheServerOrderOnTies() {
        let list = HomeListingLogic.merge([("d", [
            item("late", start: MarketFixture.at(2026, 10, 9, 9), unit: 10_000_000),
            item("soon", start: MarketFixture.at(2026, 10, 7, 9), unit: 20_000_000),
            item("tie", start: MarketFixture.at(2026, 10, 9, 9), unit: 10_000_000),
        ])])
        #expect(ids(HomeListingLogic.sorted(list, by: .nearest)) == ["soon", "late", "tie"])
        #expect(ids(HomeListingLogic.sorted(list, by: .cheap)) == ["late", "tie", "soon"])
        #expect(ids(HomeListingLogic.sorted(list, by: .expensive)) == ["soon", "late", "tie"])
    }

    @Test func filterCountAndEmptyLine() {
        var filter = HomeFilter()
        #expect(filter.activeCount == 0)
        #expect(filter.period == .days14)
        #expect(HomeListingLogic.emptyKey(query: "", filter: filter) == "driver.v3reg.emptyCategory")
        #expect(HomeListingLogic.emptyKey(query: "qarshi", filter: filter) == "driver.v3reg.emptyFiltered")
        filter.period = .today
        filter.sort = .cheap
        filter.minPrice = .from100k
        filter.exactOnly = true
        #expect(filter.activeCount == 4)
        #expect(HomeListingLogic.emptyKey(query: "", filter: filter) == "driver.v3reg.emptyFiltered")
    }

    @Test func perPersonShowsTheUnitPriceElseTheTotal() {
        let people = item("x", service: .passenger, unit: 15_000_000, basis: .perSeat, quantity: 2).listing
        #expect(HomeListingLogic.perPerson(people))
        #expect(HomeListingLogic.shownPriceMinor(people) == 15_000_000)
        let parcel = item("p", unit: 12_000_000).listing
        #expect(!HomeListingLogic.perPerson(parcel))
        #expect(HomeListingLogic.shownPriceMinor(parcel) == 12_000_000)
    }

    @Test func greetingUsesTheFirstWordOfTheName() {
        #expect(HomeListingLogic.firstName("Jasur Toshmatov") == "Jasur")
        #expect(HomeListingLogic.firstName("  Dilnoza  ") == "Dilnoza")
        #expect(HomeListingLogic.firstName("") == nil)
        #expect(HomeListingLogic.firstName(nil) == nil)
    }

    @Test func sealFollowsTheDerivedState() {
        #expect(HomeSeal.of(.approved) == .approved)
        #expect(HomeSeal.of(.incomplete) == .pending)
        #expect(HomeSeal.of(.review) == .pending)
        #expect(HomeSeal.of(.rejected) == .decided)
        #expect(HomeSeal.of(.blocked) == .decided)
        #expect(HomeSeal.approved.tone == .ok && HomeSeal.pending.tone == .warn && HomeSeal.decided.tone == .err)
        #expect(HomeSeal.approved.toastKey == "driver.v3reg.badgeApproved")
        #expect(HomeSeal.pending.toastKey == "driver.v3reg.badgePending")
        // A decided account hears its own word ("Rad etildi"), never "kutilmoqda".
        #expect(HomeSeal.decided.toastKey == nil)
    }

    @Test func kindIconFollowsServiceAndParcelType() {
        #expect(ListingKindIcon.of(item("x", service: .passenger).listing) == .user)
        var listing = item("p").listing
        #expect(ListingKindIcon.of(listing) == .pkg)
        listing.parcelType = .documents
        #expect(ListingKindIcon.of(listing) == .env)
        listing.parcelType = .bag
        #expect(ListingKindIcon.of(listing) == .bag)
    }
}

struct TripDetailRulesTests {
    private func stretch(_ from: Int, _ to: Int, seats: Int = 3, kg: Int = 20_000) -> StretchAvailabilityDTO {
        StretchAvailabilityDTO(baggageRemainingMl: 0, cargoRemainingVolumeMl: 100_000, cargoRemainingWeightG: kg, fromM: from, seatsRemaining: seats, toM: to)
    }

    @Test func zeroLengthStretchesMergeIntoTheirNeighbour() {
        // 0–0 km (under 500 m) then 0–120 km then 120–120 km: two rows would print "0–0" and "120–120" - never.
        let rows = TripDetailRules.rows([stretch(0, 300, seats: 2), stretch(300, 120_400), stretch(120_400, 512_000), stretch(512_000, 512_300, seats: 1)],
                                        startM: 0)
        #expect(rows.map { "\($0.fromKm ?? -1)-\($0.toKm ?? -1)" } == ["0-120", "120-512"])
        // The merged row keeps the tighter capacity.
        #expect(rows[0].stretch?.seatsRemaining == 2)
        #expect(rows[1].stretch?.seatsRemaining == 1)
        #expect(!rows.contains { $0.fromKm == $0.toKm })
    }

    @Test func oneStretchIsTheWholeRoad() {
        let rows = TripDetailRules.rows([stretch(0, 300), stretch(300, 800)], startM: 0)
        #expect(rows.count == 1)
        #expect(rows[0].fromKm == nil && rows[0].toKm == nil)
        #expect(rows[0].stretch?.toM == 800)
    }

    @Test func stretchesBeforeTheTripStartAreFolded() {
        let rows = TripDetailRules.rows([stretch(10_000, 30_000), stretch(30_000, 90_000), stretch(90_000, 150_000)], startM: 30_000)
        #expect(rows.map { "\($0.fromKm ?? -1)-\($0.toKm ?? -1)" } == ["0-60", "60-120"])
    }

    @Test func anEmptyTripShowsItsOwnCapacity() {
        let trip = MarketFixture.trip()
        let whole = TripDetailRules.wholeTrip(trip)
        #expect(whole.seatsRemaining == trip.seatCapacity)
        #expect(whole.cargoRemainingWeightG == trip.cargoCapacityWeightG)
        #expect(whole.cargoRemainingVolumeMl == trip.cargoCapacityVolumeMl)
    }

    @Test func titleIsTheFirstAndLastPlaceElseNothing() {
        #expect(TripDetailRules.placesTitle(["Chilonzor", "Yunusobod", "Qarshi"]) == "Chilonzor → Qarshi")
        #expect(TripDetailRules.placesTitle(["Chilonzor"]) == "Chilonzor")
        #expect(TripDetailRules.placesTitle(["", ""]) == nil)
        #expect(TripDetailRules.placesTitle([]) == nil)
    }
}
