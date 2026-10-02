package uz.elchi.app.feature.client

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import androidx.activity.compose.LocalActivity
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.delay
import uz.elchi.app.R
import uz.elchi.app.api.generated.ListingDTO
import uz.elchi.app.api.generated.ListingStatus
import uz.elchi.app.api.generated.ParcelType
import uz.elchi.app.api.generated.PriceBasis
import uz.elchi.app.api.generated.ProposalThreadDTO
import uz.elchi.app.api.generated.ShareLinkChannel
import uz.elchi.app.api.generated.ShareLinkDTO
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.Banner
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.CardRow
import uz.elchi.app.ui.components.Chip
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiField
import uz.elchi.app.ui.components.EmptyState
import uz.elchi.app.ui.components.ItemCard
import uz.elchi.app.ui.components.ItemLine
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.PickerField
import uz.elchi.app.ui.components.SectionTitle
import uz.elchi.app.ui.components.Segmented
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone
import java.time.Instant

/** How long a one-time outcome ("E'lon to'xtatildi", a server warning) stays before the screen is itself again. */
internal const val NOTICE_SHOWN_MS = 6_000L

// -- client-listing-detail ---------------------------------------------------------------------------------------

@Composable
fun ListingDetailScreen(
    vm: ListingViewModel,
    ru: Boolean,
    languageTag: String,
    onBack: () -> Unit,
    onEdit: () -> Unit,
    onBids: () -> Unit,
    onCancelled: () -> Unit,
) {
    val s by vm.state.collectAsStateWithLifecycle()
    val now by rememberNow()
    var confirmCancel by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(s.cancelled) { if (s.cancelled) onCancelled() }
    LaunchedEffect(s.notice, s.warnings) {
        if (s.notice != null || s.warnings.isNotEmpty()) {
            delay(NOTICE_SHOWN_MS)
            vm.consumeNotice()
        }
    }
    StepScaffold(
        title = t(R.string.listingDetail_title),
        onBack = onBack,
        right = t(R.string.proposal_refresh),
        onRight = vm::refresh,
        banner = { ListingNotices(s) },
    ) {
        when (val load = s.listing) {
            Load.Loading -> LoadingLine(t(R.string.common_loading))
            is Load.Failed -> LoadFailed(t(R.string.listingDetail_title), load.error, vm::refresh)
            is Load.Ready -> {
                val listing = load.value
                val stats = (s.threads as? Load.Ready)?.value?.let { OrderRules.offerStats(it, now) }
                ListingItem(listing, stats, ru, languageTag)
                ListingDetails(listing, ru)
                ParcelPhoto(s)
                if (listing.status != ListingStatus.DRAFT) {
                    ElchiButton(t(R.string.client_listingDetail_viewOffers, "count" to (stats?.open ?: 0)), onBids, Modifier.fillMaxWidth())
                }
                OwnerControls(vm, s, listing, onEdit, onCancel = { confirmCancel = true })
            }
        }
    }
    val listing = s.value
    if (confirmCancel && listing != null) {
        val open = OrderRules.offerStats(s.threadList, now).open
        CancelSheet(
            title = t(R.string.confirmDialog_cancelOrder_title),
            text = if (open > 0) t(R.string.client_listingCancel_text, "count" to open) else t(R.string.client_listingCancel_textNoOffers),
            confirm = t(R.string.bookingCancel_confirm),
            back = t(R.string.confirmDialog_back),
            busy = s.action == OwnerAction.CANCEL,
            onConfirm = vm::cancel,
            onDismiss = { confirmCancel = false },
        )
    }
}

/** One-time outcomes of the owner's commands (paused, resumed, saved) and the server's warnings with them. */
@Composable
private fun ListingNotices(s: ListingViewModel.State) {
    s.notice?.let {
        val text = t(
            when (it) {
                ListingNotice.PAUSED -> R.string.listingOwner_paused
                ListingNotice.RESUMED -> R.string.listingOwner_resumed
                ListingNotice.SAVED -> R.string.listingOwner_saved
            },
        )
        Banner(text, Tone.OK)
    }
    s.warnings.forEach { Banner(tOrNull("warning.${it.code}") ?: it.message, Tone.WARN) }
}

/** The listing as its row in the orders list shows it: route, status, date · views · offers, price. */
@Composable
internal fun ListingItem(listing: ListingDTO, stats: OfferStats?, ru: Boolean, languageTag: String, meta: String? = null, onClick: (() -> Unit)? = null) {
    val parts = listOfNotNull(
        OrderRules.dayMonth(listing.departureWindowStart, languageTag),
        listing.viewCount?.let { if (it == 0L) t(R.string.listing_viewsNone) else "$it ${t(R.string.listing_viewsSuffix)}" },
        stats?.takeIf { OrderRules.isLive(listing.status) }?.let { t(R.string.app_orderCard_bids, "count" to it.open) },
    )
    ItemCard(
        title = "${OrderRules.shortEnd(listing.originStop, listing.originPoint, ru)} → ${OrderRules.shortEnd(listing.destinationStop, listing.destinationPoint, ru)}",
        badge = (tOrNull(OrderRules.listingStatusKey(listing.status)) ?: listing.status.value) to OrderRules.statusTone(listing.status.value),
        // Taksi: "2 kishi · 2 × 150 000 so'm" above the date line.
        lines = listOfNotNull(
            if (TaxiRules.isPassenger(listing.serviceType)) ItemLine(seatsLine(listing.quantity, listing.unitPriceMinor)) else null,
            ItemLine(parts.joinToString(" · ")),
        ),
        meta = meta,
        right = soum(listing.totalMinor),
        onClick = onClick,
    )
}

@Composable
private fun ListingDetails(listing: ListingDTO, ru: Boolean) {
    ElchiCard(bordered = true) {
        CardRow(
            t(if (listing.originStop != null) R.string.listingDetail_pickupStop else R.string.listingDetail_pickupPoint),
            OrderRules.fullEnd(listing.originStop, listing.originPoint, ru),
            first = true,
            detail = listing.originPoint?.district?.nameUz?.takeIf { listing.originStop == null && listing.originPoint.address != null },
        )
        CardRow(
            t(if (listing.destinationStop != null) R.string.listingDetail_dropoffStop else R.string.listingDetail_dropoffPoint),
            OrderRules.fullEnd(listing.destinationStop, listing.destinationPoint, ru),
            detail = listing.destinationPoint?.district?.nameUz?.takeIf { listing.destinationStop == null && listing.destinationPoint.address != null },
        )
        OrderRules.windowText(listing.departureWindowStart, listing.departureWindowEnd)?.let { CardRow(t(R.string.listingDetail_departureWindow), it) }
        if (TaxiRules.isPassenger(listing.serviceType)) {
            CardRow(t(R.string.orderForm_review_passengers), t(R.string.orderForm_review_peopleCount, "count" to listing.quantity), detail = t(R.string.orderForm_review_seatNegotiated))
            CardRow(
                t(R.string.common_price),
                soum(listing.totalMinor),
                detail = t(R.string.orderForm_review_perPersonDetail, "count" to listing.quantity, "price" to soum(listing.unitPriceMinor)),
                strong = true,
            )
        } else {
            CardRow(t(R.string.common_price), soum(listing.totalMinor), strong = true)
        }
        listing.parcel?.let { parcel ->
            val type = ParcelType.entries.firstOrNull { it == parcel.parcelType && it != ParcelType.UNKNOWN }?.let { parcelTypeLabel(it) }
            val category = parcel.category?.let { "${categoryName(it, ru)} (${categoryLimits(it)})" }
            listOfNotNull(type, category).joinToString(" · ").takeIf { it.isNotEmpty() }?.let { CardRow(t(R.string.listingDetail_parcel), it) }
        }
        listing.comment?.takeIf { it.isNotBlank() }?.let { CardRow(t(R.string.listingOwner_commentLabel), it.trim()) }
        if (OrderRules.isLive(listing.status)) {
            OrderRules.dayDot(listing.expiresAt)?.let { CardRow(t(R.string.client_listingDetail_expires), t(R.string.client_listingDetail_until, "date" to it)) }
        }
    }
}

@Composable
private fun ParcelPhoto(s: ListingViewModel.State) {
    if (s.value?.parcel?.photo == null) return
    ParcelPhotoBlock(s.photo, s.photoFailed)
}

/** "Posilka rasmi": the decoded photo, a calm failure line, or progress. Shared by the listing and booking screens. */
@Composable
internal fun ParcelPhotoBlock(photo: android.graphics.Bitmap?, failed: Boolean) {
    val c = Elchi.colors
    SectionTitle(t(R.string.listingDetail_parcelPhoto))
    Box(Modifier.fillMaxWidth().height(170.dp).clip(RoundedCornerShape(18.dp)).background(c.field), contentAlignment = Alignment.Center) {
        when {
            photo != null -> {
                val image = remember(photo) { photo.asImageBitmap() }
                Image(image, t(R.string.app_photo_alt), Modifier.fillMaxSize(), contentScale = ContentScale.Crop)
            }
            failed -> Text(t(R.string.app_photo_failed), style = Elchi.type.caption, color = c.muted)
            else -> LoadingLine(t(R.string.app_photo_loading))
        }
    }
}

/** "Boshqaruv", sharing and cancel - only what the listing's status allows (`ownerListingActions`). */
@Composable
private fun OwnerControls(vm: ListingViewModel, s: ListingViewModel.State, listing: ListingDTO, onEdit: () -> Unit, onCancel: () -> Unit) {
    val status = listing.status
    val canPause = OrderRules.canPause(status)
    val canResume = OrderRules.canResume(status)
    if (OrderRules.canEdit(status) || canPause || canResume) {
        SectionTitle(t(R.string.client_listingDetail_manage))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (OrderRules.canEdit(status)) {
                ElchiButton(
                    t(R.string.listingOwner_edit), { vm.startEdit(); onEdit() }, Modifier.weight(1f).height(48.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM,
                    icon = ElchiIcon.FILE, enabled = s.action == null, horizontalPadding = 10.dp,
                )
            }
            if (canPause || canResume) {
                ElchiButton(
                    t(if (canPause) R.string.listingOwner_pause else R.string.listingOwner_resume),
                    if (canPause) vm::pause else vm::resume,
                    Modifier.weight(1f).height(48.dp),
                    ButtonVariant.NEUTRAL,
                    ButtonSize.MEDIUM,
                    enabled = s.action == null,
                    loading = s.action == OwnerAction.PAUSE || s.action == OwnerAction.RESUME,
                    horizontalPadding = 10.dp,
                )
            }
        }
        if (canPause || canResume) {
            Text(t(if (canPause) R.string.listingOwner_pauseHint else R.string.client_listingDetail_resumeHint), style = Elchi.type.caption, color = Elchi.colors.muted)
        }
    }
    s.actionError?.let { Note(errorText(it), tone = Tone.ERR) }
    if (OrderRules.canShare(status)) ShareSection(vm, s)
    if (OrderRules.canCancel(status)) {
        ElchiButton(t(R.string.listingDetail_cancel), onCancel, Modifier.fillMaxWidth(), ButtonVariant.DANGER_SOFT, enabled = s.action == null)
    }
}

/**
 * "E'lonni ulashish": TTL chips (days -> `ttl_hours`), the text's channel, then the link the server returns once -
 * kept only while this screen lives - with copy and the phone's share sheet.
 */
@Composable
private fun ShareSection(vm: ListingViewModel, s: ListingViewModel.State) {
    val context = LocalContext.current
    SectionTitle(t(R.string.listingShare_title), description = t(R.string.trackingShare_shareHint))
    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OrderRules.SHARE_TTL_DAYS.forEach { days ->
            Chip(t(R.string.trackingShare_ttlDays, "count" to days), s.shareDays == days, { vm.setShareDays(days) }, filled = true)
        }
    }
    Segmented(
        listOf(ShareLinkChannel.GENERIC to t(R.string.trackingShare_channelGeneric), ShareLinkChannel.TELEGRAM to t(R.string.client_share_telegram)),
        s.shareChannel,
        vm::setShareChannel,
    )
    ElchiButton(t(R.string.trackingShare_create), vm::createShareLink, Modifier.fillMaxWidth(), ButtonVariant.SOFT, icon = ElchiIcon.SHARE, loading = s.sharing)
    s.shareError?.let { Note(shareErrorText(it), tone = Tone.ERR) }
    if (s.linkRevoked) Note(t(R.string.trackingShare_revoked), tone = Tone.OK)
    s.link?.let { ShareResult(it, context, onRevoke = vm::revokeShareLink, busy = s.sharing) }
}

@Composable
private fun ShareResult(link: ShareLinkDTO, context: Context, onRevoke: () -> Unit, busy: Boolean) {
    val c = Elchi.colors
    val activity = LocalActivity.current
    var copied by remember(link.id) { mutableStateOf(false) }
    val chooserTitle = t(R.string.client_share_send)
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(t(R.string.client_share_link), style = Elchi.type.caption, color = c.muted)
        Text(
            link.url,
            Modifier.fillMaxWidth().heightIn(min = 44.dp).clip(RoundedCornerShape(14.dp)).background(c.field).padding(horizontal = 14.dp, vertical = 12.dp),
            style = Elchi.type.label.copy(fontFamily = FontFamily.Monospace),
            color = c.text,
        )
        Text(t(R.string.client_share_text), style = Elchi.type.caption, color = c.muted)
        Text(link.shareText, Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(c.field).padding(horizontal = 14.dp, vertical = 10.dp), style = Elchi.type.caption, color = c.text)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ElchiButton(
                t(if (copied) R.string.promoScreen_copied else R.string.promoScreen_copy),
                {
                    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                    clipboard.setPrimaryClip(ClipData.newPlainText("ELCHI", link.url))
                    copied = true
                },
                Modifier.weight(1f).height(48.dp),
                ButtonVariant.NEUTRAL,
                ButtonSize.MEDIUM,
                icon = ElchiIcon.COPY,
                horizontalPadding = 10.dp,
            )
            ElchiButton(
                chooserTitle,
                {
                    // Nothing is posted for the person (§20.2): the phone's own share sheet, with the server's text.
                    val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, link.shareText)
                    val chooser = Intent.createChooser(send, chooserTitle)
                    // LocalContext is the app-language configuration context, not the Activity: start from the
                    // Activity when there is one, else as a new task.
                    activity?.startActivity(chooser) ?: context.startActivity(chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                },
                Modifier.weight(1f).height(48.dp),
                ButtonVariant.SOFT,
                ButtonSize.MEDIUM,
                icon = ElchiIcon.SHARE,
                horizontalPadding = 10.dp,
            )
        }
        OrderRules.dayDot(link.expiresAt)?.let { day ->
            val time = OrderRules.tashkent(link.expiresAt)?.let { "$day, %02d:%02d".format(it.hour, it.minute) } ?: day
            Text(t(R.string.trackingShare_validUntil, "time" to time), style = Elchi.type.caption, color = c.muted)
        }
        Text(t(R.string.trackingShare_urlOnce), style = Elchi.type.caption, color = c.muted)
        ElchiButton(t(R.string.client_share_revoke), onRevoke, Modifier.fillMaxWidth().height(44.dp), ButtonVariant.GHOST, ButtonSize.MEDIUM, enabled = !busy)
    }
}

/**
 * `listing-cancel`: the confirmation sheet (never a one-tap cancel); also the v1 `ConfirmSheet` (select a driver,
 * confirm delivery) with a primary [confirmVariant]. Strings come resolved - the sheet is its own window. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun CancelSheet(
    title: String,
    text: String,
    confirm: String,
    back: String,
    busy: Boolean,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
    confirmVariant: ButtonVariant = ButtonVariant.DANGER,
) {
    val c = Elchi.colors
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true), containerColor = c.card) {
        Column(Modifier.padding(horizontal = 16.dp).padding(bottom = 16.dp).navigationBarsPadding(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(title, style = Elchi.type.title.copy(fontSize = androidx.compose.ui.unit.TextUnit(20f, androidx.compose.ui.unit.TextUnitType.Sp), lineHeight = androidx.compose.ui.unit.TextUnit(24f, androidx.compose.ui.unit.TextUnitType.Sp)), color = c.text)
                Text(text, style = Elchi.type.secondary, color = c.muted)
            }
            ElchiButton(confirm, onConfirm, Modifier.fillMaxWidth(), confirmVariant, loading = busy)
            ElchiButton(back, onDismiss, Modifier.fillMaxWidth(), ButtonVariant.NEUTRAL, enabled = !busy)
        }
    }
}

// -- listing-edit ------------------------------------------------------------------------------------------------

private enum class EditEdge { START, END }

private val WINDOW_INVALID = setOf(EditInvalid.WINDOW_INCOMPLETE, EditInvalid.WINDOW_ORDER, EditInvalid.WINDOW_PAST)

@Composable
fun ListingEditScreen(vm: ListingViewModel, onBack: () -> Unit, onSaved: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { if (vm.state.value.form == null) vm.startEdit() }
    LaunchedEffect(s.saved) {
        if (s.saved) {
            vm.consumeSaved()
            onSaved()
        }
    }
    val listing = s.value
    val form = s.form
    var picking by rememberSaveable { mutableStateOf<EditEdge?>(null) }
    val plan = if (listing != null && form != null) OrderRules.planListingPatch(listing, form, Instant.now()) else null
    val openOffers = OrderRules.offerStats(s.threadList, Instant.now()).open
    // Q20: ask for the second, explicit tap only when the edit really closes offers that exist.
    val warnMaterial = plan?.material == true && openOffers > 0
    StepScaffold(
        title = t(R.string.listingOwner_editTitle),
        onBack = onBack,
        footer = {
            s.saveError?.let { Note(errorText(it), tone = Tone.ERR) }
            ElchiButton(
                t(if (warnMaterial) R.string.listingOwner_materialConfirm else R.string.common_save),
                vm::save,
                Modifier.fillMaxWidth(),
                enabled = plan != null && !plan.empty && plan.invalid == null,
                loading = s.saving,
            )
        },
    ) {
        if (listing == null || form == null) {
            LoadingLine(t(R.string.common_loading))
            return@StepScaffold
        }
        ElchiField(
            form.priceDigits,
            { text -> vm.editForm { it.copy(priceDigits = text.filter(Char::isDigit).trimStart('0').take(10)) } },
            // A passenger request's price is per person ("Narx (so'm) / o'rin").
            label = t(R.string.listingOwner_priceLabel) + if (TaxiRules.isPassenger(listing.serviceType)) " " + t(R.string.listingEdit_perSeatSuffix).trim() else "",
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Next),
            visualTransformation = ThousandsTransformation,
            error = if (plan?.invalid == EditInvalid.PRICE) t(R.string.listingOwner_invalid_price) else null,
        )
        ElchiField(
            form.comment,
            { text -> vm.editForm { it.copy(comment = text.take(1000)) } },
            label = t(R.string.listingOwner_commentLabel),
            singleLine = false,
            minHeight = 96.dp,
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
            hint = t(R.string.app_bookingCancel_commentHint),
        )
        if (TaxiRules.seatsEditable(listing)) {
            // Q145: the number of people, until a booking exists; a new count closes the open offers (Q20).
            val seatsError = plan?.invalid?.takeIf { it == EditInvalid.SEATS || it == EditInvalid.SEATS_CHILDREN }
            ElchiField(
                form.seats,
                { text -> vm.editForm { it.copy(seats = text.filter(Char::isDigit).take(1)) } },
                label = t(R.string.listingEdit_seats),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Next),
                hint = t(R.string.listingEdit_seatsHint),
                error = seatsError?.let { tOrNull("listingOwner.invalid.${it.key}") ?: it.key },
            )
        }
        if (OrderRules.windowEditable(listing)) {
            val placeholder = t(R.string.client_routeSummary_windowPlaceholder)
            val windowError = plan?.invalid?.takeIf { it in WINDOW_INVALID }
            PickerField(t(R.string.listingOwner_windowStart), form.windowStart?.let(ParcelRules::display), placeholder, { picking = EditEdge.START }, error = windowError != null)
            PickerField(t(R.string.listingOwner_windowEnd), form.windowEnd?.let(ParcelRules::display), placeholder, { picking = EditEdge.END }, error = windowError != null)
            windowError?.let { Note(tOrNull("listingOwner.invalid.${it.key}") ?: it.key, tone = Tone.ERR) }
        }
        Text(t(R.string.listingOwner_nonMaterialNote), style = Elchi.type.label.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.Normal), color = Elchi.colors.muted)
        if (warnMaterial) {
            Note("${t(R.string.listingOwner_materialWarning)} ${t(R.string.listingOwner_openOffers, "count" to openOffers)}", tone = Tone.WARN)
        }
    }
    picking?.let { edge ->
        val current = if (edge == EditEdge.START) form?.windowStart else form?.windowEnd
        DateTimeDialog(
            title = t(if (edge == EditEdge.START) R.string.listingOwner_windowStart else R.string.listingOwner_windowEnd),
            initial = current ?: ParcelRules.defaultWindow(Instant.now()).let { if (edge == EditEdge.START) it.first else it.second },
            onDismiss = { picking = null },
            onPicked = { value ->
                picking = null
                vm.editForm { if (edge == EditEdge.START) it.copy(windowStart = value) else it.copy(windowEnd = value) }
            },
        )
    }
}

// -- client-listing-bids -----------------------------------------------------------------------------------------

@Composable
fun ListingBidsScreen(vm: ListingViewModel, ru: Boolean, onBack: () -> Unit, onAccepted: (Accepted) -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val b by vm.board.state.collectAsStateWithLifecycle()
    val now by rememberNow()
    LaunchedEffect(b.accepted) {
        b.accepted?.let {
            vm.board.consumeAccepted()
            onAccepted(it)
        }
    }
    val threads = OrderRules.sortOffers(s.threadList, s.sort, now)
    val cheapest = OrderRules.cheapestOpen(s.threadList, now)
    val paused = s.value?.status == ListingStatus.PAUSED
    // Offers move while the screen is away: every visit reads them again (the list stays on screen meanwhile).
    LaunchedEffect(Unit) { vm.refresh() }
    LaunchedEffect(b.notice, b.warnings) {
        if (b.notice != null || b.warnings.isNotEmpty()) {
            delay(NOTICE_SHOWN_MS)
            vm.board.consumeNotice()
        }
    }
    StepScaffold(
        title = t(R.string.listingBids_title),
        onBack = onBack,
        right = t(R.string.proposal_refresh),
        onRight = vm::refresh,
        banner = { OfferNoticeBanner(b.notice, b.warnings) },
    ) {
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(
                OfferSort.CHEAPEST to R.string.client_listingBids_sortCheapest,
                OfferSort.FASTEST to R.string.client_listingBids_sortFastest,
                OfferSort.RATING to R.string.client_listingBids_sortRating,
            ).forEach { (sort, label) -> Chip(t(label), s.sort == sort, { vm.setSort(sort) }, filled = true) }
        }
        when (val load = s.threads) {
            Load.Loading -> LoadingLine(t(R.string.common_loading))
            is Load.Failed -> LoadFailed(t(R.string.listingBids_title), load.error, vm::refresh)
            is Load.Ready -> if (load.value.isEmpty()) {
                EmptyState(ElchiIcon.TAG, t(R.string.listingBids_emptyTitle), description = t(R.string.listingBids_emptySubtitle))
            } else {
                threads.forEach { thread ->
                    val actions = OrderRules.negotiationActions(thread, now)
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        // The answer buttons live inside their own offer's card, so they cannot be read as the next one's.
                        val answer: (@Composable ColumnScope.() -> Unit)? = if (actions.open && actions.theirTurn) {
                            {
                                OfferAnswer(
                                    thread, actions, b,
                                    acceptLabel = t(R.string.listingBids_chooseDriver),
                                    onBonus = { vm.board.toggleAcceptBonus(thread.id) },
                                    onAccept = { vm.board.askAccept(thread) },
                                    onReject = { vm.board.reject(thread) },
                                    onCounter = { vm.board.openCounter(thread) },
                                    onCounterDigits = { vm.board.setCounterDigits(thread, it) },
                                    onCounterBonus = vm.board::setCounterBonus,
                                    onSendCounter = { vm.board.sendCounter(thread) },
                                    onCloseCounter = vm.board::closeCounter,
                                    counterPrice = vm.board.counterPrice(thread),
                                    listingPaused = paused,
                                )
                            }
                        } else {
                            null
                        }
                        OfferCard(thread, actions, cheapest == thread.id, now, ru, busy = b.busyThread == thread.id, onWithdraw = { vm.board.withdraw(thread) }, answer = answer)
                        if (answer == null && b.errorThread == thread.id) {
                            b.error?.let { Note(offerErrorText(it), tone = Tone.ERR) }
                        }
                    }
                }
            }
        }
        Note(t(R.string.listingBids_identityHidden), tone = Tone.BLUE)
    }
    val confirming = s.threadList.firstOrNull { it.id == b.confirming }
    if (confirming != null) AcceptDialogFor(confirming, b, onConfirm = { vm.board.accept(confirming) }, onDismiss = vm.board::dismissAccept)
}

/**
 * One driver's offer (`item` with the "Haydovchi #N" rule): live and waiting for the client, waiting for the
 * driver (the client's counter; it can be withdrawn), or closed (grey, why, nothing to press).
 */
@Composable
private fun OfferCard(
    thread: ProposalThreadDTO,
    actions: NegotiationActions,
    cheapest: Boolean,
    now: Instant,
    ru: Boolean,
    busy: Boolean,
    onWithdraw: () -> Unit,
    answer: (@Composable ColumnScope.() -> Unit)? = null,
) {
    val c = Elchi.colors
    val version = thread.currentVersion
    val summary = thread.driverSummary?.let { driverSummary(it) }
    val price = version?.let { soum(it.totalMinor) }
    val route = version?.let { "${OrderRules.shortEnd(it.pickupStop, it.pickupPoint, ru)} → ${OrderRules.shortEnd(it.dropoffStop, it.dropoffPoint, ru)}" }
    val message = version?.message?.takeIf { it.isNotBlank() }?.let { ItemLine("“${it.trim()}”", c.text) }
    // Taksi: the offer is per person - "2 × 160 000 so'm" under the total.
    val perSeat = version?.takeIf { it.priceBasis == PriceBasis.PER_SEAT }?.let { ItemLine(seatsPrice(it.quantity, it.unitPriceMinor)) }
    when {
        version == null || !actions.open -> ItemCard(
            title = driverLabel(thread),
            underlined = true,
            sub = t(R.string.listingBids_closed, "status" to closedStatus(thread, now)),
            right = price,
            rightColor = c.placeholder,
        )
        actions.theirTurn -> ItemCard(
            title = driverLabel(thread),
            underlined = true,
            highlighted = cheapest,
            badge = if (cheapest) t(R.string.client_listingBids_cheapest) to Tone.OK else null,
            sub = route,
            lines = listOfNotNull(
                perSeat,
                OrderRules.windowText(version.pickupWindowStart, version.pickupWindowEnd)?.let { ItemLine(it) },
                summary?.let { ItemLine(it) },
                message,
                OrderRules.secondsLeft(version, now)?.let { ItemLine(countdownText(it), c.tone(Tone.WARN).fg) },
            ),
            right = price,
            rightColor = c.accentText,
            footer = answer,
        )
        else -> ItemCard(
            title = driverLabel(thread),
            underlined = true,
            sub = summary,
            lines = listOfNotNull(
                perSeat,
                ItemLine(t(R.string.listingBids_awaitingDriver)),
                OrderRules.secondsLeft(version, now)?.let { ItemLine(countdownText(it), c.tone(Tone.WARN).fg) },
            ),
            right = price,
            rightColor = c.accentText,
            footer = {
                ElchiButton(t(R.string.proposals_withdraw), onWithdraw, Modifier.fillMaxWidth().height(46.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM, enabled = actions.canWithdraw, loading = busy)
            },
        )
    }
}
