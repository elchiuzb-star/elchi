package uz.elchi.app.gps

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.Application
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.location.Location
import android.net.ConnectivityManager
import android.net.Network
import android.os.BatteryManager
import android.os.Build
import android.os.Bundle
import android.os.Looper
import android.util.AtomicFile
import androidx.core.content.ContextCompat
import androidx.core.content.edit
import com.google.android.gms.common.ConnectionResult
import com.google.android.gms.common.GoogleApiAvailability
import com.google.android.gms.location.CurrentLocationRequest
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import uz.elchi.app.BuildConfig
import uz.elchi.app.api.generated.ClientPlatform
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.api.generated.PointsBatchAck
import uz.elchi.app.api.generated.PointsBatchIn
import uz.elchi.app.api.generated.TrackingPointIn
import uz.elchi.app.api.generated.TrackingSessionCreate
import uz.elchi.app.api.generated.TrackingSessionDTO
import java.io.File
import java.util.UUID

/** K1-K3 through the generated client; K1 and K3 carry an Idempotency-Key each (one per attempt). */
class ElchiTrackerApi(private val api: ElchiApi) : TrackerApi {
    override suspend fun create(tripId: String, deviceId: String, appVersion: String): TrackingSessionDTO =
        api.createTrackingSession(
            TrackingSessionCreate(appVersion = appVersion, deviceId = deviceId, platform = ClientPlatform.ANDROID, tripId = tripId),
            UUID.randomUUID().toString(),
        ).data

    override suspend fun send(sessionId: String, points: List<TrackingPointIn>): PointsBatchAck =
        api.ingestTrackingPoints(sessionId, PointsBatchIn(points)).data

    override suspend fun close(sessionId: String) {
        api.closeTrackingSession(sessionId, UUID.randomUUID().toString())
    }
}

/** The outbox in the app's private files (`files/gps/outbox.json`), replaced atomically on every write. */
class FileTrackerStorage(context: Context) : TrackerStorage {
    private val file = AtomicFile(File(File(context.filesDir, "gps").apply { mkdirs() }, "outbox.json"))

    override fun read(): String? = if (file.baseFile.exists()) file.readFully().toString(Charsets.UTF_8) else null

    override fun write(value: String) {
        val out = file.startWrite()
        try {
            out.write(value.toByteArray(Charsets.UTF_8))
            file.finishWrite(out)
        } catch (e: Exception) {
            file.failWrite(out)
            throw e
        }
    }

    override fun clear() = file.delete()
}

/** Whether any activity of the app is started (no lifecycle-process dependency: a counter of started activities). */
class AppVisibility : Application.ActivityLifecycleCallbacks {
    @Volatile private var started = 0
    val inBackground: Boolean get() = started == 0

    override fun onActivityStarted(activity: Activity) {
        started += 1
    }

    override fun onActivityStopped(activity: Activity) {
        started = (started - 1).coerceAtLeast(0)
    }

    override fun onActivityCreated(activity: Activity, savedInstanceState: Bundle?) = Unit
    override fun onActivityResumed(activity: Activity) = Unit
    override fun onActivityPaused(activity: Activity) = Unit
    override fun onActivitySaveInstanceState(activity: Activity, outState: Bundle) = Unit
    override fun onActivityDestroyed(activity: Activity) = Unit
}

/**
 * The phone side of the tracker: FusedLocationProviderClient for the positions (requested here, so they also come
 * when the service could not start), the location foreground service for the background, battery, connectivity.
 */
class AndroidTrackerPlatform(context: Context, private val visibility: AppVisibility) : TrackerPlatform {
    private val app = context.applicationContext
    private val fused by lazy { LocationServices.getFusedLocationProviderClient(app) }
    private val prefs = app.getSharedPreferences("elchi.tracking", Context.MODE_PRIVATE)
    private var callback: LocationCallback? = null

    override val appVersion: String = "android/${BuildConfig.VERSION_NAME}"

    override fun available(): Boolean =
        GoogleApiAvailability.getInstance().isGooglePlayServicesAvailable(app) == ConnectionResult.SUCCESS

    override fun access(): LocationAccess = access(app)

    @SuppressLint("MissingPermission") // access() is checked first; a revoked permission throws SecurityException
    override fun startUpdates(intervalMs: Long, onFix: (GeoFix) -> Unit) {
        stopUpdates()
        if (access() == LocationAccess.NONE) return
        val request = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, intervalMs)
            .setMinUpdateIntervalMillis(intervalMs / 2)
            .setWaitForAccurateLocation(false)
            .build()
        val cb = object : LocationCallback() {
            override fun onLocationResult(result: LocationResult) {
                result.locations.forEach { location -> fix(location)?.let(onFix) }
            }
        }
        callback = cb
        runCatching { fused.requestLocationUpdates(request, cb, Looper.getMainLooper()) }
    }

    override fun stopUpdates() {
        callback?.let { runCatching { fused.removeLocationUpdates(it) } }
        callback = null
    }

    @SuppressLint("MissingPermission")
    override fun requestCurrent(onDone: (GeoFix?) -> Unit) {
        if (access() == LocationAccess.NONE) return onDone(null)
        val request = CurrentLocationRequest.Builder().setPriority(Priority.PRIORITY_HIGH_ACCURACY).setMaxUpdateAgeMillis(0).setDurationMillis(20_000).build()
        runCatching {
            fused.getCurrentLocation(request, null)
                .addOnSuccessListener { location -> onDone(location?.let(::fix)) }
                .addOnFailureListener { onDone(null) }
        }.onFailure { onDone(null) }
    }

    override fun battery(): BatteryState? {
        val intent = app.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED)) ?: return null
        val level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
        if (level < 0 || scale <= 0) return null
        val status = intent.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
        val charging = status == BatteryManager.BATTERY_STATUS_CHARGING || status == BatteryManager.BATTERY_STATUS_FULL
        return BatteryState(level * 100 / scale, charging)
    }

    override fun inBackground(): Boolean = visibility.inBackground

    override fun startService(tripId: String) = LocationService.start(app, tripId)

    override fun stopService() = LocationService.stop(app)

    override fun onOnline(listener: () -> Unit): () -> Unit {
        val manager = app.getSystemService(ConnectivityManager::class.java) ?: return {}
        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) = listener()
        }
        return runCatching {
            manager.registerDefaultNetworkCallback(cb)
            val unsubscribe: () -> Unit = { runCatching { manager.unregisterNetworkCallback(cb) } }
            unsubscribe
        }.getOrDefault {}
    }

    /** A random, non-identifying id of this install (K1 `device_id`); not a secret, not a fingerprint. */
    override fun deviceId(): String = prefs.getString(DEVICE_ID, null) ?: "android-${UUID.randomUUID()}".also { id -> prefs.edit { putString(DEVICE_ID, id) } }

    companion object {
        private const val DEVICE_ID = "device_id"

        fun access(context: Context): LocationAccess = when {
            granted(context, Manifest.permission.ACCESS_FINE_LOCATION) -> LocationAccess.PRECISE
            granted(context, Manifest.permission.ACCESS_COARSE_LOCATION) -> LocationAccess.APPROXIMATE
            else -> LocationAccess.NONE
        }

        private fun granted(context: Context, permission: String) =
            ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED

        /** A platform fix as the outbox reads it; `is_mock` is the platform's own flag (Q149). */
        fun fix(location: Location): GeoFix? {
            if (!location.hasAccuracy()) return null
            val mock = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) location.isMock else @Suppress("DEPRECATION") location.isFromMockProvider
            return GeoFix(
                lat = location.latitude,
                lng = location.longitude,
                accuracy = location.accuracy.toDouble(),
                speed = if (location.hasSpeed()) location.speed.toDouble() else null,
                heading = if (location.hasBearing()) location.bearing.toDouble() else null,
                timeMs = location.time,
                isMock = mock,
            )
        }
    }
}
