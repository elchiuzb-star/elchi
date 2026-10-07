import Foundation

/// How the driver's trip, feed and offer screens say places, times, capacity and refusals in the active language.
extension LocaleStore {
    /// ADR-0028 (Q158/Q160): a trip is a stretch of road, named by the areas of the direction it was planned for
    /// (`Chilonzor → Qarshi`); a trip no direction points at (an older or manually planned one) is named by its times.
    func route(_ trip: TripDTO, directions: [DriverDirectionDTO] = []) -> String {
        if let direction = directions.first(where: { $0.activeTrip?.id == trip.id }) {
            return DirectionEndName.route(direction, ru: locale == .ru)
        }
        guard let start = ServerTime.parse(trip.plannedStartAt), let end = ServerTime.parse(trip.plannedEndAt) else { return "?" }
        return "\(DepartureWindow.shortText(start)) → \(DepartureWindow.shortText(end))"
    }

    /// One end of a request as the feed says it: the district of the marked place - never a street address (the exact
    /// place is agreed in the booking chat, Q100) and never a stop (ADR-0028).
    func feedEnd(_ point: PointEndDTO?) -> String {
        if let district = point?.district { return district.nameUz }
        return t("app.endLabel.mapPlace")
    }

    /// A manifest place / booking end in the driver's lists: the agreed address, else its district (ADR-0028).
    func placeText(_ point: PointEndDTO?) -> String {
        if let address = point?.address, !address.isEmpty { return address }
        return point.map { feedEnd($0) } ?? t("tripDetail.agreedPoint")
    }

    func route(_ listing: ListingPublicDTO) -> String {
        "\(feedEnd(listing.originPoint)) → \(feedEnd(listing.destinationPoint))"
    }

    /// A version's pickup → dropoff (the driver's offers list).
    func route(_ version: ProposalVersionDTO) -> String {
        "\(feedEnd(version.pickupPoint)) → \(feedEnd(version.dropoffPoint))"
    }

    /// `27 sen, 09:00–18:00` on one day, `27.09, 22:00 - 28.09, 06:00` across days.
    func span(_ start: Date, _ end: Date) -> String {
        let calendar = DepartureWindow.calendar
        if calendar.isDate(start, inSameDayAs: end) { return "\(dayMonth(start)), \(clock(start))–\(clock(end))" }
        return "\(DepartureWindow.shortText(start)) - \(DepartureWindow.shortText(end))"
    }

    func span(_ start: String, _ end: String) -> String {
        guard let from = ServerTime.parse(start), let to = ServerTime.parse(end) else { return window(start, end) }
        return span(from, to)
    }

    /// `27 sen · 3 o'rin`.
    func tripMeta(_ trip: TripDTO) -> String {
        let date = ServerTime.parse(trip.plannedStartAt).map { "\(dayMonth($0)), \(clock($0))" } ?? "?"
        return t("driverRoutes.tripMeta", ("date", date), ("seats", trip.seatCapacity))
    }

    /// `Status: Rejalashtirilgan`.
    func tripStatus(_ status: TripStatus) -> String { tOrNil(TripStatusStyle.key(status)) ?? status.rawValue }

    /// `Kichik quti · 30×20×20 sm gacha · 5 kg gacha`; a passenger request: `2 kishi · 2 × 150 000 so'm`.
    func parcelLine(_ listing: ListingPublicDTO) -> String? {
        if let people = peopleLine(listing) { return people }
        if let category = listing.parcelCategory { return "\(name(category)) · \(limits(category))" }
        return listing.parcelType.map(parcelTypeName)
    }

    /// `2 o'rin · yuk 15 kg / 80 l · bagaj 40 l` - a stretch's remaining capacity.
    func segmentLine(_ segment: StretchAvailabilityDTO) -> String {
        t("tripDetail.segmentLine", ("seats", segment.seatsRemaining),
          ("weight", t("tripDetail.kg", ("value", VehicleLock.thousandths(segment.cargoRemainingWeightG)))),
          ("volume", t("tripDetail.litres", ("value", VehicleLock.thousandths(segment.cargoRemainingVolumeMl)))),
          ("baggage", t("tripDetail.litres", ("value", VehicleLock.thousandths(segment.baggageRemainingMl)))))
    }

    /// `Taklif 1 soat 12 daqiqa amal qiladi`, nil once over.
    func driverExpiresIn(_ version: ProposalVersionDTO, now: Date) -> String? {
        guard let expires = ServerTime.parse(version.expiresAt), let left = Countdown.left(until: expires, now: now) else { return nil }
        return t("driver.proposals.expiresIn", ("time", duration(hours: left.hours, minutes: left.minutes)))
    }

    /// A refused trip command: when the boarding window opens, or the code's sentence.
    func tripRefusalText(_ error: Error) -> String {
        switch TripRefusal.of(error) {
        case .windowOpensAt(let date):
            let day = DepartureWindow.calendar.isDateInToday(date) ? clock(date) : DepartureWindow.shortText(date)
            return t("driver.trip.windowOpensAt", ("time", day))
        case .unresolvedBookings:
            return t("error.TRIP_HAS_UNRESOLVED_BOOKINGS")
        case .versionConflict, .other:
            return marketErrorText(error)
        }
    }

    /// Offer, saved-route and negotiation refusals; the rest is the shared `error.<CODE>` sentence.
    func marketErrorText(_ error: Error, seats: Int? = nil) -> String {
        switch MarketErrorText.sentence(error) {
        case .key("driverBid.capacityUnavailable", _):
            // Taksi: the trip cannot seat the request's people - another trip, or a new one.
            return t("driverBid.capacityUnavailable", ("count", seats ?? 1))
        case .key(let key, let values): return t(key, values: values.map { ($0.key, $0.value as Any) })
        case .generic:
            return bannerErrorText(error)
        }
    }

    /// `Bu narx … oraliqdan tashqarida … (100 000 so'm – 150 000 so'm)` with the reference band when it came along.
    func priceWarningText(_ warning: ApiWarning) -> String {
        let base = warningText(warning)
        guard warning.code == "PRICE_OUTSIDE_REFERENCE", case .number(let floor)? = warning.details?["floor_minor"],
              case .number(let ceiling)? = warning.details?["ceiling_minor"] else { return base }
        return "\(base) \(t("driver.bid.priceBand", ("floor", money(Int(floor))), ("ceiling", money(Int(ceiling)))))"
    }
}
