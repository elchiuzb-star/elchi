package uz.elchi.app.gps

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.LocalActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.delay
import uz.elchi.app.R
import uz.elchi.app.feature.client.ParcelRules
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone
import java.time.Instant
import java.time.format.DateTimeFormatter

private val PERMISSIONS = arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)
private val CLOCK = DateTimeFormatter.ofPattern("HH:mm")
private val CLOCK_SECONDS = DateTimeFormatter.ofPattern("HH:mm:ss")

private fun clock(ms: Long, format: DateTimeFormatter): String = Instant.ofEpochMilli(ms).atZone(ParcelRules.TASHKENT).format(format)

/**
 * The driver's GPS status strip (design 'gps-bar', web `DriverTrackingBar.tsx`) under the title of the trips list,
 * the trip, and the booking detail / chat of a running trip. [tripId] = the screen's running trip (null: shown only
 * when the publisher has something to say). It asks the location permission when an auto-start needs it, and
 * picks up a permission granted in the settings when the screen comes back.
 */
@Composable
fun DriverTrackingBar(tracker: DriverTracker, tripId: String?, modifier: Modifier = Modifier, inset: Dp = 16.dp) {
    val s by tracker.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val activity = LocalActivity.current
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(s.phase) {
        while (s.phase == TrackerPhase.ACTIVE) {
            now = System.currentTimeMillis()
            delay(5_000)
        }
        now = System.currentTimeMillis()
    }
    var explicit by remember { mutableIntStateOf(0) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
        val granted = result.values.any { it }
        tracker.accessChanged(granted)
        // Asked from the "Qayta urinish" button and Android no longer shows the question: its settings page.
        if (!granted && explicit > 0 && activity != null && !activity.shouldShowRequestPermissionRationale(Manifest.permission.ACCESS_FINE_LOCATION)) {
            openSettings(activity)
        }
        explicit = 0
    }
    // An auto-start (after "Chiqishni boshlash" / "Yo'lga chiqdim") without the permission: ask once per request.
    var handledAsk by rememberSaveable { mutableIntStateOf(s.askPermission) }
    LaunchedEffect(s.askPermission, s.phase) {
        if (s.phase == TrackerPhase.NEEDS_PERMISSION && s.askPermission != handledAsk && (tripId == null || s.tripId == tripId)) {
            handledAsk = s.askPermission
            launcher.launch(PERMISSIONS)
        }
    }
    // Back from the settings (or the system dialog): a permission given there resumes publishing by itself.
    LifecycleResumeEffect(tracker) {
        if (AndroidTrackerPlatform.access(context) != LocationAccess.NONE) tracker.accessChanged(true)
        onPauseOrDispose { }
    }
    val model = TrackerBar.model(s, tripId, now, clock = { clock(it, CLOCK) }, clockSeconds = { clock(it, CLOCK_SECONDS) }) ?: return
    val start: () -> Unit = { (tripId ?: s.tripId)?.let { tracker.start(it) } }
    val onAction: () -> Unit = {
        when (model.action) {
            BarAction.STOP -> tracker.stop()
            BarAction.PERMISSION -> {
                explicit += 1
                launcher.launch(PERMISSIONS)
            }
            BarAction.START, BarAction.RETRY, BarAction.TAKE_OVER, null -> start()
        }
    }
    TrackingStrip(model, onAction, modifier, inset)
}

private fun openSettings(activity: Activity) {
    runCatching {
        activity.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", activity.packageName, null)))
    }
}

@Composable
private fun barText(text: BarText): String {
    val values = text.params.map { (k, v) -> k to (v as Any) }.toTypedArray()
    return when (text.key) {
        "gps.permissionPrompt" -> t(R.string.driver_gps_permissionPrompt)
        else -> tOrNull(text.key, *values) ?: text.key
    }
}

@Composable
private fun TrackingStrip(model: BarModel, onAction: () -> Unit, modifier: Modifier, inset: Dp) {
    val c = Elchi.colors
    val dot = when (model.dot) {
        BarDot.GREEN -> c.tone(Tone.OK).fg
        BarDot.AMBER -> Color(0xFFE0A100)
        BarDot.RED -> c.danger
        BarDot.GRAY -> Color(0xFF9AA6B5)
    }
    val title = barText(model.title)
    val notes = model.notes.map { barText(it) }
    val actionLabel = when (model.action) {
        BarAction.STOP -> t(R.string.driverTracking_stop)
        BarAction.START -> t(R.string.driverTracking_start)
        BarAction.PERMISSION, BarAction.RETRY -> t(R.string.driverTracking_retry)
        BarAction.TAKE_OVER -> t(R.string.driverTracking_takeOver)
        null -> null
    }
    Row(
        modifier
            .fillMaxWidth()
            .padding(horizontal = inset, vertical = 6.dp)
            .clip(RoundedCornerShape(14.dp))
            .background(c.card)
            .border(1.dp, c.line, RoundedCornerShape(14.dp))
            .padding(horizontal = 12.dp, vertical = 10.dp)
            .semantics(mergeDescendants = false) { liveRegion = LiveRegionMode.Polite },
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Box(Modifier.padding(top = 4.dp).size(14.dp), contentAlignment = Alignment.Center) {
            if (model.sending) Box(Modifier.size(14.dp).clip(CircleShape).background(dot.copy(alpha = 0.25f)))
            Box(Modifier.size(9.dp).clip(CircleShape).background(dot))
        }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(title, style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold), color = c.text)
            notes.forEach { Text(it, style = Elchi.type.caption.copy(fontSize = 11.5.sp, lineHeight = 15.sp), color = c.muted) }
        }
        if (actionLabel != null) {
            val primary = model.action != BarAction.STOP
            Text(
                actionLabel,
                Modifier
                    .widthIn(max = 132.dp)
                    .heightIn(min = 34.dp)
                    .clip(RoundedCornerShape(17.dp))
                    .background(if (primary) c.brand else c.field)
                    .clickable(role = Role.Button, onClick = onAction)
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                style = Elchi.type.label.copy(fontSize = 12.5.sp, fontWeight = FontWeight.SemiBold),
                color = if (primary) c.onBrand else c.text,
                maxLines = 2,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            )
        }
    }
}
