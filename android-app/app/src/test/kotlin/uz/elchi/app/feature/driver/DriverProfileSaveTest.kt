package uz.elchi.app.feature.driver

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
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
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.DriverApi
import uz.elchi.app.api.ElchiJson
import uz.elchi.app.api.HttpTransport
import uz.elchi.app.api.generated.ElchiApi
import uz.elchi.app.session.AuthUser
import uz.elchi.app.session.Session
import uz.elchi.app.session.SessionStorage
import uz.elchi.app.ui.components.BannerCenter
import java.util.concurrent.CopyOnWriteArrayList

/**
 * The profile form's save sequence against a fake backend: v1 PATCH first, then the v2 vehicle, both read back; a
 * v2 failure after the v1 save leaves the form locked, and the retry sends only the vehicle, with the same key.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class DriverProfileSaveTest {
    private lateinit var server: MockWebServer
    private lateinit var vm: DriverProfileFormViewModel
    private val calls = CopyOnWriteArrayList<RecordedRequest>()
    private var changed = 0

    // The fake backend's state.
    @Volatile private var plate: String? = null
    @Volatile private var vehicleFailures = 0
    @Volatile private var vehicles = "[]"

    private fun ok(data: String) = MockResponse.Builder().code(200).body("""{"success":true,"data":$data}""").build()

    private fun profileJson() = """{"id":6,"user":{"id":20,"phone":"+998900001012","full_name":${if (plate != null) "\"Jasur\"" else "null"}},
        "full_name":${if (plate != null) "\"Jasur\"" else "null"},"car_model":${if (plate != null) "\"Cobalt\"" else "null"},
        "car_color":${if (plate != null) "\"Oq\"" else "null"},"plate_number":${plate?.let { "\"$it\"" } ?: "null"},
        "verification_status":"new","is_available":false}"""

    @Before
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                calls += request
                val path = request.url.encodedPath
                return when {
                    request.method == "GET" && path == "/api/v1/driver/profile" -> ok(profileJson())
                    request.method == "PATCH" && path == "/api/v1/driver/profile" -> {
                        plate = ElchiJson.parseToJsonElement(request.body!!.utf8()).jsonObject["plate_number"]?.jsonPrimitive?.content ?: plate
                        ok("""{"id":6}""")
                    }
                    request.method == "GET" && path == "/api/v2/me/vehicles" -> ok(vehicles)
                    request.method == "POST" && path == "/api/v2/vehicles" -> if (vehicleFailures > 0) {
                        vehicleFailures--
                        MockResponse.Builder().code(503).body("""{"success":false,"error":{"code":"SERVICE_UNAVAILABLE","message":"down"}}""").build()
                    } else {
                        val v = """{"id":"veh_1","plate_number":"01A123AA","plate_masked":"01 A ••• AA","make_model":"Cobalt","color":"Oq",
                            "seat_capacity":4,"cargo_max_weight_g":20000,"cargo_max_volume_ml":100000,"document_file_ids":[],
                            "verification_status":"pending","version":1,"created_at":"2026-09-30T10:00:00Z"}"""
                        vehicles = "[$v]"
                        ok(v)
                    }
                    else -> MockResponse.Builder().code(404).body("""{"success":false,"error":{"code":"NOT_FOUND","message":"$path"}}""").build()
                }
            }
        }
        server.start()
        val sessions = object : SessionStorage {
            private var session: Session? = Session("access", "refresh", AuthUser(20, "+998900001012", role = "driver"))
            override fun current() = session
            override fun save(session: Session) {
                this.session = session
            }
            override fun clear() {
                session = null
            }
        }
        val transport = HttpTransport(server.url("/api/v1").toString(), sessions)
        vm = DriverProfileFormViewModel(ElchiApi(transport), DriverApi(transport), BannerCenter()) { changed++ }
        await { it.profile != null }
    }

    @After
    fun tearDown() {
        server.close()
        Dispatchers.resetMain()
    }

    private fun await(condition: (DriverProfileFormViewModel.State) -> Boolean) = runBlocking {
        withTimeout(10_000) { vm.state.first(condition) }
    }

    private fun fill() = vm.edit { DriverForm("Jasur", "Cobalt", "Oq", "01 a 123 aa", "4", "20", "100") }

    private fun saveAndWait() {
        val before = calls.size
        vm.save()
        await { !it.saving && calls.size > before }
    }

    private fun writes() = calls.filter { it.method != "GET" }.map { "${it.method} ${it.url.encodedPath}" }

    @Test
    fun `the first save patches v1, then registers the vehicle on v2, then reads both back and locks`() {
        fill()
        saveAndWait()

        assertEquals(listOf("PATCH /api/v1/driver/profile", "POST /api/v2/vehicles"), writes())
        val patch = ElchiJson.parseToJsonElement(calls.first { it.method == "PATCH" }.body!!.utf8()).jsonObject
        assertEquals(setOf("full_name", "car_model", "car_color", "plate_number"), patch.keys)
        val post = calls.first { it.method == "POST" }
        assertNotNull(post.headers["Idempotency-Key"])
        val body = ElchiJson.parseToJsonElement(post.body!!.utf8()).jsonObject
        assertEquals("01A123AA", body["plate_number"]!!.jsonPrimitive.content)
        assertEquals("20000", body["cargo_max_weight_g"]!!.jsonPrimitive.content)
        assertEquals("100000", body["cargo_max_volume_ml"]!!.jsonPrimitive.content)
        // Read back after the writes.
        assertTrue(calls.last().method == "GET")
        val s = vm.state.value
        assertNull(s.error)
        assertTrue(s.locked && s.capacityLocked)
        assertEquals("4", s.form.seats)
        assertEquals(1, changed)
    }

    @Test
    fun `a v2 failure after the v1 save locks the form, and the retry sends only the vehicle with the same key`() {
        vehicleFailures = 1
        fill()
        saveAndWait()

        val first = vm.state.value
        assertEquals("SERVICE_UNAVAILABLE", (first.error as ApiException).code)
        assertTrue(first.locked)
        assertTrue(!first.capacityLocked)
        assertEquals("20", first.form.cargoKg) // what was typed and not yet stored stays
        assertTrue(first.canSave)

        saveAndWait()

        assertEquals(listOf("PATCH /api/v1/driver/profile", "POST /api/v2/vehicles", "POST /api/v2/vehicles"), writes())
        val keys = calls.filter { it.method == "POST" }.map { it.headers["Idempotency-Key"] }
        assertEquals(keys[0], keys[1])
        val s = vm.state.value
        assertNull(s.error)
        assertTrue(s.capacityLocked)
        assertTrue(!s.canSave)
    }

    @Test
    fun `nothing is sent while the form is incomplete`() {
        vm.edit { DriverForm(fullName = "Jasur", seats = "4") }
        vm.save()

        assertTrue(writes().isEmpty())
        assertTrue(vm.state.value.showIssues)
        assertEquals(setOf(FormIssue.MODEL, FormIssue.COLOR, FormIssue.PLATE), vm.state.value.issues)
    }
}
