package uz.elchi.app.feature.client

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.ElchiJson
import uz.elchi.app.api.FilesApi
import uz.elchi.app.api.generated.ApiWarning
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.api.generated.ListingCancel
import uz.elchi.app.api.generated.ListingCommand
import uz.elchi.app.api.generated.ListingDTO
import uz.elchi.app.api.generated.ListingPatch
import uz.elchi.app.api.generated.ProposalThreadDTO
import uz.elchi.app.api.generated.ShareLinkChannel
import uz.elchi.app.api.generated.ShareLinkCreate
import uz.elchi.app.api.generated.ShareLinkDTO
import java.time.Instant
import java.util.UUID

/** An owner command on the listing, while it runs (its button shows progress). */
enum class OwnerAction { PAUSE, RESUME, CANCEL }

/** What an owner command left to say once. */
enum class ListingNotice { PAUSED, RESUMED, SAVED }

/**
 * Stage 03, one listing of the signed-in client (scoped to its detail screen, shared with the edit and bids
 * screens opened from it): the listing, its offers, the owner's commands (edit, pause/resume, cancel), share links
 * and - through [board] - the negotiation.
 */
class ListingViewModel(
    private val api: ElchiApi,
    private val files: FilesApi,
    val listingId: String,
    private val now: () -> Instant = Instant::now,
) : ViewModel() {

    data class State(
        val listing: Load<ListingDTO> = Load.Loading,
        val threads: Load<List<ProposalThreadDTO>> = Load.Loading,
        val refreshing: Boolean = false,
        val photo: Bitmap? = null,
        val photoFailed: Boolean = false,
        val action: OwnerAction? = null,
        val actionError: Throwable? = null,
        val notice: ListingNotice? = null,
        val warnings: List<ApiWarning> = emptyList(),
        val cancelled: Boolean = false,
        // share (the URL comes back once: it lives only here, for as long as this screen does)
        val shareDays: Int = OrderRules.SHARE_TTL_DEFAULT_DAYS,
        val shareChannel: ShareLinkChannel = ShareLinkChannel.GENERIC,
        val sharing: Boolean = false,
        val shareError: Throwable? = null,
        val link: ShareLinkDTO? = null,
        val linkRevoked: Boolean = false,
        // edit
        val form: ListingEditForm? = null,
        /** The listing's values the form started from: what the person changed is what differs from these. */
        val formBase: ListingEditForm? = null,
        val saving: Boolean = false,
        val saveError: Throwable? = null,
        val saved: Boolean = false,
        // bids
        val sort: OfferSort = OfferSort.CHEAPEST,
    ) {
        val value: ListingDTO? get() = (listing as? Load.Ready)?.value
        val threadList: List<ProposalThreadDTO> get() = (threads as? Load.Ready)?.value.orEmpty()
    }

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()
    private val keys = mutableMapOf<String, String>()
    private var photoFor: String? = null

    val board = OfferBoard(
        viewModelScope,
        api,
        termsVersion = { _ -> _state.value.value?.termsVersion ?: fetchListing().termsVersion },
        reload = { reloadAll() },
    )

    init {
        refresh()
    }

    fun refresh() {
        _state.update { it.copy(refreshing = true) }
        viewModelScope.launch {
            reloadAll()
            _state.update { it.copy(refreshing = false) }
        }
    }

    private suspend fun reloadAll() {
        val listing = viewModelScope.async { loadListing() }
        val threads = viewModelScope.async { loadThreads() }
        listing.await()
        threads.await()
    }

    private suspend fun fetchListing(): ListingDTO = ElchiJson.decodeFromJsonElement(ListingDTO.serializer(), api.getListing(listingId).data)

    private suspend fun loadListing() {
        try {
            val listing = fetchListing()
            _state.update { it.copy(listing = Load.Ready(listing)) }
            loadPhoto(listing)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            // Keep what is on screen after a failed refresh; only a first load shows the failure.
            _state.update { if (it.listing is Load.Ready) it else it.copy(listing = Load.Failed(e)) }
        }
    }

    private suspend fun loadThreads() {
        try {
            val threads = api.listListingProposals(listingId, limit = THREADS_LIMIT).data
            _state.update { it.copy(threads = Load.Ready(threads)) }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            _state.update { if (it.threads is Load.Ready) it else it.copy(threads = Load.Failed(e)) }
        }
    }

    /** The cargo photo (Q6: only the owner and the assigned driver get the signed link). Read once per file. */
    private fun loadPhoto(listing: ListingDTO) {
        val photo = listing.parcel?.photo ?: return
        if (photoFor == photo.fileId) return
        photoFor = photo.fileId
        viewModelScope.launch {
            try {
                val bytes = files.download(photo.url)
                val bitmap = withContext(Dispatchers.Default) { decodeScaled(bytes) }
                _state.update { it.copy(photo = bitmap, photoFailed = bitmap == null) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                photoFor = null
                _state.update { it.copy(photoFailed = true) }
            }
        }
    }

    private fun decodeScaled(bytes: ByteArray): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        var sample = 1
        while (bounds.outWidth / (sample * 2) >= PHOTO_MAX_PX) sample *= 2
        return BitmapFactory.decodeByteArray(bytes, 0, bytes.size, BitmapFactory.Options().apply { inSampleSize = sample })
    }

    fun setSort(sort: OfferSort) = _state.update { it.copy(sort = sort) }

    fun consumeNotice() = _state.update { it.copy(notice = null, warnings = emptyList()) }

    // -- pause / resume / cancel --------------------------------------------------------------------------------

    fun pause() = command(OwnerAction.PAUSE)

    fun resume() = command(OwnerAction.RESUME)

    fun cancel() = command(OwnerAction.CANCEL)

    /**
     * Versioned commands: `expected_version` is the version on screen; if the listing moved on meanwhile
     * (VERSION_CONFLICT) it is read again and the person decides once more with the new state in front of them.
     */
    private fun command(action: OwnerAction) {
        val listing = _state.value.value ?: return
        if (_state.value.action != null) return
        _state.update { it.copy(action = action, actionError = null, notice = null) }
        val scope = "${action.name}:${listing.id}:${listing.version}"
        viewModelScope.launch {
            val key = keys.getOrPut(scope) { UUID.randomUUID().toString() }
            try {
                val command = ListingCommand(expectedVersion = listing.version)
                val result = when (action) {
                    OwnerAction.PAUSE -> api.pauseListing(listing.id, command, key)
                    OwnerAction.RESUME -> api.resumeListing(listing.id, command, key)
                    OwnerAction.CANCEL -> api.cancelListing(listing.id, ListingCancel(expectedVersion = listing.version, reasonCode = OrderRules.CANCEL_REASON), key)
                }
                keys.remove(scope)
                _state.update {
                    it.copy(
                        listing = Load.Ready(result.data),
                        action = null,
                        notice = when (action) {
                            OwnerAction.PAUSE -> ListingNotice.PAUSED
                            OwnerAction.RESUME -> ListingNotice.RESUMED
                            OwnerAction.CANCEL -> null
                        },
                        warnings = result.warnings,
                        cancelled = action == OwnerAction.CANCEL,
                        // A link to a listing that is no longer open would only show "closed".
                        link = if (action == OwnerAction.CANCEL) null else it.link,
                    )
                }
                if (action != OwnerAction.CANCEL) loadThreads()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (e is ApiException && e.status in 400..499) keys.remove(scope)
                _state.update { it.copy(action = null, actionError = e) }
                if (e is ApiException && e.code in RELOAD_ON) reloadAll()
            }
        }
    }

    // -- share --------------------------------------------------------------------------------------------------

    fun setShareDays(days: Int) = _state.update { it.copy(shareDays = days, shareError = null) }

    fun setShareChannel(channel: ShareLinkChannel) = _state.update { it.copy(shareChannel = channel, shareError = null) }

    /** Each tap is a new link (up to 5 live ones, `too_many_active`); a timed-out tap is retried with its own key. */
    fun createShareLink() {
        val s = _state.value
        if (s.sharing) return
        _state.update { it.copy(sharing = true, shareError = null) }
        val scope = "share:${s.shareDays}:${s.shareChannel.value}"
        viewModelScope.launch {
            val key = keys.getOrPut(scope) { UUID.randomUUID().toString() }
            try {
                val link = api.createShareLink(listingId, ShareLinkCreate(channel = s.shareChannel, ttlHours = OrderRules.shareTtlHours(s.shareDays)), key).data
                keys.remove(scope)
                _state.update { it.copy(sharing = false, link = link, linkRevoked = false) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (e is ApiException && e.status in 400..499) keys.remove(scope)
                _state.update { it.copy(sharing = false, shareError = e) }
            }
        }
    }

    /** `DELETE /share-links/{id}`: the link on screen stops working (and frees one of the 5 live ones). */
    fun revokeShareLink() {
        val link = _state.value.link ?: return
        if (_state.value.sharing) return
        _state.update { it.copy(sharing = true, shareError = null) }
        viewModelScope.launch {
            try {
                api.revokeShareLink(link.id)
                _state.update { it.copy(sharing = false, link = null, linkRevoked = true) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(sharing = false, shareError = e) }
            }
        }
    }

    // -- edit ---------------------------------------------------------------------------------------------------

    /** The form starts from the listing as it is now. */
    fun startEdit() {
        val listing = _state.value.value ?: return
        val form = OrderRules.editForm(listing)
        _state.update { it.copy(form = form, formBase = form, saveError = null, saved = false) }
    }

    fun editForm(transform: (ListingEditForm) -> ListingEditForm) = _state.update { s -> s.copy(form = s.form?.let(transform), saveError = null) }

    fun plan(): ListingPatchPlan? {
        val s = _state.value
        val listing = s.value ?: return null
        val form = s.form ?: return null
        return OrderRules.planListingPatch(listing, form, now())
    }

    /** Open offers the material edit would close (Q20), for the warning. */
    fun openOffers(): Int = OrderRules.offerStats(_state.value.threadList, now()).open

    /** `PATCH /listings/{id}` is not idempotent: one request per tap, the button is off while it runs. */
    fun save() {
        val s = _state.value
        val listing = s.value ?: return
        val plan = plan() ?: return
        if (s.saving || plan.empty || plan.invalid != null) return
        _state.update { it.copy(saving = true, saveError = null) }
        viewModelScope.launch {
            try {
                val body = ListingPatch(
                    expectedVersion = listing.version,
                    unitPriceMinor = plan.unitPriceMinor,
                    comment = plan.comment,
                    departureWindowStart = plan.windowStartIso,
                    departureWindowEnd = plan.windowEndIso,
                )
                val result = api.patchListing(listing.id, body)
                _state.update { it.copy(listing = Load.Ready(result.data), saving = false, saved = true, notice = ListingNotice.SAVED, warnings = result.warnings) }
                loadThreads()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(saving = false, saveError = e) }
                // The listing changed under the form (another device, the server): read it again, keep what the
                // person typed and take the new values for everything else - the next tap sends the new version
                // without silently undoing the other change.
                if (e is ApiException && e.code == VERSION_CONFLICT) {
                    loadListing()
                    _state.update { st ->
                        val fresh = st.value?.let(OrderRules::editForm)
                        val base = st.formBase
                        val typed = st.form
                        if (fresh == null || base == null || typed == null) st else st.copy(form = OrderRules.rebaseForm(typed, base, fresh), formBase = fresh)
                    }
                }
            }
        }
    }

    fun consumeSaved() = _state.update { it.copy(saved = false, form = null, formBase = null) }

    private companion object {
        const val THREADS_LIMIT = 50L
        const val PHOTO_MAX_PX = 1200
        const val VERSION_CONFLICT = "VERSION_CONFLICT"
        val RELOAD_ON = setOf(VERSION_CONFLICT, "LISTING_NOT_OPEN", "INVALID_STATE_TRANSITION")
    }
}
