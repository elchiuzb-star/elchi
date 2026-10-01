package uz.elchi.app.api

import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.builtins.serializer
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import mockwebserver3.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import uz.elchi.app.api.generated.BookingPromo
import uz.elchi.app.api.generated.BookingPromoDriverDTO
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.api.generated.Role
import uz.elchi.app.session.AuthUser
import uz.elchi.app.session.Session

class HttpTransportTest {
    private lateinit var server: MockWebServer
    private lateinit var sessions: FakeSessions
    private lateinit var transport: HttpTransport

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        sessions = FakeSessions(Session("old-access", "old-refresh", AuthUser(1, "+998901112233", role = "driver")))
        transport = HttpTransport(server.url("/api/v1").toString(), sessions)
    }

    @After
    fun tearDown() = server.close()

    private fun json(code: Int, body: String) = MockResponse.Builder().code(code).body(body).build()

    @Test
    fun `unwraps the envelope, keeps warnings, maps unknown enum values`() = runTest {
        server.enqueue(json(200, """{"success":true,"data":{"id":"usr_1","phone":"+998901112233","full_name":null,
            "primary_role":"driver","roles":["driver","courier_from_the_future"],"status":"active",
            "created_at":"2026-09-28T08:00:00Z","new_field":1},
            "warnings":[{"code":"CONTACT_MASKED","message":"masked"}]}"""))

        val result = ElchiApi(transport).getMe()

        assertEquals(listOf(Role.DRIVER, Role.UNKNOWN), result.data.roles)
        assertEquals("CONTACT_MASKED", result.warnings.single().code)
        val request = server.takeRequest()
        assertEquals("/api/v2/me", request.url.encodedPath)
        assertEquals("Bearer old-access", request.headers["Authorization"])
        assertEquals("promo_cash_v1", request.headers["X-Elchi-Client-Features"])
    }

    @Test
    fun `a response declared as the whole envelope (the feed) keeps its own meta`() = runTest {
        server.enqueue(json(200, """{"success":true,"data":[],"meta":{"limit":20,"next_cursor":"c2","ranking_version":"r1",
            "match_scope":"confirmed_stops","degraded":["ROUTING_UNAVAILABLE"]}}"""))

        val page = ElchiApi(transport).getFeed(
            serviceType = uz.elchi.app.api.generated.ServiceType.PARCEL,
            side = uz.elchi.app.api.generated.FeedSide.REQUESTS,
            dateFrom = "2026-10-01T00:00:00+05:00",
            dateTo = "2026-10-15T00:00:00+05:00",
            originRegionId = "reg_tash",
            destinationDistrictId = "dst_sam",
            includeAlternatives = true,
        ).data

        assertEquals(emptyList<Any>(), page.data)
        assertEquals("c2", page.meta.nextCursor)
        assertEquals(listOf("ROUTING_UNAVAILABLE"), page.meta.degraded)
        val request = server.takeRequest()
        assertEquals("/api/v2/feed", request.url.encodedPath)
        assertEquals("true", request.url.queryParameter("include_alternatives"))
        assertEquals("reg_tash", request.url.queryParameter("origin_region_id"))
        assertNull(request.url.queryParameter("origin_district_id"))
    }

    @Test
    fun `a discriminated union picks its member by the tag`() {
        val promo = ElchiJson.decodeFromString(BookingPromo.Serializer,
            """{"view":"driver","base_commission_minor":1,"cash_to_collect_minor":2,"commission_charged_minor":3,
                "currency":"UZS","driver_credit_minor":4,"driver_keeps_minor":5,"fare_minor":6,
                "passenger_discount_covered_minor":7,"passenger_discount_minor":8}""")
        assertTrue(promo is BookingPromoDriverDTO)
    }

    @Test
    fun `an error envelope becomes an ApiException with the server code`() = runTest {
        server.enqueue(json(409, """{"success":false,"error":{"code":"DRIVER_NOT_ELIGIBLE","message":"no","details":{"reasons":["x"]}}}"""))
        try {
            ElchiApi(transport).getMe()
            fail("expected ApiException")
        } catch (e: ApiException) {
            assertEquals(409, e.status)
            assertEquals("DRIVER_NOT_ELIGIBLE", e.code)
        }
    }

    @Test
    fun `parallel 401s share one refresh and both retry with the new token`() = runTest {
        server.enqueue(json(401, """{"success":false,"error":{"code":"UNAUTHORIZED","message":"expired"}}"""))
        server.enqueue(json(401, """{"success":false,"error":{"code":"UNAUTHORIZED","message":"expired"}}"""))
        server.enqueue(json(200, """{"success":true,"data":{"access_token":"new-access","refresh_token":"new-refresh",
            "token_type":"bearer","user":{"id":1,"phone":"+998901112233","role":"driver","status":"active"}}}"""))
        repeat(2) { server.enqueue(json(200, """{"success":true,"data":"ok"}""")) }

        val calls = (1..2).map { async { transport.send("GET", "/ping", emptyList(), null, null, String.serializer()).data } }
        assertEquals(listOf("ok", "ok"), calls.awaitAll())

        val requests: List<RecordedRequest> = (1..5).map { server.takeRequest() }
        assertEquals(1, requests.count { it.url.encodedPath == "/api/v1/auth/refresh" })
        assertEquals(2, requests.count { it.headers["Authorization"] == "Bearer new-access" })
        assertEquals("new-refresh", sessions.current()?.refreshToken)
    }

    @Test
    fun `a rejected refresh signs out`() = runTest {
        server.enqueue(json(401, """{"success":false,"error":{"code":"UNAUTHORIZED","message":"expired"}}"""))
        server.enqueue(json(401, """{"success":false,"error":{"code":"INVALID_REFRESH_TOKEN","message":"revoked"}}"""))
        runCatching { transport.send("GET", "/ping", emptyList(), null, null, String.serializer()) }
        assertNull(sessions.current())
    }

    @Test
    fun `a refused refresh is reported as an expiry, not a silent sign-out`() = runTest {
        server.enqueue(json(401, """{"success":false,"error":{"code":"UNAUTHORIZED","message":"expired"}}"""))
        server.enqueue(json(401, """{"success":false,"error":{"code":"REFRESH_TOKEN_REVOKED","message":"revoked"}}"""))
        runCatching { transport.send("GET", "/ping", emptyList(), null, null, String.serializer()) }
        assertTrue(sessions.expired)
        assertNull(sessions.current())
    }

    @Test
    fun `a server fault during refresh keeps the session`() = runTest {
        server.enqueue(json(401, """{"success":false,"error":{"code":"UNAUTHORIZED","message":"expired"}}"""))
        server.enqueue(json(503, """{"success":false,"error":{"code":"SERVICE_UNAVAILABLE","message":"down"}}"""))
        runCatching { transport.send("GET", "/ping", emptyList(), null, null, String.serializer()) }
        assertEquals("old-refresh", sessions.current()?.refreshToken)
        assertTrue(!sessions.expired)
    }

    @Test
    fun `unblock sends DELETE with an idempotency key`() = runTest {
        server.enqueue(json(200, """{"success":true,"data":{}}"""))
        AccountApi(transport).unblock("usr_7", "key-1")
        val request = server.takeRequest()
        assertEquals("DELETE", request.method)
        assertEquals("/api/v2/blocks/usr_7", request.url.encodedPath)
        assertEquals("key-1", request.headers["Idempotency-Key"])
    }

    @Test
    fun `the client name goes to the v1 profile`() = runTest {
        server.enqueue(json(200, """{"success":true,"data":{"id":3,"user_id":1,"phone":"+998901112233","full_name":"Ali Valiyev"},"message":"ok"}"""))
        assertEquals("Ali Valiyev", AccountApi(transport).updateClientName("Ali Valiyev").fullName)
        val request = server.takeRequest()
        assertEquals("PATCH", request.method)
        assertEquals("/api/v1/client/profile", request.url.encodedPath)
        assertEquals("""{"full_name":"Ali Valiyev"}""", request.body?.utf8())
    }

    @Test
    fun `no connection is a NETWORK error and keeps the session`() = runTest {
        server.close()
        try {
            transport.send("GET", "/ping", emptyList(), null, null, String.serializer())
            fail("expected ApiException")
        } catch (e: ApiException) {
            assertEquals(ApiException.NETWORK, e.code)
        }
        assertEquals("old-access", sessions.current()?.accessToken)
    }

    @Test
    fun `query values use the wire form of enums and skip nulls`() = runTest {
        server.enqueue(json(200, """{"success":true,"data":"ok"}"""))
        transport.send("GET", "/feed", listOf("side" to Role.DRIVER, "cursor" to null, "limit" to 20L), null, null, String.serializer())
        assertEquals("side=driver&limit=20", server.takeRequest().url.encodedQuery)
    }
}

private class FakeSessions(initial: Session?) : uz.elchi.app.session.SessionStorage {
    private var session = initial
    override fun current() = session
    override fun save(session: Session) {
        this.session = session
    }
    override fun clear() {
        session = null
    }
    var expired = false
    override fun expire() {
        clear()
        expired = true
    }
}
