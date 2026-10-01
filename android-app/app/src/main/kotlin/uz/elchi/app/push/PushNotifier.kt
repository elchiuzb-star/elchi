package uz.elchi.app.push

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.core.net.toUri
import uz.elchi.app.MainActivity
import uz.elchi.app.R
import uz.elchi.app.i18n.AppLocale
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.i18n.withLocale
import uz.elchi.app.session.MobileRole

/**
 * Builds the notification for a data-only push (ADR-0022: the server sends keys, never text). Words come from
 * the app's dictionary in the app's chosen language; a tap opens [MainActivity] with an `elchi://` link
 * ([PushRules.link]), the same router as any other link.
 */
class PushNotifier(context: Context, private val locale: () -> AppLocale) {
    private val app = context.applicationContext

    /** The one channel ("Bildirishnomalar" / "Уведомления"); re-created to follow a language change. */
    fun ensureChannel() {
        val words = app.withLocale(locale())
        val channel = NotificationChannel(CHANNEL_ID, words.getString(R.string.notifications_title), NotificationManager.IMPORTANCE_HIGH)
        app.getSystemService(NotificationManager::class.java)?.createNotificationChannel(channel)
    }

    fun show(message: PushMessage, role: MobileRole?) {
        if (!canPost()) return
        ensureChannel()
        val words = app.withLocale(locale())
        val title = PushRules.firstKnown(PushRules.titleKeys(message)) { words.tOrNull(it) } ?: words.getString(R.string.notification_fallback_title)
        val body = PushRules.firstKnown(PushRules.bodyKeys(message)) { words.tOrNull(it) } ?: words.getString(R.string.push_body_generic)
        val link = PushRules.link(message, role)
        val group = PushRules.group(message)
        val tag = message.aggregateId ?: APP_TAG
        val tap = PendingIntent.getActivity(
            app,
            "$tag/${message.eventType}".hashCode(),
            Intent(Intent.ACTION_VIEW, link.toUri(), app, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val manager = NotificationManagerCompat.from(app)
        val notification = NotificationCompat.Builder(app, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_elchi)
            .setColor(BRAND)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(if (message.eventType == PushRules.CHAT_MESSAGE) NotificationCompat.CATEGORY_MESSAGE else NotificationCompat.CATEGORY_STATUS)
            .setAutoCancel(true)
            .setContentIntent(tap)
            .setGroup(group)
            .build()
        // One notification per event kind and thing: a second chat message on the same thread replaces the first.
        post(manager, tag, message.eventType.hashCode(), notification)
        summarize(manager, group, tag, title, tap)
    }

    /** Two or more notifications about the same thing fold under one summary (Android shows it as a bundle). */
    private fun summarize(manager: NotificationManagerCompat, group: String, tag: String, title: String, tap: PendingIntent) {
        val active = manager.activeNotifications.count { it.notification.group == group && it.id != SUMMARY_ID }
        if (active < 2) return
        val summary = NotificationCompat.Builder(app, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_elchi)
            .setColor(BRAND)
            .setContentTitle(title)
            .setGroup(group)
            .setGroupSummary(true)
            .setGroupAlertBehavior(NotificationCompat.GROUP_ALERT_CHILDREN)
            .setAutoCancel(true)
            .setContentIntent(tap)
            .build()
        post(manager, tag, SUMMARY_ID, summary)
    }

    private fun canPost(): Boolean =
        (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            ContextCompat.checkSelfPermission(app, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) &&
            NotificationManagerCompat.from(app).areNotificationsEnabled()

    private fun post(manager: NotificationManagerCompat, tag: String, id: Int, notification: android.app.Notification) {
        try {
            manager.notify(tag, id, notification)
        } catch (_: SecurityException) {
            // The permission was withdrawn between the check and the post: the inbox still has the item.
        }
    }

    companion object {
        const val CHANNEL_ID = "elchi.events"
        private const val APP_TAG = "elchi"
        private const val SUMMARY_ID = 0
        /** Elchi brand blue (`Elchi.colors.brand`). */
        private const val BRAND = 0xFF0096FF.toInt()
    }
}
