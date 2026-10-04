package uz.elchi.app.feature.driver

import android.content.Intent
import androidx.core.net.toUri
import androidx.activity.compose.LocalActivity
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.delay
import uz.elchi.app.R
import uz.elchi.app.api.BookingClientDTO
import uz.elchi.app.api.DriverBookingDTO
import uz.elchi.app.api.generated.ReputationDTO
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.feature.client.BookingCancelSheet
import uz.elchi.app.feature.client.BookingNotices
import uz.elchi.app.feature.client.BookingRules
import uz.elchi.app.feature.client.BookingViewModel
import uz.elchi.app.feature.client.Load
import uz.elchi.app.feature.client.LoadFailed
import uz.elchi.app.feature.client.LoadingLine
import uz.elchi.app.feature.client.OrderRules
import uz.elchi.app.feature.client.ParcelPhotoBlock
import uz.elchi.app.feature.client.ParcelRules
import uz.elchi.app.feature.client.TaxiRules
import uz.elchi.app.feature.client.seatsLine
import uz.elchi.app.feature.client.seatsPrice
import uz.elchi.app.feature.client.ReputationLine
import uz.elchi.app.feature.client.StepScaffold
import uz.elchi.app.feature.client.categoryLimits
import uz.elchi.app.feature.client.categoryName
import uz.elchi.app.feature.client.displayPhone
import uz.elchi.app.feature.client.rememberNow
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
import uz.elchi.app.ui.components.ItemLine
import uz.elchi.app.ui.components.ListCard
import uz.elchi.app.ui.components.ListRow
import uz.elchi.app.ui.components.LoadingState
import uz.elchi.app.ui.components.MoneyBlock
import uz.elchi.app.ui.components.MoneyRow
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.Segmented
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone
import java.time.Instant
import java.util.Locale

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
    ItemCard(
        title = "${OrderRules.shortEnd(booking.pickup.stop, booking.pickup.point, ru)} → ${OrderRules.shortEnd(booking.dropoff.stop, booking.dropoff.point, ru)}",
        icon = ElchiIcon.PIN,
        badge = (tOrNull(DriverBookingRules.badgeKey(booking.serviceType, status)) ?: status) to DriverBookingRules.badgeTone(booking.serviceType, status),
        sub = booking.client?.displayName?.takeIf { it.isNotBlank() },
        lines = if (TaxiRules.isPassenger(booking.serviceType)) listOf(ItemLine(seatsLine(booking.quantity, booking.unitPriceMinor))) else emptyList(),
        meta = OrderRules.dayMonth(booking.pickup.windowStart ?: booking.createdAt, languageTag()),
        // Q103: what the driver collects in cash.
        right = soum(DriverBookingRules.cashToCollectMinor(booking)),
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
)

/**
 * `driver-order-detail` (parcel): what was agreed, with whom, what to collect in cash, the receiver only after the
 * trip departed (Q44/Q142), and what the driver can do in this status - "Keldim", chat, tracking, the price
 * amendment, support (Q146 the main help), cancel, rate the client; the safety report folded at the bottom. The GPS
 * bar sits on top while the trip runs.
 */
@Composable
fun DriverBookingDetailScreen(vm: BookingViewModel, tracker: DriverTracker, onBack: () -> Unit, nav: DriverBookingNav) {
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
    val booking = s.value
    val gpsTrip = booking?.let { DriverBookingRules.gpsTripId(it.serviceStatus, it.tripId) }
    StepScaffold(
        title = t(R.string.driverBooking_title),
        onBack = onBack,
        banner = {
            BookingNotices(s)
            if (gpsTrip != null) DriverTrackingBar(tracker, gpsTrip)
        },
        onRefresh = vm::refresh,
        refreshing = s.refreshing && s.booking is Load.Ready,
    ) {
        val driverView = s.driverView
        when (val load = s.booking) {
            Load.Loading -> LoadingLine(t(R.string.common_loading))
            is Load.Failed -> LoadFailed(t(R.string.driverBooking_title), load.error, vm::refresh)
            is Load.Ready -> if (driverView != null) {
                DriverBookingBody(vm, s, load.value, driverView, nav) {
                    vm.openCancel()
                    confirmCancel = true
                }
            }
        }
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
    nav: DriverBookingNav,
    onCancel: () -> Unit,
) {
    val now by rememberNow()
    val status = view.serviceStatus
    val actions = DriverBookingRules.actions(status, s.arrivedAt, view.updatedAt, now, view.noShowReview)
    val passenger = TaxiRules.isPassenger(view.serviceType)
    Header(view)
    if (actions.transitNote) Note(t(R.string.driver_booking_inTransitNote), tone = Tone.BLUE)
    Details(view)
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
    if (booking.parcelPhoto != null) ParcelPhotoBlock(s.photo, s.photoFailed)
    if (actions.arrive) {
        s.arriveError?.let { Note(errorText(it), tone = Tone.ERR) }
        ElchiButton(t(R.string.driverBooking_action_arrive), vm::arrive, Modifier.fillMaxWidth(), loading = s.arriving)
    } else if (s.arrivedAt != null && status in BookingViewModel.ARRIVE_STATUSES) {
        Note(t(R.string.driver_booking_arrivedSent), tone = Tone.OK)
    }
    if (passenger) PassengerActions(vm, s, view, now, nav)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        ElchiButton(t(R.string.driverBooking_messages), nav.onChat, Modifier.weight(1f).height(48.dp), ButtonVariant.SOFT, ButtonSize.MEDIUM, icon = ElchiIcon.CHAT, horizontalPadding = 10.dp)
        ElchiButton(t(R.string.driverBooking_tracking), nav.onTracking, Modifier.weight(1f).height(48.dp), ButtonVariant.SOFT, ButtonSize.MEDIUM, icon = ElchiIcon.PIN, horizontalPadding = 10.dp)
    }
    if (actions.amend) ElchiButton(t(R.string.driverBooking_amend), nav.onAmend, Modifier.fillMaxWidth(), ButtonVariant.NEUTRAL)
    if (actions.rate || s.rated || s.ratingRefusal != null) RateEntry(s, nav.onRate)
    // Q146: the operator chat is the booking page's main help; the safety report sits apart, folded below.
    ElchiButton(t(R.string.support_complain), nav.onSupport, Modifier.fillMaxWidth(), ButtonVariant.NEUTRAL, icon = ElchiIcon.HEAD)
    if (actions.cancel) ElchiButton(t(R.string.bookingCancel_button), onCancel, Modifier.fillMaxWidth(), ButtonVariant.DANGER_SOFT)
    ClientReputation(view, s.reputation, s.reputationFailed)
    ListCard {
        ListRow(t(R.string.safety_menuTitle), icon = ElchiIcon.SHIELD, description = t(R.string.client_bookingDetail_safetyHint), first = true, onClick = nav.onSafety)
    }
}

@Composable
private fun Header(view: DriverBookingDTO) {
    val ru = appRu()
    val status = view.serviceStatus
    val cancelled = view.cancelled?.takeIf { status == "cancelled" }?.let { c ->
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
        "${t(R.string.bookingCancel_cancelledBy)}: ${parts.joinToString(" · ")}"
    }
    val window = OrderRules.windowText(view.pickup.windowStart, view.pickup.windowEnd)
    val passenger = TaxiRules.isPassenger(view.serviceType) && view.promo == null
    ItemCard(
        title = "${OrderRules.shortEnd(view.pickup.stop, view.pickup.point, ru)} → ${OrderRules.shortEnd(view.dropoff.stop, view.dropoff.point, ru)}",
        badge = (tOrNull(DriverBookingRules.badgeKey(view.serviceType, status)) ?: status) to DriverBookingRules.badgeTone(view.serviceType, status),
        lines = listOfNotNull(cancelled?.let { ItemLine(it, Elchi.colors.tone(Tone.ERR).fg) }),
        meta = window,
        // Taksi: "2 × 150 000 so'm" (design), the per-seat basis.
        right = if (passenger) seatsPrice(view.quantity, view.unitPriceMinor) else soum(view.totalMinor),
    )
}

/** Ends (stop name or the point's district - never a street the server did not send), client, parcel, receiver, money. */
@Composable
private fun Details(view: DriverBookingDTO) {
    val ru = appRu()
    val context = LocalContext.current
    val activity = LocalActivity.current
    ElchiCard {
        CardRow(t(if (view.pickup.stop != null) R.string.driverBooking_pickupStop else R.string.driverBooking_pickupPoint), OrderRules.shortEnd(view.pickup.stop, view.pickup.point, ru), first = true)
        CardRow(t(if (view.dropoff.stop != null) R.string.driverBooking_dropoffStop else R.string.driverBooking_dropoffPoint), OrderRules.shortEnd(view.dropoff.stop, view.dropoff.point, ru))
        CardRow(t(R.string.driver_booking_clientTitle), view.client?.displayName?.takeIf { it.isNotBlank() } ?: t(R.string.driver_booking_clientFallback))
        if (TaxiRules.isPassenger(view.serviceType)) {
            // Q44: the client's phone opens when the service starts (onboard); before that the in-app chat.
            val phone = view.client?.contactPhone?.takeIf { it.isNotBlank() && view.contact?.phonesVisible != false }
            if (phone != null) {
                CardRow(
                    t(R.string.driverBooking_phone),
                    displayPhone(phone),
                    trailing = t(R.string.client_bookingDetail_call),
                    onTrailing = {
                        val dial = Intent(Intent.ACTION_DIAL, BookingRules.dialUri(phone).toUri())
                        activity?.startActivity(dial) ?: context.startActivity(dial.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                    },
                )
            } else {
                CardRow(t(R.string.driverBooking_phone), t(R.string.driverBooking_phoneHidden), muted = true)
            }
            CardRow(t(R.string.orderForm_review_passengers), seatsLine(view.quantity, view.unitPriceMinor), detail = t(R.string.orderForm_review_seatNegotiated))
        }
        view.parcelCategory?.let { CardRow(t(R.string.listingDetail_parcel), "${categoryName(it, ru)} · ${categoryLimits(it)}") }
        if (view.serviceType == ServiceType.PARCEL) when (val receiver = DriverBookingRules.receiver(view)) {
            is ReceiverView.Visible -> CardRow(
                t(R.string.driverBooking_receiver),
                listOfNotNull(receiver.name, displayPhone(receiver.phone)).joinToString(" · "),
                trailing = t(R.string.client_bookingDetail_call),
                onTrailing = {
                    val dial = Intent(Intent.ACTION_DIAL, BookingRules.dialUri(receiver.phone).toUri())
                    activity?.startActivity(dial) ?: context.startActivity(dial.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                },
            )
            is ReceiverView.Hidden -> CardRow(t(R.string.driverBooking_receiver), t(R.string.driverBooking_receiverHidden), muted = true)
        }
        CardRow(t(R.string.driverBooking_fare), t(R.string.driverBooking_fareCash, "amount" to soum(DriverBookingRules.cashToCollectMinor(view))), strong = true)
        // A cancelled booking charges nothing (the hold is released): no commission line then.
        DriverBookingRules.commissionMinor(view)?.takeIf { view.serviceStatus != "cancelled" }?.let { commission ->
            val bps = view.fee?.feeBps?.takeIf { it > 0 && view.promo == null }
            // Q103: the driver sees the commission (never the client). The percent only for the plain fee policy.
            CardRow(
                t(R.string.driver_booking_commission),
                if (bps != null) t(R.string.driver_booking_commissionValue, "amount" to soum(commission), "percent" to DriverBookingRules.percent(bps)) else soum(commission),
            )
        }
    }
}

@Composable
private fun RateEntry(s: BookingViewModel.State, onRate: () -> Unit) {
    val refusal = s.ratingRefusal
    when {
        s.rated -> Note(listOfNotNull(t(R.string.client_bookingDetail_rated), refusal?.let { errorText(it) }).joinToString(" "), tone = Tone.OK)
        refusal != null -> Note(errorText(refusal), tone = Tone.GRAY)
        else -> {
            ElchiButton(t(R.string.rating_rateClient), onRate, Modifier.fillMaxWidth())
            Text(t(R.string.driver_booking_rateNote), style = Elchi.type.caption, color = Elchi.colors.muted)
        }
    }
}

/** "Mijoz: Aziza · Yangi · Hali baholanmagan" - a real average with its counts or nothing invented (§9). */
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
            else -> "${t(R.string.reputation_new)} · ${t(R.string.reputation_notRated)}"
        }
        val detail = reputation?.takeIf { line is ReputationLine.Unrated }?.let {
            "${t(R.string.reputation_completedBookings)}: ${t(R.string.reputation_count, "count" to it.completedBookings)}"
        }
        CardRow("${t(R.string.driver_booking_clientTitle)}: $name", value, first = true, detail = detail)
    }
}
