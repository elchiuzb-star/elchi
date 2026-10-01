import Foundation
import Testing
@testable import Elchi

/// Stage 08 pure logic: trip next action and pause / resume / cancel availability, the add-trip payload, the feed query
/// (ends, date chips -> Tashkent bounds), feed groups and the alternative's reason, the pickup window, the offer body
/// (stop vs point listings), the rival board summary, the driver's turn -> allowed actions and revisions left, expiry
/// text, terms version for accept, and error -> sentence.
enum MarketFixture {
    static let tz = TimeZone(identifier: "Asia/Tashkent")!

    /// A Tashkent wall-clock instant.
    static func at(_ y: Int, _ mo: Int, _ d: Int, _ h: Int, _ mi: Int = 0) -> Date {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = tz
        return calendar.date(from: DateComponents(year: y, month: mo, day: d, hour: h, minute: mi))!
    }

    static func iso(_ date: Date) -> String { DepartureWindow.iso(date) }

    static func stop(_ id: String, _ name: String) -> StopRefDTO { StopRefDTO(id: id, nameRu: nil, nameUz: name) }

    static func trip(id: String = "trp_1", status: TripStatus = .planned, start: Date = at(2026, 10, 2, 8), cutoff: Date? = nil,
                     stops: [(String, String, TimeInterval)] = [("stp_a", "Toshkent", 0), ("stp_b", "Samarqand", 5 * 3600), ("stp_c", "Qarshi", 8 * 3600)],
                     version: Int = 1) -> TripDTO {
        TripDTO(baggageCapacityMl: 0, bookingCutoffAt: iso(cutoff ?? start), cargoCapacityVolumeMl: 100_000, cargoCapacityWeightG: 20_000,
                createdAt: iso(start.addingTimeInterval(-86_400)), detourUsedM: 0, detourUsedMinutes: 0, detourUsedS: 0, id: id, listings: [],
                maxDetourM: 5000, maxDetourMinutes: 15, pickupWaitMinutes: 10, plannedEndAt: iso(start.addingTimeInterval(stops.last?.2 ?? 0)),
                plannedStartAt: iso(start), routeVersionId: "rtv_1", seatCapacity: 3, status: status,
                stops: stops.enumerated().map { index, stop in
                    TripStopDTO(dwellMinutes: 5, plannedArrivalAt: iso(start.addingTimeInterval(stop.2)), seq: index + 1, stop: self.stop(stop.0, stop.1))
                },
                timezone: "Asia/Tashkent", vehicle: TripVehicleDTO(color: "Oq", id: "veh_1", makeModel: "Cobalt", plateMasked: "01****KA", seatCapacity: 4),
                version: version)
    }

    static func listing(id: String = "lst_1", originStop: StopRefDTO? = nil, destinationStop: StopRefDTO? = nil,
                        start: Date = at(2026, 10, 2, 9), end: Date = at(2026, 10, 2, 18), basis: PriceBasis = .total, quantity: Int = 1,
                        service: ServiceType = .parcel, unit: Int = 12_000_000) -> ListingPublicDTO {
        let point = { (district: String) in PointEndDTO(address: "Amir Temur ko'chasi, 2", district: DistrictRefDTO(id: "dst_\(district)", nameUz: district),
                                                        lat: 41.3, lng: 69.2) }
        return ListingPublicDTO(currency: .uzs, departureWindowEnd: iso(end), departureWindowStart: iso(start),
                                destinationPoint: destinationStop == nil ? point("Samarqand") : nil, destinationStop: destinationStop, id: id,
                                kind: .request, originPoint: originStop == nil ? point("Toshkent shahri") : nil, originStop: originStop,
                                priceBasis: basis, quantity: quantity, serviceType: service, status: .published, timezone: "Asia/Tashkent",
                                totalMinor: basis == .perSeat ? unit * quantity : unit, unitPriceMinor: unit)
    }

    static func feedItem(_ id: String, group: MatchGroup = .primary, reasons: [MatchReason] = [.intermediateSegment]) -> FeedItemDTO {
        FeedItemDTO(group: group, labels: [], listing: listing(id: id), match: FeedMatchDTO(matchType: group == .alternative ? .alternative : .onRoute, reasons: reasons),
                    readyToAccept: true, reputation: FeedReputationDTO(completedBookings: 0, label: .newVerified, ratingCount: 0))
    }

    static func version(author: ActorSide, status: ProposalStatus = .active, revision: Int = 1, expires: Date = Date().addingTimeInterval(3600),
                        driverLeft: Int = 3, total: Int = 12_000_000) -> ProposalVersionDTO {
        ProposalVersionDTO(authorSide: author, createdAt: iso(Date()), currency: .uzs,
                           demand: ProposalDemandDTO(baggageMl: 0, cargoVolumeMl: 12_000, cargoWeightG: 5000), expiresAt: iso(expires), id: "prv_\(revision)", listingTermsVersion: 2,
                           pickupWindowEnd: iso(at(2026, 10, 2, 10)), pickupWindowStart: iso(at(2026, 10, 2, 9)), priceBasis: .total,
                           priceRevisionsLeft: PriceRevisionsLeftDTO(client: 3, driver: driverLeft), quantity: 1, revision: revision, status: status,
                           totalMinor: total, unitPriceMinor: total)
    }

    static func thread(_ version: ProposalVersionDTO?, state: String = "open", booking: String? = nil, terms: Int = 2) -> ProposalThreadDTO {
        ProposalThreadDTO(bookingId: booking, client: ProposalPartyDTO(label: "Mijoz", side: .client), currentVersion: version,
                          driver: ProposalPartyDTO(label: "Haydovchi #1", side: .driver), id: "prp_1", listingId: "lst_1", listingTermsVersion: terms, state: state)
    }

    static func offer(_ label: String, total: Int, mine: Bool = false) -> ListingOfferDTO {
        ListingOfferDTO(currency: .uzs, isMine: mine, label: label, pickupWindowEnd: iso(at(2026, 10, 2, 10)), pickupWindowStart: iso(at(2026, 10, 2, 9)),
                        priceBasis: .total, quantity: 1, revision: 1, seatCapacity: 4, totalMinor: total, unitPriceMinor: total,
                        updatedAt: iso(Date()), vehicleClass: "car")
    }

    static func vehicle(seats: Int = 4, grams: Int? = 20_000, millilitres: Int? = 100_000) -> VehicleDTO {
        VehicleDTO(cargoMaxVolumeMl: millilitres, cargoMaxWeightG: grams, color: "Oq", createdAt: "2026-09-30T10:00:00Z", documentFileIds: [],
                   id: "veh_1", makeModel: "Cobalt", plateMasked: "01****KA", plateNumber: "01A452KA", seatCapacity: seats,
                   verificationStatus: "approved", version: 1)
    }

    static let route = RouteVersionDTO(attribution: "", distanceM: 512_463, durationS: 30_748, geometryPolyline: "", id: "rtv_1", isEstimate: true,
                                       provider: "fake", providerVersion: "1", status: "confirmed",
                                       stops: [RouteVersionStopDTO(cumulativeDistanceM: 0, cumulativeDurationS: 0, seq: 0, stopId: "stp_a"),
                                               RouteVersionStopDTO(cumulativeDistanceM: 328_214, cumulativeDurationS: 19_693, seq: 1, stopId: "stp_b"),
                                               RouteVersionStopDTO(cumulativeDistanceM: 512_463, cumulativeDurationS: 30_748, seq: 2, stopId: "stp_c")])

    static func error(_ code: String, _ details: [String: JSONValue]? = nil, status: Int = 409) -> APIError {
        APIError(status: status, code: code, message: "", details: details.map { .object($0) })
    }
}

struct TripActionsTests {
    @Test func nextActionFollowsTheWeb() {
        #expect(TripActions.of(.planned).next == .startBoarding)
        #expect(TripActions.of(.boarding).next == .depart)
        #expect(TripActions.of(.inProgress).next == .complete)
        #expect(TripActions.of(.interrupted).next == nil)
        #expect(TripActions.of(.completed).next == nil)
        #expect(TripActions.of(.cancelled).next == nil)
    }

    @Test func pauseResumeCancelAvailability() {
        #expect(!TripActions.of(.planned).canPause && TripActions.of(.planned).canCancel)
        #expect(TripActions.of(.boarding).canPause && TripActions.of(.boarding).canCancel)
        #expect(TripActions.of(.inProgress).canPause && !TripActions.of(.inProgress).canCancel)
        #expect(TripActions.of(.interrupted).canResume && TripActions.of(.interrupted).canCancel && !TripActions.of(.interrupted).canPause)
        let done = TripActions.of(.completed)
        #expect(!done.canPause && !done.canResume && !done.canCancel)
    }

    @Test func commandWordsAndReasons() {
        #expect(TripCommand.startBoarding.labelKey == "tripAction.start_boarding")
        #expect(TripCommand.interrupt.labelKey == "driver.trip.pause")
        #expect(TripCommand.resume.labelKey == "driver.trip.resume")
        #expect(TripCommand.cancel.labelKey == "driver.trip.cancel")
        #expect(TripCommand.cancel.needsReason && TripCommand.interrupt.needsReason && TripCommand.resume.needsReason)
        #expect(!TripCommand.depart.needsReason)
    }

    @Test func statusTones() {
        #expect(TripStatusStyle.tone(.planned) == .ok && TripStatusStyle.tone(.boarding) == .ok)
        #expect(TripStatusStyle.tone(.inProgress) == .blue)
        #expect(TripStatusStyle.tone(.interrupted) == .warn)
        #expect(TripStatusStyle.tone(.completed) == .gray && TripStatusStyle.tone(.cancelled) == .gray)
    }

    @Test func activeFirstThenHistoryNewestFirst() {
        let old = MarketFixture.trip(id: "a", status: .completed, start: MarketFixture.at(2026, 9, 20, 8))
        let newer = MarketFixture.trip(id: "b", status: .cancelled, start: MarketFixture.at(2026, 9, 25, 8))
        let later = MarketFixture.trip(id: "c", status: .planned, start: MarketFixture.at(2026, 10, 5, 8))
        let sooner = MarketFixture.trip(id: "d", status: .boarding, start: MarketFixture.at(2026, 10, 2, 8))
        let sections = TripList.sections([old, later, newer, sooner])
        #expect(sections.active.map(\.id) == ["d", "c"])
        #expect(sections.history.map(\.id) == ["b", "a"])
    }

    @Test func offerableTripsArePlannedWithCutoffAhead() {
        let now = MarketFixture.at(2026, 10, 1, 12)
        let past = MarketFixture.trip(id: "past", start: MarketFixture.at(2026, 10, 1, 10))
        let ahead = MarketFixture.trip(id: "ahead", start: MarketFixture.at(2026, 10, 2, 8))
        let boarding = MarketFixture.trip(id: "boarding", status: .boarding, start: MarketFixture.at(2026, 10, 2, 8))
        #expect(TripList.offerable([past, ahead, boarding], now: now).map(\.id) == ["ahead"])
    }

    @Test func boardingWindowRefusalSaysWhenItOpens() {
        let error = MarketFixture.error("INVALID_STATE_TRANSITION", ["reason": .string("boarding_window_not_open"),
                                                                     "opens_at": .string("2026-10-02T02:00:00+00:00")])
        #expect(TripRefusal.of(error) == .windowOpensAt(MarketFixture.at(2026, 10, 2, 7)))
        #expect(TripRefusal.of(MarketFixture.error("TRIP_HAS_UNRESOLVED_BOOKINGS")) == .unresolvedBookings)
        #expect(TripRefusal.of(MarketFixture.error("VERSION_CONFLICT")).refreshes)
        #expect(TripRefusal.of(MarketFixture.error("INVALID_STATE_TRANSITION")) == .other)
    }
}

struct TripPlanTests {
    let start = MarketFixture.at(2026, 10, 2, 7, 30)

    var form: TripPlanForm {
        TripPlanForm(vehicleId: "veh_1", corridorId: "cor_1", routeId: "rtv_1", start: start, seats: "3", cargoKg: "20", cargoLitres: "100")
    }

    @Test func bodyCarriesStopsTimesAndUnits() throws {
        let body = try #require(TripPlan.body(form, route: MarketFixture.route))
        #expect(body.vehicleId == "veh_1" && body.routeVersionId == "rtv_1")
        #expect(body.plannedStartAt == "2026-10-02T07:30:00+05:00")
        #expect(body.plannedEndAt == DepartureWindow.iso(start.addingTimeInterval(30_748)))
        #expect(body.stops.map(\.seq) == [1, 2, 3])
        #expect(body.stops.map(\.stopId) == ["stp_a", "stp_b", "stp_c"])
        #expect(body.stops[1].plannedArrivalAt == DepartureWindow.iso(start.addingTimeInterval(19_693)))
        #expect(body.stops.allSatisfy { $0.dwellMinutes == 5 })
        #expect(body.cargoCapacityWeightG == 20_000 && body.cargoCapacityVolumeMl == 100_000)
        #expect(body.maxDetourMinutes == 15 && body.maxDetourM == 5000 && body.pickupWaitMinutes == 10)
        #expect(body.bookingCutoffAt == nil)
        #expect(body.seatCapacity == 3)
    }

    @Test func noBodyWhileSomethingIsMissing() {
        var missing = form
        missing.start = nil
        #expect(TripPlan.body(missing, route: MarketFixture.route) == nil)
        var other = form
        other.routeId = "rtv_other"
        #expect(TripPlan.body(other, route: MarketFixture.route) == nil)
    }

    @Test func prefillFromVehicle() {
        let values = TripPlan.prefill(MarketFixture.vehicle(seats: 4, grams: 75_000, millilitres: 388_000))
        #expect(values.seats == "4" && values.cargoKg == "75" && values.cargoLitres == "388")
        #expect(TripPlan.prefill(MarketFixture.vehicle(grams: nil, millilitres: nil)).cargoKg == "0")
    }

    @Test func problemsAgainstTheVehicleAndTheClock() {
        let vehicle = MarketFixture.vehicle()
        let now = MarketFixture.at(2026, 10, 1, 12)
        #expect(TripPlan.problems(form, vehicle: vehicle, now: now).isEmpty)
        var over = form
        over.seats = "5"
        over.cargoKg = "21"
        over.cargoLitres = "abc"
        let problems = TripPlan.problems(over, vehicle: vehicle, now: now)
        #expect(problems[.seats] == .overLimit(4))
        #expect(problems[.cargoKg] == .overLimit(20))
        #expect(problems[.cargoLitres] == .notNumber)
        var past = form
        past.start = MarketFixture.at(2026, 10, 1, 11)
        #expect(TripPlan.problems(past, vehicle: vehicle, now: now)[.start] == .past)
        var empty = form
        empty.seats = "0"
        empty.cargoKg = "0"
        empty.cargoLitres = "0"
        #expect(TripPlan.problems(empty, vehicle: vehicle, now: now)[.seats] == .nothingOffered)
        var parcelsOnly = form
        parcelsOnly.seats = "0"
        #expect(TripPlan.problems(parcelsOnly, vehicle: vehicle, now: now).isEmpty)
        #expect(TripPlan.problems(TripPlanForm(), vehicle: nil, now: now)[.vehicle] == .required)
    }

    @Test func routeFiguresAndStopFilter() {
        let figures = TripPlan.figures(MarketFixture.route)
        #expect(figures.stops == 3 && figures.km == 512 && figures.hours == 9)
        #expect(TripPlan.routesThrough([MarketFixture.route], stopId: "stp_b").count == 1)
        #expect(TripPlan.routesThrough([MarketFixture.route], stopId: "stp_x").isEmpty)
        #expect(TripPlan.routesThrough([MarketFixture.route], stopId: nil).count == 1)
    }

    @Test func vehicleRefusalMarksTheField() {
        let seats = MarketFixture.error("VEHICLE_NOT_ELIGIBLE", ["field": .string("seat_capacity"), "requested": .number(5), "vehicle_limit": .number(4)])
        #expect(TripPlan.refusedField(seats)?.field == .seats && TripPlan.refusedField(seats)?.limit == 4)
        let kg = MarketFixture.error("VEHICLE_NOT_ELIGIBLE", ["field": .string("cargo_capacity_weight_g"), "vehicle_limit": .number(20_000)])
        #expect(TripPlan.refusedField(kg)?.field == .cargoKg && TripPlan.refusedField(kg)?.limit == 20)
        #expect(TripPlan.refusedField(MarketFixture.error("VEHICLE_NOT_ELIGIBLE", ["verification_status": .string("pending")])) == nil)
    }
}

struct FeedQueryTests {
    let now = MarketFixture.at(2026, 10, 1, 23, 30)
    let origin = FeedEnd(regionId: "reg_tsh", regionName: "Toshkent shahri")
    let destination = FeedEnd(regionId: "reg_sam", regionName: "Samarqand viloyati", districtId: "dst_sam", districtName: "Samarqand")

    @Test func chipsAreTashkentDays() {
        let today = FeedDateChip.today.range(now: now)
        #expect(DepartureWindow.iso(today.from) == "2026-10-01T00:00:00+05:00")
        #expect(DepartureWindow.iso(today.to) == "2026-10-02T00:00:00+05:00")
        let tomorrow = FeedDateChip.tomorrow.range(now: now)
        #expect(DepartureWindow.iso(tomorrow.from) == "2026-10-02T00:00:00+05:00" && DepartureWindow.iso(tomorrow.to) == "2026-10-03T00:00:00+05:00")
        #expect(DepartureWindow.iso(FeedDateChip.three.range(now: now).to) == "2026-10-04T00:00:00+05:00")
        #expect(DepartureWindow.iso(FeedDateChip.fourteen.range(now: now).to) == "2026-10-15T00:00:00+05:00")
        // 23:30 Tashkent is 18:30 UTC the same day; a phone in another zone must not shift the day.
        #expect(DepartureWindow.iso(FeedDateChip.today.range(now: MarketFixture.at(2026, 10, 2, 0, 30)).from) == "2026-10-02T00:00:00+05:00")
    }

    @Test func oneIdPerEnd() throws {
        let query = try #require(FeedQuery.make(FeedFilter(origin: origin, destination: destination, chip: .three), passengerAllowed: false, now: now))
        #expect(query.originRegionId == "reg_tsh" && query.originDistrictId == nil)
        #expect(query.destinationRegionId == nil && query.destinationDistrictId == "dst_sam")
        #expect(query.serviceType == .parcel)
        #expect(query.dateFrom == "2026-10-01T00:00:00+05:00" && query.dateTo == "2026-10-04T00:00:00+05:00")
    }

    @Test func noQueryWithoutBothEnds() {
        #expect(FeedQuery.make(FeedFilter(origin: origin), passengerAllowed: true, now: now) == nil)
        #expect(FeedFilter().chip == .fourteen)
    }

    @Test func passengerOnlyWhenTheFlagAllows() {
        let filter = FeedFilter(passenger: true, origin: origin, destination: destination)
        #expect(FeedQuery.make(filter, passengerAllowed: true, now: now)?.serviceType == .passenger)
        #expect(FeedQuery.make(filter, passengerAllowed: false, now: now)?.serviceType == .parcel)
    }

    @Test func filterSurvivesEncoding() throws {
        let filter = FeedFilter(passenger: false, origin: origin, destination: destination, chip: .tomorrow)
        let data = try JSONEncoder().encode(filter)
        #expect(try JSONDecoder().decode(FeedFilter.self, from: data) == filter)
    }

    @Test func savedRouteBody() throws {
        let body = try #require(SavedRoute.body(FeedFilter(origin: origin, destination: destination), passengerAllowed: false, now: now))
        #expect(body.side == .requests && body.notify == true && body.quantity == 1 && body.serviceType == .parcel)
        #expect(body.originRegionId == "reg_tsh" && body.destinationDistrictId == "dst_sam" && body.destinationRegionId == nil)
        #expect(body.timeWindowStart == DepartureWindow.iso(now) && body.timeWindowEnd == DepartureWindow.iso(now.addingTimeInterval(14 * 86_400)))
    }
}

struct FeedGroupsTests {
    @Test func alternativesAreNeverMixedIn() {
        let items = [MarketFixture.feedItem("a"), MarketFixture.feedItem("b", group: .alternative, reasons: [.nearbyStop]),
                     MarketFixture.feedItem("c", group: .unknown("future")), MarketFixture.feedItem("d", group: .alternative, reasons: [.timeDiffers])]
        let groups = FeedGroups.split(items)
        #expect(groups.primary.map(\.listing.id) == ["a", "c"])
        #expect(groups.alternative.map(\.listing.id) == ["b", "d"])
    }

    @Test func timeDiffersWins() {
        #expect(FeedGroups.alternativeReason([.nearbyStop, .timeDiffers]) == .timeDiffers)
        #expect(FeedGroups.alternativeReason([.nearbyStop]) == .nearbyStop)
        #expect(FeedGroups.alternativeReason([.intermediateSegment]) == nil)
    }

    @Test func pagesDoNotRepeat() {
        let merged = FeedGroups.appending([MarketFixture.feedItem("b"), MarketFixture.feedItem("c")], to: [MarketFixture.feedItem("a"), MarketFixture.feedItem("b")])
        #expect(merged.map(\.listing.id) == ["a", "b", "c"])
    }
}

struct OfferTests {
    @Test func pickupWindowAroundTheStopClippedToTheRequest() throws {
        // Trip at 08:00 reaches Samarqand at 13:00; request 09:00-18:00 -> 12:30-13:30.
        let trip = MarketFixture.trip(start: MarketFixture.at(2026, 10, 2, 8))
        let listing = MarketFixture.listing(originStop: MarketFixture.stop("stp_b", "Samarqand"), destinationStop: MarketFixture.stop("stp_c", "Qarshi"))
        let window = try #require(PickupWindow.of(trip: trip, listing: listing))
        #expect(window.start == MarketFixture.at(2026, 10, 2, 12, 30) && window.end == MarketFixture.at(2026, 10, 2, 13, 30))
        // Clipped: the request ends at 13:10.
        let tight = MarketFixture.listing(originStop: MarketFixture.stop("stp_b", "Samarqand"), end: MarketFixture.at(2026, 10, 2, 13, 10))
        #expect(PickupWindow.of(trip: trip, listing: tight)?.end == MarketFixture.at(2026, 10, 2, 13, 10))
        // The trip does not pass the stop, or arrives outside the window.
        #expect(PickupWindow.of(trip: trip, listing: MarketFixture.listing(originStop: MarketFixture.stop("stp_x", "Buxoro"))) == nil)
        let late = MarketFixture.listing(originStop: MarketFixture.stop("stp_c", "Qarshi"), end: MarketFixture.at(2026, 10, 2, 12))
        #expect(PickupWindow.of(trip: trip, listing: late) == nil)
    }

    @Test func pointListingsUseTheClientsWindow() throws {
        let listing = MarketFixture.listing()
        let window = try #require(PickupWindow.of(trip: MarketFixture.trip(), listing: listing))
        #expect(window.start == MarketFixture.at(2026, 10, 2, 9) && window.end == MarketFixture.at(2026, 10, 2, 18))
    }

    @Test func preselectTheTripThatFits() {
        let listing = MarketFixture.listing()
        let early = MarketFixture.trip(id: "early", start: MarketFixture.at(2026, 9, 30, 8))
        let fits = MarketFixture.trip(id: "fits", start: MarketFixture.at(2026, 10, 2, 7))
        #expect(PickupWindow.preselect([early, fits], listing: listing)?.id == "fits")
        #expect(PickupWindow.preselect([early], listing: listing) == nil)
    }

    @Test func bodyForPointAndStopListings() {
        let window = (MarketFixture.at(2026, 10, 2, 9), MarketFixture.at(2026, 10, 2, 10))
        let point = OfferBody.make(listing: MarketFixture.listing(), tripId: "trp_1", window: window, unitPriceMinor: 11_000_000, message: "  ")
        #expect(point.pickupStopId == nil && point.dropoffStopId == nil)
        #expect(point.tripId == "trp_1" && point.quantity == 1 && point.priceBasis == .total && point.unitPriceMinor == 11_000_000)
        #expect(point.pickupWindowStart == "2026-10-02T09:00:00+05:00" && point.pickupWindowEnd == "2026-10-02T10:00:00+05:00")
        #expect(point.message == nil)
        let stops = OfferBody.make(listing: MarketFixture.listing(originStop: MarketFixture.stop("stp_a", "A"), destinationStop: MarketFixture.stop("stp_b", "B")),
                                   tripId: "trp_1", window: window, unitPriceMinor: 1, message: "Salom")
        #expect(stops.pickupStopId == "stp_a" && stops.dropoffStopId == "stp_b" && stops.message == "Salom")
        // Only one end is a stop: neither is sent (both or neither).
        let half = OfferBody.make(listing: MarketFixture.listing(originStop: MarketFixture.stop("stp_a", "A")), tripId: "t", window: window, unitPriceMinor: 1)
        #expect(half.pickupStopId == nil && half.dropoffStopId == nil)
        let seats = OfferBody.make(listing: MarketFixture.listing(basis: .perSeat, quantity: 2, service: .passenger), tripId: "t", window: window, unitPriceMinor: 1)
        #expect(seats.quantity == 2 && seats.priceBasis == .perSeat)
    }

    @Test func totalsAndPercent() {
        #expect(OfferBody.totalMinor(listing: MarketFixture.listing(), unitPriceMinor: 500) == 500)
        #expect(OfferBody.totalMinor(listing: MarketFixture.listing(basis: .perSeat, quantity: 3), unitPriceMinor: 500) == 1500)
        #expect(OfferBody.totalMinor(listing: MarketFixture.listing(), unitPriceMinor: 0) == 0)
        #expect(OfferBody.percent(bps: 1500) == "15" && OfferBody.percent(bps: 750) == "7.5" && OfferBody.percent(bps: 825) == "8.25")
    }

    @Test func rivalBoardSummary() {
        let board = RivalBoard.of([MarketFixture.offer("Haydovchi #4", total: 125), MarketFixture.offer("Haydovchi #2", total: 120, mine: true),
                                   MarketFixture.offer("Haydovchi #1", total: 110)])
        #expect(board.count == 3 && board.cheapestMinor == 110)
        #expect(board.mine?.label == "Haydovchi #2")
        #expect(board.rivals.map(\.label) == ["Haydovchi #1", "Haydovchi #4"])
        let empty = RivalBoard.of([])
        #expect(empty.count == 0 && empty.cheapestMinor == nil && empty.mine == nil)
    }
}

struct DriverNegotiationTests {
    @Test func clientsCounterIsTheDriversTurn() {
        let actions = DriverNegotiation.of(MarketFixture.thread(MarketFixture.version(author: .client, driverLeft: 2)))
        #expect(actions.open && actions.driversTurn && actions.canAccept && actions.canReject && actions.canCounter && !actions.canWithdraw)
        #expect(actions.revisionsLeft == 2)
    }

    @Test func noCounterWithoutRevisionsLeft() {
        let actions = DriverNegotiation.of(MarketFixture.thread(MarketFixture.version(author: .client, driverLeft: 0)))
        #expect(actions.canAccept && !actions.canCounter)
    }

    @Test func ownVersionCanOnlyBeWithdrawn() {
        let actions = DriverNegotiation.of(MarketFixture.thread(MarketFixture.version(author: .driver)))
        #expect(actions.open && !actions.driversTurn && !actions.canAccept && !actions.canCounter && actions.canWithdraw)
    }

    @Test func closedByStateStatusOrClock() {
        #expect(!DriverNegotiation.of(MarketFixture.thread(MarketFixture.version(author: .client), state: "closed")).open)
        #expect(!DriverNegotiation.of(MarketFixture.thread(MarketFixture.version(author: .client, status: .superseded))).open)
        let expired = DriverNegotiation.of(MarketFixture.thread(MarketFixture.version(author: .client, expires: Date().addingTimeInterval(-5))))
        #expect(!expired.open && expired.expiredByClock && !expired.canAccept)
        #expect(!DriverNegotiation.of(MarketFixture.thread(nil)).open)
    }

    @Test func statusLines() {
        #expect(ProposalStatusLine.of(MarketFixture.thread(MarketFixture.version(author: .client))).key == "negotiation.clientCountered")
        #expect(ProposalStatusLine.of(MarketFixture.thread(MarketFixture.version(author: .client))).tone == .warn)
        #expect(ProposalStatusLine.of(MarketFixture.thread(MarketFixture.version(author: .driver))).key == "negotiation.waitingForAnswer")
        #expect(ProposalStatusLine.of(MarketFixture.thread(MarketFixture.version(author: .client, status: .accepted), state: "accepted",
                                                           booking: "bkg_1")).key == "client.amendment.statusAccepted")
        #expect(ProposalStatusLine.of(MarketFixture.thread(MarketFixture.version(author: .driver, status: .withdrawn), state: "closed")).key
                == "proposalStatus.withdrawn")
        #expect(ProposalStatusLine.of(MarketFixture.thread(MarketFixture.version(author: .driver, expires: Date().addingTimeInterval(-1)))).key
                == "proposalStatus.expired")
    }

    @Test func tabsUseExistingWords() {
        #expect(ProposalTab.allCases.map(\.rawValue) == ["open", "accepted", "closed"])
        #expect(ProposalTab.open.labelKey == "publicShare.open")
    }

    @Test func countdownRoundsUp() {
        let now = Date()
        #expect(Countdown.left(until: now.addingTimeInterval(72 * 60 - 20), now: now)! == (1, 12))
        #expect(Countdown.left(until: now.addingTimeInterval(-1), now: now) == nil)
    }
}

struct TermsVersionTests {
    @Test func threadCarriesTheListingTermsVersion() {
        let thread = MarketFixture.thread(MarketFixture.version(author: .client), terms: 3)
        #expect(thread.listingTermsVersion == 3)
        #expect(MarketFixture.thread(nil).listingTermsVersion == 2)
    }

    @Test func mismatchNamesTheCurrentVersion() {
        let error = MarketFixture.error("PROPOSAL_CHANGED", ["reason": .string("listing_terms_version_mismatch"), "current_listing_terms_version": .number(2)])
        #expect(ListingTerms.current(from: error) == 2)
        #expect(ListingTerms.current(from: MarketFixture.error("PROPOSAL_CHANGED", ["reason": .string("not_current_version")])) == nil)
    }
}

struct MarketErrorTextTests {
    @Test func sentences() {
        #expect(MarketErrorText.sentence(MarketFixture.error("TIME_WINDOW_CONFLICT")) == .key("driverBid.tripWindowMismatch", [:]))
        #expect(MarketErrorText.sentence(MarketFixture.error("SAVED_SEARCH_LIMIT_REACHED", ["limit": .number(10)])) == .key("error.SAVED_SEARCH_LIMIT_REACHED", [:]))
        #expect(MarketErrorText.sentence(MarketFixture.error("PROPOSAL_CHANGED", ["reason": .string("listing_terms_version_mismatch")]))
                == .key("client.listingBids.termsChanged", [:]))
        #expect(MarketErrorText.sentence(MarketFixture.error("PROPOSAL_CHANGED", ["reason": .string("demand_already_booked")]))
                == .key("client.listingBids.alreadyBooked", [:]))
        #expect(MarketErrorText.sentence(MarketFixture.error("BOOKING_CUTOFF_PASSED")) == .generic)
        #expect(MarketErrorText.sentence(URLError(.badURL)) == .generic)
    }

    @Test func openThreadOpensInstead() {
        let error = MarketFixture.error("INVALID_STATE_TRANSITION", ["reason": .string("open_thread_exists"), "thread_id": .string("prp_9")])
        #expect(MarketErrorText.openThread(error) == "prp_9")
        #expect(MarketErrorText.openThread(MarketFixture.error("INVALID_STATE_TRANSITION", ["reason": .string("open_thread_exists")])) == nil)
    }

    @MainActor @Test func pendingKeysHaveAFallback() {
        let strings = LocaleStore()
        let text = strings.marketErrorText(MarketFixture.error("SCHEDULE_CONFLICT"))
        #expect(!text.isEmpty && text != "SCHEDULE_CONFLICT")
        #expect(strings.tripRefusalText(MarketFixture.error("INVALID_STATE_TRANSITION", ["reason": .string("boarding_window_not_open"),
                                                                                          "opens_at": .string("2026-10-02T02:00:00+00:00")])).contains("07:00"))
    }
}
