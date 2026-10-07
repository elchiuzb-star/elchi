package uz.elchi.app.feature.driver

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import uz.elchi.app.R
import uz.elchi.app.api.DriverBookingDTO
import uz.elchi.app.feature.client.BookingNotice
import uz.elchi.app.feature.client.BookingSide
import uz.elchi.app.feature.client.BookingViewModel
import uz.elchi.app.feature.client.CashBlockModel
import uz.elchi.app.feature.client.CashRecordBlock
import uz.elchi.app.feature.client.TaxiRules
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.CheckRow
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import java.time.Instant

/**
 * The passenger part of `driver-order-detail` (design "Bron tafsiloti · yo'lovchi"): "Yo'lovchini chiqardim",
 * "Mijoz kelmadi" (Q7), "Yo'lovchini tushirdim", and the cash record (Q78). "Keldim" sits above it, shared with
 * the parcel.
 */
@Composable
internal fun PassengerActions(vm: BookingViewModel, s: BookingViewModel.State, view: DriverBookingDTO, now: Instant, nav: DriverBookingNav) {
    val status = view.serviceStatus
    if (DriverTaxiRules.showBoard(view.serviceType, status)) BoardBlock(vm, s, view, nav)
    NoShowBlock(vm, s, view, now)
    if (DriverTaxiRules.showDropOff(view.serviceType, status)) {
        s.dropOffError?.let { Note(errorText(it), tone = Tone.ERR) }
        // Design 08 3.4: "Manzilga yetib keldik" (the same `drop_off` command → `arrived`).
        ElchiButton(t(R.string.driver_v3bkg_arrivedAction), vm::dropOff, Modifier.fillMaxWidth(), loading = s.droppingOff)
    }
    if (TaxiRules.showCash(view.serviceType, status)) {
        CashRecordBlock(
            CashBlockModel(
                side = BookingSide.DRIVER.wire,
                dueMinor = DriverBookingRules.cashToCollectMinor(view),
                promo = view.promo != null,
                cashStatus = view.cashStatus,
                receipt = view.cashReceipt,
                amountDigits = s.cashDigits,
                note = s.cashNote,
                contestComment = s.contestComment,
                busy = s.cashBusy,
                error = s.cashError,
                onAmount = vm::setCashDigits,
                onNote = vm::setCashNote,
                onContestComment = vm::setContestComment,
                onReport = vm::reportCash,
                onAcknowledge = vm::acknowledgeCash,
                onContest = vm::contestCash,
            ),
        )
    }
}

/** "Yo'lovchini chiqardim": one tap - the driver boards the passenger (Q163 retired the boarding code). */
@Composable
private fun BoardBlock(vm: BookingViewModel, s: BookingViewModel.State, view: DriverBookingDTO, nav: DriverBookingNav) {
    val error = s.boardError?.let(DriverTaxiRules::boardError)
    when (error) {
        null -> Unit
        BoardError.TripNotStarted -> Note(t(R.string.error_TRIP_NOT_STARTED), tone = Tone.ERR)
        is BoardError.Other -> Note(errorText(error.error), tone = Tone.ERR)
    }
    ElchiButton(t(R.string.driverBooking_action_board), vm::board, Modifier.fillMaxWidth(), loading = s.boarding)
    // TRIP_NOT_STARTED: boarding starts on the trip (its GPS with it) - one tap away.
    val tripId = view.tripId
    if (error == BoardError.TripNotStarted && tripId != null) {
        ElchiButton(commandLabel(TripCommand.START_BOARDING), { nav.onTrip(tripId) }, Modifier.fillMaxWidth(), ButtonVariant.SOFT, icon = ElchiIcon.ROUTE)
    }
}

/**
 * "Mijoz kelmadi" (Q7): off until "Keldim" was sent and the wait passed (the time it unlocks is said); the sheet
 * asks how the driver tried to reach the client. Once reported, the operator decides - the screen says it waits.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun NoShowBlock(vm: BookingViewModel, s: BookingViewModel.State, view: DriverBookingDTO, now: Instant) {
    val state = DriverTaxiRules.noShow(view.serviceType, view.serviceStatus, s.arrivedAt, view.pickup.windowStart, view.pickup.windowEnd, view.noShowReview, now)
    var sheet by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(s.notice) { if (s.notice == BookingNotice.NO_SHOW_SENT) sheet = false }
    when (state) {
        NoShowState.Hidden -> return
        NoShowState.Pending -> {
            // Design 08 5.5: says it was sent and that only the operator may cancel meanwhile (Q7/Q75).
            Note(t(R.string.driver_v3bkg_noShowPendingNote), tone = Tone.WARN)
            return
        }
        else -> Unit
    }
    ElchiButton(
        t(R.string.driver_noShow_button), { vm.clearNoShowError(); sheet = true }, Modifier.fillMaxWidth(),
        if (state == NoShowState.Ready) ButtonVariant.DANGER_SOFT else ButtonVariant.NEUTRAL,
        icon = ElchiIcon.CLOCK, enabled = state == NoShowState.Ready,
    )
    val reason = (state as? NoShowState.Locked)?.let { locked ->
        val time = locked.unlocksAt?.let { DriverTime.clockOrDay(it, now) }
        if (time != null) tOrNull("driver.noShow.reason.${locked.reason}", "time" to time) else tOrNull("driver.noShow.reason.${locked.reason}")
    }
    // Unlocked: what the operator's decision means (design 08 5.3, the server's `no_show` + released hold).
    val hint = if (state == NoShowState.Ready) t(R.string.driver_v3bkg_noShowHintReady) else t(R.string.driver_noShow_hint)
    Text(listOfNotNull(reason, hint).joinToString(" "), style = Elchi.type.caption, color = Elchi.colors.muted)
    if (!sheet) s.noShowError?.let { Note(noShowErrorText(it, state), tone = Tone.ERR) }
    if (sheet) {
        // The sheet is its own window (the phone's language): every label is resolved here first.
        val title = t(R.string.driver_noShow_contactTitle)
        val labels = ContactChannel.entries.associateWith { tOrNull(it.key) ?: it.name }
        val confirm = t(R.string.driver_noShow_confirm)
        val cancel = t(R.string.common_cancel)
        val error = s.noShowError?.let { noShowErrorText(it, state) }
        var channels by remember { mutableStateOf(setOf<ContactChannel>()) }
        ModalBottomSheet(onDismissRequest = { if (!s.noShowSending) sheet = false }, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true), containerColor = Elchi.colors.card) {
            Column(Modifier.padding(horizontal = 16.dp).padding(bottom = 16.dp).navigationBarsPadding(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(title, style = Elchi.type.section, color = Elchi.colors.text)
                ContactChannel.entries.forEach { channel ->
                    CheckRow(labels.getValue(channel), channel in channels, { on -> channels = if (on) channels + channel else channels - channel })
                }
                error?.let { Note(it, tone = Tone.ERR) }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ElchiButton(confirm, { vm.reportNoShow(channels) }, Modifier.weight(1f), ButtonVariant.DANGER, ButtonSize.LARGE, enabled = channels.isNotEmpty(), loading = s.noShowSending, horizontalPadding = 10.dp)
                    ElchiButton(cancel, { sheet = false }, Modifier.weight(1f), ButtonVariant.NEUTRAL, enabled = !s.noShowSending, horizontalPadding = 10.dp)
                }
            }
        }
    }
}

/** The server's reason in the driver's words; the wait's end time when that is the reason. */
@Composable
private fun noShowErrorText(error: Throwable, state: NoShowState): String {
    val key = DriverTaxiRules.noShowRefusalKey(error) ?: return errorText(error)
    val time = (state as? NoShowState.Locked)?.unlocksAt?.let { DriverTime.clockOrDay(it, Instant.now()) }
    return (if (time != null) tOrNull(key, "time" to time) else tOrNull(key))?.takeUnless { "{time}" in it } ?: errorText(error)
}
