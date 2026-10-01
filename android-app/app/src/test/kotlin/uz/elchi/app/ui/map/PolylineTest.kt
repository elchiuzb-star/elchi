package uz.elchi.app.ui.map

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PolylineTest {
    private fun assertPoint(lat: Double, lng: Double, point: GeoPoint) {
        assertEquals(lat, point.lat, 1e-9)
        assertEquals(lng, point.lng, 1e-9)
    }

    @Test
    fun `decodes Google's reference polyline`() {
        // https://developers.google.com/maps/documentation/utilities/polylinealgorithm
        val points = decodePolyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
        assertEquals(3, points.size)
        assertPoint(38.5, -120.2, points[0])
        assertPoint(40.7, -120.95, points[1])
        assertPoint(43.252, -126.453, points[2])
    }

    @Test
    fun `decodes a route the backend returned`() {
        // Dev corridor "M39 janub" from /directions/preview: starts in Tashkent, ends near Termiz.
        val points = decodePolyline("kqc{FcezeLjou@ciMj|hB~anBz_hAn~vD~cyArjkD~~yCzscFnr~Hc{aH")
        assertTrue(points.size >= 5)
        assertEquals(41.3, points.first().lat, 0.05)
        assertEquals(69.3, points.first().lng, 0.05)
        points.forEach { assertTrue("inside Uzbekistan: $it", it.lat in 37.0..46.0 && it.lng in 55.0..74.0) }
    }

    @Test
    fun `empty and truncated input do not throw`() {
        assertEquals(emptyList<GeoPoint>(), decodePolyline(""))
        // The first point is complete, the second is cut in the middle of its longitude.
        val truncated = decodePolyline("_p~iF~ps|U_ulL")
        assertEquals(1, truncated.size)
        assertPoint(38.5, -120.2, truncated[0])
    }

    @Test
    fun `bounds of a path`() {
        assertNull(boundsOf(emptyList()))
        val (sw, ne) = boundsOf(listOf(GeoPoint(41.3, 69.2), GeoPoint(39.6, 66.9), GeoPoint(40.0, 70.0)))!!
        assertEquals(GeoPoint(39.6, 66.9), sw)
        assertEquals(GeoPoint(41.3, 70.0), ne)
    }

    // The dev corridor from /directions/preview (Tashkent -> Samarkand -> Qarshi -> Termiz), vertex by vertex.
    private val corridor = listOf(
        GeoPoint(41.3111, 69.2797), GeoPoint(41.032, 69.353), GeoPoint(40.4897, 68.7842), GeoPoint(40.1158, 67.8422),
        GeoPoint(39.6542, 66.9597), GeoPoint(38.8606, 65.789), GeoPoint(37.2242, 67.2783),
    )

    @Test
    fun `leg path keeps only the road between the two places`() {
        // Chorsu projects onto the corridor's first vertex; Samarkand is a vertex. Nothing past Samarkand is drawn.
        val leg = legPath(corridor, GeoPoint(41.32239, 69.23639), GeoPoint(39.6542, 66.9597))
        assertEquals(corridor.subList(0, 5), leg)
    }

    @Test
    fun `leg path starts and ends at the projections inside segments`() {
        // A place just off the middle of segment 1, and one just off the middle of segment 4.
        val from = GeoPoint((41.032 + 40.4897) / 2 + 0.01, (69.353 + 68.7842) / 2)
        val to = GeoPoint((39.6542 + 38.8606) / 2, (66.9597 + 65.789) / 2 + 0.01)
        val leg = legPath(corridor, from, to)
        assertEquals(corridor.subList(2, 5), leg.subList(1, leg.size - 1))
        assertOnSegment(leg.first(), corridor[1], corridor[2])
        assertOnSegment(leg.last(), corridor[4], corridor[5])
        assertEquals(40.76, leg.first().lat, 0.02)
        assertEquals(39.26, leg.last().lat, 0.02)
    }

    @Test
    fun `leg path runs backwards for the opposite direction`() {
        val from = GeoPoint(38.87, 65.8) // by Qarshi
        val to = GeoPoint(40.12, 67.84) // by the fourth vertex
        val leg = legPath(corridor, from, to)
        // The vertices in between are walked in reverse corridor order and include Samarkand.
        val inner = leg.subList(1, leg.size - 1).map(corridor::indexOf)
        assertTrue(inner.all { it >= 0 })
        assertEquals(inner.sortedDescending(), inner)
        assertTrue(4 in inner)
        assertEquals(38.87, leg.first().lat, 0.02)
        assertEquals(40.12, leg.last().lat, 0.02)
    }

    @Test
    fun `leg path within one segment is just the two projections`() {
        val from = GeoPoint(40.9, 69.2)
        val to = GeoPoint(40.6, 68.9)
        val leg = legPath(corridor, from, to)
        assertEquals(2, leg.size)
        leg.forEach { assertOnSegment(it, corridor[1], corridor[2]) }
        assertTrue(leg[0].lat > leg[1].lat)
    }

    private fun assertOnSegment(p: GeoPoint, a: GeoPoint, b: GeoPoint) {
        // Collinear with a-b (cross product ~ 0) and between them.
        val cross = (b.lat - a.lat) * (p.lng - a.lng) - (b.lng - a.lng) * (p.lat - a.lat)
        assertEquals(0.0, cross, 1e-9)
        assertTrue(p.lat in minOf(a.lat, b.lat)..maxOf(a.lat, b.lat))
    }

    @Test
    fun `leg path is empty without a road or an end`() {
        assertTrue(legPath(emptyList(), GeoPoint(41.3, 69.2), GeoPoint(39.6, 66.9)).isEmpty())
        assertTrue(legPath(corridor.take(1), GeoPoint(41.3, 69.2), GeoPoint(39.6, 66.9)).isEmpty())
        assertTrue(legPath(corridor, null, GeoPoint(39.6, 66.9)).isEmpty())
        assertTrue(legPath(corridor, GeoPoint(41.3, 69.2), null).isEmpty())
    }

    @Test
    fun `camera bounds cover the route and never shrink below the minimum span`() {
        assertNull(cameraBounds(emptyList()))
        val (sw, ne) = cameraBounds(corridor)!!
        assertEquals(GeoPoint(37.2242, 65.789), sw)
        assertEquals(GeoPoint(41.3111, 69.353), ne)

        // Two places a street apart: a box of at least 0.01 degrees around their middle.
        val (a, b) = cameraBounds(listOf(GeoPoint(41.3000, 69.2400), GeoPoint(41.3010, 69.2402)))!!
        assertEquals(0.01, b.lat - a.lat, 1e-9)
        assertEquals(0.01, b.lng - a.lng, 1e-9)
        assertEquals(41.3005, (a.lat + b.lat) / 2, 1e-9)
        assertEquals(69.2401, (a.lng + b.lng) / 2, 1e-9)

        // A single point is centred in its box.
        val (c, d) = cameraBounds(listOf(GeoPoint(39.65, 66.96)))!!
        assertEquals(39.65, (c.lat + d.lat) / 2, 1e-9)
        assertEquals(66.96, (c.lng + d.lng) / 2, 1e-9)
    }
}
