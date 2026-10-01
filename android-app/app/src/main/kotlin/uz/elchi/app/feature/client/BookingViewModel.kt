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
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.BookingClientDTO
import uz.elchi.app.api.DriverBookingDTO
import uz.elchi.app.api.ElchiJson
import uz.elchi.app.api.FilesApi
import uz.elchi.app.api.generated.AmendmentAccept
import uz.elchi.app.api.generated.AmendmentChanges
import uz.elchi.app.api.generated.AmendmentCreate
import uz.elchi.app.api.generated.AmendmentDTO
import uz.elchi.app.api.generated.AmendmentDecision
import uz.elchi.app.api.generated.ApiWarning
import uz.elchi.app.api.generated.BlockCreate
import uz.elchi.app.api.generated.BookingAction
import uz.elchi.app.api.generated.BookingActionRequest
import uz.elchi.app.api.generated.BookingPromoDriverDTO
import uz.elchi.app.api.generated.PromoDriverAckInput
import uz.elchi.app.api.generated.BookingCancel
import uz.elchi.app.api.generated.BookingPromoClientDTO
import uz.elchi.app.api.generated.ContactDetails
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.api.generated.ListingDTO
import uz.elchi.app.api.generated.PromoConsentInput
import uz.elchi.app.api.generated.RatingCreate
import uz.elchi.app.api.generated.ReportCreate
import uz.elchi.app.api.generated.ReportReasonCode
import uz.elchi.app.api.generated.ReportSubjectType
import uz.elchi.app.api.generated.ReputationDTO
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.api.generated.TrackingGrantCreate
import uz.elchi.app.api.generated.TrackingGrantDTO
import uz.elchi.app.api.generated.TrackingGrantScope
import java.time.Instant
import java.util.UUID

/** What a booking command left to say once (a banner on the detail screen), then cleared. */
enum class BookingNotice { DRIVER_CHOSEN, CANCELLED, AMENDMENT_SENT, AMENDMENT_ACCEPTED, AMENDMENT_REJECTED, AMENDMENT_WITHDRAWN, RATED, ARRIVED }

/** Whose booking screen this is: the client's (Stage 04) or the assigned driver's (Stage 09, the same screens reused). */
enum class BookingSide(val wire: String) { CLIENT("client"), DRIVER("driver") }

/**
 * Stage 04, one booking of the signed-in client (scoped to its detail screen, shared with the amendment, rating and
 * safety screens opened from it): the booking, the driver's reputation, the receiver from the client's own
 * request, the cargo photo, and the client's commands - cancel, tracking link, amendment, rating, report, block.
 * Every command carries one `Idempotency-Key` per action, kept until the server gave a definite answer.
 */
class BookingViewModel(
    private val api: ElchiApi,
    private val files: FilesApi,
    private val apiBase: String,
    val bookingId: String,
    private val now: () -> Instant = Instant::now,
    val side: BookingSide = BookingSide.CLIENT,
    /** The driver's booking commands (the generated call builds a wrong path, [BookingActionsApi]). */
    private val actions: uz.elchi.app.api.BookingActionsApi? = null,
) : ViewModel() {

    data class State(
        val booking: Load<BookingClientDTO> = Load.Loading,
        val refreshing: Boolean = false,
        val reputation: ReputationDTO? = null,
        val reputationFailed: Boolean = false,
        val receiver: ContactDetails? = null,
        val photo: Bitmap? = null,
        val photoFailed: Boolean = false,
        val notice: BookingNotice? = null,
        val warnings: List<ApiWarning> = emptyList(),
        // cancel
        val cancelReason: String = BookingRules.CLIENT_CANCEL_REASONS.first(),
        val cancelComment: String = "",
        val cancelling: Boolean = false,
        val cancelError: Throwable? = null,
        /** Set by a successful cancel; the sheet closes on it. */
        val cancelDone: Boolean = false,
        // tracking link (the URL comes back once: it lives only here, for as long as this screen does)
        val grantTtl: Int = BookingRules.GRANT_TTL_DEFAULT,
        val granting: Boolean = false,
        val grantError: Throwable? = null,
        val grant: TrackingGrantDTO? = null,
        val grantUrl: String? = null,
        val grantRevoked: Boolean = false,
        // rating
        val stars: Int = 0,
        val ratingComment: String = "",
        val rating: Boolean = false,
        /** Rated from this phone, or the server said it already has this person's rating. */
        val rated: Boolean = false,
        /** The server's word on why rating is not possible (RATING_NOT_ALLOWED / RATING_ALREADY_EXISTS). */
        val ratingRefusal: Throwable? = null,
        val ratingError: Throwable? = null,
        // amendments
        val amendments: Load<List<AmendmentDTO>> = Load.Loading,
        val amendDigits: String = "",
        val amendReason: String = "",
        /** The amendment a command runs on ([NEW_AMENDMENT] for the form). */
        val amendBusy: String? = null,
        val amendError: Throwable? = null,
        val amendErrorFor: String? = null,
        // safety
        val reportReason: ReportReasonCode? = null,
        val reportDetails: String = "",
        val reporting: Boolean = false,
        val reportError: Throwable? = null,
        val reported: Boolean = false,
        val blocking: Boolean = false,
        val blockError: Throwable? = null,
        val blocked: Boolean = false,
        // driver side (Stage 09)
        /** The driver's own view: the client, the receiver after departure, the commission (Q103). */
        val driverView: DriverBookingDTO? = null,
        /** When the driver's "Keldim" was recorded (`GET /bookings/{id}/tracking` `driver_arrived_at`): sent once. */
        val arrivedAt: String? = null,
        val arriving: Boolean = false,
        val arriveError: Throwable? = null,
    ) {
        val value: BookingClientDTO? get() = (booking as? Load.Ready)?.value
        val amendmentList: List<AmendmentDTO> get() = (amendments as? Load.Ready)?.value.orEmpty()
    }

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()
    private val keys = mutableMapOf<String, String>()
    private var photoFor: String? = null
    private var photoRetried = false
    private var reputationFor: String? = null
    private var receiverFor: String? = null

    /** Read on every return to the screen (sub-screens and the server move the booking on). */
    fun refresh() {
        if (_state.value.refreshing) return
        _state.update { it.copy(refreshing = true) }
        viewModelScope.launch {
            loadBooking()
            _state.update { it.copy(refreshing = false) }
        }
    }

    fun show(notice: BookingNotice) = _state.update { it.copy(notice = notice) }

    fun consumeNotice() = _state.update { it.copy(notice = null, warnings = emptyList()) }

    /** The cancel reasons of this side (`BookingCancel.reason_code`). */
    val cancelReasons: List<String> get() = if (side == BookingSide.DRIVER) DRIVER_CANCEL_REASONS else BookingRules.CLIENT_CANCEL_REASONS

    /** The other party of the booking (reputation, block): the driver for the client, the client for the driver. */
    fun counterpartId(s: State = _state.value): String? = if (side == BookingSide.DRIVER) s.driverView?.client?.id else s.value?.driver?.id

    /** The shared part for the reused screens; on the driver side the driver's own view is kept next to it. */
    private fun decode(json: kotlinx.serialization.json.JsonElement): BookingClientDTO? {
        if (side == BookingSide.CLIENT) return BookingClientDTO.fromJson(json)
        val driverView = DriverBookingDTO.fromJson(json) ?: return null
        val shared = BookingClientDTO.anySide(json) ?: return null
        _state.update { it.copy(driverView = driverView) }
        return shared
    }

    private suspend fun fetchBooking(): BookingClientDTO =
        decode(api.getBooking(bookingId).data) ?: throw ApiException(0, ApiException.SERVER, "not this side's booking")

    private suspend fun loadBooking() {
        try {
            val booking = fetchBooking()
            _state.update { it.copy(booking = Load.Ready(booking)) }
            afterBooking(booking)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            // Keep what is on screen after a failed refresh; only a first load shows the failure.
            _state.update { if (it.booking is Load.Ready) it else it.copy(booking = Load.Failed(e)) }
        }
    }

    /** The side reads that hang off the booking: each once, each allowed to fail without failing the screen. */
    private fun afterBooking(booking: BookingClientDTO) {
        loadPhoto(booking)
        counterpartId()?.takeIf { it != reputationFor }?.let { driverId ->
            reputationFor = driverId
            viewModelScope.launch {
                try {
                    val reputation = api.getReputation(driverId, ServiceType.PARCEL).data
                    _state.update { it.copy(reputation = reputation, reputationFailed = false) }
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    reputationFor = null
                    _state.update { it.copy(reputationFailed = true) }
                }
            }
        }
        if (side == BookingSide.DRIVER) loadArrival(booking)
        // The receiver is the client's own entry on its request (the booking shows it only to the driver).
        booking.listingIds?.request?.takeIf { it != receiverFor && side == BookingSide.CLIENT }?.let { listingId ->
            receiverFor = listingId
            viewModelScope.launch {
                runCatching { ElchiJson.decodeFromJsonElement(ListingDTO.serializer(), api.getListing(listingId).data).parcel?.receiver }
                    .onSuccess { receiver -> _state.update { it.copy(receiver = receiver) } }
                    .onFailure { if (it is CancellationException) throw it else receiverFor = null }
            }
        }
    }

    /** Q6: the signed link is short-lived; a failed download reads the booking again once for a fresh link. */
    private fun loadPhoto(booking: BookingClientDTO) {
        val photo = booking.parcelPhoto ?: return
        if (photoFor == photo.fileId && (_state.value.photo != null || !_state.value.photoFailed)) return
        photoFor = photo.fileId
        viewModelScope.launch {
            try {
                val bytes = files.download(photo.url)
                val bitmap = withContext(Dispatchers.Default) { decodeScaled(bytes) }
                _state.update { it.copy(photo = bitmap, photoFailed = bitmap == null) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (!photoRetried) {
                    photoRetried = true
                    photoFor = null
                    runCatching { fetchBooking() }.getOrNull()?.let { fresh ->
                        _state.update { it.copy(booking = Load.Ready(fresh)) }
                        loadPhoto(fresh)
                    } ?: _state.update { it.copy(photoFailed = true) }
                } else {
                    _state.update { it.copy(photoFailed = true) }
                }
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

    /** One command with its own key: a definite 4xx ends the key, a timeout or 5xx keeps it for the retry. */
    private suspend fun <T> keyed(scope: String, block: suspend (String) -> T): T {
        val key = keys.getOrPut(scope) { UUID.randomUUID().toString() }
        try {
            val result = block(key)
            keys.remove(scope)
            return result
        } catch (e: ApiException) {
            if (e.status in 400..499 && e.code != IN_PROGRESS) keys.remove(scope)
            throw e
        }
    }

    private fun setBooking(json: kotlinx.serialization.json.JsonElement) {
        decode(json)?.let { booking ->
            _state.update { it.copy(booking = Load.Ready(booking)) }
            afterBooking(booking)
        }
    }

    // -- cancel (booking-cancel sheet) --------------------------------------------------------------------------

    fun openCancel() = _state.update { it.copy(cancelReason = cancelReasons.first(), cancelComment = "", cancelError = null, cancelDone = false) }

    fun setCancelReason(code: String) = _state.update { it.copy(cancelReason = code, cancelError = null) }

    fun setCancelComment(text: String) = _state.update { it.copy(cancelComment = text.take(COMMENT_MAX)) }

    fun consumeCancelDone() = _state.update { it.copy(cancelDone = false) }

    /** `expected_version` is the version on screen; a moved booking (VERSION_CONFLICT) is read again first. */
    fun cancel() {
        val s = _state.value
        val booking = s.value ?: return
        if (s.cancelling) return
        _state.update { it.copy(cancelling = true, cancelError = null) }
        val comment = s.cancelComment.trim().takeIf { it.isNotEmpty() }
        viewModelScope.launch {
            try {
                val result = keyed("cancel:${booking.id}:${booking.version}:${s.cancelReason}:${comment.orEmpty()}") { key ->
                    api.cancelBooking(booking.id, BookingCancel(comment = comment, expectedVersion = booking.version, reasonCode = s.cancelReason), key)
                }
                setBooking(result.data)
                _state.update { it.copy(cancelling = false, cancelDone = true, notice = BookingNotice.CANCELLED, warnings = result.warnings) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(cancelling = false, cancelError = e) }
                if (e is ApiException && e.code in RELOAD_ON) loadBooking()
            }
        }
    }

    // -- tracking link ------------------------------------------------------------------------------------------

    fun setGrantTtl(minutes: Int) = _state.update { it.copy(grantTtl = minutes, grantError = null) }

    fun createGrant() {
        val s = _state.value
        if (s.granting) return
        _state.update { it.copy(granting = true, grantError = null, grantRevoked = false) }
        viewModelScope.launch {
            try {
                val grant = keyed("grant:${s.grantTtl}") { key ->
                    api.createTrackingGrant(bookingId, TrackingGrantCreate(scope = TrackingGrantScope.RECIPIENT_LINK, ttlMinutes = BookingRules.grantTtlMinutes(s.grantTtl)), key).data
                }
                _state.update { it.copy(granting = false, grant = grant, grantUrl = grant.url?.let { url -> BookingRules.absoluteUrl(apiBase, url) }) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(granting = false, grantError = e) }
            }
        }
    }

    /** The link on screen stops working (`DELETE .../tracking-grants/{id}`). */
    fun revokeGrant() {
        val grant = _state.value.grant ?: return
        if (_state.value.granting) return
        _state.update { it.copy(granting = true, grantError = null) }
        viewModelScope.launch {
            try {
                api.revokeTrackingGrant(bookingId, grant.id)
                _state.update { it.copy(granting = false, grant = null, grantUrl = null, grantRevoked = true) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(granting = false, grantError = e) }
            }
        }
    }

    // -- rating -------------------------------------------------------------------------------------------------

    fun setStars(stars: Int) = _state.update { it.copy(stars = stars.coerceIn(1, 5), ratingError = null) }

    fun setRatingComment(text: String) = _state.update { it.copy(ratingComment = text.take(COMMENT_MAX)) }

    /**
     * S1: the client rates the driver (`subject_side = driver`). "Already rated" and "not allowed" are answers, not
     * failures: the screen closes the rating with the server's sentence.
     */
    fun rate() {
        val s = _state.value
        if (s.rating || s.stars !in 1..5) return
        _state.update { it.copy(rating = true, ratingError = null) }
        val comment = s.ratingComment.trim().takeIf { it.isNotEmpty() }
        viewModelScope.launch {
            try {
                keyed("rate:${s.stars}:${comment.orEmpty()}") { key ->
                    api.createRating(bookingId, RatingCreate(comment = comment, stars = s.stars.toLong(), subjectSide = if (side == BookingSide.DRIVER) CLIENT else DRIVER), key)
                }
                _state.update { it.copy(rating = false, rated = true, notice = BookingNotice.RATED) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                val code = (e as? ApiException)?.code
                _state.update {
                    when (code) {
                        RATING_ALREADY_EXISTS -> it.copy(rating = false, rated = true, ratingRefusal = e)
                        RATING_NOT_ALLOWED -> it.copy(rating = false, ratingRefusal = e)
                        else -> it.copy(rating = false, ratingError = e)
                    }
                }
            }
        }
    }

    // -- amendments ---------------------------------------------------------------------------------------------

    fun loadAmendments() {
        viewModelScope.launch {
            try {
                val list = api.listAmendments(bookingId, limit = AMENDMENTS_LIMIT).data
                _state.update { it.copy(amendments = Load.Ready(list)) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { if (it.amendments is Load.Ready) it else it.copy(amendments = Load.Failed(e)) }
            }
        }
    }

    /** The form starts empty (the agreed price is its placeholder), so nothing is refused before anything was typed. */
    fun startAmendment() {
        _state.update { it.copy(amendDigits = "", amendReason = "", amendError = null, amendErrorFor = null) }
        loadAmendments()
    }

    fun setAmendDigits(text: String) = _state.update { it.copy(amendDigits = text.filter(Char::isDigit).trimStart('0').take(10), amendError = null) }

    fun setAmendReason(text: String) = _state.update { it.copy(amendReason = text.take(REASON_MAX), amendError = null) }

    fun amendPrice(): Long? = _state.value.value?.let { BookingRules.amendmentPrice(_state.value.amendDigits, it.unitPriceMinor) }

    /** Pochta: only the price moves (Q145 `quantity_amendable` is false), with the reason the driver will read. */
    fun sendAmendment() {
        val s = _state.value
        val booking = s.value ?: return
        val price = amendPrice() ?: return
        val reason = s.amendReason.trim().takeIf { it.isNotEmpty() } ?: return
        amendCommand(NEW_AMENDMENT, "amend:${booking.id}:${booking.version}:$price:$reason") { key ->
            val result = api.createAmendment(booking.id, AmendmentCreate(changes = AmendmentChanges(unitPriceMinor = price), expectedVersion = booking.version, reason = reason), key)
            _state.update { it.copy(amendDigits = "", amendReason = "", notice = BookingNotice.AMENDMENT_SENT, warnings = result.warnings) }
        }
    }

    /**
     * Accepting a driver's amendment changes the booking. On a discounted booking the new cash is confirmed with
     * exactly the numbers shown (Q116); without a promo nothing extra travels.
     */
    fun acceptAmendment(amendment: AmendmentDTO) = amendCommand(amendment.id, "amend-accept:${amendment.id}:${amendment.version}") { key ->
        val promo = amendment.promo as? BookingPromoClientDTO
        val consent = promo?.takeIf { side == BookingSide.CLIENT }?.let { PromoConsentInput(cashDueMinor = it.cashDueMinor, passengerBonusMinor = it.passengerDiscountMinor) }
        // Q125: the driver confirms exactly the cash and commission it was shown (discounted bookings only).
        val ack = (amendment.promo as? BookingPromoDriverDTO)?.takeIf { side == BookingSide.DRIVER }
            ?.let { PromoDriverAckInput(cashToCollectMinor = it.cashToCollectMinor, commissionChargedMinor = it.commissionChargedMinor) }
        val result = api.acceptAmendment(amendment.id, AmendmentAccept(expectedVersion = amendment.version, promoConsent = consent, promoDriverAck = ack), key)
        setBooking(result.data)
        _state.update { it.copy(notice = BookingNotice.AMENDMENT_ACCEPTED, warnings = result.warnings) }
    }

    fun rejectAmendment(amendment: AmendmentDTO) = amendCommand(amendment.id, "amend-reject:${amendment.id}:${amendment.version}") { key ->
        api.rejectAmendment(amendment.id, AmendmentDecision(expectedVersion = amendment.version), key)
        _state.update { it.copy(notice = BookingNotice.AMENDMENT_REJECTED) }
    }

    fun withdrawAmendment(amendment: AmendmentDTO) = amendCommand(amendment.id, "amend-withdraw:${amendment.id}:${amendment.version}") { key ->
        api.withdrawAmendment(amendment.id, AmendmentDecision(expectedVersion = amendment.version), key)
        _state.update { it.copy(notice = BookingNotice.AMENDMENT_WITHDRAWN) }
    }

    /** One amendment command at a time; afterwards (success or refusal) the booking and the history are read again. */
    private fun amendCommand(target: String, scope: String, block: suspend (String) -> Unit) {
        if (_state.value.amendBusy != null) return
        _state.update { it.copy(amendBusy = target, amendError = null, amendErrorFor = null) }
        viewModelScope.launch {
            try {
                keyed(scope, block)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(amendError = e, amendErrorFor = target) }
            }
            loadBooking()
            try {
                val list = api.listAmendments(bookingId, limit = AMENDMENTS_LIMIT).data
                _state.update { it.copy(amendments = Load.Ready(list)) }
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
            }
            _state.update { it.copy(amendBusy = null) }
        }
    }

    // -- safety -------------------------------------------------------------------------------------------------

    fun setReportReason(reason: ReportReasonCode) = _state.update { it.copy(reportReason = reason, reportError = null) }

    fun setReportDetails(text: String) = _state.update { it.copy(reportDetails = text.take(REPORT_MAX), reportError = null) }

    fun newReport() = _state.update { it.copy(reported = false, reportReason = null, reportDetails = "", reportError = null) }

    /** A report about this booking (`subject_type = booking`): the operator reviews it; it punishes no one by itself. */
    fun report() {
        val s = _state.value
        val reason = s.reportReason ?: return
        if (s.reporting) return
        _state.update { it.copy(reporting = true, reportError = null) }
        val details = s.reportDetails.trim().takeIf { it.isNotEmpty() }
        viewModelScope.launch {
            try {
                keyed("report:${reason.value}:${details.orEmpty()}") { key ->
                    api.createReport(ReportCreate(details = details, reasonCode = reason, subjectId = bookingId, subjectType = ReportSubjectType.BOOKING), key)
                }
                _state.update { it.copy(reporting = false, reported = true) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(reporting = false, reportError = e) }
            }
        }
    }

    /** `POST /blocks {user_id}`: the other party of this booking. The booking itself and support go on (Q15). */
    fun block() {
        val driverId = counterpartId() ?: return
        if (_state.value.blocking) return
        _state.update { it.copy(blocking = true, blockError = null) }
        viewModelScope.launch {
            try {
                keyed("block:$driverId") { key -> api.createBlock(BlockCreate(userId = driverId), key) }
                _state.update { it.copy(blocking = false, blocked = true) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(blocking = false, blockError = e) }
            }
        }
    }

    // -- driver: "Keldim" (Stage 09) ------------------------------------------------------------------------------

    /** Whether the driver's "Keldim" is already recorded: the booking DTO does not carry it, the tracking view does. */
    private fun loadArrival(booking: BookingClientDTO) {
        if (_state.value.arrivedAt != null || booking.serviceStatus !in ARRIVE_STATUSES) return
        viewModelScope.launch {
            runCatching { api.getBookingTracking(bookingId).data.driverArrivedAt }
                .onSuccess { at -> if (at != null) _state.update { it.copy(arrivedAt = at) } }
                .onFailure { if (it is CancellationException) throw it }
        }
    }

    /**
     * `POST /bookings/{id}/actions/arrive_at_pickup {expected_version}` - a signal for the client (Q44), not a status
     * change; the server records it once.
     */
    fun arrive() {
        val s = _state.value
        val booking = s.value ?: return
        val actions = actions ?: return
        if (s.arriving || side != BookingSide.DRIVER) return
        _state.update { it.copy(arriving = true, arriveError = null) }
        viewModelScope.launch {
            try {
                val result = keyed("arrive:${booking.id}:${booking.version}") { key ->
                    actions.act(booking.id, BookingAction.ARRIVE_AT_PICKUP, BookingActionRequest(expectedVersion = booking.version), key)
                }
                setBooking(result.data)
                _state.update { it.copy(arriving = false, arrivedAt = it.arrivedAt ?: now().toString(), notice = BookingNotice.ARRIVED) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(arriving = false, arriveError = e) }
                if (e is ApiException && e.code in RELOAD_ON) loadBooking()
            }
        }
    }

    init {
        refresh()
    }

    companion object {
        const val NEW_AMENDMENT = "new"
        private const val DRIVER = "driver"
        private const val CLIENT = "client"

        /** The driver's own cancel reasons (`bookingCancel.reason.<code>`); `other` last. */
        val DRIVER_CANCEL_REASONS = listOf("trip_changed", "vehicle_problem", "client_unreachable", "other")

        /** Before the service starts (server `PRE_SERVICE_STATUSES`): "Keldim" is possible. */
        val ARRIVE_STATUSES = setOf("confirmed", "awaiting_pickup")
        private const val PHOTO_MAX_PX = 1200
        private const val COMMENT_MAX = 1000
        private const val REASON_MAX = 500
        private const val REPORT_MAX = 2000
        private const val AMENDMENTS_LIMIT = 20L
        private const val IN_PROGRESS = "IDEMPOTENCY_IN_PROGRESS"
        const val RATING_ALREADY_EXISTS = "RATING_ALREADY_EXISTS"
        const val RATING_NOT_ALLOWED = "RATING_NOT_ALLOWED"
        private val RELOAD_ON = setOf("VERSION_CONFLICT", "INVALID_STATE_TRANSITION", "NO_SHOW_REVIEW_PENDING", "CUSTODY_REQUIRES_RETURN_FLOW")
    }
}
