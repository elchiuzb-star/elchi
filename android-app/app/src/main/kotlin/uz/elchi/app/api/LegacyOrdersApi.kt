package uz.elchi.app.api

import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.JsonElement

/** A district as the v1 order card names it. */
@Serializable
data class LegacyDistrict(
    val id: Long? = null,
    @SerialName("name_uz") val nameUz: String? = null,
    @SerialName("name_ru") val nameRu: String? = null,
)

/**
 * One order of the first (v1) marketplace, read-only (Q4). Prices are DECIMAL so'm (`"70000.00"` or a number),
 * not minor units - [uz.elchi.app.feature.client.OrderRules.legacyPriceMinor] converts them.
 */
@Serializable
data class LegacyOrder(
    val id: Long,
    @SerialName("order_number") val orderNumber: String? = null,
    val status: String,
    @SerialName("from_city") val fromCity: String? = null,
    @SerialName("to_city") val toCity: String? = null,
    @SerialName("from_district") val fromDistrict: LegacyDistrict? = null,
    @SerialName("to_district") val toDistrict: LegacyDistrict? = null,
    @SerialName("cargo_type") val cargoType: String? = null,
    @SerialName("suggested_price") val suggestedPrice: JsonElement? = null,
    @SerialName("client_price") val clientPrice: JsonElement? = null,
    @SerialName("final_price") val finalPrice: JsonElement? = null,
    @SerialName("bids_count") val bidsCount: Long? = null,
    @SerialName("created_at") val createdAt: String? = null,
)

@Serializable
data class LegacyPagination(val page: Int = 1, val limit: Int = 20, val total: Int = 0, @SerialName("total_pages") val totalPages: Int = 0)

@Serializable
data class LegacyOrdersPage(val items: List<LegacyOrder> = emptyList(), val pagination: LegacyPagination = LegacyPagination())

/** A region of the v1 detail (`from_city` / `to_city` is an object there, a bare name on the list card). */
@Serializable
data class LegacyCity(val id: Long? = null, @SerialName("name_uz") val nameUz: String? = null)

/**
 * The driver v1 put on an order. [phone] comes once a driver is selected (v1 has no chat); the app shows it only from
 * `accepted` on ([uz.elchi.app.feature.client.LegacyRules.phoneVisible]).
 */
@Serializable
data class LegacyDriver(
    val id: Long? = null,
    @SerialName("full_name") val fullName: String? = null,
    val phone: String? = null,
    @SerialName("car_model") val carModel: String? = null,
    @SerialName("plate_number") val plateNumber: String? = null,
    val rating: Double? = null,
    @SerialName("completed_orders") val completedOrders: Long? = null,
)

/** `GET /api/v1/client/orders/{id}`: the card plus the addresses, the client's own phones, the photo and the driver. */
@Serializable
data class LegacyOrderDetail(
    val id: Long,
    @SerialName("order_number") val orderNumber: String? = null,
    val status: String,
    @SerialName("from_city") val fromCity: LegacyCity? = null,
    @SerialName("to_city") val toCity: LegacyCity? = null,
    @SerialName("from_district") val fromDistrict: LegacyDistrict? = null,
    @SerialName("to_district") val toDistrict: LegacyDistrict? = null,
    @SerialName("pickup_address") val pickupAddress: String? = null,
    @SerialName("dropoff_address") val dropoffAddress: String? = null,
    @SerialName("pickup_lat") val pickupLat: Double? = null,
    @SerialName("pickup_lng") val pickupLng: Double? = null,
    @SerialName("dropoff_lat") val dropoffLat: Double? = null,
    @SerialName("dropoff_lng") val dropoffLng: Double? = null,
    @SerialName("sender_phone") val senderPhone: String? = null,
    @SerialName("receiver_phone") val receiverPhone: String? = null,
    @SerialName("cargo_type") val cargoType: String? = null,
    /** Short-lived signed link, downloaded with the token like a v2 parcel photo. */
    @SerialName("cargo_photo_url") val cargoPhotoUrl: String? = null,
    val comment: String? = null,
    @SerialName("suggested_price") val suggestedPrice: JsonElement? = null,
    @SerialName("client_price") val clientPrice: JsonElement? = null,
    @SerialName("final_price") val finalPrice: JsonElement? = null,
    @SerialName("assigned_driver") val assignedDriver: LegacyDriver? = null,
    @SerialName("accepted_bid_id") val acceptedBidId: Long? = null,
    @SerialName("bids_count") val bidsCount: Long? = null,
    @SerialName("created_at") val createdAt: String? = null,
)

/** One active bid on a v1 order (sorted by price by the server). No phone before a driver is chosen. */
@Serializable
data class LegacyBid(
    val id: Long,
    val price: JsonElement? = null,
    val status: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
    val driver: LegacyDriver? = null,
)

@Serializable
private data class SelectDriverBody(@SerialName("bid_id") val bidId: Long)

@Serializable
private data class RatingBody(val rating: Int, val comment: String? = null)

@Serializable
private data class CancelBody(val reason: String)

@Serializable
private data class DisputeBody(val reason: String, val comment: String? = null)

/**
 * The client's orders of the first (v1) marketplace (Q4): never migrated, never created, edited or published here -
 * only viewed, and the steps left in their life cycle (choose a driver, confirm delivery, rate, cancel, report a
 * problem). Hand-typed like [GeoApi]: v1 is not in the generated v2 contract. Envelope `{success, data, message}`.
 */
class LegacyOrdersApi(private val transport: HttpTransport) {
    /** `GET /client/orders` - the card list, paged. */
    suspend fun clientOrders(page: Int, limit: Int = PAGE): LegacyOrdersPage =
        transport.sendV1("GET", ORDERS, null, auth = true, LegacyOrdersPage.serializer(), query = listOf("page" to page, "limit" to limit)).data

    /** 404 NOT_FOUND / 403 FORBIDDEN when it is not (or no longer) this client's. */
    suspend fun order(id: Long): LegacyOrderDetail =
        transport.sendV1("GET", "$ORDERS/$id", null, auth = true, LegacyOrderDetail.serializer()).data

    suspend fun bids(id: Long): List<LegacyBid> =
        transport.sendV1("GET", "$ORDERS/$id/bids", null, auth = true, ListSerializer(LegacyBid.serializer())).data

    /** Only in `bidding`: ORDER_INVALID_STATUS, BID_NOT_ACTIVE, DRIVER_NOT_APPROVED / _BLOCKED / _NOT_AVAILABLE. */
    suspend fun selectDriver(id: Long, bidId: Long) {
        transport.sendV1("POST", "$ORDERS/$id/select-driver", json(SelectDriverBody.serializer(), SelectDriverBody(bidId)), auth = true, JsonElement.serializer())
    }

    /** Only in `delivered`; the order becomes `confirmed`. */
    suspend fun confirm(id: Long) {
        transport.sendV1("POST", "$ORDERS/$id/confirm", null, auth = true, JsonElement.serializer())
    }

    /** Only in `confirmed`; a repeat is 409 ALREADY_EXISTS (the caller treats it as done). */
    suspend fun rate(id: Long, stars: Int, comment: String?) {
        transport.sendV1("POST", "$ORDERS/$id/rating", json(RatingBody.serializer(), RatingBody(stars, comment)), auth = true, JsonElement.serializer())
    }

    /** [reason] is stored as text (the Uzbek sentence, as the web client sends it). After pickup: ORDER_INVALID_STATUS. */
    suspend fun cancel(id: Long, reason: String) {
        transport.sendV1("POST", "$ORDERS/$id/cancel", json(CancelBody.serializer(), CancelBody(reason)), auth = true, JsonElement.serializer())
    }

    /**
     * `POST /api/v1/orders/{id}/disputes`. [reason] must be the enum code (`delayed`, `lost`, ...), never a sentence -
     * the server refuses text with 400. 409 ALREADY_EXISTS when one is open. The order becomes `disputed`.
     */
    suspend fun openDispute(id: Long, reason: String, comment: String?) {
        transport.sendV1("POST", "/orders/$id/disputes", json(DisputeBody.serializer(), DisputeBody(reason, comment)), auth = true, JsonElement.serializer())
    }

    private fun <T> json(serializer: KSerializer<T>, value: T) = transport.encode(serializer, value)

    companion object {
        const val PAGE = 20
        private const val ORDERS = "/client/orders"
    }
}
