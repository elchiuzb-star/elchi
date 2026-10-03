import Foundation
import Testing
@testable import Elchi

/// BOSQICH 03 design ("Elchi Takliflar"): what the listing card's meta line, the detail's tracker, the offer badges,
/// the closed reasons, "Yangi", the counter's tap-to-validate and the offer window say.
struct ListingMetaTests {
    let newest = Fixture.date("2026-09-29T09:48:00Z")

    @Test func publishedWithAnOpenOfferSaysTheNewestInBlue() {
        let meta = ListingMeta.of(Fixture.listing(), stats: OfferStats(open: 2, newest: newest))
        #expect(meta == .newOffer(newest))
        #expect(meta?.highlighted == true)
    }

    @Test func liveWithoutOpenOffersSaysHowLongItStands() {
        let expires = Fixture.date("2026-10-02T13:00:00Z")
        #expect(ListingMeta.of(Fixture.listing(), stats: OfferStats(open: 0, newest: nil)) == .validUntil(expires))
        #expect(ListingMeta.of(Fixture.listing(), stats: nil) == .validUntil(expires))
        // Paused: hidden from the feed, so no "new offer" news either.
        #expect(ListingMeta.of(Fixture.listing(status: "paused"), stats: OfferStats(open: 1, newest: newest)) == .validUntil(expires))
        #expect(ListingMeta.validUntil(expires).highlighted == false)
    }

    @Test func closedListingsSayNoExpiry() {
        #expect(ListingMeta.of(Fixture.listing(status: "fulfilled"), stats: nil) == .driverChosen)
        #expect(ListingMeta.of(Fixture.listing(status: "expired"), stats: nil) == nil)
        #expect(ListingMeta.of(Fixture.listing(status: "cancelled"), stats: nil) == nil)
    }
}

struct ListingProgressTests {
    @Test func stepsFromTheListingThenTheBooking() {
        #expect(ListingProgress.of(Fixture.listing(), hasThreads: false, bookingStatus: nil) == ListingProgress(current: 0, dead: false))
        #expect(ListingProgress.of(Fixture.listing(), hasThreads: true, bookingStatus: nil).current == 1)
        #expect(ListingProgress.of(Fixture.listing(status: "paused"), hasThreads: true, bookingStatus: nil).current == 1)
        let fulfilled = Fixture.listing(status: "fulfilled")
        #expect(ListingProgress.of(fulfilled, hasThreads: true, bookingStatus: nil).current == 2)
        #expect(ListingProgress.of(fulfilled, hasThreads: true, bookingStatus: "confirmed").current == 2)
        #expect(ListingProgress.of(fulfilled, hasThreads: true, bookingStatus: "in_transit").current == 3)
        #expect(ListingProgress.of(fulfilled, hasThreads: true, bookingStatus: "onboard").current == 3)
        #expect(ListingProgress.of(fulfilled, hasThreads: true, bookingStatus: "completed").current == 4)
        #expect(ListingProgress.stepKeys.count == 5)
    }

    @Test func expiredAndCancelledAreDead() {
        #expect(ListingProgress.of(Fixture.listing(status: "expired"), hasThreads: true, bookingStatus: nil).dead)
        #expect(ListingProgress.of(Fixture.listing(status: "cancelled"), hasThreads: false, bookingStatus: nil).dead)
    }
}

struct OfferBadgeTests {
    let now = Fixture.date("2026-09-29T10:00:00Z")

    @Test func theBadgeFollowsTheSort() {
        let cheap = Fixture.thread(id: "a", total: 13_000_000, pickupStart: "2026-09-30T09:00:00Z", bucket: "mixed")
        let early = Fixture.thread(id: "b", total: 15_000_000, pickupStart: "2026-09-30T04:00:00Z", bucket: "good")
        let all = [cheap, early]
        #expect(OfferBadge.badges(all, sort: .cheapest, unseen: [], now: now) == ["a": .cheapest])
        #expect(OfferBadge.badges(all, sort: .fastest, unseen: [], now: now) == ["b": .fastest])
        #expect(OfferBadge.badges(all, sort: .bestRated, unseen: [], now: now) == ["b": .bestRated])
    }

    @Test func aLoneOfferIsNotTheCheapestOfAnything() {
        let only = Fixture.thread(id: "a")
        #expect(OfferBadge.badges([only], sort: .cheapest, unseen: [], now: now).isEmpty)
        #expect(OfferBadge.badges([only], sort: .fastest, unseen: [], now: now).isEmpty)
        // "Yaxshi baholangan" is the server's bucket: true of one offer too.
        #expect(OfferBadge.badges([only], sort: .bestRated, unseen: [], now: now) == ["a": .bestRated])
    }

    @Test func theDriversCounterWinsThenNew() {
        let countered = Fixture.thread(id: "a", total: 12_000_000, revision: 3)
        let fresh = Fixture.thread(id: "b", total: 14_000_000, bucket: "mixed")
        let mine = Fixture.thread(id: "c", author: "client", total: 13_000_000, revision: 2)
        let closed = Fixture.thread(id: "d", state: "closed", status: "expired", total: 1_000)
        // "Yangi" only where the answer is the client's (its own pending counter is no news).
        let badges = OfferBadge.badges([countered, fresh, mine, closed], sort: .cheapest, unseen: ["b", "c", "d"], now: now)
        #expect(badges["a"] == .counter)
        #expect(badges["b"] == .new)
        #expect(badges["c"] == nil)
        #expect(badges["d"] == nil)
        #expect(OfferBadge.counter.tone == .warn && OfferBadge.new.tone == .err && OfferBadge.cheapest.tone == .ok)
    }

    @Test func driverCounteredNeedsTheDriversTurnAfterTheFirstOffer() {
        #expect(!Fixture.thread().driverCountered(now: now))
        #expect(Fixture.thread(revision: 2).driverCountered(now: now))
        #expect(!Fixture.thread(author: "client", revision: 2).driverCountered(now: now))
        #expect(!Fixture.thread(state: "closed", status: "expired", revision: 3).driverCountered(now: now))
    }
}

struct ClosedReasonTests {
    let now = Fixture.date("2026-09-29T10:00:00Z")

    @Test func statusReasonsInTheDesignsWords() {
        func key(_ status: String, _ reason: String?) -> String {
            Fixture.thread(state: "closed", status: status, reason: reason).closedReasonKey(now: now)
        }
        #expect(key("expired", "ttl_expired") == "status.expired")
        #expect(key("rejected", "rejected") == "amendment.rejected")
        #expect(key("withdrawn", "withdrawn") == "client.offers.closed.withdrawn")
        #expect(key("expired", "demand_fulfilled") == "client.offers.closed.demandFulfilled")
        #expect(key("expired", "listing_closed") == "notification.listing.cancelled.title")
        #expect(key("expired", "listing_changed") == "client.offers.closed.listingChanged")
        // No reason: the version's status.
        #expect(key("rejected", nil) == "amendment.rejected")
        #expect(key("withdrawn", nil) == "client.offers.closed.withdrawn")
        #expect(key("expired", nil) == "status.expired")
    }

    @Test func acceptedAndClockExpiredOffers() {
        #expect(Fixture.thread(state: "accepted", status: "accepted").closedReasonKey(now: now) == "client.amendment.statusAccepted")
        #expect(Fixture.thread(expires: "2026-09-29T09:59:00Z").closedReasonKey(now: now) == "status.expired")
    }
}

struct OfferSeenTests {
    let now = Fixture.date("2026-09-29T10:00:00Z")

    @Test func newDriverVersionsOnly() {
        let a = Fixture.thread(id: "a"), b = Fixture.thread(id: "b", revision: 3)
        let mine = Fixture.thread(id: "c", author: "client", revision: 2)
        let closed = Fixture.thread(id: "d", state: "closed", status: "expired")
        #expect(OfferSeen.fresh([a, b, mine, closed], seen: [], now: now) == ["a", "b"])
        #expect(OfferSeen.fresh([a, b], seen: ["a:1", "b:2"], now: now) == ["b"])
        #expect(a.seenKey == "a:1" && mine.seenKey == nil)
    }
}

struct CounterCheckTests {
    @Test func tapToValidate() {
        #expect(CounterCheck.error(priceMinor: 0, driverUnitMinor: 14_000_000) == "listingOwner.invalid.price")
        #expect(CounterCheck.error(priceMinor: 14_000_000, driverUnitMinor: 14_000_000) == "client.offers.counterSame")
        #expect(CounterCheck.error(priceMinor: 13_500_000, driverUnitMinor: 14_000_000) == nil)
    }

    @Test func placeShortIsTheFirstPart() {
        #expect(PlaceShort.of("Chilonzor, 9-kvartal") == "Chilonzor")
        #expect(PlaceShort.of("Buxoro avtovokzali") == "Buxoro avtovokzali")
        #expect(PlaceShort.of("Yunusobod,") == "Yunusobod")
    }
}

@MainActor
struct OfferWindowTests {
    let strings = LocaleStore()

    @Test func timesOnlyOnTheListingsDay() {
        let version = Fixture.thread().currentVersion!
        // Listing 30.09 09:00 Tashkent; the offer 10:00-12:00 the same day.
        #expect(strings.offerWindow(version, listingStart: "2026-09-30T04:00:00Z") == "10:00 – 12:00")
        #expect(strings.offerWindow(version, listingStart: "2026-09-29T04:00:00Z") == "30.09, 10:00 – 12:00")
        #expect(strings.offerWindow(version, listingStart: nil) == "30.09, 10:00 – 12:00")
    }

    @Test func pastMidnightShowsBothDays() {
        let version = Fixture.thread(pickupStart: "2026-09-29T18:00:00Z").currentVersion!
        #expect(strings.offerWindow(version, listingStart: "2026-09-29T04:00:00Z") == "29.09, 23:00 – 30.09, 12:00")
    }
}
