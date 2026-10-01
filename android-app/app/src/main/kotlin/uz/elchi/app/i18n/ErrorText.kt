package uz.elchi.app.i18n

import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext
import uz.elchi.app.R
import uz.elchi.app.api.ApiException

/**
 * What a person reads when a request fails: the dictionary's sentence for the server code (`error.<CODE>`), the
 * server's own message when the code is not in the dictionary yet (it at least carries the reason), and a plain
 * "no connection" when nothing came back. Never a raw code, never "try again" for a business rule.
 */
fun Context.errorText(error: Throwable): String = when {
    error is ApiException && error.code == ApiException.NETWORK -> getString(R.string.error_offline)
    error is ApiException -> tOrNull("error.${error.code}") ?: error.message.ifBlank { getString(R.string.error_fallback) }
    else -> getString(R.string.error_fallback)
}

@Composable
fun errorText(error: Throwable): String = LocalContext.current.errorText(error)
