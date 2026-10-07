package uz.elchi.app.feature.client

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import uz.elchi.app.R
import uz.elchi.app.api.FilesApi
import uz.elchi.app.api.LegacyBid
import uz.elchi.app.api.LegacyOrderDetail
import uz.elchi.app.api.LegacyOrdersApi
import uz.elchi.app.ui.components.BannerCenter
import uz.elchi.app.ui.components.BannerText
import uz.elchi.app.ui.components.BannerTone

/** A step of a v1 order that finished; the screen moves on once and consumes it. */
enum class LegacyDone { SELECTED, CONFIRMED, CANCELLED, RATED }

/**
 * One v1 order (Q4, an archive): its detail and the steps left in its life cycle - choose a driver, confirm delivery,
 * rate, cancel. A problem goes to a Yordam ticket (Q141: no dispute form). Lives on the detail screen's back-stack
 * entry; bids and rating borrow it.
 * Outcomes go to the app's [BannerCenter]; [rated] remembers ratings sent in this session across orders.
 */
class LegacyOrderViewModel(
    private val api: LegacyOrdersApi,
    private val files: FilesApi,
    private val banners: BannerCenter,
    private val rated: MutableSet<Long>,
    val orderId: Long,
    /** The cancel reason as stored text: `client.legacy.cancelReason` in Uzbek, like the web client. */
    private val cancelReason: String,
) : ViewModel() {

    data class State(
        val order: Load<LegacyOrderDetail> = Load.Loading,
        /** 404 / 403: not (or no longer) this client's order. */
        val notFound: Boolean = false,
        val refreshing: Boolean = false,
        val photo: Bitmap? = null,
        val photoFailed: Boolean = false,
        val bids: Load<List<LegacyBid>> = Load.Loading,
        val bidsRefreshing: Boolean = false,
        /** The bid whose "Tanlash" is being confirmed / sent. */
        val selecting: Long? = null,
        val busy: Boolean = false,
        val ratedHere: Boolean = false,
        val stars: Int = 0,
        val ratingComment: String = "",
        val done: LegacyDone? = null,
        /** Counts refused commands: the screen closes its confirmation sheet so the banner is seen, not dimmed. */
        val failures: Int = 0,
    ) {
        val value: LegacyOrderDetail? get() = (order as? Load.Ready)?.value
    }

    private val _state = MutableStateFlow(State(ratedHere = orderId in rated))
    val state: StateFlow<State> = _state.asStateFlow()
    private var photoFor: String? = null

    fun refresh() {
        if (_state.value.refreshing) return
        _state.update { it.copy(refreshing = true) }
        viewModelScope.launch {
            try {
                val detail = api.order(orderId)
                _state.update { it.copy(order = Load.Ready(detail), notFound = false, refreshing = false) }
                loadPhoto(detail)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update {
                    when {
                        LegacyRules.isNotFound(e) -> it.copy(notFound = true, refreshing = false)
                        // A failed re-read keeps what is on screen; the banner says why.
                        it.order is Load.Ready -> it.copy(refreshing = false).also { banners.error(e) }
                        else -> it.copy(order = Load.Failed(e), refreshing = false)
                    }
                }
            }
        }
    }

    private fun loadPhoto(detail: LegacyOrderDetail) {
        // The signed link changes on every read; the path before `?` names the file.
        val url = detail.cargoPhotoUrl?.takeIf { it.isNotBlank() } ?: return
        val file = url.substringBefore('?')
        if (photoFor == file) return
        photoFor = file
        viewModelScope.launch {
            try {
                val bytes = files.download(url)
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

    // -- bids ---------------------------------------------------------------------------------------------------

    fun loadBids() {
        _state.update { it.copy(bidsRefreshing = true) }
        viewModelScope.launch {
            try {
                val bids = api.bids(orderId)
                _state.update { it.copy(bids = Load.Ready(bids), bidsRefreshing = false) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { if (it.bids is Load.Ready) it.copy(bidsRefreshing = false) else it.copy(bids = Load.Failed(e), bidsRefreshing = false) }
            }
        }
        refresh()
    }

    fun askSelect(bid: LegacyBid) = _state.update { it.copy(selecting = bid.id) }

    fun dismissSelect() = _state.update { if (it.busy) it else it.copy(selecting = null) }

    fun select() {
        val bidId = _state.value.selecting ?: return
        command(onError = { e ->
            if (LegacyRules.bidGone(e)) loadBids()
        }) {
            api.selectDriver(orderId, bidId)
            _state.update { it.copy(selecting = null, done = LegacyDone.SELECTED) }
            banners.ok(R.string.listingBids_driverChosen)
        }
    }

    // -- confirm / cancel ---------------------------------------------------------------------------------------

    fun confirmDelivery() = command {
        api.confirm(orderId)
        _state.update { it.copy(done = LegacyDone.CONFIRMED) }
        banners.ok(R.string.legacyOrder_confirmed)
    }

    fun cancel() = command {
        api.cancel(orderId, cancelReason)
        _state.update { it.copy(done = LegacyDone.CANCELLED) }
        banners.ok(R.string.confirmDialog_cancelOrder_done)
    }

    // -- rating -------------------------------------------------------------------------------------------------

    fun setStars(value: Int) = _state.update { it.copy(stars = value.coerceIn(1, 5)) }

    /** DESIGN10 5.5: at most [COMMENT_MAX] characters. */
    fun setRatingComment(value: String) = _state.update { it.copy(ratingComment = value.take(COMMENT_MAX)) }

    fun rate() {
        val s = _state.value
        if (s.stars !in 1..5) return
        command(onError = { e ->
            // Already rated (another device, an earlier session): it is done, say so as if just sent.
            if (LegacyRules.ratingAlreadyDone(e)) markRated()
        }, handled = LegacyRules::ratingAlreadyDone) {
            api.rate(orderId, s.stars, s.ratingComment.trim().ifEmpty { null })
            markRated()
        }
    }

    private fun markRated() {
        rated += orderId
        _state.update { it.copy(ratedHere = true, done = LegacyDone.RATED) }
        banners.ok(R.string.legacyOrder_ratingSent)
    }

    fun consumeDone() = _state.update { it.copy(done = null) }

    /**
     * One command at a time, reported through the banner: the loading line while it runs, the refusal in words after.
     * [handled] errors are not shown (the command's [onError] turns them into an outcome).
     */
    private fun command(onError: (Exception) -> Unit = {}, handled: (Exception) -> Boolean = { false }, block: suspend () -> Unit) {
        if (_state.value.busy) return
        _state.update { it.copy(busy = true) }
        banners.startAction()
        viewModelScope.launch {
            try {
                block()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (!handled(e)) banners.show(BannerTone.ERR, legacyBannerText(e))
                onError(e)
                _state.update { it.copy(selecting = null, failures = it.failures + (if (handled(e)) 0 else 1)) }
                // The order moved on meanwhile (another device, the driver): show where it is now.
                if (LegacyRules.statusChanged(e)) refresh()
            } finally {
                banners.endAction()
                _state.update { it.copy(busy = false) }
            }
        }
    }

    companion object {
        private const val PHOTO_MAX_PX = 1600
        const val COMMENT_MAX = 300
    }
}

/** A v1 refusal as banner text: the client sentence for its code, else the generic mapping. */
internal fun legacyBannerText(error: Throwable): BannerText =
    LegacyRules.errorKey(error)?.let { BannerText.Key(it) } ?: BannerText.Error(error)
