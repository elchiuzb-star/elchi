package uz.elchi.app.feature.client

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.activity.compose.LocalActivity
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
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
import uz.elchi.app.api.generated.ContactDetails
import uz.elchi.app.api.generated.ReportReasonCode
import uz.elchi.app.api.generated.ReputationDTO
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.Banner
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.CardHeader
import uz.elchi.app.ui.components.CardRow
import uz.elchi.app.ui.components.Chip
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiField
import uz.elchi.app.ui.components.ItemCard
import uz.elchi.app.ui.components.ItemLine
import uz.elchi.app.ui.components.ListCard
import uz.elchi.app.ui.components.ListRow
import uz.elchi.app.ui.components.MoneyBlock
import uz.elchi.app.ui.components.MoneyRow
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.SectionTitle
import uz.elchi.app.ui.components.SelectField
import uz.elchi.app.ui.components.StarRating
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone
import java.time.Instant
import java.time.format.DateTimeFormatter
import java.util.Locale

// -- client-booking-detail ---------------------------------------------------------------------------------------

/**
 * `client-booking-detail` "Buyurtma tafsilotlari" for a parcel booking: what was agreed, who carries it, the
 * fare (cash to the driver, never through the app), and what the client can do in this status. Read again on every
 * return to the screen and by pulling down.
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
    onRate: () -> Unit,
    onSupport: () -> Unit,
    onSafety: () -> Unit,
) {
    val s by vm.state.collectAsStateWithLifecycle()
    var confirmCancel by rememberSaveable { mutableStateOf(false) }
    LifecycleResumeEffect(vm) {
        vm.refresh()
        onPauseOrDispose { }
    }
    LaunchedEffect(s.notice, s.warnings) {
        if (s.notice != null || s.warnings.isNotEmpty()) {
            delay(NOTICE_SHOWN_MS)
            vm.consumeNotice()
        }
    }
    LaunchedEffect(s.cancelDone) {
        if (s.cancelDone) {
            confirmCancel = false
            vm.consumeCancelDone()
        }
    }
    StepScaffold(
        title = t(R.string.listingDetail_title),
        onBack = onBack,
        right = t(R.string.proposal_refresh),
        onRight = vm::refresh,
        banner = { BookingNotices(s) },
        onRefresh = vm::refresh,
        refreshing = s.refreshing && s.booking is Load.Ready,
    ) {
        when (val load = s.booking) {
            Load.Loading -> LoadingLine(t(R.string.common_loading))
            is Load.Failed -> LoadFailed(t(R.string.listingDetail_title), load.error, vm::refresh)
            is Load.Ready -> BookingBody(vm, s, load.value, ru, languageTag, onChat, onTracking, onAmend, onRate, onSupport, onSafety) {
                vm.openCancel()
                confirmCancel = true
            }
        }
    }
    val booking = s.value
    if (confirmCancel && booking != null) {
        BookingCancelSheet(vm, s, booking, ru, onDismiss = { if (!s.cancelling) confirmCancel = false })
    }
}

@Composable
private fun BookingNotices(s: BookingViewModel.State) {
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
            },
        )
        Banner(text, Tone.OK)
    }
    s.warnings.forEach { Banner(tOrNull("warning.${it.code}") ?: it.message, Tone.WARN) }
}

@Composable
private fun BookingBody(
    vm: BookingViewModel,
    s: BookingViewModel.State,
    booking: BookingClientDTO,
    ru: Boolean,
    languageTag: String,
    onChat: () -> Unit,
    onTracking: () -> Unit,
    onAmend: () -> Unit,
    onRate: () -> Unit,
    onSupport: () -> Unit,
    onSafety: () -> Unit,
    onCancel: () -> Unit,
) {
    val status = booking.serviceStatus
    BookingHeader(booking, ru, languageTag)
    if (BookingRules.reviewPending(booking.noShowReview)) Note(t(R.string.bookingCancel_reviewPending), tone = Tone.WARN)
    booking.driver?.let { DriverCard(booking, s.reputation, languageTag) }
    booking.promo?.let { PromoBlock(it) }
    FareCard(booking, s.receiver, ru)
    if (booking.parcelPhoto != null) ParcelPhotoBlock(s.photo, s.photoFailed)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        ElchiButton(t(R.string.bookingDetail_messages), onChat, Modifier.weight(1f).height(48.dp), ButtonVariant.SOFT, ButtonSize.MEDIUM, icon = ElchiIcon.CHAT, horizontalPadding = 10.dp)
        ElchiButton(t(R.string.bookingDetail_tracking), onTracking, Modifier.weight(1f).height(48.dp), ButtonVariant.SOFT, ButtonSize.MEDIUM, icon = ElchiIcon.PIN, horizontalPadding = 10.dp)
    }
    if (BookingRules.canShareTracking(status)) TrackingShareSection(vm, s)
    if (BookingRules.canAmend(status)) {
        ElchiButton(t(R.string.bookingDetail_changeTerms), onAmend, Modifier.fillMaxWidth(), ButtonVariant.NEUTRAL)
    }
    if (BookingRules.canRate(status)) RatingEntry(s, onRate)
    // Q146: the operator chat is the booking page's main help; the safety report sits apart, folded below.
    ElchiButton(t(R.string.support_complain), onSupport, Modifier.fillMaxWidth(), ButtonVariant.NEUTRAL, icon = ElchiIcon.HEAD)
    if (BookingRules.canCancel(status, booking.noShowReview)) {
        ElchiButton(t(R.string.bookingCancel_button), onCancel, Modifier.fillMaxWidth(), ButtonVariant.DANGER_SOFT)
    }
    ListCard {
        ListRow(t(R.string.safety_menuTitle), icon = ElchiIcon.SHIELD, description = t(R.string.client_bookingDetail_safetyHint), first = true, onClick = onSafety)
    }
}

/** The route, the status in words (with its tone and dot), the agreed window and what the client hands over. */
@Composable
private fun BookingHeader(booking: BookingClientDTO, ru: Boolean, languageTag: String) {
    val status = booking.serviceStatus
    val cancelled = booking.cancelled?.takeIf { status == "cancelled" }?.let { c ->
        val parts = listOfNotNull(
            BookingRules.bySideKey(c.bySide)?.let { tOrNull(it) },
            OrderRules.tashkent(c.at)?.let { ParcelRules.displayShort(it) },
            BookingRules.cancelReasonKey(c.reasonCode)?.let { tOrNull(it) },
        )
        "${t(R.string.bookingCancel_cancelledBy)}: ${parts.joinToString(" · ")}"
    }
    ItemCard(
        title = "${OrderRules.shortEnd(booking.pickup.stop, booking.pickup.point, ru)} → ${OrderRules.shortEnd(booking.dropoff.stop, booking.dropoff.point, ru)}",
        badge = (tOrNull(OrderRules.bookingStatusKey(booking.serviceType, status)) ?: status) to OrderRules.bookingTone(booking.serviceType, status),
        lines = listOfNotNull(cancelled?.let { ItemLine(it, Elchi.colors.tone(Tone.ERR).fg) }),
        meta = windowMeta(booking.pickup.windowStart, booking.pickup.windowEnd, languageTag),
        // Q103: with a discount the client hands over the cash due, not the fare.
        right = soum(booking.promo?.cashDueMinor ?: booking.totalMinor),
    )
}

/** `29 sen, 09:00–18:00` (Tashkent); the full dates when the window spans days. */
private fun windowMeta(start: String?, end: String?, languageTag: String): String? {
    val s = OrderRules.tashkent(start) ?: return null
    val e = OrderRules.tashkent(end)
    val day = OrderRules.dayMonth(start, languageTag) ?: return null
    val hm = DateTimeFormatter.ofPattern("HH:mm")
    return when {
        e == null -> "$day, ${s.format(hm)}"
        e.toLocalDate() == s.toLocalDate() -> "$day, ${s.format(hm)}–${e.format(hm)}"
        else -> OrderRules.windowText(start, end)
    }
}

/**
 * "Haydovchi va avtomobil": first name and reputation, the car, the plate (masked until Q64 opens it) and the
 * phone (only once the trip departed, Q142 - with a call button then; before that the in-app chat).
 */
@Composable
private fun DriverCard(booking: BookingClientDTO, reputation: ReputationDTO?, languageTag: String) {
    val driver = booking.driver ?: return
    val context = LocalContext.current
    val activity = LocalActivity.current
    val phone = BookingRules.phone(driver, booking.contact)
    val plate = BookingRules.plate(driver.vehicle)
    ElchiCard {
        CardHeader(t(R.string.client_bookingDetail_driverCard), badge = if (phone.visible) t(R.string.client_bookingDetail_contactOpen) else null, badgeTone = Tone.OK)
        CardRow(t(R.string.safety_driverTitle), driver.displayName, first = true, detail = reputation?.let { reputationText(it, languageTag) })
        val vehicle = driver.vehicle
        CardRow(
            t(R.string.tripDetail_vehicle),
            listOf(vehicle.makeModel, vehicle.color).filter { it.isNotBlank() }.joinToString(" · "),
            detail = t(R.string.app_rivalBoard_vehicleSeats, "vehicle" to (tOrNull("vehicleClass.${vehicle.vehicleClass}") ?: vehicle.vehicleClass), "seats" to vehicle.seatCapacity),
        )
        CardRow(
            t(R.string.driverProfileForm_plateNumber),
            plate.text,
            // Q75: a cancelled booking never gets the full plate - no promise of it then.
            detail = when {
                plate.full -> t(R.string.client_bookingDetail_plateOpen)
                BookingRules.isTerminal(booking.serviceStatus) -> null
                else -> t(R.string.client_bookingDetail_plateLater)
            },
        )
        val number = phone.number
        if (number != null) {
            CardRow(
                t(R.string.driverBooking_phone),
                displayPhone(number),
                trailing = t(R.string.client_bookingDetail_call),
                onTrailing = {
                    val dial = Intent(Intent.ACTION_DIAL, Uri.parse(BookingRules.dialUri(number)))
                    activity?.startActivity(dial) ?: context.startActivity(dial.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                },
            )
        } else {
            CardRow(t(R.string.driverBooking_phone), t(R.string.client_bookingDetail_phoneLater), detail = t(R.string.client_bookingDetail_phoneChatOnly), muted = true)
        }
    }
}

/** "★ 4,7 · 38 ta baho · 112 ta bajarilgan bron", or "Yangi haydovchi · Hali baholanmagan" - never an invented score. */
@Composable
private fun reputationText(dto: ReputationDTO, languageTag: String): String =
    when (val line = BookingRules.reputation(dto, Locale.forLanguageTag(languageTag))) {
        is ReputationLine.Rated -> t(R.string.client_bookingDetail_reputation, "rating" to line.average, "count" to line.count, "bookings" to line.bookings)
        ReputationLine.Unrated -> "${t(R.string.ratingBucket_new_verified)} · ${t(R.string.listingBids_noRatingsYet)}"
    }

/** Only on a discounted booking (never in the pilot's dev data): the fare, the discount ELCHI covers, the cash. */
@Composable
private fun PromoBlock(promo: BookingPromoClientDTO) {
    val ok = Elchi.colors.tone(Tone.OK).fg
    MoneyBlock(
        listOf(
            MoneyRow(t(R.string.promo_line_agreedPrice), soum(promo.fareMinor)),
            MoneyRow(t(R.string.promo_line_bonusDiscount), "−${soum(promo.passengerDiscountMinor)}", color = ok),
            MoneyRow(t(R.string.promo_line_cashToDriver), soum(promo.cashDueMinor), strong = true),
        ),
    )
    Text(t(R.string.promoScreen_clientCovers), style = Elchi.type.caption, color = Elchi.colors.muted)
}

/** The fare (cash to the driver - the app does not take it), the parcel's size category, the receiver. */
@Composable
private fun FareCard(booking: BookingClientDTO, receiver: ContactDetails?, ru: Boolean) {
    ElchiCard {
        CardRow(
            t(R.string.bookingDetail_fare),
            t(R.string.bookingDetail_fareCash, "amount" to soum(booking.promo?.cashDueMinor ?: booking.totalMinor)),
            first = true,
            detail = t(R.string.bookingDetail_fareNote),
        )
        booking.parcelCategory?.let { CardRow(t(R.string.listingDetail_parcel), "${categoryName(it, ru)} · ${categoryLimits(it)}") }
        receiver?.let { r ->
            CardRow(t(R.string.driverBooking_receiver), listOf(r.name.trim(), displayPhone(r.phone)).filter { it.isNotBlank() }.joinToString(" · "))
        }
    }
}

/**
 * "Yaqinlaringiz bilan kuzatuv": a recipient link (the car's state and last position, no names or phones). The
 * server returns the URL once; it lives only while this screen does.
 */
@Composable
private fun TrackingShareSection(vm: BookingViewModel, s: BookingViewModel.State) {
    val context = LocalContext.current
    SectionTitle(t(R.string.tracking_shareTitle), description = t(R.string.trackingShare_trackingHint))
    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        BookingRules.GRANT_TTL_MINUTES.forEach { minutes ->
            val label = if (minutes < 60) t(R.string.trackingShare_ttlMinutes, "count" to minutes) else t(R.string.trackingShare_ttlHours, "count" to minutes / 60)
            Chip(label, s.grantTtl == minutes, { vm.setGrantTtl(minutes) }, filled = true)
        }
    }
    ElchiButton(t(R.string.trackingShare_create), vm::createGrant, Modifier.fillMaxWidth(), ButtonVariant.SOFT, icon = ElchiIcon.SHARE, loading = s.granting && s.grant == null)
    s.grantError?.let { Note(grantErrorText(it), tone = Tone.ERR) }
    if (s.grantRevoked) Note(t(R.string.trackingShare_revoked), tone = Tone.OK)
    val url = s.grantUrl
    val grant = s.grant
    if (grant != null) {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (url != null) {
                GrantLink(url, context)
            }
            val from = OrderRules.parseInstant(grant.validFrom)
            if (from != null && from.isAfter(Instant.now().plusSeconds(60))) {
                Text(t(R.string.client_trackingShare_validFrom, "time" to shortTime(grant.validFrom)), style = Elchi.type.caption, color = Elchi.colors.muted)
            }
            Text(t(R.string.trackingShare_validUntil, "time" to shortTime(grant.expiresAt)), style = Elchi.type.caption, color = Elchi.colors.muted)
            Text(t(R.string.trackingShare_urlOnce), style = Elchi.type.caption, color = Elchi.colors.muted)
            ElchiButton(t(R.string.client_share_revoke), vm::revokeGrant, Modifier.fillMaxWidth().height(44.dp), ButtonVariant.GHOST, ButtonSize.MEDIUM, enabled = !s.granting)
        }
    }
}

@Composable
private fun GrantLink(url: String, context: Context) {
    val c = Elchi.colors
    val activity = LocalActivity.current
    var copied by remember(url) { mutableStateOf(false) }
    val chooserTitle = t(R.string.client_share_send)
    Text(t(R.string.client_share_link), style = Elchi.type.caption, color = c.muted)
    Text(
        url,
        Modifier.fillMaxWidth().heightIn(min = 44.dp).clip(RoundedCornerShape(14.dp)).background(c.field).padding(horizontal = 14.dp, vertical = 12.dp),
        style = Elchi.type.label.copy(fontFamily = FontFamily.Monospace),
        color = c.text,
    )
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        ElchiButton(
            t(if (copied) R.string.promoScreen_copied else R.string.promoScreen_copy),
            {
                val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                clipboard.setPrimaryClip(ClipData.newPlainText("ELCHI", url))
                copied = true
            },
            Modifier.weight(1f).height(48.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM, icon = ElchiIcon.COPY, horizontalPadding = 10.dp,
        )
        ElchiButton(
            chooserTitle,
            {
                // Nothing is posted for the person: the phone's own share sheet with the bare link.
                val chooser = Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, url), chooserTitle)
                activity?.startActivity(chooser) ?: context.startActivity(chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            },
            Modifier.weight(1f).height(48.dp), ButtonVariant.SOFT, ButtonSize.MEDIUM, icon = ElchiIcon.SHARE, horizontalPadding = 10.dp,
        )
    }
}

/** `29.09, 18:40` in Tashkent, or the raw value when it cannot be read. */
private fun shortTime(value: String?): String = OrderRules.tashkent(value)?.let { ParcelRules.displayShort(it) } ?: value.orEmpty()

/** grant_too_early says from when a link can be made; a finished booking says the window is closed. */
@Composable
private fun grantErrorText(error: Throwable): String {
    val api = error as? ApiException ?: return errorText(error)
    val reason = BookingRules.detailsReason(api.details)
    if (reason == "grant_too_early") {
        val from = BookingRules.detailsString(api.details, "issuable_from")?.takeIf { OrderRules.parseInstant(it) != null }
        return if (from != null) t(R.string.client_trackingShare_tooEarly, "time" to shortTime(from)) else t(R.string.client_trackingShare_tooEarlyNoTime)
    }
    if (api.code == "INVALID_STATE_TRANSITION") return t(R.string.client_trackingShare_finished)
    if (api.code == "FORBIDDEN" && reason == "booking_owner_only") return t(R.string.client_trackingShare_ownerOnly)
    return errorText(error)
}

/** "Haydovchini baholash" until rated; then "Baho berildi" (or the server's reason rating is closed). */
@Composable
private fun RatingEntry(s: BookingViewModel.State, onRate: () -> Unit) {
    val refusal = s.ratingRefusal
    when {
        s.rated -> Note(listOfNotNull(t(R.string.client_bookingDetail_rated), refusal?.let { errorText(it) }).joinToString(" "), tone = Tone.OK)
        refusal != null -> Note(errorText(refusal), tone = Tone.GRAY)
        else -> ElchiButton(t(R.string.rating_rateDriver), onRate, Modifier.fillMaxWidth())
    }
}

// -- booking-cancel ----------------------------------------------------------------------------------------------

/**
 * `booking-cancel`: reason, optional comment, confirm. Never one tap. The sheet is its own window (the phone's
 * language), so every string is resolved here first.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun BookingCancelSheet(vm: BookingViewModel, s: BookingViewModel.State, booking: BookingClientDTO, ru: Boolean, onDismiss: () -> Unit) {
    val c = Elchi.colors
    val title = t(R.string.bookingCancel_title)
    // The server's own policy line is the authority, but it comes in Uzbek only; Russian keeps the dictionary text.
    val body = booking.cancellationPolicySummary?.takeIf { !ru && it.isNotBlank() } ?: t(R.string.bookingCancel_body)
    val reasonLabel = t(R.string.bookingCancel_reasonLabel)
    val reasons = BookingRules.CLIENT_CANCEL_REASONS.map { it to (tOrNull("bookingCancel.reason.$it") ?: it) }
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
            SelectField(reasonLabel, s.cancelReason, reasons, vm::setCancelReason, placeholder = reasonLabel)
            ElchiField(
                s.cancelComment,
                vm::setCancelComment,
                label = commentLabel,
                singleLine = false,
                minHeight = 88.dp,
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
    LaunchedEffect(s.notice, s.warnings) {
        if (s.notice != null || s.warnings.isNotEmpty()) {
            delay(NOTICE_SHOWN_MS)
            vm.consumeNotice()
        }
    }
    val booking = s.value
    StepScaffold(
        title = t(R.string.amendment_title),
        onBack = onBack,
        banner = { BookingNotices(s) },
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
            Note(t(R.string.amendment_parcelQuantityFixed), tone = Tone.GRAY)
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
    val price = vm.amendPrice()
    val typed = ParcelRules.soumToMinor(s.amendDigits)
    ElchiField(
        s.amendDigits,
        vm::setAmendDigits,
        label = t(R.string.amendment_priceLabel),
        placeholder = ParcelRules.groupThousands(ParcelRules.minorToSoum(booking.unitPriceMinor)),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Next),
        visualTransformation = ThousandsTransformation,
        error = if (typed != null && typed == booking.unitPriceMinor && s.amendDigits.isNotEmpty()) t(R.string.client_amendment_noChange) else null,
    )
    ElchiField(
        s.amendReason,
        vm::setAmendReason,
        label = t(R.string.common_reason),
        placeholder = t(R.string.amendment_reasonPlaceholder),
        singleLine = false,
        minHeight = 72.dp,
        keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
        hint = t(R.string.amendment_reasonHint),
    )
    // Never recomputed beyond quantity × price: the server's total comes back with the amendment.
    price?.let { Text(t(R.string.amendment_newTotal, "total" to soum(it * booking.quantity)), style = Elchi.type.secondary.copy(fontWeight = FontWeight.SemiBold), color = Elchi.colors.text) }
    if (s.amendErrorFor == BookingViewModel.NEW_AMENDMENT) s.amendError?.let { Note(amendmentErrorText(it), tone = Tone.ERR) }
    ElchiButton(
        t(R.string.amendment_submit),
        vm::sendAmendment,
        Modifier.fillMaxWidth(),
        enabled = price != null && s.amendReason.isNotBlank() && s.amendBusy == null,
        loading = s.amendBusy == BookingViewModel.NEW_AMENDMENT,
    )
}

/** One amendment of the history: the new terms, whose it is, its status; the answers only while it is live. */
@Composable
private fun AmendmentItem(vm: BookingViewModel, s: BookingViewModel.State, amendment: AmendmentDTO, bookingStatus: String, now: Instant) {
    val actions = BookingRules.amendmentActions(amendment, bookingStatus, now)
    val status = BookingRules.amendmentDisplayStatus(amendment, now)
    val busy = s.amendBusy == amendment.id
    val otherBusy = s.amendBusy != null && !busy
    val promo = amendment.promo as? BookingPromoClientDTO
    ItemCard(
        title = "${amendment.newQuantity} × ${soum(amendment.newUnitPriceMinor)}",
        sub = t(if (amendment.authorSide == "client") R.string.amendment_mine else R.string.amendment_theirs),
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
                ElchiButton(t(R.string.amendment_withdraw), { vm.withdrawAmendment(amendment) }, Modifier.fillMaxWidth().height(46.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM, enabled = !otherBusy, loading = busy)
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

/** `booking-rating` "Haydovchini baholang": 1-5 stars and an optional comment that is checked before it is shown. */
@Composable
fun RatingScreen(vm: BookingViewModel, onBack: () -> Unit, onDone: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    LaunchedEffect(s.rated, s.ratingRefusal) { if (s.rated || s.ratingRefusal != null) onDone() }
    StepScaffold(
        title = t(R.string.rating_titleDriver),
        onBack = onBack,
        footer = {
            s.ratingError?.let { Note(errorText(it), tone = Tone.ERR) }
            ElchiButton(t(R.string.bookingRating_submit), vm::rate, Modifier.fillMaxWidth(), enabled = s.stars in 1..5, loading = s.rating)
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
        ElchiField(
            s.ratingComment,
            vm::setRatingComment,
            label = t(R.string.bookingRating_commentLabel),
            singleLine = false,
            minHeight = 96.dp,
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
        )
        Text(t(R.string.bookingRating_moderationNote), style = Elchi.type.caption, color = Elchi.colors.muted)
    }
}

// -- safety-menu -------------------------------------------------------------------------------------------------

/**
 * `safety-menu` "Xavfsizlik haqida xabar berish": a report about this booking for the operator (it punishes no one
 * by itself), and blocking the driver after a confirmation. Unblocking is not offered here (see the report).
 */
@Composable
fun SafetyScreen(vm: BookingViewModel, onBack: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    var confirmBlock by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(s.blocked) { if (s.blocked) confirmBlock = false }
    StepScaffold(title = t(R.string.safety_menuTitle), onBack = onBack) {
        Note(t(R.string.client_safety_note), tone = Tone.GRAY)
        SectionTitle(t(R.string.safety_reportTitle))
        if (s.reported) {
            Note(t(R.string.blockReport_sentNote), tone = Tone.OK, title = t(R.string.blockReport_sentTitle))
            ElchiButton(t(R.string.blockReport_reportAgain), vm::newReport, Modifier.fillMaxWidth().height(44.dp), ButtonVariant.GHOST, ButtonSize.MEDIUM)
        } else {
            val reasons = ReportReasonCode.entries.filter { it != ReportReasonCode.UNKNOWN }.map { it to (tOrNull("blockReport.reason.${it.value}") ?: it.value) }
            SelectField(t(R.string.common_reason), s.reportReason, reasons, vm::setReportReason, placeholder = t(R.string.blockReport_chooseReason))
            ElchiField(
                s.reportDetails,
                vm::setReportDetails,
                label = t(R.string.blockReport_detailsLabel),
                singleLine = false,
                minHeight = 88.dp,
                keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
                hint = t(R.string.blockReport_detailsHint),
            )
            s.reportError?.let { Note(errorText(it), tone = Tone.ERR) }
            ElchiButton(t(R.string.common_send), vm::report, Modifier.fillMaxWidth(), enabled = s.reportReason != null, loading = s.reporting)
        }
        SectionTitle(t(R.string.blockReport_blockTitle), description = t(R.string.blockReport_blockNote))
        when {
            s.blocked -> Note(t(R.string.client_safety_blocked), tone = Tone.OK)
            s.value?.driver == null -> Note(t(R.string.safety_counterpartyMissing), tone = Tone.GRAY)
            confirmBlock -> ElchiCard(bordered = true, padding = androidx.compose.foundation.layout.PaddingValues(16.dp)) {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(t(R.string.client_safety_blockConfirmTitle), style = Elchi.type.bodyStrong, color = Elchi.colors.text)
                    s.blockError?.let { Note(errorText(it), tone = Tone.ERR) }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        ElchiButton(t(R.string.client_safety_blockConfirm), vm::block, Modifier.weight(1f).height(48.dp), ButtonVariant.DANGER, ButtonSize.MEDIUM, loading = s.blocking, horizontalPadding = 10.dp)
                        ElchiButton(t(R.string.confirmDialog_back), { confirmBlock = false }, Modifier.weight(1f).height(48.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM, enabled = !s.blocking, horizontalPadding = 10.dp)
                    }
                }
            }
            else -> ElchiButton(t(R.string.blockReport_block), { confirmBlock = true }, Modifier.fillMaxWidth(), ButtonVariant.DANGER_SOFT, icon = ElchiIcon.BLOCK)
        }
    }
}
