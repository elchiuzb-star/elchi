package uz.elchi.app.deeplink

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import uz.elchi.app.api.ApiException
import uz.elchi.app.feature.client.InboxTarget
import uz.elchi.app.session.MobileRole

class DeepLinkRulesTest {
    private val hosts = DeepLinkRules.hosts("www.elchigo.uz, elchigo.uz")
    private fun parse(raw: String?) = DeepLinkRules.parse(raw, hosts)

    @Test
    fun `hosts come from one comma-separated build field`() {
        assertEquals(listOf("www.elchigo.uz", "elchigo.uz"), hosts)
        assertEquals(listOf("a.uz"), DeepLinkRules.hosts(" A.uz ,, "))
    }

    @Test
    fun `in-app paths lead to the inbox's screens`() {
        val id = "3f2c9a1e-5b7d-4c2a-9e11-0a1b2c3d4e5f"
        assertEquals(DeepLinkTarget.Booking(id), parse("elchi://bookings/$id"))
        assertEquals(DeepLinkTarget.Booking(id), parse("elchi://bookings/$id/"))
        assertEquals(DeepLinkTarget.BookingChat(id), parse("elchi://bookings/$id/messages"))
        assertEquals(DeepLinkTarget.Listing("L1"), parse("elchi://listings/L1"))
        assertEquals(DeepLinkTarget.Proposal("p_2"), parse("elchi://proposals/p_2?x=1"))
        assertEquals(DeepLinkTarget.SupportThread(id), parse("elchi://support-threads/$id"))
        // The first word may also sit in the path (`elchi:///...`), and the scheme is case-insensitive.
        assertEquals(DeepLinkTarget.Booking("7"), parse("elchi:///bookings/7"))
        assertEquals(DeepLinkTarget.Booking("7"), parse("ELCHI://bookings/7"))
    }

    @Test
    fun `the inbox and the conversations list are in-app only, without an id`() {
        assertEquals(DeepLinkTarget.Inbox(), parse("elchi://notifications"))
        assertEquals(DeepLinkTarget.Inbox(), parse("elchi://notifications/"))
        assertEquals(DeepLinkTarget.SupportThreads, parse("elchi://support-threads"))
        listOf("elchi://notifications/1", "https://www.elchigo.uz/notifications", "https://www.elchigo.uz/support-threads")
            .forEach { raw -> assertEquals(raw, DeepLinkTarget.Unsupported, parse(raw)) }
        // A push's hint: the event and, optionally, the id its inbox row mentions. A bad hint is dropped, not passed on.
        assertEquals(DeepLinkTarget.Inbox("chat.message.created", "cht_1"), parse("elchi://notifications?event=chat.message.created&ref=cht_1"))
        assertEquals(DeepLinkTarget.Inbox("support.thread.replied", null), parse("elchi://notifications?event=support.thread.replied"))
        assertEquals(DeepLinkTarget.Inbox("x.y", null), parse("elchi://notifications?event=x.y&ref=a/b"))
        assertEquals(DeepLinkTarget.Inbox(), parse("elchi://notifications?event=Bad%20Event&ref=cht_1"))
        assertEquals(DeepLinkTarget.Inbox(), parse("elchi://notifications?ref=cht_1&x"))
        // A driver has both screens; neither is an inbox item.
        listOf(DeepLinkTarget.Inbox(), DeepLinkTarget.Inbox("a.b", "c"), DeepLinkTarget.SupportThreads).forEach {
            assertEquals(it, DeepLinkRules.forRole(it, MobileRole.DRIVER))
            assertEquals(it, DeepLinkRules.forRole(it, MobileRole.CLIENT))
            assertEquals(DeepLinkTarget.Unsupported, DeepLinkRules.forRole(it, null))
            assertNull(DeepLinkRules.inboxTarget(it))
        }
    }

    @Test
    fun `referral codes are normalised, from the app scheme and the web hosts`() {
        assertEquals(DeepLinkTarget.Referral("AB2CD3EF"), parse("elchi://r/AB2CD3EF"))
        assertEquals(DeepLinkTarget.Referral("AB2CD3EF"), parse("elchi://r/ab2cd3ef"))
        assertEquals(DeepLinkTarget.Referral("AB2CD3EF"), parse("https://www.elchigo.uz/r/AB2CD3EF"))
        assertEquals(DeepLinkTarget.Referral("AB2CD3EF"), parse("https://elchigo.uz/r/ab2cd3ef/?utm=x"))
        assertEquals(DeepLinkTarget.Referral("AB2CD3EF"), parse("https://ELCHIGO.UZ/r/AB2C-D3EF"))
    }

    @Test
    fun `bad codes and anything unknown are unsupported`() {
        listOf(
            null, "", "   ", "not a uri %%", "garbage",
            // Letters outside the alphabet (0, 1, I, L, O), wrong length.
            "elchi://r/AB0CD1EF", "elchi://r/ABCDEFGIL", "elchi://r/AB2CD3E", "elchi://r/AB2CD3EFG", "elchi://r/",
            // Only /r/ on the web hosts: /t/ and /e/ stay in the browser, in-app paths are not web links.
            "https://www.elchigo.uz/t/abc", "https://www.elchigo.uz/e/abc", "https://www.elchigo.uz/bookings/1",
            "https://www.elchigo.uz/", "https://www.elchigo.uz/r/AB2CD3EF/more",
            // Another host, or plain http.
            "https://evil.example/r/AB2CD3EF", "http://www.elchigo.uz/r/AB2CD3EF",
            // Unknown or malformed in-app paths.
            "elchi://trips", "elchi://wallet/1", "elchi://bookings", "elchi://bookings/1/other", "elchi://bookings/1/messages/x",
            "elchi://listings/a%2Fb", "elchi://support-threads/${"x".repeat(65)}",
            "mailto:a@b.uz",
        ).forEach { raw -> assertEquals(raw, DeepLinkTarget.Unsupported, parse(raw)) }
    }

    @Test
    fun `a driver opens its bookings, offers, trips, wallet and a listing link`() {
        val referral = DeepLinkTarget.Referral("AB2CD3EF")
        val thread = DeepLinkTarget.SupportThread("t1")
        assertEquals(referral, DeepLinkRules.forRole(referral, MobileRole.DRIVER))
        assertEquals(thread, DeepLinkRules.forRole(thread, MobileRole.DRIVER))
        listOf(DeepLinkTarget.Booking("1"), DeepLinkTarget.BookingChat("1"), DeepLinkTarget.Proposal("1"), DeepLinkTarget.Trip("1"), DeepLinkTarget.Wallet).forEach {
            assertEquals(it, DeepLinkRules.forRole(it, MobileRole.DRIVER))
        }
        // Stage 10: the public page's "Ilovani ochish" - the offer screen (OfferRules.bidView decides what it shows).
        assertEquals(DeepLinkTarget.Listing("1"), DeepLinkRules.forRole(DeepLinkTarget.Listing("1"), MobileRole.DRIVER))
        assertEquals(DeepLinkTarget.Unsupported, DeepLinkRules.forRole(DeepLinkTarget.Listing("1"), null))
        listOf(DeepLinkTarget.Booking("1"), DeepLinkTarget.BookingChat("1"), DeepLinkTarget.Listing("1"), DeepLinkTarget.Proposal("1")).forEach {
            assertEquals(it, DeepLinkRules.forRole(it, MobileRole.CLIENT))
        }
        // The trip and the wallet are driver screens.
        assertEquals(DeepLinkTarget.Unsupported, DeepLinkRules.forRole(DeepLinkTarget.Trip("1"), MobileRole.CLIENT))
        assertEquals(DeepLinkTarget.Unsupported, DeepLinkRules.forRole(DeepLinkTarget.Wallet, MobileRole.CLIENT))
        assertEquals(DeepLinkTarget.Unsupported, DeepLinkRules.forRole(thread, null))
    }

    @Test
    fun `a client opens a listing link only when the server answers with the owner's DTO`() {
        val owner = buildJsonObject {
            put("id", "lst_1")
            put("status", "published")
            put("owner", buildJsonObject { put("display_name", "A") })
        }
        val public = buildJsonObject {
            put("id", "lst_1")
            put("status", "published")
        }
        assertTrue(DeepLinkRules.ownsListing(owner))
        assertFalse(DeepLinkRules.ownsListing(public))
        assertFalse(DeepLinkRules.ownsListing(buildJsonObject { put("owner", JsonNull) }))
        assertFalse(DeepLinkRules.ownsListing(JsonNull))
        // The link parses the same for both roles; signed out, DeepLinkCenter keeps it until a flow takes it.
        assertEquals(DeepLinkTarget.Listing("lst_1"), parse("elchi://listings/lst_1"))
        assertEquals(DeepLinkTarget.Listing("lst_1"), DeepLinkRules.forRole(DeepLinkTarget.Listing("lst_1"), MobileRole.CLIENT))
    }

    @Test
    fun `trip and wallet links parse and map to the inbox targets`() {
        assertEquals(DeepLinkTarget.Trip("trp_1"), parse("elchi://trips/trp_1"))
        assertEquals(DeepLinkTarget.Wallet, parse("elchi://wallet"))
        assertEquals(InboxTarget.Trip("trp_1"), DeepLinkRules.inboxTarget(DeepLinkTarget.Trip("trp_1")))
        assertEquals(InboxTarget.Wallet, DeepLinkRules.inboxTarget(DeepLinkTarget.Wallet))
    }

    @Test
    fun `client targets are the inbox's`() {
        assertEquals(InboxTarget.Booking("1", chat = false), DeepLinkRules.inboxTarget(DeepLinkTarget.Booking("1")))
        assertEquals(InboxTarget.Booking("1", chat = true), DeepLinkRules.inboxTarget(DeepLinkTarget.BookingChat("1")))
        assertEquals(InboxTarget.Listing("2"), DeepLinkRules.inboxTarget(DeepLinkTarget.Listing("2")))
        assertEquals(InboxTarget.Proposal("3", null), DeepLinkRules.inboxTarget(DeepLinkTarget.Proposal("3")))
        assertEquals(InboxTarget.SupportThread("4"), DeepLinkRules.inboxTarget(DeepLinkTarget.SupportThread("4")))
        assertNull(DeepLinkRules.inboxTarget(DeepLinkTarget.Referral("AB2CD3EF")))
        assertNull(DeepLinkRules.inboxTarget(DeepLinkTarget.Unsupported))
    }

    @Test
    fun `the first referral code wins`() {
        assertEquals("AB2CD3EF", ReferralRules.keep(null, "AB2CD3EF"))
        assertEquals("AB2CD3EF", ReferralRules.keep("AB2CD3EF", "ZZZZZZZZ"))
    }

    @Test
    fun `the kept code is forgotten after success or a final refusal, kept when the programme is off`() {
        val code = "AB2CD3EF"
        fun err(status: Int, c: String) = ApiException(status, c, "m")
        assertTrue(ReferralRules.forgetAfter(null, code, code))
        // A success with another typed code: the attribution is made and never replaced.
        assertTrue(ReferralRules.forgetAfter(null, "ZZZZZZZZ", code))
        listOf("REFERRAL_ALREADY_ATTRIBUTED", "REFERRAL_WINDOW_CLOSED", "REFERRAL_NOT_ELIGIBLE", "REFERRAL_SELF_REFERRAL").forEach {
            assertTrue(it, ReferralRules.forgetAfter(err(409, it), "ZZZZZZZZ", code))
        }
        assertTrue(ReferralRules.forgetAfter(err(404, "REFERRAL_CODE_INVALID"), code, code))
        assertTrue(ReferralRules.forgetAfter(err(400, "VALIDATION_ERROR"), code, code))
        // A mistyped other code does not erase the link's code.
        assertFalse(ReferralRules.forgetAfter(err(404, "REFERRAL_CODE_INVALID"), "ZZZZZZZZ", code))
        assertFalse(ReferralRules.forgetAfter(err(403, "FEATURE_DISABLED"), code, code))
        assertFalse(ReferralRules.forgetAfter(err(429, "RATE_LIMITED"), code, code))
        assertFalse(ReferralRules.forgetAfter(err(0, ApiException.NETWORK), code, code))
        assertFalse(ReferralRules.forgetAfter(err(500, ApiException.SERVER), code, code))
        assertFalse(ReferralRules.forgetAfter(IllegalStateException(), code, code))
        assertFalse(ReferralRules.forgetAfter(null, code, null))
    }
}
