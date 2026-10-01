package uz.elchi.app.feature.client

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.BookingClientDTO
import uz.elchi.app.api.generated.AcceptRequest
import uz.elchi.app.api.generated.ApiWarning
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.api.generated.PromoPreviewDTO
import uz.elchi.app.api.generated.ProposalCounter
import uz.elchi.app.api.generated.ProposalDecision
import uz.elchi.app.api.generated.ProposalPromoClientDTO
import uz.elchi.app.api.generated.ProposalThreadDTO
import java.util.UUID

/** What an offer command left to say once (a banner), then cleared. */
enum class OfferNotice { COUNTER_SENT, REJECTED, WITHDRAWN }

/** An accept went through. [booking] is null only if the answer could not be read as the client view. */
data class Accepted(val booking: BookingClientDTO?)

/**
 * The client's side of the negotiation, shared by the bids screen of one listing and "Takliflarim": counter
 * (with the promo preview), reject, withdraw and accept (after the confirmation dialog). Each command carries one
 * `Idempotency-Key` per action - `accept:{thread}:{version}` and the like - reused until the server has given a
 * definite answer, so a retry after a timeout can never make a second booking.
 *
 * [termsVersion] gives the listing's `terms_version` the accept must send (Q54); [reload] re-reads the threads
 * (and listing) after every command and after every refusal, so the screen never shows a stale turn.
 */
class OfferBoard(
    private val scope: CoroutineScope,
    private val api: ElchiApi,
    private val termsVersion: suspend (ProposalThreadDTO) -> Long,
    private val reload: suspend () -> Unit,
) {
    data class State(
        /** The thread a command is running on; its buttons show progress, every other thread's stay usable. */
        val busyThread: String? = null,
        /** The thread whose inline counter form is open. */
        val counterFor: String? = null,
        val counterDigits: String = "",
        /** `GET /listings/{id}/promo-preview` for the typed price: a quote (bonus lines) or why there is none. */
        val counterPreview: PromoPreviewDTO? = null,
        val counterBonus: Boolean = false,
        /** Threads whose "Bonusni ishlataman" box is ticked (never pre-ticked). */
        val acceptBonus: Set<String> = emptySet(),
        /** The thread whose accept dialog is open. */
        val confirming: String? = null,
        val error: Throwable? = null,
        val errorThread: String? = null,
        val notice: OfferNotice? = null,
        /** Server warnings of the last command (e.g. `PRICE_OUTSIDE_REFERENCE`, Q90 - advice, not a refusal). */
        val warnings: List<ApiWarning> = emptyList(),
        /** Set once an accept made the booking; the screen leaves for the orders list. */
        val accepted: Accepted? = null,
    )

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()
    private val keys = mutableMapOf<String, String>()
    private var previewJob: Job? = null

    // -- counter ------------------------------------------------------------------------------------------------

    fun openCounter(thread: ProposalThreadDTO) {
        val version = thread.currentVersion ?: return
        val digits = ParcelRules.minorToSoum(version.totalMinor).toString()
        _state.update { it.copy(counterFor = thread.id, counterDigits = digits, counterPreview = null, counterBonus = false, error = null, errorThread = null) }
        preview(thread, digits)
    }

    fun closeCounter() {
        previewJob?.cancel()
        _state.update { it.copy(counterFor = null, counterDigits = "", counterPreview = null, counterBonus = false) }
    }

    fun setCounterDigits(thread: ProposalThreadDTO, text: String) {
        val digits = text.filter(Char::isDigit).trimStart('0').take(10)
        _state.update { it.copy(counterDigits = digits, counterBonus = false) }
        preview(thread, digits)
    }

    fun setCounterBonus(on: Boolean) = _state.update { it.copy(counterBonus = on && it.counterPreview?.quote != null) }

    /** The bonus preview follows the typed price, 500 ms after typing stops. A failed preview just shows nothing. */
    private fun preview(thread: ProposalThreadDTO, digits: String) {
        previewJob?.cancel()
        val minor = ParcelRules.soumToMinor(digits) ?: return _state.update { it.copy(counterPreview = null) }
        val quantity = thread.currentVersion?.quantity
        previewJob = scope.launch {
            delay(PREVIEW_DEBOUNCE_MS)
            val result = try {
                api.promoPreview(thread.listingId, minor, quantity).data
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                null
            }
            _state.update { if (it.counterFor == thread.id) it.copy(counterPreview = result) else it }
        }
    }

    /** A price the counter may send: a positive whole so'm amount that differs from the one on the table. */
    fun counterPrice(thread: ProposalThreadDTO): Long? =
        ParcelRules.soumToMinor(_state.value.counterDigits)?.takeIf { it != thread.currentVersion?.totalMinor }

    /** For a parcel request only the price (and nothing else) changes; the version stays the one answered. */
    fun sendCounter(thread: ProposalThreadDTO) {
        val version = thread.currentVersion ?: return
        val price = counterPrice(thread) ?: return
        val s = _state.value
        val consent = OrderRules.counterConsent(s.counterPreview?.quote, s.counterBonus)
        run(thread, "counter:${thread.id}:${version.revision}:$price:${consent != null}") { key ->
            val result = api.counterProposal(thread.id, ProposalCounter(expectedRevision = version.revision, unitPriceMinor = price, promoConsent = consent), key)
            previewJob?.cancel()
            _state.update { it.copy(counterFor = null, counterDigits = "", counterPreview = null, counterBonus = false, notice = OfferNotice.COUNTER_SENT, warnings = result.warnings) }
        }
    }

    // -- reject / withdraw --------------------------------------------------------------------------------------

    fun reject(thread: ProposalThreadDTO) {
        val version = thread.currentVersion ?: return
        run(thread, "reject:${thread.id}:${version.revision}") { key ->
            api.rejectProposal(thread.id, ProposalDecision(expectedRevision = version.revision), key)
            _state.update { it.copy(notice = OfferNotice.REJECTED, warnings = emptyList()) }
        }
    }

    fun withdraw(thread: ProposalThreadDTO) {
        val version = thread.currentVersion ?: return
        run(thread, "withdraw:${thread.id}:${version.revision}") { key ->
            api.withdrawProposal(thread.id, ProposalDecision(expectedRevision = version.revision), key)
            _state.update { it.copy(notice = OfferNotice.WITHDRAWN, warnings = emptyList()) }
        }
    }

    // -- accept -------------------------------------------------------------------------------------------------

    fun toggleAcceptBonus(threadId: String) = _state.update {
        it.copy(acceptBonus = if (threadId in it.acceptBonus) it.acceptBonus - threadId else it.acceptBonus + threadId)
    }

    fun askAccept(thread: ProposalThreadDTO) = _state.update { it.copy(confirming = thread.id, error = null, errorThread = null) }

    fun dismissAccept() = _state.update { it.copy(confirming = null) }

    /**
     * The booking is made at the version's own `total_minor` (Q90) - nothing is recomputed here. The bonus is used
     * only when the box was ticked, with exactly the numbers the person saw; `PROMO_QUOTE_STALE` unticks it.
     */
    fun accept(thread: ProposalThreadDTO) {
        val version = thread.currentVersion ?: return
        val quote = version.promoQuote as? ProposalPromoClientDTO
        val consent = OrderRules.acceptConsent(quote, thread.id in _state.value.acceptBonus)
        _state.update { it.copy(confirming = null) }
        run(thread, "accept:${thread.id}:${version.id}:${consent != null}") { key ->
            val body = AcceptRequest(proposalVersionId = version.id, expectedListingTermsVersion = termsVersion(thread), promoConsent = consent)
            val booking = BookingClientDTO.fromJson(api.acceptProposal(thread.id, body, key).data)
            _state.update { it.copy(accepted = Accepted(booking), acceptBonus = it.acceptBonus - thread.id) }
        }
    }

    fun consumeNotice() = _state.update { it.copy(notice = null, warnings = emptyList()) }

    fun consumeAccepted() = _state.update { it.copy(accepted = null) }

    fun clearError() = _state.update { it.copy(error = null, errorThread = null) }

    /** One command on one thread; afterwards (success or refusal) the threads are read again. */
    private fun run(thread: ProposalThreadDTO, scopeKey: String, block: suspend (key: String) -> Unit) {
        if (_state.value.busyThread != null) return
        _state.update { it.copy(busyThread = thread.id, error = null, errorThread = null, notice = null, warnings = emptyList()) }
        scope.launch {
            val key = keys.getOrPut(scopeKey) { UUID.randomUUID().toString() }
            try {
                block(key)
                keys.remove(scopeKey)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                // A definite refusal is final for this key; a timeout or 5xx keeps it so a retry cannot double up.
                if (e is ApiException && e.status in 400..499 && e.code !in RETRYABLE) keys.remove(scopeKey)
                _state.update {
                    it.copy(
                        error = e,
                        errorThread = thread.id,
                        acceptBonus = if (e is ApiException && e.code == PROMO_QUOTE_STALE) it.acceptBonus - thread.id else it.acceptBonus,
                        counterBonus = if (e is ApiException && e.code == PROMO_QUOTE_STALE) false else it.counterBonus,
                    )
                }
            }
            runCatching { reload() }
            _state.update { it.copy(busyThread = null) }
        }
    }

    companion object {
        private const val PREVIEW_DEBOUNCE_MS = 500L
        private const val PROMO_QUOTE_STALE = "PROMO_QUOTE_STALE"
        private val RETRYABLE = setOf("RATE_LIMITED", "IDEMPOTENCY_IN_PROGRESS")

        /** Codes that say nothing about the client and must not read as its fault (the driver's wallet, eligibility). */
        val DRIVER_SIDE = setOf("DRIVER_NOT_ELIGIBLE", "INSUFFICIENT_COMMISSION_BALANCE")
    }
}
