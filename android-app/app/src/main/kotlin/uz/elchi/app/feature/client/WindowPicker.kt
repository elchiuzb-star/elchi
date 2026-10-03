package uz.elchi.app.feature.client

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import uz.elchi.app.R
import uz.elchi.app.i18n.t
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime

/** Which edge of the departure window is being picked. */
enum class WindowEdge { START, END }

/** Why the sheet's selection cannot be taken (design `pkErr`). */
enum class WindowPickError { PAST, END_BEFORE_START }

/**
 * Day and month names for the window picker, in the design's spelling (`Ya/Du/…`, `yan/fev/…`, `Sentabr`) - Android's
 * uz CLDR data spells them differently. They come from the dictionary's comma lists (`client.order.picker.weekdays`,
 * Sunday first; `…months`; `…monthsFull`); a list of the wrong length falls back to the built-in one.
 */
data class WindowNames(val weekdays: List<String>, val months: List<String>, val monthsFull: List<String>) {
    fun weekdayShort(day: DayOfWeek): String = weekdays[day.value % 7]

    fun monthShort(month: Int): String = months[month - 1]

    fun monthFull(month: Int): String = monthsFull[month - 1]

    companion object {
        private val WEEKDAYS_UZ = listOf("Ya", "Du", "Se", "Ch", "Pa", "Ju", "Sh")
        private val WEEKDAYS_RU = listOf("Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб")
        private val MONTHS_UZ = listOf("yan", "fev", "mar", "apr", "may", "iyn", "iyl", "avg", "sen", "okt", "noy", "dek")
        private val MONTHS_RU = listOf("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
        private val MONTHS_FULL_UZ = listOf("Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun", "Iyul", "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr")
        private val MONTHS_FULL_RU = listOf("Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь")

        fun builtIn(ru: Boolean): WindowNames =
            if (ru) WindowNames(WEEKDAYS_RU, MONTHS_RU, MONTHS_FULL_RU) else WindowNames(WEEKDAYS_UZ, MONTHS_UZ, MONTHS_FULL_UZ)

        /** The dictionary's comma lists; each one of the wrong length is replaced by the built-in list. */
        fun fromLists(weekdays: String?, months: String?, monthsFull: String?, ru: Boolean): WindowNames {
            val fallback = builtIn(ru)
            fun parse(text: String?, size: Int, default: List<String>) =
                text?.split(",")?.map(String::trim)?.takeIf { list -> list.size == size && list.none(String::isEmpty) } ?: default
            return WindowNames(parse(weekdays, 7, fallback.weekdays), parse(months, 12, fallback.months), parse(monthsFull, 12, fallback.monthsFull))
        }
    }
}

/** The names in the app's language, from the dictionary. */
@Composable
internal fun windowNames(): WindowNames = WindowNames.fromLists(
    t(R.string.client_order_picker_weekdays),
    t(R.string.client_order_picker_months),
    t(R.string.client_order_picker_monthsFull),
    appRu(),
)

/** The pure part of the window sheet (design `pickerVals`/`openPicker`): unit-tested. */
object WindowPickerRules {
    /** Three weeks of days, from today. */
    const val DAYS = 21

    /** The minute wheel: quarters of an hour. */
    val MINUTES = listOf(0, 15, 30, 45)

    /** "+2 soat", "+4 soat", "+8 soat"; then "Kun oxirigacha" (23:45 of the start's day). */
    val QUICK_HOURS = listOf(2, 4, 8)

    fun days(today: LocalDate): List<LocalDate> = (0 until DAYS).map { today.plusDays(it.toLong()) }

    /** Where the wheels start: the edge's value; an empty end six hours after the start; an empty start at noon. */
    fun initial(edge: WindowEdge, start: LocalDateTime?, end: LocalDateTime?, today: LocalDate): LocalDateTime {
        val current = if (edge == WindowEdge.START) start else end
        val base = when {
            current != null -> current
            edge == WindowEdge.END && start != null -> start.withHour((start.hour + 6).coerceAtMost(23))
            else -> LocalDateTime.of(today, LocalTime.NOON)
        }
        return snap(base, today)
    }

    /** Onto the strip (a day outside it goes to its first day) and onto a quarter of an hour. */
    fun snap(value: LocalDateTime, today: LocalDate): LocalDateTime {
        val day = value.toLocalDate().takeIf { !it.isBefore(today) && it.isBefore(today.plusDays(DAYS.toLong())) } ?: today
        // Down to the quarter: 09:55 stays in its hour (09:45) rather than wrapping to 09:00.
        val quarter = value.minute / 15
        return LocalDateTime.of(day, LocalTime.of(value.hour, MINUTES[quarter]))
    }

    fun error(edge: WindowEdge, selected: LocalDateTime, start: LocalDateTime?, now: LocalDateTime): WindowPickError? = when {
        edge == WindowEdge.START && selected.isBefore(now) -> WindowPickError.PAST
        edge == WindowEdge.END && start != null && !selected.isAfter(start) -> WindowPickError.END_BEFORE_START
        else -> null
    }

    /** A quick end: [hours] after the start, or (null) the end of the start's day. */
    fun quickEnd(start: LocalDateTime, hours: Int?): LocalDateTime =
        if (hours == null) LocalDateTime.of(start.toLocalDate(), LocalTime.of(23, 45)) else start.plusHours(hours.toLong())
}

private val ROW = 44.dp

/**
 * The design's window sheet, shared by the route step and the Taksi home: Boshlanishi | Tugashi tabs, a 21-day
 * strip, hour and minute wheels, quick ends for the end edge, the error line and "Keyingi: tugash vaqti" / "Tayyor".
 * Times are Tashkent wall-clock times.
 */
@Composable
internal fun WindowSheet(
    edge: WindowEdge,
    start: LocalDateTime?,
    end: LocalDateTime?,
    onStart: (LocalDateTime) -> Unit,
    onEnd: (LocalDateTime) -> Unit,
    onDismiss: () -> Unit,
) {
    val c = Elchi.colors
    val names = windowNames()
    val today = remember { LocalDate.now(ParcelRules.TASHKENT) }
    val days = remember(today) { WindowPickerRules.days(today) }
    var current by remember { mutableStateOf(edge) }
    // The other edge as saved so far (a committed tab switch updates it here before the parent recomposes).
    var savedStart by remember { mutableStateOf(start) }
    var savedEnd by remember { mutableStateOf(end) }
    val first = remember { WindowPickerRules.initial(edge, start, end, today) }
    var dayIndex by remember { mutableIntStateOf(days.indexOf(first.toLocalDate()).coerceAtLeast(0)) }
    var hour by remember { mutableIntStateOf(first.hour) }
    var minuteIndex by remember { mutableIntStateOf(WindowPickerRules.MINUTES.indexOf(first.minute).coerceAtLeast(0)) }
    // Bumped whenever the values are set from outside the wheels (a tab, a quick chip): the wheels scroll there.
    var sync by remember { mutableIntStateOf(0) }

    val selected = LocalDateTime.of(days[dayIndex], LocalTime.of(hour, WindowPickerRules.MINUTES[minuteIndex]))
    val error = WindowPickerRules.error(current, selected, savedStart, LocalDateTime.now(ParcelRules.TASHKENT))

    fun load(target: WindowEdge) {
        val value = WindowPickerRules.initial(target, savedStart, savedEnd, today)
        current = target
        dayIndex = days.indexOf(value.toLocalDate()).coerceAtLeast(0)
        hour = value.hour
        minuteIndex = WindowPickerRules.MINUTES.indexOf(value.minute).coerceAtLeast(0)
        sync++
    }

    fun commit() {
        if (current == WindowEdge.START) {
            savedStart = selected
            onStart(selected)
        } else {
            savedEnd = selected
            onEnd(selected)
        }
    }

    val startLabel = t(R.string.client_order_windowStartShort)
    val endLabel = t(R.string.client_order_windowEndShort)
    FormSheet(title = null, onDismiss = onDismiss, scrollable = true) {
        // Tabs: the edge being picked shows the live selection, the other its saved value.
        Row(Modifier.fillMaxWidth().clip(CircleShape).background(c.field).padding(4.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            listOf(WindowEdge.START to startLabel, WindowEdge.END to endLabel).forEach { (tab, label) ->
                val on = tab == current
                val value = if (on) selected else if (tab == WindowEdge.START) savedStart else savedEnd
                Column(
                    Modifier
                        .weight(1f)
                        .height(40.dp)
                        .then(if (on) Modifier.shadow(4.dp, CircleShape, ambientColor = c.shadow, spotColor = c.shadow) else Modifier)
                        .clip(CircleShape)
                        .background(if (on) c.card else Color.Transparent)
                        .selectable(on, role = Role.Tab) {
                            if (on) return@selectable
                            if (error == null) commit()
                            load(tab)
                        },
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Center,
                ) {
                    Text(label, style = Elchi.type.badge.copy(fontWeight = FontWeight.Normal, lineHeight = 13.sp), color = c.muted)
                    Text(value?.let { tabValue(it, names) } ?: "—", style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold, lineHeight = 16.sp), color = c.text, maxLines = 1)
                }
            }
        }
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Bottom) {
            Text("${names.monthFull(days[dayIndex].monthValue)} ${days[dayIndex].year}", Modifier.weight(1f), style = Elchi.type.bodyStrong, color = c.text)
            Text(t(R.string.client_order_picker_swipe), style = Elchi.type.caption, color = c.muted)
        }
        DayStrip(days, dayIndex, sync, names) { dayIndex = it }
        Wheels(hour, minuteIndex, sync, onHour = { hour = it }, onMinute = { minuteIndex = it })
        if (current == WindowEdge.END && savedStart != null) {
            val base = savedStart!!
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                (WindowPickerRules.QUICK_HOURS.map<Int, Int?> { it } + listOf(null)).forEach { hours ->
                    val label = if (hours == null) t(R.string.client_order_picker_endOfDay) else t(R.string.client_order_picker_plusHours, "hours" to hours)
                    Text(
                        label,
                        Modifier
                            .clip(CircleShape)
                            .background(c.soft)
                            .clickable(role = Role.Button) {
                                val value = WindowPickerRules.snap(WindowPickerRules.quickEnd(base, hours), today)
                                dayIndex = days.indexOf(value.toLocalDate()).coerceAtLeast(0)
                                hour = value.hour
                                minuteIndex = WindowPickerRules.MINUTES.indexOf(value.minute).coerceAtLeast(0)
                                sync++
                            }
                            .padding(horizontal = 12.dp, vertical = 8.dp),
                        style = Elchi.type.label,
                        color = c.softText,
                        maxLines = 1,
                    )
                }
            }
        }
        if (error != null) {
            Text(
                if (error == WindowPickError.PAST) t(R.string.client_order_picker_past) else t(R.string.client_order_err_endAfterStart),
                style = Elchi.type.caption.copy(fontSize = 12.5.sp),
                color = c.tone(Tone.ERR).fg,
            )
        }
        val goesOn = current == WindowEdge.START && savedEnd == null
        ElchiButton(
            if (goesOn) t(R.string.client_order_picker_next) else t(R.string.client_keyboard_done),
            {
                if (error == null) {
                    commit()
                    if (goesOn) load(WindowEdge.END) else onDismiss()
                }
            },
            Modifier.fillMaxWidth(),
            dimmed = error != null,
        )
    }
}

/** "28 sen, 09:00" */
private fun tabValue(value: LocalDateTime, names: WindowNames): String =
    "${value.dayOfMonth} ${names.monthShort(value.monthValue)}, %02d:%02d".format(value.hour, value.minute)

@Composable
private fun DayStrip(days: List<LocalDate>, selected: Int, sync: Int, names: WindowNames, onDay: (Int) -> Unit) {
    val c = Elchi.colors
    val state = rememberLazyListState(initialFirstVisibleItemIndex = (selected - 1).coerceAtLeast(0))
    LaunchedEffect(sync) { if (sync > 0) state.animateScrollToItem((selected - 1).coerceAtLeast(0)) }
    val today = t(R.string.driver_feed_dateToday)
    val tomorrow = t(R.string.driver_feed_dateTomorrow)
    LazyRow(state = state, horizontalArrangement = Arrangement.spacedBy(8.dp), contentPadding = PaddingValues(vertical = 2.dp)) {
        itemsIndexed(days) { i, day ->
            val on = i == selected
            val shape = RoundedCornerShape(18.dp)
            val week = when (i) {
                0 -> today
                1 -> tomorrow
                else -> names.weekdayShort(day.dayOfWeek)
            }
            Column(
                Modifier
                    .width(58.dp)
                    .height(74.dp)
                    .clip(shape)
                    .background(if (on) c.brand else sheetWell())
                    .then(if (on) Modifier else Modifier.border(1.dp, c.line, shape))
                    .selectable(on, role = Role.RadioButton) { onDay(i) },
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(2.dp, Alignment.CenterVertically),
            ) {
                Text(week, style = Elchi.type.badge.copy(fontWeight = FontWeight.Medium), color = if (on) c.onBrand else c.muted, maxLines = 1)
                Text(day.dayOfMonth.toString(), style = Elchi.type.section.copy(fontSize = 20.sp, lineHeight = 24.sp, fontWeight = FontWeight.SemiBold), color = if (on) c.onBrand else c.text)
                Text(names.monthShort(day.monthValue), style = Elchi.type.badge.copy(fontSize = 10.sp, fontWeight = FontWeight.Normal), color = if (on) c.onBrand else c.muted)
            }
        }
    }
}

@Composable
private fun Wheels(hour: Int, minuteIndex: Int, sync: Int, onHour: (Int) -> Unit, onMinute: (Int) -> Unit) {
    val c = Elchi.colors
    val well = sheetWell()
    Box(Modifier.fillMaxWidth().height(ROW * 5).clip(RoundedCornerShape(20.dp)).background(well)) {
        // The selection band behind the middle row.
        Box(
            Modifier
                .padding(horizontal = 12.dp)
                .padding(top = ROW * 2)
                .fillMaxWidth()
                .height(ROW)
                .shadow(4.dp, RoundedCornerShape(14.dp), ambientColor = c.shadow, spotColor = c.shadow)
                .clip(RoundedCornerShape(14.dp))
                .background(c.card),
        )
        Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
            Wheel((0..23).map { "%02d".format(it) }, hour, sync, onHour)
            Text(":", Modifier.padding(bottom = 4.dp), style = Elchi.type.title.copy(fontWeight = FontWeight.SemiBold), color = c.text)
            Wheel(WindowPickerRules.MINUTES.map { "%02d".format(it) }, minuteIndex, sync, onMinute)
        }
        Box(Modifier.fillMaxWidth().height(56.dp).background(Brush.verticalGradient(listOf(well, well.copy(alpha = 0f)))))
        Box(Modifier.align(Alignment.BottomCenter).fillMaxWidth().height(56.dp).background(Brush.verticalGradient(listOf(well.copy(alpha = 0f), well))))
    }
}

/**
 * One wheel: two blank rows above and below, so value i sits in the middle row when the list's first visible
 * item is i (a released drag settles there).
 */
@Composable
private fun Wheel(labels: List<String>, selected: Int, sync: Int, onSelect: (Int) -> Unit) {
    val c = Elchi.colors
    val state = rememberLazyListState(initialFirstVisibleItemIndex = selected)
    val scope = rememberCoroutineScope()
    val rowPx = with(LocalDensity.current) { ROW.toPx() }
    val centre by remember(state) {
        derivedStateOf { (state.firstVisibleItemIndex + if (state.firstVisibleItemScrollOffset > rowPx / 2) 1 else 0).coerceIn(0, labels.lastIndex) }
    }
    LaunchedEffect(state) { snapshotFlow { centre }.collect { onSelect(it) } }
    LaunchedEffect(sync) { if (sync > 0) state.animateScrollToItem(selected) }
    // The wheel owns its drag (the sheet around it scrolls too, and would take it): the list follows the finger and
    // settles on the nearest value when it is let go.
    LazyColumn(
        Modifier
            .width(96.dp)
            .height(ROW * 5)
            .pointerInput(state) {
                detectVerticalDragGestures(
                    onDragEnd = { scope.launch { state.animateScrollToItem(centre) } },
                    onDragCancel = { scope.launch { state.animateScrollToItem(centre) } },
                ) { change, dragAmount ->
                    change.consume()
                    state.dispatchRawDelta(-dragAmount)
                }
            },
        state = state,
        userScrollEnabled = false,
    ) {
        items(2) { Box(Modifier.height(ROW)) }
        itemsIndexed(labels) { i, label ->
            val distance = kotlin.math.abs(i - centre)
            Box(
                Modifier
                    .fillMaxWidth()
                    .height(ROW)
                    .clickable(role = Role.Button) { scope.launch { state.animateScrollToItem(i) } }
                    .semantics { contentDescription = label },
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    label,
                    style = Elchi.type.title.copy(
                        fontSize = when (distance) { 0 -> 24.sp; 1 -> 19.sp; else -> 16.sp },
                        fontWeight = if (distance == 0) FontWeight.SemiBold else FontWeight.Medium,
                        fontFeatureSettings = "tnum",
                    ),
                    color = when (distance) { 0 -> c.text; 1 -> c.placeholder; else -> c.placeholder.copy(alpha = 0.55f) },
                )
            }
        }
        items(2) { Box(Modifier.height(ROW)) }
    }
}
