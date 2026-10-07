package uz.elchi.app.feature.client

import android.content.ActivityNotFoundException
import android.content.Intent
import android.provider.ContactsContract
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDefaults
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.SelectableDates
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.TimePickerDefaults
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.OffsetMapping
import androidx.compose.ui.text.input.TransformedText
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import androidx.core.net.toUri
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.launch
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
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.CardRow
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiField
import uz.elchi.app.ui.components.ElchiIconView
import uz.elchi.app.ui.components.ListCard
import uz.elchi.app.ui.components.ListRow
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.SystemBarIcons
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
import uz.elchi.app.ui.theme.tone
import java.io.File
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.ZoneOffset

// -- client-route-summary (Pochta step 1 / 3) ---------------------------------------------------------------------

/**
 * "Yo'nalish": the two ends (with "O'zgartirish"), the road estimate, the departure window tiles (the shared window
 * sheet), the price stepper and the total. The button is grey until the step is complete but still answers: a tap
 * lists what is missing at the top and outlines the fields. [editing]: opened from the review, so the button saves
 * and goes back there.
 */
@Composable
fun RouteSummaryScreen(vm: ParcelRequestViewModel, ru: Boolean, editing: Boolean, onBack: () -> Unit, onChange: (End) -> Unit, onSave: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val c = Elchi.colors
    val draft = s.draft
    val issues = ParcelRules.routeIssues(draft, s.directionReady, Instant.now())
    var showErrors by rememberSaveable { mutableStateOf(false) }
    if (issues.isEmpty()) showErrors = false
    val shown = if (showErrors) issues else emptyList()
    var picking by rememberSaveable { mutableStateOf<WindowEdge?>(null) }
    val scroll = rememberScrollState()
    val scope = rememberCoroutineScope()
    StepScaffold(
        title = t(R.string.routeSummary_direction),
        onBack = onBack,
        step = 1 to 3,
        scrollState = scroll,
        footer = {
            ElchiButton(
                if (editing) t(R.string.client_order_saveAndReturn) else t(R.string.common_save),
                {
                    if (issues.isEmpty()) onSave() else {
                        showErrors = true
                        scope.launch { scroll.animateScrollTo(0) }
                    }
                },
                Modifier.fillMaxWidth(),
                dimmed = issues.isNotEmpty(),
            )
        },
    ) {
        ErrorList(shown.map { issueText(it) })
        ElchiCard {
            EndRow(t(R.string.routeSummary_pickup), draft.origin, ru, first = true) { onChange(End.ORIGIN) }
            EndRow(t(R.string.routeSummary_dropoff), draft.destination, ru, first = false) { onChange(End.DESTINATION) }
        }
        when (val d = s.direction) {
            is Direction.Ready -> {
                val p = d.preview
                ElchiCard(background = c.highlight, padding = PaddingValues(horizontal = 16.dp, vertical = 2.dp)) {
                    CardRow(t(R.string.routeSummary_estimatedRoute), roadText(p.legDistanceM, p.legDurationS), first = true, strong = true)
                }
                ParcelRules.offRouteMeters(p)?.let { Note(t(R.string.app_location_offRoute, "km" to ParcelRules.km(it)), tone = Tone.WARN) }
                RouteMiniMap(s, draft)
            }
            Direction.Checking -> LoadingLine(t(R.string.home_checkingRoute))
            Direction.Mismatch -> Note(t(R.string.home_movePointHint), tone = Tone.ERR, title = t(R.string.app_location_previewMismatch))
            is Direction.Failed -> LoadFailed(t(R.string.routeSummary_estimatedRoute), d.error, vm::refreshDirection)
            Direction.Incomplete -> Unit
        }
        FormLabel(t(R.string.orderForm_review_window)) {
            WindowTiles(
                draft.start,
                draft.endTime,
                onEdge = { picking = it },
                startError = RouteIssue.WINDOW_START in shown || RouteIssue.WINDOW_PAST in shown,
                endError = RouteIssue.WINDOW_END in shown || RouteIssue.WINDOW_ORDER in shown,
                onSheet = false,
            )
            Text(windowHint(draft), style = Elchi.type.caption, color = c.muted)
        }
        FormLabel(t(R.string.common_price)) {
            PriceStepper(draft.priceDigits, { digits -> vm.edit { it.copy(priceDigits = digits) } }, error = RouteIssue.PRICE in shown, onSheet = false)
            Text(t(R.string.client_order_priceStepHint), style = Elchi.type.caption, color = c.muted)
        }
        val minor = ParcelRules.soumToMinor(draft.priceDigits)
        ElchiCard(background = c.highlight, padding = PaddingValues(horizontal = 16.dp, vertical = 2.dp)) {
            CardRow(t(R.string.common_total), minor?.let { soum(it) } ?: t(R.string.common_dash), first = true, detail = t(R.string.routeSummary_driversSendOffers), strong = true)
        }
    }
    picking?.let { edge ->
        WindowSheet(
            edge = edge,
            start = draft.start,
            end = draft.endTime,
            onStart = { value -> vm.edit { it.copy(windowStart = ParcelRules.formatLocal(value)) } },
            onEnd = { value -> vm.edit { it.copy(windowEnd = ParcelRules.formatLocal(value)) } },
            onDismiss = { picking = null },
        )
    }
}

/** A labelled block of the form (13sp label above its control, design `Jo'nash oynasi`, `Narx`). */
@Composable
internal fun FormLabel(label: String, content: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(label, style = Elchi.type.label, color = Elchi.colors.text)
        content()
    }
}

@Composable
private fun EndRow(key: String, place: Place?, ru: Boolean, first: Boolean, onChange: () -> Unit) {
    CardRow(
        key,
        place?.let { placeTitle(it, ru) } ?: t(R.string.app_route_noAddress),
        first = first,
        detail = place?.areaLine(ru),
        trailing = t(R.string.app_route_change),
        onTrailing = onChange,
        muted = place == null,
        strong = place != null,
    )
}

/** The place as a title: "Joriy joylashuv" for the phone's position, else the address or coordinates. */
@Composable
internal fun placeTitle(place: Place, ru: Boolean): String = if (place.current) t(R.string.home_currentLocation) else place.label(ru)

@Composable
internal fun issueText(issue: RouteIssue): String = t(
    when (issue) {
        RouteIssue.POINTS -> R.string.app_validation_bothPoints
        RouteIssue.WINDOW_START -> R.string.app_validation_windowStart
        RouteIssue.WINDOW_END -> R.string.client_order_err_windowEnd
        RouteIssue.WINDOW_PAST -> R.string.app_validation_windowPast
        RouteIssue.WINDOW_ORDER -> R.string.client_order_err_endAfterStart
        RouteIssue.SEATS -> R.string.client_taxi_err_seats
        RouteIssue.PRICE -> R.string.listingOwner_invalid_price
    },
)

// -- client-order-contact (Pochta step 2 / 3) ---------------------------------------------------------------------

private enum class ContactSide { SENDER, RECEIVER }

private enum class ContactSheet { SENDER, RECEIVER, TYPE, SIZE, BAN, PHOTO }

@Composable
private fun contactIssueText(issue: ContactIssue): String = when (issue) {
    ContactIssue.SENDER_NAME -> t(R.string.client_order_err_senderName)
    ContactIssue.SENDER_PHONE -> t(R.string.client_order_err_phone9)
    ContactIssue.RECEIVER_NAME -> t(R.string.client_order_err_receiverName)
    ContactIssue.RECEIVER_PHONE -> t(R.string.client_order_err_receiverPhone)
    ContactIssue.TYPE -> t(R.string.client_order_err_type)
    ContactIssue.SIZE -> t(R.string.client_order_err_size)
    ContactIssue.PHOTO -> "${t(R.string.orderForm_photoRequired).trimEnd('.')}."
}

/**
 * "Jo'natma ma'lumotlari": sender and receiver as contact cards (the phone's contacts, a new number or the account),
 * the parcel's type and size (sheets), its photo (inline, replace / delete), the prohibited-items list (a sheet) and
 * the optional comment. Tap-to-validate like the route step; an unconfirmed catalog keeps the button off.
 */
@Composable
fun OrderContactScreen(vm: ParcelRequestViewModel, ru: Boolean, editing: Boolean, account: Pair<String, String>, onBack: () -> Unit, onNext: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val c = Elchi.colors
    val d = s.draft
    val catalog = s.catalogValue
    val issues = ParcelRules.contactIssues(d)
    var showErrors by rememberSaveable { mutableStateOf(false) }
    if (issues.isEmpty()) showErrors = false
    val shown = if (showErrors) issues else emptyList()
    var sheet by rememberSaveable { mutableStateOf<ContactSheet?>(null) }
    val scroll = rememberScrollState()
    val scope = rememberCoroutineScope()
    val catalogBlocked = catalog?.confirmed != true
    // The pickers live on the screen, not in the chooser sheet: the sheet closes when one opens, and a launcher that
    // left the composition would lose its result.
    val context = LocalContext.current
    var captureUri by rememberSaveable { mutableStateOf<String?>(null) }
    val gallery = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri -> uri?.let(vm::uploadPhoto) }
    val camera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { saved ->
        val uri = captureUri
        if (saved && uri != null) vm.uploadPhoto(uri.toUri())
    }
    StepScaffold(
        title = t(R.string.client_order_contactTitle),
        onBack = onBack,
        step = 2 to 3,
        scrollState = scroll,
        footer = {
            ElchiButton(
                if (editing) t(R.string.client_order_saveAndReturn) else t(R.string.common_continue),
                {
                    if (issues.isEmpty()) onNext() else {
                        showErrors = true
                        scope.launch { scroll.animateScrollTo(0) }
                    }
                },
                Modifier.fillMaxWidth(),
                // The size catalog unconfirmed (Q140): nothing can be sent, so the button stays off.
                enabled = !catalogBlocked || s.catalog is Load.Loading,
                dimmed = issues.isNotEmpty() || s.photoUploading,
            )
        },
    ) {
        ErrorList(shown.map { contactIssueText(it) })
        ContactCard(
            t(R.string.orderForm_review_sender),
            d.senderName,
            d.senderDigits,
            error = ContactIssue.SENDER_NAME in shown || ContactIssue.SENDER_PHONE in shown,
        ) { sheet = ContactSheet.SENDER }
        ContactCard(
            t(R.string.orderForm_review_receiver),
            d.receiverName,
            d.receiverDigits,
            error = ContactIssue.RECEIVER_NAME in shown || ContactIssue.RECEIVER_PHONE in shown,
        ) { sheet = ContactSheet.RECEIVER }

        FormLabel(t(R.string.client_order_parcelSection)) {
            val type = ParcelType.entries.firstOrNull { it.value == d.parcelType && it != ParcelType.UNKNOWN }
            val category = catalog?.items?.firstOrNull { it.id == d.categoryId }
            ElchiCard(padding = PaddingValues(0.dp)) {
                SelectRow(t(R.string.client_order_typeRow), type?.let { parcelTypeLabel(it) }, null, first = true, error = ContactIssue.TYPE in shown) { sheet = ContactSheet.TYPE }
                SelectRow(t(R.string.client_order_sizeRow), category?.let { categoryName(it, ru) }, category?.let { categoryLimits(it) }, first = false, error = ContactIssue.SIZE in shown) { sheet = ContactSheet.SIZE }
            }
            when (val cat = s.catalog) {
                is Load.Failed -> LoadFailed(t(R.string.parcelCategory_loadFailed), cat.error, vm::loadCatalog)
                is Load.Ready -> if (!cat.value.confirmed) Note(t(R.string.parcelCategory_unconfirmed), tone = Tone.WARN)
                Load.Loading -> Unit
            }
        }

        FormLabel(t(R.string.orderForm_photoTitle)) {
            PhotoBlock(s, error = ContactIssue.PHOTO in shown, onPick = { sheet = ContactSheet.PHOTO }, onRemove = vm::removePhoto)
        }

        Row(
            Modifier.clip(RoundedCornerShape(8.dp)).clickable(role = Role.Button) { sheet = ContactSheet.BAN }.heightIn(min = 44.dp).padding(end = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            ElchiIconView(ElchiIcon.ALERT, c.accentText, size = 16.dp)
            Text(t(R.string.client_order_banLink), style = Elchi.type.label.copy(fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold), color = c.accentText)
        }

        FormLabel(t(R.string.client_order_noteLabel)) {
            NoteField(d.comment) { v -> vm.edit { it.copy(comment = v.take(ParcelRules.NOTE_MAX)) } }
            if (ParcelRules.noteHasContact(d.comment)) {
                Text(t(R.string.client_order_noteMasked), style = Elchi.type.caption, color = c.tone(Tone.WARN).fg)
            }
        }
        Note(t(R.string.orderForm_phonesHidden))
    }

    when (sheet) {
        ContactSheet.SENDER, ContactSheet.RECEIVER -> {
            val side = if (sheet == ContactSheet.SENDER) ContactSide.SENDER else ContactSide.RECEIVER
            ContactPickerSheet(side, if (side == ContactSide.SENDER) d.senderDigits else d.receiverDigits, account, onDismiss = { sheet = null }) { name, digits ->
                vm.edit { if (side == ContactSide.SENDER) it.copy(senderName = name, senderDigits = digits) else it.copy(receiverName = name, receiverDigits = digits) }
                sheet = null
            }
        }
        ContactSheet.TYPE -> FormSheet(t(R.string.orderForm_parcelType), onDismiss = { sheet = null }) {
            ParcelType.entries.filter { it != ParcelType.UNKNOWN }.forEach { type ->
                SheetOption(parcelTypeLabel(type), d.parcelType == type.value, {
                    vm.edit { it.copy(parcelType = type.value) }
                    sheet = null
                })
            }
        }
        ContactSheet.SIZE -> FormSheet(t(R.string.parcelCategory_label), onDismiss = { sheet = null }) {
            when (val cat = s.catalog) {
                Load.Loading -> LoadingLine(t(R.string.parcelCategory_loading))
                is Load.Failed -> LoadFailed(t(R.string.parcelCategory_loadFailed), cat.error, vm::loadCatalog)
                is Load.Ready -> if (!cat.value.confirmed) {
                    Note(t(R.string.parcelCategory_unconfirmed), tone = Tone.WARN)
                } else {
                    cat.value.items.orEmpty().forEach { item ->
                        SheetOption(categoryName(item, ru), d.categoryId == item.id, {
                            vm.edit { it.copy(categoryId = item.id) }
                            sheet = null
                        }, detail = categoryLimits(item), icon = categoryIcon(item.iconKey))
                    }
                    if (cat.value.synthetic == true) Text(t(R.string.parcelCategory_synthetic), style = Elchi.type.caption, color = c.tone(Tone.WARN).fg)
                }
            }
        }
        ContactSheet.BAN -> {
            val p = (s.policy as? Load.Ready)?.value
            val badge = p?.takeIf { it.approved }?.let { policy ->
                listOfNotNull(policy.label, policy.effectiveFrom?.let { shortDate(it) }).takeIf { it.size == 2 }?.let { t(R.string.client_order_banSince, "label" to it[0], "date" to it[1]) }
                    ?: policy.label
            }
            FormSheet(t(R.string.parcelPolicy_title), onDismiss = { sheet = null }, badge = badge) {
                PolicyRows(s.policy, vm::loadPolicy)
                ElchiButton(t(R.string.client_order_banOk), { sheet = null }, Modifier.fillMaxWidth().padding(top = 4.dp).height(52.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM)
            }
        }
        ContactSheet.PHOTO -> PhotoChooser(
            onCamera = {
                val file = PhotoCompressor(context).newCaptureFile()
                val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", file)
                captureUri = uri.toString()
                try {
                    camera.launch(uri)
                } catch (e: ActivityNotFoundException) {
                    gallery.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                }
            },
            onGallery = { gallery.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) },
            onDismiss = { sheet = null },
        )
        null -> Unit
    }
}

/** "Turi  Quti  ⌄" - a row of the parcel card that opens its sheet; a 3dp red edge marks a missing value. */
@Composable
private fun SelectRow(key: String, value: String?, detail: String?, first: Boolean, error: Boolean, onClick: () -> Unit) {
    val c = Elchi.colors
    Column {
        if (!first) Box(Modifier.fillMaxWidth().height(1.dp).background(c.field))
        Row(
            Modifier
                .fillMaxWidth()
                .heightIn(min = 54.dp)
                .clickable(role = Role.Button, onClick = onClick)
                .then(if (error) Modifier.drawBehind { drawRect(Color(0xFFE58A8A), size = androidx.compose.ui.geometry.Size(3.dp.toPx(), size.height)) } else Modifier)
                .padding(horizontal = 14.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(key, Modifier.width(62.dp), style = Elchi.type.label.copy(fontWeight = FontWeight.Normal), color = c.muted)
            Column(Modifier.weight(1f)) {
                Text(
                    value ?: t(R.string.client_order_choose),
                    style = Elchi.type.body.copy(fontWeight = if (value == null) FontWeight.Normal else FontWeight.SemiBold),
                    color = if (value == null) c.placeholder else c.text,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                if (detail != null) Text(detail, style = Elchi.type.caption, color = c.muted)
            }
            ElchiIconView(ElchiIcon.CHEV_D, c.placeholder, size = 16.dp)
        }
    }
}

/** The comment box (white card, two lines at least, design placeholder). */
@Composable
private fun NoteField(value: String, onValue: (String) -> Unit) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(18.dp)
    val label = t(R.string.client_order_noteLabel)
    val placeholder = t(R.string.client_order_notePlaceholder)
    BasicTextField(
        value = value,
        onValueChange = onValue,
        textStyle = Elchi.type.body.copy(color = c.text, lineHeight = 22.sp),
        cursorBrush = SolidColor(c.brand),
        keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
        modifier = Modifier
            .fillMaxWidth()
            .shadow(10.dp, shape, ambientColor = c.shadow, spotColor = c.shadow)
            .clip(shape)
            .background(c.card)
            .heightIn(min = 68.dp)
            .padding(horizontal = 14.dp, vertical = 12.dp)
            .semantics { contentDescription = label },
        decorationBox = { inner ->
            Box {
                if (value.isEmpty()) Text(placeholder, style = Elchi.type.body, color = c.placeholder)
                inner()
            }
        },
    )
}

/** "Posilka rasmi": the upload tile, the spinner while it uploads, or the photo card with replace and delete. */
@Composable
private fun PhotoBlock(s: ParcelRequestViewModel.State, error: Boolean, onPick: () -> Unit, onRemove: () -> Unit) {
    val c = Elchi.colors
    val local = s.draft.photoLocalPath
    val preview = remember(local) { local?.let { PhotoCompressor.previewBitmap(File(it), maxEdge = 300) } }
    val hasPhoto = s.draft.photoFileUrl != null
    val shape = RoundedCornerShape(18.dp)
    when {
        s.photoUploading -> LoadingLine(t(R.string.app_photo_loading))
        hasPhoto -> Row(
            Modifier.fillMaxWidth().shadow(10.dp, shape, ambientColor = c.shadow, spotColor = c.shadow).clip(shape).background(c.card).padding(8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Box(Modifier.size(64.dp).clip(RoundedCornerShape(14.dp)).background(c.field)) {
                if (preview != null) Image(preview.asImageBitmap(), t(R.string.orderForm_photoAlt), Modifier.fillMaxSize(), contentScale = ContentScale.Crop)
            }
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    ElchiIconView(ElchiIcon.CHECK_C, c.tone(Tone.OK).fg, size = 14.dp)
                    Text(t(R.string.orderForm_photoReady), style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold), color = c.tone(Tone.OK).noteText)
                }
                Text(local?.let { File(it).name } ?: "", style = Elchi.type.caption, color = c.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            CircleAction(ElchiIcon.REFRESH, t(R.string.client_order_photoReplaceShort), c.soft, c.softText, onPick)
            CircleAction(ElchiIcon.TRASH, t(R.string.common_delete), c.tone(Tone.ERR).bg, c.tone(Tone.ERR).fg, onRemove)
        }
        else -> Row(
            Modifier
                .fillMaxWidth()
                .heightIn(min = 62.dp)
                .clip(shape)
                .background(if (c.isDark) c.highlight else Color(0xFFF4FAFF))
                .drawBehind {
                    val stroke = 2.dp.toPx()
                    drawRoundRect(
                        color = if (error) Color(0xFFE58A8A) else Color(0xFF0096FF),
                        topLeft = androidx.compose.ui.geometry.Offset(stroke / 2, stroke / 2),
                        size = androidx.compose.ui.geometry.Size(size.width - stroke, size.height - stroke),
                        cornerRadius = androidx.compose.ui.geometry.CornerRadius(18.dp.toPx()),
                        style = androidx.compose.ui.graphics.drawscope.Stroke(stroke, pathEffect = androidx.compose.ui.graphics.PathEffect.dashPathEffect(floatArrayOf(7.dp.toPx(), 5.dp.toPx()))),
                    )
                }
                .clickable(role = Role.Button, onClick = onPick)
                .padding(horizontal = 14.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Box(Modifier.size(40.dp).clip(CircleShape).background(c.soft), contentAlignment = Alignment.Center) { ElchiIconView(ElchiIcon.CAMERA, c.accentText, size = 20.dp) }
            Column(verticalArrangement = Arrangement.spacedBy(1.dp)) {
                Text(t(R.string.orderForm_uploadPhoto), style = Elchi.type.secondary.copy(fontWeight = FontWeight.SemiBold), color = c.text)
                Text(t(R.string.client_order_photoDriverSees), style = Elchi.type.caption, color = c.muted)
            }
        }
    }
    s.photoError?.let { e -> Note(if (e is ApiException) errorText(e) else t(R.string.client_photo_unreadable), tone = Tone.ERR) }
}

@Composable
private fun CircleAction(icon: ElchiIcon, label: String, bg: Color, fg: Color, onClick: () -> Unit) {
    Box(
        Modifier.size(44.dp).clip(CircleShape).clickable(role = Role.Button, onClick = onClick).semantics { contentDescription = label },
        contentAlignment = Alignment.Center,
    ) {
        Box(Modifier.size(40.dp).clip(CircleShape).background(bg), contentAlignment = Alignment.Center) { ElchiIconView(icon, fg, size = 17.dp) }
    }
}

/** Camera or gallery, then the compress + upload pipeline (`cargo_photo`). */
@Composable
private fun PhotoChooser(onCamera: () -> Unit, onGallery: () -> Unit, onDismiss: () -> Unit) {
    FormSheet(t(R.string.orderForm_uploadPhoto), onDismiss = onDismiss) {
        ListCard {
            ListRow(t(R.string.client_photo_camera), icon = ElchiIcon.CAMERA, first = true, onClick = {
                onDismiss()
                onCamera()
            })
            ListRow(t(R.string.client_photo_gallery), icon = ElchiIcon.UPLOAD, onClick = {
                onDismiss()
                onGallery()
            })
        }
    }
}

/**
 * "Yuboruvchini tanlang" / "Qabul qiluvchini tanlang": search, the phone's own contact picker (no contacts
 * permission - the system picker grants the one row), "+ Yangi raqam" (name + 9 digits) and the account ("SIZ").
 * The prototype's in-app contact list and recent receivers have no data source (BLOCKED) and are left out.
 */
@Composable
private fun ContactPickerSheet(side: ContactSide, currentDigits: String, account: Pair<String, String>, onDismiss: () -> Unit, onPick: (String, String) -> Unit) {
    val c = Elchi.colors
    val context = LocalContext.current
    val toast = LocalFlowToast.current
    var query by rememberSaveable { mutableStateOf("") }
    var manual by rememberSaveable { mutableStateOf(false) }
    var name by rememberSaveable { mutableStateOf("") }
    var digits by rememberSaveable { mutableStateOf("") }
    val pickedSender = t(R.string.client_order_pickedSender)
    val pickedReceiver = t(R.string.client_order_pickedReceiver)
    val invalid = t(R.string.client_order_manualInvalid)
    val pick: (String, String) -> Unit = { n, p ->
        onPick(n, p)
        toast.show((if (side == ContactSide.SENDER) pickedSender else pickedReceiver).replace("{name}", n))
    }
    val device = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val uri = result.data?.data ?: return@rememberLauncherForActivityResult
        val row = runCatching {
            context.contentResolver.query(uri, arrayOf(ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME, ContactsContract.CommonDataKinds.Phone.NUMBER), null, null, null)?.use { cursor ->
                if (cursor.moveToFirst()) cursor.getString(0).orEmpty() to cursor.getString(1).orEmpty() else null
            }
        }.getOrNull()
        val (n, number) = row ?: return@rememberLauncherForActivityResult
        val local = ParcelRules.contactDigits(number)
        if (ParcelRules.nameValid(n) && ParcelRules.phoneValid(local)) {
            pick(n.trim(), local)
        } else {
            // Not an Uzbek mobile number (or no name): the manual form opens with what was read.
            manual = true
            name = n.trim()
            digits = local
            toast.show(invalid)
        }
    }
    FormSheet(if (side == ContactSide.SENDER) t(R.string.client_order_pickSender) else t(R.string.client_order_pickReceiver), onDismiss = onDismiss) {
        ElchiField(query, { query = it }, placeholder = t(R.string.client_order_contactSearch), icon = ElchiIcon.SEARCH, minHeight = 48.dp)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ElchiButton(t(R.string.client_order_deviceContacts), {
                runCatching { device.launch(Intent(Intent.ACTION_PICK, ContactsContract.CommonDataKinds.Phone.CONTENT_URI)) }
            }, Modifier.weight(1f), ButtonVariant.SOFT, ButtonSize.MEDIUM, icon = ElchiIcon.PHONE, horizontalPadding = 10.dp)
            ElchiButton(t(R.string.client_order_newNumber), { manual = !manual }, Modifier.weight(1f), if (manual) ButtonVariant.NAVY else ButtonVariant.NEUTRAL, ButtonSize.MEDIUM, horizontalPadding = 10.dp)
        }
        if (manual) {
            val ok = ParcelRules.nameValid(name) && ParcelRules.phoneValid(digits)
            Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(sheetWell()).padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                ElchiField(name, { name = it.take(120) }, placeholder = t(R.string.client_order_manualName), minHeight = 46.dp, keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Words, imeAction = ImeAction.Next))
                ElchiField(
                    digits,
                    { digits = it.filter(Char::isDigit).take(9) },
                    prefix = "+998",
                    placeholder = "90 123 45 67",
                    monospace = true,
                    minHeight = 46.dp,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone, imeAction = ImeAction.Done),
                    visualTransformation = UzPhoneTransformation,
                )
                ElchiButton(t(R.string.client_order_choosePick), { if (ok) pick(name.trim(), digits) else toast.show(invalid) }, Modifier.fillMaxWidth(), size = ButtonSize.MEDIUM, dimmed = !ok)
            }
        }
        val me = account.takeIf { (n, p) -> ParcelRules.nameValid(n) && ParcelRules.phoneValid(p) }
        val q = query.trim().lowercase().replace(" ", "")
        val meShown = me?.takeIf { (n, p) -> q.isEmpty() || n.lowercase().replace(" ", "").contains(q) || p.contains(q) }
        if (meShown != null) {
            Text(t(R.string.client_order_groupYou), Modifier.padding(top = 4.dp), style = Elchi.type.caption.copy(fontWeight = FontWeight.SemiBold, letterSpacing = 0.7.sp), color = c.muted)
            val (n, p) = meShown
            val on = currentDigits == p
            val shape = RoundedCornerShape(18.dp)
            Row(
                Modifier
                    .fillMaxWidth()
                    .clip(shape)
                    .border(1.dp, c.line, shape)
                    .background(if (on) c.highlight else c.card)
                    .clickable(role = Role.Button) { pick(n.trim(), p) }
                    .padding(horizontal = 14.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Box(Modifier.size(38.dp).clip(CircleShape).background(c.brand), contentAlignment = Alignment.Center) {
                    Text(initials(n), style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold), color = c.onBrand)
                }
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
                    Text(t(R.string.client_order_me, "name" to n.trim()), style = Elchi.type.secondary.copy(fontSize = 14.5.sp, fontWeight = FontWeight.SemiBold), color = c.text)
                    Text("+998 ${ParcelRules.groupPhone(p)}", style = Elchi.type.caption.copy(fontSize = 12.5.sp, fontFamily = FontFamily.Monospace), color = c.muted)
                }
                if (on) ElchiIconView(ElchiIcon.CHECK_C, c.tone(Tone.OK).fg, size = 18.dp)
            }
        } else if (!manual) {
            Text(t(R.string.client_order_contactNone), Modifier.fillMaxWidth().padding(vertical = 14.dp), style = Elchi.type.label.copy(fontWeight = FontWeight.Normal), color = c.muted, textAlign = TextAlign.Center)
        }
    }
}

/** The prohibited-items rows (§5.2) inside their sheet, with the states; "not approved" never reads as "all allowed". */
@Composable
private fun PolicyRows(policy: Load<ParcelPolicyDTO>, retry: () -> Unit) {
    val c = Elchi.colors
    when (policy) {
        Load.Loading -> LoadingLine(t(R.string.common_loading))
        is Load.Failed -> {
            Note(t(R.string.parcelPolicy_loadFailed), tone = Tone.ERR)
            ElchiButton(t(R.string.common_retry), retry, Modifier.fillMaxWidth(), ButtonVariant.GHOST, ButtonSize.MEDIUM, icon = ElchiIcon.REFRESH)
        }
        is Load.Ready -> {
            val p = policy.value
            when {
                !p.approved -> Note(t(R.string.parcelPolicy_unconfirmed), tone = Tone.WARN)
                p.items.isNullOrEmpty() -> Note(t(R.string.parcelPolicy_empty), tone = Tone.GRAY)
                else -> p.items.forEach { item ->
                    val applies = item.appliesTo?.let { tOrNull("parcelPolicy.appliesTo.$it") }
                    val source = item.sourceRef?.let { ref ->
                        item.sourceCheckedOn?.let { t(R.string.parcelPolicy_sourceChecked, "source" to ref, "date" to shortDate(it)) } ?: t(R.string.parcelPolicy_source, "source" to ref)
                    }
                    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Box(Modifier.fillMaxWidth().height(1.dp).background(c.field))
                        Text(tOrNull("parcelPolicy.category.${item.category}") ?: item.category, Modifier.padding(top = 10.dp), style = Elchi.type.caption, color = c.muted)
                        Text(item.title, style = Elchi.type.secondary.copy(fontWeight = FontWeight.Medium), color = c.text)
                        listOfNotNull(applies, source).joinToString(" · ").ifEmpty { null }?.let { Text(it, Modifier.padding(bottom = 2.dp), style = Elchi.type.caption, color = c.muted) }
                    }
                }
            }
        }
    }
}

// -- client-order-review (Pochta 3 / 3, Taksi 1 / 1) --------------------------------------------------------------

/** Where a review row's pencil leads. */
enum class EditTarget { ROUTE, CONTACT }

@Composable
fun OrderReviewScreen(
    vm: ParcelRequestViewModel,
    ru: Boolean,
    account: Pair<String, String>,
    onBack: () -> Unit,
    onEdit: (EditTarget) -> Unit,
    onPublished: () -> Unit,
) {
    val s by vm.state.collectAsStateWithLifecycle()
    val d = s.draft
    val p = s.preview
    LaunchedEffect(s.published) { if (s.published != null) onPublished() }
    val ready = if (d.taxi) TaxiRules.readyToPublish(d, s.directionReady, Instant.now()) else ParcelRules.readyToPublish(d, s.directionReady, Instant.now())
    val route = { onEdit(EditTarget.ROUTE) }
    val contact = { onEdit(EditTarget.CONTACT) }
    StepScaffold(
        title = t(R.string.orderForm_review_title),
        onBack = onBack,
        step = if (d.taxi) 1 to 1 else 3 to 3,
        footer = {
            s.publishError?.let { PublishError(it) }
            if (!ready && !s.publishing) Note(t(if (d.taxi) R.string.orderForm_review_incompletePassenger else R.string.orderForm_review_incompleteParcel), tone = Tone.WARN)
            ElchiButton(
                if (s.publishing) t(R.string.client_order_publishing) else t(R.string.orderForm_review_publish),
                vm::publish,
                Modifier.fillMaxWidth(),
                enabled = ready || s.publishing,
                dimmed = s.publishing,
            )
            ElchiButton(t(R.string.listingOwner_edit), route, Modifier.fillMaxWidth().height(40.dp), ButtonVariant.GHOST, ButtonSize.MEDIUM, enabled = !s.publishing)
        },
    ) {
        val category = s.catalogValue?.items?.firstOrNull { it.id == d.categoryId }
        val type = ParcelType.entries.firstOrNull { it.value == d.parcelType && it != ParcelType.UNKNOWN }
        ElchiCard(padding = PaddingValues(horizontal = 16.dp, vertical = 2.dp)) {
            ReviewRow(t(R.string.routeSummary_direction), regionLine(d, ru), detail = p?.corridorName, first = true, onEdit = route)
            d.origin?.let { ReviewRow(t(R.string.orderForm_review_pickupPlace), placeTitle(it, ru), detail = placeDetail(it, ru), onEdit = route) }
            d.destination?.let {
                ReviewRow(t(if (d.taxi) R.string.client_taxi_dropoffPlace else R.string.orderForm_review_dropoffPlace), placeTitle(it, ru), detail = placeDetail(it, ru), onEdit = route)
            }
            p?.let { ReviewRow(t(R.string.routeSummary_estimatedRoute), roadText(it.legDistanceM, it.legDurationS)) }
            ReviewRow(t(R.string.orderForm_review_window), windowLine(d), onEdit = route)
            val minor = ParcelRules.soumToMinor(d.priceDigits)
            if (d.taxi) {
                val seats = TaxiRules.seatCount(d)
                ReviewRow(
                    t(R.string.client_taxi_seats),
                    if (seats >= TaxiRules.WHOLE_CABIN) t(R.string.client_taxi_wholeCabinSeats) else t(R.string.orderForm_review_peopleCount, "count" to seats),
                    onEdit = route,
                )
                ReviewRow(
                    t(R.string.common_price),
                    minor?.let { "${seats.coerceAtLeast(1)} × ${soum(it)} = ${soum(TaxiRules.totalMinor(it, TaxiRules.billedSeats(d)))}" } ?: "",
                    detail = t(R.string.orderForm_review_driversSendOffers),
                    onEdit = route,
                )
                ReviewRow(
                    t(R.string.client_taxi_passenger),
                    account.first,
                    detail = t(R.string.client_taxi_accountData, "phone" to "+998 ${ParcelRules.groupPhone(account.second)}"),
                )
                if (d.comment.isNotBlank()) ReviewRow(t(R.string.listingOwner_commentLabel), ParcelRules.maskNote(d.comment.trim()))
                return@ElchiCard
            }
            ReviewRow(t(R.string.common_price), minor?.let { soum(it) } ?: "", detail = t(R.string.orderForm_review_driversSendOffers), onEdit = route)
            ReviewRow(
                t(R.string.orderForm_review_parcel),
                type?.let { parcelTypeLabel(it) } ?: "",
                detail = category?.let { "${categoryName(it, ru)} · ${categoryLimits(it)}" },
                onEdit = contact,
            )
            ReviewRow(t(R.string.orderForm_review_sender), d.senderName.trim(), detail = "+998 ${ParcelRules.groupPhone(d.senderDigits)}", onEdit = contact)
            ReviewRow(t(R.string.orderForm_review_receiver), d.receiverName.trim(), detail = "+998 ${ParcelRules.groupPhone(d.receiverDigits)}", onEdit = contact)
            ReviewRow(
                t(R.string.orderForm_photoTitle),
                t(if (d.photoFileUrl != null) R.string.orderForm_review_uploaded else R.string.client_order_photoNotUploaded),
                muted = d.photoFileUrl == null,
                onEdit = contact,
            )
            if (d.comment.isNotBlank()) ReviewRow(t(R.string.listingOwner_commentLabel), ParcelRules.maskNote(d.comment.trim()), onEdit = contact)
        }
    }
}

/** "Toshkent shahri → Samarqand viloyati" (design `routeLine`: the regions). */
@Composable
internal fun regionLine(d: ParcelDraft, ru: Boolean): String =
    "${d.origin?.region(ru) ?: t(R.string.direction_from)} → ${d.destination?.region(ru) ?: t(R.string.direction_to)}"

/** "28.09, 09:00 – 28.09, 18:00" */
@Composable
internal fun windowLine(d: ParcelDraft): String {
    val start = d.start ?: return ""
    val end = d.endTime ?: return ""
    return "${ParcelRules.displayShort(start)} – ${ParcelRules.displayShort(end)}"
}

/** "Chilonzor, Toshkent shahri" (ADR-0028: every end is a point, there is no verified stop). */
@Composable
private fun placeDetail(place: Place, ru: Boolean): String = place.areaLine(ru)

// -- client-success -----------------------------------------------------------------------------------------------

/**
 * "Buyurtma e'lon qilindi": the summary card (route, window, total - the listing has no human-readable number, so
 * none is shown), one note per server warning, "Buyurtmalarimga o'tish" and "Yangi buyurtma".
 */
@Composable
fun OrderSuccessScreen(vm: ParcelRequestViewModel, ru: Boolean, onDone: () -> Unit, onNewOrder: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val c = Elchi.colors
    val d = s.draft
    SystemBarIcons(dark = !c.isDark)
    // Back from here is the same as the button: the published request is done, the next one starts clean.
    BackHandler(onBack = onDone)
    Column(Modifier.fillMaxSize().background(c.page)) {
        Column(
            Modifier.weight(1f).statusBarsPadding().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp).padding(top = 12.dp, bottom = 20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Column(Modifier.fillMaxWidth().padding(top = 40.dp, bottom = 10.dp, start = 8.dp, end = 8.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Box(Modifier.size(84.dp).clip(CircleShape).background(c.tone(Tone.OK).bg), contentAlignment = Alignment.Center) {
                    ElchiIconView(ElchiIcon.CHECK_C, c.tone(Tone.OK).fg, size = 40.dp)
                }
                Text(t(R.string.orderForm_success_title), style = Elchi.type.title.copy(fontSize = 26.sp, lineHeight = 31.sp), color = c.text, textAlign = TextAlign.Center)
                Text(
                    "${t(R.string.orderForm_success_waiting)}. ${t(R.string.orderForm_success_notify)}.",
                    Modifier.widthIn(max = 300.dp),
                    style = Elchi.type.secondary,
                    color = c.muted,
                    textAlign = TextAlign.Center,
                )
            }
            if (d.origin != null && d.destination != null) {
                val minor = ParcelRules.soumToMinor(d.priceDigits)
                val total = minor?.let { soum(if (d.taxi) TaxiRules.totalMinor(it, TaxiRules.billedSeats(d)) else it) }
                ElchiCard(padding = PaddingValues(horizontal = 16.dp, vertical = 12.dp)) {
                    Text(regionLine(d, ru), style = Elchi.type.bodyStrong, color = c.text)
                    Text(listOfNotNull(windowLine(d).ifEmpty { null }, total).joinToString(" · "), style = Elchi.type.label.copy(fontWeight = FontWeight.Normal), color = c.muted)
                }
            }
            // One note per server warning, each in its own words (e.g. the comment's contacts were masked, Q43).
            s.published?.warnings.orEmpty().forEach { warning ->
                Note(tOrNull("warning.${warning.code}") ?: warning.message, tone = Tone.WARN)
            }
        }
        Column(Modifier.fillMaxWidth().background(c.card)) {
            Box(Modifier.fillMaxWidth().height(1.dp).background(c.line))
            Column(Modifier.navigationBarsPadding().padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 4.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                ElchiButton(t(R.string.orderForm_success_toOrders), onDone, Modifier.fillMaxWidth())
                ElchiButton(t(R.string.client_order_newOrder), onNewOrder, Modifier.fillMaxWidth().height(40.dp), ButtonVariant.GHOST, ButtonSize.MEDIUM)
            }
        }
    }
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

// -- parcel type and size ------------------------------------------------------------------------------------

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

internal fun categoryIcon(iconKey: String): ElchiIcon = when {
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

/** `2026-09-01` / an ISO instant -> `01.09.2026`. */
private fun shortDate(value: String): String = runCatching {
    val date = if (value.length == 10) LocalDate.parse(value) else Instant.parse(value).atZone(ParcelRules.TASHKENT).toLocalDate()
    "%02d.%02d.%d".format(date.dayOfMonth, date.monthValue, date.year)
}.getOrDefault(value)

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

