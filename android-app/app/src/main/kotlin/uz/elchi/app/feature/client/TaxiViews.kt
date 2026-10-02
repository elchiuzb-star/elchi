package uz.elchi.app.feature.client

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import uz.elchi.app.R
import uz.elchi.app.api.generated.CashReceiptDTO
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.CardRow
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiField
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.SectionTitle
import uz.elchi.app.ui.icons.ElchiIcon
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

/**
 * The design's `seat-picker`: the cabin drawn as three by two cells - the driver's seat (drawn, never offered), the
 * front seat, the three rear seats. A tap marks or unmarks a seat (never the last one); the number on a marked seat is
 * the order it was picked in. Below, once: the booking is the count, the exact seat is agreed with the driver.
 */
@Composable
internal fun SeatPicker(selected: List<String>, onToggle: (String) -> Unit) {
    val c = Elchi.colors
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text(t(R.string.seatPicker_howMany), Modifier.weight(1f), style = Elchi.type.label, color = c.muted)
            Text(t(R.string.seatPicker_peopleCount, "count" to selected.size), style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold), color = c.text)
        }
        Column(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(c.field).padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                DriverSeat()
                Spacer(Modifier.weight(1f))
                SeatCell(Seat.FRONT, selected, onToggle)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SeatCell(Seat.REAR_LEFT, selected, onToggle)
                SeatCell(Seat.REAR_MIDDLE, selected, onToggle)
                SeatCell(Seat.REAR_RIGHT, selected, onToggle)
            }
        }
        Text(
            buildAnnotatedString {
                append(t(R.string.seatPicker_bookedIs))
                append(" ")
                withStyle(SpanStyle(fontWeight = FontWeight.SemiBold, color = c.text)) { append(t(R.string.seatPicker_seatCount)) }
                append(t(R.string.seatPicker_seatNotReserved))
            },
            style = Elchi.type.caption,
            color = c.muted,
        )
    }
}

@Composable
private fun RowScope.DriverSeat() {
    val c = Elchi.colors
    val dash = c.outline
    Column(
        Modifier
            .weight(1f)
            .height(SEAT_HEIGHT)
            .clip(RoundedCornerShape(14.dp))
            .background(c.card.copy(alpha = 0.5f))
            .drawBehind {
                drawRoundRect(
                    dash,
                    cornerRadius = CornerRadius(14.dp.toPx()),
                    style = Stroke(width = 2.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(5.dp.toPx(), 4.dp.toPx()))),
                )
            },
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Box(Modifier.size(18.dp).border(2.dp, c.placeholder, CircleShape))
        Text(t(R.string.seatPicker_driver), Modifier.padding(top = 4.dp), style = Elchi.type.badge.copy(fontSize = 10.sp), color = c.placeholder)
    }
}

@Composable
private fun RowScope.SeatCell(seat: Seat, selected: List<String>, onToggle: (String) -> Unit) {
    val c = Elchi.colors
    val order = TaxiRules.seatOrder(selected, seat.id)
    val on = order != null
    val label = tOrNull(seat.key) ?: seat.id
    val shape = RoundedCornerShape(14.dp)
    Box(
        Modifier
            .weight(1f)
            .height(SEAT_HEIGHT)
            .clip(shape)
            .background(if (on) c.highlight else c.card)
            .border(if (on) 2.dp else 1.5.dp, if (on) c.brand else c.outline, shape)
            .toggleable(value = on, role = Role.Checkbox, onValueChange = { onToggle(seat.id) })
            .semantics { contentDescription = label },
    ) {
        Column(Modifier.align(Alignment.Center).padding(horizontal = 4.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            // A seat, drawn: a back and a cushion read as a seat at this size.
            val seatColor = if (on) c.brand else c.placeholder
            Box(Modifier.width(22.dp).height(12.dp).clip(RoundedCornerShape(topStart = 6.dp, topEnd = 6.dp)).border(2.dp, seatColor, RoundedCornerShape(topStart = 6.dp, topEnd = 6.dp)))
            Box(Modifier.width(28.dp).height(7.dp).clip(RoundedCornerShape(bottomStart = 4.dp, bottomEnd = 4.dp)).background(seatColor.copy(alpha = 0.35f)))
            Text(label, Modifier.padding(top = 4.dp), style = Elchi.type.badge.copy(fontSize = 10.sp, fontWeight = FontWeight.Medium), color = if (on) c.text else c.muted, textAlign = TextAlign.Center, maxLines = 2)
        }
        if (order != null) {
            Box(
                Modifier.align(Alignment.TopEnd).padding(5.dp).size(18.dp).clip(CircleShape).background(c.brand),
                contentAlignment = Alignment.Center,
            ) {
                Text(order.toString(), style = Elchi.type.badge, color = c.onBrand)
            }
        }
    }
}

private val SEAT_HEIGHT = 72.dp

// -- boarding code (client) ---------------------------------------------------------------------------------------

/**
 * "Chiqish kodi": the 6 digits the passenger says to the driver at the car (design `B.code`), and "Yangi kod olish"
 * (the old code stops at once; 3 a day, 2 minutes apart - Q75). Hidden once onboard or closed (the server sends none).
 */
@Composable
internal fun BoardingCodeBlock(s: BookingViewModel.State, onReissue: () -> Unit) {
    val c = Elchi.colors
    val code = s.boardingCode ?: return
    ElchiCard(padding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp, vertical = 14.dp)) {
        Text(t(R.string.proofCode_boarding_code), style = Elchi.type.caption, color = c.muted)
        Text(
            code.chunked(3).joinToString(" "),
            Modifier.padding(vertical = 6.dp).semantics { contentDescription = code.toList().joinToString(" ") },
            style = Elchi.type.title.copy(fontFamily = FontFamily.Monospace, fontSize = 34.sp, lineHeight = 40.sp, letterSpacing = 4.sp, fontWeight = FontWeight.SemiBold),
            color = c.text,
        )
        Text(t(R.string.proofHint_boarding), style = Elchi.type.caption, color = c.muted)
    }
    ElchiButton(t(R.string.reissue_button), onReissue, Modifier.fillMaxWidth(), ButtonVariant.NEUTRAL, icon = ElchiIcon.REFRESH, loading = s.reissuing)
    Text(t(R.string.reissue_hint), style = Elchi.type.caption, color = c.muted)
    if (s.reissued) Note(t(R.string.reissue_done), tone = Tone.OK)
    s.reissueError?.let { e ->
        val limit = TaxiRules.reissueLimit(e)
        val text = if (limit != null) {
            listOfNotNull(
                limit.first?.let { reissueWaitText(TaxiRules.reissueWait(it)) } ?: errorText(e),
                limit.second?.let { t(R.string.reissue_left, "count" to it) },
            ).joinToString(" ")
        } else {
            errorText(e)
        }
        Note(text, tone = if (limit != null) Tone.WARN else Tone.ERR)
    }
}

@Composable
private fun reissueWaitText(wait: ReissueWait): String = when (wait) {
    is ReissueWait.Minutes -> t(R.string.reissue_waitMinutes, "minutes" to wait.minutes, "seconds" to wait.seconds)
    is ReissueWait.Hours -> t(R.string.reissue_waitHours, "hours" to wait.hours, "minutes" to wait.minutes)
}

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
                ElchiCard { CardRow(t(R.string.app_cash_title), cashReportedText(receipt, mine = false), first = true) }
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
                    ElchiButton(t(R.string.app_cash_acknowledge), m.onAcknowledge, Modifier.weight(1f).height(48.dp), size = ButtonSize.MEDIUM, enabled = !m.busy, loading = m.busy, horizontalPadding = 10.dp)
                    ElchiButton(
                        t(R.string.app_cash_contest), m.onContest, Modifier.weight(1f).height(48.dp), ButtonVariant.DANGER_SOFT, ButtonSize.MEDIUM,
                        enabled = !m.busy && m.contestComment.isNotBlank(), horizontalPadding = 10.dp,
                    )
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
