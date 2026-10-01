package uz.elchi.app.api

import kotlinx.serialization.json.JsonElement
import uz.elchi.app.api.generated.BookingAction
import uz.elchi.app.api.generated.BookingActionRequest

/**
 * `POST /bookings/{id}/actions/{action}`: the generated `bookingAction` puts the Kotlin enum's name into the path
 * (`.../actions/ARRIVE_AT_PICKUP`, which the server does not know), so the same request goes through the transport
 * with the wire value (`arrive_at_pickup`) and the Idempotency-Key.
 */
class BookingActionsApi(private val transport: ApiTransport) {
    suspend fun act(bookingId: String, action: BookingAction, body: BookingActionRequest, idempotencyKey: String): ApiResult<JsonElement> =
        transport.send(
            "POST",
            "/bookings/$bookingId/actions/${action.value}",
            emptyList(),
            transport.encode(BookingActionRequest.serializer(), body),
            idempotencyKey,
            JsonElement.serializer(),
        )
}
