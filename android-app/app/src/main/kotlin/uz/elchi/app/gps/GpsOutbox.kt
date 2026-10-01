package uz.elchi.app.gps

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import uz.elchi.app.api.ElchiJson
import uz.elchi.app.api.generated.PointsBatchAck
import uz.elchi.app.api.generated.TrackingPointIn
import java.time.Instant
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.roundToLong
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * The driver's GPS outbox (spec §10.3-§10.4, Q148) - pure: no Android, no network, no clock of its own. A port of the
 * web `mobile-app/src/app/gpsOutbox.ts`, with the native differences: `is_mock` is the platform's real flag, and the
 * queue lives in a file instead of `localStorage`.
 *
 * A fix becomes a contract point (`TrackingPointIn`: integer units, WGS84 degrees), goes into a local queue with a
 * per-session `seq`, leaves in batches of at most [MAX_POINTS_PER_BATCH], and is removed only by the server's ACK.
 * Nothing here invents a point: a fix the contract would refuse is skipped, never "corrected" into a new place, and
 * points the queue had to drop are counted so the screen can say that history is missing (§10.4).
 *
 * The numbers mirror `app/contracts/tracking.py`.
 */
object GpsOutbox {
    // --- mirrored contract values (app/contracts/tracking.py) ---------------------------------------------------
    const val MAX_POINTS_PER_BATCH = 100
    const val LOCAL_QUEUE_MAX_POINTS = 20_000
    const val LOCAL_QUEUE_MAX_AGE_MS = 24L * 3600 * 1000
    const val MAX_ACCURACY_M = 10_000
    const val MAX_SPEED_MPS_INPUT = 100

    /** §10.3 send targets: moving ~10 s, waiting 30 s (app configuration, not an OS guarantee). */
    const val SEND_INTERVAL_MOVING_SECONDS = 10
    const val SEND_INTERVAL_WAITING_SECONDS = 30

    /** §10.4 freshness: a position younger than this counts as "sending". */
    const val FRESH_MAX_AGE_SECONDS = 30

    /** At or above this speed (or distance since the last kept fix) the car is moving. */
    private const val MOVING_SPEED_MPS = 1.0
    private const val MOVING_DISTANCE_M = 25.0

    /**
     * The contract point for one fix, or null when the server would refuse it as `invalid` - a single bad field fails
     * the whole batch (422), so such a fix is skipped here rather than sent. Optional fields the phone cannot measure
     * are left out.
     */
    fun toPoint(fix: GeoFix, seq: Long): QueuedPoint? {
        if (!fix.lat.isFinite() || !fix.lng.isFinite() || fix.lat !in -90.0..90.0 || fix.lng !in -180.0..180.0) return null
        if (!fix.accuracy.isFinite() || fix.accuracy < 0 || fix.accuracy > MAX_ACCURACY_M) return null
        if (fix.timeMs <= 0 || seq < 0) return null
        val speed = fix.speed?.takeIf { it.isFinite() && it >= 0 }?.roundToLong()?.takeIf { it <= MAX_SPEED_MPS_INPUT }
        val heading = fix.heading?.takeIf { it.isFinite() && it >= 0 }?.roundToLong()?.let { it % 360 }
        val battery = fix.battery?.takeIf { it in 0..100 }
        return QueuedPoint(
            seq = seq,
            capturedMs = fix.timeMs,
            lat = fix.lat,
            lng = fix.lng,
            accuracyM = fix.accuracy.roundToLong(),
            speedMps = speed,
            headingDeg = heading,
            batteryPct = battery,
            isMock = fix.isMock,
        )
    }

    /** Great-circle distance in metres (same formula as the server's `rules.distance_m`). */
    fun distanceM(aLat: Double, aLng: Double, bLat: Double, bLng: Double): Double {
        val rad = Math.PI / 180
        val dphi = (bLat - aLat) * rad
        val dlmb = (bLng - aLng) * rad
        val h = sin(dphi / 2).let { it * it } + cos(aLat * rad) * cos(bLat * rad) * sin(dlmb / 2).let { it * it }
        return 2 * 6_371_008.8 * asin(min(1.0, sqrt(h)))
    }

    /**
     * Sampling: the provider may report every second; the queue keeps one fix per ~10 s while moving and per ~30 s
     * while standing (§10.3). A fix not newer than the last kept one is dropped (a cached position replayed).
     */
    fun shouldRecord(previous: GeoFix?, next: GeoFix): Boolean {
        if (previous == null) return true
        val elapsed = next.timeMs - previous.timeMs
        if (elapsed <= 0) return false
        val moving = (next.speed?.takeIf { it.isFinite() }?.let { it >= MOVING_SPEED_MPS } == true) ||
            distanceM(previous.lat, previous.lng, next.lat, next.lng) >= MOVING_DISTANCE_M
        val interval = if (moving) SEND_INTERVAL_MOVING_SECONDS else SEND_INTERVAL_WAITING_SECONDS
        return elapsed >= interval * 1000L
    }

    /**
     * On each tick the newest fix sampling held back is kept when it is the car's new place (moved >= 25 m since the
     * last kept fix: possibly its final position before it stops) or its cadence is due anyway. A standing phone whose
     * provider reports every few seconds therefore still keeps one fix per 30 s (§10.3), not one per tick.
     */
    fun recordPending(last: GeoFix?, pending: GeoFix): Boolean {
        if (last == null) return true
        if (pending.timeMs <= last.timeMs) return false
        return distanceM(last.lat, last.lng, pending.lat, pending.lng) >= MOVING_DISTANCE_M || shouldRecord(last, pending)
    }

    fun empty(tripId: String, sessionId: String): Outbox = Outbox(tripId, sessionId, nextSeq = 0, points = emptyList(), dropped = 0)

    /** Enforce §10.4: at most 24 hours and 20 000 points; the oldest go first and are counted. */
    fun prune(outbox: Outbox, nowMs: Long): Outbox {
        val cutoff = nowMs - LOCAL_QUEUE_MAX_AGE_MS
        var points = outbox.points.filter { it.capturedMs >= cutoff }
        if (points.size > LOCAL_QUEUE_MAX_POINTS) points = points.takeLast(LOCAL_QUEUE_MAX_POINTS)
        if (points.size == outbox.points.size) return outbox
        return outbox.copy(points = points, dropped = outbox.dropped + (outbox.points.size - points.size))
    }

    /** Add one fix under the next `seq`; a fix the contract would refuse is skipped without using a `seq`. */
    fun enqueue(outbox: Outbox, fix: GeoFix, nowMs: Long): Outbox {
        val point = toPoint(fix, outbox.nextSeq) ?: return outbox
        return prune(outbox.copy(nextSeq = outbox.nextSeq + 1, points = outbox.points + point), nowMs)
    }

    /** The oldest points, at most [limit] (never more than the contract's batch size). */
    fun nextBatch(outbox: Outbox, limit: Int = MAX_POINTS_PER_BATCH): List<QueuedPoint> =
        outbox.points.take(limit.coerceIn(1, MAX_POINTS_PER_BATCH))

    /**
     * Remove what the server answered for. Accepted and duplicate points are stored; rejected ones (`too_old`,
     * `future_timestamp`, `invalid`, `payload_conflict`) would be rejected again on every retry, so they leave the queue
     * too and are counted as missing history. Nothing else is removed.
     */
    fun applyAck(outbox: Outbox, ack: PointsBatchAck): Outbox {
        val rejected = ack.rejected.map { it.seq }.toSet()
        val answered = ack.acceptedSeqs.toSet() + ack.duplicateSeqs + rejected
        if (answered.isEmpty()) return outbox
        val points = outbox.points.filterNot { it.seq in answered }
        val removedRejected = outbox.points.count { it.seq in rejected }
        return outbox.copy(points = points, dropped = outbox.dropped + removedRejected)
    }

    /**
     * Carry points an earlier session could not take (network down, the session already replaced) into a new session
     * of the same trip. `seq` is per session, so they are renumbered in capture order; the points themselves are
     * unchanged.
     */
    fun adoptPoints(outbox: Outbox, earlier: Outbox, nowMs: Long): Outbox {
        var next = outbox.nextSeq
        val adopted = earlier.points.sortedBy { it.capturedMs }.map { it.copy(seq = next++) }
        return prune(outbox.copy(nextSeq = next, points = outbox.points + adopted, dropped = outbox.dropped + earlier.dropped), nowMs)
    }

    /** A batch the server refused as a whole (422): drop exactly those points so one bad point cannot block the queue. */
    fun dropBatch(outbox: Outbox, batch: List<QueuedPoint>): Outbox {
        val seqs = batch.map { it.seq }.toSet()
        val points = outbox.points.filterNot { it.seq in seqs }
        return outbox.copy(points = points, dropped = outbox.dropped + (outbox.points.size - points.size))
    }

    // --- storage ------------------------------------------------------------------------------------------------

    fun serialize(outbox: Outbox): String = ElchiJson.encodeToString(
        StoredOutbox.serializer(),
        StoredOutbox(
            v = 1,
            trip = outbox.tripId,
            session = outbox.sessionId,
            next = outbox.nextSeq,
            dropped = outbox.dropped,
            points = outbox.points.map { StoredPoint(it.seq, it.capturedMs, it.lat, it.lng, it.accuracyM, it.speedMps, it.headingDeg, it.batteryPct, if (it.isMock) 1 else 0) },
        ),
    )

    /** Null for anything that is not a well-formed stored outbox (a corrupt file is discarded, never half-trusted). */
    fun parse(raw: String?): Outbox? {
        if (raw.isNullOrBlank()) return null
        val stored = runCatching { ElchiJson.decodeFromString(StoredOutbox.serializer(), raw) }.getOrNull() ?: return null
        if (stored.v != 1 || stored.next < 0) return null
        val points = stored.points.map { p ->
            val fix = GeoFix(p.lat, p.lng, p.a.toDouble(), p.sp?.toDouble(), p.h?.toDouble(), p.t, p.b, p.m == 1)
            toPoint(fix, p.s)?.takeIf { p.s < stored.next } ?: return null
        }
        return Outbox(stored.trip, stored.session, stored.next, points, stored.dropped.coerceAtLeast(0))
    }
}

/** What the location provider gave us. [timeMs] is the fix's own time (the device clock); [battery] 0-100 at that time. */
data class GeoFix(
    val lat: Double,
    val lng: Double,
    val accuracy: Double,
    val speed: Double?,
    val heading: Double?,
    val timeMs: Long,
    val battery: Int? = null,
    /** Android `Location.isMock` (API 31+) / `isFromMockProvider`: a real platform signal, unlike the web's constant. */
    val isMock: Boolean = false,
)

/** One queued point, already in contract units; [TrackingPointIn] only when it leaves. */
data class QueuedPoint(
    val seq: Long,
    val capturedMs: Long,
    val lat: Double,
    val lng: Double,
    val accuracyM: Long,
    val speedMps: Long? = null,
    val headingDeg: Long? = null,
    val batteryPct: Int? = null,
    val isMock: Boolean = false,
) {
    fun toDto(): TrackingPointIn = TrackingPointIn(
        accuracyM = accuracyM,
        batteryPct = batteryPct?.toLong(),
        capturedAt = Instant.ofEpochMilli(capturedMs).toString(),
        headingDeg = headingDeg,
        isMock = isMock,
        lat = lat,
        lng = lng,
        seq = seq,
        speedMps = speedMps,
    )
}

data class Outbox(
    val tripId: String,
    val sessionId: String,
    val nextSeq: Long,
    val points: List<QueuedPoint>,
    /** Points the queue dropped (too old, over the size limit) or the server refused: history that does not exist. */
    val dropped: Int,
)

/** Compact on disk: a full queue (20 000 points) stays around 1.5 MB. */
@Serializable
private data class StoredOutbox(
    val v: Int,
    val trip: String,
    val session: String,
    val next: Long,
    val dropped: Int = 0,
    val points: List<StoredPoint>,
)

@Serializable
private data class StoredPoint(
    val s: Long,
    val t: Long,
    val lat: Double,
    val lng: Double,
    val a: Long,
    @SerialName("sp") val sp: Long? = null,
    val h: Long? = null,
    val b: Int? = null,
    val m: Int = 0,
)
