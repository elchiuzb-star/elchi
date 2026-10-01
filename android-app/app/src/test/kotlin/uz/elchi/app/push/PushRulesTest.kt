package uz.elchi.app.push

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.deeplink.DeepLinkRules
import uz.elchi.app.deeplink.DeepLinkTarget
import uz.elchi.app.session.MobileRole

class PushRulesTest {
    private fun msg(type: String, id: String? = null, key: String? = "notification.$type.title") = PushMessage(type, id, key)

    @Test
    fun `a message is the three allowlisted keys, anything else is ignored`() {
        assertEquals(
            PushMessage("booking.accepted", "bkg_abc", "notification.booking.accepted.title"),
            PushRules.parse(mapOf("event_type" to "booking.accepted", "aggregate_id" to "bkg_abc", "title_key" to "notification.booking.accepted.title", "phone" to "+998")),
        )
        assertEquals(PushMessage("chat.message.created", null, null), PushRules.parse(mapOf("event_type" to "chat.message.created")))
        // Not ours, or shapes that must not reach a link or a lookup.
        assertNull(PushRules.parse(emptyMap()))
        assertNull(PushRules.parse(mapOf("event_type" to " ")))
        assertNull(PushRules.parse(mapOf("event_type" to "Booking Accepted")))
        assertEquals(
            PushMessage("booking.accepted", null, null),
            PushRules.parse(mapOf("event_type" to "booking.accepted", "aggregate_id" to "../x", "title_key" to "a b")),
        )
    }

    @Test
    fun `title keys follow the inbox, body falls back to the caller's line`() {
        val m = msg("booking.cancelled", "bkg_1", key = "custom.key")
        assertEquals(listOf("custom.key", "notification.booking.cancelled.title", "notification.fallback.title"), PushRules.titleKeys(m))
        assertEquals(listOf("notification.booking.cancelled.title", "notification.fallback.title"), PushRules.titleKeys(msg("booking.cancelled")))
        assertEquals(listOf("notification.x.title", "notification.fallback.title"), PushRules.titleKeys(msg("x", key = null)))
        assertEquals(listOf("notification.booking.cancelled.body"), PushRules.bodyKeys(m))

        val dict = mapOf("notification.booking.cancelled.title" to "Bron bekor qilindi", "notification.fallback.title" to "Yangi bildirishnoma", "has.param" to "Kod {code}")
        assertEquals("Bron bekor qilindi", PushRules.firstKnown(PushRules.titleKeys(m), dict::get))
        assertEquals("Yangi bildirishnoma", PushRules.firstKnown(PushRules.titleKeys(msg("new.event")), dict::get))
        // A text with an unfilled placeholder never reaches the shade; nothing known -> the caller's generic line.
        assertEquals("Yangi bildirishnoma", PushRules.firstKnown(listOf("has.param", "notification.fallback.title"), dict::get))
        assertNull(PushRules.firstKnown(PushRules.bodyKeys(m), dict::get))
    }

    @Test
    fun `a client's tap opens the thing the event is about`() {
        val c = MobileRole.CLIENT
        assertEquals("elchi://bookings/bkg_1", PushRules.link(msg("booking.accepted", "bkg_1"), c))
        assertEquals("elchi://bookings/bkg_1", PushRules.link(msg("booking.driver_arrived", "bkg_1"), c))
        assertEquals("elchi://bookings/bkg_1", PushRules.link(msg("tracking.window_opened", "bkg_1"), c))
        assertEquals("elchi://bookings/bkg_1/messages", PushRules.link(msg("chat.message.created", "bkg_1"), c))
        assertEquals("elchi://listings/lst_2", PushRules.link(msg("listing.expired", "lst_2"), c))
        assertEquals("elchi://proposals/prp_3", PushRules.link(msg("proposal.created", "prp_3"), c))
    }

    @Test
    fun `without a screen of its own, the tap asks the inbox for the same event's row`() {
        val c = MobileRole.CLIENT
        // A chat message's aggregate is the chat thread: the inbox row (params.thread_id) links the booking chat.
        assertEquals("elchi://notifications?event=chat.message.created&ref=cht_5", PushRules.link(msg("chat.message.created", "cht_5"), c))
        // An operator reply's aggregate is the requester (never in params): the newest reply's row.
        assertEquals("elchi://notifications?event=support.thread.replied", PushRules.link(msg("support.thread.replied", "usr_4"), c))
        assertEquals("elchi://notifications?event=trip.status_changed&ref=trp_6", PushRules.link(msg("trip.status_changed", "trp_6"), c))
        assertEquals("elchi://notifications?event=x.y", PushRules.link(msg("x.y"), c))
        assertEquals("elchi://notifications?event=booking.accepted&ref=nounderscore", PushRules.link(msg("booking.accepted", "nounderscore"), c))
        assertTrue(PushRules.fallsBackToThreads("support.thread.replied"))
        assertFalse(PushRules.fallsBackToThreads("chat.message.created"))
        assertFalse(PushRules.fallsBackToThreads(null))
    }

    @Test
    fun `a driver's push opens its booking, chat, offer, trip and wallet`() {
        assertEquals("elchi://notifications?event=support.thread.replied", PushRules.link(msg("support.thread.replied", "usr_4"), MobileRole.DRIVER))
        assertEquals("elchi://bookings/bkg_1", PushRules.link(msg("booking.accepted", "bkg_1"), MobileRole.DRIVER))
        assertEquals("elchi://bookings/bkg_1/messages", PushRules.link(msg("chat.message.created", "bkg_1"), MobileRole.DRIVER))
        assertEquals("elchi://proposals/prp_2", PushRules.link(msg("proposal.countered", "prp_2"), MobileRole.DRIVER))
        assertEquals("elchi://trips/trp_3", PushRules.link(msg("trip.departed", "trp_3"), MobileRole.DRIVER))
        assertEquals("elchi://wallet", PushRules.link(msg("wallet.topup.approved", "top_4"), MobileRole.DRIVER))
        assertEquals("elchi://wallet", PushRules.link(msg("wallet.balance.changed", "wal_5"), MobileRole.DRIVER))
        // A listing is a client screen; no role at all = the inbox way.
        assertEquals("elchi://notifications?event=listing.updated&ref=lst_6", PushRules.link(msg("listing.updated", "lst_6"), MobileRole.DRIVER))
        assertEquals("elchi://notifications?event=booking.accepted&ref=bkg_1", PushRules.link(msg("booking.accepted", "bkg_1"), null))
        // A client never gets the driver's trip or wallet link.
        assertEquals("elchi://notifications?event=trip.departed&ref=trp_3", PushRules.link(msg("trip.departed", "trp_3"), MobileRole.CLIENT))
    }

    @Test
    fun `the router reads the inbox hint back`() {
        assertEquals(
            DeepLinkTarget.Inbox("chat.message.created", "cht_5"),
            DeepLinkRules.parse(PushRules.link(msg("chat.message.created", "cht_5"), MobileRole.CLIENT), emptyList()),
        )
        assertEquals(
            DeepLinkTarget.Inbox("support.thread.replied", null),
            DeepLinkRules.parse(PushRules.link(msg("support.thread.replied", "usr_4"), MobileRole.DRIVER), emptyList()),
        )
    }

    @Test
    fun `every link is one the deep-link router opens`() {
        val types = listOf("booking.accepted", "chat.message.created", "support.thread.replied", "listing.published", "proposal.created", "trip.status_changed")
        val ids = listOf(null, "bkg_1", "lst_1", "prp_1", "cht_1", "usr_1", "trp_1")
        for (role in listOf(MobileRole.CLIENT, MobileRole.DRIVER)) for (type in types) for (id in ids) {
            val link = PushRules.link(msg(type, id), role)
            val target = DeepLinkRules.forRole(DeepLinkRules.parse(link, emptyList()), role)
            assertTrue("$role $type $id -> $link", target != DeepLinkTarget.Unsupported)
        }
    }

    @Test
    fun `notifications group by the thing they are about`() {
        assertEquals("elchi.bkg_1", PushRules.group(msg("booking.accepted", "bkg_1")))
        assertEquals(PushRules.group(msg("booking.started", "bkg_1")), PushRules.group(msg("chat.message.created", "bkg_1")))
        assertEquals("elchi.app", PushRules.group(msg("x")))
    }

    @Test
    fun `the token is registered when nothing, the token or the person changed, or once a day`() {
        val now = 1_000_000_000L
        val saved = PushRegistration(token = "t1", userId = 7, deviceId = "dev_1", atMillis = now - 1000)
        assertFalse(PushRules.needsRegistration(saved, "t1", 7, now))
        assertTrue(PushRules.needsRegistration(saved.copy(deviceId = null), "t1", 7, now))
        assertTrue(PushRules.needsRegistration(saved, "t2", 7, now))
        assertTrue(PushRules.needsRegistration(saved, "t1", 8, now))
        assertTrue(PushRules.needsRegistration(saved.copy(atMillis = now - PushRules.REFRESH_AFTER_MILLIS), "t1", 7, now))
        assertTrue(PushRules.needsRegistration(saved.copy(atMillis = now + 1), "t1", 7, now))
        assertTrue(PushRules.needsRegistration(PushRegistration(null, null, null, 0), "t1", 7, now))
    }
}
