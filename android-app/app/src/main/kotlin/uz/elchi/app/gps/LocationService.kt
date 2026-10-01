package uz.elchi.app.gps

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import androidx.core.net.toUri
import uz.elchi.app.ElchiApplication
import uz.elchi.app.MainActivity
import uz.elchi.app.R
import uz.elchi.app.i18n.withLocale

/**
 * The location foreground service (Q148 native): while a trip publishes, it keeps the process in the foreground for
 * Android, so the positions the tracker requested keep coming with the app in the background or the screen locked.
 * It does not read locations itself. The ongoing notification says what is happening (`driver.gps.*`), a tap opens the
 * trip, "To'xtatish" stops publishing (K3). Started only from the visible app (Android 14 refuses a location
 * service started from the background without the background permission, which this app does not ask for).
 */
class LocationService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val container = (application as ElchiApplication).container
        if (intent?.action == ACTION_STOP) {
            container.tracker.stop()
            stopSelfNow()
            return START_NOT_STICKY
        }
        val tripId = intent?.getStringExtra(EXTRA_TRIP) ?: container.tracker.state.value.tripId.orEmpty()
        // startForegroundService() obliges startForeground() first, whatever happens next.
        val started = runCatching {
            ServiceCompat.startForeground(
                this,
                NOTIFICATION_ID,
                notification(tripId),
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION else 0,
            )
        }
        if (started.isFailure || tripId.isEmpty() || !container.tracker.isRunning()) {
            container.tracker.setServiceRunning(false)
            stopSelfNow()
            return START_NOT_STICKY
        }
        container.tracker.setServiceRunning(true)
        // A killed process is not restarted into a half state: the app resumes publishing when it is opened again.
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        (application as ElchiApplication).container.tracker.setServiceRunning(false)
        super.onDestroy()
    }

    private fun stopSelfNow() {
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun notification(tripId: String): android.app.Notification {
        val container = (application as ElchiApplication).container
        val words = applicationContext.withLocale(container.locale.state.value)
        ensureChannel(this, words.getString(R.string.driver_gps_channelName))
        val open = PendingIntent.getActivity(
            this,
            REQUEST_OPEN,
            Intent(Intent.ACTION_VIEW, "elchi://trips/$tripId".toUri(), this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val stop = PendingIntent.getService(
            this,
            REQUEST_STOP,
            Intent(this, LocationService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_elchi)
            .setColor(BRAND)
            .setContentTitle(words.getString(R.string.driver_gps_notificationTitle))
            .setContentText(words.getString(R.string.driver_gps_notificationText))
            .setStyle(NotificationCompat.BigTextStyle().bigText(words.getString(R.string.driver_gps_notificationText)))
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_NAVIGATION)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .setContentIntent(open)
            .addAction(0, words.getString(R.string.driverTracking_stop), stop)
            .build()
    }

    companion object {
        const val CHANNEL_ID = "elchi.tracking"
        private const val NOTIFICATION_ID = 4109
        private const val REQUEST_OPEN = 4110
        private const val REQUEST_STOP = 4111
        private const val ACTION_STOP = "uz.elchi.app.gps.STOP"
        private const val EXTRA_TRIP = "trip_id"
        private const val BRAND = 0xFF0096FF.toInt()

        /** Low importance: no sound, but the ongoing row (and the status-bar icon) is always there while it runs. */
        fun ensureChannel(context: Context, name: String) {
            val channel = NotificationChannel(CHANNEL_ID, name, NotificationManager.IMPORTANCE_LOW).apply { setShowBadge(false) }
            context.getSystemService(NotificationManager::class.java)?.createNotificationChannel(channel)
        }

        fun start(context: Context, tripId: String) {
            runCatching {
                ContextCompat.startForegroundService(context, Intent(context, LocationService::class.java).putExtra(EXTRA_TRIP, tripId))
            }
        }

        fun stop(context: Context) {
            runCatching { context.stopService(Intent(context, LocationService::class.java)) }
        }
    }
}
