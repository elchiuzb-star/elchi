package uz.elchi.app.feature.driver

import uz.elchi.app.api.generated.LedgerLineDTO
import uz.elchi.app.api.generated.TopupCreate
import uz.elchi.app.api.generated.TopupStatus
import uz.elchi.app.feature.client.OrderRules
import uz.elchi.app.feature.client.ParcelRules
import uz.elchi.app.ui.theme.Tone
import java.time.Instant
import java.time.LocalDate
import java.time.YearMonth

/** The four tiles under the balance (web ConnectedApp.tsx:6862): sums of what the ledger really recorded. */
data class WalletTiles(val capturedMinor: Long, val reversedMinor: Long, val topupsMinor: Long)

/** One bar of the 7-day chart: a Tashkent day and the commission captured on it. */
data class ChartDay(val day: LocalDate, val minor: Long)

/** The chart's period toggle "7 kun / 6 oy" (design 09 2.3, web ConnectedApp.tsx:7180). */
enum class ChartPeriod { DAILY, MONTHLY }

/** One bar of the 6-month chart: a Tashkent calendar month and the commission captured in it (loaded pages only). */
data class ChartMonth(val month: YearMonth, val minor: Long)

/**
 * "Komissiya balansi" (§9.1-9.3): only the commission account is money here. `commission_capture` is what ELCHI took,
 * `reversal` what it gave back, `topup` what the driver paid in; the fare never enters this ledger (cash between the
 * client and the driver), so nothing here is "earnings" (AGENTS §9). A pending top-up is a request, not money.
 */
object WalletRules {
    const val KIND_TOPUP = "topup"
    const val KIND_CAPTURE = "commission_capture"
    const val KIND_REVERSAL = "reversal"
    const val KIND_ADJUSTMENT = "adjustment"
    const val CREDIT = "credit"
    const val DEBIT = "debit"

    /** `TopupCreate.method`; bank transfer first (the default). */
    val METHODS = listOf("bank_transfer", "cash_desk")

    const val CHART_DAYS = 7
    const val PAYER_REFERENCE_MAX = 128
    const val NOTE_MAX = 500

    fun tiles(lines: List<LedgerLineDTO>): WalletTiles = WalletTiles(
        capturedMinor = sum(lines, KIND_CAPTURE, DEBIT),
        reversedMinor = sum(lines, KIND_REVERSAL, CREDIT),
        topupsMinor = sum(lines, KIND_TOPUP, CREDIT),
    )

    private fun sum(lines: List<LedgerLineDTO>, kind: String, direction: String): Long =
        lines.filter { it.kind == kind && it.direction == direction }.sumOf { it.amountMinor }

    /** The last [days] Tashkent days, oldest first, each with the commission captured that day (zero when none). */
    fun chart(lines: List<LedgerLineDTO>, now: Instant, days: Int = CHART_DAYS): List<ChartDay> {
        val today = now.atZone(ParcelRules.TASHKENT).toLocalDate()
        val range = (days - 1 downTo 0).map { today.minusDays(it.toLong()) }
        val byDay = lines.filter { it.kind == KIND_CAPTURE && it.direction == DEBIT }
            .mapNotNull { line -> OrderRules.parseInstant(line.occurredAt)?.atZone(ParcelRules.TASHKENT)?.toLocalDate()?.let { it to line.amountMinor } }
            .groupBy({ it.first }, { it.second })
        return range.map { day -> ChartDay(day, byDay[day]?.sum() ?: 0L) }
    }

    const val CHART_MONTHS = 6

    /**
     * The last [months] Tashkent calendar months, oldest first, each with the commission captured in it - summed from
     * the movements already loaded (as the web does): nothing is said about older pages that were not read.
     */
    fun monthly(lines: List<LedgerLineDTO>, now: Instant, months: Int = CHART_MONTHS): List<ChartMonth> {
        val current = YearMonth.from(now.atZone(ParcelRules.TASHKENT))
        val range = (months - 1 downTo 0).map { current.minusMonths(it.toLong()) }
        val byMonth = lines.filter { it.kind == KIND_CAPTURE && it.direction == DEBIT }
            .mapNotNull { line -> OrderRules.parseInstant(line.occurredAt)?.atZone(ParcelRules.TASHKENT)?.let { YearMonth.from(it) to line.amountMinor } }
            .groupBy({ it.first }, { it.second })
        return range.map { month -> ChartMonth(month, byMonth[month]?.sum() ?: 0L) }
    }

    /**
     * `TWO_PERSON_APPROVAL_THRESHOLD_MINOR` (`app/contracts/money.py`, Q17): a top-up above 1 000 000 so'm needs a second
     * finance approver. The API does not expose it, so it is mirrored here - keep the two equal.
     */
    const val TWO_PERSON_APPROVAL_THRESHOLD_MINOR = 100_000_000L

    /** "Katta summa: ikki moliya xodimi tasdiqlaydi." under the amount (design 09 2.10). */
    fun largeAmount(amountDigits: String): Boolean = (ParcelRules.soumToMinor(amountDigits) ?: 0L) > TWO_PERSON_APPROVAL_THRESHOLD_MINOR

    /** The preset chips (design 09 2.11), whole so'm. */
    val PRESETS: List<Long> = listOf(50_000L, 100_000L, 200_000L, 500_000L)

    /**
     * "To'lov maqsadi: 90 777 11 22" (design 09 2.7): the driver's own number without the country code, grouped
     * 2-3-2-2; null for a number that is not an Uzbek mobile one (then the line is not shown).
     */
    fun paymentPurposePhone(phone: String?): String? {
        val digits = phone?.filter(Char::isDigit) ?: return null
        val national = when {
            digits.length == 12 && digits.startsWith("998") -> digits.substring(3)
            digits.length == 9 -> digits
            else -> return null
        }
        return "${national.substring(0, 2)} ${national.substring(2, 5)} ${national.substring(5, 7)} ${national.substring(7, 9)}"
    }

    /** No capture in the window: the chart's empty state (in dev parcel commissions stay held until finance acts). */
    fun chartEmpty(chart: List<ChartDay>): Boolean = chart.all { it.minor == 0L }

    /**
     * `POST /wallet/topups` body: whole so'm > 0 (minor units on the wire), a known method, the optional payer
     * reference and note trimmed (empty = not sent). Null when the amount cannot be sent. No receipt: the API has no
     * upload type for it.
     */
    fun topupBody(amountDigits: String, method: String, payerReference: String, note: String): TopupCreate? {
        val amount = ParcelRules.soumToMinor(amountDigits) ?: return null
        if (method !in METHODS) return null
        return TopupCreate(
            amountMinor = amount,
            method = method,
            payerReference = payerReference.trim().take(PAYER_REFERENCE_MAX).takeIf { it.isNotEmpty() },
            note = note.trim().take(NOTE_MAX).takeIf { it.isNotEmpty() },
        )
    }

    /** `status.<status>` - `awaiting_second_approval` has its own word (`status.awaiting_second_approval`). */
    fun topupStatusKey(status: TopupStatus): String = "status.${status.value.ifEmpty { "pending" }}"

    fun topupTone(status: TopupStatus): Tone = when (status) {
        TopupStatus.APPROVED -> Tone.OK
        TopupStatus.REJECTED -> Tone.ERR
        TopupStatus.PENDING, TopupStatus.AWAITING_SECOND_APPROVAL -> Tone.WARN
        TopupStatus.UNKNOWN -> Tone.GRAY
    }

    /** A credit adds to the balance, a debit takes from it. */
    fun signed(line: LedgerLineDTO): String = if (line.direction == CREDIT) "+" else "−"
}
