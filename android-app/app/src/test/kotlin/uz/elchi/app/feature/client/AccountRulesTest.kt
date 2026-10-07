package uz.elchi.app.feature.client

import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.BookingClientDTO
import uz.elchi.app.api.ElchiJson
import uz.elchi.app.api.generated.ListingDTO
import uz.elchi.app.api.generated.NotificationDTO
import uz.elchi.app.api.generated.ProgressDTO
import uz.elchi.app.api.generated.PromoBucketDTO
import uz.elchi.app.api.generated.ProposalThreadDTO
import uz.elchi.app.api.generated.ReferralCodeDTO
import uz.elchi.app.api.generated.ReportStatus
import uz.elchi.app.api.generated.SupportTicketStatus
import uz.elchi.app.session.RefreshFailure
import uz.elchi.app.session.SessionRules
import uz.elchi.app.ui.theme.Tone
import java.time.Instant

class AccountRulesTest {
    /** 30.09.2026 15:00 in Tashkent. */
    private val now: Instant = Instant.parse("2026-09-30T10:00:00Z")

    private fun notification(
        type: String = "proposal.created",
        titleKey: String = "notification.$type.title",
        bodyKey: String = "notification.$type.body",
        link: String? = "/proposals/prp_1",
        read: Boolean = false,
        params: String = """{"listing_id":"lst_9","revision":2,"nested":{"a":1}}""",
        created: String = "2026-09-30T10:24:00+05:00",
        id: String = "ntf_1",
    ): NotificationDTO = ElchiJson.decodeFromString(
        NotificationDTO.serializer(),
        """{"id":"$id","type":"$type","title_key":"$titleKey","body_key":"$bodyKey","params":$params,"is_read":$read,
           "created_at":"$created","link":${link?.let { "\"$it\"" } ?: "null"}}""",
    )

    // -- inbox --------------------------------------------------------------------------------------------------

    @Test
    fun `inbox links lead to the booking, its chat, a listing, a proposal's listing and a support thread`() {
        assertEquals(InboxTarget.Booking("bkg_1", chat = false), InboxRules.parseLink("/bookings/bkg_1"))
        assertEquals(InboxTarget.Booking("bkg_1", chat = true), InboxRules.parseLink("/bookings/bkg_1/messages"))
        assertEquals(InboxTarget.Booking("bkg_1", chat = false), InboxRules.parseLink("https://api.elchigo.uz/api/v2/bookings/bkg_1/"))
        assertEquals(InboxTarget.Listing("lst_1"), InboxRules.parseLink("/listings/lst_1"))
        assertEquals(InboxTarget.SupportThread("sth_1"), InboxRules.parseLink("/support-threads/sth_1"))
        assertEquals(InboxTarget.Trip("trp_1"), InboxRules.parseLink("/trips/trp_1"))
    }

    @Test
    fun `a proposal link opens its listing when the params name it, else only says which thread`() {
        val item = notification()
        assertEquals(InboxTarget.Proposal("prp_1", "lst_9"), InboxRules.parseLink(item.link, item.params))
        // Q100: the proposal's own chat is never opened; the link still leads to the listing.
        assertEquals(InboxTarget.Proposal("prp_1", null), InboxRules.parseLink("/proposals/prp_1/messages"))
    }

    @Test
    fun `no link or an unknown one leads nowhere`() {
        assertNull(InboxRules.parseLink(null))
        assertNull(InboxRules.parseLink("  "))
        assertNull(InboxRules.parseLink("/wallet/topups/1"))
        assertNull(InboxRules.parseLink("/bookings/bkg_1/tracking"))
    }

    @Test
    fun `title falls back from the server key to the event key to the generic one, never the raw key`() {
        val item = notification(type = "booking.accepted", titleKey = "notification.booking.accepted.v2.title")
        val dictionary = mapOf("notification.booking.accepted.title" to "Kelishuv tuzildi", "notification.fallback.title" to "Yangi bildirishnoma")
        assertEquals("Kelishuv tuzildi", InboxRules.firstKnown(InboxRules.titleKeys(item), dictionary::get))
        val unknown = notification(type = "brand.new", titleKey = "x.y")
        assertEquals("Yangi bildirishnoma", InboxRules.firstKnown(InboxRules.titleKeys(unknown), dictionary::get))
        assertEquals(listOf("notification.brand.new.body").last(), InboxRules.bodyKeys(unknown).last())
        assertNull(InboxRules.firstKnown(InboxRules.bodyKeys(unknown), dictionary::get))
    }

    @Test
    fun `params become placeholder values, nested objects are dropped`() {
        val params = InboxRules.params(notification().params).toMap()
        assertEquals(mapOf("listing_id" to "lst_9", "revision" to "2"), params)
        assertTrue(InboxRules.params(JsonPrimitive(1)).isEmpty())
    }

    @Test
    fun `time reads today as HH-mm, yesterday separately, older as a day`() {
        assertEquals(InboxTime.Today("10:24"), InboxRules.time("2026-09-30T10:24:00+05:00", now, "uz"))
        // 23:30 UTC on the 29th is already 04:30 on the 30th in Tashkent.
        assertEquals(InboxTime.Today("04:30"), InboxRules.time("2026-09-29T23:30:00Z", now, "uz"))
        assertEquals(InboxTime.Yesterday("08:12"), InboxRules.time("2026-09-29T08:12:00+05:00", now, "uz"))
        val older = InboxRules.time("2026-09-12T08:12:00+05:00", now, "ru")
        assertTrue(older is InboxTime.Day && older.date.startsWith("12 "))
        val lastYear = InboxRules.time("2025-12-31T08:00:00+05:00", now, "uz") as InboxTime.Day
        assertTrue(lastYear.date.endsWith("2025"))
        assertNull(InboxRules.time(null, now, "uz"))
    }

    @Test
    fun `unread count, marking read and merging pages`() {
        val items = listOf(notification(id = "a"), notification(id = "b", read = true), notification(id = "c"))
        assertEquals(2, InboxRules.unreadCount(items))
        val marked = InboxRules.markRead(items, "a")
        assertEquals(1, InboxRules.unreadCount(marked))
        assertEquals(items.map { it.id }, marked.map { it.id })
        val merged = InboxRules.merge(items, listOf(notification(id = "c"), notification(id = "d")))
        assertEquals(listOf("a", "b", "c", "d"), merged.map { it.id })
    }

    @Test
    fun `a push tap finds the newest row of its event that mentions its id`() {
        val chat = { id: String, thread: String, bkg: String ->
            notification(type = "chat.message.created", id = id, link = "/bookings/$bkg/messages", params = """{"thread_id":"$thread","author_side":"driver"}""")
        }
        val reply = notification(type = "support.thread.replied", id = "r", link = "/support-threads/sth_1", params = """{"thread_id":"sth_1","booking_id":"bkg_1"}""")
        // Newest first, as the server pages them.
        val items = listOf(chat("c3", "cht_2", "bkg_2"), reply, chat("c2", "cht_1", "bkg_1"), chat("c1", "cht_1", "bkg_1"))
        assertEquals("c2", InboxRules.pushMatch(items, "chat.message.created", "cht_1")?.id)
        assertEquals("c3", InboxRules.pushMatch(items, "chat.message.created", null)?.id)
        assertEquals("r", InboxRules.pushMatch(items, "support.thread.replied", null)?.id)
        assertNull(InboxRules.pushMatch(items, "chat.message.created", "cht_9"))
        assertNull(InboxRules.pushMatch(items, "booking.accepted", null))
        assertEquals(InboxTarget.Booking("bkg_1", chat = true), InboxRules.parseLink(InboxRules.pushMatch(items, "chat.message.created", "cht_1")?.link))
    }

    // -- profile ------------------------------------------------------------------------------------------------

    private fun listing(id: String, status: String, created: String, service: String = "parcel"): ListingDTO = ElchiJson.decodeFromString(
        ListingDTO.serializer(),
        """{"id":"$id","kind":"request","service_type":"$service","status":"$status","version":1,"terms_version":1,
        "owner":{"id":"usr_1","display_name":"Demo"},"corridor_id":"cor_1",
        "origin_point":{"lat":41.3,"lng":69.2,"district":{"id":"dst_a","name_uz":"Toshkent"},"address":null},
        "destination_point":{"lat":39.7,"lng":64.4,"district":{"id":"dst_b","name_uz":"Buxoro"},"address":null},
        "departure_window_start":"2026-10-01T04:00:00Z","departure_window_end":"2026-10-01T13:00:00Z","timezone":"Asia/Tashkent",
        "price_basis":"total","unit_price_minor":100,"quantity":1,"total_minor":100,"currency":"UZS","payment_method":"cash",
        "expires_at":"2026-10-01T13:00:00Z","comment":null,"view_count":0,"created_at":"$created"}""",
    )

    private fun booking(id: String, status: String, created: String): BookingClientDTO = ElchiJson.decodeFromString(
        BookingClientDTO.serializer(),
        """{"id":"$id","viewer_side":"client","service_type":"parcel","service_status":"$status","pickup":{},"dropoff":{},
        "unit_price_minor":100,"total_minor":100,"created_at":"$created"}""",
    )

    private fun thread(id: String, author: String, state: String = "open"): ProposalThreadDTO = ElchiJson.decodeFromString(
        ProposalThreadDTO.serializer(),
        """{"id":"$id","listing_id":"lst_1","listing_terms_version":1,"state":"$state","client":{"side":"client","label":"Mijoz"},"driver":{"side":"driver","label":"Haydovchi #1"},
        "current_version":{"id":"prv_$id","listing_terms_version":1,"revision":1,"author_side":"$author","status":"active","pickup_window_start":"2026-10-01T04:00:00Z",
        "pickup_window_end":"2026-10-01T06:00:00Z","quantity":1,"price_basis":"total","unit_price_minor":100,"total_minor":100,"currency":"UZS",
        "expires_at":"2026-09-30T12:00:00Z","created_at":"2026-09-30T09:00:00Z","demand":{"baggage_ml":0,"cargo_weight_g":0,"cargo_volume_ml":0},"price_revisions_left":{"client":3,"driver":3}}}""",
    )

    @Test
    fun `profile numbers come from v2 listings, bookings and the offers waiting for me`() {
        val listings = listOf(
            listing("lst_1", "published", "2026-09-30T08:00:00Z"),
            listing("lst_2", "paused", "2026-09-29T08:00:00Z"),
            listing("lst_3", "fulfilled", "2026-09-28T08:00:00Z"),
            listing("lst_4", "cancelled", "2026-09-27T08:00:00Z"),
            listing("lst_p", "published", "2026-09-27T08:00:00Z", service = "passenger"),
        )
        val bookings = listOf(
            booking("bkg_1", "in_transit", "2026-09-28T09:00:00Z"),
            booking("bkg_2", "completed", "2026-09-20T09:00:00Z"),
            booking("bkg_3", "cancelled", "2026-09-19T09:00:00Z"),
        )
        val threads = mapOf(
            "lst_1" to listOf(thread("a", "driver"), thread("b", "client"), thread("c", "driver", state = "closed")),
            "lst_2" to listOf(thread("d", "driver")),
        )
        val stats = ProfileRules.stats(listings, bookings, threads, now)
        assertEquals(4, stats.total)
        assertEquals(3, stats.active) // two open listings + the booking in transit
        assertEquals(2, stats.offers) // driver-authored open offers on open listings
        assertEquals(1, stats.completed)
        assertEquals("status.published", stats.latestKey) // lst_1 is newer than any booking
    }

    @Test
    fun `the newest booking names the latest order, unknown offers stay unknown`() {
        val stats = ProfileRules.stats(
            listOf(listing("lst_1", "fulfilled", "2026-09-28T08:00:00Z")),
            listOf(booking("bkg_1", "in_transit", "2026-09-28T09:00:00Z")),
            threads = null,
            now = now,
        )
        assertNull(stats.offers)
        assertEquals("parcel.status.driverDeparted", stats.latestKey)
        assertNull(ProfileRules.stats(emptyList(), emptyList(), emptyMap(), now).latestKey)
    }

    @Test
    fun `initials and the name to save`() {
        assertEquals("AK", ProfileRules.initials("Aziza  Karimova"))
        assertEquals("D", ProfileRules.initials("demo"))
        assertNull(ProfileRules.initials("  "))
        assertNull(ProfileRules.initials(null))
        assertEquals("Ali Valiyev", ProfileRules.nameToSave("  Ali   Valiyev ", "Demo"))
        assertNull(ProfileRules.nameToSave("   ", "Demo"))
        assertNull(ProfileRules.nameToSave("Demo ", "Demo"))
    }

    @Test
    fun `design 05 - a name needs two letters, the latest order is tinted by how far it got`() {
        assertTrue(ProfileRules.nameTooShort("A"))
        assertTrue(ProfileRules.nameTooShort(" 1. "))
        assertFalse(ProfileRules.nameTooShort("Ali"))
        assertFalse(ProfileRules.nameTooShort("Юн"))
        val going = ProfileRules.stats(emptyList(), listOf(booking("bkg_1", "in_transit", "2026-09-28T09:00:00Z")), emptyMap(), now)
        assertEquals(Tone.BLUE, going.latestTone)
        val done = ProfileRules.stats(emptyList(), listOf(booking("bkg_1", "completed", "2026-09-28T09:00:00Z")), emptyMap(), now)
        assertEquals(Tone.OK, done.latestTone)
        val cancelled = ProfileRules.stats(emptyList(), listOf(booking("bkg_1", "cancelled", "2026-09-28T09:00:00Z")), emptyMap(), now)
        assertNull(cancelled.latestTone)
        assertEquals(Tone.BLUE, ProfileRules.stats(listOf(listing("lst_1", "published", "2026-09-30T08:00:00Z")), emptyList(), emptyMap(), now).latestTone)
        assertNull(ProfileRules.stats(emptyList(), emptyList(), emptyMap(), now).latestTone)
    }

    // -- promo --------------------------------------------------------------------------------------------------

    private fun bucket(instrument: String = "passenger_bonus"): PromoBucketDTO = ElchiJson.decodeFromString(
        PromoBucketDTO.serializer(),
        """{"instrument":"$instrument","service_type":"parcel","available_minor":1000000,"reserved_minor":0,"under_review_minor":500000,
        "consumed_minor":2000000,"expired_minor":100,"reversed_minor":50,"next_expiry_at":"2026-10-15T00:00:00Z","currency":"UZS"}""",
    )

    @Test
    fun `bucket rows in reading order, expired includes reversed, hints only where they belong`() {
        val rows = PromoRules.bucketRows(bucket())
        assertEquals(listOf("promo.bucket.available", "promo.bucket.reserved", "docState.pending", "promo.bucket.consumed", "promo.bucket.expired"), rows.map { it.labelKey })
        assertEquals(listOf(1_000_000L, 0L, 500_000L, 2_000_000L, 150L), rows.map { it.minor })
        assertEquals("promo.bucket.underReviewHint", rows[2].hintKey)
        assertNull(rows[0].hintKey)
        assertEquals("15.10.2026", PromoRules.date("2026-10-15T00:00:00Z"))
    }

    @Test
    fun `only client bonus buckets are shown`() {
        assertEquals(1, PromoRules.clientBuckets(listOf(bucket(), bucket("driver_credit"))).size)
        assertEquals("promo.instrument.passengerBonus", PromoRules.instrumentKey(bucket().instrument))
    }

    @Test
    fun `the programme is off only for FEATURE_DISABLED on promotions`() {
        val off = ApiException(403, "FEATURE_DISABLED", "off", buildJsonObject { put("flag", "promotions_enabled") })
        val otherFlag = ApiException(403, "FEATURE_DISABLED", "off", buildJsonObject { put("flag", "parcel_enabled") })
        assertTrue(PromoRules.isProgramOff(off))
        assertTrue(PromoRules.isProgramOff(ApiException(403, "FEATURE_DISABLED", "off")))
        assertFalse(PromoRules.isProgramOff(otherFlag))
        assertFalse(PromoRules.isProgramOff(ApiException(429, "RATE_LIMITED", "slow")))
        assertFalse(PromoRules.isProgramOff(null))
        assertEquals("promoScreen.programOff", PromoRules.programOffKey(hasBuckets = false))
        assertEquals("promoScreen.programOffWithBalance", PromoRules.programOffKey(hasBuckets = true))
    }

    @Test
    fun `codes are normalised like the server and checked against the alphabet`() {
        assertEquals("AB2CD3EF", PromoRules.normalizeCode(" ab2c-d3ef "))
        assertNull(PromoRules.normalizeCode("AB2CD3E")) // 7 characters
        assertNull(PromoRules.normalizeCode("AB2CD3E0")) // 0 is not in the alphabet
        assertNull(PromoRules.normalizeCode("AB2CD3EI")) // neither is I
        assertNull(PromoRules.normalizeCode(null))
        assertEquals("AB2CD3EF", PromoRules.typedCode("ab2-cd3ef9"))
    }

    @Test
    fun `the share link only when a host is configured`() {
        val configured = ReferralCodeDTO(code = "AB2CD3EF", linkStatus = "configured_unverified", shareUrl = "https://elchigo.uz/r/AB2CD3EF")
        val none = ReferralCodeDTO(code = "AB2CD3EF", linkStatus = "not_configured", shareUrl = null)
        assertEquals("https://elchigo.uz/r/AB2CD3EF", PromoRules.shareUrl(configured))
        assertNull(PromoRules.shareUrl(none))
        assertEquals("AB2CD3EF", PromoRules.shareText(none))
        assertEquals("promo.qualification.review", PromoRules.enrollmentStatusKey("review", "promised"))
        assertEquals("promo.enrollment.promised", PromoRules.enrollmentStatusKey(null, "promised"))
        assertNull(PromoRules.enrollmentStatusKey(null, "mystery"))
    }

    // -- safety, help -------------------------------------------------------------------------------------------

    @Test
    fun `report tones - someone still has to look is warn, actioned ok, dismissed neutral`() {
        assertEquals(Tone.WARN, SafetyRules.reportTone(ReportStatus.OPEN))
        assertEquals(Tone.WARN, SafetyRules.reportTone(ReportStatus.UNDER_REVIEW))
        assertEquals(Tone.OK, SafetyRules.reportTone(ReportStatus.ACTIONED))
        assertEquals(Tone.GRAY, SafetyRules.reportTone(ReportStatus.DISMISSED))
        assertEquals(Tone.GRAY, SafetyRules.reportTone(ReportStatus.UNKNOWN))
        assertEquals("blockReport.status.under_review", SafetyRules.reportStatusKey(ReportStatus.UNDER_REVIEW))
    }

    @Test
    fun `ticket and thread statuses`() {
        assertEquals("client.support.ticket.acknowledged", SafetyRules.ticketStatusKey(SupportTicketStatus.ACKNOWLEDGED))
        assertNull(SafetyRules.ticketStatusKey(SupportTicketStatus.UNKNOWN))
        assertEquals(Tone.BLUE, SafetyRules.threadTone("answered"))
        assertEquals(Tone.WARN, SafetyRules.threadTone("assigned"))
        assertEquals(Tone.GRAY, SafetyRules.threadTone("waiting"))
        assertEquals(Tone.GRAY, SafetyRules.threadTone("closed"))
        assertEquals("Posilka kechikmoqda", SafetyRules.ticketTitle("\n  Posilka kechikmoqda\nbron B-2041"))
        assertFalse(SafetyRules.ticketReady(" abc "))
        assertTrue(SafetyRules.ticketReady("Salom!"))
    }

    // -- account deletion ---------------------------------------------------------------------------------------

    @Test
    fun `deletion blockers - named counters with counts, anything else once`() {
        val details = buildJsonObject {
            put("reason", "active_bookings")
            put("active_bookings", 2)
            put("active_orders", 0)
            put("open_disputes", 1)
            put("open_sos_tickets", 0)
            put("pending_no_show_reviews", 0)
            put("wallet_balance_minor", 5000)
            put("custody_cases", 1)
        }
        val lines = DeletionRules.blockers(details)
        assertEquals(
            listOf(
                DeletionBlocker("client.accountDelete.blocked.active_bookings", 2),
                DeletionBlocker("client.accountDelete.blocked.open_disputes", 1),
                DeletionBlocker("client.accountDelete.blocked.other", null),
            ),
            lines,
        )
    }

    @Test
    fun `deletion blockers without other counters, or without details`() {
        val only = buildJsonObject { put("active_bookings", 1); put("held_commission_minor", 0) }
        assertEquals(listOf(DeletionBlocker("client.accountDelete.blocked.active_bookings", 1)), DeletionRules.blockers(only))
        // The server also splits active_bookings into as-client / as-driver: that is the same booking, not "something else".
        val split = buildJsonObject { put("active_bookings", 1); put("active_bookings_as_client", 1); put("active_bookings_as_driver", 0) }
        assertEquals(listOf(DeletionBlocker("client.accountDelete.blocked.active_bookings", 1)), DeletionRules.blockers(split))
        // A refusal that names nothing still says something is open.
        assertEquals(listOf(DeletionBlocker("client.accountDelete.blocked.other", null)), DeletionRules.blockers(null))
        assertEquals(listOf(DeletionBlocker("client.accountDelete.blocked.other", null)), DeletionRules.blockers(buildJsonObject { put("reason", "x") }))
    }

    // -- session ------------------------------------------------------------------------------------------------

    @Test
    fun `a refused refresh token expires the session, offline and server faults keep it`() {
        listOf("INVALID_TOKEN" to 401, "REFRESH_TOKEN_REVOKED" to 401, "TOKEN_EXPIRED" to 401, "UNAUTHORIZED" to 401, "USER_BLOCKED" to 403, "USER_INACTIVE" to 403)
            .forEach { (code, status) -> assertEquals(code, RefreshFailure.EXPIRED, SessionRules.refreshFailure(status, code)) }
        assertEquals(RefreshFailure.EXPIRED, SessionRules.refreshFailure(400, "VALIDATION_ERROR"))
        assertEquals(RefreshFailure.KEEP_SESSION, SessionRules.refreshFailure(0, ApiException.NETWORK))
        assertEquals(RefreshFailure.KEEP_SESSION, SessionRules.refreshFailure(503, "SERVICE_UNAVAILABLE"))
        assertEquals(RefreshFailure.KEEP_SESSION, SessionRules.refreshFailure(500, ApiException.SERVER))
    }

    @Test
    fun `design 05 - the friend's code entry, the usable row, campaign tones`() {
        assertNull(PromoRules.entryErrorKey("AB2C", "AB2CD3EF")) // not finished: no error, the button just waits
        assertEquals("promoScreen.codeFormat", PromoRules.entryErrorKey("AB2CD3E1", null)) // 1 is not in the alphabet
        assertEquals("client.bonus.ownCode", PromoRules.entryErrorKey("AB2CD3EF", "ab2cd3ef"))
        assertNull(PromoRules.entryErrorKey("ZX2CD3EF", "AB2CD3EF"))
        assertTrue(PromoRules.bucketRows(bucket()).first().usable)
        assertEquals(1, PromoRules.bucketRows(bucket()).count { it.usable })
        assertEquals(Tone.OK, PromoRules.enrollmentTone("qualified", "promised"))
        assertEquals(Tone.WARN, PromoRules.enrollmentTone("review", "promised"))
        assertEquals(Tone.BLUE, PromoRules.enrollmentTone(null, "promised"))
        assertEquals(Tone.GRAY, PromoRules.enrollmentTone(null, "released"))
    }

    @Test
    fun `design 05 - help hint while too short, the orders link only for open bookings or orders`() {
        assertFalse(SafetyRules.ticketTooShort(""))
        assertFalse(SafetyRules.ticketTooShort("   "))
        assertTrue(SafetyRules.ticketTooShort(" abcd "))
        assertFalse(SafetyRules.ticketTooShort("Salom!"))
        assertEquals(1000, SafetyRules.TICKET_MAX)
        assertTrue(DeletionRules.leadsToOrders(DeletionRules.blockers(buildJsonObject { put("active_bookings", 1) })))
        assertTrue(DeletionRules.leadsToOrders(DeletionRules.blockers(buildJsonObject { put("active_orders", 2) })))
        assertFalse(DeletionRules.leadsToOrders(DeletionRules.blockers(buildJsonObject { put("open_disputes", 1) })))
        assertFalse(DeletionRules.leadsToOrders(null))
    }

    @Test
    fun `only the referee sees a progress line, in trips or services, never counting what is in review`() {
        val trips = ProgressDTO(done = 3, inReview = 1, remaining = 7, required = 10, unit = "distinct_trip")
        val line = PromoRules.progressLine("referee", trips)!!
        assertEquals("promo.progress.doneTrips", line.key)
        assertEquals(3L, line.done)
        assertEquals(10L, line.required)
        assertEquals(0.3f, line.fraction, 0.0001f)
        assertTrue(line.inReview)
        // The referrer never sees the other person's activity (ADR-0023, DESIGN09 3.8).
        assertNull(PromoRules.progressLine("referrer", trips))
        assertNull(PromoRules.progressLine("referee", null))
        assertNull(PromoRules.progressLine("referee", trips.copy(required = 0)))
        val services = PromoRules.progressLine("referee", ProgressDTO(done = 5, inReview = 0, remaining = 0, required = 2, unit = "service"))!!
        assertEquals("promo.progress.doneServices", services.key)
        assertEquals(2L, services.done)
        assertEquals(1f, services.fraction, 0.0001f)
        assertFalse(services.inReview)
    }
}
