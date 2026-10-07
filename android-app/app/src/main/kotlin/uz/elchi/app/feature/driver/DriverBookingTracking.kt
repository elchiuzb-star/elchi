package uz.elchi.app.feature.driver

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.elchi.app.R
import uz.elchi.app.api.generated.TrackingFreshness
import uz.elchi.app.feature.client.BookingRules
import uz.elchi.app.feature.client.Load
import uz.elchi.app.feature.client.LoadFailed
import uz.elchi.app.feature.client.LoadingLine
import uz.elchi.app.feature.client.OrderRules
import uz.elchi.app.feature.client.ParcelRules
import uz.elchi.app.feature.client.StepScaffold
import uz.elchi.app.feature.client.TrackingViewModel
import uz.elchi.app.feature.client.WhileStarted
import uz.elchi.app.feature.client.rememberNow
import uz.elchi.app.gps.DriverTracker
import uz.elchi.app.gps.DriverTrackingBar
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.CardRow
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.RoundIconButton
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.map.ElchiMap
import uz.elchi.app.ui.map.GeoPoint
import uz.elchi.app.ui.map.MapFocus
import uz.elchi.app.ui.map.MapMarker
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone
import java.time.format.DateTimeFormatter

/**
 * Design 08 "Kuzatuv (siz yuborayotgan)": what the client sees of the driver's own car - the server's last point
 * (Q148: never this phone's position), its freshness word, the sentence on when this phone sends (background only
 * while the location service really runs), and the rows Holat / Oxirgi nuqta. The GPS bar on top while the trip runs.
 * The distance to the destination does not exist (11.5 BLOCKED).
 */
@Composable
fun DriverBookingTrackingScreen(vm: TrackingViewModel, tracker: DriverTracker, onBack: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val snapshot by tracker.state.collectAsStateWithLifecycle()
    val now by rememberNow()
    WhileStarted(vm) { vm.watch() }
    val booking = (s.booking as? Load.Ready)?.value
    val gpsTrip = booking?.let { DriverBookingRules.gpsTripId(it.serviceStatus, it.tripId) }
    StepScaffold(
        title = t(R.string.driver_v3bkg_trackingTitle),
        onBack = onBack,
        banner = { if (gpsTrip != null) DriverTrackingBar(tracker, gpsTrip) },
        actions = { RoundIconButton(ElchiIcon.REFRESH, t(R.string.proposal_refresh), vm::refresh) },
    ) {
        if (s.booking is Load.Failed) {
            LoadFailed(t(R.string.driver_v3bkg_trackingTitle), (s.booking as Load.Failed).error, vm::refresh)
            return@StepScaffold
        }
        val c = Elchi.colors
        val live = s.live
        val data = live.data
        val point = data?.lastPoint?.takeIf { data.window.isOpen }
        val freshness = data?.let { BookingRules.effectiveFreshness(it.freshness, it.lastPoint, now) } ?: TrackingFreshness.UNKNOWN
        val word = t(freshnessWord(freshness))
        if (point != null) {
            val here = GeoPoint(point.lat, point.lng)
            val fresh = freshness == TrackingFreshness.FRESH
            val markers = remember(point.lat, point.lng, fresh) { listOf(MapMarker(here, if (fresh) MapMarker.Kind.VEHICLE else MapMarker.Kind.VEHICLE_STALE)) }
            val focus = remember(point.lat, point.lng) { MapFocus.At(here, 14f) }
            Box(Modifier.fillMaxWidth().height(260.dp).clip(RoundedCornerShape(20.dp))) {
                ElchiMap(
                    Modifier.fillMaxWidth().height(260.dp),
                    markers = markers,
                    focus = focus,
                    interactive = false,
                    placeholderTitle = t(R.string.client_map_unavailable),
                    placeholderText = "${t(R.string.client_tracking_coordinates)}: ${ParcelRules.coordinates(point.lat, point.lng)}",
                )
                Row(
                    Modifier.align(Alignment.TopStart).padding(12.dp).shadow(6.dp, CircleShape, ambientColor = c.shadow, spotColor = c.shadow)
                        .clip(CircleShape).background(c.card).padding(horizontal = 12.dp, vertical = 6.dp)
                        .semantics { liveRegion = LiveRegionMode.Polite },
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Box(Modifier.size(8.dp).clip(CircleShape).background(freshnessDot(freshness)))
                    Text(word, style = Elchi.type.badge, color = c.text)
                }
            }
        } else {
            when {
                s.booking is Load.Loading || (!live.loaded && live.error == null) -> LoadingLine(t(R.string.common_loading))
                live.gone -> Note(t(R.string.liveTracking_gone), tone = Tone.GRAY)
                live.featureOff -> Note(t(R.string.bookingTracking_liveDisabled), tone = Tone.GRAY, title = t(R.string.client_tracking_notStarted))
                live.closedReason != null || (data != null && !data.window.isOpen) -> {
                    val reason = live.closedReason ?: data?.window?.reason?.value.orEmpty()
                    Note(tOrNull("trackingWindow.$reason") ?: t(R.string.trackingWindow_not_yet_open), tone = Tone.GRAY)
                }
                live.error != null -> Note(errorText(live.error), tone = Tone.ERR)
                else -> Note(t(R.string.liveTracking_noPoint), tone = Tone.GRAY, title = word)
            }
        }
        // Design 08 11.2: the point the client sees, then when this phone sends (the web's fixed sentence is Q148's).
        Text(
            "${t(R.string.driver_v3bkg_trackingNote)} ${tOrNull(DriverBookingRules.trackingNoteKey(snapshot)).orEmpty()}".trim(),
            style = Elchi.type.caption,
            color = c.muted,
        )
        ElchiCard {
            val status = booking?.let { b -> tOrNull(DriverBookingRules.badgeKey(b.serviceType, b.serviceStatus, review = b.noShowReview)) ?: b.serviceStatus } ?: "—"
            CardRow(t(R.string.support_statusLabel), status, first = true)
            val last = data?.lastPoint?.let { p ->
                val time = OrderRules.tashkent(p.capturedAt)?.format(DateTimeFormatter.ofPattern("HH:mm:ss")) ?: "?"
                "$time · ±${p.accuracyM} m"
            }
            CardRow(t(R.string.publicTracking_lastPosition), last ?: "—", detail = data?.lastPoint?.let { word })
        }
        if (data != null && live.error != null && live.closedReason == null) Note(errorText(live.error), tone = Tone.WARN)
    }
}

private fun freshnessWord(freshness: TrackingFreshness): Int = when (freshness) {
    TrackingFreshness.FRESH -> R.string.publicTracking_fresh
    TrackingFreshness.DELAYED -> R.string.publicTracking_delayed
    TrackingFreshness.LOST -> R.string.publicTracking_lost
    else -> R.string.publicTracking_noData
}

@Composable
private fun freshnessDot(freshness: TrackingFreshness): Color = when (freshness) {
    TrackingFreshness.FRESH -> Elchi.colors.tone(Tone.OK).fg
    TrackingFreshness.DELAYED -> Color(0xFFE0A100)
    TrackingFreshness.LOST -> Elchi.colors.danger
    else -> Color(0xFF9AA6B5)
}
