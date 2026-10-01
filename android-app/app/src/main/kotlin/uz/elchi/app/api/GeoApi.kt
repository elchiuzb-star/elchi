package uz.elchi.app.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * A name for a coordinate, or a coordinate for a picked suggestion. `provider = "local"` means the server had no
 * geocoder answer and fell back to the nearest district: there is no real address, so the app shows coordinates.
 * The `detected_*_id` fields are v1 (legacy) ids and are deliberately not read - v2 districts are strings.
 */
@Serializable
data class GeocodeResult(
    @SerialName("formatted_address") val formattedAddress: String? = null,
    val lat: Double? = null,
    val lng: Double? = null,
    val region: String? = null,
    val district: String? = null,
    val provider: String = "",
) {
    val hasRealAddress: Boolean get() = provider != LOCAL && !formattedAddress.isNullOrBlank()

    companion object {
        const val LOCAL = "local"
    }
}

/** A typed-place suggestion. It carries no coordinate: [GeoApi.resolvePlace] turns the picked one into a point. */
@Serializable
data class PlaceSuggestion(
    val title: String? = null,
    val subtitle: String? = null,
    @SerialName("formatted_address") val formattedAddress: String? = null,
    val region: String? = null,
    val district: String? = null,
    val locality: String? = null,
    @SerialName("distance_m") val distanceM: Double? = null,
    val uri: String,
)

@Serializable
data class PlaceSuggestions(val results: List<PlaceSuggestion> = emptyList())

@Serializable
private data class ReverseGeocodeRequest(val lat: Double, val lng: Double, val language: String)

@Serializable
private data class SuggestRequest(
    val text: String,
    val language: String,
    @SerialName("near_lat") val nearLat: Double? = null,
    @SerialName("near_lng") val nearLng: Double? = null,
    @SerialName("span_deg") val spanDeg: Double? = null,
    val district: String? = null,
    val limit: Int = 10,
)

@Serializable
private data class ResolvePlaceRequest(val uri: String, val language: String)

/**
 * The geocoder goes through our own server (`/api/v1/geo/...`, Yandex behind it). The Yandex geocoder and suggest
 * keys live only on the backend; the app never talks to Yandex's HTTP APIs directly. Hand-typed like [AuthApi]:
 * v1 is not in the generated v2 contract.
 */
class GeoApi(private val transport: HttpTransport) {
    suspend fun reverseGeocode(lat: Double, lng: Double, language: String): GeocodeResult =
        transport.sendV1("POST", "/geo/reverse-geocode", json(ReverseGeocodeRequest.serializer(), ReverseGeocodeRequest(lat, lng, language)), auth = false, GeocodeResult.serializer()).data

    /** [nearLat]/[nearLng] + [district] bias the answer towards the chosen district without hiding the rest. */
    suspend fun suggest(text: String, language: String, nearLat: Double?, nearLng: Double?, district: String?, limit: Int = 8): List<PlaceSuggestion> {
        val near = nearLat != null && nearLng != null
        val body = SuggestRequest(text, language, nearLat, nearLng, if (near) SPAN_DEG else null, district, limit)
        return transport.sendV1("POST", "/geo/suggest", json(SuggestRequest.serializer(), body), auth = false, PlaceSuggestions.serializer()).data.results
    }

    /** `404 GEOCODE_FAILED` when the provider cannot place the suggestion. */
    suspend fun resolvePlace(uri: String, language: String): GeocodeResult =
        transport.sendV1("POST", "/geo/resolve-place", json(ResolvePlaceRequest.serializer(), ResolvePlaceRequest(uri, language)), auth = false, GeocodeResult.serializer()).data

    private fun <T> json(serializer: kotlinx.serialization.KSerializer<T>, value: T) = transport.encode(serializer, value)

    private companion object {
        /** The web client's search box around a district centre (about 35 km). */
        const val SPAN_DEG = 0.35
    }
}
