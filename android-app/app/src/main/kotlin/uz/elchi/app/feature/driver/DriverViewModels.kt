package uz.elchi.app.feature.driver

import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import uz.elchi.app.api.DriverApi
import uz.elchi.app.api.DriverProfileDTO
import uz.elchi.app.api.FilesApi
import uz.elchi.app.api.generated.AttributionRequest
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.api.generated.VehicleDTO
import uz.elchi.app.feature.client.ActionKeys
import uz.elchi.app.feature.client.Load
import uz.elchi.app.feature.client.PromoRules
import uz.elchi.app.deeplink.PendingReferral
import uz.elchi.app.deeplink.ReferralRules
import uz.elchi.app.ui.components.BannerCenter
import uz.elchi.app.ui.components.BannerText
import uz.elchi.app.ui.components.BannerTone

private suspend fun <T> attempt(block: suspend () -> T): Result<T> = try {
    Result.success(block())
} catch (e: CancellationException) {
    throw e
} catch (e: Exception) {
    Result.failure(e)
}

/** A driver failure for the app banner: the driver sentence when there is one ([DriverRules.errorKey]), else the generic one. */
internal fun driverBanner(error: Throwable, maxMb: Int? = null): BannerText =
    DriverRules.errorKey(error)?.let { key -> BannerText.Key(key, params = maxMb?.let { mapOf("max" to it.toString()) }.orEmpty()) }
        ?: BannerText.Error(error)

/**
 * The signed-in driver as every tab sees it: the v1 profile (status = the gate, Q96), the wallet balance
 * (viewable before approval, Q22) and the v2 vehicles. One per person for the whole driver flow; screens that
 * change the record call [refresh] when they are done.
 */
class DriverViewModel(
    private val api: ElchiApi,
    private val driver: DriverApi,
    private val banners: BannerCenter,
    private val referral: PendingReferral? = null,
) : ViewModel() {

    data class State(
        val profile: Load<DriverProfileDTO> = Load.Loading,
        /** The referral confirmation from the home row is running. */
        val referralBusy: Boolean = false,
        /** `available_minor`; Failed / Loading show "—". */
        val wallet: Load<Long> = Load.Loading,
        val refreshing: Boolean = false,
        val availabilityBusy: Boolean = false,
        /** The five document rows (home's checklist and the derived status); null = not read (yet). */
        val documents: List<DocRow>? = null,
        /** The v2 vehicles (step 1 is done once the car is there too); null = not read (yet). */
        val vehicles: List<VehicleDTO>? = null,
    ) {
        val loaded: DriverProfileDTO? get() = (profile as? Load.Ready)?.value
        val status: DriverStatus? get() = loaded?.let { DriverStatus.from(it.verificationStatus) }

        /** The car is stored (v1 lock and the v2 vehicle): "Profilni ko'rish", checklist step 1 ticked. */
        val profileDone: Boolean get() = DriverRules.profileDone(loaded, vehicles)

        /** The status as the driver reads it (design 06 §1.5), not the raw server word. */
        val verify: VerifyState? get() = status?.let { DriverRules.verifyState(it, profileDone, documents) }
    }

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()
    private val keys = ActionKeys()

    /** The referral code kept from a link (`driverHome.pendingReferral` row); null = no row. */
    val pendingReferral: StateFlow<String?> = referral?.pending ?: MutableStateFlow(null)

    init {
        refresh()
    }

    /**
     * The home row's tap: `POST /referrals/attribution {code, audience: driver}` with an Idempotency-Key.
     * - Made: `link.referralApplied`, and the code is forgotten.
     * - The programme is off (`403 FEATURE_DISABLED`): the programme-off sentence; the code is kept for later.
     * - Refused for good (invalid code, already attributed, window closed...): the server's sentence; forgotten.
     * - Offline, 429, 5xx: the error; kept, the row stays to try again.
     */
    fun confirmReferral() {
        val store = referral ?: return
        val code = store.pending.value ?: return
        if (_state.value.referralBusy) return
        val scope = "attribute:driver:$code"
        _state.update { it.copy(referralBusy = true) }
        banners.startAction()
        viewModelScope.launch {
            val result = attempt { api.attribute(AttributionRequest(audience = AUDIENCE, code = code), keys.key(scope)) }
            val error = result.exceptionOrNull()
            keys.settle(scope, error)
            if (ReferralRules.forgetAfter(error, code, store.pending.value)) store.forget()
            banners.endAction()
            when {
                error == null -> banners.show(BannerTone.OK, BannerText.Key("link.referralApplied"))
                PromoRules.isProgramOff(error) -> banners.show(BannerTone.INFO, BannerText.Key("promoScreen.programOff"))
                else -> banners.error(error)
            }
            _state.update { it.copy(referralBusy = false) }
        }
    }

    /** The row's X: the code is forgotten on this phone, nothing is sent (design 06 §1.1). */
    fun forgetReferral() {
        if (_state.value.referralBusy) return
        referral?.forget()
    }

    fun refresh() {
        if (_state.value.refreshing) return
        _state.update { it.copy(refreshing = true) }
        viewModelScope.launch {
            val profile = async { attempt { driver.profile() } }
            val wallet = async { attempt { api.getMyWallet().data.availableMinor } }
            val documents = async { attempt { DriverRules.docRows(driver.documents()) } }
            val vehicles = async { attempt { api.listMyVehicles().data } }
            profile.await()
                .onSuccess { p -> _state.update { it.copy(profile = Load.Ready(p)) } }
                // A failed re-read keeps what is on screen; only the first read shows the error.
                .onFailure { e -> _state.update { if (it.profile is Load.Ready) it else it.copy(profile = Load.Failed(e)) } }
            wallet.await()
                .onSuccess { minor -> _state.update { it.copy(wallet = Load.Ready(minor)) } }
                .onFailure { e -> _state.update { if (it.wallet is Load.Ready) it else it.copy(wallet = Load.Failed(e)) } }
            // A failed re-read keeps the last rows; never read = null (the server's word decides the status).
            documents.await().onSuccess { rows -> _state.update { it.copy(documents = rows) } }
            vehicles.await().onSuccess { list -> _state.update { it.copy(vehicles = list) } }
            _state.update { it.copy(refreshing = false) }
        }
    }

    /** Optimistic: the switch moves at once and goes back if the server refuses. */
    fun setAvailability(on: Boolean) {
        val s = _state.value
        val profile = s.loaded ?: return
        if (s.availabilityBusy || !DriverRules.availabilityEnabled(DriverStatus.from(profile.verificationStatus), profile.isAvailable)) return
        _state.update { it.copy(profile = Load.Ready(profile.copy(isAvailable = on)), availabilityBusy = true) }
        banners.startAction()
        viewModelScope.launch {
            attempt { driver.setAvailability(on) }
                .onSuccess { stored ->
                    _state.update { st -> st.copy(profile = (st.profile as? Load.Ready)?.let { Load.Ready(it.value.copy(isAvailable = stored)) } ?: st.profile) }
                    banners.show(BannerTone.OK, BannerText.Key(DriverRules.availabilityDoneKey(stored)))
                }
                .onFailure { e ->
                    _state.update { st -> st.copy(profile = (st.profile as? Load.Ready)?.let { Load.Ready(it.value.copy(isAvailable = profile.isAvailable)) } ?: st.profile) }
                    banners.show(BannerTone.ERR, driverBanner(e))
                }
            banners.endAction()
            _state.update { it.copy(availabilityBusy = false) }
        }
    }

    private companion object {
        const val AUDIENCE = "driver"
    }
}

/**
 * "Haydovchi profili": the name (always editable) and the car, entered once (Q94). Save runs [DriverRules.savePlan]:
 * v1 PATCH, then the v2 vehicle if it is still missing, then both are read again - the form is locked from then on.
 */
class DriverProfileFormViewModel(
    private val api: ElchiApi,
    private val driver: DriverApi,
    private val banners: BannerCenter,
    private val onChanged: () -> Unit,
) : ViewModel() {

    data class State(
        val load: Load<Unit> = Load.Loading,
        val profile: DriverProfileDTO? = null,
        val vehicles: List<VehicleDTO> = emptyList(),
        val form: DriverForm = DriverForm(),
        val saving: Boolean = false,
        val error: Throwable? = null,
        /** Validation marks show after the first save attempt, not while typing the first letters. */
        val showIssues: Boolean = false,
        /** The Q94 lock dialog is open: the save waits for "Ha, saqlash". */
        val confirmingLock: Boolean = false,
        /** A save went through: the screen goes back (design 06 §2.12). */
        val finished: Boolean = false,
    ) {
        val locked: Boolean get() = DriverRules.vehicleLocked(profile)
        val capacityLocked: Boolean get() = DriverRules.capacityLocked(vehicles)
        val vehicle: VehicleDTO? get() = DriverRules.ownVehicle(profile, vehicles)
        val issues: Set<FormIssue> get() = DriverRules.issues(form, locked, capacityLocked)

        /** Something to send: a changed name, or the first save, or the vehicle still missing. */
        val canSave: Boolean get() = profile != null && !saving &&
            DriverRules.savePlan(form, profile, vehicles).let { it.patch != null || it.vehicle != null }
    }

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()
    private val keys = ActionKeys()

    init {
        load()
    }

    fun load() {
        viewModelScope.launch {
            if (_state.value.profile == null) _state.update { it.copy(load = Load.Loading) }
            reload().onFailure { e -> _state.update { if (it.profile == null) it.copy(load = Load.Failed(e)) else it } }
        }
    }

    /** Profile + vehicles again; the form follows the server for what it stores and keeps the rest as typed. */
    private suspend fun reload(): Result<Unit> {
        val profile = attempt { driver.profile() }
        val vehicles = attempt { api.listMyVehicles().data }
        val p = profile.getOrElse { return Result.failure(it) }
        val v = vehicles.getOrElse { return Result.failure(it) }
        _state.update { it.copy(load = Load.Ready(Unit), profile = p, vehicles = v, form = DriverRules.formFrom(p, v, it.form)) }
        return Result.success(Unit)
    }

    fun edit(change: (DriverForm) -> DriverForm) = _state.update { it.copy(form = change(it.form), error = null) }

    /** "Saqlash": checks the form, then asks before the save that locks the car (Q94), else saves at once. */
    fun save() {
        val s = _state.value
        val profile = s.profile ?: return
        if (s.saving) return
        if (s.issues.isNotEmpty()) {
            _state.update { it.copy(showIssues = true) }
            return
        }
        if (DriverRules.locksCar(DriverRules.savePlan(s.form, profile, s.vehicles))) {
            _state.update { it.copy(confirmingLock = true, showIssues = true) }
            return
        }
        send()
    }

    /** "Ha, saqlash" in the lock dialog. */
    fun confirmLock() {
        if (!_state.value.confirmingLock) return
        _state.update { it.copy(confirmingLock = false) }
        send()
    }

    /** "Tekshirib chiqaman": back to the form, nothing sent. */
    fun cancelLock() = _state.update { it.copy(confirmingLock = false) }

    private fun send() {
        val s = _state.value
        val profile = s.profile ?: return
        if (s.saving || s.issues.isNotEmpty()) return
        val plan = DriverRules.savePlan(s.form, profile, s.vehicles)
        val locking = DriverRules.locksCar(plan)
        _state.update { it.copy(saving = true, error = null, showIssues = true) }
        banners.startAction()
        viewModelScope.launch {
            var failure: Throwable? = null
            plan.patch?.let { patch -> attempt { driver.updateProfile(patch) }.onFailure { failure = it } }
            // The v2 car only after v1 stored the same one: a refused plate must not leave a v2 row behind.
            if (failure == null) {
                plan.vehicle?.let { vehicle ->
                    val result = attempt { api.createVehicle(vehicle, keys.key(VEHICLE)) }
                    keys.settle(VEHICLE, result.exceptionOrNull())
                    result.onFailure { failure = it }
                }
            }
            // Read both back whatever happened: after a v1 success the form is locked even if v2 failed.
            reload()
            val error = failure
            _state.update { it.copy(saving = false, error = error, finished = error == null) }
            banners.endAction()
            if (error == null) banners.show(BannerTone.OK, BannerText.Key(if (locking) "driver.form.savedLocked" else "driverProfileForm.saved"))
            onChanged()
        }
    }

    private companion object {
        const val VEHICLE = "vehicle"
    }
}

/** Reads a picked file: an image through the Stage 02 pipeline (JPEG, long edge 1600), a PDF as it is. */
interface DocumentSource {
    class Picked(val bytes: ByteArray, val mimeType: String?)

    suspend fun image(uri: Uri): ByteArray

    /** At most [maxBytes] + 1 bytes are read: enough to know the file is too large. */
    suspend fun file(uri: Uri, maxBytes: Long): Picked
}

/** A file the app refuses before sending it (the server would say the same). */
class DocumentFileError(val kind: Kind) : Exception(kind.name) {
    enum class Kind { TOO_LARGE, WRONG_TYPE, UNREADABLE }
}

/**
 * "Hujjatlar": five named slots (§17.1). Upload = `POST /files/upload` with the slot's type, then
 * `POST /driver/documents`; the first one moves the driver to `pending`, which [onChanged] carries to home.
 */
class DriverDocumentsViewModel(
    private val driver: DriverApi,
    private val files: FilesApi,
    private val source: DocumentSource,
    private val banners: BannerCenter,
    private val onChanged: () -> Unit,
) : ViewModel() {

    data class State(
        val rows: Load<List<DocRow>> = Load.Loading,
        val refreshing: Boolean = false,
        val uploading: Set<DocType> = emptySet(),
        /** The last upload failure, shown under its row until the next try. */
        val failed: Pair<DocType, Throwable>? = null,
    )

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()

    fun refresh() {
        if (_state.value.refreshing) return
        _state.update { it.copy(refreshing = true) }
        viewModelScope.launch {
            attempt { driver.documents() }
                .onSuccess { docs -> _state.update { it.copy(rows = Load.Ready(DriverRules.docRows(docs))) } }
                .onFailure { e -> _state.update { if (it.rows is Load.Ready) it else it.copy(rows = Load.Failed(e)) } }
            _state.update { it.copy(refreshing = false) }
        }
    }

    fun upload(type: DocType, uri: Uri, asFile: Boolean) {
        if (type in _state.value.uploading) return
        _state.update { it.copy(uploading = it.uploading + type, failed = if (it.failed?.first == type) null else it.failed) }
        viewModelScope.launch {
            val result = attempt {
                val (bytes, mime) = if (asFile) {
                    val picked = source.file(uri, type.maxBytes)
                    picked.bytes to (picked.mimeType ?: "")
                } else {
                    source.image(uri) to FilesApi.JPEG
                }
                if (!DriverRules.mimeAllowed(type, mime)) throw DocumentFileError(DocumentFileError.Kind.WRONG_TYPE)
                if (!DriverRules.sizeAllowed(type, bytes.size.toLong())) throw DocumentFileError(DocumentFileError.Kind.TOO_LARGE)
                val name = "${type.wire}.${if (mime == FilesApi.PDF) "pdf" else "jpg"}"
                val uploaded = files.upload(bytes, name, type.wire, mime)
                driver.submitDocument(type.wire, uploaded.fileUrl, uploaded.mimeType ?: mime, uploaded.sizeBytes ?: bytes.size.toLong())
            }
            _state.update { it.copy(uploading = it.uploading - type) }
            result
                .onSuccess {
                    banners.show(BannerTone.OK, BannerText.Key("driverDocs.uploadedForReview", keyParams = mapOf("type" to "docType.${type.wire}")))
                    refresh()
                    onChanged()
                }
                .onFailure { e -> _state.update { it.copy(failed = type to e) } }
        }
    }

    /** The signed link of an uploaded image, for the preview (links are short-lived: read just before). */
    suspend fun preview(url: String): ByteArray? = attempt { files.download(url) }.getOrNull()
}
