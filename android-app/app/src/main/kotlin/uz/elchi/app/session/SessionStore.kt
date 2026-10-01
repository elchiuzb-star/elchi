package uz.elchi.app.session

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import uz.elchi.app.api.ElchiJson
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** The v1 `/auth/me` user as the auth endpoints return it (v1 is hand-typed by design, ADR-0010 §5). */
@Serializable
data class AuthUser(
    val id: Long,
    val phone: String,
    @SerialName("full_name") val fullName: String? = null,
    val role: String,
    val status: String = "",
) {
    val mobileRole: MobileRole? get() = MobileRole.entries.firstOrNull { it.wire == role }
}

enum class MobileRole(val wire: String) { CLIENT("client"), DRIVER("driver") }

@Serializable
data class Session(val accessToken: String, val refreshToken: String, val user: AuthUser)

/** Where the HTTP layer reads and replaces the session (a fake in tests). */
interface SessionStorage {
    fun current(): Session?
    fun save(session: Session)
    fun clear()

    /** The server refused the refresh token: drop the session and let the app say so ("Sessiya tugadi"). */
    fun expire() = clear()
}

/** Who was signed in when the server ended the session - the sign-in screen starts from this phone number. */
data class SessionExpiry(val phone: String, val role: MobileRole?)

/**
 * The signed-in session, encrypted with an AES-GCM key that never leaves the Android Keystore. Loaded once at
 * start, then served from memory; [state] lets the UI follow sign-in, refresh and sign-out (also the HTTP
 * layer's, when a refresh is rejected).
 */
class SessionStore(context: Context) : SessionStorage {
    private val prefs = context.getSharedPreferences("elchi.session", Context.MODE_PRIVATE)
    private val _state = MutableStateFlow(load())
    val state: StateFlow<Session?> = _state.asStateFlow()

    override fun current(): Session? = _state.value

    override fun save(session: Session) {
        val plain = ElchiJson.encodeToString(Session.serializer(), session).toByteArray()
        val cipher = Cipher.getInstance(TRANSFORMATION).apply { init(Cipher.ENCRYPT_MODE, key()) }
        val sealed = cipher.iv + cipher.doFinal(plain)
        prefs.edit().putString(KEY, Base64.encodeToString(sealed, Base64.NO_WRAP)).apply()
        _state.value = session
    }

    override fun clear() {
        prefs.edit().remove(KEY).apply()
        _state.value = null
    }

    private val _expired = MutableStateFlow<SessionExpiry?>(null)

    /**
     * Set once when a refresh was refused (not offline, not a sign-out the person asked for); the app shows its
     * dialog until [dismissExpired]. In memory only: after a restart the entry flow simply starts.
     */
    val expired: StateFlow<SessionExpiry?> = _expired.asStateFlow()

    override fun expire() {
        val user = _state.value?.user ?: return
        clear()
        _expired.value = SessionExpiry(user.phone, user.mobileRole)
    }

    fun dismissExpired() {
        _expired.value = null
    }

    /**
     * Debug builds only (`MainActivity`, intent extra): both tokens become garbage, so the next call's refresh is
     * refused exactly as a revoked one would be - the way to see the session-expired dialog on demand.
     */
    fun breakTokensForTesting() {
        val session = _state.value ?: return
        save(session.copy(accessToken = "broken-access-token", refreshToken = "broken-refresh-token"))
    }

    private fun load(): Session? = runCatching {
        val sealed = Base64.decode(prefs.getString(KEY, null) ?: return null, Base64.NO_WRAP)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, sealed, 0, IV_BYTES))
        val plain = cipher.doFinal(sealed, IV_BYTES, sealed.size - IV_BYTES)
        ElchiJson.decodeFromString(Session.serializer(), String(plain))
    }.getOrElse {
        // A key lost with a restore or OS reset cannot decrypt the old blob: sign in again instead of crashing.
        prefs.edit().remove(KEY).apply()
        null
    }

    private fun key(): SecretKey {
        val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        (keyStore.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE).apply {
            init(
                KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build(),
            )
        }.generateKey()
    }

    private companion object {
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
        const val ALIAS = "elchi.session.key"
        const val KEY = "session"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV_BYTES = 12
    }
}
