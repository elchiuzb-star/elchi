package uz.elchi.app.feature.driver

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import uz.elchi.app.api.generated.FeedSide
import uz.elchi.app.api.generated.MatchGroup
import uz.elchi.app.api.generated.MatchReason
import uz.elchi.app.api.generated.MatchType
import uz.elchi.app.api.generated.SavedSearchDTO
import uz.elchi.app.api.generated.ServiceType
import java.time.Instant

class FeedRulesTest {
    // 23:30 in Tashkent on 1 October: "today" is still the 1st there, though UTC is the same day too.
    private val lateEvening: Instant = Instant.parse("2026-10-01T18:30:00Z")
    // 02:00 in Tashkent on 2 October while UTC is still the 1st: the chip must follow Tashkent.
    private val earlyMorning: Instant = Instant.parse("2026-10-01T21:00:00Z")

    private val tashkentCity = FeedEnd(regionId = "reg_tash", regionName = "Toshkent shahri", requiresDistrict = false)
    private val samarqand = FeedEnd(regionId = "reg_sam", regionName = "Samarqand viloyati", requiresDistrict = true, districtId = "dst_sam", districtName = "Samarqand")

    @Test
    fun `one id per side, district first, region only where no district is required`() {
        assertEquals(EndIds(null, "dst_sam"), FeedRules.endIds(samarqand))
        assertEquals(EndIds("reg_tash", null), FeedRules.endIds(tashkentCity))
        assertEquals(EndIds(null, "dst_chil"), FeedRules.endIds(tashkentCity.copy(districtId = "dst_chil")))
        assertNull(FeedRules.endIds(samarqand.copy(districtId = null)))
        assertNull(FeedRules.endIds(FeedEnd()))
    }

    @Test
    fun `date chips are Tashkent day boundaries`() {
        assertEquals("2026-10-01T00:00:00+05:00" to "2026-10-02T00:00:00+05:00", FeedRules.dateRange(FeedDays.TODAY, lateEvening))
        assertEquals("2026-10-02T00:00:00+05:00" to "2026-10-03T00:00:00+05:00", FeedRules.dateRange(FeedDays.TOMORROW, lateEvening))
        assertEquals("2026-10-01T00:00:00+05:00" to "2026-10-04T00:00:00+05:00", FeedRules.dateRange(FeedDays.THREE, lateEvening))
        assertEquals("2026-10-01T00:00:00+05:00" to "2026-10-15T00:00:00+05:00", FeedRules.dateRange(FeedDays.FOURTEEN, lateEvening))
        assertEquals("2026-10-02T00:00:00+05:00" to "2026-10-03T00:00:00+05:00", FeedRules.dateRange(FeedDays.TODAY, earlyMorning))
    }

    @Test
    fun `query needs both ends and defaults to 14 days of parcel requests`() {
        assertNull(FeedRules.query(FeedFilter(origin = tashkentCity), lateEvening))
        val q = FeedRules.query(FeedFilter(origin = tashkentCity, destination = samarqand), lateEvening)!!
        assertEquals(ServiceType.PARCEL, q.service)
        assertEquals(EndIds("reg_tash", null), q.origin)
        assertEquals(EndIds(null, "dst_sam"), q.destination)
        assertEquals("2026-10-15T00:00:00+05:00", q.dateTo)
        val passenger = FeedFilter(service = "passenger", origin = tashkentCity, destination = samarqand)
        assertEquals(ServiceType.PARCEL, FeedRules.effectiveService(passenger, passengerEnabled = false).serviceType)
        assertEquals(ServiceType.PASSENGER, FeedRules.effectiveService(passenger, passengerEnabled = true).serviceType)
    }

    @Test
    fun `filter survives a round trip and garbage reads as the default`() {
        val f = FeedFilter(origin = tashkentCity, destination = samarqand, days = FeedDays.THREE)
        assertEquals(f, FeedRules.decode(FeedRules.encode(f)))
        assertEquals(FeedFilter(), FeedRules.decode("{not json"))
        assertEquals(FeedFilter(), FeedRules.decode(null))
    }

    @Test
    fun `alternatives are split off and time_differs wins over nearby_stop`() {
        val items = listOf(
            S08.feedItem("a"),
            S08.feedItem("b", MatchGroup.ALTERNATIVE, listOf(MatchReason.NEARBY_STOP, MatchReason.TIME_DIFFERS)),
            S08.feedItem("c", type = MatchType.EXACT),
            S08.feedItem("d", MatchGroup.UNKNOWN),
        )
        val g = FeedRules.split(items)
        assertEquals(listOf("a", "c", "d"), g.primary.map { it.listing.id })
        assertEquals(listOf("b"), g.alternative.map { it.listing.id })
        assertEquals("time_differs", FeedRules.alternativeReason(listOf(MatchReason.NEARBY_STOP, MatchReason.TIME_DIFFERS)))
        assertEquals("nearby_stop", FeedRules.alternativeReason(listOf(MatchReason.NEARBY_STOP)))
        assertNull(FeedRules.alternativeReason(listOf(MatchReason.FULL_ROUTE)))
        assertEquals("match.exact", FeedRules.matchKey(MatchType.EXACT))
        assertEquals("match.on_route", FeedRules.matchKey(MatchType.ON_ROUTE))
        assertNull(FeedRules.matchKey(MatchType.DETOUR))
    }

    @Test
    fun `card ends use the stop or the district, never the street address`() {
        val l = S08.listing()
        assertEquals("Toshkent shahri", FeedRules.endName(l.originStop, l.originPoint, ru = false))
        assertEquals("Samarqand", FeedRules.endName(l.destinationStop, l.destinationPoint, ru = false))
        assertEquals("Registon", FeedRules.endName(S08.stop("stp_reg", "Registon"), null, ru = false))
    }

    @Test
    fun `saved search body is the feed's ends for 14 days from now`() {
        val q = FeedRules.query(FeedFilter(origin = tashkentCity, destination = samarqand), lateEvening)!!
        val body = FeedRules.savedSearchBody(q, Instant.parse("2026-10-01T06:15:42Z"))
        assertEquals("reg_tash", body.originRegionId)
        assertNull(body.originDistrictId)
        assertEquals("dst_sam", body.destinationDistrictId)
        assertNull(body.destinationRegionId)
        assertEquals(FeedSide.REQUESTS, body.side)
        assertEquals(ServiceType.PARCEL, body.serviceType)
        assertEquals(1L, body.quantity)
        assertEquals(true, body.notify)
        assertEquals("2026-10-01T11:15:00+05:00", body.timeWindowStart)
        assertEquals("2026-10-15T11:15:00+05:00", body.timeWindowEnd)
    }

    @Test
    fun `saved route title reads names, never ids`() {
        val saved = SavedSearchDTO(
            createdAt = "2026-10-01T06:00:00Z", id = "svs_1", notify = true, quantity = 1, serviceType = ServiceType.PARCEL, side = FeedSide.REQUESTS,
            originRegionId = "reg_tash", destinationDistrictId = "dst_sam",
            timeWindowEnd = "2026-10-15T06:00:00Z", timeWindowStart = "2026-10-01T06:00:00Z",
        )
        assertEquals("Toshkent shahri → Samarqand", FeedRules.savedRouteTitle(saved, mapOf("reg_tash" to "Toshkent shahri", "dst_sam" to "Samarqand"), "•"))
        assertEquals("? → Samarqand", FeedRules.savedRouteTitle(saved, mapOf("dst_sam" to "Samarqand"), "•"))
    }
}
