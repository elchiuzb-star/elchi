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

class DriverApiTest {
    private lateinit var server: MockWebServer
    private lateinit var transport: HttpTransport
    private var session: Session? = Session("access", "refresh", AuthUser(20, "+998900001012", role = "driver"))

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        val sessions = object : SessionStorage {
            override fun current() = session
            override fun save(session: Session) {
                this@DriverApiTest.session = session
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
    fun `the profile is read from v1 with the token, rating left out`() = runTest {
        server.enqueue(ok("""{"success":true,"data":{"id":6,"user":{"id":20,"phone":"+998900001012","full_name":null,"status":"active"},
            "full_name":null,"car_model":null,"plate_number":null,"plate_number_normalized":null,"car_color":null,
            "verification_status":"new","rating":0.0,"total_orders":0,"completed_orders":0,"is_available":false,
            "created_at":"2026-09-30T10:00:00"},"message":"OK"}"""))

        val profile = DriverApi(transport).profile()

        assertEquals("new", profile.verificationStatus)
        assertNull(profile.plateNumber)
        assertFalse(profile.isAvailable)
        val request = server.takeRequest()
        assertEquals("/api/v1/driver/profile", request.url.encodedPath)
        assertEquals("Bearer access", request.headers["Authorization"])
    }

    @Test
    fun `a locked save sends only the name - no vehicle keys at all`() = runTest {
        server.enqueue(ok("""{"success":true,"data":{"id":6,"full_name":"Jasur"},"message":"Driver profile updated"}"""))

        DriverApi(transport).updateProfile(DriverProfileUpdate(fullName = "Jasur"))

        val request = server.takeRequest()
        assertEquals("PATCH", request.method)
        assertEquals("""{"full_name":"Jasur"}""", request.body?.utf8())
    }

    @Test
    fun `a locked vehicle field is refused with its code and details`() = runTest {
        server.enqueue(
            MockResponse.Builder().code(403).body(
                """{"success":false,"error":{"code":"DRIVER_VEHICLE_LOCKED","message":"locked","details":{"locked_fields":["plate_number"]}}}""",
            ).build(),
        )

        val error = runCatching { DriverApi(transport).updateProfile(DriverProfileUpdate(plateNumber = "01A")) }.exceptionOrNull() as ApiException

        assertEquals(403, error.status)
        assertEquals("DRIVER_VEHICLE_LOCKED", error.code)
        assertEquals("plate_number", error.details!!.jsonObject["locked_fields"].toString().trim('[', ']', '"'))
    }

    @Test
    fun `a document is uploaded with its own type and mime, then registered`() = runTest {
        server.enqueue(ok("""{"success":true,"data":{"file_url":"/api/v1/files/u/20/p.pdf?exp=1&sig=s","type":"passport",
            "mime_type":"application/pdf","size_bytes":4,"original_filename":"passport.pdf"},"message":"File uploaded successfully"}"""))
        server.enqueue(ok("""{"success":true,"data":{"document_id":3,"driver_id":6,"document_type":"passport",
            "file_url":"/api/v1/files/u/20/p.pdf?exp=2&sig=t","status":"pending","rejection_reason":null},"message":"Document submitted"}"""))

        val uploaded = FilesApi(transport).upload(byteArrayOf(0x25, 0x50, 0x44, 0x46), "passport.pdf", "passport", FilesApi.PDF)
        val row = DriverApi(transport).submitDocument("passport", uploaded.fileUrl, uploaded.mimeType!!, uploaded.sizeBytes!!)

        val upload = server.takeRequest()
        assertEquals("/api/v1/files/upload", upload.url.encodedPath)
        val text = upload.body!!.utf8()
        assertTrue(text.contains("name=\"type\"") && text.contains("passport"))
        assertTrue(text.contains("filename=\"passport.pdf\""))
        assertTrue(text.contains("Content-Type: application/pdf"))
        val submit = server.takeRequest()
        assertEquals("/api/v1/driver/documents", submit.url.encodedPath)
        val body = ElchiJson.parseToJsonElement(submit.body!!.utf8()).jsonObject
        assertEquals("passport", body["document_type"]!!.jsonPrimitive.content)
        assertEquals("/api/v1/files/u/20/p.pdf?exp=1&sig=s", body["file_url"]!!.jsonPrimitive.content)
        assertEquals("application/pdf", body["mime_type"]!!.jsonPrimitive.content)
        assertEquals("4", body["size_bytes"]!!.jsonPrimitive.content)
        assertEquals("pending", row.status)
    }

    @Test
    fun `a file over the limit reads as FILE_TOO_LARGE`() = runTest {
        server.enqueue(MockResponse.Builder().code(413).body("""{"success":false,"error":{"code":"FILE_TOO_LARGE","message":"too large"}}""").build())

        val error = runCatching { FilesApi(transport).upload(byteArrayOf(1), "selfie.jpg", "selfie", FilesApi.JPEG) }.exceptionOrNull() as ApiException

        assertEquals(413, error.status)
        assertEquals("FILE_TOO_LARGE", error.code)
    }

    @Test
    fun `documents are listed and availability returns the stored value`() = runTest {
        server.enqueue(ok("""{"success":true,"data":[{"document_id":1,"driver_id":6,"document_type":"license","file_url":"/f",
            "status":"rejected","rejection_reason":"rasm xira"}],"message":"OK"}"""))
        server.enqueue(ok("""{"success":true,"data":{"is_available":true},"message":"Availability updated"}"""))

        val docs = DriverApi(transport).documents()
        val on = DriverApi(transport).setAvailability(true)

        assertEquals("rasm xira", docs.single().rejectionReason)
        assertTrue(on)
        server.takeRequest()
        val toggle = server.takeRequest()
        assertEquals("/api/v1/driver/availability", toggle.url.encodedPath)
        assertEquals("""{"is_available":true}""", toggle.body?.utf8())
    }
}
