import SwiftUI

/// Where the GPS bar shows (spec C): the trips list (the running trip), a trip's detail (when that trip runs or is
/// the one being published) and a booking's detail / chat on a running trip. Each wrapper decides from live state.
struct TripsGpsBar: View {
    let tracker: DriverTracker
    let trips: TripsModel

    var body: some View {
        let running = trips.trackable?.id
        if running != nil || tracker.snapshot.phase != .idle {
            GpsBarView(tracker: tracker, tripId: running ?? (tracker.isRunning() ? tracker.snapshot.tripId : nil))
        }
    }
}

struct TripGpsBar: View {
    let tracker: DriverTracker
    let trip: TripDetailModel

    var body: some View {
        let publishable = trip.trip.value.map { GpsContract.publishableTripStatuses.contains($0.status.rawValue) } ?? false
        if publishable {
            GpsBarView(tracker: tracker, tripId: trip.id)
        } else if tracker.snapshot.tripId == trip.id {
            GpsBarView(tracker: tracker, tripId: nil)
        }
    }
}

struct BookingGpsBar: View {
    let tracker: DriverTracker
    let booking: DriverBookingModel

    /// The booking says its trip is boarding (awaiting pickup) or under way.
    static let runningStatuses: Set<String> = ["awaiting_pickup", "in_transit", "picked_up"]

    var body: some View {
        if let dto = booking.booking.value {
            if Self.runningStatuses.contains(dto.status) {
                GpsBarView(tracker: tracker, tripId: dto.tripId)
            } else if tracker.snapshot.tripId == dto.tripId && tracker.isRunning() {
                GpsBarView(tracker: tracker, tripId: dto.tripId)
            }
        }
    }
}
