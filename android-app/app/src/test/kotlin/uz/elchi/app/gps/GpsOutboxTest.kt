package uz.elchi.app.gps

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.api.generated.PointRejectionDTO
import uz.elchi.app.api.generated.PointsBatchAck
import uz.elchi.app.api.generated.TrackingPointRejectReason
import uz.elchi.app.api.generated.TrackingSessionStatus

class GpsOutboxTest {
    private val t0 = 1_790_000_000_000L

    private fun fix(dtS: Long = 0, lat: Double = 41.30, lng: Double = 69.24, accuracy: Double = 8.4, speed: Double? = null, heading: Double? = null, mock: Boolean = false, battery: Int? = null) =
        GeoFix(lat, lng, accuracy, speed, heading, t0 + dtS * 1000, battery, mock)

    private fun boxWith(n: Int, startSeq: Long = 0, session: String = "trs_1", trip: String = "trp_1", stepS: Long = 10): Outbox {
        var box = GpsOutbox.empty(trip, session).copy(nextSeq = startSeq)
        repeat(n) { i -> box = GpsOutbox.enqueue(box, fix(dtS = i * stepS), t0 + n * stepS * 1000) }
        return box
    }

    private fun ack(accepted: List<Long> = emptyList(), duplicate: List<Long> = emptyList(), rejected: List<Long> = emptyList()) =
        PointsBatchAck(accepted, duplicate, rejected.map { PointRejectionDTO(TrackingPointRejectReason.TOO_OLD, it) }, TrackingSessionStatus.ACTIVE)

    // -- point mapping ------------------------------------------------------------------------------------------------

    @Test
    fun `a fix becomes a contract point in integer units with the platform mock flag`() {
        val point = GpsOutbox.toPoint(fix(accuracy = 12.6, speed = 13.4, heading = 359.7, mock = true, battery = 18), seq = 7)!!
        assertEquals(7L, point.seq)
        assertEquals(13L, point.accuracyM)
        assertEquals(13L, point.speedMps)
        // 359.7 rounds to 360, which the contract does not take: it wraps to 0.
        assertEquals(0L, point.headingDeg)
        assertEquals(18, point.batteryPct)
        assertTrue(point.isMock)
        val dto = point.toDto()
        assertEquals(true, dto.isMock)
        assertEquals(13L, dto.accuracyM)
        assertTrue(dto.capturedAt.endsWith("Z"))
    }

    @Test
    fun `optional fields out of range are left out, never corrected`() {
        val point = GpsOutbox.toPoint(fix(speed = 140.0, heading = -3.0, battery = 140), seq = 0)!!
        assertNull(point.speedMps) // > 100 m/s: the server would call it invalid
        assertNull(point.headingDeg)
        assertNull(point.batteryPct)
        assertFalse(point.isMock)
        assertNull(GpsOutbox.toPoint(fix(speed = Double.NaN), 0)!!.speedMps)
    }

    @Test
    fun `fixes the server would refuse are skipped`() {
        assertNull(GpsOutbox.toPoint(fix(lat = 91.0), 0))
        assertNull(GpsOutbox.toPoint(fix(lng = -181.0), 0))
        assertNull(GpsOutbox.toPoint(fix(lat = Double.NaN), 0))
        assertNull(GpsOutbox.toPoint(fix(accuracy = 10_001.0), 0))
        assertNull(GpsOutbox.toPoint(fix(accuracy = -1.0), 0))
        assertNull(GpsOutbox.toPoint(fix().copy(timeMs = 0), 0))
        assertNotNull(GpsOutbox.toPoint(fix(accuracy = 10_000.0), 0))
    }

    // -- sampling -----------------------------------------------------------------------------------------------------

    @Test
    fun `sampling keeps one fix per 10 s moving and per 30 s standing`() {
        val first = fix()
        assertTrue(GpsOutbox.shouldRecord(null, first))
        // Moving by speed: 10 s.
        assertFalse(GpsOutbox.shouldRecord(first, fix(dtS = 9, speed = 5.0)))
        assertTrue(GpsOutbox.shouldRecord(first, fix(dtS = 10, speed = 5.0)))
        // Moving by distance (>= 25 m) without a speed.
        assertTrue(GpsOutbox.shouldRecord(first, fix(dtS = 10, lat = 41.3003)))
        // Standing: 30 s.
        assertFalse(GpsOutbox.shouldRecord(first, fix(dtS = 29, speed = 0.2)))
        assertTrue(GpsOutbox.shouldRecord(first, fix(dtS = 30, speed = 0.2)))
        // A replayed or older fix never.
        assertFalse(GpsOutbox.shouldRecord(first, fix(dtS = 0)))
        assertFalse(GpsOutbox.shouldRecord(fix(dtS = 60), fix(dtS = 50, speed = 9.0)))
    }

    @Test
    fun `a held-back fix is kept on the tick only when the car moved or its cadence is due`() {
        val last = fix()
        assertTrue(GpsOutbox.recordPending(null, last))
        // Standing, 5 s later: not yet (30 s cadence) - a phone reporting every 5 s still keeps one per 30 s.
        assertFalse(GpsOutbox.recordPending(last, fix(dtS = 5, speed = 0.0)))
        assertTrue(GpsOutbox.recordPending(last, fix(dtS = 30, speed = 0.0)))
        // Moved 30+ m within 5 s: possibly the final place before a stop - kept.
        assertTrue(GpsOutbox.recordPending(last, fix(dtS = 5, lat = 41.3003)))
        assertFalse(GpsOutbox.recordPending(last, fix(dtS = 0, lat = 41.3003)))
    }

    @Test
    fun `distance follows the great circle`() {
        val d = GpsOutbox.distanceM(41.2995, 69.2401, 39.6542, 66.9597) // Tashkent - Samarkand
        assertTrue("$d", d in 265_000.0..275_000.0)
    }

    // -- queue ------------------------------------------------------------------------------------------------------

    @Test
    fun `enqueue numbers points per session and a refused fix uses no seq`() {
        var box = GpsOutbox.empty("trp_1", "trs_1")
        box = GpsOutbox.enqueue(box, fix(), t0)
        box = GpsOutbox.enqueue(box, fix(dtS = 10, lat = 95.0), t0)
        box = GpsOutbox.enqueue(box, fix(dtS = 20), t0 + 20_000)
        assertEquals(listOf(0L, 1L), box.points.map { it.seq })
        assertEquals(2L, box.nextSeq)
    }

    @Test
    fun `the queue keeps at most 24 hours and 20000 points and counts what it dropped`() {
        val day = GpsOutbox.LOCAL_QUEUE_MAX_AGE_MS
        val box = boxWith(3, stepS = 3600) // points at 0 h, 1 h, 2 h
        val pruned = GpsOutbox.prune(box, t0 + day + 90 * 60_000L) // now = 25.5 h: the 0 h and 1 h points are too old
        assertEquals(listOf(2L), pruned.points.map { it.seq })
        assertEquals(2, pruned.dropped)

        val many = GpsOutbox.empty("trp_1", "trs_1").copy(
            nextSeq = 20_005,
            points = (0 until 20_005).map { QueuedPoint(it.toLong(), t0 + it, 41.0, 69.0, 5) },
        )
        val capped = GpsOutbox.prune(many, t0 + 30_000)
        assertEquals(GpsOutbox.LOCAL_QUEUE_MAX_POINTS, capped.points.size)
        assertEquals(5L, capped.points.first().seq) // the oldest went first
        assertEquals(5, capped.dropped)
    }

    @Test
    fun `batches hold at most 100 points, oldest first`() {
        val box = boxWith(250, stepS = 10)
        val batch = GpsOutbox.nextBatch(box)
        assertEquals(100, batch.size)
        assertEquals(0L, batch.first().seq)
        assertEquals(25, GpsOutbox.nextBatch(box, limit = 25).size)
        assertEquals(100, GpsOutbox.nextBatch(box, limit = 1000).size)
    }

    @Test
    fun `only the ACK removes points - accepted, duplicate and rejected - and rejections are counted`() {
        val box = boxWith(5)
        val after = GpsOutbox.applyAck(box, ack(accepted = listOf(0, 1), duplicate = listOf(2), rejected = listOf(3)))
        assertEquals(listOf(4L), after.points.map { it.seq })
        assertEquals(1, after.dropped)
        // An empty answer changes nothing.
        assertEquals(box, GpsOutbox.applyAck(box, ack()))
    }

    @Test
    fun `a refused batch is dropped and counted so it cannot block the queue`() {
        val box = boxWith(5)
        val after = GpsOutbox.dropBatch(box, box.points.take(3))
        assertEquals(listOf(3L, 4L), after.points.map { it.seq })
        assertEquals(3, after.dropped)
    }

    @Test
    fun `points of an earlier session are renumbered into the new one in capture order`() {
        val earlier = GpsOutbox.empty("trp_1", "trs_old").copy(
            nextSeq = 40,
            points = listOf(QueuedPoint(31, t0 + 20_000, 41.0, 69.0, 5), QueuedPoint(30, t0 + 10_000, 41.0, 69.0, 5)),
            dropped = 2,
        )
        val fresh = GpsOutbox.empty("trp_1", "trs_new")
        val adopted = GpsOutbox.adoptPoints(fresh, earlier, t0 + 30_000)
        assertEquals("trs_new", adopted.sessionId)
        assertEquals(listOf(0L, 1L), adopted.points.map { it.seq })
        assertEquals(listOf(t0 + 10_000, t0 + 20_000), adopted.points.map { it.capturedMs })
        assertEquals(2L, adopted.nextSeq)
        assertEquals(2, adopted.dropped)
    }

    @Test
    fun `the stored outbox survives a round trip and a corrupt file is discarded`() {
        val box = GpsOutbox.applyAck(boxWith(3), ack(rejected = listOf(0)))
            .let { GpsOutbox.enqueue(it, fix(dtS = 100, speed = 4.0, heading = 90.0, mock = true, battery = 55), t0 + 100_000) }
        val parsed = GpsOutbox.parse(GpsOutbox.serialize(box))
        assertEquals(box, parsed)
        assertNull(GpsOutbox.parse(null))
        assertNull(GpsOutbox.parse("{not json"))
        assertNull(GpsOutbox.parse("""{"v":2,"trip":"t","session":"s","next":0,"points":[]}"""))
        // A point that the contract would refuse makes the whole file untrusted.
        assertNull(GpsOutbox.parse("""{"v":1,"trip":"t","session":"s","next":1,"points":[{"s":0,"t":$t0,"lat":95.0,"lng":69.0,"a":5}]}"""))
    }
}
