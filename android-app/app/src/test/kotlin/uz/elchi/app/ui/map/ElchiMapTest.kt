package uz.elchi.app.ui.map

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ElchiMapTest {
    @Test
    fun `MapKit locale follows the app language`() {
        assertEquals("uz_UZ", mapKitLocale("uz"))
        assertEquals("ru_RU", mapKitLocale("ru"))
        assertEquals("uz_UZ", mapKitLocale("en")) // Uzbek is the fallback language
    }

    @Test
    fun `an empty loading grid is not a drawn map`() {
        // Background, grid lines and a route with two markers: a handful of colours.
        val grid = IntArray(24 * 48) { i ->
            when {
                i % 24 == 0 || i / 24 % 12 == 0 -> 0xFFD8DCE0.toInt()
                i % 97 == 0 -> 0xFF1E96FF.toInt()
                i % 131 == 0 -> 0xFF0B1F44.toInt()
                i % 53 == 0 -> 0xFFFFFFFF.toInt()
                else -> 0xFFEEF1F4.toInt()
            }
        }
        assertFalse(looksDrawn(grid))
    }

    @Test
    fun `tiles are a drawn map`() {
        // Many distinct colours (land, roads, water, parks, labels) once the tiles are in.
        val tiles = IntArray(24 * 48) { i -> 0xFF000000.toInt() or ((i % 40) * 0x060503) }
        assertTrue(looksDrawn(tiles))
    }

    @Test
    fun `antialiasing noise does not count as colours`() {
        // Shades that differ only in the low 4 bits of each channel are one colour.
        val noise = IntArray(24 * 48) { i -> 0xFFEEF1F0.toInt() or (i % 16) or ((i % 13) shl 8) }
        assertFalse(looksDrawn(noise))
    }
}
