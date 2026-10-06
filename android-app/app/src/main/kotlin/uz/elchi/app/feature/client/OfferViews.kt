package uz.elchi.app.feature.client

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.produceState
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import kotlinx.coroutines.delay
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import uz.elchi.app.R
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.generated.ApiWarning
import uz.elchi.app.api.generated.ProposalDriverSummaryDTO
import uz.elchi.app.api.generated.ProposalPromoClientDTO
import uz.elchi.app.api.generated.ProposalThreadDTO
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.Banner
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiField
import uz.elchi.app.ui.components.MoneyBlock
import uz.elchi.app.ui.components.MoneyRow
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone
import java.time.Instant

// Pieces shared by the bids screen of one listing and "Takliflarim".

/** The clock the countdowns and the local expiry read; ticks every second while the screen is shown. */
@Composable
internal fun rememberNow(): State<Instant> = produceState(Instant.now()) {
    while (true) {
        delay(1_000)
        value = Instant.now()
    }
}

/** `120 000 so'm` */
@Composable
internal fun soum(minor: Long): String = ParcelRules.formatSoum(minor, t(R.string.common_soum))

/** "Haydovchi #3" in the app's language; the server's label as it is when it carries no number. */
@Composable
internal fun driverLabel(thread: ProposalThreadDTO): String =
    driverNumber(thread)?.let { t(R.string.client_listingBids_driver, "number" to it) } ?: thread.driver.label

internal fun driverNumber(thread: ProposalThreadDTO): String? = Regex("#(\\d+)").find(thread.driver.label)?.groupValues?.get(1)

/** "Yengil avtomobil · 4 o'rin · Yaxshi baholangan · 12 ta baho" - the anonymous set the client compares by (Q40). */
@Composable
internal fun driverSummary(summary: ProposalDriverSummaryDTO): String {
    val vehicle = tOrNull("vehicleClass.${summary.vehicleClass}") ?: summary.vehicleClass
    val head = t(R.string.app_rivalBoard_vehicleSeats, "vehicle" to vehicle, "seats" to summary.seatCapacity)
    val bucket = summary.ratingBucket?.let { tOrNull("ratingBucket.${it.value}") }
    val count = summary.ratingCount ?: 0
    // A group is never shown as if it were a number (U6): with no ratings yet the sentence says so.
    val rating = when {
        bucket != null && count > 0 -> t(R.string.app_rivalBoard_ratings, "bucket" to bucket, "count" to count)
        bucket != null -> "$bucket · ${t(R.string.listingBids_noRatingsYet)}"
        else -> t(R.string.listingBids_noRatingsYet)
    }
    return "$head · $rating"
}

/** "1 soat 40 daqiqa qoldi" */
@Composable
internal fun countdownText(seconds: Long): String {
    val (hours, minutes) = OrderRules.countdownParts(seconds)
    val time = when {
        hours > 0 && minutes > 0 -> t(R.string.app_duration_hoursMinutes, "hours" to hours, "minutes" to minutes)
        hours > 0 -> t(R.string.app_duration_hours, "hours" to hours)
        else -> t(R.string.app_duration_minutes, "minutes" to minutes)
    }
    return t(R.string.client_offers_timeLeft, "time" to time)
}

/** "Muddati tugagan", "Rad etildi", "Boshqa haydovchi tanlandi" ... - why a closed offer closed. */
@Composable
internal fun closedReason(thread: ProposalThreadDTO, now: Instant): String {
    val key = OrderRules.closedReasonKey(thread, now)
    return tOrNull(key) ?: key.substringAfterLast('.')
}

/** "12 daqiqa oldin" */
@Composable
internal fun agoText(ago: OrderRules.Ago): String = when (ago) {
    is OrderRules.Ago.Minutes -> t(R.string.publicTracking_minutesAgo, "minutes" to ago.value)
    is OrderRules.Ago.Hours -> t(R.string.client_time_hoursAgo, "hours" to ago.value)
    is OrderRules.Ago.Days -> t(R.string.client_time_daysAgo, "days" to ago.value)
}

/**
 * An offer command's refusal in words the client can act on. The driver's wallet or eligibility is said neutrally
 * (it is not the client's fault, and no blame is put on the driver); a changed listing says so.
 */
@Composable
internal fun offerErrorText(error: Throwable): String {
    val api = error as? ApiException ?: return errorText(error)
    if (api.code in OfferBoard.DRIVER_SIDE) return t(R.string.client_listingBids_driverCannotTake)
    if (api.code == "PROPOSAL_CHANGED") {
        val reason = ((api.details as? JsonObject)?.get("reason") as? JsonPrimitive)?.contentOrNull
        when (reason) {
            "listing_terms_version_mismatch", "listing_terms_changed" -> return t(R.string.client_listingBids_termsChanged)
            "demand_already_booked" -> return t(R.string.client_listingBids_alreadyBooked)
        }
    }
    return errorText(error)
}

/** A share-link refusal: `too_many_active` names the limit (5). */
@Composable
internal fun shareErrorText(error: Throwable): String {
    val details = (error as? ApiException)?.details as? JsonObject
    val reason = (details?.get("reason") as? JsonPrimitive)?.contentOrNull
    if (reason == "too_many_active") {
        val limit = (details["limit"] as? JsonPrimitive)?.intOrNull ?: 5
        return t(R.string.client_share_tooMany, "limit" to limit)
    }
    return errorText(error)
}

/**
 * The money lines of a promo quote (never shown without one). Unticked, the bonus is not used: the cash equals the
 * price and the discount line is not claimed.
 */
@Composable
internal fun promoRows(priceMinor: Long, quote: ProposalPromoClientDTO, ticked: Boolean, offer: Boolean): List<MoneyRow> {
    val ok = Elchi.colors.tone(Tone.OK).fg
    val first = MoneyRow(t(if (offer) R.string.promo_line_offerPrice else R.string.promo_line_agreedPrice), soum(priceMinor))
    return if (ticked) {
        listOf(
            first,
            MoneyRow(t(R.string.promo_line_bonusDiscount), "−${soum(quote.passengerDiscountMinor)}", color = ok),
            MoneyRow(t(R.string.promo_line_cashToDriver), soum(quote.cashDueMinor), strong = true),
        )
    } else {
        listOf(first, MoneyRow(t(R.string.promo_line_cashToDriver), soum(priceMinor), strong = true))
    }
}

/** "Nega chegirma yo'q?" with the dictionary's sentence for the server's reason; nothing for an unknown reason. */
@Composable
internal fun NoDiscountNote(reason: String?) {
    val key = OrderRules.noDiscountKey(reason) ?: return
    val text = tOrNull(key) ?: return
    Note(text, tone = Tone.GRAY, title = t(R.string.promoScreen_whyNoDiscount))
}

/**
 * `accept-confirm`: accepting makes the booking at once, so it is never a single tap. The strings are resolved
 * by the caller - a dialog window has the phone's language, not the app's.
 */
@Composable
internal fun AcceptDialog(
    title: String,
    text: String,
    rows: List<MoneyRow>,
    confirm: String,
    back: String,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    val c = Elchi.colors
    Dialog(onDismissRequest = onDismiss) {
        Column(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(28.dp)).background(c.card).padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(title, style = Elchi.type.title.copy(fontSize = androidx.compose.ui.unit.TextUnit(19f, androidx.compose.ui.unit.TextUnitType.Sp), lineHeight = androidx.compose.ui.unit.TextUnit(23f, androidx.compose.ui.unit.TextUnitType.Sp)), color = c.text)
                Text(text, style = Elchi.type.secondary, color = c.muted)
            }
            MoneyBlock(rows)
            ElchiButton(confirm, onConfirm, Modifier.fillMaxWidth())
            ElchiButton(back, onDismiss, Modifier.fillMaxWidth().height(46.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM)
        }
    }
}

/** The dialog for [thread]: agreed total (never recomputed, Q90) and, with a ticked bonus, the cash to the driver. */
@Composable
internal fun AcceptDialogFor(thread: ProposalThreadDTO, board: OfferBoard.State, onConfirm: () -> Unit, onDismiss: () -> Unit, requestWindow: Pair<String?, String?>? = null) {
    val version = thread.currentVersion ?: return
    val quote = version.promoQuote as? ProposalPromoClientDTO
    val rows = if (quote != null) promoRows(version.totalMinor, quote, thread.id in board.acceptBonus, offer = false)
    else listOf(MoneyRow(t(R.string.promo_line_agreedPrice), soum(version.totalMinor), strong = true))
    AcceptDialog(
        title = driverNumber(thread)?.let { t(R.string.client_accept_title, "number" to it) } ?: t(R.string.confirmDialog_selectDriver_title),
        // Q153: accepting a time proposal is the consent - the confirm says which time is being agreed to.
        text = listOfNotNull(timeProposalText(version, requestWindow), t(R.string.client_accept_text)).joinToString("\n\n"),
        rows = rows,
        confirm = t(R.string.client_accept_confirm),
        back = t(R.string.confirmDialog_back),
        onConfirm = onConfirm,
        onDismiss = onDismiss,
    )
}
