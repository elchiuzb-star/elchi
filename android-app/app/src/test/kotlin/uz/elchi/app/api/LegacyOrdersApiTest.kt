package uz.elchi.app.api

import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okio.Buffer
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import uz.elchi.app.feature.client.LegacyRules
import uz.elchi.app.feature.client.OrderRules
import uz.elchi.app.session.AuthUser
import uz.elchi.app.session.Session
import uz.elchi.app.session.SessionStorage

class LegacyOrdersApiTest {
    private lateinit var server: MockWebServer
    private lateinit var transport: HttpTransport
    private var session: Session? = Session("access", "refresh", AuthUser(7, "+998900001001", role = "client"))

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        val sessions = object : SessionStorage {
            override fun current() = session
            override fun save(session: Session) {
                this@LegacyOrdersApiTest.session = session
            }
            override fun clear() {
                session = null
            }
        }
        transport = HttpTransport(server.url("/api/v1").toString(), sessions)
    }

    @After
    fun tearDown() = server.close()

    @Test
    fun `v1 client orders are paged with the token and read with decimal so'm prices`() = runTest {
        server.enqueue(
            MockResponse.Builder().code(200).body(
                """{"success":true,"data":{"items":[{"id":41,"order_number":"EL-0041","status":"confirmed","from_city":"Toshkent",
                "to_city":"Namangan","from_district":{"id":1,"name_uz":"Chilonzor"},"to_district":null,"cargo_type":"box",
                "suggested_price":"65000.00","client_price":null,"final_price":"70000.00","payment_method":"cash",
                "payment_status":"paid","bids_count":3,"created_at":"2026-08-04T09:00:00"}],
                "pagination":{"page":2,"limit":20,"total":21,"total_pages":2}},"message":"OK"}""",
            ).build(),
        )

        val page = LegacyOrdersApi(transport).clientOrders(page = 2)

        val request = server.takeRequest()
        assertEquals("/api/v1/client/orders", request.url.encodedPath)
        assertEquals("2", request.url.queryParameter("page"))
        assertEquals("20", request.url.queryParameter("limit"))
        assertEquals("Bearer access", request.headers["Authorization"])
        val order = page.items.single()
        assertEquals("Toshkent", order.fromCity)
        assertEquals("Chilonzor", order.fromDistrict?.nameUz)
        assertEquals(7_000_000L, OrderRules.legacyPriceMinor(order.finalPrice, order.suggestedPrice))
        assertEquals(2, page.pagination.totalPages)
    }

    @Test
    fun `the v1 detail reads regions, coordinates, the driver and decimal prices`() = runTest {
        server.enqueue(
            MockResponse.Builder().code(200).body(
                """{"success":true,"data":{"id":4,"order_number":"ORD-4277DD60D9","status":"in_transit",
                "from_city":{"id":1,"name_uz":"Toshkent shahri"},"to_city":{"id":3,"name_uz":"Samarqand viloyati"},
                "from_district":{"id":4,"city_id":1,"name_uz":"Mirobod","name_ru":"Mirobod","center_lat":41.2311,"center_lng":69.3597},
                "pickup_address":"Toshkent, Amir Temur ko'chasi, 1","dropoff_address":"Samarqand, Registon ko'chasi, 5",
                "pickup_lat":41.2995,"pickup_lng":69.2401,"dropoff_lat":39.6542,"dropoff_lng":66.9597,
                "sender_phone":"+998900001001","receiver_phone":"+998901112233","cargo_type":null,"cargo_photo_url":null,
                "comment":"Stage 06","suggested_price":60000.0,"client_price":67000.0,"final_price":72000.0,
                "assigned_driver":{"id":4,"full_name":"Demo Haydovchi","phone":"+998900001010","car_model":"Chevrolet Cobalt",
                "plate_number":"90 D 001 AA","rating":0.0,"completed_orders":0},"accepted_bid_id":4,"bids_count":1,
                "published_at":"2026-09-30T10:28:41.297437","created_at":"2026-09-30T15:28:41.270557+05:00"},"message":"OK"}""",
            ).build(),
        )

        val order = LegacyOrdersApi(transport).order(4)

        assertEquals("/api/v1/client/orders/4", server.takeRequest().url.encodedPath)
        assertEquals("Samarqand viloyati", order.toCity?.nameUz)
        assertEquals(69.2401, order.pickupLng!!, 0.0)
        assertEquals("+998900001010", order.assignedDriver?.phone)
        assertEquals(0.0, order.assignedDriver?.rating!!, 0.0)
        assertEquals(7_200_000L, LegacyRules.priceMinor(order))
    }

    @Test
    fun `bids are a list, cheapest first as sent`() = runTest {
        server.enqueue(
            MockResponse.Builder().code(200).body(
                """{"success":true,"data":[{"id":2,"order_id":2,"price":68000.0,"status":"active","created_at":"2026-09-30T15:28:40+05:00",
                "driver":{"id":4,"full_name":"Demo Haydovchi","car_model":"Chevrolet Cobalt","plate_number":"90 D 001 AA","rating":4.6,"completed_orders":3}},
                {"id":3,"order_id":2,"price":"70000.00","status":"active","driver":null}],"message":"OK"}""",
            ).build(),
        )

        val bids = LegacyOrdersApi(transport).bids(2)

        assertEquals("/api/v1/client/orders/2/bids", server.takeRequest().url.encodedPath)
        assertEquals(listOf(2L, 3L), bids.map { it.id })
        assertEquals(listOf(6_800_000L, 7_000_000L), bids.map { LegacyRules.bidPriceMinor(it.price) })
        assertNull(bids[1].driver)
    }

    @Test
    fun `the commands post their bodies to the v1 paths`() = runTest {
        repeat(5) { server.enqueue(MockResponse.Builder().code(200).body("""{"success":true,"data":{},"message":"OK"}""").build()) }
        val api = LegacyOrdersApi(transport)

        api.selectDriver(2, bidId = 3)
        api.confirm(1)
        api.rate(1, 5, null)
        api.cancel(3, "Mijoz bekor qildi")
        api.openDispute(4, "lost", "Qutisi ezilgan")

        val sent = List(5) { server.takeRequest() }
        assertEquals(listOf("/api/v1/client/orders/2/select-driver", "/api/v1/client/orders/1/confirm", "/api/v1/client/orders/1/rating", "/api/v1/client/orders/3/cancel", "/api/v1/orders/4/disputes"), sent.map { it.url.encodedPath })
        assertEquals(List(5) { "POST" }, sent.map { it.method })
        assertEquals("""{"bid_id":3}""", sent[0].body?.utf8())
        assertEquals("{}", sent[1].body?.utf8())
        assertEquals("""{"rating":5}""", sent[2].body?.utf8())
        assertEquals("""{"reason":"Mijoz bekor qildi"}""", sent[3].body?.utf8())
        assertEquals("""{"reason":"lost","comment":"Qutisi ezilgan"}""", sent[4].body?.utf8())
    }

    @Test
    fun `a repeated rating comes back as ALREADY_EXISTS`() = runTest {
        server.enqueue(MockResponse.Builder().code(409).body("""{"success":false,"error":{"code":"ALREADY_EXISTS","message":"Rating already exists","details":{}}}""").build())

        val error = runCatching { LegacyOrdersApi(transport).rate(1, 4, "ok") }.exceptionOrNull()

        assertTrue(error is ApiException && LegacyRules.ratingAlreadyDone(error))
    }

    @Test
    fun `a signed file link relative to the API host is downloaded with the token`() = runTest {
        val bytes = byteArrayOf(1, 2, 3, 4)
        server.enqueue(MockResponse.Builder().code(200).body(Buffer().write(bytes)).build())

        val result = FilesApi(transport).download("/api/v1/files/cargo_photo/2026/09/a.jpg?exp=1&sig=x")

        assertArrayEquals(bytes, result)
        val request = server.takeRequest()
        assertEquals("/api/v1/files/cargo_photo/2026/09/a.jpg", request.url.encodedPath)
        assertEquals("x", request.url.queryParameter("sig"))
        assertEquals("Bearer access", request.headers["Authorization"])
    }

    @Test
    fun `a file on another host gets no token`() = runTest {
        val other = MockWebServer().apply { start() }
        try {
            other.enqueue(MockResponse.Builder().code(200).body(Buffer().write(byteArrayOf(9))).build())
            FilesApi(transport).download(other.url("/bucket/a.jpg?sig=x").toString())
            assertNull(other.takeRequest().headers["Authorization"])
        } finally {
            other.close()
        }
    }
}
