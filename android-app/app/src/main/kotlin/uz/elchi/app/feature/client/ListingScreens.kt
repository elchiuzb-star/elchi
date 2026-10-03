package uz.elchi.app.feature.client

import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import androidx.activity.compose.LocalActivity
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.relocation.BringIntoViewRequester
import androidx.compose.foundation.relocation.bringIntoViewRequester
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
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
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.layout
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.delay
import uz.elchi.app.R
import uz.elchi.app.api.generated.ListingDTO
import uz.elchi.app.api.generated.ListingStatus
import uz.elchi.app.api.generated.ParcelType
import uz.elchi.app.api.generated.ProposalThreadDTO
import uz.elchi.app.api.generated.ShareLinkDTO
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.Banner
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.Chip
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiField
import uz.elchi.app.ui.components.ElchiIconView
import uz.elchi.app.ui.components.ItemCard
import uz.elchi.app.ui.components.ItemLine
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.PickerField
import uz.elchi.app.ui.components.RoundIconButton
import uz.elchi.app.ui.components.SectionTitle
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.map.ElchiMap
import uz.elchi.app.ui.map.GeoPoint
import uz.elchi.app.ui.map.MapFocus
import uz.elchi.app.ui.map.MapKitSupport
import uz.elchi.app.ui.map.MapMarker
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone
import java.time.Instant

/** How long a one-time outcome (a server warning) stays before the screen is itself again. */
internal const val NOTICE_SHOWN_MS = 6_000L

// -- client-listing-detail ---------------------------------------------------------------------------------------

/**
 * `listing` "Buyurtma tafsilotlari" (BOSQICH 03): a still map of the direction, the sheet card (status, tracker,
 * window, facts), the status notice, then the drivers' offers inline (sort chips, offer cards, accept / counter /
 * reject) and the owner's controls. The bar has the pencil (edit; designer to confirm) and share (a link made once
 * on this screen, then the phone's share sheet). [scrollToOffers]: opened from a notification about an offer - the
 * screen starts at "Haydovchi takliflari".
 */
@Composable
fun ListingDetailScreen(
    vm: ListingViewModel,
    ru: Boolean,
    languageTag: String,
    onBack: () -> Unit,
    onEdit: () -> Unit,
    onCancelled: () -> Unit,
    onAccepted: (Accepted) -> Unit,
    scrollToOffers: Boolean = false,
) {
    val s by vm.state.collectAsStateWithLifecycle()
    val b by vm.board.state.collectAsStateWithLifecycle()
    val now by rememberNow()
    var confirmCancel by rememberSaveable { mutableStateOf(false) }
    val toast = LocalFlowToast.current
    LaunchedEffect(s.cancelled) { if (s.cancelled) onCancelled() }
    LaunchedEffect(b.accepted) {
        b.accepted?.let {
            vm.board.consumeAccepted()
            onAccepted(it)
        }
    }
    ListingNoticeToast(s.notice, vm::consumeNotice)
    OfferNoticeToast(b.notice) { vm.board.consumeNotice() }
    ShareEffects(s, vm, toast)
    val listing = s.value
    StepScaffold(
        title = t(R.string.listingDetail_title),
        onBack = onBack,
        onRefresh = vm::refresh,
        refreshing = s.refreshing && listing != null,
        banner = {
            s.warnings.forEach { Banner(tOrNull("warning.${it.code}") ?: it.message, Tone.WARN) }
            OfferWarnings(b.warnings) { vm.board.consumeNotice() }
        },
        actions = listing?.let { l ->
            {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    if (OrderRules.canEdit(l.status)) {
                        RoundIconButton(ElchiIcon.FILE, t(R.string.listingOwner_edit), { vm.startEdit(); onEdit() }, iconRes = R.drawable.ic_pencil)
                    }
                    if (OrderRules.canShare(l.status)) {
                        RoundIconButton(ElchiIcon.SHARE, t(R.string.client_share_send), vm::share, loading = s.sharing)
                    }
                }
            }
        },
    ) {
        when (val load = s.listing) {
            Load.Loading -> LoadingLine(t(R.string.common_loading))
            is Load.Failed -> LoadFailed(t(R.string.listingDetail_title), load.error, vm::refresh)
            is Load.Ready -> {
                val l = load.value
                val stats = OrderRules.offerStats(s.threadList, now)
                HeroMap(l)
                ListingSheet(l, s, stats, ru, hasMap = heroMapShown(l))
                OrderRules.listingNotice(l.status)?.let { (key, tone) -> StatusNotice(tOrNull(key) ?: key, tone) }
                OffersSection(vm, s, b, l, stats, now, ru, scrollToOffers)
                ShareLinkRow(s, vm)
                OwnerControls(vm, s, l, onCancel = { confirmCancel = true })
            }
        }
    }
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
    val confirming = s.threadList.firstOrNull { it.id == b.confirming }
    if (confirming != null) AcceptDialogFor(confirming, b, onConfirm = { vm.board.accept(confirming) }, onDismiss = vm.board::dismissAccept)
}

/** "E'lon to'xtatildi", "Saqlandi · 2 ta ochiq taklif yopildi" ... as the design's toast. */
@Composable
private fun ListingNoticeToast(notice: ListingNotice?, consume: () -> Unit) {
    val toast = LocalFlowToast.current
    val text = when (notice) {
        ListingNotice.Paused -> t(R.string.listingOwner_paused)
        ListingNotice.Resumed -> t(R.string.listingOwner_resumed)
        ListingNotice.Saved -> t(R.string.listingOwner_saved)
        is ListingNotice.SavedClosed -> t(R.string.client_listing_savedClosed, "count" to notice.count)
        null -> null
    }
    LaunchedEffect(notice) {
        if (text != null) {
            toast.show(text)
            // The server's warnings (a banner) stay their own time; only the toast is consumed here.
            delay(NOTICE_SHOWN_MS)
            consume()
        }
    }
}

/**
 * The bar's share: the phone's share sheet with the server's `share_text` (never a text of our own, §3). Without one
 * the URL is copied and the toast says the person's name and phone are not shown. A refusal (5 live links) is a toast.
 */
@Composable
private fun ShareEffects(s: ListingViewModel.State, vm: ListingViewModel, toast: FlowToast) {
    val context = LocalContext.current
    val activity = LocalActivity.current
    val chooserTitle = t(R.string.client_share_send)
    val copied = t(R.string.client_listing_shareCopied)
    LaunchedEffect(s.shareNow) {
        val link = s.shareNow ?: return@LaunchedEffect
        vm.consumeShareNow()
        val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, link.shareText)
        val chooser = Intent.createChooser(send, chooserTitle)
        try {
            // LocalContext is the app-language configuration context, not the Activity: start from the Activity.
            activity?.startActivity(chooser) ?: context.startActivity(chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (e: ActivityNotFoundException) {
            copyLink(context, link)
            toast.show(copied)
        }
    }
    val error = s.shareError?.let { shareErrorText(it) }
    LaunchedEffect(s.shareError) {
        if (error != null) {
            toast.show(error)
            vm.consumeShareError()
        }
    }
}

private fun copyLink(context: Context, link: ShareLinkDTO) {
    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    clipboard.setPrimaryClip(ClipData.newPlainText("ELCHI", link.url))
}

/** The listing as its row in the orders list shows it: route, status, date · views · offers, meta, price. */
@Composable
internal fun ListingItem(listing: ListingDTO, stats: OfferStats?, ru: Boolean, languageTag: String, meta: Pair<String, Color?>? = null, onClick: (() -> Unit)? = null) {
    val parts = listOfNotNull(
        OrderRules.dayMonth(listing.departureWindowStart, languageTag),
        listing.viewCount?.let { if (it == 0L) t(R.string.listing_viewsNone) else "$it ${t(R.string.listing_viewsSuffix)}" },
        stats?.takeIf { OrderRules.isLive(listing.status) }?.let { t(R.string.app_orderCard_bids, "count" to it.open) },
    )
    ItemCard(
        title = routeTitle(listing, ru),
        badge = listingBadge(listing.status),
        // Taksi: "2 kishi · 2 × 150 000 so'm" above the date line.
        lines = listOfNotNull(
            if (TaxiRules.isPassenger(listing.serviceType)) ItemLine(seatsLine(listing.quantity, listing.unitPriceMinor)) else null,
            ItemLine(parts.joinToString(" · ")),
        ),
        meta = meta?.first,
        metaColor = meta?.second,
        right = soum(listing.totalMinor),
        onClick = onClick,
    )
}

/** "Toshkent → Buxoro" */
@Composable
internal fun routeTitle(listing: ListingDTO, ru: Boolean): String =
    "${OrderRules.shortEnd(listing.originStop, listing.originPoint, ru)} → ${OrderRules.shortEnd(listing.destinationStop, listing.destinationPoint, ru)}"

/** The listing's status pill: "Bron qilindi" for a fulfilled request (the client's word), the shared word otherwise. */
@Composable
internal fun listingBadge(status: ListingStatus): Pair<String, Tone> =
    (tOrNull(OrderRules.clientListingStatusKey(status)) ?: status.value) to OrderRules.statusTone(status.value)

private fun heroMapShown(listing: ListingDTO): Boolean =
    MapKitSupport.likelyAvailable && (listing.originPoint != null || listing.destinationPoint != null)

/**
 * The 150dp still map of the direction (design hero): the two marked places and a line between them. The pill says
 * "Yo'nalish" - the listing carries no distance (2.1, BLOCKED). Hidden without coordinates or a usable map.
 */
@Composable
private fun HeroMap(listing: ListingDTO) {
    var usable by remember { mutableStateOf(MapKitSupport.likelyAvailable) }
    if (!usable || !heroMapShown(listing)) return
    val c = Elchi.colors
    val markers = remember(listing.id) {
        listOfNotNull(
            listing.originPoint?.let { MapMarker(GeoPoint(it.lat, it.lng), MapMarker.Kind.ORIGIN) },
            listing.destinationPoint?.let { MapMarker(GeoPoint(it.lat, it.lng), MapMarker.Kind.DESTINATION) },
        )
    }
    // The listing has no road geometry: a straight line between the two places shows the direction only.
    val route = remember(markers) { if (markers.size == 2) listOf(markers[0].point, markers[1].point) else emptyList() }
    val focus = remember(markers) { MapFocus.Fit(markers.map { it.point }) }
    Box(Modifier.fillMaxWidth().height(150.dp).padding(horizontal = 0.dp).clip(RoundedCornerShape(24.dp))) {
        ElchiMap(
            Modifier.fillMaxSize(),
            markers = markers,
            route = route,
            focus = focus,
            padding = PaddingValues(start = 28.dp, end = 28.dp, top = 20.dp, bottom = 48.dp),
            logoBottom = 40.dp,
            interactive = false,
            onAvailability = { usable = it },
            placeholderTitle = t(R.string.client_map_unavailable),
        )
        Row(
            Modifier
                .align(Alignment.BottomEnd)
                .padding(end = 12.dp, bottom = 46.dp)
                .shadow(8.dp, CircleShape, ambientColor = c.shadow, spotColor = c.shadow)
                .clip(CircleShape)
                .background(c.card)
                .padding(horizontal = 12.dp, vertical = 7.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Box(Modifier.size(8.dp).clip(CircleShape).background(Color(0xFF9AA6B5)))
            Text(t(R.string.routeSummary_direction), style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold, fontSize = 12.5.sp), color = c.text)
        }
    }
}

/**
 * The sheet card over the map: route and "Holat" with the status pill (there is no short public listing code, 2.2),
 * the 5-step tracker, the window ends with their places, then the facts grid (with the parcel photo column) and the
 * comment and expiry the design drops.
 */
@Composable
private fun ListingSheet(listing: ListingDTO, s: ListingViewModel.State, stats: OfferStats, ru: Boolean, hasMap: Boolean) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(28.dp)
    Column(
        Modifier
            .fillMaxWidth()
            // Overlaps the map by 34dp and gives that space back, so the next block keeps the usual gap.
            .then(if (hasMap) Modifier.layout { measurable, constraints ->
                val placeable = measurable.measure(constraints)
                val lift = 34.dp.roundToPx()
                layout(placeable.width, placeable.height - lift) { placeable.place(0, -lift) }
            } else Modifier)
            .shadow(12.dp, shape, ambientColor = c.shadow, spotColor = c.shadow)
            .clip(shape)
            .background(c.card)
            .padding(start = 18.dp, end = 18.dp, top = 20.dp, bottom = 20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Box(Modifier.fillMaxWidth()) {
            Box(Modifier.align(Alignment.TopCenter).offset(y = (-12).dp).width(44.dp).height(5.dp).clip(CircleShape).background(c.outline))
        }
        Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(routeTitle(listing, ru), Modifier.weight(1f), style = Elchi.type.section.copy(fontSize = 18.sp, lineHeight = 23.sp), color = c.text)
            Column(horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(t(R.string.support_statusLabel), style = Elchi.type.caption, color = c.muted)
                val (text, tone) = listingBadge(listing.status)
                val colors = c.tone(tone)
                Text(
                    text,
                    Modifier.clip(RoundedCornerShape(16.dp)).background(colors.bg).padding(horizontal = 14.dp, vertical = 7.dp),
                    style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold, fontSize = 12.5.sp, lineHeight = 16.sp),
                    color = colors.fg,
                    textAlign = TextAlign.End,
                )
            }
        }
        Tracker(OrderRules.listingProgress(listing, s.threadList, s.bookingStatus))
        val startPlace = OrderRules.shortPlace(OrderRules.fullEnd(listing.originStop, listing.originPoint, ru))
        val endPlace = OrderRules.shortPlace(OrderRules.fullEnd(listing.destinationStop, listing.destinationPoint, ru))
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(t(R.string.client_listing_departAt, "time" to (OrderRules.dayTime(listing.departureWindowStart) ?: "—")), style = Elchi.type.caption, color = c.muted)
                Text(startPlace, style = Elchi.type.secondary.copy(fontWeight = FontWeight.Medium, fontSize = 15.sp), color = c.text)
            }
            Column(Modifier.weight(1f), horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(t(R.string.client_listing_deadlineAt, "time" to (OrderRules.dayTime(listing.departureWindowEnd) ?: "—")), style = Elchi.type.caption, color = c.muted, textAlign = TextAlign.End)
                Text(endPlace, style = Elchi.type.secondary.copy(fontWeight = FontWeight.Medium, fontSize = 15.sp), color = c.text, textAlign = TextAlign.End)
            }
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(if (c.isDark) c.line else Color(0xFFEEF1F5)))
        FactsGrid(listing, s, stats, ru)
        val extras = buildList {
            listing.comment?.takeIf { it.isNotBlank() }?.let { add(t(R.string.listingOwner_commentLabel) to it.trim()) }
            if (OrderRules.isLive(listing.status)) {
                OrderRules.dayDot(listing.expiresAt)?.let { add(t(R.string.client_listingDetail_expires) to t(R.string.client_listingDetail_until, "date" to it)) }
            }
        }
        extras.forEach { (key, value) -> Fact(key, value) }
    }
}

/** Five dots joined by dotted lines: E'lon qilindi · Takliflar · Haydovchi tanlandi · Yo'lda · Yakunlandi. */
@Composable
private fun Tracker(progress: ListingProgress) {
    val c = Elchi.colors
    val names = listOf(
        t(R.string.app_orderStatus_published),
        t(R.string.client_listing_stepOffers),
        t(R.string.listingBids_driverChosen),
        t(R.string.status_in_transit),
        t(R.string.app_progress_completed),
    )
    val idle = if (c.isDark) c.field else Color(0xFFEEF1F5)
    Row(
        Modifier.fillMaxWidth().semantics { contentDescription = names.take(progress.step + 1).joinToString(" · ") },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        names.forEachIndexed { i, _ ->
            val done = !progress.stopped && i <= progress.step
            val crossed = progress.stopped && i == 1
            val bg = when {
                done -> c.brand
                crossed -> c.tone(Tone.ERR).bg
                else -> idle
            }
            Box(
                Modifier
                    .size(26.dp)
                    .clip(CircleShape)
                    .background(bg)
                    .then(if (!progress.stopped && i == progress.step) Modifier.border(3.dp, Color(0xFFBFE3FF), CircleShape) else Modifier),
                contentAlignment = Alignment.Center,
            ) {
                ElchiIconView(if (crossed) ElchiIcon.X else ElchiIcon.CHECK, if (crossed) c.tone(Tone.ERR).fg else if (done) c.onBrand else c.placeholder, size = 13.dp)
            }
            if (i < names.lastIndex) {
                val lineColor = if (!progress.stopped && i < progress.step) c.brand else c.outline
                DottedLine(lineColor, Modifier.weight(1f).padding(horizontal = 4.dp))
            }
        }
    }
}

@Composable
private fun DottedLine(color: Color, modifier: Modifier) {
    androidx.compose.foundation.Canvas(modifier.height(3.dp)) {
        val r = size.height / 2
        var x = r
        while (x < size.width) {
            drawCircle(color, r, androidx.compose.ui.geometry.Offset(x, r))
            x += r * 3.2f
        }
    }
}

/**
 * Qayerdan / Qayerga / Narx / Ko'rishlar / Posilka (Taksi: Yo'lovchilar) / Takliflar, two columns; a parcel with a
 * photo gets the design's 92dp photo column beside the first three rows.
 */
@Composable
private fun FactsGrid(listing: ListingDTO, s: ListingViewModel.State, stats: OfferStats, ru: Boolean) {
    val taxi = TaxiRules.isPassenger(listing.serviceType)
    val facts = buildList {
        add(Triple(t(R.string.ui_from), OrderRules.fullEnd(listing.originStop, listing.originPoint, ru), null))
        add(Triple(t(R.string.ui_to), OrderRules.fullEnd(listing.destinationStop, listing.destinationPoint, ru), null))
        add(Triple(t(R.string.common_price), soum(listing.totalMinor), if (taxi) seatsPrice(listing.quantity, listing.unitPriceMinor) else null))
        add(Triple(t(R.string.client_listing_views), t(R.string.client_listing_viewsCount, "count" to (listing.viewCount ?: 0L)), null))
        if (taxi) {
            add(Triple(t(R.string.orderForm_review_passengers), t(R.string.orderForm_review_peopleCount, "count" to listing.quantity), null))
        } else {
            val parcel = listing.parcel
            val size = parcel?.category?.let { categoryName(it, ru) }
                ?: parcel?.parcelType?.takeIf { it != ParcelType.UNKNOWN }?.let { parcelTypeLabel(it) }
            add(Triple(t(R.string.listingDetail_parcel), size ?: "—", null))
        }
        add(Triple(t(R.string.client_listing_stepOffers), t(R.string.client_listing_offersOpenShort, "count" to stats.open), null))
    }
    val photo = !taxi && listing.parcel?.photo != null
    val rows = facts.chunked(2)
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            rows.forEach { pair ->
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    pair.forEach { (k, v, d) -> Fact(k, v, Modifier.weight(1f), d) }
                    if (pair.size == 1) Spacer(Modifier.weight(1f))
                }
            }
        }
        if (photo) PhotoColumn(s)
    }
}

@Composable
private fun Fact(key: String, value: String, modifier: Modifier = Modifier, detail: String? = null) {
    val c = Elchi.colors
    Column(modifier, verticalArrangement = Arrangement.spacedBy(3.dp)) {
        Text(key, style = Elchi.type.caption, color = c.muted)
        Text(value, style = Elchi.type.secondary.copy(fontWeight = FontWeight.Medium, fontSize = 14.5.sp, lineHeight = 19.sp), color = c.text)
        if (detail != null) Text(detail, style = Elchi.type.caption, color = c.muted)
    }
}

/** The parcel photo beside the facts (92 x 150): the signed thumbnail, a calm failure line, or progress. */
@Composable
private fun PhotoColumn(s: ListingViewModel.State) {
    val c = Elchi.colors
    Box(
        Modifier.width(92.dp).height(150.dp).clip(RoundedCornerShape(20.dp)).background(c.field),
        contentAlignment = Alignment.Center,
    ) {
        val photo = s.photo
        when {
            photo != null -> {
                val image = remember(photo) { photo.asImageBitmap() }
                Image(image, t(R.string.app_photo_alt), Modifier.fillMaxSize(), contentScale = ContentScale.Crop)
            }
            s.photoFailed -> Text(t(R.string.app_photo_failed), Modifier.padding(6.dp), style = Elchi.type.caption.copy(fontSize = 10.5.sp, lineHeight = 14.sp), color = c.muted, textAlign = TextAlign.Center)
            else -> androidx.compose.material3.CircularProgressIndicator(Modifier.size(20.dp), color = c.brand, strokeWidth = 2.dp)
        }
    }
}

/** The status notice under the card (paused / expired grey, cancelled red, fulfilled green). */
@Composable
private fun StatusNotice(text: String, tone: Tone) {
    val c = Elchi.colors
    val colors = c.tone(tone)
    val icon = when (tone) {
        Tone.ERR -> ElchiIcon.ALERT
        Tone.OK -> ElchiIcon.CHECK_C
        else -> ElchiIcon.INFO
    }
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(colors.bg).padding(horizontal = 14.dp, vertical = 12.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        ElchiIconView(icon, colors.fg, Modifier.padding(top = 1.dp), size = 18.dp)
        Text(text, style = Elchi.type.label.copy(fontWeight = FontWeight.Normal, lineHeight = 19.sp), color = colors.noteText)
    }
}

/**
 * "Haydovchi takliflari" with "{n} ta ochiq taklif" / "Ochiq taklif yo'q" / "Hozircha taklif yo'q", the sort chips
 * and the offer cards - or the small "Haydovchi javob berganda ..." card. Q43's note closes the board.
 */
@OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)
@Composable
private fun OffersSection(
    vm: ListingViewModel,
    s: ListingViewModel.State,
    b: OfferBoard.State,
    listing: ListingDTO,
    stats: OfferStats,
    now: Instant,
    ru: Boolean,
    scrollToOffers: Boolean,
) {
    if (listing.status == ListingStatus.DRAFT) return
    val c = Elchi.colors
    val threads = s.threadList
    val requester = remember { BringIntoViewRequester() }
    var scrolled by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(scrollToOffers, s.threads is Load.Ready) {
        if (scrollToOffers && !scrolled && s.threads is Load.Ready) {
            delay(150)
            // A rect taller than the screen: the header lands at the top, the offers under it.
            requester.bringIntoView(androidx.compose.ui.geometry.Rect(0f, 0f, 1f, 100_000f))
            scrolled = true
        }
    }
    val sub = when {
        stats.open > 0 -> t(R.string.client_listing_offersSubOpen, "count" to stats.open)
        threads.isNotEmpty() -> t(R.string.client_listing_offersSubNoneOpen)
        else -> t(R.string.client_listing_offersSubNone)
    }
    Row(Modifier.fillMaxWidth().bringIntoViewRequester(requester).padding(top = 4.dp), verticalAlignment = Alignment.Bottom) {
        Text(t(R.string.listingBids_title), Modifier.weight(1f), style = Elchi.type.section, color = c.text)
        if (s.threads is Load.Ready) Text(sub, style = Elchi.type.label.copy(fontWeight = FontWeight.Normal), color = c.muted)
    }
    when (val load = s.threads) {
        Load.Loading -> LoadingLine(t(R.string.common_loading))
        is Load.Failed -> LoadFailed(t(R.string.listingBids_title), load.error, vm::refresh)
        is Load.Ready -> if (load.value.isEmpty()) {
            OffersWaitCard()
        } else {
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf(
                    OfferSort.CHEAPEST to R.string.client_listingBids_sortCheapest,
                    OfferSort.FASTEST to R.string.client_listingBids_sortFastest,
                    OfferSort.RATING to R.string.client_listingBids_sortRating,
                ).forEach { (sort, label) -> Chip(t(label), s.sort == sort, { vm.setSort(sort) }, filled = true) }
            }
            val sorted = OrderRules.sortOffers(threads, s.sort, now)
            val badges = OrderRules.sortBadges(threads, s.sort, now)
            val handlers = remember(vm) { OfferHandlers(vm.board) }
            val listingDay = OrderRules.dayDot(listing.departureWindowStart)
            sorted.forEach { thread ->
                OfferCard(
                    thread, b, handlers, now, ru,
                    badge = badges[thread.id],
                    fresh = thread.id in s.freshOffers,
                    previousTotal = s.previousTotals[thread.id],
                    listingDay = listingDay,
                    route = offerRouteIfDifferent(thread, listing, ru),
                    paused = listing.status == ListingStatus.PAUSED,
                )
            }
            Note(t(R.string.listingBids_identityHidden), tone = Tone.BLUE)
        }
    }
}

/** An offer's own route, only when it is not the listing's ("Chilonzor → Registon" for a driver's other stop). */
@Composable
private fun offerRouteIfDifferent(thread: ProposalThreadDTO, listing: ListingDTO, ru: Boolean): String? {
    val v = thread.currentVersion ?: return null
    val offer = "${OrderRules.shortEnd(v.pickupStop, v.pickupPoint, ru)} → ${OrderRules.shortEnd(v.dropoffStop, v.dropoffPoint, ru)}"
    return offer.takeIf { it != routeTitle(listing, ru) }
}

/** After the bar's share made a link: the URL with "Havolani bekor qilish" (the design's `revokeLink` is unbound). */
@Composable
private fun ShareLinkRow(s: ListingViewModel.State, vm: ListingViewModel) {
    val c = Elchi.colors
    if (s.linkRevoked) Note(t(R.string.trackingShare_revoked), tone = Tone.OK)
    val link = s.link ?: return
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(c.card).padding(horizontal = 14.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(t(R.string.client_share_link), style = Elchi.type.caption, color = c.muted)
        Text(link.url, style = Elchi.type.label.copy(fontFamily = FontFamily.Monospace), color = c.text, maxLines = 2)
        OrderRules.dayDot(link.expiresAt)?.let { day ->
            val time = OrderRules.tashkent(link.expiresAt)?.let { "$day, %02d:%02d".format(it.hour, it.minute) } ?: day
            Text(t(R.string.trackingShare_validUntil, "time" to time), style = Elchi.type.caption, color = c.muted)
        }
        ElchiButton(t(R.string.client_share_revoke), vm::revokeShareLink, Modifier.align(Alignment.End).height(36.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM, enabled = !s.sharing, horizontalPadding = 14.dp)
    }
}

/**
 * Pause / resume as one compact row with its hint (designer to confirm, 2.9), the last command's refusal, and the
 * centred red "Buyurtmani bekor qilish" text button (2.10) - only what the status allows (`ownerListingActions`).
 */
@Composable
private fun androidx.compose.foundation.layout.ColumnScope.OwnerControls(vm: ListingViewModel, s: ListingViewModel.State, listing: ListingDTO, onCancel: () -> Unit) {
    val c = Elchi.colors
    val status = listing.status
    val canPause = OrderRules.canPause(status)
    val canResume = OrderRules.canResume(status)
    if (canPause || canResume) {
        Row(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(c.card).padding(start = 14.dp, end = 8.dp, top = 8.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(
                t(if (canPause) R.string.listingOwner_pauseHint else R.string.client_listingDetail_resumeHint),
                Modifier.weight(1f),
                style = Elchi.type.caption,
                color = c.muted,
            )
            ElchiButton(
                t(if (canPause) R.string.listingOwner_pause else R.string.listingOwner_resume),
                if (canPause) vm::pause else vm::resume,
                Modifier.height(40.dp),
                ButtonVariant.NEUTRAL,
                ButtonSize.MEDIUM,
                enabled = s.action == null,
                loading = s.action == OwnerAction.PAUSE || s.action == OwnerAction.RESUME,
                horizontalPadding = 14.dp,
            )
        }
    }
    s.actionError?.let { Note(errorText(it), tone = Tone.ERR) }
    if (OrderRules.canCancel(status)) {
        Text(
            t(R.string.listingDetail_cancel),
            Modifier
                .align(Alignment.CenterHorizontally)
                .heightIn(min = 44.dp)
                .clip(CircleShape)
                .clickable(enabled = s.action == null, role = Role.Button, onClick = onCancel)
                .padding(horizontal = 12.dp, vertical = 12.dp),
            style = Elchi.type.secondary.copy(fontWeight = FontWeight.Medium),
            color = c.tone(Tone.ERR).fg,
        )
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
                Text(title, style = Elchi.type.title.copy(fontSize = 20.sp, lineHeight = 24.sp), color = c.text)
                Text(text, style = Elchi.type.secondary, color = c.muted)
            }
            ElchiButton(confirm, onConfirm, Modifier.fillMaxWidth(), confirmVariant, loading = busy)
            ElchiButton(back, onDismiss, Modifier.fillMaxWidth(), ButtonVariant.NEUTRAL, enabled = !busy)
        }
    }
}

/** "Posilka rasmi": the decoded photo, a calm failure line, or progress. Shared by the booking and v1 screens. */
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

// -- listing-edit ------------------------------------------------------------------------------------------------

private enum class EditEdge { START, END }

private val WINDOW_INVALID = setOf(EditInvalid.WINDOW_INCOMPLETE, EditInvalid.WINDOW_ORDER, EditInvalid.WINDOW_PAST)

/**
 * `edit` "E'lonni tahrirlash": price (so'm), comment (300), seats (Taksi, Q145), the window. "Saqlash" is always
 * tappable: a tap with something invalid shows the red box at the top and the red field (DESIGN02 6.9). Moving the
 * window with open offers asks for "Tushundim, saqlash" (Q20).
 */
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
    val shown = plan?.invalid?.takeIf { s.editTried }
    val scroll = rememberScrollState()
    LaunchedEffect(s.editTried, shown) { if (shown != null) scroll.animateScrollTo(0) }
    StepScaffold(
        title = t(R.string.listingOwner_editTitle),
        onBack = onBack,
        scrollState = scroll,
        footer = {
            s.saveError?.let { Note(errorText(it), tone = Tone.ERR) }
            ElchiButton(
                t(if (warnMaterial) R.string.listingOwner_materialConfirm else R.string.common_save),
                vm::save,
                Modifier.fillMaxWidth(),
                enabled = plan != null,
                loading = s.saving,
            )
        },
    ) {
        if (listing == null || form == null) {
            LoadingLine(t(R.string.common_loading))
            return@StepScaffold
        }
        shown?.let { Note(tOrNull("listingOwner.invalid.${it.key}") ?: it.key, tone = Tone.ERR) }
        ElchiField(
            form.priceDigits,
            { text -> vm.editForm { it.copy(priceDigits = text.filter(Char::isDigit).trimStart('0').take(OfferBoard.MAX_DIGITS)) } },
            // A passenger request's price is per person ("Narx (so'm) / o'rin").
            label = t(R.string.listingOwner_priceLabel) + if (TaxiRules.isPassenger(listing.serviceType)) " " + t(R.string.listingEdit_perSeatSuffix).trim() else "",
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Next),
            visualTransformation = ThousandsTransformation,
            suffix = t(R.string.common_soum),
            error = if (shown == EditInvalid.PRICE) t(R.string.listingOwner_invalid_price) else null,
        )
        ElchiField(
            form.comment,
            { text -> vm.editForm { it.copy(comment = text.take(COMMENT_MAX)) } },
            label = t(R.string.listingOwner_commentLabel),
            singleLine = false,
            minHeight = 96.dp,
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
            hint = t(R.string.app_bookingCancel_commentHint),
        )
        if (TaxiRules.seatsEditable(listing)) {
            // Q145: the number of people, until a booking exists; a new count closes the open offers (Q20).
            val seatsError = shown?.takeIf { it == EditInvalid.SEATS || it == EditInvalid.SEATS_CHILDREN }
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
            val windowError = shown?.takeIf { it in WINDOW_INVALID }
            PickerField(t(R.string.listingOwner_windowStart), form.windowStart?.let(ParcelRules::display), placeholder, { picking = EditEdge.START }, error = windowError != null)
            PickerField(t(R.string.listingOwner_windowEnd), form.windowEnd?.let(ParcelRules::display), placeholder, { picking = EditEdge.END }, error = windowError != null)
        }
        // 4.6: kept - it is true (Q20) and tells what an edit does not do.
        Text(t(R.string.listingOwner_nonMaterialNote), style = Elchi.type.label.copy(fontWeight = FontWeight.Normal), color = Elchi.colors.muted)
        if (warnMaterial) {
            // Parcel: the design's sentence. Taksi keeps the longer one - it also covers the seat count (Q145).
            val text = if (TaxiRules.isPassenger(listing.serviceType)) {
                "${t(R.string.listingOwner_materialWarning)} ${t(R.string.listingOwner_openOffers, "count" to openOffers)}"
            } else {
                t(R.string.client_listing_editWindowWarn, "count" to openOffers)
            }
            Note(text, tone = Tone.WARN)
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

/** The design's comment limit (the server takes 1000). */
private const val COMMENT_MAX = 300
