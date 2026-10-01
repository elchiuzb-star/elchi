package uz.elchi.app.push

import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import uz.elchi.app.ElchiApplication

/**
 * FCM entry point. Messages are data-only (ADR-0022), so [onMessageReceived] runs in every app state (foreground,
 * background, killed) and the app builds the notification itself.
 */
class ElchiMessagingService : FirebaseMessagingService() {
    private val container get() = (application as ElchiApplication).container

    override fun onNewToken(token: String) {
        container.push.onNewToken(token)
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val parsed = PushRules.parse(message.data) ?: return
        // Signed out (or the session ended) on this phone: the message is not for whoever holds it now.
        val session = container.sessions.current() ?: return
        container.pushNotifier.show(parsed, session.user.mobileRole)
        container.push.notifyReceived()
    }
}
