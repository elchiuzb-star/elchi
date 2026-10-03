package uz.elchi.app.feature.client

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.widthIn
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.sp
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.elchi.app.R
import uz.elchi.app.api.BookingClientDTO
import uz.elchi.app.api.generated.BookingTrackingDTO
import uz.elchi.app.api.generated.TrackingFreshness
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiIconView
import uz.elchi.app.ui.components.RoundIconButton
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.components.GpsTone
import uz.elchi.app.ui.components.LadderRow
import uz.elchi.app.ui.components.LadderState
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.SectionTitle
import uz.elchi.app.ui.components.StatusLadder
import uz.elchi.app.ui.map.ElchiMap
import uz.elchi.app.ui.map.GeoPoint
import uz.elchi.app.ui.map.MapFocus
import uz.elchi.app.ui.map.MapMarker
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone
import java.time.Instant
import java.time.format.DateTimeFormatter

/**
 * `booking-tracking` "Kuzatuv": the booking's stages as the system recorded them, and the driver's live position
 * with an honest freshness - re-aged on this phone's clock and never shown as live unless it is. No ETA exists in
 * the pilot, so none is shown (6.7 BLOCKED). Everything stops when the screen is left or the app goes to the
 * background. The window is the server's (a Taksi window opens 30 min before pickup), never gated on the status here.
 */
@Composable
fun BookingTrackingScreen(vm: TrackingViewModel, onBack: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val now by rememberNow()
    val toast = LocalFlowToast.current
    val refreshed = t(R.string.client_booking_refreshed)
    WhileStarted(vm) { vm.watch() }
    StepScaffold(
        title = t(R.string.bookingTracking_title),
        onBack = onBack,
        actions = {
            RoundIconButton(ElchiIcon.REFRESH, t(R.string.proposal_refresh), {
                vm.refresh()
                toast.show(refreshed)
            })
        },
    ) {
        SectionTitle(t(R.string.bookingTracking_progressTitle), description = t(R.string.bookingTracking_progressHint))
        val booking = (s.booking as? Load.Ready)?.value
        when (val load = s.booking) {
            Load.Loading -> LoadingLine(t(R.string.common_loading))
            is Load.Failed -> LoadFailed(t(R.string.bookingTracking_title), load.error, vm::refresh)
            is Load.Ready -> Ladder(load.value)
        }
        SectionTitle(t(R.string.bookingTracking_liveTitle))
        LiveSection(s.live, now, booking?.serviceStatus)
    }
}

@Composable
private fun Ladder(booking: BookingClientDTO) {
    val labels = mapOf(LadderState.DONE to t(R.string.client_tracking_stepDone), LadderState.CURRENT to t(R.string.client_tracking_stepCurrent))
    // Design 04: a cancelled booking is two rungs - agreed, then cancelled (red) with its time.
    if (booking.serviceStatus == "cancelled") {
        StatusLadder(
            listOf(
                LadderRow(t(R.string.status_confirmed), OrderRules.dayTime(booking.createdAt), LadderState.DONE),
                LadderRow(t(R.string.bookingCancel_cancelledBy), OrderRules.dayTime(booking.cancelled?.at), LadderState.FAILED),
            ),
            stateLabels = labels,
        )
        return
    }
    val rows = BookingRules.ladder(booking).map { item ->
        LadderRow(
            title = tOrNull(item.key) ?: item.step.name,
            time = item.at?.let { OrderRules.tashkent(it)?.let(ParcelRules::displayShort) },
            state = when (item.state) {
                StepState.DONE -> LadderState.DONE
                StepState.CURRENT -> LadderState.CURRENT
                StepState.TODO -> LadderState.TODO
            },
        )
    }
    StatusLadder(rows, stateLabels = labels)
    // No-show and the return statuses are not steps on the way: they are said in words.
    if (BookingRules.ladderIndex(booking.serviceStatus, booking.serviceType) == null) {
        val status = tOrNull(OrderRules.bookingStatusKey(booking.serviceType, booking.serviceStatus)) ?: booking.serviceStatus
        val tone = OrderRules.bookingTone(booking.serviceType, booking.serviceStatus)
        Note(t(R.string.client_tracking_offLadder, "status" to status), tone = if (tone == Tone.ERR) Tone.ERR else Tone.WARN)
    }
}

@Composable
private fun LiveSection(live: LiveState, now: Instant, status: String?) {
    val data = live.data
    when {
        live.gone -> Note(t(R.string.liveTracking_gone), tone = Tone.GRAY)
        live.featureOff -> ClosedCard(t(R.string.client_tracking_notStarted), t(R.string.bookingTracking_liveDisabled))
        live.closedReason != null -> ClosedWindowCard(status, live.closedReason)
        data != null && !data.window.isOpen -> ClosedWindowCard(status, data.window.reason.value)
        data != null -> LivePosition(data, now, polling = live.transport != LiveTransport.SOCKET)
        live.error != null -> Note(errorText(live.error), tone = Tone.ERR)
        else -> LoadingLine(t(R.string.common_loading))
    }
    // A failed refresh under a position already on screen: say so, keep the position (it ages honestly).
    if (data != null && live.error != null && live.closedReason == null) Note(errorText(live.error), tone = Tone.WARN)
}

/** The window's closed reasons in words (parcel not picked up yet, booking or trip finished). */
@Composable
private fun windowText(reason: String): String = tOrNull("trackingWindow.$reason") ?: t(R.string.trackingWindow_not_yet_open)

/** Design 04 `liveOff`: a card with the pin, a title (not started / closed / cancelled) and the server's reason. */
@Composable
private fun ClosedWindowCard(status: String?, reason: String) {
    when (BookingRules.closedWindowTitle(status, reason)) {
        ClosedWindow.CANCELLED -> ClosedCard(t(R.string.client_tracking_bookingCancelled), "${t(R.string.client_tracking_liveClosed)}.")
        ClosedWindow.FINISHED -> ClosedCard(t(R.string.client_tracking_liveClosed), windowText(reason))
        ClosedWindow.NOT_STARTED -> ClosedCard(t(R.string.client_tracking_notStarted), windowText(reason))
    }
}

@Composable
private fun ClosedCard(title: String, body: String) {
    val c = Elchi.colors
    ElchiCard(padding = PaddingValues(horizontal = 16.dp, vertical = 26.dp)) {
        Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Box(Modifier.size(56.dp).clip(CircleShape).background(c.field), contentAlignment = Alignment.Center) {
                ElchiIconView(ElchiIcon.PIN, c.muted, size = 26.dp)
            }
            Text(title, style = Elchi.type.secondary.copy(fontWeight = FontWeight.SemiBold, fontSize = 15.sp), color = c.text, textAlign = TextAlign.Center)
            Text(body, Modifier.widthIn(max = 280.dp), style = Elchi.type.label.copy(fontWeight = FontWeight.Normal, lineHeight = 19.sp), color = c.muted, textAlign = TextAlign.Center)
        }
    }
}

@Composable
private fun LivePosition(data: BookingTrackingDTO, now: Instant, polling: Boolean) {
    val c = Elchi.colors
    val point = data.lastPoint
    val freshness = BookingRules.effectiveFreshness(data.freshness, point, now)
    val live = freshness == TrackingFreshness.FRESH
    val tone = when (freshness) {
        TrackingFreshness.FRESH -> GpsTone.LIVE
        TrackingFreshness.DELAYED -> GpsTone.DELAYED
        TrackingFreshness.LOST -> GpsTone.LOST
        else -> GpsTone.NONE
    }
    val stateTitle = t(freshnessTitle(freshness))
    if (point != null) {
        val here = GeoPoint(point.lat, point.lng)
        val markers = remember(point.lat, point.lng, live) { listOf(MapMarker(here, if (live) MapMarker.Kind.VEHICLE else MapMarker.Kind.VEHICLE_STALE)) }
        val focus = remember(point.lat, point.lng) { MapFocus.At(here, 14f) }
        Box(Modifier.fillMaxWidth().height(230.dp).clip(RoundedCornerShape(20.dp))) {
            ElchiMap(
                Modifier.fillMaxWidth().height(230.dp),
                markers = markers,
                focus = focus,
                interactive = false,
                placeholderTitle = t(R.string.client_map_unavailable),
                placeholderText = "${t(R.string.client_tracking_coordinates)}: ${ParcelRules.coordinates(point.lat, point.lng)}",
            )
            // The pill claims "Jonli" only for a fresh point; otherwise it names the state.
            Row(
                Modifier.align(Alignment.TopStart).padding(12.dp).shadow(6.dp, CircleShape, ambientColor = c.shadow, spotColor = c.shadow)
                    .clip(CircleShape).background(c.card).padding(horizontal = 12.dp, vertical = 6.dp)
                    .semantics { liveRegion = LiveRegionMode.Polite },
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Box(Modifier.size(8.dp).clip(CircleShape).background(dotColor(tone)))
                Text(stateTitle, style = Elchi.type.badge, color = c.text)
            }
        }
        val time = OrderRules.tashkent(point.capturedAt)?.format(DateTimeFormatter.ofPattern("HH:mm:ss")) ?: "?"
        val line = t(R.string.client_tracking_lastPointLine, "time" to time, "accuracy" to point.accuracyM)
        val low = if (point.lowAccuracy) " (${t(R.string.liveTracking_lowAccuracy)})" else ""
        val cadence = if (polling) " ${t(R.string.liveTracking_polling)}" else ""
        Text("$line$low.$cadence", style = Elchi.type.caption, color = c.muted)
    }
    when (freshness) {
        TrackingFreshness.FRESH -> Unit
        TrackingFreshness.DELAYED -> {
            val age = BookingRules.pointAgeSeconds(point?.capturedAt, now) ?: 60
            val minutes = ((age + 59) / 60).coerceAtLeast(1)
            Note(t(R.string.client_tracking_delayedNote, "time" to t(R.string.app_duration_minutes, "minutes" to minutes)), tone = Tone.WARN)
        }
        TrackingFreshness.LOST -> Note(t(R.string.client_tracking_lostNote), tone = Tone.ERR)
        else -> Note(t(R.string.liveTracking_noPoint), tone = Tone.GRAY, title = stateTitle)
    }
}

/** The design's short state words: Jonli / Kechikmoqda / Aloqa uzilgan / Joylashuv yo'q. */
private fun freshnessTitle(freshness: TrackingFreshness): Int = when (freshness) {
    TrackingFreshness.FRESH -> R.string.publicTracking_fresh
    TrackingFreshness.DELAYED -> R.string.publicTracking_delayed
    TrackingFreshness.LOST -> R.string.publicTracking_lost
    else -> R.string.publicTracking_noData
}

@Composable
private fun dotColor(tone: GpsTone) = when (tone) {
    GpsTone.LIVE -> Elchi.colors.tone(Tone.OK).fg
    GpsTone.DELAYED -> androidx.compose.ui.graphics.Color(0xFFE0A100)
    GpsTone.LOST -> Elchi.colors.danger
    GpsTone.NONE -> androidx.compose.ui.graphics.Color(0xFF9AA6B5)
}
