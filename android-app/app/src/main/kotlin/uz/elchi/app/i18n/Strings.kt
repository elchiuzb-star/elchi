package uz.elchi.app.i18n

import android.content.Context
import android.content.res.Configuration
import androidx.annotation.StringRes
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import uz.elchi.app.i18n.generated.StringKeys
import java.util.Locale

/**
 * The two app languages. Uzbek is the product's language and the fallback (values/ is uz); strings come from
 * the shared web dictionary via scripts/gen_native_strings.mjs.
 */
enum class AppLocale(val tag: String, val label: String) {
    UZ("uz", "O'zbekcha"),
    RU("ru", "Русский"),
}

/** Holds the chosen language; the choice survives restarts. The UI re-renders through [state]. */
class LocaleStore(context: Context) {
    private val prefs = context.getSharedPreferences("elchi.settings", Context.MODE_PRIVATE)
    private val _state = MutableStateFlow(AppLocale.entries.firstOrNull { it.tag == prefs.getString(KEY, null) } ?: AppLocale.UZ)
    val state: StateFlow<AppLocale> = _state.asStateFlow()

    fun set(locale: AppLocale) {
        prefs.edit().putString(KEY, locale.tag).apply()
        _state.value = locale
    }

    private companion object {
        const val KEY = "locale"
    }
}

/** A context whose resources speak [locale] - provided as LocalContext so every `stringResource` follows it. */
fun Context.withLocale(locale: AppLocale): Context {
    val config = Configuration(resources.configuration).apply { setLocale(Locale.forLanguageTag(locale.tag)) }
    return createConfigurationContext(config)
}

/** Fills `{name}` placeholders. */
fun fill(template: String, values: Array<out Pair<String, Any>>): String =
    values.fold(template) { text, (name, value) -> text.replace("{$name}", value.toString()) }

/** The sentence for a string resource, in the active language, with `{name}` placeholders filled. */
@Composable
fun t(@StringRes id: Int, vararg values: Pair<String, Any>): String = fill(stringResource(id), values)

/**
 * The same lookup for a key only known at runtime (`error.<code>`, a status). Null when the dictionary has no
 * such key, so the caller decides what an unknown value looks like.
 */
fun Context.tOrNull(key: String, vararg values: Pair<String, Any>): String? =
    StringKeys.byKey[key]?.let { fill(getString(it), values) }

@Composable
fun tOrNull(key: String, vararg values: Pair<String, Any>): String? = LocalContext.current.tOrNull(key, *values)
