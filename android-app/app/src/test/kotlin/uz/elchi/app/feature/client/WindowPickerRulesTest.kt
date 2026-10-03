package uz.elchi.app.feature.client

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.LocalDateTime

class WindowPickerRulesTest {
    private val today = LocalDate.parse("2026-09-27")
    private fun at(text: String) = LocalDateTime.parse(text)

    @Test
    fun `the strip is three weeks from today`() {
        val days = WindowPickerRules.days(today)
        assertEquals(21, days.size)
        assertEquals(today, days.first())
        assertEquals(LocalDate.parse("2026-10-17"), days.last())
    }

    @Test
    fun `the wheels open on the edge's value, an empty end six hours after the start, an empty start at noon`() {
        val start = at("2026-09-28T09:00")
        val end = at("2026-09-28T18:00")
        assertEquals(start, WindowPickerRules.initial(WindowEdge.START, start, end, today))
        assertEquals(end, WindowPickerRules.initial(WindowEdge.END, start, end, today))
        assertEquals(at("2026-09-28T15:00"), WindowPickerRules.initial(WindowEdge.END, start, null, today))
        assertEquals(at("2026-09-28T23:00"), WindowPickerRules.initial(WindowEdge.END, at("2026-09-28T20:00"), null, today))
        assertEquals(at("2026-09-27T12:00"), WindowPickerRules.initial(WindowEdge.START, null, null, today))
    }

    @Test
    fun `values snap onto the strip and onto quarters`() {
        assertEquals(at("2026-09-28T09:00"), WindowPickerRules.snap(at("2026-09-28T09:10"), today))
        assertEquals(at("2026-09-28T09:15"), WindowPickerRules.snap(at("2026-09-28T09:20"), today))
        assertEquals(at("2026-09-28T09:45"), WindowPickerRules.snap(at("2026-09-28T09:55"), today))
        // A day before today or after the strip falls back to today.
        assertEquals(at("2026-09-27T09:00"), WindowPickerRules.snap(at("2026-09-20T09:00"), today))
        assertEquals(at("2026-09-27T09:00"), WindowPickerRules.snap(at("2026-11-20T09:00"), today))
    }

    @Test
    fun `a start in the past and an end not after the start are refused`() {
        val now = at("2026-09-27T09:41")
        assertEquals(WindowPickError.PAST, WindowPickerRules.error(WindowEdge.START, at("2026-09-27T09:30"), null, now))
        assertNull(WindowPickerRules.error(WindowEdge.START, at("2026-09-27T09:45"), null, now))
        val start = at("2026-09-28T09:00")
        assertEquals(WindowPickError.END_BEFORE_START, WindowPickerRules.error(WindowEdge.END, start, start, now))
        assertEquals(WindowPickError.END_BEFORE_START, WindowPickerRules.error(WindowEdge.END, at("2026-09-28T08:45"), start, now))
        assertNull(WindowPickerRules.error(WindowEdge.END, at("2026-09-28T09:15"), start, now))
        assertNull(WindowPickerRules.error(WindowEdge.END, at("2026-09-28T09:15"), null, now))
    }

    @Test
    fun `quick ends are hours after the start or the end of its day`() {
        val start = at("2026-09-28T09:00")
        assertEquals(at("2026-09-28T11:00"), WindowPickerRules.quickEnd(start, 2))
        assertEquals(at("2026-09-28T17:00"), WindowPickerRules.quickEnd(start, 8))
        assertEquals(at("2026-09-28T23:45"), WindowPickerRules.quickEnd(start, null))
        assertEquals(at("2026-09-29T02:00"), WindowPickerRules.quickEnd(at("2026-09-28T18:00"), 8))
    }

    @Test
    fun `day and month names come from the dictionary's lists, Sunday first, with the design's as fallback`() {
        val uz = WindowNames.fromLists("Ya,Du,Se,Ch,Pa,Ju,Sh", "yan,fev,mar,apr,may,iyn,iyl,avg,sen,okt,noy,dek", null, ru = false)
        assertEquals("Ya", uz.weekdayShort(DayOfWeek.SUNDAY))
        assertEquals("Du", uz.weekdayShort(DayOfWeek.MONDAY))
        assertEquals("sen", uz.monthShort(9))
        assertEquals("Sentabr", uz.monthFull(9))
        // A broken list (wrong length) falls back to the built-in one.
        val ru = WindowNames.fromLists("Пн,Вт", "", "Январь", ru = true)
        assertEquals("Пн", ru.weekdayShort(DayOfWeek.MONDAY))
        assertEquals("Вс", ru.weekdayShort(DayOfWeek.SUNDAY))
        assertEquals("сен", ru.monthShort(9))
        assertEquals("Сентябрь", ru.monthFull(9))
    }
}
