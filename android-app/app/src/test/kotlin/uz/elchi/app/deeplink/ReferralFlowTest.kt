package uz.elchi.app.deeplink

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
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
import uz.elchi.app.api.DriverApi
import uz.elchi.app.api.HttpTransport
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.feature.client.BonusViewModel
import uz.elchi.app.feature.client.Load
import uz.elchi.app.feature.driver.DriverViewModel
import uz.elchi.app.session.AuthUser
import uz.elchi.app.session.Session
import uz.elchi.app.session.SessionStorage
import uz.elchi.app.ui.components.BannerCenter
import uz.elchi.app.ui.components.BannerText
import uz.elchi.app.ui.components.BannerTone
import java.util.concurrent.CopyOnWriteArrayList

/** The kept referral code against a fake backend: the driver home row's confirmation and the client's prefill. */
@OptIn(ExperimentalCoroutinesApi::class)
class ReferralFlowTest {
    private lateinit var server: MockWebServer
    private lateinit var transport: HttpTransport
    private val calls = CopyOnWriteArrayList<RecordedRequest>()
    @Volatile private var attribution: MockResponse = ok("{}")

    private class FakeReferral(code: String?) : PendingReferral {
        private val flow = MutableStateFlow(code)
        override val pending: StateFlow<String?> = flow
        override fun forget() {
            flow.value = null
        }
    }

    private fun ok(data: String) = MockResponse.Builder().code(200).body("""{"success":true,"data":$data}""").build()
    private fun refused(status: Int, code: String, details: String = "{}") =
        MockResponse.Builder().code(status).body("""{"success":false,"error":{"code":"$code","message":"server says $code","details":$details}}""").build()

    @Before
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                calls += request
                return when (request.url.encodedPath) {
                    "/api/v2/referrals/attribution" -> attribution
                    "/api/v2/me/referrals" -> ok("""{"attributions":[],"enrollments":[],"invited":{}}""")
                    "/api/v2/me/promo-balance" -> ok("""{"buckets":[]}""")
                    else -> refused(403, "FEATURE_DISABLED", """{"flag":"promotions_enabled"}""")
                }
            }
        }
        server.start()
        val sessions = object : SessionStorage {
            private var session: Session? = Session("access", "refresh", AuthUser(20, "+998900001010", role = "driver"))
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

    private fun confirm(response: MockResponse, code: String = "AB2CD3EF"): Pair<FakeReferral, BannerCenter> {
        attribution = response
        val referral = FakeReferral(code)
        val banners = BannerCenter()
        val vm = DriverViewModel(ElchiApi(transport), DriverApi(transport), banners, referral)
        vm.confirmReferral()
        runBlocking { withTimeout(10_000) { vm.state.first { !it.referralBusy && !it.refreshing && banners.banner.value != null } } }
        return referral to banners
    }

    @Test
    fun `driver confirmation sends the code for the driver audience with a key, then forgets it`() {
        val (referral, banners) = confirm(MockResponse.Builder().code(201).body(
            """{"success":true,"data":{"id":"att_1","audience":"driver","status":"attributed","attributed_at":"2026-09-30T10:00:00Z","window_ends_at":"2026-10-03T10:00:00Z"}}""",
        ).build())
        val sent = calls.single { it.url.encodedPath == "/api/v2/referrals/attribution" }
        val body = sent.body!!.utf8()
        assertTrue(body, body.contains(""""code":"AB2CD3EF"""") && body.contains(""""audience":"driver""""))
        assertNotNull(sent.headers["Idempotency-Key"])
        assertNull(referral.pending.value)
        assertEquals(BannerTone.OK, banners.banner.value!!.tone)
        assertEquals(BannerText.Key("link.referralApplied"), banners.banner.value!!.text)
    }

    @Test
    fun `programme off keeps the code and says so`() {
        val (referral, banners) = confirm(refused(403, "FEATURE_DISABLED", """{"flag":"promotions_enabled"}"""))
        assertEquals("AB2CD3EF", referral.pending.value)
        assertEquals(BannerText.Key("promoScreen.programOff"), banners.banner.value!!.text)
    }

    @Test
    fun `an invalid code shows the server's refusal and is forgotten`() {
        val (referral, banners) = confirm(refused(404, "REFERRAL_CODE_INVALID"))
        assertNull(referral.pending.value)
        assertEquals(BannerTone.ERR, banners.banner.value!!.tone)
    }

    @Test
    fun `rate limited keeps the code for another try`() {
        val (referral, _) = confirm(refused(429, "RATE_LIMITED"))
        assertEquals("AB2CD3EF", referral.pending.value)
    }

    @Test
    fun `the client bonus screen starts with the kept code in the entry field`() {
        val vm = BonusViewModel(ElchiApi(transport), FakeReferral("AB2CD3EF"))
        assertEquals("AB2CD3EF", vm.state.value.entered)
        assertEquals("AB2CD3EF", vm.state.value.normalized)
        val empty = BonusViewModel(ElchiApi(transport), FakeReferral(null))
        assertEquals("", empty.state.value.entered)
        // Let both screens finish reading (the programme is off here: the code stays kept, the field stays filled).
        for (model in listOf(vm, empty)) {
            runBlocking { withTimeout(10_000) { model.state.first { !it.codeLoading && it.referrals !is Load.Loading && it.balance !is Load.Loading } } }
        }
        assertEquals("AB2CD3EF", vm.state.value.entered)
    }
}
