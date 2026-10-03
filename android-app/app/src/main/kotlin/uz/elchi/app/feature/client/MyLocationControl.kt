package uz.elchi.app.feature.client

import android.Manifest
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.LifecycleResumeEffect
import kotlinx.coroutines.delay
import uz.elchi.app.R
import uz.elchi.app.i18n.t
import uz.elchi.app.ui.components.ElchiIconView
import uz.elchi.app.ui.components.RoundIconButton
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.map.MyLocation
import uz.elchi.app.ui.map.MyLocationPhase
import uz.elchi.app.ui.map.MyLocationState
import uz.elchi.app.ui.map.UserLocationSource
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone

private val PERMISSIONS = arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)

/** An "unavailable" banner goes by itself after this; "denied" stays until closed, panned or tapped again. */
private const val UNAVAILABLE_SHOWN_MS = 6_000L

/** The client home's "my location": the [MyLocation] state machine wired to the phone (permission, fused location). */
@Stable
class MyLocationController internal constructor(
    private val source: UserLocationSource,
    private val askPermission: () -> Unit,
) {
    var state by mutableStateOf(MyLocationState())
        internal set

    private fun now() = System.currentTimeMillis()

    fun tap() {
        state = MyLocation.tap(state, source.granted(), source.locationOn(), now())
        if (state.phase == MyLocationPhase.ASKING) askPermission()
    }

    /** The camera left the user (a pan, or the route's recentre button). */
    fun panned() {
        state = MyLocation.panned(state)
    }

    fun dismiss() {
        state = MyLocation.dismiss(state)
    }

    internal fun permissionResult(granted: Boolean) {
        state = MyLocation.permissionResult(state, granted, source.locationOn(), now())
    }

    internal fun resumed() {
        state = MyLocation.resumed(state, source.granted(), source.locationOn(), now())
        source.start { state = MyLocation.fix(state, it) }
    }

    internal fun paused() = source.stop()

    internal fun requestCurrent() = source.current(MyLocation.TIMEOUT_MS) { state = MyLocation.fix(state, it) }
}

/**
 * The dot follows the phone only while the home is on screen (resumed): updates stop on pause and when the home
 * leaves. Nothing is asked at start - the permission dialog comes from the button only.
 */
@Composable
fun rememberMyLocation(): MyLocationController {
    val context = LocalContext.current
    val holder = remember { arrayOfNulls<MyLocationController>(1) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
        holder[0]?.permissionResult(result.values.any { it })
    }
    val controller = remember { MyLocationController(UserLocationSource(context)) { launcher.launch(PERMISSIONS) }.also { holder[0] = it } }
    LifecycleResumeEffect(controller) {
        controller.resumed()
        onPauseOrDispose { controller.paused() }
    }
    // One wait per tap: a precise fix is asked for, and the wait ends as "unavailable" after TIMEOUT_MS.
    val attempt = controller.state.attempt
    LaunchedEffect(attempt) {
        if (controller.state.phase != MyLocationPhase.LOCATING) return@LaunchedEffect
        controller.requestCurrent()
        delay(MyLocation.TIMEOUT_MS)
        controller.state = MyLocation.timeout(controller.state, attempt)
    }
    LaunchedEffect(controller.state.phase) {
        if (controller.state.phase == MyLocationPhase.UNAVAILABLE) {
            delay(UNAVAILABLE_SHOWN_MS)
            controller.dismiss()
        }
    }
    return controller
}

/** The round crosshair button: a spinner while the first fix is awaited, brand-tinted while the map is on the user. */
@Composable
fun MyLocationButton(
    controller: MyLocationController,
    modifier: Modifier = Modifier,
    /** Runs before the tap is handled (the home marks that the fix should also fill "Qayerdan"). */
    onTap: () -> Unit = {},
    /** Something else waits on the fix (the place being built from it): the spinner stays. */
    loading: Boolean = false,
) {
    val phase = controller.state.phase
    val locating = phase == MyLocationPhase.LOCATING || loading
    val label = if (locating) "${t(R.string.client_map_myLocation)}, ${t(R.string.client_map_locating)}" else t(R.string.client_map_myLocation)
    RoundIconButton(
        ElchiIcon.LOCATE,
        label,
        {
            onTap()
            controller.tap()
        },
        modifier,
        tint = if (phase == MyLocationPhase.CENTRED) Elchi.colors.brand else null,
        loading = locating,
    )
}

/** "Denied" (with the app's settings) or "unavailable", floating under the top bar. */
@Composable
fun MyLocationBanner(controller: MyLocationController, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    when (controller.state.phase) {
        MyLocationPhase.DENIED -> MapBanner(t(R.string.client_map_locationDenied), t(R.string.clientProfile_settings), { openAppSettings(context) }, controller::dismiss, modifier)
        MyLocationPhase.UNAVAILABLE -> MapBanner(t(R.string.client_map_locationUnavailable), null, {}, controller::dismiss, modifier)
        else -> Unit
    }
}

@Composable
private fun MapBanner(text: String, action: String?, onAction: () -> Unit, onClose: () -> Unit, modifier: Modifier) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(16.dp)
    Row(
        modifier
            .fillMaxWidth()
            .shadow(12.dp, shape, ambientColor = c.shadow, spotColor = c.shadow)
            .clip(shape)
            .background(c.card)
            .semantics { liveRegion = LiveRegionMode.Polite }
            .padding(start = 14.dp, top = 12.dp, bottom = 12.dp, end = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        ElchiIconView(ElchiIcon.ALERT, c.tone(Tone.WARN).fg, Modifier.padding(top = 1.dp), size = 18.dp)
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(text, style = Elchi.type.label.copy(fontWeight = FontWeight.Normal, lineHeight = Elchi.type.secondary.lineHeight), color = c.text)
            if (action != null) {
                Text(
                    action,
                    Modifier.clip(RoundedCornerShape(8.dp)).clickable(role = Role.Button, onClick = onAction).padding(vertical = 6.dp),
                    style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold),
                    color = c.accentText,
                )
            }
        }
        val close = t(R.string.common_close)
        Box(
            Modifier.size(40.dp).clip(CircleShape).clickable(role = Role.Button, onClick = onClose).semantics { contentDescription = close },
            contentAlignment = Alignment.Center,
        ) { ElchiIconView(ElchiIcon.X, c.muted, size = 18.dp) }
    }
}

private fun openAppSettings(context: Context) {
    runCatching {
        context.startActivity(
            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", context.packageName, null))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    }
}
