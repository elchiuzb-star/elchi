package uz.elchi.app.feature.client

import android.net.Uri
import android.util.Log
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.ElchiJson
import uz.elchi.app.api.FilesApi
import uz.elchi.app.api.generated.ApiWarning
import uz.elchi.app.api.generated.DirectionPreviewDTO
import uz.elchi.app.api.generated.EffectiveFlagValuesDTO
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.api.generated.ListingCommand
import uz.elchi.app.api.generated.ListingDTO
import uz.elchi.app.api.generated.ParcelCategoryCatalogDTO
import uz.elchi.app.api.generated.ParcelPolicyDTO
import java.time.Instant
import java.util.UUID

/** A server lookup the screens wait on. */
sealed interface Load<out T> {
    data object Loading : Load<Nothing>
    data class Ready<T>(val value: T) : Load<T>
    data class Failed(val error: Throwable) : Load<Nothing>
}

/**
 * Q88 "can ELCHI carry between these two places?" - asked automatically once both ends are marked. Ready is the
 * only state that lets the person continue.
 */
sealed interface Direction {
    data object Incomplete : Direction
    data object Checking : Direction
    data class Ready(val preview: DirectionPreviewDTO) : Direction
    /** 409 ROUTE_MISMATCH: no confirmed route serves both points. */
    data object Mismatch : Direction
    data class Failed(val error: Throwable) : Direction
}

enum class ServiceMode { PARCEL, TAXI }

/**
 * The create/publish attempt, saved with the draft so a retry after a timeout (or a process restart) reuses the
 * same `Idempotency-Key` and, once the draft listing exists, never creates a second one.
 */
@Serializable
data class PublishProgress(
    val createKey: String? = null,
    val listingId: String? = null,
    val listingVersion: Long? = null,
    val publishKey: String? = null,
    val createWarnings: List<ApiWarning> = emptyList(),
)

data class Published(val listing: ListingDTO, val warnings: List<ApiWarning>)

/**
 * Stage 02, one instance for the signed-in client's flow: the parcel request draft (home -> route -> contacts ->
 * parcel -> photo -> review), the direction preview, the effective flags of the matched corridor, the size catalog
 * and prohibited-items policy, the photo upload and the create + publish command.
 */
class ParcelRequestViewModel(
    private val api: ElchiApi,
    private val files: FilesApi,
    private val photos: PhotoCompressor,
    private val saved: SavedStateHandle,
    private val now: () -> Instant = Instant::now,
) : ViewModel() {

    data class State(
        val draft: ParcelDraft = ParcelDraft(),
        val direction: Direction = Direction.Incomplete,
        /** Null while unknown; a failed read is [flagsFailed] and counts as "off". */
        val flags: EffectiveFlagValuesDTO? = null,
        val flagsLoading: Boolean = false,
        val flagsFailed: Boolean = false,
        val mode: ServiceMode = ServiceMode.PARCEL,
        val catalog: Load<ParcelCategoryCatalogDTO> = Load.Loading,
        val policy: Load<ParcelPolicyDTO> = Load.Loading,
        val photoUploading: Boolean = false,
        val photoError: Throwable? = null,
        val publishing: Boolean = false,
        val publishError: Throwable? = null,
        val published: Published? = null,
    ) {
        val preview: DirectionPreviewDTO? get() = (direction as? Direction.Ready)?.preview
        val directionReady: Boolean get() = preview != null

        /** Parcel allowed on the matched corridor: true / false, or null while the corridor's flags are loading. */
        val parcelEnabled: Boolean? get() = when {
            flagsFailed -> false
            flagsLoading || flags == null -> null
            else -> flags.parcelEnabled
        }

        val passengerEnabled: Boolean get() = !flagsFailed && flags?.passengerEnabled == true

        /** "Yo'nalishni ko'rish": both places on a confirmed route and the parcel service open there. */
        val canContinueFromHome: Boolean get() = directionReady && mode == ServiceMode.PARCEL && parcelEnabled == true

        val catalogValue: ParcelCategoryCatalogDTO? get() = (catalog as? Load.Ready)?.value
    }

    private val _state = MutableStateFlow(State(draft = restoreDraft()))
    val state: StateFlow<State> = _state.asStateFlow()
    private var progress: PublishProgress = saved.get<String>(KEY_PROGRESS)?.let { runCatching { ElchiJson.decodeFromString(PublishProgress.serializer(), it) }.getOrNull() } ?: PublishProgress()
    private var directionJob: Job? = null
    private var flagsJob: Job? = null
    /** The corridor the current flags were read for; null = the country scope. */
    private var flagsCorridor: String? = null

    init {
        loadFlags(corridorId = null)
        refreshDirection()
        loadCatalog()
        loadPolicy()
    }

    private fun restoreDraft(): ParcelDraft {
        val restored = saved.get<String>(KEY_DRAFT)?.let { runCatching { ElchiJson.decodeFromString(ParcelDraft.serializer(), it) }.getOrNull() }
        return restored ?: freshDraft()
    }

    /** Tomorrow 09:00-18:00 in Tashkent; the contacts are filled by [prefillSender]. */
    private fun freshDraft(): ParcelDraft {
        val (start, end) = ParcelRules.defaultWindow(now())
        return ParcelDraft(windowStart = ParcelRules.formatLocal(start), windowEnd = ParcelRules.formatLocal(end))
    }

    /** The signed-in person as the sender, only while the fields are still empty (never overwrites an edit). */
    fun prefillSender(name: String?, phone: String?) = edit { d ->
        d.copy(
            senderName = d.senderName.ifEmpty { name.orEmpty().trim() },
            senderDigits = d.senderDigits.ifEmpty { ParcelRules.localDigits(phone) },
        )
    }

    /** Every draft change goes through here: saved for process death, and a changed body needs a new create key. */
    fun edit(transform: (ParcelDraft) -> ParcelDraft) {
        val before = _state.value.draft
        val after = transform(before)
        if (after == before) return
        _state.update { it.copy(draft = after, publishError = null) }
        saved[KEY_DRAFT] = ElchiJson.encodeToString(ParcelDraft.serializer(), after)
        // A draft listing created from the old body no longer matches: the next publish writes a new one.
        if (progress != PublishProgress()) saveProgress(PublishProgress())
    }

    fun setEnd(end: End, place: Place) {
        edit { it.withEnd(end, place) }
        refreshDirection()
    }

    fun setMode(mode: ServiceMode) = _state.update { it.copy(mode = mode) }

    // -- direction + flags ---------------------------------------------------------------------------------------

    fun refreshDirection() {
        val draft = _state.value.draft
        val origin = draft.origin
        val destination = draft.destination
        directionJob?.cancel()
        if (origin == null || destination == null) {
            _state.update { it.copy(direction = Direction.Incomplete) }
            if (flagsCorridor != null) loadFlags(corridorId = null)
            return
        }
        _state.update { it.copy(direction = Direction.Checking) }
        directionJob = viewModelScope.launch {
            val direction = try {
                val preview = api.previewDirection(origin.lat, origin.lng, origin.districtId, destination.lat, destination.lng, destination.districtId).data
                Direction.Ready(preview)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (e is ApiException && e.code == ROUTE_MISMATCH) Direction.Mismatch else Direction.Failed(e)
            }
            _state.update { it.copy(direction = direction) }
            // Flags are read for the corridor that actually serves this pair (not the country scope); without a
            // corridor the previous one's flags no longer apply.
            if (direction is Direction.Ready) loadFlags(direction.preview.corridorId) else if (flagsCorridor != null) loadFlags(corridorId = null)
        }
    }

    private fun loadFlags(corridorId: String?) {
        flagsJob?.cancel()
        flagsCorridor = corridorId
        _state.update { it.copy(flagsLoading = true, flagsFailed = false) }
        flagsJob = viewModelScope.launch {
            try {
                val flags = api.effectiveFlags(corridorId).data.flags
                _state.update { it.copy(flags = flags, flagsLoading = false, mode = if (flags.passengerEnabled) it.mode else ServiceMode.PARCEL) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                // Unknown flags count as "off": nothing is offered that the server may refuse.
                _state.update { it.copy(flags = null, flagsLoading = false, flagsFailed = true, mode = ServiceMode.PARCEL) }
            }
        }
    }

    // -- catalog + policy ----------------------------------------------------------------------------------------

    fun loadCatalog() {
        _state.update { it.copy(catalog = Load.Loading) }
        viewModelScope.launch {
            val result = load { api.parcelCategories().data }
            _state.update { it.copy(catalog = result) }
            // A saved category that is no longer in the (confirmed) catalog cannot be sent.
            val catalog = (result as? Load.Ready)?.value ?: return@launch
            val chosen = _state.value.draft.categoryId
            if (chosen != null && (!catalog.confirmed || catalog.items.orEmpty().none { it.id == chosen })) edit { it.copy(categoryId = null) }
        }
    }

    fun loadPolicy() {
        _state.update { it.copy(policy = Load.Loading) }
        viewModelScope.launch {
            val result = load { api.parcelPolicy().data }
            _state.update { it.copy(policy = result) }
        }
    }

    // -- photo ---------------------------------------------------------------------------------------------------

    /** Compresses the picked or captured image (max ~1600 px, JPEG) and uploads it as `cargo_photo`. */
    fun uploadPhoto(uri: Uri) {
        if (_state.value.photoUploading) return
        _state.update { it.copy(photoUploading = true, photoError = null) }
        viewModelScope.launch {
            try {
                val photo = photos.compress(uri)
                val uploaded = files.uploadCargoPhoto(photo.bytes, photo.file.name)
                edit { it.copy(photoFileUrl = uploaded.fileUrl, photoLocalPath = photo.file.absolutePath) }
                _state.update { it.copy(photoUploading = false) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                // ApiException, PhotoCompressor.UnreadableImage, or an unexpected answer: the screen says so.
                Log.w(TAG, "parcel photo not uploaded", e)
                _state.update { it.copy(photoUploading = false, photoError = e) }
            }
        }
    }

    // -- create + publish ----------------------------------------------------------------------------------------

    fun canPublish(): Boolean = ParcelRules.readyToPublish(_state.value.draft, _state.value.directionReady, now())

    /**
     * Create the draft listing, then publish it. One `Idempotency-Key` per action, kept until the action is known
     * to have failed for good; a create that went through is never repeated - a failed publish is retried on the
     * same draft.
     */
    fun publish() {
        val s = _state.value
        if (s.publishing || !canPublish()) return
        _state.update { it.copy(publishing = true, publishError = null) }
        viewModelScope.launch {
            try {
                if (progress.listingId == null) {
                    val key = progress.createKey ?: newKey().also { saveProgress(progress.copy(createKey = it)) }
                    val created = api.createListing(ParcelRules.buildListingCreate(s.draft), key)
                    saveProgress(progress.copy(listingId = created.data.id, listingVersion = created.data.version, createWarnings = created.warnings))
                }
                val published = publishCreated()
                val warnings = (progress.createWarnings + published.second).distinctBy { it.code }
                saveProgress(PublishProgress())
                _state.update { it.copy(publishing = false, published = Published(published.first, warnings)) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (e is ApiException && e.isDefinitive()) {
                    // The same key would only replay this refusal; the next attempt is a new action.
                    saveProgress(if (progress.listingId == null) progress.copy(createKey = null) else progress.copy(publishKey = null))
                }
                _state.update { it.copy(publishing = false, publishError = e) }
            }
        }
    }

    /** Publishes the saved draft listing; on VERSION_CONFLICT re-reads it once (it may already be published). */
    private suspend fun publishCreated(): Pair<ListingDTO, List<ApiWarning>> {
        val id = checkNotNull(progress.listingId)
        val key = progress.publishKey ?: newKey().also { saveProgress(progress.copy(publishKey = it)) }
        return try {
            val result = api.publishListing(id, ListingCommand(expectedVersion = checkNotNull(progress.listingVersion)), key)
            result.data to result.warnings
        } catch (e: ApiException) {
            if (e.code != VERSION_CONFLICT) throw e
            val current = api.getListing(id).data.jsonObject
            val status = current["status"]?.jsonPrimitive?.content
            if (status == "published") return ElchiJson.decodeFromJsonElement(ListingDTO.serializer(), current) to emptyList()
            val version = current["version"]?.jsonPrimitive?.longOrNull ?: current["version"]?.jsonPrimitive?.intOrNull?.toLong() ?: throw e
            val retryKey = newKey()
            saveProgress(progress.copy(listingVersion = version, publishKey = retryKey))
            val result = api.publishListing(id, ListingCommand(expectedVersion = version), retryKey)
            result.data to result.warnings
        }
    }

    /** After the success screen: a clean draft for the next request (contacts are prefilled again by the screen). */
    fun startOver() {
        _state.value.draft.photoLocalPath?.let { runCatching { java.io.File(it).delete() } }
        val fresh = freshDraft()
        saved[KEY_DRAFT] = ElchiJson.encodeToString(ParcelDraft.serializer(), fresh)
        saveProgress(PublishProgress())
        directionJob?.cancel()
        _state.update { it.copy(draft = fresh, direction = Direction.Incomplete, published = null, publishError = null, photoError = null) }
        loadFlags(corridorId = null)
    }

    private suspend fun <T> load(block: suspend () -> T): Load<T> = try {
        Load.Ready(block())
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        Load.Failed(e)
    }

    private fun saveProgress(value: PublishProgress) {
        progress = value
        saved[KEY_PROGRESS] = ElchiJson.encodeToString(PublishProgress.serializer(), value)
    }

    private fun newKey(): String = UUID.randomUUID().toString()

    /** A 4xx that repeating the same request cannot change (not a rate limit, not "still in progress"). */
    private fun ApiException.isDefinitive(): Boolean = status in 400..499 && code !in RETRYABLE

    private companion object {
        const val TAG = "ParcelRequest"
        const val KEY_DRAFT = "parcel.draft"
        const val KEY_PROGRESS = "parcel.publish"
        const val ROUTE_MISMATCH = "ROUTE_MISMATCH"
        const val VERSION_CONFLICT = "VERSION_CONFLICT"
        val RETRYABLE = setOf("RATE_LIMITED", "IDEMPOTENCY_IN_PROGRESS")
    }
}
