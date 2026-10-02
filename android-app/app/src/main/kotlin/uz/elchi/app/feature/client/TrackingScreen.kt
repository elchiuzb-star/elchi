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
import uz.elchi.app.ui.components.GpsStateRow
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
 * the pilot, so none is shown. Everything stops when the screen is left or the app goes to the background.
 */
@Composable
fun BookingTrackingScreen(vm: TrackingViewModel, onBack: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val now by rememberNow()
    WhileStarted(vm) { vm.watch() }
    StepScaffold(title = t(R.string.bookingTracking_title), onBack = onBack) {
        SectionTitle(t(R.string.bookingTracking_progressTitle), description = t(R.string.bookingTracking_progressHint))
        when (val load = s.booking) {
            Load.Loading -> LoadingLine(t(R.string.common_loading))
            is Load.Failed -> LoadFailed(t(R.string.bookingTracking_title), load.error, {})
            is Load.Ready -> Ladder(load.value)
        }
        SectionTitle(t(R.string.bookingTracking_liveTitle))
        LiveSection(s.live, now)
    }
}

@Composable
private fun Ladder(booking: BookingClientDTO) {
    val labels = mapOf(LadderState.DONE to t(R.string.client_tracking_stepDone), LadderState.CURRENT to t(R.string.client_tracking_stepCurrent))
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
    // Cancelled and the return statuses are not steps on the way: they are said in words.
    if (BookingRules.ladderIndex(booking.serviceStatus, booking.serviceType) == null) {
        val status = tOrNull(OrderRules.bookingStatusKey(booking.serviceType, booking.serviceStatus)) ?: booking.serviceStatus
        val tone = OrderRules.bookingTone(booking.serviceType, booking.serviceStatus)
        Note(t(R.string.client_tracking_offLadder, "status" to status), tone = if (tone == Tone.ERR) Tone.ERR else Tone.WARN)
    }
}

@Composable
private fun LiveSection(live: LiveState, now: Instant) {
    val data = live.data
    when {
        live.gone -> Note(t(R.string.liveTracking_gone), tone = Tone.GRAY)
        live.featureOff -> Note(t(R.string.bookingTracking_liveDisabled), tone = Tone.GRAY)
        live.closedReason != null -> Note(windowText(live.closedReason), tone = Tone.GRAY)
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

@Composable
private fun LivePosition(data: BookingTrackingDTO, now: Instant, polling: Boolean) {
    val c = Elchi.colors
    val point = data.lastPoint
    val freshness = BookingRules.effectiveFreshness(data.freshness, point, now)
    val live = freshness == TrackingFreshness.FRESH
    if (!data.window.isOpen) {
        Note(windowText(data.window.reason.value), tone = Tone.GRAY)
        return
    }
    val (tone, notes) = when (freshness) {
        TrackingFreshness.FRESH -> GpsTone.LIVE to listOf(t(R.string.client_tracking_freshLine))
        TrackingFreshness.DELAYED -> GpsTone.DELAYED to listOf(t(R.string.liveTracking_delayedHint))
        TrackingFreshness.LOST -> GpsTone.LOST to listOf(t(R.string.liveTracking_lostHint))
        else -> GpsTone.NONE to listOf(t(R.string.liveTracking_noPoint))
    }
    GpsStateRow(tone, t(freshnessTitle(freshness)), notes)
    if (point != null) {
        val here = GeoPoint(point.lat, point.lng)
        val markers = remember(point.lat, point.lng, live) { listOf(MapMarker(here, if (live) MapMarker.Kind.VEHICLE else MapMarker.Kind.VEHICLE_STALE)) }
        val focus = remember(point.lat, point.lng) { MapFocus.At(here, 14f) }
        Box(Modifier.fillMaxWidth().height(220.dp).clip(RoundedCornerShape(20.dp))) {
            ElchiMap(
                Modifier.fillMaxWidth().height(220.dp),
                markers = markers,
                focus = focus,
                interactive = false,
                placeholderTitle = t(R.string.client_map_unavailable),
                placeholderText = "${t(R.string.client_tracking_coordinates)}: ${ParcelRules.coordinates(point.lat, point.lng)}",
            )
            // The label claims "live" only for a fresh point; otherwise it names the state.
            Row(
                Modifier.align(Alignment.TopStart).padding(12.dp).shadow(6.dp, CircleShape, ambientColor = c.shadow, spotColor = c.shadow)
                    .clip(CircleShape).background(c.card).padding(horizontal = 12.dp, vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Box(Modifier.size(8.dp).clip(CircleShape).background(dotColor(tone)))
                Text(t(freshnessTitle(freshness)), style = Elchi.type.badge, color = c.text)
            }
        }
        val time = OrderRules.tashkent(point.capturedAt)?.format(DateTimeFormatter.ofPattern("HH:mm")) ?: "?"
        val line = t(R.string.client_tracking_lastPointLine, "time" to time, "accuracy" to point.accuracyM)
        val low = if (point.lowAccuracy) " (${t(R.string.liveTracking_lowAccuracy)})" else ""
        val cadence = if (polling) " ${t(R.string.liveTracking_polling)}" else ""
        Text("$line$low.$cadence", style = Elchi.type.caption, color = c.muted)
    }
}

private fun freshnessTitle(freshness: TrackingFreshness): Int = when (freshness) {
    TrackingFreshness.FRESH -> R.string.liveTracking_freshness_fresh
    TrackingFreshness.DELAYED -> R.string.liveTracking_freshness_delayed
    TrackingFreshness.LOST -> R.string.liveTracking_freshness_lost
    else -> R.string.liveTracking_freshness_no_data
}

@Composable
private fun dotColor(tone: GpsTone) = when (tone) {
    GpsTone.LIVE -> Elchi.colors.tone(Tone.OK).fg
    GpsTone.DELAYED -> androidx.compose.ui.graphics.Color(0xFFE0A100)
    GpsTone.LOST -> Elchi.colors.danger
    GpsTone.NONE -> androidx.compose.ui.graphics.Color(0xFF9AA6B5)
}
