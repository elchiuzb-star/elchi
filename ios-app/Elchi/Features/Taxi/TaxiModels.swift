import Foundation
import Observation

// MARK: - Naqd to'lov qaydi (both sides)

/// The cash record of one passenger booking, from one side: record the handover (`POST /cash-receipts`), or answer
/// the other side's record - confirm it or contest it (an operator then decides, Q78). Nothing here moves money.
@MainActor @Observable
final class CashRecordModel {
    enum Command: Equatable { case report, acknowledge, contest }

    let bookingId: String
    /// "client" or "driver".
    let side: String
    private let api: ElchiAPI
    private let keys: ActionKeys
    /// After any answer the booking is read again (its `cash_status` and version moved).
    var onChanged: (@MainActor () async -> Void)?

    private(set) var running: Command?
    private(set) var error: Error?
    private(set) var failed: Command?
    private(set) var notice: String?

    init(bookingId: String, side: String, api: ElchiAPI, keys: ActionKeys) {
        self.bookingId = bookingId
        self.side = side
        self.api = api
        self.keys = keys
    }

    func clear() {
        error = nil
        failed = nil
        notice = nil
    }

    /// Records the amount as handed over (the booking version guards it; a note when it differs from what is due).
    func report(version: Int, amountMinor: Int, dueMinor: Int, note: String) async -> Bool {
        guard running == nil, let body = CashRecord.report(version: version, amountMinor: amountMinor, dueMinor: dueMinor, note: note) else {
            return false
        }
        let action = "cash:\(bookingId):\(version):\(amountMinor)"
        return await run(.report, action: action, notice: side == "driver" ? "driverBooking.cashRecorded" : "bookingDetail.cashRecorded") {
            api, key in _ = try await api.reportCashReceipt(bookingId: self.bookingId, body: body, idempotencyKey: key)
        }
    }

    func acknowledge(_ receipt: CashReceiptDTO) async -> Bool {
        let body = CashRecord.acknowledge(receipt)
        return await run(.acknowledge, action: "cash-ack:\(receipt.id):\(receipt.version)", notice: answeredKey) { api, key in
            _ = try await api.acknowledgeCashReceipt(bookingId: self.bookingId, receiptId: receipt.id, body: body, idempotencyKey: key)
        }
    }

    func contest(_ receipt: CashReceiptDTO, comment: String) async -> Bool {
        guard let body = CashRecord.contest(receipt, comment: comment) else { return false }
        return await run(.contest, action: "cash-contest:\(receipt.id):\(receipt.version)", notice: answeredKey) { api, key in
            _ = try await api.contestCashReceipt(bookingId: self.bookingId, receiptId: receipt.id, body: body, idempotencyKey: key)
        }
    }

    private var answeredKey: String { side == "driver" ? "driverBooking.cashAnswered" : "bookingDetail.answerSaved" }

    private func run(_ command: Command, action: String, notice noticeKey: String,
                     _ send: (ElchiAPI, String) async throws -> Void) async -> Bool {
        guard running == nil else { return false }
        running = command
        clear()
        defer { running = nil }
        do {
            try await send(api, keys.key(action))
            keys.settle(action)
            notice = noticeKey
            await onChanged?()
            return true
        } catch {
            keys.settle(action, after: error)
            self.error = error
            failed = command
            // The other side answered first, or the booking moved: show where it is now.
            if (error as? APIError)?.code != APIError.network { await onChanged?() }
            return false
        }
    }
}

// MARK: - The driver's passenger commands

/// "Yo'lovchini chiqardim" (board), "Yo'lovchini tushirdim" (drop-off) and "Mijoz kelmadi"
/// (report_no_show, Q7) on one booking, plus what the no-show gate needs: when "Keldim" was recorded (the tracking
/// view's `driver_arrived_at`, else this phone's own record) and the trip's announced wait.
@MainActor @Observable
final class DriverTaxiModel {
    enum Command: Equatable { case board, dropOff, noShow }

    let bookingId: String
    private let api: ElchiAPI
    private let keys: ActionKeys
    /// A command answered with the booking: the detail takes it (or reads it again).
    var onBooking: (@MainActor (JSONValue?) async -> Void)?

    private(set) var running: Command?
    private(set) var error: Error?
    private(set) var failed: Command?
    private(set) var notice: String?
    /// When "Keldim" was recorded on the server, when known.
    private(set) var arrivedAt: Date?
    /// The trip's announced wait at the pickup (`pickup_wait_minutes`), 10 until read.
    private(set) var waitMinutes = NoShowGate.defaultWaitMinutes

    init(bookingId: String, api: ElchiAPI, keys: ActionKeys) {
        self.bookingId = bookingId
        self.api = api
        self.keys = keys
        arrivedAt = ArrivedSignals.at(bookingId)
    }

    func clear() {
        error = nil
        failed = nil
        notice = nil
    }

    /// The arrival time and the trip's wait, for a booking that awaits its passenger.
    func loadGate(tripId: String) async {
        if let tracking = try? await api.getBookingTracking(bookingId: bookingId).data, let at = ServerTime.parse(tracking.driverArrivedAt) {
            arrivedAt = at
            ArrivedSignals.mark(bookingId, at: at)
        }
        if let trip = try? await api.getTrip(tripId: tripId).data, case .number(let minutes)? = trip["pickup_wait_minutes"] {
            waitMinutes = Int(minutes)
        }
    }

    /// "Keldim" just went through on this phone.
    func arrived(at date: Date) {
        if arrivedAt == nil { arrivedAt = date }
    }

    func unlocksAt(windowStart: Date?) -> Date? {
        NoShowGate.unlocksAt(arrivedAt: arrivedAt, windowStart: windowStart, waitMinutes: waitMinutes)
    }

    /// Q163: boarding takes no code - the driver's tap alone.
    func board(version: Int) async -> Bool {
        await run(.board, action: "board:\(bookingId):\(version)", notice: "driverBooking.statusUpdated") { api, key in
            try await api.bookingAction(bookingId: self.bookingId, action: .board, body: BookingActionRequest(expectedVersion: version),
                                        idempotencyKey: key).data
        }
    }

    func dropOff(version: Int) async -> Bool {
        await run(.dropOff, action: "drop-off:\(bookingId):\(version)", notice: "driverBooking.statusUpdated") { api, key in
            try await api.bookingAction(bookingId: self.bookingId, action: .dropOff, body: BookingActionRequest(expectedVersion: version),
                                        idempotencyKey: key).data
        }
    }

    func reportNoShow(version: Int, channels: Set<NoShowChannel>) async -> Bool {
        guard let body = NoShowReport.body(version: version, channels: channels) else { return false }
        return await run(.noShow, action: "no-show:\(bookingId):\(version)", notice: "driver.noShow.sent") { api, key in
            try await api.bookingAction(bookingId: self.bookingId, action: .reportNoShow, body: body, idempotencyKey: key).data
        }
    }

    private func run(_ command: Command, action: String, notice noticeKey: String,
                     _ send: (ElchiAPI, String) async throws -> JSONValue) async -> Bool {
        guard running == nil else { return false }
        running = command
        clear()
        defer { running = nil }
        do {
            let json = try await send(api, keys.key(action))
            keys.settle(action)
            notice = noticeKey
            await onBooking?(json)
            return true
        } catch {
            keys.settle(action, after: error)
            self.error = error
            failed = command
            // Anything but a dropped connection may mean the booking moved on: read it again.
            if let code = (error as? APIError)?.code, code != APIError.network { await onBooking?(nil) }
            return false
        }
    }
}
