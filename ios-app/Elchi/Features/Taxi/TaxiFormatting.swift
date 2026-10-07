import Foundation

/// How the Taksi screens say people, per-seat prices and the passenger states in the active language.
extension LocaleStore {
    /// `2 × 150 000 so'm`.
    func seatsTotal(_ count: Int, unitMinor: Int) -> String {
        t("client.taxi.seatsTotal", ("count", count), ("price", money(unitMinor)))
    }

    /// `2 kishi · 2 × 150 000 so'm` - a passenger listing, offer or booking said as people and the per-seat price.
    func peopleLine(_ count: Int, unitMinor: Int) -> String {
        "\(t("seatPicker.peopleCount", ("count", count))) · \(seatsTotal(count, unitMinor: unitMinor))"
    }

    /// The price on a header card: `2 × 150 000 so'm` for a per-seat booking, the total otherwise.
    func bookingPrice(_ booking: ClientBookingDTO) -> String {
        guard booking.serviceType == .passenger, booking.promo == nil, PassengerMoney.perSeat(booking.priceBasis) else {
            return money(booking.cashDueMinor)
        }
        return seatsTotal(booking.quantity, unitMinor: booking.unitPriceMinor)
    }

    /// The people line of a passenger listing (`2 kishi · 2 × 150 000 so'm`), nil for a parcel.
    func peopleLine(_ listing: ListingDTO) -> String? {
        guard listing.serviceType == .passenger else { return nil }
        let count = listing.passenger?.seatCount ?? listing.quantity
        return peopleLine(count, unitMinor: listing.unitPriceMinor)
    }

    /// The same for a request in the driver's feed.
    func peopleLine(_ listing: ListingPublicDTO) -> String? {
        guard listing.serviceType == .passenger else { return nil }
        return peopleLine(max(listing.quantity, 1), unitMinor: listing.unitPriceMinor)
    }

    /// "Yo'lovchini chiqardim" refused: the trip not started, else the refusal's own sentence.
    func boardErrorText(_ error: Error) -> String {
        switch BoardRefusal.of(error) {
        case .tripNotStarted: t("error.TRIP_NOT_STARTED")
        case .other: errorText(error)
        }
    }

    /// "Mijoz kelmadi" refused, said with its reason (`wait_time_not_elapsed` names the time when that is known).
    func noShowErrorText(_ error: Error, unlocksAt: Date?) -> String {
        guard let key = NoShowReport.refusalKey(error, known: { tOrNil($0) != nil }) else { return errorText(error) }
        if key == "driver.noShow.reason.wait_time_not_elapsed" {
            return t(key, ("time", unlocksAt.map { clockOrDay($0) } ?? "…"))
        }
        return t(key)
    }

    /// `14:05` today, `27.09, 14:05` on another day.
    func clockOrDay(_ date: Date, now: Date = Date()) -> String {
        DepartureWindow.calendar.isDate(date, inSameDayAs: now) ? clock(date) : DepartureWindow.shortText(date)
    }

    /// A refused cash record or answer: the note / comment rule in words, the rest as the code's sentence.
    func cashErrorText(_ error: Error) -> String {
        if let error = error as? APIError, error.code == "VALIDATION_ERROR" {
            switch error.details?["field"] {
            case .string("note")?: return t("app.cash.noteRequired")
            case .string("comment")?: return t("app.cash.commentRequired")
            default: break
            }
        }
        return errorText(error)
    }
}

