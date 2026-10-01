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
import androidx.compose.ui.text.font.FontWeight
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
fun DriverProfileFormScreen(vm: DriverProfileFormViewModel, onBack: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val c = Elchi.colors
    val issues = if (s.showIssues) s.issues else emptySet()
    val required = t(R.string.driver_form_required)
    val positive = t(R.string.driver_form_positiveNumber)
    val lockHint = t(R.string.driverProfileForm_vehicleLockedHint)
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
                ElchiField(
                    f.fullName, { v -> vm.edit { it.copy(fullName = v) } },
                    label = t(R.string.driverProfileForm_fullName),
                    error = required.takeIf { FormIssue.NAME in issues },
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Words),
                )
                if (s.locked) Note(t(R.string.driverProfileForm_vehicleLockedBody), tone = Tone.BLUE, title = t(R.string.driverProfileForm_vehicleLockedTitle))
                ElchiField(
                    f.carModel, { v -> vm.edit { it.copy(carModel = v) } },
                    label = t(R.string.driverProfileForm_carModel), placeholder = t(R.string.driverProfileForm_carModelPlaceholder),
                    locked = s.locked, hint = lockHint.takeIf { s.locked }, error = required.takeIf { FormIssue.MODEL in issues },
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Words),
                )
                ElchiField(
                    f.carColor, { v -> vm.edit { it.copy(carColor = v) } },
                    label = t(R.string.driverProfileForm_carColor), placeholder = t(R.string.driverProfileForm_carColorPlaceholder),
                    locked = s.locked, hint = lockHint.takeIf { s.locked }, error = required.takeIf { FormIssue.COLOR in issues },
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
                    label = t(R.string.driverProfileForm_passengerSeats),
                    locked = s.capacityLocked, hint = lockHint.takeIf { s.capacityLocked },
                    error = t(R.string.listingOwner_invalid_seats).takeIf { FormIssue.SEATS in issues },
                    keyboardOptions = number,
                )
                ElchiField(
                    f.cargoKg, { v -> vm.edit { it.copy(cargoKg = digits(v)) } },
                    label = t(R.string.driverProfileForm_cargoKg),
                    locked = s.capacityLocked, hint = lockHint.takeIf { s.capacityLocked }, error = positive.takeIf { FormIssue.CARGO_KG in issues },
                    keyboardOptions = number,
                )
                ElchiField(
                    f.cargoLitres, { v -> vm.edit { it.copy(cargoLitres = digits(v)) } },
                    label = t(R.string.driverProfileForm_cargoLitres),
                    locked = s.capacityLocked, hint = lockHint.takeIf { s.capacityLocked }, error = positive.takeIf { FormIssue.CARGO_LITRES in issues },
                    keyboardOptions = number,
                )
                if (!s.locked) Note(t(R.string.driver_profile_lockWarning), tone = Tone.WARN)
                s.vehicle?.let { vehicle ->
                    val status = tOrNull("vehicleStatus.${vehicle.verificationStatus}") ?: vehicle.verificationStatus
                    ElchiCard {
                        CardRow(t(R.string.driverProfileForm_vehicleStatus), "${vehicle.makeModel} · ${vehicle.plateMasked} · $status", first = true)
                    }
                }
                if (s.locked && s.vehicle?.verificationStatus != "approved") {
                    Text(t(R.string.driverProfileForm_routesAfterReview), style = Elchi.type.caption, color = c.muted)
                }
            }
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
fun DriverDocumentsScreen(vm: DriverDocumentsViewModel, onBack: () -> Unit) {
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
                ElchiCard(padding = PaddingValues(horizontal = 16.dp, vertical = 14.dp)) {
                    Text(
                        t(R.string.driverDocs_submittedCount, "submitted" to DriverRules.submitted(rows.value), "total" to DocType.entries.size),
                        style = Elchi.type.bodyStrong, color = c.text,
                    )
                    Text(t(R.string.driverDocs_intro), Modifier.padding(top = 2.dp), style = Elchi.type.caption, color = c.muted)
                }
                rows.value.forEach { row ->
                    DocumentRow(
                        row = row,
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
private fun DocumentRow(row: DocRow, uploading: Boolean, error: Throwable?, onUpload: () -> Unit, onPreview: () -> Unit) {
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
    ) {
        error?.let { Note(driverErrorText(it, row.type.maxMb), tone = Tone.ERR) }
        if (uploading) {
            LoadingLine(t(R.string.driver_docs_uploading))
        } else {
            ElchiButton(
                t(if (row.state == DocState.MISSING) R.string.driverDocs_upload else R.string.driverDocs_reupload),
                onUpload,
                Modifier.fillMaxWidth(),
                if (rejected) ButtonVariant.PRIMARY else ButtonVariant.NEUTRAL,
                ButtonSize.MEDIUM,
                icon = ElchiIcon.UPLOAD,
            )
        }
    }
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
