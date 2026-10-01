package uz.elchi.app.push

import android.content.Context
import android.util.Log
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.edit
import com.google.android.gms.tasks.Task
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import uz.elchi.app.BuildConfig
import uz.elchi.app.api.generated.ClientPlatform
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.api.generated.PushTokenRegister
import uz.elchi.app.session.SessionStore
import java.util.UUID
import kotlin.coroutines.resume

/**
 * This phone's FCM token and its registration on the server (N2 `POST /api/v2/devices/push-token`, an upsert by
 * token; `DELETE /api/v2/devices/{id}` on sign-out). The token is kept even while signed out, so it is registered
 * right after the next sign-in. Whether notifications may be *shown* (POST_NOTIFICATIONS) does not matter here:
 * the server does not know it, and the in-app inbox works either way.
 */
class PushRegistrar(
    context: Context,
    private val api: ElchiApi,
    private val sessions: SessionStore,
    private val scope: CoroutineScope,
) {
    private val app = context.applicationContext
    private val prefs = app.getSharedPreferences("elchi.push", Context.MODE_PRIVATE)
    private val mutex = Mutex()
    private val _received = MutableSharedFlow<Unit>(extraBufferCapacity = 1, onBufferOverflow = BufferOverflow.DROP_OLDEST)

    /** A push arrived (any app state): the signed-in flow re-reads the unread dot. */
    val received: SharedFlow<Unit> = _received.asSharedFlow()

    /** Sign-in, a restart with a stored session, or another person on this phone: register when needed. */
    fun start() {
        scope.launch {
            sessions.state.map { it?.user?.id }.distinctUntilChanged().collect { userId -> if (userId != null) sync() }
        }
    }

    /** FirebaseMessagingService.onNewToken: remember it, and register it when someone is signed in. */
    fun onNewToken(token: String) {
        prefs.edit { putString(TOKEN, token) }
        scope.launch { sync() }
    }

    fun notifyReceived() {
        _received.tryEmit(Unit)
    }

    /** Sends the token when [PushRules.needsRegistration] says so. Failures are quiet: the next start tries again. */
    suspend fun sync() = mutex.withLock {
        val userId = sessions.current()?.user?.id ?: return@withLock
        val token = prefs.getString(TOKEN, null) ?: fetchToken()?.also { prefs.edit { putString(TOKEN, it) } } ?: return@withLock
        if (!PushRules.needsRegistration(saved(), token, userId, System.currentTimeMillis())) return@withLock
        try {
            val device = api.registerPushToken(
                PushTokenRegister(platform = ClientPlatform.ANDROID, tokenOrSubscription = token, appVersion = BuildConfig.VERSION_NAME),
                idempotencyKey = UUID.randomUUID().toString(),
            ).data
            // The person may have signed out while the call was on its way: then this row is not theirs to keep.
            if (sessions.current()?.user?.id == userId) {
                prefs.edit {
                    putString(REGISTERED_TOKEN, token)
                    putLong(REGISTERED_USER, userId)
                    putString(DEVICE_ID, device.id)
                    putLong(REGISTERED_AT, System.currentTimeMillis())
                }
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Log.w(TAG, "push token registration failed: ${e.javaClass.simpleName}")
        }
    }

    /**
     * Sign-out and account deletion, while the session still works: revoke this device on the server (best effort)
     * and forget it here. The FCM token itself is kept for the next sign-in.
     */
    suspend fun unregister() = mutex.withLock {
        val deviceId = prefs.getString(DEVICE_ID, null)
        if (deviceId != null && sessions.current() != null) {
            try {
                api.revokeDevice(deviceId)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                Log.w(TAG, "device revoke failed: ${e.javaClass.simpleName}")
            }
        }
        forgetRegistration()
        // What is already in the shade belonged to the person who is leaving.
        NotificationManagerCompat.from(app).cancelAll()
    }

    /** After the account is gone: also drop the FCM token, so nothing addressed to it can arrive here any more. */
    fun dropToken() {
        prefs.edit { remove(TOKEN) }
        runCatching { FirebaseMessaging.getInstance().deleteToken() }
    }

    /** Asked for POST_NOTIFICATIONS once on this install (after sign-in, on home). */
    var permissionAsked: Boolean
        get() = prefs.getBoolean(PERMISSION_ASKED, false)
        set(value) = prefs.edit { putBoolean(PERMISSION_ASKED, value) }

    private fun saved() = PushRegistration(
        token = prefs.getString(REGISTERED_TOKEN, null),
        userId = prefs.getLong(REGISTERED_USER, -1L).takeIf { it >= 0 },
        deviceId = prefs.getString(DEVICE_ID, null),
        atMillis = prefs.getLong(REGISTERED_AT, 0L),
    )

    private fun forgetRegistration() = prefs.edit {
        remove(REGISTERED_TOKEN)
        remove(REGISTERED_USER)
        remove(DEVICE_ID)
        remove(REGISTERED_AT)
    }

    private suspend fun fetchToken(): String? = try {
        FirebaseMessaging.getInstance().token.await()
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        // No Google Play services, offline at first start, ...: onNewToken or the next start brings it.
        Log.w(TAG, "FCM token unavailable: ${e.javaClass.simpleName}")
        null
    }

    private companion object {
        const val TAG = "ElchiPush"
        const val TOKEN = "token"
        const val REGISTERED_TOKEN = "registered_token"
        const val REGISTERED_USER = "registered_user"
        const val DEVICE_ID = "device_id"
        const val REGISTERED_AT = "registered_at"
        const val PERMISSION_ASKED = "permission_asked"
    }
}

/** A Play services task as a suspending call (no extra dependency for one use). */
private suspend fun <T> Task<T>.await(): T? = suspendCancellableCoroutine { cont ->
    addOnCompleteListener { task ->
        if (task.isSuccessful) cont.resume(task.result) else cont.resumeWith(Result.failure(task.exception ?: IllegalStateException("task failed")))
    }
}
