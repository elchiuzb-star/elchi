import Foundation
import Observation

// MARK: - Pure rules (Q22, §9.1-9.3)

/// What the commission balance screen derives. Only the commission account is real money here: the fare is cash
/// between the client and the driver and never enters this ledger (no "earnings" are invented, §9).
public enum WalletLogic {
    public struct Tiles: Equatable, Sendable {
        public let heldMinor: Int
        public let reversedMinor: Int
        public let topupsMinor: Int
        public let pendingTopupsMinor: Int
        /// Commission ELCHI captured (the chart's subject).
        public let capturedMinor: Int
    }

    /// Held and pending from the wallet; approved top-ups, reversals and captures summed from the transactions
    /// (web CA:6859-6885).
    public static func tiles(wallet: WalletDTO, lines: [LedgerLineDTO]) -> Tiles {
        func sum(_ kind: String, _ direction: String) -> Int {
            lines.filter { $0.kind == kind && $0.direction == direction }.reduce(0) { $0 + $1.amountMinor }
        }
        return Tiles(heldMinor: wallet.heldMinor, reversedMinor: sum("reversal", "credit"), topupsMinor: sum("topup", "credit"),
                     pendingTopupsMinor: wallet.pendingTopupsMinor, capturedMinor: sum("commission_capture", "debit"))
    }

    public struct Bar: Equatable, Sendable {
        public let day: Date
        public let minor: Int
    }

    /// The last 7 Tashkent days (oldest first) of `commission_capture` debits. All zero = the empty state (in dev a
    /// parcel commission stays held until finance finalizes it, so expect that).
    public static func chart(_ lines: [LedgerLineDTO], now: Date = Date()) -> [Bar] {
        let calendar = DepartureWindow.calendar
        let today = calendar.startOfDay(for: now)
        let days = (0..<7).reversed().compactMap { calendar.date(byAdding: .day, value: -$0, to: today) }
        var totals = Dictionary(uniqueKeysWithValues: days.map { ($0, 0) })
        for line in lines where line.kind == "commission_capture" && line.direction == "debit" {
            guard let at = ServerTime.parse(line.occurredAt) else { continue }
            let day = calendar.startOfDay(for: at)
            if totals[day] != nil { totals[day]! += line.amountMinor }
        }
        return days.map { Bar(day: $0, minor: totals[$0] ?? 0) }
    }

    public static func chartIsEmpty(_ bars: [Bar]) -> Bool { bars.allSatisfy { $0.minor == 0 } }

    /// DESIGN09 2.3: the chart's "7 kun / 6 oy" toggle.
    public enum Period: String, CaseIterable, Sendable {
        case daily, monthly

        public var labelKey: String { "income.period.\(rawValue)" }
    }

    /// The last 6 Tashkent months (oldest first, each bar dated the month's first day) of `commission_capture`
    /// debits - from the pages already loaded only (as the web does; nothing is said about pages not loaded).
    public static func monthlyChart(_ lines: [LedgerLineDTO], now: Date = Date()) -> [Bar] {
        let calendar = DepartureWindow.calendar
        guard let thisMonth = calendar.date(from: calendar.dateComponents([.year, .month], from: now)) else { return [] }
        let months = (0..<6).reversed().compactMap { calendar.date(byAdding: .month, value: -$0, to: thisMonth) }
        var totals = Dictionary(uniqueKeysWithValues: months.map { ($0, 0) })
        for line in lines where line.kind == "commission_capture" && line.direction == "debit" {
            guard let at = ServerTime.parse(line.occurredAt),
                  let month = calendar.date(from: calendar.dateComponents([.year, .month], from: at)) else { continue }
            if totals[month] != nil { totals[month]! += line.amountMinor }
        }
        return months.map { Bar(day: $0, minor: totals[$0] ?? 0) }
    }

    public static func chart(_ lines: [LedgerLineDTO], period: Period, now: Date = Date()) -> [Bar] {
        period == .daily ? chart(lines, now: now) : monthlyChart(lines, now: now)
    }

    /// Mirrors `app/contracts/money.py` `TWO_PERSON_APPROVAL_THRESHOLD_MINOR` (1 000 000 so'm): a top-up above it is
    /// approved by two different finance people (Q17). The API does not expose it - keep the two in step.
    public static let twoPersonThresholdMinor = 100_000_000

    /// "Katta summa: ikki moliya xodimi tasdiqlaydi." under the amount.
    public static func largeAmount(_ amountText: String) -> Bool { Money.minor(fromSoum: amountText) > twoPersonThresholdMinor }

    /// DESIGN09 2.11: the preset chips (whole so'm).
    public static let presetsSoum = [50_000, 100_000, 200_000, 500_000]

    /// DESIGN09 2.7: "To'lov maqsadi: 90 777 11 22" - the driver's own phone in national format (nil without one).
    public static func paymentPurposePhone(_ phone: String?) -> String? {
        guard let phone else { return nil }
        let local = UzPhone.localDigits(fromE164: phone)
        return local.count == 9 ? UzPhone.formatLocal(local) : nil
    }

    public static let methods = ["bank_transfer", "cash_desk"]

    /// `POST /wallet/topups`: a positive whole-so'm amount; optional text fields go only when typed (≤ 128 / 500).
    public static func topupBody(amountText: String, method: String, payerReference: String, note: String) -> TopupCreate? {
        let minor = Money.minor(fromSoum: amountText)
        guard minor > 0, methods.contains(method) else { return nil }
        let payer = payerReference.trimmingCharacters(in: .whitespacesAndNewlines)
        let text = note.trimmingCharacters(in: .whitespacesAndNewlines)
        return TopupCreate(amountMinor: minor, method: method, note: text.isEmpty ? nil : String(text.prefix(500)),
                           payerReference: payer.isEmpty ? nil : String(payer.prefix(128)))
    }

    /// A request's badge: waiting (pending, second approval) in amber, approved green, rejected red.
    public static func status(_ status: TopupStatus) -> StatusLabel {
        switch status {
        case .pending: StatusLabel(key: "status.pending", raw: status.rawValue, tone: .warn)
        case .awaitingSecondApproval: StatusLabel(key: "status.awaiting_second_approval", raw: status.rawValue, tone: .warn)
        case .approved: StatusLabel(key: "status.approved", raw: status.rawValue, tone: .ok)
        case .rejected: StatusLabel(key: "status.rejected", raw: status.rawValue, tone: .err)
        case .unknown(let raw): StatusLabel(key: "status.\(raw)", raw: raw, tone: .gray)
        }
    }

    /// "+" for money in, "−" for money out.
    public static func sign(_ line: LedgerLineDTO) -> String { line.direction == "credit" ? "+" : "−" }

    public static func kindKey(_ line: LedgerLineDTO) -> String { "driver.wallet.kind.\(line.kind)" }
}

// MARK: - Komissiya balansi

@MainActor @Observable
final class WalletModel {
    private let api: ElchiAPI
    private let keys: ActionKeys
    private let banners: BannerCenter
    /// After a top-up or a refresh the home row reads the balance again.
    var onBalanceChanged: (() async -> Void)?

    private(set) var wallet: Loadable<WalletDTO> = .loading
    private(set) var lines: [LedgerLineDTO] = []
    private(set) var linesLoaded = false
    private(set) var linesError: Error?
    private(set) var nextCursor: String?
    private(set) var loadingMore = false
    private(set) var topups: Loadable<[TopupDTO]> = .loading

    var period: WalletLogic.Period = .daily
    var amountText = ""
    var method = "bank_transfer"
    var payerReference = ""
    var note = ""
    private(set) var sending = false
    private(set) var sendError: Error?
    private(set) var attempted = false

    init(api: ElchiAPI, keys: ActionKeys, banners: BannerCenter) {
        self.api = api
        self.keys = keys
        self.banners = banners
    }

    var tiles: WalletLogic.Tiles? { wallet.value.map { WalletLogic.tiles(wallet: $0, lines: lines) } }
    var chart: [WalletLogic.Bar] { WalletLogic.chart(lines, period: period) }
    var body: TopupCreate? { WalletLogic.topupBody(amountText: amountText, method: method, payerReference: payerReference, note: note) }

    func load() async {
        async let wallet: Void = loadWallet()
        async let lines: Void = loadLines()
        async let topups: Void = loadTopups()
        _ = await (wallet, lines, topups)
    }

    private func loadWallet() async {
        do {
            wallet = .loaded(try await api.getMyWallet().data)
        } catch {
            if wallet.value == nil { wallet = .failed(error) }
        }
    }

    private func loadLines() async {
        do {
            let result = try await api.listMyTransactions(limit: 50)
            lines = result.data
            nextCursor = result.meta?.nextCursor
            linesError = nil
        } catch {
            linesError = error
        }
        linesLoaded = true
    }

    func loadMore() async {
        guard let cursor = nextCursor, !loadingMore else { return }
        loadingMore = true
        defer { loadingMore = false }
        guard let result = try? await api.listMyTransactions(cursor: cursor, limit: 50) else { return }
        let known = Set(lines.map(\.transactionId))
        lines += result.data.filter { !known.contains($0.transactionId) }
        nextCursor = result.meta?.nextCursor
    }

    private func loadTopups() async {
        do {
            topups = .loaded(try await api.listMyTopups(limit: 20).data)
        } catch {
            if topups.value == nil { topups = .failed(error) }
        }
    }

    /// "So'rov yuborish": pending until finance approves (it is not money yet, §9.2).
    func submit() async {
        attempted = true
        guard let body, !sending else { return }
        let action = "topup:\(body.amountMinor):\(body.method):\(body.payerReference ?? ""):\(body.note ?? "")"
        sending = true
        sendError = nil
        defer { sending = false }
        do {
            _ = try await api.createMyTopup(body: body, idempotencyKey: keys.key(action)).data
            keys.settle(action)
            amountText = ""
            payerReference = ""
            note = ""
            attempted = false
            banners.ok("income.topupSent")
            await load()
            await onBalanceChanged?()
        } catch {
            keys.settle(action, after: error)
            sendError = error
        }
    }
}
