package uz.elchi.app.feature.client

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import uz.elchi.app.R
import uz.elchi.app.api.generated.CashReceiptDTO
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.CardRow
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiField
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.SectionTitle
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone

// -- seats --------------------------------------------------------------------------------------------------------

/** `2 kishi · 2 × 150 000 so'm` - a passenger listing or booking's people and its per-seat price. */
@Composable
internal fun seatsLine(count: Long, unitMinor: Long): String =
    "${t(R.string.orderForm_review_peopleCount, "count" to count)} · ${t(R.string.client_taxi_seatsTotal, "count" to count, "price" to soum(unitMinor))}"

/** `2 × 150 000 so'm` */
@Composable
internal fun seatsPrice(count: Long, unitMinor: Long): String = t(R.string.client_taxi_seatsTotal, "count" to count, "price" to soum(unitMinor))

// -- cash record (both sides) ---------------------------------------------------------------------------------------

/** What the cash block needs from its screen: the amounts, the receipt and the commands. */
internal class CashBlockModel(
    val side: String,
    val dueMinor: Long,
    val promo: Boolean,
    val cashStatus: String?,
    val receipt: CashReceiptDTO?,
    val amountDigits: String,
    val note: String,
    val contestComment: String,
    val busy: Boolean,
    val error: Throwable?,
    val onAmount: (String) -> Unit,
    val onNote: (String) -> Unit,
    val onContestComment: (String) -> Unit,
    val onReport: () -> Unit,
    val onAcknowledge: () -> Unit,
    val onContest: () -> Unit,
)

/**
 * "Naqd to'lov qaydi" (design `cash-ack`, web `CashAcknowledgement`): a record that cash changed hands between two
 * people - ELCHI neither receives nor settles it. One side records the handover (a differing amount needs a note),
 * the other confirms it or contests it (with a comment); a contested record goes to the operator (Q78).
 */
@Composable
internal fun CashRecordBlock(m: CashBlockModel) {
    val c = Elchi.colors
    val driver = m.side == "driver"
    SectionTitle(t(R.string.app_cash_title), description = t(R.string.app_cash_explainer))
    Text(
        "${t(if (m.promo) R.string.app_cash_dueLabel else R.string.app_cash_agreedLabel)}: ${soum(m.dueMinor)}",
        style = Elchi.type.secondary.copy(fontWeight = FontWeight.SemiBold),
        color = c.text,
    )
    val receipt = m.receipt
    when (TaxiRules.cashView(m.cashStatus, receipt, m.side)) {
        CashView.REPORT -> {
            ElchiField(
                m.amountDigits,
                m.onAmount,
                label = t(if (driver) R.string.app_cash_receivedField else R.string.app_cash_givenField),
                placeholder = ParcelRules.groupThousands(ParcelRules.minorToSoum(m.dueMinor)),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Next),
                visualTransformation = ThousandsTransformation,
            )
            val amount = ParcelRules.soumToMinor(m.amountDigits)
            if (TaxiRules.cashNoteRequired(amount, m.dueMinor)) {
                ElchiField(
                    m.note,
                    m.onNote,
                    label = t(R.string.listingOwner_commentLabel),
                    singleLine = false,
                    minHeight = 72.dp,
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
                    // The amount differs from the cash due: the server asks why.
                    hint = t(R.string.app_cash_noteRequired),
                )
            }
            ElchiButton(
                t(if (driver) R.string.app_cash_markReceived else R.string.app_cash_markGiven),
                m.onReport,
                Modifier.fillMaxWidth(),
                enabled = amount != null && (!TaxiRules.cashNoteRequired(amount, m.dueMinor) || m.note.isNotBlank()),
                loading = m.busy,
            )
        }
        CashView.AWAITING_OTHER -> ElchiCard {
            receipt?.let { CardRow(t(R.string.app_cash_title), cashReportedText(it, mine = true), first = true, detail = t(R.string.app_cash_awaitingOther)) }
                ?: CardRow(t(R.string.app_cash_title), t(R.string.app_cash_awaitingOther), first = true)
        }
        CashView.DECIDE -> {
            if (receipt != null) {
                // Design 04: "Naqd to'lovni tasdiqlang" with the amount the other side recorded.
                ElchiCard(padding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp, vertical = 12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Text(t(R.string.client_booking_cashConfirmTitle), Modifier.weight(1f), style = Elchi.type.label.copy(fontWeight = FontWeight.Normal), color = c.muted)
                        Text(soum(receipt.amountMinor), style = Elchi.type.secondary.copy(fontWeight = FontWeight.SemiBold, fontSize = 15.sp), color = c.text, maxLines = 1)
                    }
                    Text(cashReportedText(receipt, mine = false), Modifier.padding(top = 4.dp), style = Elchi.type.caption, color = c.muted)
                }
                ElchiField(
                    m.contestComment,
                    m.onContestComment,
                    label = t(R.string.common_reason),
                    singleLine = false,
                    minHeight = 64.dp,
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
                    hint = t(R.string.driver_trip_reasonHint),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    // Design 04: "Rozi emasman" first, "Tasdiqlayman" (the brand button) on the right.
                    ElchiButton(
                        t(R.string.app_cash_contest), m.onContest, Modifier.weight(1f).height(48.dp), ButtonVariant.DANGER_SOFT, ButtonSize.MEDIUM,
                        enabled = !m.busy && m.contestComment.isNotBlank(), horizontalPadding = 10.dp,
                    )
                    ElchiButton(t(R.string.app_cash_acknowledge), m.onAcknowledge, Modifier.weight(1f).height(48.dp), size = ButtonSize.MEDIUM, enabled = !m.busy, loading = m.busy, horizontalPadding = 10.dp)
                }
            }
        }
        CashView.BOTH_CONFIRMED -> Note(t(R.string.app_cash_bothConfirmed), tone = Tone.OK)
        CashView.CONTESTED -> Note(t(R.string.app_cash_contested), tone = Tone.ERR)
    }
    m.error?.let { Note(errorText(it), tone = Tone.ERR) }
}

/** "Siz qayd qildingiz: 300 000 so'm · 27.09, 14:20" / "Ikkinchi tomon qayd qildi: …". */
@Composable
private fun cashReportedText(receipt: CashReceiptDTO, mine: Boolean): String {
    val date = OrderRules.tashkent(receipt.reportedAt)?.let { ParcelRules.displayShort(it) } ?: receipt.reportedAt
    return t(if (mine) R.string.app_cash_reportedByMe else R.string.app_cash_reportedByOther, "amount" to soum(receipt.amountMinor), "date" to date)
}
