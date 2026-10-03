package uz.elchi.app.feature.client

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.api.ElchiJson
import uz.elchi.app.api.generated.DirectionPreviewDTO
import uz.elchi.app.api.generated.ListingCreate
import uz.elchi.app.api.generated.PointEndDTO
import java.time.Instant
import java.time.LocalDateTime

class ParcelRulesTest {
    private val nbsp = ParcelRules.NBSP

    private val tashkent = Place(
        regionId = "reg_tk", regionUz = "Toshkent shahri", districtId = "dst_tk", districtUz = "Toshkent shahri",
        lat = 41.2856, lng = 69.2044, address = "Chilonzor, 9-kvartal",
    )
    private val samarkand = Place(
        regionId = "reg_sa", regionUz = "Samarqand viloyati", districtId = "dst_sa", districtUz = "Samarqand",
        lat = 39.6547, lng = 66.9758, address = null,
    )

    /** 29.09.2026 15:00 in Tashkent. */
    private val now: Instant = Instant.parse("2026-09-29T10:00:00Z")

    private fun complete() = ParcelDraft(
        origin = tashkent,
        destination = samarkand,
        windowStart = "2026-09-30T09:00",
        windowEnd = "2026-09-30T18:00",
        priceDigits = "120000",
        senderName = " Aziza Karimova ",
        senderDigits = "901234567",
        receiverName = "Dilnoza Rahimova",
        receiverDigits = "915552211",
        comment = "  Ertalab 10 gacha qo'ng'iroq qilmang ",
        parcelType = "box",
        categoryId = "pct_small",
        photoFileUrl = "/api/v1/files/cargo/abc.jpg?exp=1&sig=x",
    )

    // -- money --------------------------------------------------------------------------------------------------

    @Test
    fun `so'm text becomes minor units, anything else is null`() {
        assertEquals(12_000_000L, ParcelRules.soumToMinor("120000"))
        assertEquals(12_000_000L, ParcelRules.soumToMinor("120 000"))
        assertEquals(12_000_000L, ParcelRules.soumToMinor("120${nbsp}000"))
        assertEquals(100L, ParcelRules.soumToMinor("1"))
        assertNull(ParcelRules.soumToMinor(""))
        assertNull(ParcelRules.soumToMinor("0"))
        assertNull(ParcelRules.soumToMinor("12.5"))
        assertNull(ParcelRules.soumToMinor("-5"))
        assertNull(ParcelRules.soumToMinor("9999999999999")) // no overflow into nonsense
        assertEquals(120_000L, ParcelRules.minorToSoum(12_000_000L))
    }

    @Test
    fun `prices are grouped by thousands with a no-break space`() {
        assertEquals("999", ParcelRules.groupThousands(999))
        assertEquals("120${nbsp}000", ParcelRules.groupThousands(120_000))
        assertEquals("1${nbsp}234${nbsp}567", ParcelRules.groupThousands(1_234_567))
        assertEquals("120${nbsp}000${nbsp}so'm", ParcelRules.formatSoum(12_000_000, "so'm"))
    }

    // -- departure window ---------------------------------------------------------------------------------------

    @Test
    fun `default window is tomorrow 09-18 in Tashkent, whatever the UTC date`() {
        val (start, end) = ParcelRules.defaultWindow(now)
        assertEquals(LocalDateTime.parse("2026-09-30T09:00"), start)
        assertEquals(LocalDateTime.parse("2026-09-30T18:00"), end)
        // 20:30 UTC on the 29th is already 01:30 on the 30th in Tashkent: "tomorrow" is the 1st.
        val (lateStart, _) = ParcelRules.defaultWindow(Instant.parse("2026-09-29T20:30:00Z"))
        assertEquals(LocalDateTime.parse("2026-10-01T09:00"), lateStart)
    }

    @Test
    fun `window times go to the API as instants with the Tashkent offset`() {
        assertEquals("2026-09-30T09:00:00+05:00", ParcelRules.toOffsetIso(LocalDateTime.parse("2026-09-30T09:00")))
        assertEquals("2026-09-30T09:00", ParcelRules.formatLocal(LocalDateTime.parse("2026-09-30T09:00:41")))
        assertEquals("30.09.2026, 09:00", ParcelRules.display(LocalDateTime.parse("2026-09-30T09:00")))
        assertEquals("30.09, 18:00", ParcelRules.displayShort(LocalDateTime.parse("2026-09-30T18:00")))
    }

    // -- what is missing ----------------------------------------------------------------------------------------

    @Test
    fun `a complete route step has no issues`() {
        assertEquals(emptyList<RouteIssue>(), ParcelRules.routeIssues(complete(), directionReady = true, now = now))
    }

    @Test
    fun `route issues are listed in screen order`() {
        val draft = ParcelDraft(destination = samarkand, windowStart = null, windowEnd = null, priceDigits = "")
        assertEquals(
            listOf(RouteIssue.POINTS, RouteIssue.WINDOW_START, RouteIssue.WINDOW_END, RouteIssue.PRICE),
            ParcelRules.routeIssues(draft, directionReady = false, now = now),
        )
        // Both points but the preview has not succeeded: still "points".
        assertEquals(listOf(RouteIssue.POINTS), ParcelRules.routeIssues(complete(), directionReady = false, now = now))
    }

    @Test
    fun `a window in the past or ending before it starts is refused`() {
        val past = complete().copy(windowStart = "2026-09-29T14:00", windowEnd = "2026-09-29T18:00")
        assertEquals(listOf(RouteIssue.WINDOW_PAST), ParcelRules.routeIssues(past, true, now))
        val backwards = complete().copy(windowStart = "2026-09-30T18:00", windowEnd = "2026-09-30T09:00")
        assertEquals(listOf(RouteIssue.WINDOW_ORDER), ParcelRules.routeIssues(backwards, true, now))
        val equal = complete().copy(windowEnd = "2026-09-30T09:00")
        assertEquals(listOf(RouteIssue.WINDOW_ORDER), ParcelRules.routeIssues(equal, true, now))
    }

    @Test
    fun `contacts need both names and two 9-digit phones, the parcel a type and a size`() {
        assertTrue(ParcelRules.contactsComplete(complete()))
        assertFalse(ParcelRules.contactsComplete(complete().copy(receiverDigits = "91555221")))
        assertFalse(ParcelRules.contactsComplete(complete().copy(senderName = "  ")))
        assertTrue(ParcelRules.parcelComplete(complete()))
        assertFalse(ParcelRules.parcelComplete(complete().copy(categoryId = null)))
        assertTrue(ParcelRules.readyToPublish(complete(), true, now))
        assertFalse(ParcelRules.readyToPublish(complete().copy(photoFileUrl = null), true, now))
    }

    @Test
    fun `the contact step lists its issues in the design's order, names need two letters`() {
        assertEquals(emptyList<ContactIssue>(), ParcelRules.contactIssues(complete()))
        assertEquals(ContactIssue.entries.toList(), ParcelRules.contactIssues(ParcelDraft()))
        assertEquals(listOf(ContactIssue.SENDER_NAME), ParcelRules.contactIssues(complete().copy(senderName = " A ")))
        assertEquals(listOf(ContactIssue.RECEIVER_PHONE), ParcelRules.contactIssues(complete().copy(receiverDigits = "91555")))
        assertEquals(listOf(ContactIssue.PHOTO), ParcelRules.contactIssues(complete().copy(photoFileUrl = null)))
        assertFalse(ParcelRules.contactsComplete(complete().copy(receiverName = "D")))
    }

    @Test
    fun `a phone from the contacts keeps its 9 local digits`() {
        assertEquals("901234567", ParcelRules.contactDigits("+998 90 123-45-67"))
        assertEquals("901234567", ParcelRules.contactDigits("90 123 45 67"))
        assertEquals("901234567", ParcelRules.contactDigits("8 (998) 90 123 45 67"))
        assertEquals("12345", ParcelRules.contactDigits("123-45"))
    }

    @Test
    fun `the price stepper moves by 5 000, never below nothing, at most 8 digits`() {
        assertEquals("5000", ParcelRules.stepPrice("", +1))
        assertEquals("125000", ParcelRules.stepPrice("120000", +1))
        assertEquals("115000", ParcelRules.stepPrice("120000", -1))
        assertEquals("", ParcelRules.stepPrice("5000", -1))
        assertEquals("", ParcelRules.stepPrice("3000", -1))
        assertEquals("", ParcelRules.stepPrice("", -1))
        assertEquals("99999999", ParcelRules.stepPrice("99999000", +1))
        assertEquals("12345678", ParcelRules.cleanPrice("0012 345 6789"))
        assertEquals("", ParcelRules.cleanPrice("000"))
    }

    @Test
    fun `a phone or link in the comment is warned about and masked in the preview`() {
        assertFalse(ParcelRules.noteHasContact("Ertalab 10 gacha qo'ng'iroq qilmang"))
        assertTrue(ParcelRules.noteHasContact("Tel 90 123 45 67"))
        assertTrue(ParcelRules.noteHasContact("t.me/aziza"))
        assertTrue(ParcelRules.noteHasContact("yozing @aziza"))
        assertEquals("Tel •••, yoki •••", ParcelRules.maskNote("Tel 901234567, yoki https://t.me/x"))
        assertEquals("Ertalab 10 da", ParcelRules.maskNote("Ertalab 10 da"))
    }

    @Test
    fun `the window length is known only for a valid window`() {
        assertEquals(540L, ParcelRules.windowMinutes(complete()))
        assertNull(ParcelRules.windowMinutes(complete().copy(windowEnd = "2026-09-30T09:00")))
        assertNull(ParcelRules.windowMinutes(complete().copy(windowStart = null)))
    }

    @Test
    fun `the current place is the nearest active district centre within 50 km`() {
        fun district(id: String, lat: Double?, lng: Double?, active: Boolean = true) = uz.elchi.app.api.generated.DistrictDTO(
            centerLat = lat, centerLng = lng, id = id, isActive = active, nameUz = id,
            region = uz.elchi.app.api.generated.RegionRefDTO(code = "R", id = "reg", nameUz = "Region"), stopsCount = 0,
        )
        val chilonzor = district("chilonzor", 41.2756, 69.2034)
        val yunusobod = district("yunusobod", 41.3650, 69.2850)
        val closed = district("closed", 41.2800, 69.2040, active = false)
        val noCentre = district("none", null, null)
        val list = listOf(yunusobod, closed, noCentre, chilonzor)
        assertEquals("chilonzor", ParcelRules.nearestDistrict(41.2856, 69.2044, list)?.id)
        // Abroad (Almaty): nothing within reach.
        assertNull(ParcelRules.nearestDistrict(43.2389, 76.8897, list))
        assertEquals(0.0, ParcelRules.distanceKm(41.0, 69.0, 41.0, 69.0), 1e-9)
        assertEquals(111.2, ParcelRules.distanceKm(41.0, 69.0, 42.0, 69.0), 0.2)
    }

    @Test
    fun `the place subtitle is district then region, one name when they are the same`() {
        assertEquals("Samarqand, Samarqand viloyati", samarkand.areaLine(ru = false))
        assertEquals("Toshkent shahri", tashkent.areaLine(ru = false))
    }

    // -- request body -------------------------------------------------------------------------------------------

    @Test
    fun `the listing body is a parcel request with points, Tashkent window and minor units`() {
        val body = ParcelRules.buildListingCreate(complete())
        val json = ElchiJson.encodeToJsonElement(ListingCreate.serializer(), body).jsonObject

        assertEquals("request", json.str("kind"))
        assertEquals("parcel", json.str("service_type"))
        assertEquals("total", json.str("price_basis"))
        assertEquals("12000000", json.str("unit_price_minor"))
        assertEquals("UZS", json.str("currency"))
        assertEquals("cash", json.str("payment_method"))
        assertEquals("Asia/Tashkent", json.str("timezone"))
        assertEquals("2026-09-30T09:00:00+05:00", json.str("departure_window_start"))
        assertEquals("2026-09-30T18:00:00+05:00", json.str("departure_window_end"))
        assertEquals("Ertalab 10 gacha qo'ng'iroq qilmang", json.str("comment"))

        val origin = json["origin_point"]!!.jsonObject
        assertEquals("dst_tk", origin.str("district_id"))
        assertEquals("41.2856", origin.str("lat"))
        assertEquals("Chilonzor, 9-kvartal", origin.str("address"))
        assertFalse("a point end sends no stop id", "origin_stop_id" in json)
        assertFalse("no address is omitted, not null", "address" in json["destination_point"]!!.jsonObject)

        val parcel = json["parcel"]!!.jsonObject
        assertEquals("box", parcel.str("parcel_type"))
        assertEquals("pct_small", parcel.str("category_id"))
        assertEquals("sender", parcel.str("payer"))
        assertEquals("Aziza Karimova", parcel["sender"]!!.jsonObject.str("name"))
        assertEquals("+998901234567", parcel["sender"]!!.jsonObject.str("phone"))
        assertEquals("+998915552211", parcel["receiver"]!!.jsonObject.str("phone"))
        assertEquals("/api/v1/files/cargo/abc.jpg?exp=1&sig=x", parcel.str("photo_file_id"))
        assertFalse("no typed dimensions (Q140)", "weight_g" in parcel || "length_cm" in parcel)
    }

    @Test
    fun `a verified stop replaces the point, and a blank comment is left out`() {
        val draft = complete().copy(origin = tashkent.copy(stopId = "stp_1", stopUz = "Chilonzor bekati"), comment = "   ")
        val json = ElchiJson.encodeToJsonElement(ListingCreate.serializer(), ParcelRules.buildListingCreate(draft)).jsonObject
        assertEquals("stp_1", json.str("origin_stop_id"))
        assertFalse("origin_point" in json)
        assertTrue("destination_point" in json)
        assertFalse("comment" in json)
    }

    @Test(expected = IllegalStateException::class)
    fun `an incomplete draft is never turned into a body`() {
        ParcelRules.buildListingCreate(complete().copy(priceDigits = ""))
    }

    // -- formatting helpers -------------------------------------------------------------------------------------

    @Test
    fun `phones, addresses and coordinates`() {
        assertEquals("901234567", ParcelRules.localDigits("+998901234567"))
        assertEquals("901234567", ParcelRules.localDigits("+998 90 123 45 67"))
        assertEquals("", ParcelRules.localDigits("+7 999 123 45 67"))
        assertEquals("", ParcelRules.localDigits(null))
        assertEquals("90 123 45 67", ParcelRules.groupPhone("901234567"))
        assertEquals("Samarqand, Amir Temur koʻchasi, 18А", ParcelRules.withoutCountry("Oʻzbekiston, Samarqand, Amir Temur koʻchasi, 18А"))
        assertEquals("Samarqand", ParcelRules.withoutCountry("Узбекистан, Samarqand"))
        assertEquals("Toshkent", ParcelRules.withoutCountry("Toshkent"))
        assertEquals("39.65480, 66.97560", ParcelRules.coordinates(39.6548, 66.9756))
        assertEquals("Chilonzor, 9-kvartal", tashkent.label(ru = false))
        assertEquals("39.65470, 66.97580", samarkand.label(ru = false))
        assertEquals("Toshkent shahri", tashkent.area(ru = false))
        assertEquals("Samarqand viloyati / Samarqand", samarkand.area(ru = false))
    }

    @Test
    fun `road time rounds to 5 minutes, distance to whole km`() {
        assertEquals(4 to 35, ParcelRules.durationParts(16_500))
        assertEquals(6 to 0, ParcelRules.durationParts(21_738)) // 6 h 02 min -> 6 h
        assertEquals(0 to 5, ParcelRules.durationParts(30)) // never "0 minutes"
        assertEquals("362", ParcelRules.km(362_289))
        assertEquals("5,3", ParcelRules.km(5_300))
        assertEquals("6", ParcelRules.km(6_000))
        assertEquals("0,5", ParcelRules.kg(500))
        assertEquals("5", ParcelRules.kg(5_000))
        assertEquals("30", ParcelRules.kg(30_000))
    }

    @Test
    fun `an end more than 5 km off the road is reported with its distance`() {
        fun preview(originOffset: Long?, destinationOffset: Long?) = DirectionPreviewDTO(
            corridorId = "cor", corridorName = "Toshkent – Samarqand", destination = PointEndDTO(lat = 0.0, lng = 0.0, routeOffsetM = destinationOffset),
            distanceM = 1, durationS = 1, legDistanceM = 1, legDurationS = 1, maxPointOffsetM = 250_000,
            origin = PointEndDTO(lat = 0.0, lng = 0.0, routeOffsetM = originOffset), routePolyline = "", routeVersionId = "rtv",
        )
        assertNull(ParcelRules.offRouteMeters(preview(5, 5_000)))
        assertEquals(6_000L, ParcelRules.offRouteMeters(preview(6_000, 120)))
        assertEquals(9_000L, ParcelRules.offRouteMeters(preview(6_000, 9_000)))
        assertNull(ParcelRules.offRouteMeters(preview(null, null)))
    }

    @Test
    fun `the draft survives a save and restore`() {
        val draft = complete()
        val restored = ElchiJson.decodeFromString(ParcelDraft.serializer(), ElchiJson.encodeToString(ParcelDraft.serializer(), draft))
        assertEquals(draft, restored)
    }

    private fun JsonObject.str(key: String): String? = this[key]?.jsonPrimitive?.content
}
