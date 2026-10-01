package uz.elchi.app.ui.map

import kotlin.math.cos

/** A coordinate, independent of any map SDK (the route must still be computable when the map cannot load). */
data class GeoPoint(val lat: Double, val lng: Double)

/**
 * Google encoded-polyline decoder - the format of `DirectionPreviewDTO.route_polyline` (the web client's
 * `utils/polyline.ts`, precision 5). https://developers.google.com/maps/documentation/utilities/polylinealgorithm
 * A truncated string yields the points decoded so far instead of throwing.
 */
fun decodePolyline(encoded: String, precision: Int = 5): List<GeoPoint> {
    if (encoded.isEmpty()) return emptyList()
    var factor = 1.0
    repeat(precision) { factor *= 10 }
    val points = ArrayList<GeoPoint>()
    var index = 0
    var lat = 0L
    var lng = 0L

    fun next(): Long? {
        var result = 0L
        var shift = 0
        while (true) {
            if (index >= encoded.length) return null
            val byte = encoded[index++].code - 63
            result = result or ((byte and 0x1f).toLong() shl shift)
            shift += 5
            if (byte < 0x20) break
        }
        return if (result and 1L != 0L) (result shr 1).inv() else result shr 1
    }

    while (index < encoded.length) {
        lat += next() ?: break
        lng += next() ?: break
        points += GeoPoint(lat / factor, lng / factor)
    }
    return points
}

/** South-west and north-east corners of a path; null for an empty one. */
fun boundsOf(points: List<GeoPoint>): Pair<GeoPoint, GeoPoint>? {
    if (points.isEmpty()) return null
    return GeoPoint(points.minOf { it.lat }, points.minOf { it.lng }) to GeoPoint(points.maxOf { it.lat }, points.maxOf { it.lng })
}

/**
 * The stretch of road between the two marked places. `route_polyline` is the whole corridor - often far longer
 * than the trip (Tashkent - Termiz for a Tashkent - Samarkand parcel) - and drawing all of it would run the line
 * past the destination and shrink the markers into a country-wide view. Each place is projected onto its nearest
 * segment; the leg is the first projection, the vertices between the two, then the second projection (walked
 * backwards when the destination lies before the origin along the road). The markers stay at the places
 * themselves, which may sit a little off the road. Empty when there is no road or either end is missing.
 */
fun legPath(path: List<GeoPoint>, from: GeoPoint?, to: GeoPoint?): List<GeoPoint> {
    if (path.size < 2 || from == null || to == null) return emptyList()
    val start = project(path, from)
    val end = project(path, to)
    val forward = start.segment < end.segment || (start.segment == end.segment && start.t <= end.t)
    val between = if (forward) path.subList(start.segment + 1, end.segment + 1) else path.subList(end.segment + 1, start.segment + 1).asReversed()
    val leg = ArrayList<GeoPoint>(between.size + 2)
    (listOf(start.point) + between + end.point).forEach { if (leg.lastOrNull() != it) leg += it }
    return leg
}

/** Where a point lands on a path: segment `i` runs from vertex i to i + 1, [t] is the fraction along it. */
private class Projection(val segment: Int, val t: Double, val point: GeoPoint)

/**
 * The nearest point to [p] on any segment of [path]. Distances are measured on a plane around [p] (longitude
 * scaled by cos(latitude)): exact enough to pick a segment and a spot on it at road scale.
 */
private fun project(path: List<GeoPoint>, p: GeoPoint): Projection {
    val k = cos(Math.toRadians(p.lat))
    var best = Projection(0, 0.0, path[0])
    var bestDistance = Double.MAX_VALUE
    for (i in 0 until path.size - 1) {
        val a = path[i]
        val b = path[i + 1]
        val ax = (a.lng - p.lng) * k
        val ay = a.lat - p.lat
        val dx = (b.lng - a.lng) * k
        val dy = b.lat - a.lat
        val length = dx * dx + dy * dy
        val t = if (length == 0.0) 0.0 else (-(ax * dx + ay * dy) / length).coerceIn(0.0, 1.0)
        val qx = ax + t * dx
        val qy = ay + t * dy
        val distance = qx * qx + qy * qy
        if (distance < bestDistance) {
            bestDistance = distance
            val point = when (t) {
                0.0 -> a
                1.0 -> b
                else -> GeoPoint(a.lat + t * (b.lat - a.lat), a.lng + t * (b.lng - a.lng))
            }
            best = Projection(i, t, point)
        }
    }
    return best
}

/**
 * The box the camera frames for [points]: their bounds, grown around the centre to at least [minSpan] degrees
 * each way so two places a street apart are not framed at building level. Null for no points.
 */
fun cameraBounds(points: List<GeoPoint>, minSpan: Double = 0.01): Pair<GeoPoint, GeoPoint>? {
    val (sw, ne) = boundsOf(points) ?: return null
    val halfLat = maxOf(ne.lat - sw.lat, minSpan) / 2
    val halfLng = maxOf(ne.lng - sw.lng, minSpan) / 2
    val lat = (sw.lat + ne.lat) / 2
    val lng = (sw.lng + ne.lng) / 2
    return GeoPoint(lat - halfLat, lng - halfLng) to GeoPoint(lat + halfLat, lng + halfLng)
}
