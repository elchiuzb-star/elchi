package uz.elchi.app.session

/** What a failed token refresh means for the person on this phone. */
enum class RefreshFailure {
    /** Nothing reached the server, or the server itself failed: keep the session, the next call tries again. */
    KEEP_SESSION,

    /** The server refused the refresh token (revoked, expired, garbage) or the account: sign in again. */
    EXPIRED,
}

object SessionRules {
    /** The refusals the server names for "this login is over" (401) and "this account may not continue" (403). */
    val RELOGIN_CODES = setOf("INVALID_TOKEN", "REFRESH_TOKEN_REVOKED", "TOKEN_EXPIRED", "UNAUTHORIZED", "USER_BLOCKED", "USER_INACTIVE")

    /**
     * [status] 0 is "no answer" (offline, timeout). A 5xx is the server's own trouble and says nothing about the
     * token. Every other refusal of `POST /auth/refresh` means the stored refresh token cannot be used again.
     */
    fun refreshFailure(status: Int, code: String): RefreshFailure = when {
        code in RELOGIN_CODES -> RefreshFailure.EXPIRED
        status == 0 || status >= 500 -> RefreshFailure.KEEP_SESSION
        else -> RefreshFailure.EXPIRED
    }
}
