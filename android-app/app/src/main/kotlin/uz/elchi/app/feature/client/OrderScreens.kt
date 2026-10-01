package uz.elchi.app.feature.client

import android.content.ActivityNotFoundException
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDefaults
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.SelectableDates
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.TimePickerDefaults
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.OffsetMapping
import androidx.compose.ui.text.input.TransformedText
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import androidx.core.net.toUri
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import uz.elchi.app.R
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.generated.ParcelCategoryDTO
import uz.elchi.app.api.generated.ParcelPolicyDTO
import uz.elchi.app.api.generated.ParcelType
import uz.elchi.app.feature.entry.UzPhoneTransformation
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.Banner
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.CardHeader
import uz.elchi.app.ui.components.CardRow
import uz.elchi.app.ui.components.Chip
import uz.elchi.app.ui.components.ChoiceGrid
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiField
import uz.elchi.app.ui.components.EmptyState
import uz.elchi.app.ui.components.ListCard
import uz.elchi.app.ui.components.ListRow
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.PickerField
import uz.elchi.app.ui.components.RadioCard
import uz.elchi.app.ui.components.SectionTitle
import uz.elchi.app.ui.components.SystemBarIcons
import uz.elchi.app.ui.components.UploadBox
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.map.ElchiMap
import uz.elchi.app.ui.map.GeoPoint
import uz.elchi.app.ui.map.MapFocus
import uz.elchi.app.ui.map.MapKitSupport
import uz.elchi.app.ui.map.MapMarker
import uz.elchi.app.ui.map.decodePolyline
import uz.elchi.app.ui.map.legPath
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import java.io.File
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.ZoneOffset

// -- client-route-summary (step 1) -------------------------------------------------------------------------------

private enum class WindowEdge { START, END }

@Composable
fun RouteSummaryScreen(vm: ParcelRequestViewModel, ru: Boolean, onBack: () -> Unit, onChange: (End) -> Unit, onSave: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val c = Elchi.colors
    val draft = s.draft
    val issues = ParcelRules.routeIssues(draft, s.directionReady, Instant.now())
    var picking by rememberSaveable { mutableStateOf<WindowEdge?>(null) }
    StepScaffold(
        title = t(R.string.routeSummary_direction),
        onBack = onBack,
        footer = {
            ElchiButton(t(R.string.common_save), onSave, Modifier.fillMaxWidth(), enabled = issues.isEmpty())
            if (issues.isNotEmpty()) Note(issues.map { issueText(it) }.joinToString(" · "), tone = Tone.ERR)
        },
    ) {
        ElchiCard(bordered = true) {
            EndRow(t(R.string.routeSummary_pickup), draft.origin, ru, first = true) { onChange(End.ORIGIN) }
            EndRow(t(R.string.routeSummary_dropoff), draft.destination, ru, first = false) { onChange(End.DESTINATION) }
        }
        when (val d = s.direction) {
            is Direction.Ready -> {
                val p = d.preview
                ElchiCard(bordered = true) {
                    CardRow(
                        t(R.string.routeSummary_estimatedRoute),
                        roadText(p.legDistanceM, p.legDurationS),
                        first = true,
                        detail = "${t(R.string.routeSummary_driverProposesTimeLine1)} ${t(R.string.routeSummary_driverProposesTimeLine2)}",
                    )
                }
                ParcelRules.offRouteMeters(p)?.let { Note(t(R.string.app_location_offRoute, "km" to ParcelRules.km(it)), tone = Tone.WARN) }
                RouteMiniMap(s, draft)
                if (!p.districtsOnRoute.isNullOrEmpty()) {
                    ElchiCard(bordered = true) {
                        CardRow(t(R.string.routeSummary_districtsTitle), p.districtsOnRoute.joinToString(" - "), first = true, detail = t(R.string.routeSummary_districtsHint))
                    }
                }
            }
            Direction.Checking -> LoadingLine(t(R.string.home_checkingRoute))
            Direction.Mismatch -> Note(t(R.string.home_movePointHint), tone = Tone.ERR, title = t(R.string.app_location_previewMismatch))
            is Direction.Failed -> LoadFailed(t(R.string.routeSummary_estimatedRoute), d.error, vm::refreshDirection)
            Direction.Incomplete -> Unit
        }
        val placeholder = t(R.string.client_routeSummary_windowPlaceholder)
        PickerField(
            t(R.string.listingOwner_windowStart),
            draft.start?.let(ParcelRules::display),
            placeholder,
            onClick = { picking = WindowEdge.START },
            error = RouteIssue.WINDOW_START in issues || RouteIssue.WINDOW_PAST in issues,
        )
        PickerField(
            t(R.string.listingOwner_windowEnd),
            draft.endTime?.let(ParcelRules::display),
            placeholder,
            onClick = { picking = WindowEdge.END },
            hint = t(R.string.routeSummary_windowHint),
            error = RouteIssue.WINDOW_END in issues || RouteIssue.WINDOW_ORDER in issues,
        )
        ElchiField(
            draft.priceDigits,
            { text -> vm.edit { it.copy(priceDigits = text.filter(Char::isDigit).trimStart('0').take(10)) } },
            label = t(R.string.listingOwner_priceLabel),
            placeholder = "200${ParcelRules.NBSP}000",
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Done),
            visualTransformation = ThousandsTransformation,
        )
        val minor = ParcelRules.soumToMinor(draft.priceDigits)
        ElchiCard(background = c.highlight) {
            CardRow(
                t(R.string.common_total),
                minor?.let { ParcelRules.formatSoum(it, t(R.string.common_soum)) } ?: t(R.string.common_dash),
                first = true,
                detail = t(R.string.routeSummary_driversSendOffers),
                strong = true,
            )
        }
    }
    picking?.let { edge ->
        val current = if (edge == WindowEdge.START) draft.start else draft.endTime
        val fallback = (if (edge == WindowEdge.START) null else draft.start) ?: ParcelRules.defaultWindow(Instant.now()).let { if (edge == WindowEdge.START) it.first else it.second }
        DateTimeDialog(
            title = t(if (edge == WindowEdge.START) R.string.listingOwner_windowStart else R.string.listingOwner_windowEnd),
            initial = current ?: fallback,
            onDismiss = { picking = null },
            onPicked = { value ->
                picking = null
                vm.edit { d ->
                    val text = ParcelRules.formatLocal(value)
                    if (edge == WindowEdge.START) d.copy(windowStart = text) else d.copy(windowEnd = text)
                }
            },
        )
    }
}

@Composable
private fun EndRow(key: String, place: Place?, ru: Boolean, first: Boolean, onChange: () -> Unit) {
    CardRow(
        key,
        place?.label(ru) ?: t(R.string.app_route_noAddress),
        first = first,
        detail = place?.area(ru),
        trailing = t(R.string.app_route_change),
        onTrailing = onChange,
        muted = place == null,
    )
}

/** The confirmed road between the two places, on a small still map (hidden when the map is unavailable). */
@Composable
private fun RouteMiniMap(s: ParcelRequestViewModel.State, draft: ParcelDraft) {
    var usable by remember { mutableStateOf(MapKitSupport.likelyAvailable) }
    if (!usable) return
    val markers = listOfNotNull(
        draft.origin?.let { MapMarker(GeoPoint(it.lat, it.lng), MapMarker.Kind.ORIGIN) },
        draft.destination?.let { MapMarker(GeoPoint(it.lat, it.lng), MapMarker.Kind.DESTINATION) },
    )
    val route = remember(s.preview?.routePolyline, markers) {
        legPath(s.preview?.routePolyline?.let(::decodePolyline).orEmpty(), markers.firstOrNull { it.kind == MapMarker.Kind.ORIGIN }?.point, markers.firstOrNull { it.kind == MapMarker.Kind.DESTINATION }?.point)
    }
    val focus = remember(route, markers) { MapFocus.Fit(markers.map { it.point } + route) }
    Box(Modifier.fillMaxWidth().height(220.dp).clip(RoundedCornerShape(20.dp))) {
        ElchiMap(
            Modifier.fillMaxSize(),
            markers = markers,
            route = route,
            focus = focus,
            padding = androidx.compose.foundation.layout.PaddingValues(18.dp),
            interactive = false,
            onAvailability = { usable = it },
            placeholderTitle = t(R.string.client_map_unavailable),
        )
    }
}

@Composable
private fun issueText(issue: RouteIssue): String = t(
    when (issue) {
        RouteIssue.POINTS -> R.string.app_validation_bothPoints
        RouteIssue.WINDOW_START -> R.string.app_validation_windowStart
        RouteIssue.WINDOW_END -> R.string.app_validation_windowEnd
        RouteIssue.WINDOW_PAST -> R.string.app_validation_windowPast
        RouteIssue.WINDOW_ORDER -> R.string.app_validation_endAfterStart
        RouteIssue.PRICE -> R.string.listingOwner_invalid_price
    },
)

/** `120000` shown as `120 000` while typing; the cursor maps back onto the raw digits. */
internal object ThousandsTransformation : VisualTransformation {
    override fun filter(text: AnnotatedString): TransformedText {
        val raw = text.text
        if (raw.isEmpty() || !raw.all(Char::isDigit)) return TransformedText(text, OffsetMapping.Identity)
        val out = ParcelRules.groupThousands(raw.toLong())
        val mapping = object : OffsetMapping {
            // A separator sits before digit i (i > 0) when a whole number of thousands follows it.
            override fun originalToTransformed(offset: Int): Int {
                val k = offset.coerceIn(0, raw.length)
                return k + (1 until k).count { (raw.length - it) % 3 == 0 }
            }

            override fun transformedToOriginal(offset: Int): Int = out.take(offset).count(Char::isDigit)
        }
        return TransformedText(AnnotatedString(out), mapping)
    }
}

/** Date, then time - in Tashkent wall-clock terms; days before today cannot be picked. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun DateTimeDialog(title: String, initial: LocalDateTime, onDismiss: () -> Unit, onPicked: (LocalDateTime) -> Unit) {
    val c = Elchi.colors
    // Dialog windows get their own context (the phone's language): every label is resolved out here, in ours.
    val continueLabel = t(R.string.common_continue)
    val confirmLabel = t(R.string.common_confirm)
    val cancelLabel = t(R.string.common_cancel)
    var date by remember { mutableStateOf<LocalDate?>(null) }
    val today = LocalDate.now(ParcelRules.TASHKENT)
    val dateColors = DatePickerDefaults.colors(
        containerColor = c.card, titleContentColor = c.muted, headlineContentColor = c.text, weekdayContentColor = c.muted,
        dayContentColor = c.text, selectedDayContainerColor = c.brand, selectedDayContentColor = c.onBrand, todayDateBorderColor = c.brand,
        todayContentColor = c.accentText, disabledDayContentColor = c.placeholder, navigationContentColor = c.text,
        yearContentColor = c.text, selectedYearContainerColor = c.brand, selectedYearContentColor = c.onBrand, dividerColor = c.line,
    )
    val pickedDate = date
    if (pickedDate == null) {
        val state = rememberDatePickerState(
            initialSelectedDateMillis = initial.toLocalDate().atStartOfDay().toInstant(ZoneOffset.UTC).toEpochMilli(),
            selectableDates = object : SelectableDates {
                override fun isSelectableDate(utcTimeMillis: Long): Boolean =
                    !Instant.ofEpochMilli(utcTimeMillis).atZone(ZoneOffset.UTC).toLocalDate().isBefore(today)

                override fun isSelectableYear(year: Int): Boolean = year >= today.year
            },
        )
        DatePickerDialog(
            onDismissRequest = onDismiss,
            confirmButton = {
                TextButton(onClick = {
                    state.selectedDateMillis?.let { date = Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate() }
                }, enabled = state.selectedDateMillis != null) { Text(continueLabel, color = c.accentText) }
            },
            dismissButton = { TextButton(onClick = onDismiss) { Text(cancelLabel, color = c.muted) } },
            colors = dateColors,
        ) {
            // Title and headline are ours: Material formats them in the phone's language, not the app's.
            DatePicker(
                state,
                colors = dateColors,
                showModeToggle = false,
                title = { Text(title, Modifier.padding(start = 24.dp, end = 12.dp, top = 16.dp), style = Elchi.type.label, color = c.muted) },
                headline = {
                    val selected = state.selectedDateMillis?.let { Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate() }
                    Text(
                        selected?.let { "%02d.%02d.%d".format(it.dayOfMonth, it.monthValue, it.year) } ?: "",
                        Modifier.padding(start = 24.dp, end = 12.dp, bottom = 12.dp),
                        style = Elchi.type.title,
                        color = c.text,
                    )
                },
            )
        }
    } else {
        val state = rememberTimePickerState(initial.hour, initial.minute, is24Hour = true)
        AlertDialog(
            onDismissRequest = onDismiss,
            containerColor = c.card,
            confirmButton = {
                TextButton(onClick = { onPicked(LocalDateTime.of(pickedDate, LocalTime.of(state.hour, state.minute))) }) {
                    Text(confirmLabel, color = c.accentText)
                }
            },
            dismissButton = { TextButton(onClick = onDismiss) { Text(cancelLabel, color = c.muted) } },
            title = { Text(title, style = Elchi.type.label, color = c.muted) },
            text = {
                TimePicker(
                    state,
                    colors = TimePickerDefaults.colors(
                        clockDialColor = c.field, selectorColor = c.brand, containerColor = c.card, clockDialSelectedContentColor = c.onBrand,
                        clockDialUnselectedContentColor = c.text, timeSelectorSelectedContainerColor = c.soft, timeSelectorUnselectedContainerColor = c.field,
                        timeSelectorSelectedContentColor = c.softText, timeSelectorUnselectedContentColor = c.text,
                    ),
                )
            },
        )
    }
}

// -- client-order-address (step 2) -------------------------------------------------------------------------------

@Composable
fun OrderAddressScreen(vm: ParcelRequestViewModel, ru: Boolean, onBack: () -> Unit, onNext: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val d = s.draft
    StepScaffold(
        title = t(R.string.orderForm_contactTitle),
        onBack = onBack,
        footer = { ElchiButton(t(R.string.common_continue), onNext, Modifier.fillMaxWidth(), enabled = ParcelRules.contactsComplete(d)) },
    ) {
        ElchiCard(background = Elchi.colors.field) {
            CardRow(t(R.string.routeSummary_direction), routeLine(d, ru), first = true)
        }
        val words = KeyboardOptions(capitalization = KeyboardCapitalization.Words, imeAction = ImeAction.Next)
        val phone = KeyboardOptions(keyboardType = KeyboardType.Phone, imeAction = ImeAction.Next)
        ElchiField(d.senderName, { v -> vm.edit { it.copy(senderName = v.take(120)) } }, label = t(R.string.orderForm_senderName), keyboardOptions = words)
        PhoneField(t(R.string.orderForm_senderPhone), d.senderDigits, phone) { v -> vm.edit { it.copy(senderDigits = v) } }
        ElchiField(d.receiverName, { v -> vm.edit { it.copy(receiverName = v.take(120)) } }, label = t(R.string.orderForm_receiverName), keyboardOptions = words)
        PhoneField(t(R.string.orderForm_receiverPhone), d.receiverDigits, phone) { v -> vm.edit { it.copy(receiverDigits = v) } }
        ElchiField(
            d.comment,
            { v -> vm.edit { it.copy(comment = v.take(1000)) } },
            label = t(R.string.listingOwner_commentLabel),
            singleLine = false,
            minHeight = 96.dp,
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
        )
        Note(t(R.string.orderForm_phonesHidden))
    }
}

@Composable
private fun PhoneField(label: String, digits: String, options: KeyboardOptions, onDigits: (String) -> Unit) {
    ElchiField(
        digits,
        { onDigits(it.filter(Char::isDigit).take(9)) },
        label = label,
        prefix = "+998",
        placeholder = "90 123 45 67",
        monospace = true,
        keyboardOptions = options,
        visualTransformation = UzPhoneTransformation,
    )
}

@Composable
private fun routeLine(d: ParcelDraft, ru: Boolean): String =
    "${d.origin?.district(ru) ?: t(R.string.direction_from)} → ${d.destination?.district(ru) ?: t(R.string.direction_to)}"

// -- client-order-parcel (step 3) --------------------------------------------------------------------------------

@Composable
internal fun parcelTypeLabel(type: ParcelType): String = t(
    when (type) {
        ParcelType.DOCUMENTS -> R.string.app_parcelType_documents
        ParcelType.BOX -> R.string.app_parcelType_box
        ParcelType.BAG -> R.string.app_parcelType_bag
        ParcelType.ELECTRONICS -> R.string.app_parcelType_electronics
        ParcelType.CLOTHING -> R.string.app_parcelType_clothing
        ParcelType.OTHER, ParcelType.UNKNOWN -> R.string.app_parcelType_other
    },
)

private fun categoryIcon(iconKey: String): ElchiIcon = when {
    iconKey.startsWith("env") -> ElchiIcon.ENV
    iconKey == "bag" -> ElchiIcon.BAG
    iconKey.endsWith("large") -> ElchiIcon.ARCHIVE
    else -> ElchiIcon.PKG
}

@Composable
internal fun categoryName(item: ParcelCategoryDTO, ru: Boolean) = if (ru) item.nameRu ?: item.nameUz else item.nameUz

@Composable
internal fun categoryLimits(item: ParcelCategoryDTO): String = t(
    R.string.parcelCategory_limits,
    "length" to item.maxLengthCm, "width" to item.maxWidthCm, "height" to item.maxHeightCm, "weight" to ParcelRules.kg(item.maxWeightG),
)

@Composable
fun OrderParcelScreen(vm: ParcelRequestViewModel, ru: Boolean, onBack: () -> Unit, onNext: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val d = s.draft
    val catalog = s.catalogValue
    val types = ParcelType.entries.filter { it != ParcelType.UNKNOWN }
    StepScaffold(
        title = t(R.string.orderForm_parcelTitle),
        onBack = onBack,
        footer = {
            ElchiButton(t(R.string.common_continue), onNext, Modifier.fillMaxWidth(), enabled = ParcelRules.parcelComplete(d) && catalog?.confirmed == true)
        },
    ) {
        SectionTitle(t(R.string.orderForm_parcelType))
        ChoiceGrid(types.map { it.value to parcelTypeLabel(it) }, d.parcelType, { v -> vm.edit { it.copy(parcelType = v) } })
        SectionTitle(t(R.string.parcelCategory_label), description = t(R.string.parcelCategory_hint))
        when (val cat = s.catalog) {
            Load.Loading -> LoadingLine(t(R.string.parcelCategory_loading))
            is Load.Failed -> LoadFailed(t(R.string.parcelCategory_loadFailed), cat.error, vm::loadCatalog)
            is Load.Ready -> if (!cat.value.confirmed) {
                Note(t(R.string.parcelCategory_unconfirmed), tone = Tone.WARN)
            } else {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    cat.value.items.orEmpty().forEach { item ->
                        RadioCard(categoryIcon(item.iconKey), categoryName(item, ru), categoryLimits(item), d.categoryId == item.id, { vm.edit { it.copy(categoryId = item.id) } })
                    }
                }
                if (cat.value.synthetic == true) Note(t(R.string.parcelCategory_synthetic), tone = Tone.WARN)
            }
        }
        PolicyBlock(s.policy, vm::loadPolicy)
    }
}

/** Prohibited items (§5.2): shown before sending, with its source; "not approved" never reads as "all allowed". */
@Composable
private fun PolicyBlock(policy: Load<ParcelPolicyDTO>, retry: () -> Unit) {
    when (policy) {
        Load.Loading -> LoadingLine(t(R.string.common_loading))
        is Load.Failed -> {
            SectionTitle(t(R.string.parcelPolicy_title))
            Note(t(R.string.parcelPolicy_loadFailed), tone = Tone.ERR)
            ElchiButton(t(R.string.common_retry), retry, Modifier.fillMaxWidth(), ButtonVariant.GHOST, ButtonSize.MEDIUM, icon = ElchiIcon.REFRESH)
        }
        is Load.Ready -> {
            val p = policy.value
            when {
                !p.approved -> {
                    SectionTitle(t(R.string.parcelPolicy_title))
                    Note(t(R.string.parcelPolicy_unconfirmed), tone = Tone.WARN)
                }
                p.items.isNullOrEmpty() -> {
                    SectionTitle(t(R.string.parcelPolicy_title))
                    Note(t(R.string.parcelPolicy_empty), tone = Tone.GRAY)
                }
                else -> {
                    val badge = listOfNotNull(p.label, p.effectiveFrom?.let { t(R.string.parcelPolicy_effectiveFrom, "date" to shortDate(it)) }).joinToString(" · ").ifEmpty { null }
                    ElchiCard(bordered = true) {
                        CardHeader(t(R.string.parcelPolicy_title), badge)
                        p.items.forEachIndexed { i, item ->
                            val applies = item.appliesTo?.let { tOrNull("parcelPolicy.appliesTo.$it") }
                            val source = item.sourceRef?.let { ref ->
                                item.sourceCheckedOn?.let { t(R.string.parcelPolicy_sourceChecked, "source" to ref, "date" to shortDate(it)) } ?: t(R.string.parcelPolicy_source, "source" to ref)
                            }
                            CardRow(
                                tOrNull("parcelPolicy.category.${item.category}") ?: item.category,
                                item.title,
                                first = false,
                                detail = listOfNotNull(applies, source).joinToString(" · ").ifEmpty { null },
                            )
                        }
                    }
                }
            }
        }
    }
}

/** `2026-09-01` / an ISO instant -> `01.09.2026`. */
private fun shortDate(value: String): String = runCatching {
    val date = if (value.length == 10) LocalDate.parse(value) else Instant.parse(value).atZone(ParcelRules.TASHKENT).toLocalDate()
    "%02d.%02d.%d".format(date.dayOfMonth, date.monthValue, date.year)
}.getOrDefault(value)

// -- client-order-photo (step 4) ---------------------------------------------------------------------------------

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OrderPhotoScreen(vm: ParcelRequestViewModel, onBack: () -> Unit, onNext: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val c = Elchi.colors
    val context = LocalContext.current
    var chooser by remember { mutableStateOf(false) }
    var captureUri by rememberSaveable { mutableStateOf<String?>(null) }
    val gallery = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri -> uri?.let(vm::uploadPhoto) }
    val camera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { saved ->
        val uri = captureUri
        if (saved && uri != null) vm.uploadPhoto(uri.toUri())
    }
    val preview = remember(s.draft.photoLocalPath) { s.draft.photoLocalPath?.let { PhotoCompressor.previewBitmap(File(it)) } }
    val hasPhoto = s.draft.photoFileUrl != null

    StepScaffold(
        title = t(R.string.orderForm_photoTitle),
        onBack = onBack,
        footer = { ElchiButton(t(R.string.orderForm_reviewOrder), onNext, Modifier.fillMaxWidth(), enabled = hasPhoto && !s.photoUploading) },
    ) {
        if (!hasPhoto && !s.photoUploading) {
            UploadBox(t(R.string.orderForm_uploadPhoto), t(R.string.orderForm_uploadPhotoHint), { chooser = true })
        }
        if (preview != null && (hasPhoto || s.photoUploading)) {
            Box(Modifier.fillMaxWidth().height(180.dp).clip(RoundedCornerShape(18.dp)).background(c.field), contentAlignment = Alignment.Center) {
                Image(preview.asImageBitmap(), t(R.string.orderForm_photoAlt), Modifier.fillMaxSize(), contentScale = ContentScale.Crop)
            }
        }
        if (s.photoUploading) LoadingLine(t(R.string.app_photo_loading))
        if (hasPhoto && !s.photoUploading) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Chip(t(R.string.orderForm_photoReady), selected = true, onClick = {}, icon = ElchiIcon.CHECK_C)
                Spacer(Modifier.weight(1f))
                ElchiButton(t(R.string.client_photo_replace), { chooser = true }, variant = ButtonVariant.GHOST, size = ButtonSize.MEDIUM, icon = ElchiIcon.REFRESH)
            }
        }
        s.photoError?.let { e ->
            Note(if (e is ApiException) errorText(e) else t(R.string.client_photo_unreadable), tone = Tone.ERR)
        }
    }

    if (chooser) {
        // The sheet is its own window with the phone's language: labels are resolved here, in the app's.
        val sheetTitle = t(R.string.orderForm_uploadPhoto)
        val cameraLabel = t(R.string.client_photo_camera)
        val galleryLabel = t(R.string.client_photo_gallery)
        ModalBottomSheet(onDismissRequest = { chooser = false }, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true), containerColor = c.page) {
            Column(Modifier.padding(horizontal = 16.dp).padding(bottom = 24.dp).navigationBarsPadding(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(sheetTitle, style = Elchi.type.section, color = c.text)
                ListCard {
                    ListRow(cameraLabel, icon = ElchiIcon.CAMERA, first = true, onClick = {
                        chooser = false
                        val file = PhotoCompressor(context).newCaptureFile()
                        val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", file)
                        captureUri = uri.toString()
                        try {
                            camera.launch(uri)
                        } catch (e: ActivityNotFoundException) {
                            gallery.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                        }
                    })
                    ListRow(galleryLabel, icon = ElchiIcon.UPLOAD, onClick = {
                        chooser = false
                        gallery.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                    })
                }
            }
        }
    }
}

// -- client-order-review (step 5) --------------------------------------------------------------------------------

@Composable
fun OrderReviewScreen(vm: ParcelRequestViewModel, ru: Boolean, onBack: () -> Unit, onEdit: () -> Unit, onPublished: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val d = s.draft
    val p = s.preview
    LaunchedEffect(s.published) { if (s.published != null) onPublished() }
    val ready = ParcelRules.readyToPublish(d, s.directionReady, Instant.now())
    StepScaffold(
        title = t(R.string.orderForm_review_title),
        onBack = onBack,
        footer = {
            s.publishError?.let { PublishError(it) }
            if (!ready && !s.publishing) Note(t(R.string.orderForm_review_incompleteParcel), tone = Tone.WARN)
            ElchiButton(t(R.string.orderForm_review_publish), vm::publish, Modifier.fillMaxWidth(), enabled = ready, loading = s.publishing)
            ElchiButton(t(R.string.listingOwner_edit), onEdit, Modifier.fillMaxWidth().height(40.dp), ButtonVariant.GHOST, ButtonSize.MEDIUM, enabled = !s.publishing)
        },
    ) {
        val category = s.catalogValue?.items?.firstOrNull { it.id == d.categoryId }
        val type = ParcelType.entries.firstOrNull { it.value == d.parcelType }
        ElchiCard(bordered = true) {
            CardRow(t(R.string.routeSummary_direction), routeLine(d, ru), first = true, detail = p?.corridorName)
            d.origin?.let { CardRow(t(R.string.orderForm_review_pickupPlace), it.label(ru), detail = placeDetail(it, ru)) }
            d.destination?.let { CardRow(t(R.string.orderForm_review_dropoffPlace), it.label(ru), detail = placeDetail(it, ru)) }
            p?.let { CardRow(t(R.string.routeSummary_estimatedRoute), roadText(it.legDistanceM, it.legDurationS)) }
            p?.districtsOnRoute?.takeIf { it.isNotEmpty() }?.let {
                CardRow(t(R.string.home_routeDistricts), it.joinToString(" - "), detail = t(R.string.orderForm_review_districtsDetail))
            }
            if (d.start != null && d.endTime != null) {
                CardRow(t(R.string.orderForm_review_window), "${ParcelRules.displayShort(d.start!!)} - ${ParcelRules.displayShort(d.endTime!!)}")
            }
            ParcelRules.soumToMinor(d.priceDigits)?.let {
                CardRow(t(R.string.common_price), ParcelRules.formatSoum(it, t(R.string.common_soum)), detail = t(R.string.orderForm_review_driversSendOffers), strong = true)
            }
            if (type != null) {
                CardRow(t(R.string.orderForm_review_parcel), parcelTypeLabel(type), detail = category?.let { "${categoryName(it, ru)} · ${categoryLimits(it)}" })
            }
            CardRow(t(R.string.orderForm_review_sender), d.senderName, detail = "+998 ${ParcelRules.groupPhone(d.senderDigits)}")
            CardRow(t(R.string.orderForm_review_receiver), d.receiverName, detail = "+998 ${ParcelRules.groupPhone(d.receiverDigits)}")
            CardRow(t(R.string.orderForm_photoTitle), t(if (d.photoFileUrl != null) R.string.orderForm_review_uploaded else R.string.app_photo_none), muted = d.photoFileUrl == null)
            if (d.comment.isNotBlank()) CardRow(t(R.string.listingOwner_commentLabel), d.comment.trim())
        }
    }
}

/** "Chilonzor, Toshkent shahri", or "Tasdiqlangan bekat · …" for a verified stop (Q88.4). */
@Composable
private fun placeDetail(place: Place, ru: Boolean): String {
    val where = listOf(place.district(ru), place.region(ru)).distinct().joinToString(", ")
    return if (place.stopId != null) t(R.string.orderForm_review_verifiedStop, "where" to where) else where
}

/**
 * The server's refusal in the dictionary's words. LISTING_INCOMPLETE / VALIDATION_ERROR also name the fields
 * (`details.missing`, `details.field`) - translated to the labels the person saw, never the raw names.
 */
@Composable
private fun PublishError(error: Throwable) {
    val fields = (error as? ApiException)?.details?.let { details ->
        val obj = details as? JsonObject
        val names = mutableListOf<String>()
        (obj?.get("missing") as? JsonArray)?.forEach { (it as? JsonPrimitive)?.contentOrNull?.let(names::add) }
        (obj?.get("field") as? JsonPrimitive)?.contentOrNull?.let(names::add)
        names
    }.orEmpty()
    val labels = fields.mapNotNull { fieldLabel(it) }.distinct().map { t(it) }
    Note(if (labels.isEmpty()) errorText(error) else labels.joinToString(", "), tone = Tone.ERR, title = if (labels.isEmpty()) null else errorText(error))
}

private fun fieldLabel(field: String): Int? {
    val name = field.removePrefix("parcel.").removePrefix("body.")
    return when {
        name.startsWith("departure_window_start") -> R.string.listingOwner_windowStart
        name.startsWith("departure_window_end") -> R.string.listingOwner_windowEnd
        name.startsWith("unit_price") -> R.string.common_price
        name.startsWith("photo") -> R.string.orderForm_photoTitle
        name.startsWith("category") -> R.string.parcelCategory_label
        name.startsWith("parcel_type") -> R.string.orderForm_parcelType
        name.startsWith("sender") -> R.string.orderForm_review_sender
        name.startsWith("receiver") -> R.string.orderForm_review_receiver
        name.startsWith("origin") -> R.string.routeSummary_pickup
        name.startsWith("destination") -> R.string.routeSummary_dropoff
        name.startsWith("comment") -> R.string.listingOwner_commentLabel
        else -> null
    }
}

// -- client-success ----------------------------------------------------------------------------------------------

@Composable
fun OrderSuccessScreen(vm: ParcelRequestViewModel, onDone: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val c = Elchi.colors
    SystemBarIcons(dark = !c.isDark)
    // Back from here is the same as the button: the published request is done, the next one starts clean.
    BackHandler(onBack = onDone)
    Column(Modifier.fillMaxSize().background(c.page)) {
        Column(Modifier.statusBarsPadding()) { Banner(t(R.string.orderForm_success_title), Tone.OK) }
        Column(
            Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).padding(top = 40.dp, bottom = 20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            EmptyState(
                ElchiIcon.CHECK_C,
                t(R.string.orderForm_success_title),
                description = "${t(R.string.orderForm_success_waiting)}. ${t(R.string.orderForm_success_notify)}.",
            )
            // One note per server warning, each in its own words (e.g. the comment's contacts were masked, Q43).
            s.published?.warnings.orEmpty().forEach { warning ->
                Note(tOrNull("warning.${warning.code}") ?: warning.message, tone = Tone.WARN)
            }
        }
        Column(Modifier.fillMaxWidth().background(c.card)) {
            Box(Modifier.fillMaxWidth().height(1.dp).background(c.line))
            Column(Modifier.navigationBarsPadding().padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 8.dp)) {
                ElchiButton(t(R.string.orderForm_success_toOrders), onDone, Modifier.fillMaxWidth())
            }
        }
    }
}
