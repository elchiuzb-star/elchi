package uz.elchi.app.feature.client

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import uz.elchi.app.ui.components.RoundIconButton
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.TextUnitType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.delay
import uz.elchi.app.R
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.BookingClientDTO
import uz.elchi.app.api.generated.AmendmentDTO
import uz.elchi.app.api.generated.BookingPromoClientDTO
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.Banner
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.CardRow
import uz.elchi.app.ui.components.ElchiDialog
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiField
import uz.elchi.app.ui.components.ItemCard
import uz.elchi.app.ui.components.ItemLine
import uz.elchi.app.ui.components.MoneyBlock
import uz.elchi.app.ui.components.MoneyRow
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.SectionTitle
import uz.elchi.app.ui.components.StarRating
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone
import java.time.Instant

// -- client-booking-detail ---------------------------------------------------------------------------------------

/**
 * `client-booking-detail` "Buyurtma tafsilotlari" (design 04 "Elchi Bron"): the map hero that opens the tracking, the
 * sheet card with the badge, tracker and facts, the status notices, then what the client can do in this status, and
 * the fixed driver bar (call + chat). Read again on every return to the screen and by pulling down.
 */
@Composable
fun BookingDetailScreen(
    vm: BookingViewModel,
    ru: Boolean,
    languageTag: String,
    onBack: () -> Unit,
    onChat: () -> Unit,
    onTracking: () -> Unit,
    onAmend: () -> Unit,
    onRate: (Int) -> Unit,
    onSupport: () -> Unit,
    onSafety: () -> Unit,
) {
    val s by vm.state.collectAsStateWithLifecycle()
    var confirmCancel by rememberSaveable { mutableStateOf(false) }
    val toast = LocalFlowToast.current
    LifecycleResumeEffect(vm) {
        vm.refresh()
        onPauseOrDispose { }
    }
    BookingNoticeToast(vm, s)
    ShareTrackingEffects(vm, s)
    LaunchedEffect(s.cancelDone) {
        if (s.cancelDone) {
            confirmCancel = false
            vm.consumeCancelDone()
        }
    }
    val booking = s.value
    val unread = booking?.let { BookingRules.unreadCount(s.chatCount, ChatSeenCounts.seen(it.id)) } ?: 0
    StepScaffold(
        title = t(R.string.listingDetail_title),
        onBack = onBack,
        banner = { BookingWarnings(s) },
        onRefresh = vm::refresh,
        refreshing = s.refreshing && s.booking is Load.Ready,
        actions = {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                // Design: share while not cancelled and before delivery/arrival; the support shortcut always.
                if (booking != null && BookingRules.canShareTracking(booking.serviceStatus)) {
                    RoundIconButton(ElchiIcon.SHARE, t(R.string.client_booking_shareTracking), vm::shareTracking, loading = s.granting)
                }
                RoundIconButton(ElchiIcon.HEAD, t(R.string.support_complain), onSupport)
            }
        },
        footerOnPage = true,
        footer = booking?.driver?.let {
            { DriverBar(booking, s.reputation, unread, languageTag, onChat = onChat, onLockedCall = toast::show) }
        },
    ) {
        when (val load = s.booking) {
            Load.Loading -> LoadingLine(t(R.string.common_loading))
            is Load.Failed -> LoadFailed(t(R.string.listingDetail_title), load.error, vm::refresh)
            is Load.Ready -> BookingBody(vm, s, load.value, ru, languageTag, onTracking, onAmend, onRate, onSupport, onSafety) {
                vm.openCancel()
                confirmCancel = true
            }
        }
    }
    if (confirmCancel && booking != null) {
        BookingCancelSheet(vm, s, booking, ru, onDismiss = { if (!s.cancelling) confirmCancel = false })
    }
}

/** The driver's screens: the outcome of a command as a banner (their flow has no toast host). */
@Composable
internal fun BookingNotices(s: BookingViewModel.State) {
    s.notice?.let {
        val text = t(
            when (it) {
                BookingNotice.DRIVER_CHOSEN -> R.string.listingBids_driverChosen
                BookingNotice.CANCELLED -> R.string.bookingCancel_done
                BookingNotice.AMENDMENT_SENT -> R.string.amendment_sent
                BookingNotice.AMENDMENT_ACCEPTED -> R.string.amendment_accepted
                BookingNotice.AMENDMENT_REJECTED -> R.string.amendment_rejected
                BookingNotice.AMENDMENT_WITHDRAWN -> R.string.amendment_withdrawn
                BookingNotice.RATED -> R.string.client_bookingDetail_rated
                BookingNotice.ARRIVED -> R.string.driver_booking_arrived
                BookingNotice.COMPLETED -> R.string.client_taxi_completed
                BookingNotice.STATUS_UPDATED -> R.string.driverBooking_statusUpdated
                BookingNotice.NO_SHOW_SENT -> R.string.driver_noShow_sent
                BookingNotice.CASH_RECORDED -> R.string.driverBooking_cashRecorded
                BookingNotice.CASH_ACKNOWLEDGED, BookingNotice.CASH_CONTESTED -> R.string.driverBooking_cashAnswered
            },
        )
        Banner(text, Tone.OK)
    }
    BookingWarnings(s)
}

/** The server's warnings of a command (a masked comment ...): a banner on both sides. */
@Composable
internal fun BookingWarnings(s: BookingViewModel.State) {
    s.warnings.forEach { Banner(tOrNull("warning.${it.code}") ?: it.message, Tone.WARN) }
}

/** The banner strip of a screen shared with the driver: the client says outcomes as toasts, the driver as banners. */
@Composable
internal fun SharedBookingBanner(vm: BookingViewModel, s: BookingViewModel.State) {
    if (vm.side == BookingSide.DRIVER) BookingNotices(s) else BookingWarnings(s)
}

@Composable
private fun BookingBody(
    vm: BookingViewModel,
    s: BookingViewModel.State,
    booking: BookingClientDTO,
    ru: Boolean,
    languageTag: String,
    onTracking: () -> Unit,
    onAmend: () -> Unit,
    onRate: (Int) -> Unit,
    onSupport: () -> Unit,
    onSafety: () -> Unit,
    onCancel: () -> Unit,
) {
    val status = booking.serviceStatus
    var confirmComplete by rememberSaveable { mutableStateOf(false) }
    BookingHero(booking, onTracking)
    BookingSheet(booking, s, ru, languageTag)
    BookingStatusNotices(booking, s)
    // Taksi: the code the passenger says at the car, until it boards (Q44).
    if (TaxiRules.showBoardingCode(booking.serviceType, status)) BoardingCodeBlock(s, vm::reissueCode)
    booking.promo?.let { BookingPromoBlock(it) }
    DriverInfoCard(booking)
    ActiveShareCard(vm, s)
    if (TaxiRules.showCash(booking.serviceType, status)) CashRecordBlock(clientCashModel(vm, s, booking))
    if (TaxiRules.canComplete(booking.serviceType, status)) {
        // The design omits it; without it the trip waits for an operator to close it (TAXI-SPEC).
        s.completeError?.let { Note(errorText(it), tone = Tone.ERR) }
        ElchiButton(t(R.string.client_taxi_complete), { confirmComplete = true }, Modifier.fillMaxWidth(), icon = ElchiIcon.CHECK_C, loading = s.completing)
        Text(t(R.string.client_taxi_completeHint), style = Elchi.type.caption, color = Elchi.colors.muted)
    }
    if (confirmComplete) {
        ElchiDialog(
            title = t(R.string.client_taxi_completeConfirmTitle),
            text = t(R.string.client_taxi_completeHint),
            confirm = t(R.string.common_confirm),
            onConfirm = {
                confirmComplete = false
                vm.complete()
            },
            onDismiss = { confirmComplete = false },
            dismiss = t(R.string.common_cancel),
        )
    }
    // S1: rating opens only at `completed` (never with the cash block before it).
    if (BookingRules.canRate(status)) RatingEntry(s, onRate)
    if (BookingRules.canAmend(status)) {
        ElchiButton(t(R.string.bookingDetail_changeTerms), onAmend, Modifier.fillMaxWidth().height(48.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM)
    }
    // Q146: the operator chat is the booking page's main help (the bar's head icon is only a shortcut).
    ElchiButton(t(R.string.support_complain), onSupport, Modifier.fillMaxWidth().height(48.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM, icon = ElchiIcon.HEAD)
    SafetyRowCard(onSafety)
    if (BookingRules.canCancel(status, booking.noShowReview)) {
        Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
            Text(
                t(R.string.bookingCancel_button),
                Modifier.clip(CircleShape).clickable(role = Role.Button, onClick = onCancel).heightIn(min = 44.dp).padding(horizontal = 16.dp, vertical = 11.dp),
                style = Elchi.type.secondary.copy(fontWeight = FontWeight.Medium),
                color = Elchi.colors.tone(Tone.ERR).fg,
            )
        }
    }
}

/** The cash block's inputs on the client's side ("Naqd berildi deb qayd qilish"). */
@Composable
private fun clientCashModel(vm: BookingViewModel, s: BookingViewModel.State, booking: BookingClientDTO) = CashBlockModel(
    side = BookingSide.CLIENT.wire,
    dueMinor = booking.promo?.cashDueMinor ?: booking.totalMinor,
    promo = booking.promo != null,
    cashStatus = booking.cashStatus,
    receipt = booking.cashReceipt,
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
)

/**
 * The star card until rated; then "Baho berildi: ★★★★ (4 / 5). Izoh ..." when the stars were sent from here, else
 * "Baho berildi" (the booking DTO carries no rating, 1.14) - or the server's reason rating is closed.
 */
@Composable
private fun RatingEntry(s: BookingViewModel.State, onRate: (Int) -> Unit) {
    val refusal = s.ratingRefusal
    when {
        s.rated && s.ratedStars in 1..5 && refusal == null -> Note(t(R.string.client_booking_ratedStars, "stars" to BookingRules.starsText(s.ratedStars)), tone = Tone.OK)
        s.rated -> Note(listOfNotNull(t(R.string.client_bookingDetail_rated), refusal?.let { errorText(it) }).joinToString(" "), tone = Tone.OK)
        refusal != null -> Note(errorText(refusal), tone = Tone.GRAY)
        else -> RatingStarCard(onRate)
    }
}

// -- booking-cancel ----------------------------------------------------------------------------------------------

/**
 * `booking-cancel`: reason, optional comment, confirm. Never one tap. The sheet is its own window (the phone's
 * language), so every string is resolved here first.
 */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
internal fun BookingCancelSheet(vm: BookingViewModel, s: BookingViewModel.State, booking: BookingClientDTO, ru: Boolean, onDismiss: () -> Unit) {
    val c = Elchi.colors
    val title = t(R.string.bookingCancel_title)
    // The server's own policy line is the authority, but it comes in Uzbek only; Russian keeps the dictionary text.
    val body = booking.cancellationPolicySummary?.takeIf { !ru && it.isNotBlank() } ?: t(R.string.bookingCancel_body)
    val reasonLabel = t(R.string.bookingCancel_reasonLabel)
    val reasons = vm.cancelReasons.map { it to (tOrNull("bookingCancel.reason.$it") ?: it) }
    val commentLabel = t(R.string.bookingCancel_commentLabel)
    val commentHint = t(R.string.app_bookingCancel_commentHint)
    val confirm = t(R.string.bookingCancel_confirm)
    val keep = t(R.string.bookingCancel_keep)
    val error = s.cancelError?.let { e -> BookingRules.cancelRefusalKey((e as? ApiException)?.code)?.let { tOrNull(it) } ?: errorText(e) }
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true), containerColor = c.card) {
        Column(
            Modifier.padding(horizontal = 16.dp).padding(bottom = 16.dp).navigationBarsPadding().verticalScrollIfNeeded(),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(title, style = Elchi.type.title.copy(fontSize = TextUnit(20f, TextUnitType.Sp), lineHeight = TextUnit(24f, TextUnitType.Sp)), color = c.text)
                Text(body, style = Elchi.type.secondary, color = c.muted)
            }
            // Design 04: "Sabab" + wrap chips, one chosen (the first from the start), the chosen one dark.
            Text(reasonLabel, style = Elchi.type.label, color = c.text)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                reasons.forEach { (code, label) -> ReasonChip(label, s.cancelReason == code) { vm.setCancelReason(code) } }
            }
            ElchiField(
                s.cancelComment,
                vm::setCancelComment,
                placeholder = commentLabel,
                singleLine = false,
                minHeight = 72.dp,
                keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
                hint = commentHint,
            )
            error?.let { Note(it, tone = Tone.ERR) }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ElchiButton(confirm, vm::cancel, Modifier.weight(1f), ButtonVariant.DANGER, loading = s.cancelling, horizontalPadding = 10.dp)
                ElchiButton(keep, onDismiss, Modifier.weight(1f), ButtonVariant.NEUTRAL, enabled = !s.cancelling, horizontalPadding = 10.dp)
            }
        }
    }
}

/** One cancel reason (design `cancelItems`): navy when chosen, a white outlined pill otherwise. */
@Composable
private fun ReasonChip(text: String, selected: Boolean, onClick: () -> Unit) {
    val c = Elchi.colors
    val selectedBg = if (c.isDark) Color(0xFF1B3563) else c.navy
    Text(
        text,
        Modifier
            .clip(CircleShape)
            .background(if (selected) selectedBg else c.card)
            .then(if (selected) Modifier else Modifier.border(1.dp, c.line, CircleShape))
            .selectable(selected, role = Role.RadioButton, onClick = onClick)
            .heightIn(min = 40.dp)
            .padding(horizontal = 14.dp, vertical = 10.dp),
        style = Elchi.type.label.copy(fontSize = TextUnit(13f, TextUnitType.Sp)),
        color = if (selected) Color.White else c.text,
    )
}

/** The sheet grows with the reason list and the keyboard; it scrolls rather than clipping its buttons. */
@Composable
private fun Modifier.verticalScrollIfNeeded(): Modifier = this.then(Modifier.verticalScroll(rememberScrollState()))

// -- booking-amendment -------------------------------------------------------------------------------------------

/**
 * `booking-amendment` "Shartlarni o'zgartirish": the agreement as it stands, a new price with the reason the
 * driver will read (a parcel is one consignment: only the price moves), and the history with the answers the
 * client may give. It takes effect only when the other side accepts.
 */
@Composable
fun AmendmentScreen(vm: BookingViewModel, onBack: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val now by rememberNow()
    LaunchedEffect(Unit) { vm.startAmendment() }
    BookingNoticeToast(vm, s)
    if (vm.side == BookingSide.DRIVER) {
        LaunchedEffect(s.notice, s.warnings) {
            if (s.notice != null || s.warnings.isNotEmpty()) {
                delay(NOTICE_SHOWN_MS)
                vm.consumeNotice()
            }
        }
    }
    val booking = s.value
    StepScaffold(
        title = t(R.string.amendment_title),
        onBack = onBack,
        banner = { SharedBookingBanner(vm, s) },
        onRefresh = { vm.refresh(); vm.loadAmendments() },
        refreshing = s.refreshing,
    ) {
        if (booking == null) {
            LoadingLine(t(R.string.common_loading))
            return@StepScaffold
        }
        ElchiCard {
            CardRow(
                t(R.string.amendment_currentTerms),
                "${booking.quantity} × ${soum(booking.unitPriceMinor)} = ${soum(booking.totalMinor)}",
                first = true,
                detail = t(R.string.amendment_takesEffectNote),
                strong = true,
            )
        }
        val open = BookingRules.hasOpenAmendment(s.amendmentList, booking.serviceStatus, now)
        if (BookingRules.canAmend(booking.serviceStatus)) {
            SectionTitle(t(R.string.amendment_proposeTitle))
            // Q145: after the booking the count stays as agreed (D9) - only the price can move.
            Note(
                if (TaxiRules.isPassenger(booking.serviceType)) t(R.string.amendment_seatsFixed, "count" to booking.quantity) else t(R.string.amendment_parcelQuantityFixed),
                tone = Tone.GRAY,
            )
            if (open) {
                Note(t(R.string.client_amendment_openExists), tone = Tone.WARN)
            } else {
                AmendmentForm(vm, s, booking)
            }
        } else {
            Note(t(R.string.client_amendment_onlyConfirmed), tone = Tone.GRAY)
        }
        SectionTitle(t(R.string.client_amendment_history))
        when (val load = s.amendments) {
            Load.Loading -> LoadingLine(t(R.string.common_loading))
            is Load.Failed -> LoadFailed(t(R.string.amendment_title), load.error, vm::loadAmendments)
            is Load.Ready -> if (load.value.isEmpty()) {
                Text(t(R.string.amendment_empty), style = Elchi.type.label.copy(fontWeight = FontWeight.Normal), color = Elchi.colors.muted)
            } else {
                load.value.forEach { AmendmentItem(vm, s, it, booking.serviceStatus, now) }
            }
        }
    }
}

@Composable
private fun AmendmentForm(vm: BookingViewModel, s: BookingViewModel.State, booking: BookingClientDTO) {
    val taxi = TaxiRules.isPassenger(booking.serviceType)
    val toast = LocalFlowToast.current
    val price = vm.amendPrice()
    val typed = ParcelRules.soumToMinor(s.amendDigits)
    val problem = s.amendFormError
    val priceError = when {
        problem == AmendFormError.PRICE_MISSING -> t(R.string.listingOwner_invalid_price)
        problem == AmendFormError.PRICE_SAME || (typed != null && typed == booking.unitPriceMinor) -> t(R.string.client_amendment_noChange)
        else -> null
    }
    val reasonError = if (problem == AmendFormError.REASON) t(R.string.client_booking_amendReasonRequired) else null
    // Design `sendAmend`: the button stays tappable; a tap with a problem says it (toast) and marks the field.
    val problemText = when (problem) {
        AmendFormError.PRICE_MISSING -> t(R.string.listingOwner_invalid_price)
        AmendFormError.PRICE_SAME -> t(R.string.client_amendment_noChange)
        AmendFormError.REASON -> t(R.string.client_booking_amendReasonRequired)
        null -> null
    }
    LaunchedEffect(s.amendFormNonce) { if (s.amendFormNonce > 0 && problemText != null) toast.show(problemText) }
    ElchiField(
        s.amendDigits,
        vm::setAmendDigits,
        // Taksi: the price is per person (the count is fixed, Q145).
        label = t(if (taxi) R.string.routeSummary_pricePerPerson else R.string.amendment_priceLabel),
        placeholder = ParcelRules.groupThousands(ParcelRules.minorToSoum(booking.unitPriceMinor)),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Next),
        visualTransformation = ThousandsTransformation,
        suffix = t(R.string.common_soum),
        error = priceError,
    )
    ElchiField(
        s.amendReason,
        vm::setAmendReason,
        label = t(R.string.common_reason),
        placeholder = t(if (taxi) R.string.amendment_reasonPlaceholder else R.string.client_booking_amendReasonPlaceholder),
        keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
        hint = t(R.string.amendment_reasonHint),
        error = reasonError,
    )
    // Never recomputed beyond quantity × price: the server's total comes back with the amendment.
    Text(
        t(R.string.amendment_newTotal, "total" to (price?.let { soum(it * booking.quantity) } ?: "—")),
        style = Elchi.type.secondary.copy(fontWeight = FontWeight.SemiBold),
        color = Elchi.colors.text,
    )
    if (s.amendErrorFor == BookingViewModel.NEW_AMENDMENT) s.amendError?.let { Note(amendmentErrorText(it), tone = Tone.ERR) }
    ElchiButton(
        t(R.string.amendment_submit),
        vm::sendAmendment,
        Modifier.fillMaxWidth(),
        enabled = s.amendBusy == null,
        dimmed = BookingRules.amendmentFormError(s.amendDigits, s.amendReason, booking.unitPriceMinor) != null,
        loading = s.amendBusy == BookingViewModel.NEW_AMENDMENT,
    )
}

/** One amendment of the history: the new terms, whose it is, its status; the answers only while it is live. */
@Composable
private fun AmendmentItem(vm: BookingViewModel, s: BookingViewModel.State, amendment: AmendmentDTO, bookingStatus: String, now: Instant) {
    val actions = BookingRules.amendmentActions(amendment, bookingStatus, now, vm.side.wire)
    val status = BookingRules.amendmentDisplayStatus(amendment, now)
    val busy = s.amendBusy == amendment.id
    val otherBusy = s.amendBusy != null && !busy
    val promo = amendment.promo as? BookingPromoClientDTO
    ItemCard(
        title = "${amendment.newQuantity} × ${soum(amendment.newUnitPriceMinor)}",
        sub = t(if (amendment.authorSide == vm.side.wire) R.string.amendment_mine else R.string.amendment_theirs),
        badge = (tOrNull(BookingRules.amendmentStatusKey(status)) ?: status) to BookingRules.amendmentTone(status),
        lines = listOfNotNull(
            // A driver's proposal left from before boarding: still "proposed" on the server, but it can no longer apply.
            if (status == "proposed" && !actions.open) ItemLine(t(R.string.client_amendment_onlyConfirmed)) else null,
            if (actions.open) OrderRules.parseInstant(amendment.expiresAt)?.let { ItemLine(t(R.string.client_amendment_expiresIn, "time" to countdownDuration(java.time.Duration.between(now, it).seconds.coerceAtLeast(0))), Elchi.colors.tone(Tone.WARN).fg) } else null,
        ),
        right = soum(amendment.newTotalMinor),
        footer = if (!actions.open) null else ({
            if (promo != null && actions.canAccept) {
                MoneyBlock(
                    listOf(
                        MoneyRow(t(R.string.promo_line_agreedPrice), soum(promo.fareMinor)),
                        MoneyRow(t(R.string.promo_line_bonusDiscount), "−${soum(promo.passengerDiscountMinor)}", color = Elchi.colors.tone(Tone.OK).fg),
                        MoneyRow(t(R.string.promo_line_cashToDriver), soum(promo.cashDueMinor), strong = true),
                    ),
                )
            }
            if (actions.canAccept) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ElchiButton(t(R.string.amendment_accept), { vm.acceptAmendment(amendment) }, Modifier.weight(1f).height(48.dp), size = ButtonSize.MEDIUM, enabled = !otherBusy, loading = busy, horizontalPadding = 10.dp)
                    ElchiButton(t(R.string.proposal_reject), { vm.rejectAmendment(amendment) }, Modifier.weight(1f).height(48.dp), ButtonVariant.DANGER_SOFT, ButtonSize.MEDIUM, enabled = !busy && !otherBusy, horizontalPadding = 10.dp)
                }
            }
            if (actions.canWithdraw) {
                ElchiButton(t(R.string.client_booking_amendWithdraw), { vm.withdrawAmendment(amendment) }, Modifier.fillMaxWidth().height(46.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM, enabled = !otherBusy, loading = busy)
            }
            if (s.amendErrorFor == amendment.id) s.amendError?.let { Note(amendmentErrorText(it), tone = Tone.ERR) }
        }),
    )
}

/** "1 soat 40 daqiqa", rounded up to whole minutes. */
@Composable
private fun countdownDuration(seconds: Long): String {
    val (hours, minutes) = OrderRules.countdownParts(seconds)
    return when {
        hours > 0 && minutes > 0 -> t(R.string.app_duration_hoursMinutes, "hours" to hours, "minutes" to minutes)
        hours > 0 -> t(R.string.app_duration_hours, "hours" to hours)
        else -> t(R.string.app_duration_minutes, "minutes" to minutes)
    }
}

/** AMENDMENT_CONFLICT and `no_change` in words; everything else the dictionary's error sentence. */
@Composable
private fun amendmentErrorText(error: Throwable): String {
    val api = error as? ApiException ?: return errorText(error)
    val reason = BookingRules.detailsReason(api.details)
    if (api.code == "AMENDMENT_CONFLICT") BookingRules.amendmentConflictKey(reason)?.let { key -> tOrNull(key)?.let { return it } }
    if (api.code == "VALIDATION_ERROR" && reason == "no_change") return t(R.string.client_amendment_noChange)
    return errorText(error)
}

// -- booking-rating ----------------------------------------------------------------------------------------------

/**
 * `booking-rating` "Haydovchini baholang": 1-5 stars with their word (Yomon .. A'lo), an optional comment checked before
 * it is shown. "Bahoni yuborish" stays tappable: without a star its tap says so (design `foot.go`). The design's tag
 * chips have no API field (10.3 BLOCKED).
 */
@Composable
fun RatingScreen(vm: BookingViewModel, onBack: () -> Unit, onDone: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val toast = LocalFlowToast.current
    val pick = t(R.string.client_booking_ratePickStars)
    LaunchedEffect(s.rated, s.ratingRefusal) { if (s.rated || s.ratingRefusal != null) onDone() }
    StepScaffold(
        title = t(if (vm.side == BookingSide.DRIVER) R.string.rating_titleClient else R.string.rating_titleDriver),
        onBack = onBack,
        footer = {
            s.ratingError?.let { Note(errorText(it), tone = Tone.ERR) }
            ElchiButton(
                t(R.string.bookingRating_submit),
                { if (s.stars in 1..5) vm.rate() else toast.show(pick) },
                Modifier.fillMaxWidth(),
                dimmed = s.stars !in 1..5,
                loading = s.rating,
            )
            ElchiButton(t(R.string.bookingRating_later), onBack, Modifier.fillMaxWidth().height(44.dp), ButtonVariant.GHOST, ButtonSize.MEDIUM, enabled = !s.rating)
        },
    ) {
        Text(
            t(R.string.bookingRating_prompt),
            Modifier.fillMaxWidth().padding(top = 8.dp),
            style = Elchi.type.title.copy(fontSize = TextUnit(18f, TextUnitType.Sp), lineHeight = TextUnit(24f, TextUnitType.Sp)),
            color = Elchi.colors.text,
            textAlign = androidx.compose.ui.text.style.TextAlign.Center,
        )
        val starLabels = (1..5).associateWith { t(R.string.bookingRating_starsAria, "value" to it) }
        StarRating(s.stars, vm::setStars, label = { starLabels.getValue(it) })
        Text(
            tOrNull(BookingRules.starLabelKey(s.stars)).orEmpty(),
            Modifier.fillMaxWidth(),
            style = Elchi.type.secondary.copy(fontWeight = FontWeight.SemiBold),
            color = if (s.stars in 1..5) Elchi.colors.accentText else Elchi.colors.placeholder,
            textAlign = androidx.compose.ui.text.style.TextAlign.Center,
        )
        ElchiField(
            s.ratingComment,
            vm::setRatingComment,
            label = t(R.string.client_booking_rateCommentOptional),
            placeholder = t(R.string.client_booking_rateCommentPlaceholder),
            singleLine = false,
            minHeight = 112.dp,
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
        )
        Text(t(R.string.bookingRating_moderationNote), style = Elchi.type.caption, color = Elchi.colors.muted)
    }
}

// -- safety-menu -------------------------------------------------------------------------------------------------

/**
 * `safety-menu` "Xavfsizlik": a report about this booking for the operator (it punishes no one by itself) - the 8
 * server reasons as the design's radio list, the first chosen - and blocking the other party after a confirmation
 * dialog ("Bu bron davom etadi"). Unblocking is not offered (11.6 BLOCKED: the server's DELETE is not usable).
 */
@Composable
fun SafetyScreen(vm: BookingViewModel, onBack: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    var confirmBlock by rememberSaveable { mutableStateOf(false) }
    val driverSide = vm.side == BookingSide.DRIVER
    val toast = LocalFlowToast.current
    val name = if (driverSide) s.driverView?.client?.displayName else s.value?.driver?.displayName
    val blockedText = name?.takeIf { it.isNotBlank() && !driverSide }?.let { t(R.string.client_booking_blockedName, "name" to it) }
    var wasBlocked by remember { mutableStateOf(s.blocked) }
    LaunchedEffect(s.blocked) {
        if (s.blocked) {
            confirmBlock = false
            if (!wasBlocked && blockedText != null) toast.show(blockedText)
            wasBlocked = true
        }
    }
    StepScaffold(title = t(if (driverSide) R.string.safety_menuTitle else R.string.safety_section), onBack = onBack) {
        Note(t(R.string.client_safety_note), tone = Tone.GRAY)
        SectionTitle(t(R.string.safety_reportTitle))
        if (s.reported) {
            Note(t(R.string.client_booking_reportSentShort), tone = Tone.OK, title = t(R.string.blockReport_sentTitle))
            ElchiButton(t(R.string.blockReport_reportAgain), vm::newReport, Modifier.fillMaxWidth().height(44.dp), ButtonVariant.GHOST, ButtonSize.MEDIUM)
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                BookingViewModel.REPORT_REASONS.forEach { reason ->
                    ReasonRadio(tOrNull("blockReport.reason.${reason.value}") ?: reason.value, s.reportReason == reason) { vm.setReportReason(reason) }
                }
            }
            ElchiField(
                s.reportDetails,
                vm::setReportDetails,
                label = t(R.string.blockReport_detailsLabel),
                singleLine = false,
                minHeight = 96.dp,
                keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
                hint = t(R.string.blockReport_detailsHint),
            )
            s.reportError?.let { Note(errorText(it), tone = Tone.ERR) }
            ElchiButton(t(R.string.common_send), vm::report, Modifier.fillMaxWidth(), enabled = s.reportReason != null, loading = s.reporting)
        }
        SectionTitle(t(R.string.blockReport_blockTitle), description = t(R.string.blockReport_blockNote))
        when {
            s.blocked -> Note(t(if (driverSide) R.string.driver_safety_blocked else R.string.client_safety_blocked), tone = Tone.OK)
            vm.counterpartId(s) == null -> Note(t(R.string.safety_counterpartyMissing), tone = Tone.GRAY)
            else -> {
                s.blockError?.let { Note(errorText(it), tone = Tone.ERR) }
                ElchiButton(t(R.string.blockReport_block), { confirmBlock = true }, Modifier.fillMaxWidth(), ButtonVariant.DANGER_SOFT, icon = ElchiIcon.BLOCK, loading = s.blocking)
            }
        }
    }
    if (confirmBlock && !s.blocked) {
        ElchiDialog(
            title = when {
                driverSide -> t(R.string.driver_safety_blockConfirmTitle)
                !name.isNullOrBlank() -> t(R.string.client_booking_blockConfirmName, "name" to name)
                else -> t(R.string.client_safety_blockConfirmTitle)
            },
            text = t(R.string.client_booking_blockKeepsBooking),
            confirm = t(R.string.client_safety_blockConfirm),
            confirmVariant = ButtonVariant.DANGER,
            onConfirm = {
                confirmBlock = false
                vm.block()
            },
            onDismiss = { confirmBlock = false },
            dismiss = t(R.string.confirmDialog_back),
            stacked = true,
        )
    }
}

/** One report reason as the design's radio card: brand border and filled ring when chosen. */
@Composable
private fun ReasonRadio(text: String, selected: Boolean, onClick: () -> Unit) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(16.dp)
    Row(
        Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(if (selected) c.highlight else c.card)
            .border(if (selected) 2.dp else 1.dp, if (selected) c.brand else c.line, shape)
            .selectable(selected, role = Role.RadioButton, onClick = onClick)
            .heightIn(min = 48.dp)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Box(Modifier.size(20.dp).clip(CircleShape).border(if (selected) 6.dp else 2.dp, if (selected) c.brand else c.outline, CircleShape))
        Text(text, Modifier.weight(1f), style = Elchi.type.secondary.copy(fontWeight = FontWeight.Medium), color = c.text)
    }
}
