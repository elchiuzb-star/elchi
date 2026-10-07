package uz.elchi.app.feature.driver

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import uz.elchi.app.api.DriverBookingDTO
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.feature.client.Load
import uz.elchi.app.gps.DriverTracker

/**
 * "Buyurtmalar": the driver's bookings (`GET /me/bookings?role=driver`, cursor pages), live first, then the history.
 * One per driver flow (the tab and the profile's "Buyurtmalarim" read the same list).
 */
class DriverBookingsViewModel(
    private val api: ElchiApi,
    /** This phone's GPS publisher: the Orders tab shows its bar like every other driver screen (design 08 0.2). */
    val tracker: DriverTracker? = null,
) : ViewModel() {
    data class State(
        val bookings: Load<List<DriverBookingDTO>> = Load.Loading,
        val cursor: String? = null,
        val loadingMore: Boolean = false,
        val refreshing: Boolean = false,
    ) {
        val list: List<DriverBookingDTO> get() = (bookings as? Load.Ready)?.value.orEmpty()
    }

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        if (_state.value.refreshing) return
        _state.update { it.copy(refreshing = true) }
        viewModelScope.launch {
            tryCall { api.listMyBookings(role = ROLE, limit = PAGE) }
                .onSuccess { page ->
                    val rows = page.data.mapNotNull(DriverBookingDTO::fromJson)
                    _state.update { it.copy(bookings = Load.Ready(DriverBookingRules.ordered(rows)), cursor = page.meta?.nextCursor) }
                }
                .onFailure { e -> _state.update { if (it.bookings is Load.Ready) it else it.copy(bookings = Load.Failed(e)) } }
            _state.update { it.copy(refreshing = false) }
        }
    }

    fun loadMore() {
        val cursor = _state.value.cursor ?: return
        if (_state.value.loadingMore) return
        _state.update { it.copy(loadingMore = true) }
        viewModelScope.launch {
            tryCall { api.listMyBookings(role = ROLE, cursor = cursor, limit = PAGE) }
                .onSuccess { page ->
                    val rows = page.data.mapNotNull(DriverBookingDTO::fromJson)
                    _state.update { s -> s.copy(bookings = Load.Ready(DriverBookingRules.ordered((s.list + rows).distinctBy { it.id })), cursor = page.meta?.nextCursor) }
                }
            _state.update { it.copy(loadingMore = false) }
        }
    }

    private companion object {
        const val ROLE = "driver"
        const val PAGE = 30L
    }
}
