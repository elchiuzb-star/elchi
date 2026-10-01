import Foundation

/// How the orders and offers screens say places, dates, drivers and statuses in the active language.
extension LocaleStore {
    /// One end of a listing, offer or booking: the stop's name, else the marked place's district, else its address.
    func endName(stop: StopRefDTO?, point: PointEndDTO?) -> String {
        if let stop { return locale == .ru ? stop.nameRu ?? stop.nameUz : stop.nameUz }
        if let point { return point.district?.nameUz ?? point.address ?? GeoPoint(lat: point.lat, lng: point.lng).text }
        return "?"
    }

    /// The detail row's value: the full street address when the place has one.
    func endAddress(stop: StopRefDTO?, point: PointEndDTO?) -> String {
        if stop == nil, let address = point?.address, !address.isEmpty { return address }
        return endName(stop: stop, point: point)
    }

    /// `Toshkent → Buxoro`.
    func route(_ listing: ListingDTO) -> String {
        "\(endName(stop: listing.originStop, point: listing.originPoint)) → \(endName(stop: listing.destinationStop, point: listing.destinationPoint))"
    }

    func route(_ booking: ClientBookingDTO) -> String {
        "\(endName(stop: booking.pickup.stop, point: booking.pickup.point)) → \(endName(stop: booking.dropoff.stop, point: booking.dropoff.point))"
    }

    func route(_ order: LegacyOrder) -> String {
        let from = order.fromCity ?? order.fromDistrict?.nameUz ?? "?"
        let to = order.toCity ?? order.toDistrict?.nameUz ?? "?"
        return "\(from) → \(to)"
    }

    /// `29 sen` / `29 сент.` (Tashkent calendar day, the language's short month - the design's list date).
    func dayMonth(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: locale == .ru ? "ru_RU" : "uz_Latn_UZ")
        formatter.timeZone = DepartureWindow.timeZone
        formatter.dateFormat = "d MMM"
        return formatter.string(from: date)
    }

    /// `29.09, 09:00 - 29.09, 18:00` from two server instants.
    func window(_ start: String?, _ end: String?) -> String {
        let parts = [start, end].map { ServerTime.parse($0).map(DepartureWindow.shortText) ?? "?" }
        return parts.joined(separator: " - ")
    }

    /// `29.09 - 29.09` (the day part only).
    func windowDays(_ start: String?, _ end: String?) -> String {
        let parts = [start, end].map { ServerTime.parse($0).map { String(DepartureWindow.shortText($0).prefix(5)) } ?? "?" }
        return parts.joined(separator: " - ")
    }

    /// `12 daqiqa oldin` / `3 soat oldin` / `2 kun oldin`.
    func ago(_ date: Date, now: Date = Date()) -> String {
        let minutes = Countdown.minutesAgo(date, now: now)
        if minutes < 60 { return t("publicTracking.minutesAgo", ("minutes", minutes)) }
        if minutes < 24 * 60 { return t("client.time.hoursAgo", ("hours", minutes / 60)) }
        return t("client.time.daysAgo", ("days", minutes / (24 * 60)))
    }

    /// `1 soat 40 daqiqa` - the time an offer still stands.
    func duration(hours: Int, minutes: Int) -> String {
        hours == 0 ? t("app.duration.minutes", ("minutes", minutes))
            : minutes == 0 ? t("app.duration.hours", ("hours", hours))
            : t("app.duration.hoursMinutes", ("hours", hours), ("minutes", minutes))
    }

    /// `Taklif 1 soat 40 daqiqa amal qiladi`, or nil once the offer's time is over.
    func expiresIn(_ version: ProposalVersionDTO, now: Date) -> String? {
        guard let expires = ServerTime.parse(version.expiresAt), let left = Countdown.left(until: expires, now: now) else { return nil }
        return t("client.listingBids.expiresIn", ("time", duration(hours: left.hours, minutes: left.minutes)))
    }

    /// "Haydovchi #3" in the active language (the server's label is Uzbek; its number is stable per listing, Q40).
    func driverLabel(_ thread: ProposalThreadDTO) -> String {
        thread.driverNumber.map { t("client.listingBids.driver", ("number", $0)) } ?? thread.driver.label
    }

    /// `Yengil avtomobil · 4 o'rin · Yaxshi baholangan · 12 ta baho` - the anonymous comparison set (Q40, ADR-0026):
    /// never a name, plate or phone before accept (Q43). An unrated driver reads `Yangi haydovchi · Hali
    /// baholanmagan` (the same wording as Android), never "0 ta baho".
    func driverSummary(_ summary: ProposalDriverSummaryDTO) -> String {
        let vehicle = tOrNil("vehicleClass.\(summary.vehicleClass)") ?? summary.vehicleClass
        let car = t("app.rivalBoard.vehicleSeats", ("vehicle", vehicle), ("seats", summary.seatCapacity))
        guard let bucket = summary.ratingBucket, let bucketText = tOrNil("ratingBucket.\(bucket.rawValue)") else {
            return "\(car) · \(t("listingBids.noRatingsYet"))"
        }
        guard let count = summary.ratingCount, count > 0 else { return "\(car) · \(bucketText) · \(t("listingBids.noRatingsYet"))" }
        return "\(car) · \(t("app.rivalBoard.ratings", ("bucket", bucketText), ("count", count)))"
    }

    func status(_ label: StatusLabel) -> (text: String, tone: Tone) {
        (tOrNil(label.key) ?? label.raw, label.tone)
    }

    /// `14 ta ko'rish` or `Hali hech kim ko'rmagan` (Q98: people, not openings).
    func views(_ count: Int?) -> String {
        guard let count, count > 0 else { return t("listing.viewsNone") }
        return "\(count) \(t("listing.viewsSuffix"))"
    }

    /// `Quti · Kichik quti (30×20×20 sm gacha · 5 kg gacha)`.
    func parcel(_ details: ParcelDetails?) -> String? {
        guard let details else { return nil }
        let type = details.parcelType.map(parcelTypeName)
        let category = details.category.map { "\(name($0)) (\(limits($0)))" }
        let parts = [type, category].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// A refused answer to an offer, said for the client. The driver's own trouble (its commission wallet, its
    /// eligibility) is told neutrally - never blamed on anyone; a changed thread says what changed.
    func offerErrorText(_ error: Error) -> String {
        guard let error = error as? APIError else { return errorText(error) }
        switch error.code {
        case "INSUFFICIENT_COMMISSION_BALANCE", "DRIVER_NOT_ELIGIBLE":
            return t("client.listingBids.driverCannotTake")
        case "PROPOSAL_CHANGED":
            switch error.details?["reason"] {
            case .string("listing_terms_changed")?, .string("listing_terms_version_mismatch")?: return t("client.listingBids.termsChanged")
            case .string("demand_already_booked")?: return t("client.listingBids.alreadyBooked")
            default: return errorText(error)
            }
        default:
            return errorText(error)
        }
    }

    /// Share-link refusals: the active-link limit gets its own sentence.
    func shareErrorText(_ error: Error) -> String {
        if let error = error as? APIError, error.code == "VALIDATION_ERROR", error.details?["reason"] == .string("too_many_active") {
            let limit: Int = if case .number(let value)? = error.details?["limit"] { Int(value) } else { 5 }
            return t("client.share.tooMany", ("limit", limit))
        }
        return errorText(error)
    }
}
