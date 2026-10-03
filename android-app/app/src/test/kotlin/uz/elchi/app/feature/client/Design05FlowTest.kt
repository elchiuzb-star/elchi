package uz.elchi.app.feature.client

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.withTimeout
import mockwebserver3.Dispatcher
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import mockwebserver3.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import uz.elchi.app.api.HttpTransport
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.session.AuthUser
import uz.elchi.app.session.Session
import uz.elchi.app.session.SessionStorage
import uz.elchi.app.ui.components.BannerCenter
import uz.elchi.app.ui.components.BannerText
import uz.elchi.app.ui.components.BannerTone
import java.util.concurrent.CopyOnWriteArrayList

/** Design 05 (profile, help, safety, bonus) against a fake backend: unblock toast, own code, threads on help. */
@OptIn(ExperimentalCoroutinesApi::class)
class Design05FlowTest {
    private lateinit var server: MockWebServer
    private lateinit var transport: HttpTransport
    private val calls = CopyOnWriteArrayList<RecordedRequest>()
    @Volatile private var unblock: MockResponse = ok("{}")

    private fun ok(data: String) = MockResponse.Builder().code(200).body("""{"success":true,"data":$data}""").build()
    private fun refused(status: Int, code: String) =
        MockResponse.Builder().code(status).body("""{"success":false,"error":{"code":"$code","message":"server says $code","details":{}}}""").build()

    private fun thread(id: String, created: String) =
        """{"id":"$id","booking_id":"bkg_1","created_at":"$created","message_count":2,"requester_side":"client","staff_status":"answered","status":"open","version":1}"""

    @Before
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                calls += request
                val path = request.url.encodedPath
                return when {
                    request.method == "DELETE" && path.startsWith("/api/v2/blocks/") -> unblock
                    path == "/api/v2/blocks" -> ok("""[{"id":"blk_1","user_id":"usr_7","created_at":"2026-10-01T10:00:00Z"},{"id":"blk_2","user_id":"usr_8","created_at":"2026-10-01T11:00:00Z"}]""")
                    path == "/api/v2/me/reports" -> ok("[]")
                    path == "/api/v2/me/referral-code" -> ok("""{"code":"AB2CD3EF","link_status":"not_configured"}""")
                    path == "/api/v2/me/referrals" -> ok("""{"attributions":[],"enrollments":[],"invited":{}}""")
                    path == "/api/v2/me/promo-balance" -> ok("""{"buckets":[]}""")
                    path == "/api/v2/referrals/attribution" ->
                        ok("""{"id":"att_1","audience":"client","status":"attributed","attributed_at":"2026-10-01T10:00:00Z","window_ends_at":"2026-10-04T10:00:00Z"}""")
                    path == "/api/v2/me/support-threads" -> ok("[${thread("sth_old", "2026-09-01T10:00:00Z")},${thread("sth_new", "2026-10-01T10:00:00Z")}]")
                    path == "/api/v2/me/support/tickets" -> ok("[]")
                    path == "/api/v2/support/contacts" -> ok("""{"available":false}""")
                    else -> refused(404, "NOT_FOUND")
                }
            }
        }
        server.start()
        val sessions = object : SessionStorage {
            private var session: Session? = Session("access", "refresh", AuthUser(10, "+998900001001", role = "client"))
            override fun current() = session
            override fun save(session: Session) {
                this.session = session
            }
            override fun clear() {
                session = null
            }
        }
        transport = HttpTransport(server.url("/api/v1").toString(), sessions)
    }

    @After
    fun tearDown() {
        server.close()
        Dispatchers.resetMain()
    }

    private fun safety(banners: BannerCenter): SafetyCenterViewModel {
        val vm = SafetyCenterViewModel(ElchiApi(transport), banners)
        runBlocking { withTimeout(10_000) { vm.state.first { it.blocks is Load.Ready && !it.refreshing } } }
        return vm
    }

    @Test
    fun `unblocking removes the row with a key and says so`() {
        val banners = BannerCenter()
        val vm = safety(banners)
        vm.unblock("usr_7")
        runBlocking { withTimeout(10_000) { vm.state.first { it.unblocking == null && (it.blocks as Load.Ready).value.size == 1 } } }
        assertEquals(listOf("usr_8"), (vm.state.value.blocks as Load.Ready).value.map { it.userId })
        assertNotNull(calls.single { it.method == "DELETE" }.headers["Idempotency-Key"])
        assertEquals(BannerTone.OK, banners.banner.value!!.tone)
        assertEquals(BannerText.Key("client.profile.unblocked"), banners.banner.value!!.text)
    }

    @Test
    fun `a refused unblock keeps the row and shows no success`() {
        unblock = refused(409, "CONFLICT")
        val banners = BannerCenter()
        val vm = safety(banners)
        vm.unblock("usr_7")
        runBlocking { withTimeout(10_000) { vm.state.first { it.unblockError != null } } }
        assertEquals(2, (vm.state.value.blocks as Load.Ready).value.size)
        assertNull(banners.banner.value)
    }

    @Test
    fun `the own code is refused before the server, another code is accepted and named`() {
        val banners = BannerCenter()
        val vm = BonusViewModel(ElchiApi(transport), banners = banners)
        runBlocking { withTimeout(10_000) { vm.state.first { it.code != null && it.referrals is Load.Ready } } }
        vm.setEntered("ab2cd3ef")
        assertEquals("client.bonus.ownCode", vm.state.value.entryErrorKey)
        assertNull(vm.state.value.normalized)
        vm.submitCode()
        assertTrue(calls.none { it.url.encodedPath == "/api/v2/referrals/attribution" })

        vm.setEntered("ZX2CD3EF")
        assertNull(vm.state.value.entryErrorKey)
        vm.submitCode()
        runBlocking { withTimeout(10_000) { vm.state.first { it.accepted } } }
        assertEquals("ZX2CD3EF", vm.state.value.acceptedCode)

        vm.markCopied("AB2CD3EF")
        assertEquals(BannerText.Key("client.bonus.codeCopied", params = mapOf("code" to "AB2CD3EF")), banners.banner.value!!.text)
    }

    @Test
    fun `help reads the operator conversations newest first`() {
        val vm = HelpViewModel(ElchiApi(transport))
        runBlocking { withTimeout(10_000) { vm.state.first { it.threads is Load.Ready && !it.refreshing } } }
        assertEquals(listOf("sth_new", "sth_old"), (vm.state.value.threads as Load.Ready).value.map { it.id })
    }

    @Test
    fun `the threads bar refresh says Yangilandi, a pull does not`() {
        val banners = BannerCenter()
        val vm = SupportThreadsViewModel(ElchiApi(transport), banners)
        vm.refresh()
        runBlocking { withTimeout(10_000) { vm.state.first { it.threads is Load.Ready && !it.refreshing } } }
        assertNull(banners.banner.value)
        vm.refresh(announce = true)
        runBlocking { withTimeout(10_000) { vm.state.first { !it.refreshing && banners.banner.value != null } } }
        assertEquals(BannerText.Key("client.booking.refreshed"), banners.banner.value!!.text)
    }
}
