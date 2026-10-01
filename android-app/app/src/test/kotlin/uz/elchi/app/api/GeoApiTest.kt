package uz.elchi.app.api

import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import uz.elchi.app.session.AuthUser
import uz.elchi.app.session.Session
import uz.elchi.app.session.SessionStorage

class GeoApiTest {
    private lateinit var server: MockWebServer
    private lateinit var transport: HttpTransport
    private var session: Session? = Session("access", "refresh", AuthUser(7, "+998900001001", role = "client"))

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        val sessions = object : SessionStorage {
            override fun current() = session
            override fun save(session: Session) {
                this@GeoApiTest.session = session
            }
            override fun clear() {
                session = null
            }
        }
        transport = HttpTransport(server.url("/api/v1").toString(), sessions)
    }

    @After
    fun tearDown() = server.close()

    private fun ok(body: String) = MockResponse.Builder().code(200).body(body).build()

    @Test
    fun `reverse geocode goes to the v1 proxy without a token and reads a local fallback`() = runTest {
        server.enqueue(ok("""{"success":true,"data":{"formatted_address":"Samarqand","lat":39.65,"lng":66.96,
            "region":null,"district":"Samarqand","place_id":null,"provider":"local","detected_region_id":3,"detected_district_id":122},"message":"OK"}"""))

        val result = GeoApi(transport).reverseGeocode(39.65, 66.96, "ru")

        assertFalse("provider=local is not a real address", result.hasRealAddress)
        val request = server.takeRequest()
        assertEquals("/api/v1/geo/reverse-geocode", request.url.encodedPath)
        assertNull(request.headers["Authorization"])
        val body = ElchiJson.parseToJsonElement(request.body!!.utf8()).jsonObject
        assertEquals("ru", body["language"]!!.jsonPrimitive.content)
    }

    @Test
    fun `suggest sends the district centre and name, and reads suggestions without coordinates`() = runTest {
        server.enqueue(ok("""{"success":true,"data":{"results":[{"title":"Registon","subtitle":"Mehmonxona","formatted_address":"Mirzo Ulugʻbek koʻchasi, 16А",
            "region":null,"district":null,"locality":"Samarqand","distance_m":410,"uri":"ymapsbm1://org?oid=1"}]},"message":"OK"}"""))

        val results = GeoApi(transport).suggest("Registon", "uz", 39.65, 66.96, "Samarqand")

        assertEquals("ymapsbm1://org?oid=1", results.single().uri)
        assertEquals(410.0, results.single().distanceM!!, 0.0)
        val body = ElchiJson.parseToJsonElement(server.takeRequest().body!!.utf8()).jsonObject
        assertEquals("39.65", body["near_lat"]!!.jsonPrimitive.content)
        assertEquals("0.35", body["span_deg"]!!.jsonPrimitive.content)
        assertEquals("Samarqand", body["district"]!!.jsonPrimitive.content)
    }

    @Test
    fun `a cargo photo is uploaded as multipart with the type field and the bearer token`() = runTest {
        server.enqueue(ok("""{"success":true,"data":{"file_url":"/api/v1/files/u/7/cargo.jpg?exp=1&sig=s","type":"cargo_photo",
            "mime_type":"image/jpeg","size_bytes":3,"original_filename":"parcel.jpg"},"message":"File uploaded successfully"}"""))

        val uploaded = FilesApi(transport).uploadCargoPhoto(byteArrayOf(1, 2, 3), "parcel.jpg")

        assertEquals("/api/v1/files/u/7/cargo.jpg?exp=1&sig=s", uploaded.fileUrl)
        val request = server.takeRequest()
        assertEquals("/api/v1/files/upload", request.url.encodedPath)
        assertEquals("Bearer access", request.headers["Authorization"])
        assertTrue(request.headers["Content-Type"]!!.startsWith("multipart/form-data"))
        val text = request.body!!.utf8()
        assertTrue(text.contains("name=\"type\"") && text.contains("cargo_photo"))
        assertTrue(text.contains("name=\"file\"; filename=\"parcel.jpg\""))
    }

    @Test
    fun `an upload is sent again after a refreshed token`() = runTest {
        server.enqueue(MockResponse.Builder().code(401).body("""{"success":false,"error":{"code":"UNAUTHORIZED","message":"expired"}}""").build())
        server.enqueue(ok("""{"success":true,"data":{"access_token":"new","refresh_token":"r2","user":{"id":7,"phone":"+998900001001","role":"client"}}}"""))
        server.enqueue(ok("""{"success":true,"data":{"file_url":"/f.jpg"}}"""))

        assertEquals("/f.jpg", FilesApi(transport).uploadCargoPhoto(byteArrayOf(9), "p.jpg").fileUrl)

        server.takeRequest()
        assertEquals("/api/v1/auth/refresh", server.takeRequest().url.encodedPath)
        val retried = server.takeRequest()
        assertEquals("Bearer new", retried.headers["Authorization"])
        assertTrue(retried.body!!.utf8().contains("cargo_photo"))
    }
}
