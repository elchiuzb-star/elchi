package uz.elchi.app.feature.client

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.activity.compose.LocalActivity
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.TextUnitType
import androidx.compose.ui.unit.dp
import androidx.core.net.toUri
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.elchi.app.R
import uz.elchi.app.api.LegacyBid
import uz.elchi.app.api.LegacyOrderDetail
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.CardHeader
import uz.elchi.app.ui.components.CardRow
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiField
import uz.elchi.app.ui.components.EmptyListState
import uz.elchi.app.ui.components.ItemCard
import uz.elchi.app.ui.components.ListCard
import uz.elchi.app.ui.components.ListRow
import uz.elchi.app.ui.components.LoadingState
import uz.elchi.app.ui.components.NotFoundState
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.SelectField
import uz.elchi.app.ui.components.StarRating
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.map.ElchiMap
import uz.elchi.app.ui.map.GeoPoint
import uz.elchi.app.ui.map.MapFocus
import uz.elchi.app.ui.map.MapMarker
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import java.util.Locale

/*
 * Stage 06: the client's orders of the first (v1) marketplace, kept as an archive (Q4). Every screen opens with the
 * grey archive note; the actions are only those left in the order's life cycle - never create, edit or publish.
 */

@Composable
private fun ArchiveNote() = Note(t(R.string.client_legacy_archiveNote), tone = Tone.GRAY)

// -- client-order-detail (v1) ------------------------------------------------------------------------------------

/**
 * `client-order-detail` "Buyurtma tafsilotlari" (v1): route, status and price; addresses; the client's own phones
 * and comment; the photo; the driver (with the phone from `accepted` on - v1 has no chat); the map points; and the
 * actions the status allows. Read again on every return and by pulling down; 404 / 403 is "not found".
 */
@Composable
fun LegacyDetailScreen(
    vm: LegacyOrderViewModel,
    languageTag: String,
    onBack: () -> Unit,
    onBids: () -> Unit,
    onRate: () -> Unit,
    onDispute: () -> Unit,
    onCancelled: () -> Unit,
) {
    val s by vm.state.collectAsStateWithLifecycle()
    var sheet by rememberSaveable { mutableStateOf<LegacySheet?>(null) }
    LifecycleResumeEffect(vm) {
        vm.refresh()
        onPauseOrDispose { }
    }
    LaunchedEffect(s.failures) { if (s.failures > 0) sheet = null }
    // Only the outcomes of this screen's own sheets; the sub-screens consume theirs.
    LaunchedEffect(s.done) {
        when (s.done) {
            LegacyDone.CONFIRMED -> {
                vm.consumeDone()
                sheet = null
                onRate()
            }
            LegacyDone.CANCELLED -> {
                vm.consumeDone()
                sheet = null
                onCancelled()
            }
            else -> Unit
        }
    }
    StepScaffold(
        title = t(R.string.orders_detailTitle),
        onBack = onBack,
        onRefresh = vm::refresh,
        refreshing = s.refreshing && s.order is Load.Ready,
    ) {
        ArchiveNote()
        when {
            s.notFound -> NotFoundState(onBack)
            else -> when (val load = s.order) {
                Load.Loading -> LoadingState(count = 3)
                is Load.Failed -> LoadFailed(t(R.string.orders_detailTitle), load.error, vm::refresh)
                is Load.Ready -> LegacyBody(s, load.value, languageTag, onBids, onRate, onDispute, onSheet = { sheet = it })
            }
        }
    }
    val order = s.value
    when (sheet) {
        LegacySheet.CONFIRM -> CancelSheet(
            title = t(R.string.confirmDialog_confirmDelivery_title),
            text = t(R.string.confirmDialog_confirmDelivery_text),
            confirm = t(R.string.client_legacy_confirmDeliveryYes),
            back = t(R.string.confirmDialog_back),
            busy = s.busy,
            onConfirm = vm::confirmDelivery,
            onDismiss = { if (!s.busy) sheet = null },
            confirmVariant = ButtonVariant.PRIMARY,
        )
        LegacySheet.CANCEL -> CancelSheet(
            title = t(R.string.confirmDialog_cancelOrder_title),
            text = tOrNull(LegacyRules.cancelTextKey(order?.status.orEmpty())) ?: t(R.string.confirmDialog_cancelOrder_text),
            confirm = t(R.string.common_cancel),
            back = t(R.string.confirmDialog_back),
            busy = s.busy,
            onConfirm = vm::cancel,
            onDismiss = { if (!s.busy) sheet = null },
        )
        LegacySheet.MAP -> if (order != null) LegacyMapSheet(order, onDismiss = { sheet = null }) else sheet = null
        null -> Unit
    }
}

private enum class LegacySheet { CONFIRM, CANCEL, MAP }

@Composable
private fun LegacyBody(
    s: LegacyOrderViewModel.State,
    order: LegacyOrderDetail,
    languageTag: String,
    onBids: () -> Unit,
    onRate: () -> Unit,
    onDispute: () -> Unit,
    onSheet: (LegacySheet) -> Unit,
) {
    val status = order.status
    val actions = LegacyRules.actions(status, s.ratedHere)
    ItemCard(
        title = LegacyRules.route(order),
        badge = (tOrNull(OrderRules.legacyStatusKey(status)) ?: status) to OrderRules.statusTone(status),
        sub = order.orderNumber,
        meta = LegacyRules.displayTime(order.createdAt),
        right = LegacyRules.priceMinor(order)?.let { soum(it) },
    )
    ElchiCard {
        CardRow(t(R.string.routeSummary_pickup), order.pickupAddress?.takeIf { it.isNotBlank() } ?: "—", first = true, detail = order.fromDistrict?.nameUz)
        CardRow(t(R.string.routeSummary_dropoff), order.dropoffAddress?.takeIf { it.isNotBlank() } ?: "—", detail = order.toDistrict?.nameUz)
    }
    ElchiCard {
        CardRow(t(R.string.orderForm_review_sender), order.senderPhone?.let(::displayPhone) ?: "—", first = true)
        CardRow(t(R.string.orderForm_review_receiver), order.receiverPhone?.let(::displayPhone) ?: "—")
        CardRow(t(R.string.listingOwner_commentLabel), order.comment?.takeIf { it.isNotBlank() } ?: "—", muted = order.comment.isNullOrBlank())
    }
    if (!order.cargoPhotoUrl.isNullOrBlank()) ParcelPhotoBlock(s.photo, s.photoFailed)
    order.assignedDriver?.let { LegacyDriverCard(order, languageTag) }
    if (LegacyRules.hasAnyPoint(order)) {
        ListCard {
            val pickup = t(if (LegacyRules.hasPoint(order.pickupLat, order.pickupLng)) R.string.orders_pickupMarked else R.string.orders_pickupNotMarked)
            val dropoff = t(if (LegacyRules.hasPoint(order.dropoffLat, order.dropoffLng)) R.string.orders_dropoffMarked else R.string.orders_dropoffNotMarked)
            ListRow(t(R.string.orders_mapPoints), icon = ElchiIcon.PIN, description = "$pickup · $dropoff", first = true, onClick = { onSheet(LegacySheet.MAP) })
        }
    }
    if (actions.viewBids) {
        val count = order.bidsCount ?: 0
        ElchiButton(
            if (count > 0) t(R.string.client_listingDetail_viewOffers, "count" to count) else t(R.string.orders_viewBids),
            onBids,
            Modifier.fillMaxWidth(),
            ButtonVariant.SOFT,
        )
    }
    if (actions.confirmDelivery) {
        ElchiButton(t(R.string.orders_confirmDelivered), { onSheet(LegacySheet.CONFIRM) }, Modifier.fillMaxWidth(), enabled = !s.busy)
    }
    if (actions.rate) ElchiButton(t(R.string.rating_rateDriver), onRate, Modifier.fillMaxWidth())
    if (actions.cancel && actions.report) {
        // The design's pair: "Muammo haqida xabar" beside "Bekor qilish".
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ElchiButton(t(R.string.orders_reportProblem), onDispute, Modifier.weight(1f).height(52.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM, horizontalPadding = 12.dp, maxLines = 2)
            ElchiButton(t(R.string.common_cancel), { onSheet(LegacySheet.CANCEL) }, Modifier.weight(1f).height(52.dp), ButtonVariant.DANGER_SOFT, ButtonSize.MEDIUM, enabled = !s.busy, horizontalPadding = 12.dp, maxLines = 2)
        }
    } else {
        if (actions.report) ElchiButton(t(R.string.orders_reportProblem), onDispute, Modifier.fillMaxWidth(), ButtonVariant.NEUTRAL)
        if (actions.cancel) ElchiButton(t(R.string.orders_cancel), { onSheet(LegacySheet.CANCEL) }, Modifier.fillMaxWidth(), ButtonVariant.DANGER_SOFT, enabled = !s.busy)
    }
}

/** The driver v1 put on the order: name, car and plate, rating (never an invented one); the phone from `accepted` on. */
@Composable
private fun LegacyDriverCard(order: LegacyOrderDetail, languageTag: String) {
    val driver = order.assignedDriver ?: return
    val context = LocalContext.current
    val activity = LocalActivity.current
    val phone = LegacyRules.driverPhone(order.status, driver)
    ElchiCard {
        CardHeader(t(R.string.dispute_side_driver))
        CardRow(
            t(R.string.safety_driverTitle),
            driver.fullName?.takeIf { it.isNotBlank() } ?: t(R.string.dispute_side_driver),
            first = true,
            detail = LegacyRules.ratingText(driver.rating, Locale.forLanguageTag(languageTag)) ?: t(R.string.listingBids_noRatingsYet),
        )
        vehicleLine(driver.carModel, driver.plateNumber)?.let { CardRow(t(R.string.tripDetail_vehicle), it) }
        if (phone != null) {
            CardRow(
                t(R.string.driverBooking_phone),
                displayPhone(phone),
                trailing = t(R.string.client_legacy_call),
                onTrailing = {
                    val dial = Intent(Intent.ACTION_DIAL, BookingRules.dialUri(phone).toUri())
                    activity?.startActivity(dial) ?: context.startActivity(dial.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                },
            )
        }
    }
}

private fun vehicleLine(car: String?, plate: String?): String? =
    listOfNotNull(car?.takeIf { it.isNotBlank() }, plate?.takeIf { it.isNotBlank() }).joinToString(" · ").ifEmpty { null }

// -- map-sheet ---------------------------------------------------------------------------------------------------

/**
 * "Xarita nuqtalari": a small still map with the pickup ring and the drop-off pin (fitted; one point is centred),
 * no route line (v1 has none), and the old app's Yandex Maps links. Strings are resolved here - the sheet is its own
 * window.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LegacyMapSheet(order: LegacyOrderDetail, onDismiss: () -> Unit) {
    val c = Elchi.colors
    val context = LocalContext.current
    val activity = LocalActivity.current
    val pickup = order.pickupLat?.takeIf { LegacyRules.hasPoint(order.pickupLat, order.pickupLng) }?.let { GeoPoint(it, order.pickupLng!!) }
    val dropoff = order.dropoffLat?.takeIf { LegacyRules.hasPoint(order.dropoffLat, order.dropoffLng) }?.let { GeoPoint(it, order.dropoffLng!!) }
    val markers = listOfNotNull(pickup?.let { MapMarker(it, MapMarker.Kind.ORIGIN) }, dropoff?.let { MapMarker(it, MapMarker.Kind.DESTINATION) })
    val focus = remember(markers) {
        if (markers.size == 1) MapFocus.At(markers.single().point, SINGLE_POINT_ZOOM) else MapFocus.Fit(markers.map { it.point })
    }
    val title = t(R.string.mapSheet_title)
    val openPickup = t(R.string.mapSheet_openPickup)
    val openRoute = t(R.string.mapSheet_open)
    val unavailable = t(R.string.client_map_unavailable)
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true), containerColor = c.card) {
        Column(Modifier.padding(horizontal = 16.dp).padding(bottom = 16.dp).navigationBarsPadding(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(title, style = Elchi.type.title.copy(fontSize = TextUnit(20f, TextUnitType.Sp), lineHeight = TextUnit(24f, TextUnitType.Sp)), color = c.text)
            Box(Modifier.fillMaxWidth().height(180.dp).clip(RoundedCornerShape(20.dp))) {
                ElchiMap(
                    Modifier.fillMaxSize(),
                    markers = markers,
                    focus = focus,
                    padding = PaddingValues(24.dp),
                    interactive = false,
                    placeholderTitle = unavailable,
                )
            }
            if (pickup != null) {
                ElchiButton(openPickup, { openExternal(context, activity, LegacyRules.yandexPointUrl(pickup.lat, pickup.lng)) }, Modifier.fillMaxWidth(), ButtonVariant.SOFT)
            }
            if (dropoff != null) {
                ElchiButton(openRoute, { openExternal(context, activity, LegacyRules.yandexRouteUrl(dropoff.lat, dropoff.lng)) }, Modifier.fillMaxWidth(), ButtonVariant.NEUTRAL)
            }
        }
    }
}

/** The Yandex Maps app when installed (it handles yandex.uz links), else the browser. */
private fun openExternal(context: Context, activity: android.app.Activity?, url: String) {
    Log.i(TAG, "open $url")
    val view = Intent(Intent.ACTION_VIEW, url.toUri())
    try {
        activity?.startActivity(view) ?: context.startActivity(view.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    } catch (e: ActivityNotFoundException) {
        Log.w(TAG, "no app for $url", e)
    }
}

private const val TAG = "ElchiLegacy"
private const val SINGLE_POINT_ZOOM = 14f

// -- client-bids (v1) --------------------------------------------------------------------------------------------

/**
 * `client-bids` "Haydovchi takliflari" (v1): the active bids, cheapest first - name, car, plate, rating, price and
 * "Tanlash" behind a confirmation. Closed once the order left `published` / `bidding`.
 */
@Composable
fun LegacyBidsScreen(vm: LegacyOrderViewModel, languageTag: String, onBack: () -> Unit, onSelected: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { vm.loadBids() }
    LaunchedEffect(s.done) {
        if (s.done == LegacyDone.SELECTED) {
            vm.consumeDone()
            onSelected()
        }
    }
    val order = s.value
    StepScaffold(
        title = t(R.string.listingBids_title),
        onBack = onBack,
        onRefresh = vm::loadBids,
        refreshing = s.bidsRefreshing && s.bids is Load.Ready,
    ) {
        ArchiveNote()
        when {
            s.notFound -> NotFoundState(onBack)
            order != null && !LegacyRules.bidsOpen(order.status) -> Note(t(R.string.client_legacy_bidsClosed), tone = Tone.GRAY)
            else -> when (val load = s.bids) {
                Load.Loading -> LoadingState(count = 2)
                is Load.Failed -> LoadFailed(t(R.string.listingBids_title), load.error, vm::loadBids)
                is Load.Ready -> if (load.value.isEmpty()) {
                    if (order?.status == "published") {
                        EmptyListState(title = t(R.string.orders_noBids), description = t(R.string.orders_noBidsHint))
                    } else {
                        EmptyListState(title = t(R.string.listingBids_emptyTitle), description = t(R.string.listingBids_emptySubtitle))
                    }
                } else {
                    load.value.forEach { bid -> LegacyBidItem(bid, languageTag, enabled = !s.busy) { vm.askSelect(bid) } }
                }
            }
        }
    }
    if (s.selecting != null) {
        CancelSheet(
            title = t(R.string.confirmDialog_selectDriver_title),
            text = t(R.string.confirmDialog_selectDriver_text),
            confirm = t(R.string.confirmDialog_selectDriver_confirm),
            back = t(R.string.confirmDialog_back),
            busy = s.busy,
            onConfirm = vm::select,
            onDismiss = vm::dismissSelect,
            confirmVariant = ButtonVariant.PRIMARY,
        )
    }
}

@Composable
private fun LegacyBidItem(bid: LegacyBid, languageTag: String, enabled: Boolean, onSelect: () -> Unit) {
    val driver = bid.driver
    val rating = LegacyRules.ratingText(driver?.rating, Locale.forLanguageTag(languageTag)) ?: t(R.string.listingBids_noRatingsYet)
    ItemCard(
        title = driver?.fullName?.takeIf { it.isNotBlank() } ?: t(R.string.dispute_side_driver),
        sub = listOfNotNull(vehicleLine(driver?.carModel, driver?.plateNumber), rating).joinToString(" · "),
        right = LegacyRules.bidPriceMinor(bid.price)?.let { soum(it) },
        rightColor = Elchi.colors.accentText,
        footer = {
            ElchiButton(t(R.string.confirmDialog_selectDriver_confirm), onSelect, Modifier.fillMaxWidth().height(46.dp), size = ButtonSize.MEDIUM, enabled = enabled)
        },
    )
}

// -- client-rating (v1) ------------------------------------------------------------------------------------------

/** `client-rating` "Haydovchini baholang" (v1): 1-5 stars and an optional comment; "Keyinroq" leaves it for later. */
@Composable
fun LegacyRatingScreen(vm: LegacyOrderViewModel, onBack: () -> Unit, onDone: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    LaunchedEffect(s.done) {
        if (s.done == LegacyDone.RATED) {
            vm.consumeDone()
            onDone()
        }
    }
    StepScaffold(
        title = t(R.string.rating_titleDriver),
        onBack = onBack,
        footer = {
            ElchiButton(t(R.string.legacyOrder_ratingSubmit), vm::rate, Modifier.fillMaxWidth(), enabled = s.stars in 1..5, loading = s.busy)
            ElchiButton(t(R.string.legacyOrder_later), onBack, Modifier.fillMaxWidth().height(44.dp), ButtonVariant.GHOST, ButtonSize.MEDIUM, enabled = !s.busy)
        },
    ) {
        ArchiveNote()
        s.value?.assignedDriver?.fullName?.takeIf { it.isNotBlank() }?.let {
            Text(it, Modifier.fillMaxWidth().padding(top = 8.dp), style = Elchi.type.title.copy(fontSize = TextUnit(18f, TextUnitType.Sp)), color = Elchi.colors.text, textAlign = TextAlign.Center)
        }
        Text(t(R.string.legacyOrder_ratingHint), Modifier.fillMaxWidth(), style = Elchi.type.secondary, color = Elchi.colors.muted, textAlign = TextAlign.Center)
        val labels = (1..5).associateWith { t(R.string.legacyOrder_stars, "value" to it) }
        StarRating(s.stars, vm::setStars, label = { labels.getValue(it) })
        ElchiField(
            s.ratingComment,
            vm::setRatingComment,
            label = t(R.string.legacyOrder_ratingComment),
            singleLine = false,
            minHeight = 96.dp,
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
            hint = t(R.string.app_bookingCancel_commentHint),
        )
    }
}

// -- client-dispute (v1) -----------------------------------------------------------------------------------------

/**
 * `client-dispute` "Muammo haqida xabar berish" (v1): one of the server's reason codes (labels from the dictionary,
 * the code on the wire) and optional details; the order becomes `disputed`.
 */
@Composable
fun LegacyDisputeScreen(vm: LegacyOrderViewModel, onBack: () -> Unit, onDone: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    LaunchedEffect(s.done) {
        if (s.done == LegacyDone.DISPUTED) {
            vm.consumeDone()
            onDone()
        }
    }
    val reasons = LegacyRules.DISPUTE_REASONS.map { it to (tOrNull(LegacyRules.disputeReasonKey(it)) ?: it) }
    StepScaffold(
        title = t(R.string.legacyOrder_dispute_title),
        onBack = onBack,
        footer = { ElchiButton(t(R.string.common_send), vm::openDispute, Modifier.fillMaxWidth(), loading = s.busy) },
    ) {
        ArchiveNote()
        SelectField(t(R.string.common_reason), s.disputeReason, reasons, vm::setDisputeReason, placeholder = t(R.string.common_reason))
        ElchiField(
            s.disputeDetails,
            vm::setDisputeDetails,
            label = t(R.string.client_legacy_dispute_details),
            singleLine = false,
            minHeight = 110.dp,
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
            hint = t(R.string.blockReport_detailsHint),
        )
    }
}
