import Foundation
import Testing
@testable import Elchi

/// ADR-0027 (driver directions): a port of the web's `directionFeed.test.ts` (grouping, day ranges, Tashkent clocks, end
/// names, the server answers the screens act on) plus the native-only rules - the add form's validation and body, the
/// offer body / idempotency action / outcome mapping, the time-proposal resend at the car's ETA, the client's
/// `outside_request_window` sentence, and the trip read by districts (Q158).
enum DirectionFixture {
    static func item(_ id: String, _ fit: String, eta: String? = nil, departure: String? = nil, thread: String? = nil) -> DirectionRequestItemDTO {
        DirectionRequestItemDTO(fit: fit, listing: MarketFixture.listing(id: id), matchType: .exact, myThreadId: thread, pickupEta: eta,
                                suggestedDepartureAt: departure)
    }

    static func end(region: String = "reg_1", regionUz: String = "Toshkent shahri", regionRu: String? = "г. Ташкент",
                    district: String? = nil, districtUz: String? = nil, districtRu: String? = nil) -> DirectionEndDTO {
        DirectionEndDTO(districtId: district, districtNameRu: districtRu, districtNameUz: districtUz, regionId: region, regionNameRu: regionRu,
                        regionNameUz: regionUz)
    }

    static func direction(_ id: String, status: String = "active") -> DriverDirectionDTO {
        DriverDirectionDTO(cargoCapacityVolumeMl: 100_000, cargoCapacityWeightG: 20_000, createdAt: "2026-10-06T08:00:00Z",
                           destination: end(region: "reg_2", regionUz: "Qashqadaryo viloyati", district: "dst_9", districtUz: "Qarshi", districtRu: "Карши"),
                           id: id, origin: end(), seatCapacity: 4, status: status, updatedAt: "2026-10-06T08:00:00Z", vehicleId: "veh_1", version: 1)
    }

    static func error(_ status: Int, _ code: String, _ details: [String: JSONValue]? = nil) -> APIError {
        APIError(status: status, code: code, message: "x", details: details.map { .object($0) })
    }

    static func region(_ id: String, requiresDistrict: Bool?) -> RegionDTO {
        RegionDTO(code: id, id: id, nameUz: id, requiresDistrict: requiresDistrict)
    }

    static func district(_ id: String, region: String) -> DistrictDTO {
        DistrictDTO(id: id, nameUz: id, region: RegionRefDTO(code: region, id: region, nameUz: region))
    }

    static func trip(created: Bool, retimed: Bool, start: String = "2026-10-06T17:04:13Z") -> DirectionOfferDTO {
        DirectionOfferDTO(thread: MarketFixture.thread(nil), timeProposal: false,
                          trip: DirectionTripRefDTO(id: "trp_1", plannedEndAt: start, plannedStartAt: start, seatsBooked: 0, status: .planned),
                          tripCreated: created, tripRetimed: retimed)
    }
}

struct DirectionFeedTests {
    @Test func groupsCutThePageIntoThreeAnswersAndKeepTheServerOrder() {
        let groups = DirectionFeed.groups([DirectionFixture.item("a", "no_trip"), DirectionFixture.item("b", "fits_trip"),
                                           DirectionFixture.item("c", "time_differs"), DirectionFixture.item("d", "fits_trip")])
        #expect(groups.fits.map(\.listing.id) == ["b", "d"])
        #expect(groups.fresh.map(\.listing.id) == ["a"])
        #expect(groups.otherTime.map(\.listing.id) == ["c"])
        #expect(DirectionFeed.groups([]).isEmpty)
    }

    private let now = ISO8601DateFormatter().date(from: "2026-10-06T08:30:00Z")! // 13:30 in Tashkent

    @Test func todayRunsFromNowToTashkentMidnight() {
        let range = DirectionFeed.range(.today, now: now)
        #expect(range.from == "2026-10-06T08:30:00.000Z")
        #expect(range.to == "2026-10-06T19:00:00.000Z")
    }

    @Test func tomorrowIsTheWholeNextTashkentDay() {
        let range = DirectionFeed.range(.tomorrow, now: now)
        #expect(range.from == "2026-10-06T19:00:00.000Z")
        #expect(range.to == "2026-10-07T19:00:00.000Z")
    }

    @Test func threeAndFourteenDays() {
        // Safar v3 5.3: "3 kun" = today and the next two Tashkent days; "14 kun" = exactly 14 days from now.
        #expect(DirectionFeed.range(.days3, now: now).from == "2026-10-06T08:30:00.000Z")
        #expect(DirectionFeed.range(.days3, now: now).to == "2026-10-08T19:00:00.000Z")
        #expect(DirectionFeed.range(.days14, now: now).to == "2026-10-20T08:30:00.000Z")
        #expect(DirectionFeedDay.allCases.map(\.labelKey) == ["dir.day.today", "dir.day.tomorrow", "driver.feed.date3", "driver.feed.date14"])
        // Late evening in Tashkent (00:30 next day local) still counts the local day.
        let late = ISO8601DateFormatter().date(from: "2026-10-06T19:30:00Z")!
        #expect(DirectionFeed.range(.today, now: late).to == "2026-10-07T19:00:00.000Z")
    }

    @Test func clocksAreTashkentWallTime() {
        #expect(DirectionFeed.clock("2026-10-06T17:04:13Z") == "22:04")
        #expect(DirectionFeed.clock("2026-10-06T17:04:13+00:00") == "22:04")
        #expect(DirectionFeed.clock(nil) == "-")
        #expect(DirectionFeed.dayClock("2026-10-06T19:30:00Z") == "07.10 00:30") // past midnight in Tashkent: the next day
    }

    @Test func endNamesTheDistrictOrTheCityRegion() {
        #expect(DirectionEndName.of(DirectionFixture.end(), ru: false) == "Toshkent shahri")
        #expect(DirectionEndName.of(DirectionFixture.end(), ru: true) == "г. Ташкент")
        let qarshi = DirectionFixture.end(district: "dst_1", districtUz: "Qarshi", districtRu: "Карши")
        #expect(DirectionEndName.of(qarshi, ru: true) == "Карши")
        #expect(DirectionEndName.of(qarshi, ru: false) == "Qarshi")
        #expect(DirectionEndName.route(DirectionFixture.direction("drd_1"), ru: false) == "Toshkent shahri → Qarshi")
    }

    @Test func pickKeepsTheChosenLiveDirectionElseTheFirstActive() {
        let list = [DirectionFixture.direction("a", status: "paused"), DirectionFixture.direction("b"), DirectionFixture.direction("c", status: "archived")]
        #expect(DirectionFeed.pick(list, current: "a") == "a")
        #expect(DirectionFeed.pick(list, current: "c") == "b") // archived is gone
        #expect(DirectionFeed.pick(list, current: nil) == "b")
        #expect(DirectionFeed.pick([DirectionFixture.direction("a", status: "paused")], current: nil) == "a")
        #expect(DirectionFeed.pick([], current: "x") == nil)
        #expect(DirectionFeed.live(list).map(\.id) == ["a", "b"])
    }

    @Test func passengerOnlyWhenTheFlagAllowsIt() {
        #expect(DirectionFeed.service(passengerAllowed: true, passenger: true) == .passenger)
        #expect(DirectionFeed.service(passengerAllowed: false, passenger: true) == .parcel)
        #expect(DirectionFeed.service(passengerAllowed: true, passenger: false) == .parcel)
    }
}

struct DirectionAnswerTests {
    @Test func readsTheCarsEtaFromATimeConflict() {
        let conflict = DirectionFixture.error(409, "TIME_WINDOW_CONFLICT", ["reason": .string("trip_time_differs"), "eta": .string("2026-10-06T17:04:13+00:00")])
        #expect(DirectionAnswer.timeProposalEta(conflict) == "2026-10-06T17:04:13+00:00")
        #expect(DirectionAnswer.timeProposalEta(DirectionFixture.error(409, "ROUTE_MISMATCH")) == nil)
        #expect(DirectionAnswer.timeProposalTooFar(conflict) == nil)
    }

    @Test func q157TooFarIsNotOfferedAsAProposal() {
        let far = DirectionFixture.error(409, "TIME_WINDOW_CONFLICT", ["eta": .string("2026-10-06T18:43:13+00:00"), "time_proposal_possible": .bool(false)])
        #expect(DirectionAnswer.timeProposalEta(far) == nil)
        #expect(DirectionAnswer.timeProposalTooFar(far).map { [$0.early, $0.late] } == [3, 12])
        let limits = DirectionFixture.error(409, "TIME_WINDOW_CONFLICT", ["reason": .string("time_proposal_too_far"), "max_early_minutes": .number(120),
                                                                          "max_late_minutes": .number(600)])
        #expect(DirectionAnswer.timeProposalTooFar(limits).map { [$0.early, $0.late] } == [2, 10])
    }

    @Test func tellsNoRoadDuplicateAndPassedPickupApart() {
        #expect(DirectionAnswer.isNoRoad(DirectionFixture.error(409, "ROUTE_MISMATCH", ["reason": .string("no_corridor_serves_direction")])))
        #expect(DirectionAnswer.isDuplicate(DirectionFixture.error(400, "VALIDATION_ERROR", ["reason": .string("direction_exists")])))
        #expect(!DirectionAnswer.isDuplicate(DirectionFixture.error(400, "VALIDATION_ERROR", ["reason": .string("district_required")])))
        #expect(DirectionAnswer.isPickupPassed(DirectionFixture.error(409, "BOOKING_CUTOFF_PASSED", ["reason": .string("pickup_passed")])))
        #expect(!DirectionAnswer.isPickupPassed(DirectionFixture.error(409, "BOOKING_CUTOFF_PASSED")))
    }
}

struct DirectionFormTests {
    @Test func bothEndsNeedARegionAndADistrictWhereTheRegionHasThem() {
        var form = DirectionForm()
        #expect(!form.ready)
        #expect(form.body == nil)
        form.origin = DirectionFormEnd(region: DirectionFixture.region("reg_city", requiresDistrict: false))
        #expect(form.origin.ready) // a city without districts is the whole city
        form.destination = DirectionFormEnd(region: DirectionFixture.region("reg_sam", requiresDistrict: true))
        #expect(!form.ready)
        form.destination.district = DirectionFixture.district("dst_toy", region: "reg_sam")
        #expect(form.ready)
        // Unknown `requires_district` counts as required (the server's default).
        #expect(!DirectionFormEnd(region: DirectionFixture.region("reg_x", requiresDistrict: nil)).ready)
    }

    @Test func theBodyIsTwoEndsAndNothingElse() throws {
        let form = DirectionForm(origin: DirectionFormEnd(region: DirectionFixture.region("reg_city", requiresDistrict: false)),
                                 destination: DirectionFormEnd(region: DirectionFixture.region("reg_sam", requiresDistrict: true),
                                                               district: DirectionFixture.district("dst_toy", region: "reg_sam")))
        let body = try #require(form.body)
        #expect(body.origin == DirectionEndInput(districtId: nil, regionId: "reg_city"))
        #expect(body.destination == DirectionEndInput(districtId: "dst_toy", regionId: "reg_sam"))
        #expect(body.vehicleId == nil && body.seatCapacity == nil && body.cargoCapacityWeightG == nil)
        let json = try #require(String(data: JSONEncoder().encode(body), encoding: .utf8))
        #expect(!json.contains("vehicle_id"))
        #expect(form.action == "direction.create:reg_city:-:reg_sam:dst_toy")
    }
}

struct DirectionOfferTests {
    @Test func theBodyCarriesPriceMessageAndProposedTimeOnly() {
        let plain = DirectionOffer.body(listingId: "lst_1", unitPriceMinor: 15_000_000, message: "  ", pickupAt: nil)
        #expect(plain == DirectionOfferCreate(listingId: "lst_1", message: nil, pickupAt: nil, unitPriceMinor: 15_000_000))
        let proposal = DirectionOffer.body(listingId: "lst_1", unitPriceMinor: 15_000_000, message: "Salom", pickupAt: "2026-10-06T17:04:13+00:00")
        #expect(proposal.pickupAt == "2026-10-06T17:04:13+00:00")
        #expect(proposal.message == "Salom")
    }

    @MainActor @Test func aRetryReusesTheKeyButATimeProposalIsANewRequest() {
        let plain = DirectionOffer.body(listingId: "lst_1", unitPriceMinor: 100, message: nil, pickupAt: nil)
        let again = DirectionOffer.body(listingId: "lst_1", unitPriceMinor: 100, message: "different text", pickupAt: nil)
        let proposal = DirectionOffer.body(listingId: "lst_1", unitPriceMinor: 100, message: nil, pickupAt: "2026-10-06T17:04:13+00:00")
        #expect(DirectionOffer.action(directionId: "drd_1", body: plain) == DirectionOffer.action(directionId: "drd_1", body: again))
        #expect(DirectionOffer.action(directionId: "drd_1", body: plain) != DirectionOffer.action(directionId: "drd_1", body: proposal))
        // The key store hands the same key back until the server answers for sure.
        let keys = ActionKeys()
        let action = DirectionOffer.action(directionId: "drd_1", body: plain)
        let first = keys.key(action)
        keys.settle(action, after: APIError(status: 0, code: APIError.network, message: "", details: nil))
        #expect(keys.key(action) == first)
        keys.settle(action)
        #expect(keys.key(action) != first)
    }

    @Test func proposedTimeComesFromTheConflictElseFromATimeDiffersRequest() {
        let differs = DirectionFixture.item("a", "time_differs", eta: "2026-10-06T17:00:00Z")
        let fits = DirectionFixture.item("b", "fits_trip", eta: "2026-10-06T09:00:00Z")
        #expect(DirectionOffer.proposeAt(item: differs, conflictEta: nil) == "2026-10-06T17:00:00Z")
        #expect(DirectionOffer.proposeAt(item: fits, conflictEta: nil) == nil)
        // The time-proposal resend uses `pickup_at = details.eta`.
        #expect(DirectionOffer.proposeAt(item: fits, conflictEta: "2026-10-06T17:04:13+00:00") == "2026-10-06T17:04:13+00:00")
    }

    @Test func outcomesMapToTheSentences() {
        let created = DirectionOffer.sentMessage(DirectionFixture.trip(created: true, retimed: false))
        #expect(created.key == "dir.bid.tripCreated" && created.time == "06.10 22:04")
        let retimed = DirectionOffer.sentMessage(DirectionFixture.trip(created: false, retimed: true))
        #expect(retimed.key == "dir.bid.tripRetimed" && retimed.time == "06.10 22:04")
        #expect(DirectionOffer.sentMessage(DirectionFixture.trip(created: false, retimed: false)).key == "driverBid.sent")
        #expect(DirectionOffer.sentMessage(DirectionFixture.trip(created: false, retimed: false)).time == nil)
    }

    @Test func refusalsMapToProposeTooFarPassedOrTheError() {
        let conflict = DirectionFixture.error(409, "TIME_WINDOW_CONFLICT", ["eta": .string("2026-10-06T17:04:13+00:00"), "time_proposal_possible": .bool(true)])
        if case .proposeTime(let eta) = DirectionOfferRefusal.of(conflict, hadPickupAt: false) { #expect(eta == "2026-10-06T17:04:13+00:00") } else { Issue.record("not proposeTime") }
        // A second conflict on a time proposal is an ordinary error, not a loop.
        if case .other = DirectionOfferRefusal.of(conflict, hadPickupAt: true) {} else { Issue.record("not other") }
        let far = DirectionFixture.error(409, "TIME_WINDOW_CONFLICT", ["reason": .string("time_proposal_too_far")])
        if case .tooFar(let early, let late) = DirectionOfferRefusal.of(far, hadPickupAt: false) { #expect(early == 3 && late == 12) } else { Issue.record("not tooFar") }
        let passed = DirectionFixture.error(409, "BOOKING_CUTOFF_PASSED", ["reason": .string("pickup_passed")])
        if case .passed = DirectionOfferRefusal.of(passed, hadPickupAt: false) {} else { Issue.record("not passed") }
        if case .other = DirectionOfferRefusal.of(DirectionFixture.error(409, "ROUTE_CHANGED"), hadPickupAt: false) {} else { Issue.record("not other") }
    }
}

@MainActor
struct DirectionClientTests {
    @Test func outsideRequestWindowSaysTheProposedTimeAndTheAskedWindow() {
        var version = MarketFixture.version(author: .driver)
        version.pickupWindowStart = "2026-10-06T17:30:00Z"
        #expect(TimeProposalLine.values(version, listingStart: "2026-10-06T08:00:00Z", listingEnd: "2026-10-06T10:00:00Z") == nil)
        version.outsideRequestWindow = true
        let values = TimeProposalLine.values(version, listingStart: "2026-10-06T08:00:00Z", listingEnd: "2026-10-06T10:00:00Z")
        let strings = LocaleStore()
        strings.set(.uz)
        #expect(strings.t("offer.timeProposal", values: values ?? [])
                == "Haydovchi 06.10 22:30 da olishni taklif qilmoqda (siz 06.10 13:00 – 15:00 so'ragansiz)")
        strings.set(.ru)
        #expect(strings.t("offer.timeProposal", values: values ?? []) == "Водитель предлагает забрать в 06.10 22:30 (вы просили 06.10 13:00 – 15:00)")
        strings.set(.uz)
    }

    @MainActor @Test func placesAreMarkedPointsNeverStops() {
        let strings = LocaleStore()
        strings.set(.uz)
        let point = PointEndDTO(address: "Bunyodkor ko'chasi 1", district: DistrictRefDTO(id: "dst_ch", nameUz: "Chilonzor"), lat: 41.28, lng: 69.2)
        // The feed and the lists: the district, never the street (Q100) - and no stop at all (ADR-0028).
        #expect(strings.feedEnd(point) == "Chilonzor")
        #expect(strings.endName(point) == "Chilonzor")
        // The booking detail / manifest: the agreed address, else the district.
        #expect(strings.endAddress(point) == "Bunyodkor ko'chasi 1")
        #expect(strings.placeText(point) == "Bunyodkor ko'chasi 1")
        let bare = PointEndDTO(district: DistrictRefDTO(id: "dst_q", nameUz: "Qarshi"), lat: 38.86, lng: 65.79)
        #expect(strings.placeText(bare) == "Qarshi" && strings.endAddress(bare) == "Qarshi")
        #expect(strings.placeText(nil) == strings.t("tripDetail.agreedPoint"))
    }

    @MainActor @Test func aTripIsNamedByItsDirectionElseItsTimes() {
        let strings = LocaleStore()
        strings.set(.uz)
        let trip = MarketFixture.trip(id: "trp_9", start: MarketFixture.at(2026, 10, 2, 8))
        #expect(strings.route(trip) == "02.10, 08:00 → 02.10, 16:00")
        let direction = DriverDirectionDTO(activeTrip: DirectionTripRefDTO(id: "trp_9", plannedEndAt: trip.plannedEndAt, plannedStartAt: trip.plannedStartAt,
                                                                           seatsBooked: 0, status: .planned),
                                           cargoCapacityVolumeMl: 0, cargoCapacityWeightG: 0, createdAt: trip.createdAt,
                                           destination: DirectionEndDTO(districtId: "dst_q", districtNameUz: "Qarshi", regionId: "reg_q", regionNameUz: "Qashqadaryo"),
                                           id: "drd_1", origin: DirectionEndDTO(regionId: "reg_t", regionNameUz: "Toshkent shahri"), seatCapacity: 4,
                                           status: "active", updatedAt: trip.createdAt, vehicleId: "veh_1", version: 1)
        #expect(strings.route(trip, directions: [direction]) == "Toshkent shahri → Qarshi")
    }

    @Test func theTripReadsAsDistrictsAlongTheRoad() {
        let names = ["Chilonzor", "Chilonzor", "Yangiyo'l", "Samarqand", "Samarqand", "Chilonzor"]
        let places = TripPlaces.alongTheRoad(Array(names.enumerated())) { $0.element }
        #expect(places.map(\.name) == ["Chilonzor", "Yangiyo'l", "Samarqand", "Chilonzor"])
        #expect(places.map(\.stop.offset) == [0, 2, 3, 5]) // the first of a run keeps its time
    }

    @Test func everyDirectionKeyIsInTheDictionary() {
        let strings = LocaleStore()
        let keys = ["dir.added", "dir.archive", "dir.archived", "dir.bid.planned", "dir.bid.proposeTime", "dir.bid.timeProposal", "dir.bid.tooFar",
                    "dir.bid.tripCreated", "dir.bid.tripRetimed", "dir.capacity", "dir.card.asked", "dir.card.departure", "dir.card.eta",
                    "dir.card.myOffer", "dir.day.today", "dir.day.tomorrow", "dir.day.week", "dir.district", "dir.districtPlaceholder",
                    "dir.districtSearch", "dir.exists", "dir.feedEmpty", "dir.feedPick", "dir.formHint", "dir.group.fits", "dir.group.fitsNote",
                    "dir.group.new", "dir.group.newNote", "dir.group.time", "dir.group.timeNote", "dir.noDirections", "dir.noDirectionsHint",
                    "dir.noRoad", "dir.noTrip", "dir.openRequests", "dir.passed", "dir.pause", "dir.paused", "dir.region", "dir.regionPlaceholder",
                    "dir.resume", "dir.save", "dir.statusActive", "dir.statusPaused", "dir.trip", "dir.tripsHint", "dir.tripsTitle", "dir.updated",
                    "dir.via", "dir.wholeCity", "offer.timeProposal", "tripDetail.stretchKm", "error.ROUTE_CHANGED", "match.confirmedRoadsNote"]
        for language in [AppLocale.uz, .ru] {
            strings.set(language)
            for key in keys { #expect(strings.tOrNil(key) != nil, "missing \(key)") }
        }
        strings.set(.uz)
    }
}
