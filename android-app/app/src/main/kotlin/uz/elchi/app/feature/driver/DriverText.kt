package uz.elchi.app.feature.driver

import uz.elchi.app.feature.client.ParcelRules
import java.time.Instant
import java.time.format.DateTimeFormatter

/** Driver-screen times, always in Tashkent (§6 display rule). */
object DriverTime {
    private val CLOCK = DateTimeFormatter.ofPattern("HH:mm")
    private val DAY_CLOCK = DateTimeFormatter.ofPattern("dd.MM, HH:mm")

    /** `10:30` */
    fun clock(instant: Instant): String = instant.atZone(ParcelRules.TASHKENT).format(CLOCK)

    /** `29.09, 07:30` */
    fun dayClock(instant: Instant): String = instant.atZone(ParcelRules.TASHKENT).format(DAY_CLOCK)

    /** `10:30` today (Tashkent), else `02.10, 10:30`. */
    fun clockOrDay(instant: Instant, now: Instant): String =
        if (instant.atZone(ParcelRules.TASHKENT).toLocalDate() == now.atZone(ParcelRules.TASHKENT).toLocalDate()) clock(instant) else dayClock(instant)

    /** `27.09, 09:00 - 18:00` on one day, else both ends in full. */
    fun range(start: Instant, end: Instant): String {
        val s = start.atZone(ParcelRules.TASHKENT)
        val e = end.atZone(ParcelRules.TASHKENT)
        return if (s.toLocalDate() == e.toLocalDate()) "${s.format(DAY_CLOCK)} - ${e.format(CLOCK)}" else "${s.format(DAY_CLOCK)} - ${e.format(DAY_CLOCK)}"
    }
}
