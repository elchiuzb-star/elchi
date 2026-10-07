package uz.elchi.app.feature.driver

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import java.util.Locale
import kotlinx.coroutines.delay
import uz.elchi.app.R
import uz.elchi.app.api.BookingClientDTO
import uz.elchi.app.api.DriverBookingDTO
import uz.elchi.app.api.generated.ReputationDTO
import uz.elchi.app.feature.client.BookingCancelSheet
import uz.elchi.app.feature.client.BookingNotices
import uz.elchi.app.feature.client.BookingRules
import uz.elchi.app.feature.client.BookingViewModel
import uz.elchi.app.feature.client.ChatSeenCounts
import uz.elchi.app.feature.client.FlowToast
import uz.elchi.app.feature.client.FlowToastHost
import uz.elchi.app.feature.client.Load
import uz.elchi.app.feature.client.LoadFailed
import uz.elchi.app.feature.client.LoadingLine
import uz.elchi.app.feature.client.OrderRules
import uz.elchi.app.feature.client.ParcelRules
import uz.elchi.app.feature.client.ReputationLine
import uz.elchi.app.feature.client.SafetyRowCard
import uz.elchi.app.feature.client.StepScaffold
import uz.elchi.app.feature.client.TaxiRules
import uz.elchi.app.feature.client.rememberNow
import uz.elchi.app.feature.client.seatsPrice
import uz.elchi.app.feature.client.soum
import uz.elchi.app.gps.DriverTracker
import uz.elchi.app.gps.DriverTrackingBar
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.CardHeader
import uz.elchi.app.ui.components.CardRow
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.EmptyState
import uz.elchi.app.ui.components.ItemCard
import uz.elchi.app.ui.components.LoadingState
import uz.elchi.app.ui.components.MoneyBlock
import uz.elchi.app.ui.components.MoneyRow
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.Segmented
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone

private const val NOTICE_SHOWN_MS = 4_000L

// -- driver-orders ------------------------------------------------------------------------------------------------

/** The Orders tab body (the gate is the caller's): "Takliflarim" on top, then the bookings, live first. */
@Composable
internal fun ColumnScope.DriverOrdersBody(
    vm: DriverBookingsViewModel,
    proposals: ProposalsViewModel,
    onProposals: () -> Unit,
    onBooking: (String) -> Unit,
    /** Before approval there are no offers to list (design 06 §0.3): the bookings only. */
    showProposals: Boolean = true,
) {
    val s by vm.state.collectAsStateWithLifecycle()
    var activeFilter by rememberSaveable { mutableStateOf(true) }
    // Design 08 0.2: the GPS bar on the Orders root too - for the trip a live booking runs on, or whatever this
    // phone is publishing (nothing is drawn while the tracker is idle and no booking's trip runs).
    vm.tracker?.let { tracker ->
        val trip = s.list.firstNotNullOfOrNull { DriverBookingRules.gpsTripId(it.serviceStatus, it.tripId) }
        DriverTrackingBar(tracker, trip, inset = 0.dp)
    }
    if (showProposals) ProposalsEntry(proposals, onProposals)
    when (val load = s.bookings) {
        Load.Loading -> LoadingState(count = 3)
        is Load.Failed -> LoadFailed(t(R.string.driverOrders_title), load.error, vm::refresh)
        is Load.Ready -> if (load.value.isEmpty()) {
            EmptyState(DriverTab.ORDERS.icon, t(R.string.driverOrders_empty), Modifier.padding(top = 12.dp), description = t(R.string.driverOrders_emptyHint))
        } else {
            val (live, done) = load.value.partition { DriverBookingRules.isActive(it.serviceStatus) }
            Segmented(
                listOf(true to "${t(R.string.driver_orders_filterActive)} · ${live.size}", false to "${t(R.string.driver_orders_filterHistory)} · ${done.size}"),
                selected = activeFilter,
                onSelect = { activeFilter = it },
            )
            val shown = if (activeFilter) live else done
            if (shown.isEmpty()) {
                Text(t(R.string.driverOrders_empty), Modifier.padding(vertical = 8.dp), style = Elchi.type.label, color = Elchi.colors.muted)
            }
            shown.forEach { DriverBookingRow(it) { onBooking(it.id) } }
            if (s.cursor != null) {
                ElchiButton(t(R.string.blockReport_loadMore), vm::loadMore, Modifier.fillMaxWidth().height(44.dp), ButtonVariant.GHOST, ButtonSize.MEDIUM, loading = s.loadingMore)
            }
        }
    }
}

@Composable
private fun DriverBookingRow(booking: DriverBookingDTO, onClick: () -> Unit) {
    val ru = appRu()
    val status = booking.serviceStatus
    val day = OrderRules.dayMonth(booking.pickup.windowStart ?: booking.createdAt, languageTag())
    // Design 08 1.4: "Yo'lovchi · 2 kishi · 27 sen" / "Pochta · 27 sen" (the client's name is on the detail).
    val service = if (TaxiRules.isPassenger(booking.serviceType)) {
        listOf(t(R.string.client_taxi_passenger), t(R.string.orderForm_review_peopleCount, "count" to booking.quantity))
    } else {
        listOf(t(R.string.driverFeed_modeParcel))
    }
    ItemCard(
        title = "${OrderRules.shortEnd(booking.pickup.point, ru)} → ${OrderRules.shortEnd(booking.dropoff.point, ru)}",
        modifier = if (DriverBookingRules.dimmed(status)) Modifier.alpha(0.75f) else Modifier,
        icon = DriverBookingRules.rowIcon(booking.serviceType),
        badge = (tOrNull(DriverBookingRules.badgeKey(booking.serviceType, status, short = true, review = booking.noShowReview)) ?: status) to
            DriverBookingRules.badgeTone(booking.serviceType, status, booking.noShowReview),
        meta = (service + listOfNotNull(day)).joinToString(" · "),
        // Taksi: "2 × 150 000 so'm" (the per-seat basis); Pochta or a discounted ride: the total (design 08 1.5).
        right = if (DriverBookingRules.seatsPriced(booking)) seatsPrice(booking.quantity, booking.unitPriceMinor) else soum(booking.totalMinor),
        onClick = onClick,
    )
}

// -- driver-order-detail ------------------------------------------------------------------------------------------

/** Where the driver's booking screen leads. */
data class DriverBookingNav(
    val onChat: () -> Unit,
    val onTracking: () -> Unit,
    val onAmend: () -> Unit,
    val onRate: () -> Unit,
    val onSupport: () -> Unit,
    val onSafety: () -> Unit,
    /** The booking's trip (Taksi: "start boarding first" after TRIP_NOT_STARTED). */
    val onTrip: (String) -> Unit = {},
    /** The booking chat's `message_count` (the bar's unread badge, design 08 2.8); null when it cannot be read. */
    val chatCount: suspend () -> Long? = { null },
)

/**
 * `driver-order-detail` (design 08 "Buyurtma tafsilotlari"): the client's design-04 layout for the driver - the map
 * hero (its pill from this phone's tracker), the sheet with the badge, ladder and facts, the notices (cancelled, on
 * the way, arrived, GPS off), what the driver can do in this status ("Keldim", the passenger block, the amendment and
 * its pending / accepted line, support - Q146 the main help -, cancel, rate), the client's reputation, the folded
 * safety row, and the fixed contact bar (call once the phone opened - Q44/Q142 - and chat with the unread count).
 * The GPS bar sits on top while the trip runs.
 */
@Composable
fun DriverBookingDetailScreen(vm: BookingViewModel, tracker: DriverTracker, onBack: () -> Unit, nav: DriverBookingNav) {
    val s by vm.state.collectAsStateWithLifecycle()
    var confirmCancel by rememberSaveable { mutableStateOf(false) }
    var chatTick by remember { mutableIntStateOf(0) }
    var chatCount by remember { mutableStateOf<Long?>(null) }
    val toast = remember { FlowToast() }
    LifecycleResumeEffect(vm) {
        vm.refresh()
        vm.loadAmendments()
        chatTick++
        onPauseOrDispose { }
    }
    LaunchedEffect(chatTick) { if (chatTick > 0) nav.chatCount()?.let { chatCount = it } }
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
    val booking = s.value
    val view = s.driverView
    val gpsTrip = booking?.let { DriverBookingRules.gpsTripId(it.serviceStatus, it.tripId) }
    val unread = booking?.let { BookingRules.unreadCount(chatCount, ChatSeenCounts.seen(it.id)) } ?: 0
    Box(Modifier.fillMaxSize()) {
        StepScaffold(
            title = t(R.string.driverBooking_title),
            onBack = onBack,
            banner = {
                BookingNotices(s)
                if (gpsTrip != null) DriverTrackingBar(tracker, gpsTrip)
            },
            onRefresh = {
                vm.refresh()
                vm.loadAmendments()
                chatTick++
            },
            refreshing = s.refreshing && s.booking is Load.Ready,
            footerOnPage = true,
            footer = view?.let { v -> { ClientContactBar(v, unread, nav.onChat, toast::show) } },
        ) {
            when (val load = s.booking) {
                Load.Loading -> LoadingLine(t(R.string.common_loading))
                is Load.Failed -> LoadFailed(t(R.string.driverBooking_title), load.error, vm::refresh)
                is Load.Ready -> if (view != null) {
                    DriverBookingBody(vm, s, load.value, view, tracker, nav) {
                        vm.openCancel()
                        confirmCancel = true
                    }
                }
            }
        }
        FlowToastHost(toast, Modifier.align(Alignment.BottomCenter).navigationBarsPadding().padding(start = 16.dp, end = 16.dp, bottom = 96.dp))
    }
    if (confirmCancel && booking != null) {
        BookingCancelSheet(vm, s, booking, appRu(), onDismiss = { if (!s.cancelling) confirmCancel = false })
    }
}

@Composable
private fun DriverBookingBody(
    vm: BookingViewModel,
    s: BookingViewModel.State,
    booking: BookingClientDTO,
    view: DriverBookingDTO,
    tracker: DriverTracker,
    nav: DriverBookingNav,
    onCancel: () -> Unit,
) {
    val now by rememberNow()
    val snapshot by tracker.state.collectAsStateWithLifecycle()
    val ru = appRu()
    val tag = languageTag()
    val status = view.serviceStatus
    val actions = DriverBookingRules.actions(status, s.arrivedAt, view.updatedAt, now, view.noShowReview)
    val passenger = TaxiRules.isPassenger(view.serviceType)
    DriverBookingHero(booking, DriverBookingRules.heroChip(status, view.tripId, snapshot), nav.onTracking)
    DriverBookingSheet(booking, view, s, ru, tag)
    CancelledNotice(view)
    if (actions.transitNote) Note(t(R.string.driver_booking_inTransitNote), tone = Tone.BLUE)
    if (DriverBookingRules.arrivedNote(view.serviceType, status)) Note(t(R.string.driver_v3bkg_arrivedNote), tone = Tone.OK)
    if (DriverBookingRules.gpsOffWarn(status, view.tripId, snapshot)) Note(t(R.string.driver_v3bkg_gpsOffWarn), tone = Tone.WARN)
    view.promo?.let { promo ->
        MoneyBlock(
            listOf(
                MoneyRow(t(R.string.promo_line_agreedPrice), soum(promo.fareMinor)),
                MoneyRow(t(R.string.promo_line_discountCovered), soum(promo.passengerDiscountCoveredMinor)),
                MoneyRow(t(R.string.promo_line_cashFromClient), soum(promo.cashToCollectMinor), strong = true),
                MoneyRow(t(R.string.promo_line_creditUsed), soum(promo.driverCreditMinor)),
                MoneyRow(t(R.string.promo_line_chargedFromBalance), soum(promo.commissionChargedMinor)),
                MoneyRow(t(R.string.promo_line_youKeep), soum(promo.driverKeepsMinor), strong = true),
            ),
        )
    }
    // Q7 / TAXI-SPEC: "Keldim" stays - the server refuses a no-show without a recorded arrival (design 08 3.1).
    if (actions.arrive) {
        s.arriveError?.let { Note(errorText(it), tone = Tone.ERR) }
        ElchiButton(t(R.string.driverBooking_action_arrive), vm::arrive, Modifier.fillMaxWidth(), loading = s.arriving)
    } else if (s.arrivedAt != null && status in BookingViewModel.ARRIVE_STATUSES) {
        Note(t(R.string.driver_booking_arrivedSent), tone = Tone.OK)
    }
    if (passenger) PassengerActions(vm, s, view, now, nav)
    val amend = DriverBookingRules.amendNotice(s.amendmentList, status, now)
    if (actions.amend && amend !is DriverAmendNotice.Pending) {
        ElchiButton(t(R.string.driverBooking_amend), nav.onAmend, Modifier.fillMaxWidth().height(48.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM)
    }
    amend?.let { AmendNotice(it, view) }
    // Q146: the operator chat is the booking page's main help; the safety report sits apart, folded below.
    ElchiButton(t(R.string.support_complain), nav.onSupport, Modifier.fillMaxWidth().height(48.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM, icon = ElchiIcon.HEAD)
    if (actions.cancel) ElchiButton(t(R.string.bookingCancel_button), onCancel, Modifier.fillMaxWidth().height(48.dp), ButtonVariant.DANGER_SOFT, ButtonSize.MEDIUM)
    if (actions.rate || s.rated || s.ratingRefusal != null) RateEntry(s, nav.onRate)
    ClientReputation(view, s.reputation, s.reputationFailed)
    SafetyRowCard(nav.onSafety)
}

/** "Bekor qilindi: Siz · 27.09, 10:02 · Safar rejasi o'zgardi" as a notice under the sheet (design 08 8.3). */
@Composable
private fun CancelledNotice(view: DriverBookingDTO) {
    val c = view.cancelled?.takeIf { view.serviceStatus == "cancelled" } ?: return
    val parts = listOfNotNull(
        // The driver reads "Siz" for its own cancel, "Mijoz" for the client's.
        when (c.bySide) {
            "driver" -> t(R.string.client_bookingDetail_bySideClient)
            "client" -> t(R.string.driver_booking_clientTitle)
            else -> BookingRules.bySideKey(c.bySide)?.let { tOrNull(it) }
        },
        OrderRules.tashkent(c.at)?.let { ParcelRules.displayShort(it) },
        BookingRules.cancelReasonKey(c.reasonCode)?.let { tOrNull(it) },
    )
    Note(listOf(t(R.string.bookingCancel_cancelledBy), parts.joinToString(" · ")).filter { it.isNotEmpty() }.joinToString(": "), tone = Tone.ERR)
}

/**
 * Design 08 7.4: "Yangi narx taklifi yuborildi: X — mijoz javobi kutilmoqda." while the driver's proposal is open,
 * "Mijoz yangi narxni qabul qildi: X" once accepted. The amendment carries no reason (BLOCKED): it is said only for a
 * proposal sent from this phone, otherwise that part is cut.
 */
@Composable
private fun AmendNotice(notice: DriverAmendNotice, view: DriverBookingDTO) {
    val amendment = when (notice) {
        is DriverAmendNotice.Pending -> notice.amendment
        is DriverAmendNotice.Accepted -> notice.amendment
    }
    val price = if (TaxiRules.isPassenger(view.serviceType)) seatsPrice(amendment.newQuantity, amendment.newUnitPriceMinor) else soum(amendment.newTotalMinor)
    when (notice) {
        is DriverAmendNotice.Pending -> {
            // The reason only when this phone sent the proposal (the server does not return it).
            val reason = DriverAmendReasons.sent(view.id)
            val text = t(R.string.driver_v3bkg_amendPending, "price" to price, "reason" to (reason ?: REASON_MARKER))
            Note(if (reason != null) text else DriverBookingRules.dropReason(text, REASON_MARKER), tone = Tone.BLUE)
        }
        is DriverAmendNotice.Accepted -> Note(t(R.string.driver_v3bkg_amendAccepted, "price" to price), tone = Tone.OK)
    }
}

private const val REASON_MARKER = "\u2063"

@Composable
private fun RateEntry(s: BookingViewModel.State, onRate: () -> Unit) {
    val refusal = s.ratingRefusal
    when {
        // Design 08 12.3: "Baho berildi: ★★★★ (4 / 5)" right after sending; the plain sentence after a reload.
        s.rated && s.ratedStars in 1..5 && refusal == null -> Note(t(R.string.client_booking_ratedStars, "stars" to BookingRules.starsText(s.ratedStars)), tone = Tone.OK)
        s.rated -> Note(listOfNotNull(t(R.string.client_bookingDetail_rated), refusal?.let { errorText(it) }).joinToString(" "), tone = Tone.OK)
        refusal != null -> Note(errorText(refusal), tone = Tone.GRAY)
        else -> {
            ElchiButton(t(R.string.rating_rateClient), onRate, Modifier.fillMaxWidth())
            Text(t(R.string.driver_booking_rateNote), style = Elchi.type.caption, color = Elchi.colors.muted)
        }
    }
}

/** "Mijoz: Aziza · Yangi" / "Hali baholanmagan · Bajarilgan bronlar: 2 ta" - a real average or nothing invented (§9). */
@Composable
private fun ClientReputation(view: DriverBookingDTO, reputation: ReputationDTO?, failed: Boolean) {
    val name = view.client?.displayName?.takeIf { it.isNotBlank() } ?: return
    ElchiCard {
        CardHeader(t(R.string.reputation_title))
        val line = BookingRules.reputation(reputation, Locale.forLanguageTag(languageTag()))
        val value = when {
            reputation == null && failed -> "—"
            reputation == null -> t(R.string.common_loading)
            line is ReputationLine.Rated -> t(R.string.client_bookingDetail_reputation, "rating" to line.average, "count" to line.count, "bookings" to line.bookings)
            else -> t(R.string.reputation_new)
        }
        val detail = reputation?.takeIf { line is ReputationLine.Unrated }?.let {
            "${t(R.string.reputation_notRated)} · ${t(R.string.reputation_completedBookings)}: ${t(R.string.reputation_count, "count" to it.completedBookings)}"
        }
        CardRow("${t(R.string.driver_booking_clientTitle)}: $name", value, first = true, detail = detail)
    }
}
