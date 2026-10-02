package uz.elchi.app.ui.map

import android.annotation.SuppressLint
import android.content.Context
import android.location.Location
import android.location.LocationManager
import android.os.Looper
import androidx.core.location.LocationManagerCompat
import com.google.android.gms.location.CurrentLocationRequest
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import com.google.android.gms.tasks.CancellationTokenSource
import uz.elchi.app.gps.AndroidTrackerPlatform
import uz.elchi.app.gps.LocationAccess

/**
 * The phone's position for the client map's "you are here" dot: fused location on the device only - nothing here
 * is sent anywhere, and it is independent of the driver's GPS publishing (its own client and callback). Updates run
 * only between [start] and [stop] (the home is visible), at a balanced, battery-friendly priority; a tap asks for
 * one precise [current] fix on top (and so does [start], once, for the first dot).
 */
class UserLocationSource(context: Context) {
    private val app = context.applicationContext
    private val fused by lazy { LocationServices.getFusedLocationProviderClient(app) }
    private var callback: LocationCallback? = null
    private var cancel: CancellationTokenSource? = null

    fun granted(): Boolean = AndroidTrackerPlatform.access(app) != LocationAccess.NONE

    /** The phone's location switch (off: no fix will come, say so at once). */
    fun locationOn(): Boolean =
        app.getSystemService(LocationManager::class.java)?.let(LocationManagerCompat::isLocationEnabled) ?: false

    @SuppressLint("MissingPermission") // granted() first; a permission revoked meanwhile throws, caught
    fun start(onFix: (UserFix) -> Unit) {
        stop()
        if (!granted()) return
        // The cached position draws the dot at once; one short precise request covers a phone whose cache is empty
        // and whose balanced updates have no network source (no Wi-Fi/cell location) - then GPS idles again.
        runCatching { fused.lastLocation.addOnSuccessListener { it?.let { location -> onFix(fix(location)) } } }
        current(FIRST_FIX_MS, onFix)
        val request = LocationRequest.Builder(Priority.PRIORITY_BALANCED_POWER_ACCURACY, INTERVAL_MS)
            .setMinUpdateIntervalMillis(INTERVAL_MS / 2)
            .build()
        val cb = object : LocationCallback() {
            override fun onLocationResult(result: LocationResult) {
                result.lastLocation?.let { onFix(fix(it)) }
            }
        }
        callback = cb
        runCatching { fused.requestLocationUpdates(request, cb, Looper.getMainLooper()) }.onFailure { callback = null }
    }

    /** One fresh, precise fix after a tap (nothing within [durationMs]: nothing is called). */
    @SuppressLint("MissingPermission")
    fun current(durationMs: Long, onFix: (UserFix) -> Unit) {
        if (!granted()) return
        cancel?.cancel()
        val token = CancellationTokenSource().also { cancel = it }
        val request = CurrentLocationRequest.Builder()
            .setPriority(Priority.PRIORITY_HIGH_ACCURACY)
            .setMaxUpdateAgeMillis(MyLocation.FRESH_MS)
            .setDurationMillis(durationMs)
            .build()
        runCatching { fused.getCurrentLocation(request, token.token).addOnSuccessListener { it?.let { location -> onFix(fix(location)) } } }
    }

    fun stop() {
        callback?.let { runCatching { fused.removeLocationUpdates(it) } }
        callback = null
        cancel?.cancel()
        cancel = null
    }

    private fun fix(location: Location) = UserFix(
        GeoPoint(location.latitude, location.longitude),
        if (location.hasAccuracy()) location.accuracy else 0f,
        location.time,
    )

    private companion object {
        const val INTERVAL_MS = 10_000L
        const val FIRST_FIX_MS = 15_000L
    }
}
