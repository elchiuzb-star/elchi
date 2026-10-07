import Foundation
import Testing
@testable import Elchi

/// DESIGN07 (BOSQICH 07, driver trips / feed / saved routes / offers / negotiation): the feed's "already offered"
/// mark, the negotiation badge and sentence (with the driver's own counter), the counter's same-price check, the
/// saved-route state (already saved, limit) and open-in-feed, the departure's sentence, the home counts, the accept
/// -> booking chat decision, the trip tones, stop dots and the one-live-trip guard.
struct Design07Tests {
    private typealias F = MarketFixture

    private func thread(_ id: String, listing: String, _ version: ProposalVersionDTO?, state: String = "open", booking: String? = nil,
                        versions: [ProposalVersionDTO]? = nil) -> ProposalThreadDTO {
        ProposalThreadDTO(bookingId: booking, client: ProposalPartyDTO(label: "Mijoz", side: .client), currentVersion: version,
                          driver: ProposalPartyDTO(label: "Haydovchi #1", side: .driver), id: id, listingId: listing, listingTermsVersion: 2,
                          state: state, versions: versions)
    }

    // MARK: Feed mark (5.7)

    @Test func feedMarkShowsMyOpenOfferWithItsTotal() {
        let open = [thread("prp_1", listing: "lst_1", F.version(author: .driver, total: 15_000_000))]
        #expect(FeedOfferMark.of(listingId: "lst_1", open: open, accepted: []) == .offered(threadId: "prp_1", totalMinor: 15_000_000))
        #expect(FeedOfferMark.of(listingId: "lst_2", open: open, accepted: []) == FeedOfferMark.none)
        #expect(FeedOfferMark.of(listingId: "lst_1", open: nil, accepted: nil) == FeedOfferMark.none)
    }

    @Test func feedMarkAcceptedWinsOverOpen() {
        let open = [thread("prp_1", listing: "lst_1", F.version(author: .client, revision: 2))]
        let accepted = [thread("prp_9", listing: "lst_1", F.version(author: .client, status: .accepted), state: "accepted", booking: "bkg_1")]
        let mark = FeedOfferMark.of(listingId: "lst_1", open: open, accepted: accepted)
        #expect(mark == .accepted(threadId: "prp_9"))
        #expect(mark.threadId == "prp_9")
    }

    @Test func feedMarkUnderAClientCounterShowsTheDriversOwnPrice() {
        let mine = F.version(author: .driver, status: .superseded, revision: 1, total: 16_000_000)
        let theirs = F.version(author: .client, revision: 2, total: 14_000_000)
        let open = [thread("prp_1", listing: "lst_1", theirs)]
        #expect(FeedOfferMark.of(listingId: "lst_1", open: open, accepted: []) == .countered(threadId: "prp_1"))
        #expect(FeedOfferMark.of(listingId: "lst_1", open: open, accepted: [], versions: { _ in [mine, theirs] })
                == .offered(threadId: "prp_1", totalMinor: 16_000_000))
    }

    @Test func feedMarkIgnoresAnOfferThatRanOut() {
        let open = [thread("prp_1", listing: "lst_1", F.version(author: .driver, expires: Date().addingTimeInterval(-60)))]
        #expect(FeedOfferMark.of(listingId: "lst_1", open: open, accepted: []) == FeedOfferMark.none)
    }

    // MARK: Negotiation badge and line (8.1 / 8.2)

    @Test func badgeWaitingCounteredAndMyCounter() {
        #expect(ProposalBadge.of(thread("p", listing: "l", F.version(author: .driver, revision: 1))) == .waiting)
        #expect(ProposalBadge.of(thread("p", listing: "l", F.version(author: .client, revision: 2))) == .countered)
        #expect(ProposalBadge.of(thread("p", listing: "l", F.version(author: .driver, revision: 3))) == .myCounter)
        #expect(ProposalBadge.waiting.key == "status.proposed" && ProposalBadge.waiting.tone == .gray)
        #expect(ProposalBadge.countered.key == "driver.offer.badgeCountered" && ProposalBadge.countered.tone == .warn && ProposalBadge.countered.outlined)
        #expect(ProposalBadge.myCounter.key == "driver.offer.badgeMyCounter" && ProposalBadge.myCounter.tone == .blue)
    }

    @Test func badgeClosedStates() {
        #expect(ProposalBadge.of(thread("p", listing: "l", F.version(author: .client, status: .accepted), state: "accepted", booking: "bkg")) == .accepted)
        #expect(ProposalBadge.of(thread("p", listing: "l", F.version(author: .driver, status: .rejected), state: "closed")) == .rejected)
        #expect(ProposalBadge.of(thread("p", listing: "l", F.version(author: .driver, status: .withdrawn), state: "closed")) == .withdrawn)
        #expect(ProposalBadge.of(thread("p", listing: "l", F.version(author: .driver, expires: Date().addingTimeInterval(-1)))) == .expired)
        #expect(ProposalBadge.accepted.key == "client.booking.amendStatusAccepted" && ProposalBadge.accepted.tone == .ok)
        #expect(ProposalBadge.rejected.key == "status.rejected" && ProposalBadge.rejected.tone == .err)
        #expect(ProposalBadge.withdrawn.key == "status.withdrawn" && ProposalBadge.withdrawn.faded)
    }

    @Test func counteredLineCarriesBothPricesWhenTheHistoryIsKnown() {
        let mine = F.version(author: .driver, status: .superseded, revision: 1, total: 15_000_000)
        let theirs = F.version(author: .client, revision: 2, total: 13_000_000)
        let open = thread("p", listing: "l", theirs)
        #expect(ProposalLine.of(open) == .key("negotiation.clientCountered"))
        #expect(ProposalLine.of(open, versions: [mine, theirs]) == .clientCounter(priceMinor: 13_000_000, mineMinor: 15_000_000))
        // The thread's own history (an opened thread) counts too.
        #expect(ProposalLine.of(thread("p", listing: "l", theirs, versions: [mine, theirs])) == .clientCounter(priceMinor: 13_000_000, mineMinor: 15_000_000))
    }

    @Test func linesForWaitingMyCounterAcceptedAndClosed() {
        #expect(ProposalLine.of(thread("p", listing: "l", F.version(author: .driver))) == .key("negotiation.waitingForAnswer"))
        #expect(ProposalLine.of(thread("p", listing: "l", F.version(author: .driver, revision: 3, total: 14_000_000))) == .myCounter(priceMinor: 14_000_000))
        #expect(ProposalLine.of(thread("p", listing: "l", F.version(author: .client, status: .accepted), state: "accepted")) == .key("driver.offer.acceptedLine"))
        #expect(ProposalLine.of(thread("p", listing: "l", F.version(author: .driver, status: .withdrawn), state: "closed")) == nil)
    }

    // MARK: Counter check (8.5)

    @Test func counterNeedsADifferentPrice() {
        #expect(DriverCounterCheck.problemKey(priceMinor: 0, clientUnitMinor: 13_000_000) == "driver.offer.priceRequired")
        #expect(DriverCounterCheck.problemKey(priceMinor: 13_000_000, clientUnitMinor: 13_000_000) == "driver.offer.counterSame")
        #expect(DriverCounterCheck.problemKey(priceMinor: 14_000_000, clientUnitMinor: 13_000_000) == nil)
    }

    // MARK: Saved routes (6.2 / 6.3 / 6.5)

    private func saved(_ id: String, originDistrict: String? = nil, originRegion: String? = nil, destinationDistrict: String? = nil,
                       destinationRegion: String? = nil, service: ServiceType = .parcel) -> SavedSearchDTO {
        SavedSearchDTO(createdAt: "2026-10-01T10:00:00Z", destinationDistrictId: destinationDistrict, destinationRegionId: destinationRegion, id: id,
                       notify: true, originDistrictId: originDistrict, originRegionId: originRegion, quantity: 1, serviceType: service, side: .requests,
                       timeWindowEnd: "2026-10-15T10:00:00Z", timeWindowStart: "2026-10-01T10:00:00Z")
    }

    private var filter: FeedFilter {
        FeedFilter(origin: FeedEnd(regionId: "reg_tash", regionName: "Toshkent", districtId: "dst_chil", districtName: "Chilonzor"),
                   destination: FeedEnd(regionId: "reg_sam", regionName: "Samarqand"))
    }

    @Test func savedRouteAlreadySaved() {
        let same = saved("ss_1", originDistrict: "dst_chil", destinationRegion: "reg_sam")
        #expect(SavedRoute.state(filter, passengerAllowed: false, saved: [same]) == .alreadySaved)
        // Another service is another saved route.
        #expect(SavedRoute.state(filter, passengerAllowed: false, saved: [saved("ss_1", originDistrict: "dst_chil", destinationRegion: "reg_sam",
                                                                                 service: .passenger)]) == .canSave)
        #expect(SavedRoute.state(filter, passengerAllowed: false, saved: [saved("ss_2", originDistrict: "dst_yunus", destinationRegion: "reg_sam")]) == .canSave)
        #expect(SavedRoute.state(FeedFilter(), passengerAllowed: false, saved: []) == .noRoute)
    }

    @Test func savedRouteLimit() {
        let ten = (0..<SavedRoute.limit).map { saved("ss_\($0)", originRegion: "reg_\($0)", destinationRegion: "reg_x") }
        #expect(SavedRoute.state(filter, passengerAllowed: false, saved: ten) == .limitReached)
        #expect(SavedRoute.state(filter, passengerAllowed: false, saved: Array(ten.prefix(9))) == .canSave)
        // Already saved says so even at the limit.
        #expect(SavedRoute.state(filter, passengerAllowed: false, saved: Array(ten.prefix(9)) + [saved("s", originDistrict: "dst_chil", destinationRegion: "reg_sam")])
                == .alreadySaved)
    }

    @Test func savedRouteOpensInTheFeed() {
        let regions = [RegionDTO(code: "TK", id: "reg_tash", nameRu: "Ташкент", nameUz: "Toshkent"), RegionDTO(code: "SM", id: "reg_sam", nameUz: "Samarqand")]
        let districts = ["dst_chil": DistrictDTO(id: "dst_chil", nameRu: "Чиланзар", nameUz: "Chilonzor",
                                                 region: RegionRefDTO(code: "TK", id: "reg_tash", nameUz: "Toshkent"))]
        let current = FeedFilter(chip: .three)
        let opened = SavedRoute.feedFilter(from: saved("ss", originDistrict: "dst_chil", destinationRegion: "reg_sam", service: .passenger),
                                           current: current, regions: regions, districts: districts)
        #expect(opened?.origin == FeedEnd(regionId: "reg_tash", regionName: "Toshkent", regionNameRu: "Ташкент", districtId: "dst_chil",
                                          districtName: "Chilonzor", districtNameRu: "Чиланзар"))
        #expect(opened?.destination == FeedEnd(regionId: "reg_sam", regionName: "Samarqand"))
        #expect(opened?.passenger == true && opened?.chip == .three)
        // A district not loaded yet: nothing to open.
        #expect(SavedRoute.feedFilter(from: saved("ss", originDistrict: "dst_other", destinationRegion: "reg_sam"), current: current, regions: regions,
                                      districts: districts) == nil)
    }

    // MARK: Departure (3.4)

    @Test func departureSentences() {
        let now = F.at(2026, 10, 3, 12)
        var form = TripPlanForm(vehicleId: "veh_1", corridorId: "cor_1", routeId: "rtv_1", start: nil, seats: "3", cargoKg: "20", cargoLitres: "100")
        #expect(TripPlan.departureKey(TripPlan.problems(form, vehicle: F.vehicle(), now: now)[.start]) == "driver.trip.departureRequired")
        form.start = now.addingTimeInterval(-60)
        #expect(TripPlan.departureKey(TripPlan.problems(form, vehicle: F.vehicle(), now: now)[.start]) == "driver.trip.departurePast")
        form.start = now.addingTimeInterval(3600)
        #expect(TripPlan.departureKey(TripPlan.problems(form, vehicle: F.vehicle(), now: now)[.start]) == nil)
    }

    // MARK: Home counts (1.2)

    @Test func homeStatsCountWhatIsStillGoing() {
        let trips = [F.trip(id: "t1", status: .planned), F.trip(id: "t2", status: .inProgress), F.trip(id: "t3", status: .completed),
                     F.trip(id: "t4", status: .cancelled), F.trip(id: "t5", status: .interrupted)]
        let offers = [thread("p1", listing: "l1", F.version(author: .driver)), thread("p2", listing: "l2", F.version(author: .client, revision: 2)),
                      thread("p3", listing: "l3", F.version(author: .driver, expires: Date().addingTimeInterval(-5)))]
        let stats = DriverHomeStats.of(trips: trips, openProposals: offers, bookingStatuses: ["confirmed", "in_transit", "completed", "cancelled"])
        #expect(stats == DriverHomeStats(trips: 3, offers: 2, bookings: 2))
        let unknown = DriverHomeStats.of(trips: nil, openProposals: nil, bookingStatuses: nil)
        #expect(DriverHomeStats.text(unknown.trips) == "—" && DriverHomeStats.text(0) == "0")
    }

    // MARK: Accept -> booking chat (8.7, Q100)

    @Test func acceptOpensTheBookingChat() {
        #expect(AcceptNext.after(bookingId: "bkg_1") == .bookingChat("bkg_1"))
        #expect(AcceptNext.after(bookingId: nil) == .stay)
        #expect(AcceptNext.after(bookingId: "") == .stay)
    }

    // MARK: Trips (2.2 / 2.5 / 2.6 / 4.2)

    @Test func tripTonesStopDotsAndOneLiveTrip() {
        #expect(TripStopDot.of(index: 0, status: .planned) == .ahead)
        #expect(TripStopDot.of(index: 0, status: .boarding) == .current && TripStopDot.of(index: 1, status: .boarding) == .ahead)
        #expect(TripStopDot.of(index: 0, status: .inProgress) == .done && TripStopDot.of(index: 1, status: .inProgress) == .current)
        #expect(TripStopDot.of(index: 2, status: .completed) == .done)
        let planned = F.trip(id: "t1", status: .planned)
        #expect(LiveTrip.blocksStart(planned, among: [planned, F.trip(id: "t2", status: .boarding)]))
        #expect(!LiveTrip.blocksStart(planned, among: [planned, F.trip(id: "t2", status: .completed)]))
        #expect(LiveTrip.bannerKey(.depart) == "driver.trip.departed" && LiveTrip.bannerKey(.cancel) == "driver.trip.cancelled")
        #expect(LiveTrip.bannerKey(.startBoarding) == "driverRoutes.tripStatusUpdated")
    }
}
