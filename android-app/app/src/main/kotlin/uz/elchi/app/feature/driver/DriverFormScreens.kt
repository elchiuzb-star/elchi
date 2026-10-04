package uz.elchi.app.feature.driver

import android.content.ActivityNotFoundException
import android.graphics.BitmapFactory
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.sp
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.core.content.FileProvider
import androidx.core.net.toUri
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.elchi.app.R
import uz.elchi.app.api.FilesApi
import uz.elchi.app.feature.client.Load
import uz.elchi.app.feature.client.LoadFailed
import uz.elchi.app.feature.client.LoadingLine
import uz.elchi.app.feature.client.PhotoCompressor
import uz.elchi.app.feature.client.StepScaffold
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.CardRow
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiField
import uz.elchi.app.ui.components.ItemCard
import uz.elchi.app.ui.components.ItemLine
import uz.elchi.app.ui.components.ListCard
import uz.elchi.app.ui.components.ListRow
import uz.elchi.app.ui.components.LoadingState
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone

/** A driver failure as a sentence: the driver-specific ones first ([DriverRules.errorKey]), else the generic text. */
@Composable
internal fun driverErrorText(error: Throwable, maxMb: Int? = null): String {
    if (error is DocumentFileError) {
        return when (error.kind) {
            DocumentFileError.Kind.TOO_LARGE -> t(R.string.driver_error_fileTooLarge, "max" to (maxMb ?: 0))
            DocumentFileError.Kind.WRONG_TYPE -> t(R.string.error_DRIVER_DOCUMENT_INVALID_TYPE)
            DocumentFileError.Kind.UNREADABLE -> t(R.string.client_photo_unreadable)
        }
    }
    if (error is PhotoCompressor.UnreadableImage) return t(R.string.client_photo_unreadable)
    return DriverRules.errorKey(error)?.let { tOrNull(it, "max" to (maxMb ?: 0)) } ?: errorText(error)
}

// -- driver-profile-form --------------------------------------------------------------------------------------

/**
 * `driver-profile-form` "Haydovchi profili". First time: every field open and the warning that the car locks once
 * saved. After that (the profile has a plate, Q94): the car read-only with a lock and "ask an operator", the
 * vehicle's review status, and Save sends the name only.
 */
@Composable
fun DriverProfileFormScreen(vm: DriverProfileFormViewModel, onBack: () -> Unit, onHelp: () -> Unit = {}) {
    val s by vm.state.collectAsStateWithLifecycle()
    val c = Elchi.colors
    val issues = if (s.showIssues) s.issues else emptySet()
    val required = t(R.string.driver_form_required)
    val lockHint = t(R.string.driverProfileForm_vehicleLockedHint)
    // A save went through: back to where the driver came from (design 06 §2.12); the banner says what happened.
    LaunchedEffect(s.finished) { if (s.finished) onBack() }
    StepScaffold(
        title = t(R.string.driverProfileForm_title),
        onBack = onBack,
        footer = {
            s.error?.let { Note(driverErrorText(it), tone = Tone.ERR) }
            ElchiButton(t(R.string.common_save), vm::save, Modifier.fillMaxWidth(), enabled = s.canSave, loading = s.saving)
        },
    ) {
        val load = s.load
        when {
            s.profile == null && load is Load.Failed -> LoadFailed(t(R.string.driverProfileForm_title), load.error, vm::load)
            s.profile == null -> LoadingState(count = 3)
            else -> {
                val f = s.form
                // The lock first, above the fields (design 06 §2.1): locked = who can change it, open = it will lock.
                if (s.locked) Note(t(R.string.driverProfileForm_vehicleLockedBody), tone = Tone.BLUE, title = t(R.string.driverProfileForm_vehicleLockedTitle))
                else Note(t(R.string.driver_profile_lockWarning), tone = Tone.WARN)
                ElchiField(
                    f.fullName, { v -> vm.edit { it.copy(fullName = v) } },
                    label = t(R.string.driverProfileForm_fullName),
                    error = t(R.string.driver_form_nameRequired).takeIf { FormIssue.NAME in issues },
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Words),
                )
                ElchiField(
                    f.carModel, { v -> vm.edit { it.copy(carModel = v) } },
                    label = t(R.string.driverProfileForm_carModel), placeholder = t(R.string.driverProfileForm_carModelPlaceholder),
                    locked = s.locked, hint = lockHint.takeIf { s.locked }, error = t(R.string.driver_form_modelRequired).takeIf { FormIssue.MODEL in issues },
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Words),
                )
                ElchiField(
                    f.carColor, { v -> vm.edit { it.copy(carColor = v) } },
                    label = t(R.string.driverProfileForm_carColor), placeholder = t(R.string.driverProfileForm_carColorPlaceholder),
                    locked = s.locked, hint = lockHint.takeIf { s.locked }, error = t(R.string.driver_form_colorRequired).takeIf { FormIssue.COLOR in issues },
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
                )
                ElchiField(
                    f.plate, { v -> vm.edit { it.copy(plate = v.uppercase()) } },
                    label = t(R.string.driverProfileForm_plateNumber), placeholder = t(R.string.driverProfileForm_plateNumberPlaceholder),
                    locked = s.locked, hint = lockHint.takeIf { s.locked }, error = required.takeIf { FormIssue.PLATE in issues },
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Characters, autoCorrectEnabled = false),
                    monospace = true,
                )
                val number = KeyboardOptions(keyboardType = KeyboardType.Number)
                val digits: (String) -> String = { v -> v.filter(Char::isDigit).take(4) }
                ElchiField(
                    f.seats, { v -> vm.edit { it.copy(seats = digits(v).take(1)) } },
                    label = t(R.string.driverProfileForm_passengerSeats), placeholder = "4",
                    locked = s.capacityLocked, hint = lockHint.takeIf { s.capacityLocked },
                    error = t(R.string.driver_form_seatsRange).takeIf { FormIssue.SEATS in issues },
                    keyboardOptions = number,
                )
                // Required, 0 allowed: 0 = no parcels (sent as "no cargo capacity").
                ElchiField(
                    f.cargoKg, { v -> vm.edit { it.copy(cargoKg = digits(v)) } },
                    label = t(R.string.driverProfileForm_cargoKg),
                    locked = s.capacityLocked, hint = lockHint.takeIf { s.capacityLocked },
                    error = t(R.string.driver_form_cargoKgRequired).takeIf { FormIssue.CARGO_KG in issues },
                    keyboardOptions = number,
                )
                ElchiField(
                    f.cargoLitres, { v -> vm.edit { it.copy(cargoLitres = digits(v)) } },
                    label = t(R.string.driverProfileForm_cargoLitres),
                    locked = s.capacityLocked, hint = lockHint.takeIf { s.capacityLocked },
                    error = required.takeIf { FormIssue.CARGO_LITRES in issues },
                    keyboardOptions = number,
                )
                s.vehicle?.let { vehicle ->
                    val status = tOrNull("vehicleStatus.${vehicle.verificationStatus}") ?: vehicle.verificationStatus
                    ElchiCard {
                        CardRow(t(R.string.driverProfileForm_vehicleStatus), "${vehicle.makeModel} · ${vehicle.plateMasked} · $status", first = true)
                    }
                }
                if (s.locked && s.vehicle?.verificationStatus != "approved") {
                    Text(t(R.string.driverProfileForm_routesAfterReview), style = Elchi.type.caption, color = c.muted)
                }
                // Only an operator changes a stored car (Q94): the Help screen's ticket form is the way to ask.
                if (s.locked) ElchiButton(t(R.string.driver_form_askOperator), onHelp, Modifier.fillMaxWidth(), ButtonVariant.NEUTRAL, icon = ElchiIcon.HEAD)
            }
        }
    }
    if (s.confirmingLock) LockConfirmDialog(s.form, onConfirm = vm::confirmLock, onDismiss = vm::cancelLock)
}

/**
 * Q94's last check before the save that locks the car: what will be stored, "Ha, saqlash" / "Tekshirib chiqaman".
 * The dialog is its own window with the phone's language, so every label is resolved here first.
 */
@Composable
private fun LockConfirmDialog(form: DriverForm, onConfirm: () -> Unit, onDismiss: () -> Unit) {
    val c = Elchi.colors
    val title = t(R.string.driver_form_lockTitle)
    val text = t(R.string.driver_form_lockText)
    val confirm = t(R.string.driver_form_lockConfirm)
    val review = t(R.string.driver_form_lockReview)
    val rows = DriverRules.lockSummary(form).map { row ->
        val label = tOrNull(row.labelKey).orEmpty()
        val value = if (row.params.isEmpty()) row.value else t(R.string.driver_form_cargoSummary, *row.params.toList().toTypedArray())
        label to value
    }
    Dialog(onDismissRequest = onDismiss) {
        Column(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(28.dp)).background(c.card).padding(horizontal = 18.dp, vertical = 22.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(title, Modifier.semantics { heading() }, style = Elchi.type.title.copy(fontSize = 19.sp, lineHeight = 24.sp), color = c.text)
            Text(text, style = Elchi.type.secondary, color = c.muted)
            Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(c.page).padding(horizontal = 12.dp, vertical = 4.dp)) {
                rows.forEachIndexed { i, (label, value) ->
                    if (i > 0) Box(Modifier.fillMaxWidth().height(1.dp).background(c.outline))
                    Row(Modifier.fillMaxWidth().padding(vertical = 7.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Text(label, Modifier.weight(1f), style = Elchi.type.label.copy(fontWeight = FontWeight.Normal), color = c.muted)
                        Text(value, style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold), color = c.text, textAlign = TextAlign.End)
                    }
                }
            }
            ElchiButton(confirm, onConfirm, Modifier.fillMaxWidth().height(52.dp), ButtonVariant.PRIMARY, ButtonSize.MEDIUM)
            ElchiButton(review, onDismiss, Modifier.fillMaxWidth().height(46.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM)
        }
    }
}

// -- driver-documents -------------------------------------------------------------------------------------------

/**
 * `driver-documents` "Hujjatlar": N / 5 sent, then one named row per document with its state, the reason when it
 * was rejected, the file limits, and upload / re-upload (camera, gallery, and a PDF where the type allows one).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DriverDocumentsScreen(vm: DriverDocumentsViewModel, onBack: () -> Unit, account: DriverStatus? = null) {
    val s by vm.state.collectAsStateWithLifecycle()
    val c = Elchi.colors
    val context = LocalContext.current
    LaunchedEffect(Unit) { vm.refresh() }
    var picking by rememberSaveable { mutableStateOf<String?>(null) }
    var target by rememberSaveable { mutableStateOf<String?>(null) }
    var captureUri by rememberSaveable { mutableStateOf<String?>(null) }
    var previewing by remember { mutableStateOf<DocRow?>(null) }
    val targetType = target?.let(DocType::from)
    val gallery = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri -> if (uri != null && targetType != null) vm.upload(targetType, uri, asFile = false) }
    val camera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { saved ->
        val uri = captureUri
        if (saved && uri != null && targetType != null) vm.upload(targetType, uri.toUri(), asFile = false)
    }
    val pdf = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri -> if (uri != null && targetType != null) vm.upload(targetType, uri, asFile = true) }

    StepScaffold(title = t(R.string.driverDocs_title), onBack = onBack, onRefresh = vm::refresh, refreshing = s.refreshing && s.rows is Load.Ready) {
        when (val rows = s.rows) {
            Load.Loading -> LoadingState(count = 3)
            is Load.Failed -> LoadFailed(t(R.string.driverDocs_title), rows.error, vm::refresh)
            is Load.Ready -> {
                val submitted = DriverRules.submitted(rows.value)
                val total = DocType.entries.size
                ElchiCard(padding = PaddingValues(horizontal = 16.dp, vertical = 14.dp)) {
                    Text(
                        t(R.string.driverDocs_submittedCount, "submitted" to submitted, "total" to total),
                        style = Elchi.type.bodyStrong, color = c.text,
                    )
                    // n / 5 as a 6dp bar (design 06 §3.1).
                    Box(Modifier.padding(top = 8.dp).fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp)).background(c.field)) {
                        Box(Modifier.fillMaxWidth(submitted.toFloat() / total).height(6.dp).clip(RoundedCornerShape(3.dp)).background(c.brand))
                    }
                    Text(t(R.string.driverDocs_intro), Modifier.padding(top = 8.dp), style = Elchi.type.caption, color = c.muted)
                }
                rows.value.forEach { row ->
                    DocumentRow(
                        row = row,
                        canUpload = DriverRules.canUpload(row.state, account),
                        uploading = row.type in s.uploading,
                        error = s.failed?.takeIf { it.first == row.type }?.second,
                        onUpload = { picking = row.type.wire },
                        onPreview = { previewing = row },
                    )
                }
            }
        }
    }

    val sheetType = picking?.let(DocType::from)
    if (sheetType != null) {
        // The sheet is its own window with the phone's language: labels are resolved here, in the app's.
        val sheetTitle = tOrNull("docType.${sheetType.wire}").orEmpty()
        val hint = tOrNull(DriverRules.fileHintKey(sheetType), "max" to sheetType.maxMb).orEmpty()
        val cameraLabel = t(R.string.client_photo_camera)
        val galleryLabel = t(R.string.client_photo_gallery)
        val pdfLabel = t(R.string.driver_docs_pdf)
        ModalBottomSheet(onDismissRequest = { picking = null }, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true), containerColor = c.page) {
            Column(Modifier.padding(horizontal = 16.dp).padding(bottom = 24.dp).navigationBarsPadding(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text(sheetTitle, style = Elchi.type.section, color = c.text)
                    Text(hint, style = Elchi.type.caption, color = c.muted)
                }
                ListCard {
                    ListRow(cameraLabel, icon = ElchiIcon.CAMERA, first = true, onClick = {
                        picking = null
                        target = sheetType.wire
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
                        picking = null
                        target = sheetType.wire
                        gallery.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                    })
                    if (sheetType.pdfAllowed) {
                        ListRow(pdfLabel, icon = ElchiIcon.FILE, onClick = {
                            picking = null
                            target = sheetType.wire
                            runCatching { pdf.launch(arrayOf(FilesApi.PDF)) }
                        })
                    }
                }
            }
        }
    }

    previewing?.let { row -> DocumentPreview(vm, row) { previewing = null } }
}

@Composable
private fun DocumentRow(row: DocRow, canUpload: Boolean, uploading: Boolean, error: Throwable?, onUpload: () -> Unit, onPreview: () -> Unit) {
    val c = Elchi.colors
    val rejected = row.state == DocState.REJECTED
    val lines = buildList {
        row.reason?.let { add(ItemLine(t(R.string.driverDocs_rejectionReason, "reason" to it), c.tone(Tone.ERR).fg)) }
        add(ItemLine(tOrNull(DriverRules.fileHintKey(row.type), "max" to row.type.maxMb).orEmpty()))
    }
    ItemCard(
        title = tOrNull("docType.${row.type.wire}") ?: row.type.wire,
        icon = if (row.type.pdfAllowed) ElchiIcon.FILE else ElchiIcon.CAMERA,
        sub = tOrNull("docHint.${row.type.wire}"),
        badge = (tOrNull("docState.${row.state.wire}") ?: row.state.wire) to DriverRules.docTone(row.state),
        lines = lines,
        onClick = if (row.fileUrl != null && !uploading) onPreview else null,
        outline = c.tone(Tone.ERR).fg.takeIf { rejected },
        // Approved rows and decided accounts have nothing to upload (design 06 §3.5, §3.6): no footer at all.
        footer = if (!canUpload && !uploading && error == null) null else {
            {
                error?.let { Note(driverErrorText(it, row.type.maxMb), tone = Tone.ERR) }
                if (uploading) {
                    LoadingLine(t(R.string.driver_docs_uploading))
                } else if (canUpload) {
                    ElchiButton(
                        t(if (row.state == DocState.MISSING) R.string.driverDocs_upload else R.string.driverDocs_reupload),
                        onUpload,
                        Modifier.fillMaxWidth(),
                        if (DriverRules.uploadPrimary(row.state)) ButtonVariant.PRIMARY else ButtonVariant.SOFT,
                        ButtonSize.MEDIUM,
                        icon = ElchiIcon.UPLOAD,
                    )
                }
            }
        },
    )
}

/** The uploaded file behind a row: its signed link read now (links are short-lived). A PDF has no picture here. */
@Composable
private fun DocumentPreview(vm: DriverDocumentsViewModel, row: DocRow, onDismiss: () -> Unit) {
    val c = Elchi.colors
    val title = tOrNull("docType.${row.type.wire}").orEmpty()
    val loading = t(R.string.common_loading)
    val close = t(R.string.common_close)
    val noPicture = t(R.string.driver_docs_pdf)
    val image by produceState<Load<ImageBitmap?>>(Load.Loading, row.fileUrl) {
        val bytes = row.fileUrl?.let { vm.preview(it) }
        value = Load.Ready(bytes?.let { BitmapFactory.decodeByteArray(it, 0, it.size)?.asImageBitmap() })
    }
    Dialog(onDismissRequest = onDismiss) {
        Column(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(28.dp)).background(c.card).padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text(title, style = Elchi.type.section.copy(fontWeight = FontWeight.SemiBold), color = c.text)
            Box(Modifier.fillMaxWidth().heightIn(min = 120.dp).clip(RoundedCornerShape(18.dp)).background(c.field), contentAlignment = Alignment.Center) {
                when (val state = image) {
                    is Load.Ready -> {
                        val bitmap = state.value
                        if (bitmap != null) Image(bitmap, title, Modifier.fillMaxWidth(), contentScale = ContentScale.FillWidth)
                        else Row(Modifier.padding(16.dp)) { Text(noPicture, style = Elchi.type.label, color = c.muted) }
                    }
                    else -> LoadingLine(loading)
                }
            }
            ElchiButton(close, onDismiss, Modifier.fillMaxWidth(), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM)
        }
    }
}
