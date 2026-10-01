package uz.elchi.app.feature.client

import androidx.lifecycle.ViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.BookingClientDTO
import uz.elchi.app.api.LiveSocketFactory
import uz.elchi.app.api.generated.ElchiApi

/**
 * `booking-tracking` "Kuzatuv": the status ladder (from the booking, read again every 15 s) and the live position
 * ([LiveTrackingSession]). Both run only while the screen is started ([watch]); leaving the screen or putting the
 * app in the background closes the socket and stops every poll.
 */
class TrackingViewModel(
    private val api: ElchiApi,
    val bookingId: String,
    private val sockets: LiveSocketFactory?,
    private val socketUrl: String,
    private val accessToken: () -> String?,
) : ViewModel() {

    data class State(
        val booking: Load<BookingClientDTO> = Load.Loading,
        val live: LiveState = LiveState(),
    )

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()

    suspend fun watch() = coroutineScope {
        launch {
            while (true) {
                loadBooking()
                delay(LiveTrackingSession.POLL_MS)
            }
        }
        LiveTrackingSession(
            bookingId = bookingId,
            fetch = { api.getBookingTracking(bookingId).data },
            sockets = sockets,
            socketUrl = socketUrl,
            accessToken = accessToken,
            update = { transform -> _state.update { it.copy(live = transform(it.live)) } },
        ).run()
    }

    private suspend fun loadBooking() {
        try {
            val booking = BookingClientDTO.fromJson(api.getBooking(bookingId).data) ?: throw ApiException(0, ApiException.SERVER, "not a client booking")
            _state.update { it.copy(booking = Load.Ready(booking)) }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            _state.update { if (it.booking is Load.Ready) it else it.copy(booking = Load.Failed(e)) }
        }
    }
}
