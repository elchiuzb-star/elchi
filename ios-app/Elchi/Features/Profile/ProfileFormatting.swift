import Foundation

/// How the Stage 05 screens say notifications, dates and the app version in the active language.
extension LocaleStore {
    func inboxTitle(_ item: NotificationDTO) -> String {
        let params = Inbox.params(item)
        return Inbox.title(item) { tOrNil($0, values: params) }
    }

    func inboxBody(_ item: NotificationDTO) -> String {
        let params = Inbox.params(item)
        return Inbox.body(item) { tOrNil($0, values: params) }
    }

    /// `10:24` today, `Kecha, 08:12` yesterday, `12 sen` earlier this year, `12.09.2025` before that.
    func inboxTime(_ createdAt: String, now: Date = Date()) -> String {
        guard let date = ServerTime.parse(createdAt) else { return "" }
        switch InboxTime.of(date, now: now) {
        case .today:
            return clock(date)
        case .yesterday:
            return t("client.notifications.yesterday", ("time", clock(date)))
        case .earlier(let sameYear):
            return sameYear ? dayMonth(date) : dateOnly(date)
        }
    }

    /// `21.09.2026` (Tashkent).
    func dateOnly(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = DepartureWindow.timeZone
        formatter.dateFormat = "dd.MM.yyyy"
        return formatter.string(from: date)
    }

    func dateOnly(_ text: String?) -> String? { ServerTime.parse(text).map(dateOnly) }

    /// "Bloklangan: 14.09.2026".
    func blockedAt(_ text: String) -> String { t("client.safety.blockedAt", ("date", dateOnly(text) ?? text)) }

    /// `Mijoz bonusi · pochta`.
    func bucketTitle(_ bucket: PromoBucketDTO) -> String {
        let instrument = switch bucket.instrument {
        case .passengerBonus: t("promo.instrument.passengerBonus")
        case .driverCredit: t("promo.instrument.driverCredit")
        case .unknown(let raw): raw
        }
        let service = bucket.serviceType == .parcel ? t("promoScreen.service.parcel") : t("promoScreen.service.passenger")
        return "\(instrument) · \(service)"
    }

    /// A campaign's status: the qualification step when there is one, else the enrolment state.
    func enrollmentStatus(_ enrollment: EnrollmentDTO) -> String {
        let qualification: [String: String] = ["waiting": "promo.qualification.waiting", "review": "promo.qualification.review",
                                               "qualified": "promo.qualification.qualified",
                                               "granted": "notification.promo.reward_granted.title", "rejected": "amendment.rejected"]
        let enrolment: [String: String] = ["promised": "promo.enrollment.promised", "granted": "notification.promo.reward_granted.title",
                                           "released": "promo.enrollment.released", "rejected": "amendment.rejected"]
        if let status = enrollment.qualificationStatus, let key = qualification[status] { return t(key) }
        return enrolment[enrollment.status].map { t($0) } ?? enrollment.status
    }

    /// The app's version name for the settings footer.
    var appVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "?"
    }
}
