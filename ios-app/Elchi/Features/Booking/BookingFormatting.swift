import Foundation

/// How the booking screens say times, the driver, the vehicle, the cancellation and refusals in the active language.
extension LocaleStore {
    /// `09:00` (Tashkent wall clock).
    func clock(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = DepartureWindow.timeZone
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: date)
    }

    /// `27 sen, 09:00–18:00` - the pickup window as the header card says it.
    func bookingWhen(_ booking: ClientBookingDTO) -> String? {
        guard let start = ServerTime.parse(booking.pickup.windowStart) else { return nil }
        let end = ServerTime.parse(booking.pickup.windowEnd)
        return "\(dayMonth(start)), \(clock(start))\(end.map { "–\(clock($0))" } ?? "")"
    }

    /// A chat or support message's time: `14:05` today, `27.09, 14:05` on another day.
    func messageTime(_ text: String?, now: Date = Date()) -> String? {
        guard let date = ServerTime.parse(text) else { return nil }
        return DepartureWindow.calendar.isDate(date, inSameDayAs: now) ? clock(date) : DepartureWindow.shortText(date)
    }

    /// `★ 4,7 · 38 ta baho · 112 ta bajarilgan bron`, or `Yangi haydovchi · Hali baholanmagan` while nobody has rated
    /// the driver (never "0 ta baho", never an invented score - §8.2).
    func reputationLine(_ reputation: ReputationDTO) -> String {
        guard reputation.ratingCount > 0, let average = reputation.averageRating else {
            return "\(t("ratingBucket.new_verified")) · \(t("reputation.notRated"))"
        }
        let score = String(format: "%.1f", average).replacingOccurrences(of: ".", with: ",")
        return t("client.bookingDetail.reputation", ("rating", score), ("count", reputation.ratingCount),
                 ("bookings", reputation.completedBookings))
    }

    /// `Chevrolet Cobalt · oq`.
    func vehicleName(_ vehicle: ClientBookingDTO.Vehicle) -> String {
        [vehicle.makeModel, vehicle.color].filter { !$0.isEmpty }.joined(separator: " · ")
    }

    /// `Yengil avtomobil · 4 o'rin`.
    func vehicleClassLine(_ vehicle: ClientBookingDTO.Vehicle) -> String {
        t("app.rivalBoard.vehicleSeats", ("vehicle", tOrNil("vehicleClass.\(vehicle.vehicleClass)") ?? vehicle.vehicleClass),
          ("seats", vehicle.seatCapacity))
    }

    /// `Kichik quti · 30×20×20 sm gacha · 5 kg gacha` (with the parcel type in front when the listing says it).
    func parcelLine(_ category: ParcelCategoryDTO?, type: ParcelType?) -> String? {
        let parts = [type.map(parcelTypeName), category.map(name), category.map(limits)].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// `Bekor qilindi: Haydovchi · 25.09, 18:40 · Mashinada nosozlik`.
    func cancelledLine(_ cancelled: ClientBookingDTO.Cancelled) -> String {
        let side = tOrNil(BookingCancelReason.sideKey(cancelled.bySide)) ?? cancelled.bySide
        let reason = cancelled.reasonCode.isEmpty ? nil
            : (tOrNil(BookingCancelReason.key(forCode: cancelled.reasonCode)) ?? t("bookingCancel.reason.other"))
        let parts = [side, ServerTime.parse(cancelled.at).map(DepartureWindow.shortText), reason].compactMap { $0 }
        return "\(t("bookingCancel.cancelledBy")): \(parts.joined(separator: " · "))"
    }

    /// A refused cancel, said for this booking.
    func cancelErrorText(_ error: Error) -> String {
        switch (error as? APIError)?.code {
        case "VERSION_CONFLICT"?: t("bookingCancel.refused.changed")
        case "CUSTODY_REQUIRES_RETURN_FLOW"?: t("bookingCancel.refused.custody")
        case "NO_SHOW_REVIEW_PENDING"?: t("bookingCancel.refused.noShowPending")
        case "INVALID_STATE_TRANSITION"?: t("client.bookingCancel.tooLate")
        default: errorText(error)
        }
    }

    /// A refused recipient link: too early says from when; a finished booking says so.
    func grantErrorText(_ error: Error) -> String {
        guard let error = error as? APIError else { return errorText(error) }
        if error.code == "VALIDATION_ERROR", error.details?["reason"] == .string("grant_too_early") {
            if case .string(let from)? = error.details?["issuable_from"], let date = ServerTime.parse(from) {
                return t("client.trackingShare.tooEarly", ("time", DepartureWindow.shortText(date)))
            }
            return t("client.trackingShare.tooEarlyNoTime")
        }
        if error.code == "INVALID_STATE_TRANSITION" { return t("client.trackingShare.finished") }
        if error.code == "FORBIDDEN" { return t("client.trackingShare.ownerOnly") }
        return errorText(error)
    }

    /// A refused amendment, said with its reason.
    func amendmentErrorText(_ error: Error) -> String {
        guard let error = error as? APIError else { return errorText(error) }
        switch error.code {
        case "AMENDMENT_CONFLICT":
            let keys = ["amendment_open": "client.amendment.openExists", "trip_not_planned": "client.amendment.conflict.tripNotPlanned",
                        "booking_changed": "client.amendment.conflict.bookingChanged", "amendment_expired": "client.amendment.conflict.expired"]
            if case .string(let reason)? = error.details?["reason"], let key = keys[reason] { return t(key) }
            return errorText(error)
        case "VALIDATION_ERROR" where error.details?["reason"] == .string("no_change"):
            return t("client.amendment.noChange")
        case "VERSION_CONFLICT":
            return t("bookingCancel.refused.changed")
        case "INVALID_STATE_TRANSITION":
            return t("client.amendment.conflict.tripNotPlanned")
        default:
            return errorText(error)
        }
    }

    /// The text of a chat message: its words, a quick reply's label, or the hidden line.
    func chatText(_ message: ChatMessageDTO) -> String {
        if message.moderationStatus == .hiddenByStaff { return t("bookingChat.hiddenByStaff") }
        if let code = message.quickReplyCode { return tOrNil("quickReply.\(code.rawValue)") ?? code.rawValue }
        return message.text ?? ""
    }

    /// Why live location is not shown, as the grey note says it.
    func trackingClosedText(_ reason: String) -> String {
        switch reason {
        case "feature_off": t("bookingTracking.liveDisabled")
        default: tOrNil("trackingWindow.\(reason)") ?? t("error.TRACKING_WINDOW_NOT_OPEN")
        }
    }
}
