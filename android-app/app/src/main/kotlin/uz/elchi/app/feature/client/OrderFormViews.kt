package uz.elchi.app.feature.client

import android.annotation.SuppressLint
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import uz.elchi.app.R
import uz.elchi.app.i18n.fill
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.ElchiIconView
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.icons.StrokeIcons
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone
import java.time.LocalDate
import java.time.LocalDateTime

// -- dictionary ---------------------------------------------------------------------------------------------------

/**
 * The app speaks Russian right now. Read from the locale-wrapped context the app provides as LocalContext (a new
 * context, so a language change recomposes): LocalConfiguration would be the phone's language, not the app's.
 */
@SuppressLint("LocalContextConfigurationRead")
@Composable
internal fun appRu(): Boolean = LocalContext.current.resources.configuration.locales[0].language == "ru"

/**
 * A design string whose key is not in the generated dictionary yet: the key wins as soon as it is generated; until
 * then the design's own uz/ru wording stands in (listed in the report as "strings still needed").
 */
@Composable
internal fun tx(key: String, uz: String, ru: String, vararg values: Pair<String, Any>): String =
    tOrNull(key, *values) ?: fill(if (appRu()) ru else uz, values)

// -- toast --------------------------------------------------------------------------------------------------------

/** The design's toast: a navy note under the status bar for 2.4 s ("Yuboruvchi: …", "Avval …"). One per flow. */
@Stable
class FlowToast {
    var text by mutableStateOf<String?>(null)
        private set
    var nonce by mutableIntStateOf(0)
        private set

    fun show(message: String) {
        text = message
        nonce++
    }

    fun hide() {
        text = null
    }
}

val LocalFlowToast = staticCompositionLocalOf { FlowToast() }

@Composable
fun FlowToastHost(toast: FlowToast, modifier: Modifier = Modifier) {
    val nonce = toast.nonce
    LaunchedEffect(nonce) {
        if (toast.text != null) {
            delay(TOAST_MS)
            toast.hide()
        }
    }
    val c = Elchi.colors
    val shape = RoundedCornerShape(16.dp)
    AnimatedVisibility(toast.text != null, modifier, enter = fadeIn(), exit = fadeOut()) {
        Text(
            toast.text.orEmpty(),
            Modifier
                .fillMaxWidth()
                .shadow(16.dp, shape, ambientColor = c.shadow, spotColor = c.shadow)
                .clip(shape)
                .background(if (c.isDark) Color(0xFF1B3563) else c.navy)
                .clickable(onClick = toast::hide)
                .semantics { liveRegion = LiveRegionMode.Polite }
                .padding(horizontal = 16.dp, vertical = 12.dp),
            style = Elchi.type.label.copy(fontSize = 13.5.sp, lineHeight = 19.sp),
            color = Color.White,
            textAlign = TextAlign.Center,
        )
    }
}

private const val TOAST_MS = 2_400L

// -- error box ----------------------------------------------------------------------------------------------------

/** The design's red box at the top of a step (or under the Taksi block): one line per missing thing. */
@Composable
internal fun ErrorList(lines: List<String>, modifier: Modifier = Modifier) {
    if (lines.isEmpty()) return
    Note(lines.joinToString("\n"), modifier, tone = Tone.ERR)
}

// -- price stepper ------------------------------------------------------------------------------------------------

/**
 * `−` [price so'm] `+` - ±5 000 so'm a tap, typed digits too (at most 8). [onSheet]: the Taksi home's grey variant
 * inside the bottom sheet; otherwise the white card of the route step.
 */
@Composable
internal fun PriceStepper(digits: String, onDigits: (String) -> Unit, error: Boolean, onSheet: Boolean, modifier: Modifier = Modifier) {
    val c = Elchi.colors
    val err = c.tone(Tone.ERR)
    val shape = RoundedCornerShape(18.dp)
    val price = digits.toLongOrNull() ?: 0L
    val decLabel = t(R.string.client_order_priceDec)
    val incLabel = t(R.string.client_order_priceInc)
    Row(
        modifier
            .fillMaxWidth()
            .height(if (onSheet) 56.dp else 60.dp)
            .then(if (onSheet) Modifier else Modifier.shadow(12.dp, shape, ambientColor = c.shadow, spotColor = c.shadow))
            .clip(shape)
            .background(if (onSheet) sheetWell() else c.card)
            .then(if (error) Modifier.border(1.5.dp, err.fg, shape) else Modifier)
            .padding(horizontal = if (onSheet) 5.dp else 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        val btn = if (onSheet) 46.dp else 48.dp
        StepButton("−", decLabel, btn, bg = if (onSheet) c.card else if (price > 0) c.field else sheetWell(), fg = if (price > 0) c.text else c.placeholder.copy(alpha = 0.6f)) {
            onDigits(ParcelRules.stepPrice(digits, -1))
        }
        val priceLabel = t(R.string.common_price)
        Row(Modifier.weight(1f), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
            val style = Elchi.type.title.copy(fontSize = if (onSheet) 21.sp else 22.sp, lineHeight = 28.sp, fontWeight = FontWeight.SemiBold, textAlign = TextAlign.Center, color = c.text)
            BasicTextField(
                value = digits,
                onValueChange = { onDigits(ParcelRules.cleanPrice(it)) },
                singleLine = true,
                textStyle = style,
                cursorBrush = SolidColor(c.brand),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Done),
                visualTransformation = ThousandsTransformation,
                modifier = Modifier.weight(1f).semantics { contentDescription = priceLabel },
                decorationBox = { inner ->
                    Box(contentAlignment = Alignment.Center) {
                        if (digits.isEmpty()) Text("0", style = style.copy(color = c.placeholder))
                        inner()
                    }
                },
            )
            Text(" ${t(R.string.common_soum)}", style = Elchi.type.secondary, color = c.muted, maxLines = 1)
        }
        StepButton("+", incLabel, btn, bg = c.brand, fg = c.onBrand) { onDigits(ParcelRules.stepPrice(digits, +1)) }
    }
}

@Composable
private fun StepButton(sign: String, label: String, size: Dp, bg: Color, fg: Color, onClick: () -> Unit) {
    Box(
        Modifier
            .size(size)
            .clip(RoundedCornerShape(14.dp))
            .background(bg)
            .clickable(role = Role.Button, onClick = onClick)
            .semantics { contentDescription = label },
        contentAlignment = Alignment.Center,
    ) { Text(sign, style = Elchi.type.title.copy(fontSize = 24.sp, lineHeight = 26.sp), color = fg) }
}

/** The grey well inside the white sheet (design #F3F5F8); on dark the field colour. */
@Composable
internal fun sheetWell(): Color = if (Elchi.colors.isDark) Elchi.colors.field else Elchi.colors.page

// -- departure window tiles ---------------------------------------------------------------------------------------

/**
 * `09:00 Ertaga, 28 sen → 18:00 Ertaga, 28 sen`: the two edges of the departure window as tiles; a tap opens the
 * window sheet on that edge. [onSheet]: the Taksi home's grey well; otherwise the white card of the route step.
 */
@Composable
internal fun WindowTiles(
    start: LocalDateTime?,
    end: LocalDateTime?,
    onEdge: (WindowEdge) -> Unit,
    startError: Boolean,
    endError: Boolean,
    onSheet: Boolean,
    modifier: Modifier = Modifier,
) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(16.dp)
    Row(
        modifier
            .fillMaxWidth()
            .then(if (onSheet) Modifier else Modifier.shadow(10.dp, shape, ambientColor = c.shadow, spotColor = c.shadow))
            .clip(shape)
            .background(if (onSheet) sheetWell() else c.card)
            .padding(4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        WindowTile(start, t(R.string.client_order_windowStartEmpty), t(R.string.client_order_windowStartShort), startError, Modifier.weight(1f)) { onEdge(WindowEdge.START) }
        Text("→", Modifier.padding(horizontal = 2.dp), style = Elchi.type.secondary, color = c.placeholder)
        WindowTile(end, t(R.string.client_order_windowEndEmpty), t(R.string.client_order_windowEndShort), endError, Modifier.weight(1f)) { onEdge(WindowEdge.END) }
    }
}

@Composable
private fun WindowTile(value: LocalDateTime?, empty: String, label: String, error: Boolean, modifier: Modifier, onClick: () -> Unit) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(12.dp)
    val date = value?.let { tileDate(it.toLocalDate()) }
    val time = value?.let { "%02d:%02d".format(it.hour, it.minute) }
    Row(
        modifier
            .height(44.dp)
            .clip(shape)
            .border(2.dp, if (error) c.tone(Tone.ERR).fg else Color.Transparent, shape)
            .clickable(role = Role.Button, onClick = onClick)
            .semantics { contentDescription = "$label: ${listOfNotNull(time, date).joinToString(", ").ifEmpty { empty }}" }
            .padding(horizontal = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(time ?: "--:--", style = Elchi.type.bodyStrong.copy(fontFeatureSettings = "tnum"), color = if (value != null) c.text else c.placeholder, maxLines = 1)
        Text(date ?: empty, style = Elchi.type.caption, color = if (value != null) c.accentText else c.placeholder, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

/** "28 sen" today, "Ertaga, 28 sen", "Pa, 1 okt" - the tile's date. */
@Composable
private fun tileDate(date: LocalDate): String {
    val today = LocalDate.now(ParcelRules.TASHKENT)
    val names = windowNames()
    val dayMonth = "${date.dayOfMonth} ${names.monthShort(date.monthValue)}"
    return when (date) {
        today -> dayMonth
        today.plusDays(1) -> "${t(R.string.driver_feed_dateTomorrow)}, $dayMonth"
        else -> "${names.weekdayShort(date.dayOfWeek)}, $dayMonth"
    }
}

/** "Oyna: 9 soat · Haydovchilar shu oraliqda jo'nashni taklif qiladi." (the length only for a valid window). */
@Composable
internal fun windowHint(draft: ParcelDraft): String {
    val base = t(R.string.routeSummary_windowHint)
    val minutes = ParcelRules.windowMinutes(draft) ?: return base
    val hours = minutes / 60
    val rest = minutes % 60
    val length = when {
        hours > 0 && rest > 0 -> t(R.string.app_duration_hoursMinutes, "hours" to hours, "minutes" to rest)
        hours > 0 -> t(R.string.app_duration_hours, "hours" to hours)
        else -> t(R.string.app_duration_minutes, "minutes" to rest)
    }
    return "${t(R.string.client_order_windowLength, "length" to length)} · $base"
}

// -- seats (Taksi) ------------------------------------------------------------------------------------------------

/** "Necha kishi" + 1 / 2 / 3 / Butun salon; the value on the right ("Tanlang", "2 kishi", "Butun salon"). */
@Composable
internal fun SeatCountPicker(count: Int, onCount: (Int) -> Unit, error: Boolean) {
    val c = Elchi.colors
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(t(R.string.seatPicker_howMany), Modifier.weight(1f), style = Elchi.type.label, color = c.text)
            Text(seatValue(count), style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold), color = c.accentText)
        }
        val groupShape = RoundedCornerShape(18.dp)
        Row(
            Modifier.fillMaxWidth().then(if (error) Modifier.border(1.5.dp, c.tone(Tone.ERR).fg, groupShape) else Modifier),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            TaxiRules.COUNT_CHOICES.forEach { n ->
                val on = count == n
                val whole = n == TaxiRules.WHOLE_CABIN
                val shape = RoundedCornerShape(14.dp)
                Box(
                    Modifier
                        .weight(if (whole) 1.6f else 1f)
                        .height(46.dp)
                        .clip(shape)
                        .background(if (on) c.brand else c.card)
                        .then(if (on) Modifier else Modifier.border(1.5.dp, c.outline, shape))
                        .selectable(on, role = Role.RadioButton) { onCount(n) },
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        if (whole) t(R.string.client_taxi_wholeCabin) else n.toString(),
                        Modifier.padding(horizontal = 6.dp),
                        style = Elchi.type.bodyStrong.copy(fontSize = if (whole) 14.sp else 18.sp),
                        color = if (on) c.onBrand else c.text,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
    }
}

@Composable
private fun seatValue(count: Int): String = when {
    count <= 0 -> t(R.string.client_order_choose)
    count >= TaxiRules.WHOLE_CABIN -> t(R.string.client_taxi_wholeCabin)
    else -> t(R.string.orderForm_review_peopleCount, "count" to count)
}

/** "Jami · 2 kishi" / "Jami · butun salon" with the total on the right (design's blue bar). */
@Composable
internal fun TotalBar(draft: ParcelDraft) {
    val c = Elchi.colors
    val count = TaxiRules.seatCount(draft)
    val who = if (count >= TaxiRules.WHOLE_CABIN) t(R.string.client_taxi_wholeCabinLower) else t(R.string.orderForm_review_peopleCount, "count" to count.coerceAtLeast(1))
    val minor = ParcelRules.soumToMinor(draft.priceDigits)
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(c.highlight).padding(horizontal = 14.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(t(R.string.client_order_totalFor, "who" to who), Modifier.weight(1f), style = Elchi.type.label.copy(fontWeight = FontWeight.Normal), color = c.softText)
        Text(minor?.let { soum(TaxiRules.totalMinor(it, TaxiRules.billedSeats(draft))) } ?: t(R.string.common_dash), style = Elchi.type.section.copy(fontSize = 18.sp, fontWeight = FontWeight.SemiBold), color = c.text)
    }
}

// -- review -------------------------------------------------------------------------------------------------------

/** A review row: key, value, detail, and the design's round pencil when the row can be edited. */
@Composable
internal fun ReviewRow(key: String, value: String, detail: String? = null, first: Boolean = false, muted: Boolean = false, onEdit: (() -> Unit)? = null) {
    val c = Elchi.colors
    val editLabel = t(R.string.listingOwner_edit)
    Column {
        if (!first) Box(Modifier.fillMaxWidth().height(1.dp).background(c.field))
        Row(Modifier.padding(vertical = 9.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(key, style = Elchi.type.caption, color = c.muted)
                Text(value.ifBlank { t(R.string.common_dash) }, style = Elchi.type.secondary.copy(fontWeight = FontWeight.Medium, lineHeight = 19.sp), color = if (muted) c.placeholder else c.text)
                if (!detail.isNullOrBlank()) Text(detail, style = Elchi.type.caption, color = c.muted)
            }
            if (onEdit != null) {
                Box(
                    Modifier.size(44.dp).clip(CircleShape).clickable(role = Role.Button, onClick = onEdit).semantics { contentDescription = "$editLabel: $key" },
                    contentAlignment = Alignment.Center,
                ) {
                    Box(Modifier.size(32.dp).clip(CircleShape).background(c.field), contentAlignment = Alignment.Center) {
                        Icon(StrokeIcons.Edit, null, Modifier.size(14.dp), tint = c.text)
                    }
                }
            }
        }
    }
}

// -- contact card -------------------------------------------------------------------------------------------------

/** "AK" for "Aziza Karimova". */
internal fun initials(name: String): String =
    name.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }.take(2).joinToString("") { it.first().uppercase() }

/** Sender / receiver as a card (design `cS`/`cR`): avatar, name, number, "O'zgartirish" - or the empty prompt. */
@Composable
internal fun ContactCard(label: String, name: String, digits: String, error: Boolean, onClick: () -> Unit) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(18.dp)
    val filled = ParcelRules.nameValid(name) && ParcelRules.phoneValid(digits)
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(label, style = Elchi.type.label, color = c.text)
        Row(
            Modifier
                .fillMaxWidth()
                .heightIn(min = 62.dp)
                .shadow(10.dp, shape, ambientColor = c.shadow, spotColor = c.shadow)
                .clip(shape)
                .background(c.card)
                .then(if (error) Modifier.border(1.5.dp, c.tone(Tone.ERR).fg, shape) else Modifier)
                .clickable(role = Role.Button, onClick = onClick)
                .padding(horizontal = 14.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Box(Modifier.size(40.dp).clip(CircleShape).background(if (filled) c.soft else avatarEmpty()), contentAlignment = Alignment.Center) {
                if (filled) Text(initials(name), style = Elchi.type.secondary.copy(fontWeight = FontWeight.SemiBold), color = c.softText)
                else ElchiIconView(ElchiIcon.USERS, c.accentText, size = 20.dp)
            }
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
                Text(
                    if (filled) name.trim() else t(R.string.client_order_contactEmpty),
                    style = Elchi.type.bodyStrong,
                    color = if (filled) c.text else c.placeholder,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    if (filled) "+998 ${ParcelRules.groupPhone(digits)}" else t(R.string.client_order_contactEmptyHint),
                    style = Elchi.type.caption.copy(fontSize = 12.5.sp, fontFamily = if (filled) FontFamily.Monospace else Elchi.type.caption.fontFamily),
                    color = c.muted,
                )
            }
            Text(
                if (filled) t(R.string.app_route_change) else t(R.string.client_order_choosePick),
                style = Elchi.type.label.copy(fontSize = 12.5.sp, fontWeight = FontWeight.SemiBold),
                color = c.accentText,
            )
        }
    }
}

@Composable
internal fun avatarEmpty(): Color = if (Elchi.colors.isDark) Elchi.colors.field else Color(0xFFEEF4FA)

// -- sheets -------------------------------------------------------------------------------------------------------

/**
 * The design's bottom sheet: handle, title (with an optional pill on the right), content. The sheet is a window of
 * its own whose context speaks the phone's language - the app's context and configuration are provided again so
 * every `t()` inside speaks the app's.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun FormSheet(title: String?, onDismiss: () -> Unit, badge: String? = null, scrollable: Boolean = true, content: @Composable ColumnScope.() -> Unit) {
    val c = Elchi.colors
    val context = LocalContext.current
    val configuration = LocalConfiguration.current
    val toast = LocalFlowToast.current
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        containerColor = c.card,
        shape = RoundedCornerShape(topStart = 32.dp, topEnd = 32.dp),
        dragHandle = { Box(Modifier.padding(top = 14.dp, bottom = 4.dp).size(44.dp, 5.dp).clip(CircleShape).background(c.outline)) },
    ) {
        CompositionLocalProvider(LocalContext provides context, LocalConfiguration provides configuration, LocalFlowToast provides toast) {
            Column(
                Modifier
                    .fillMaxWidth()
                    .then(if (scrollable) Modifier.verticalScroll(rememberScrollState()) else Modifier)
                    .padding(horizontal = 16.dp)
                    .padding(top = 6.dp, bottom = 20.dp)
                    .navigationBarsPadding(),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                if (title != null) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(title, Modifier.weight(1f), style = Elchi.type.section.copy(fontSize = 19.sp, lineHeight = 25.sp), color = c.text)
                    if (badge != null) {
                        Text(badge, Modifier.clip(CircleShape).background(c.soft).padding(horizontal = 10.dp, vertical = 4.dp), style = Elchi.type.badge, color = c.accentText, maxLines = 1)
                    }
                }
                content()
            }
        }
    }
}

/** A choice row inside a sheet (design `selOpts`): optional icon tile, title, one line, radio circle. */
@Composable
internal fun SheetOption(title: String, selected: Boolean, onClick: () -> Unit, detail: String? = null, icon: ElchiIcon? = null) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(16.dp)
    Row(
        Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(if (selected) c.highlight else c.card)
            .border(if (selected) 2.dp else 1.dp, if (selected) c.brand else c.line, shape)
            .selectable(selected, role = Role.RadioButton, onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (icon != null) {
            Box(Modifier.size(38.dp).clip(RoundedCornerShape(12.dp)).background(c.card).border(1.dp, c.line, RoundedCornerShape(12.dp)), contentAlignment = Alignment.Center) {
                ElchiIconView(icon, c.accentText)
            }
        }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
            Text(title, style = Elchi.type.secondary.copy(fontSize = 14.5.sp, fontWeight = FontWeight.SemiBold), color = c.text)
            if (detail != null) Text(detail, style = Elchi.type.caption, color = c.muted)
        }
        Box(Modifier.size(20.dp).clip(CircleShape).border(if (selected) 6.dp else 2.dp, if (selected) c.brand else c.outline, CircleShape))
    }
}
