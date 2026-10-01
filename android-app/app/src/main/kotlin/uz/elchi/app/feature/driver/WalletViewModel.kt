package uz.elchi.app.feature.driver

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.api.generated.LedgerLineDTO
import uz.elchi.app.api.generated.TopupDTO
import uz.elchi.app.api.generated.WalletDTO
import uz.elchi.app.feature.client.ActionKeys
import uz.elchi.app.feature.client.Load
import uz.elchi.app.ui.components.BannerCenter
import uz.elchi.app.ui.components.BannerText
import uz.elchi.app.ui.components.BannerTone

/**
 * "Komissiya balansi": `GET /wallet`, `/wallet/topups`, `/wallet/transactions` (cursor), and the top-up request
 * (`POST /wallet/topups` with an Idempotency-Key). Read again on every visit.
 */
class WalletViewModel(
    private val api: ElchiApi,
    private val banners: BannerCenter,
    private val onChanged: () -> Unit = {},
) : ViewModel() {
    data class Form(val amount: String = "", val method: String = WalletRules.METHODS.first(), val payerReference: String = "", val note: String = "")

    data class State(
        val wallet: Load<WalletDTO> = Load.Loading,
        val topups: Load<List<TopupDTO>> = Load.Loading,
        val lines: Load<List<LedgerLineDTO>> = Load.Loading,
        val linesCursor: String? = null,
        val loadingMore: Boolean = false,
        val refreshing: Boolean = false,
        val form: Form = Form(),
        val sending: Boolean = false,
        val sendError: Throwable? = null,
    ) {
        val lineList: List<LedgerLineDTO> get() = (lines as? Load.Ready)?.value.orEmpty()
    }

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()
    private val keys = ActionKeys()

    init {
        refresh()
    }

    fun refresh() {
        if (_state.value.refreshing) return
        _state.update { it.copy(refreshing = true) }
        viewModelScope.launch {
            val wallet = async { tryCall { api.getMyWallet().data } }
            val topups = async { tryCall { api.listMyTopups(limit = TOPUPS) } }
            val lines = async { tryCall { api.listMyTransactions(limit = PAGE) } }
            wallet.await()
                .onSuccess { w -> _state.update { it.copy(wallet = Load.Ready(w)) } }
                .onFailure { e -> _state.update { if (it.wallet is Load.Ready) it else it.copy(wallet = Load.Failed(e)) } }
            topups.await()
                .onSuccess { r -> _state.update { it.copy(topups = Load.Ready(r.data)) } }
                .onFailure { e -> _state.update { if (it.topups is Load.Ready) it else it.copy(topups = Load.Failed(e)) } }
            lines.await()
                .onSuccess { r -> _state.update { it.copy(lines = Load.Ready(r.data), linesCursor = r.meta?.nextCursor) } }
                .onFailure { e -> _state.update { if (it.lines is Load.Ready) it else it.copy(lines = Load.Failed(e)) } }
            _state.update { it.copy(refreshing = false) }
        }
    }

    fun loadMore() {
        val cursor = _state.value.linesCursor ?: return
        if (_state.value.loadingMore) return
        _state.update { it.copy(loadingMore = true) }
        viewModelScope.launch {
            tryCall { api.listMyTransactions(cursor = cursor, limit = PAGE) }
                .onSuccess { r -> _state.update { s -> s.copy(lines = Load.Ready((s.lineList + r.data).distinctBy { it.transactionId to it.kind }), linesCursor = r.meta?.nextCursor) } }
                .onFailure { e -> banners.error(e) }
            _state.update { it.copy(loadingMore = false) }
        }
    }

    fun edit(change: (Form) -> Form) = _state.update { it.copy(form = change(it.form), sendError = null) }

    /** A request for finance, not money: the balance changes only when it is approved (§9.2). */
    fun sendTopup() {
        val s = _state.value
        if (s.sending) return
        val body = WalletRules.topupBody(s.form.amount, s.form.method, s.form.payerReference, s.form.note) ?: return
        // The same request, the same key: a retry after a timeout cannot file it twice.
        val scope = "topup:${body.hashCode()}"
        _state.update { it.copy(sending = true, sendError = null) }
        banners.startAction()
        viewModelScope.launch {
            val result = tryCall { api.createMyTopup(body, keys.key(scope)).data }
            keys.settle(scope, result.exceptionOrNull())
            banners.endAction()
            result
                .onSuccess {
                    banners.show(BannerTone.OK, BannerText.Key("income.topupSent"))
                    _state.update { it.copy(sending = false, form = Form()) }
                    refresh()
                    onChanged()
                }
                .onFailure { e -> _state.update { it.copy(sending = false, sendError = e) } }
        }
    }

    private companion object {
        const val PAGE = 50L
        const val TOPUPS = 20L
    }
}
