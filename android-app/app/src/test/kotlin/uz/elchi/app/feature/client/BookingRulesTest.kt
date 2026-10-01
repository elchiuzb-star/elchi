package uz.elchi.app.feature.client

import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.elchi.app.api.BookingClientDTO
import uz.elchi.app.api.BookingNoShowReviewDTO
import uz.elchi.app.api.ElchiJson
import uz.elchi.app.api.generated.AmendmentDTO
import uz.elchi.app.api.generated.ChatMessageDTO
import uz.elchi.app.api.generated.ReputationDTO
import uz.elchi.app.api.generated.SupportMessageDTO
import uz.elchi.app.api.generated.TrackingFreshness
import uz.elchi.app.api.generated.TrackingLastPointDTO
import uz.elchi.app.api.trackingSocketUrl
import uz.elchi.app.ui.theme.Tone
import java.time.Instant
import java.util.Locale

class BookingRulesTest {
    private val now: Instant = Instant.parse("2026-09-29T13:00:00Z")

    private fun booking(
        status: String = "confirmed",
        plateNumber: String? = null,
        phone: String? = null,
        phonesVisible: Boolean = false,
        visibleFrom: String? = null,
        cancelled: String = "null",
        extra: String = "",
    ): BookingClientDTO = ElchiJson.decodeFromString(
        BookingClientDTO.serializer(),
        """{"id":"bkg_1","viewer_side":"client","service_type":"parcel","service_status":"$status","cash_status":"unpaid","version":3,
        "trip_id":"trp_1","listing_ids":{"request":"lst_1","supply":null},"quantity":1,"price_basis":"total","unit_price_minor":12000000,
        "total_minor":12000000,"currency":"UZS","payment_method":"cash",
        "pickup":{"stop":null,"point":{"lat":41.28,"lng":69.2,"district":{"id":"dst_a","name_uz":"Toshkent shahri"},"address":"Toshkent"},"occurrence_seq":1,
          "window_start":"2026-09-29T13:10:00Z","window_end":"2026-09-29T14:20:00Z"},
        "dropoff":{"stop":{"id":"stp_b","name_uz":"Registon","name_ru":"Регистан"},"point":null,"occurrence_seq":2},
        "driver":{"id":"usr_d","display_name":"Jasur","vehicle":{"vehicle_class":"car","seat_capacity":4,"make_model":"Chevrolet Cobalt","color":"oq",
          "plate_masked":"01 A ••• KA","plate_number":${plateNumber?.let { "\"$it\"" } ?: "null"},"plate_number_visible_from":"2026-09-29T12:40:00Z"},
          "contact_phone":${phone?.let { "\"$it\"" } ?: "null"}},
        "contact":{"phones_visible":$phonesVisible,"visible_from":${visibleFrom?.let { "\"$it\"" } ?: "null"},"visible_until":null,"chat_thread_id":null,"support_available":true},
        "cancelled":$cancelled,"cancellation_policy_summary":"Pilotda jarima yo'q","promo":null,
        "created_at":"2026-09-29T12:40:16.672402Z","updated_at":"2026-09-29T12:40:30Z"$extra}""",
    )

    private fun amendment(status: String = "proposed", author: String = "driver", expires: String = "2026-09-29T14:00:00Z"): AmendmentDTO =
        ElchiJson.decodeFromString(
            AmendmentDTO.serializer(),
            """{"id":"amd_1","booking_id":"bkg_1","status":"$status","author_side":"$author","changes":{"unit_price_minor":12500000},
            "new_quantity":1,"new_unit_price_minor":12500000,"new_total_minor":12500000,"expires_at":"$expires","version":1}""",
        )

    private fun message(id: String, at: String, mine: Boolean = false, hidden: Boolean = false): ChatMessageDTO =
        ElchiJson.decodeFromString(
            ChatMessageDTO.serializer(),
            """{"id":"$id","author_side":"${if (mine) "client" else "driver"}","is_mine":$mine,"text":"t $id","quick_reply_code":null,
            "moderation_status":"${if (hidden) "hidden_by_staff" else "visible"}","created_at":"$at"}""",
        )

    private fun point(capturedAt: String): TrackingLastPointDTO =
        TrackingLastPointDTO(accuracyM = 12, capturedAt = capturedAt, lat = 41.3, lng = 69.2, lowAccuracy = false, receivedAt = capturedAt)

    // -- availability by status ---------------------------------------------------------------------------------

    @Test
    fun cancelOnlyBeforeDepartureAndNotDuringANoShowReview() {
        assertTrue(BookingRules.canCancel("confirmed"))
        assertTrue(BookingRules.canCancel("awaiting_pickup"))
        listOf("in_transit", "picked_up", "delivered", "completed", "cancelled", "return_required").forEach { assertFalse(it, BookingRules.canCancel(it)) }
        assertFalse(BookingRules.canCancel("confirmed", BookingNoShowReviewDTO("pending")))
        assertTrue(BookingRules.canCancel("confirmed", BookingNoShowReviewDTO("rejected")))
    }

    @Test
    fun amendOnlyWhileConfirmed_notInAwaitingPickupLikeTheWeb() {
        assertTrue(BookingRules.canAmend("confirmed"))
        listOf("awaiting_pickup", "in_transit", "delivered", "completed", "cancelled").forEach { assertFalse(it, BookingRules.canAmend(it)) }
    }

    @Test
    fun rateOnlyCompleted() {
        assertTrue(BookingRules.canRate("completed"))
        listOf("confirmed", "in_transit", "delivered", "cancelled").forEach { assertFalse(it, BookingRules.canRate(it)) }
    }

    @Test
    fun trackingLinkHiddenOnceDeliveredOrClosed() {
        listOf("confirmed", "awaiting_pickup", "in_transit", "return_required").forEach { assertTrue(it, BookingRules.canShareTracking(it)) }
        listOf("delivered", "completed", "cancelled", "returned", "delivery_failed").forEach { assertFalse(it, BookingRules.canShareTracking(it)) }
    }

    // -- words for codes ----------------------------------------------------------------------------------------

    @Test
    fun cancelReasonsAreTheClientFourWithOtherLast_andUnknownCodesHaveNoWords() {
        assertEquals(listOf("plans_changed", "found_other_option", "driver_unreachable", "other"), BookingRules.CLIENT_CANCEL_REASONS)
        assertEquals("bookingCancel.reason.vehicle_problem", BookingRules.cancelReasonKey("vehicle_problem"))
        assertEquals("bookingCancel.reason.plans_changed", BookingRules.cancelReasonKey("plans_changed"))
        assertNull(BookingRules.cancelReasonKey("listing_changed_by_ops"))
        assertNull(BookingRules.cancelReasonKey(null))
    }

    @Test
    fun cancelRefusalsMapToSentences_andTooLatePointsToSupportNotADispute() {
        assertEquals("bookingCancel.refused.noShowPending", BookingRules.cancelRefusalKey("NO_SHOW_REVIEW_PENDING"))
        assertEquals("bookingCancel.refused.custody", BookingRules.cancelRefusalKey("CUSTODY_REQUIRES_RETURN_FLOW"))
        assertEquals("client.bookingCancel.tooLate", BookingRules.cancelRefusalKey("INVALID_STATE_TRANSITION"))
        assertEquals("bookingCancel.refused.changed", BookingRules.cancelRefusalKey("VERSION_CONFLICT"))
        assertNull(BookingRules.cancelRefusalKey("RATE_LIMITED"))
    }

    @Test
    fun whoCancelled() {
        assertEquals("client.bookingDetail.bySideClient", BookingRules.bySideKey("client"))
        assertEquals("safety.driverTitle", BookingRules.bySideKey("driver"))
        assertEquals("support.operator", BookingRules.bySideKey("operator"))
        assertNull(BookingRules.bySideKey("martian"))
    }

    @Test
    fun amendmentConflictReasonsAndRetryAfter() {
        assertEquals("client.amendment.openExists", BookingRules.amendmentConflictKey("amendment_open"))
        assertEquals("client.amendment.conflict.tripNotPlanned", BookingRules.amendmentConflictKey("trip_not_planned"))
        assertEquals("client.amendment.conflict.bookingChanged", BookingRules.amendmentConflictKey("booking_changed"))
        assertEquals("client.amendment.conflict.expired", BookingRules.amendmentConflictKey("amendment_expired"))
        assertNull(BookingRules.amendmentConflictKey("something_new"))
        assertEquals(12L, BookingRules.retryAfterSeconds(buildJsonObject { put("retry_after_s", 12) }))
        assertEquals(3L, BookingRules.retryAfterSeconds(buildJsonObject { put("retry_after_s", JsonPrimitive("2.2")) }))
        assertEquals(1L, BookingRules.retryAfterSeconds(buildJsonObject { put("retry_after_s", 0) }))
        assertNull(BookingRules.retryAfterSeconds(buildJsonObject { put("limit", 20) }))
    }

    // -- status ladder ------------------------------------------------------------------------------------------

    @Test
    fun ladderMarksDoneCurrentAndTodo_withOnlyTheTimesTheBookingCarries() {
        val confirmed = BookingRules.ladder(booking("confirmed"))
        assertEquals(listOf(StepState.CURRENT, StepState.TODO, StepState.TODO, StepState.TODO, StepState.TODO), confirmed.map { it.state })
        assertEquals("2026-09-29T12:40:16.672402Z", confirmed[0].at)
        assertNull(confirmed[2].at)

        val departed = BookingRules.ladder(booking("in_transit", visibleFrom = "2026-09-29T13:12:00Z"))
        assertEquals(listOf(StepState.DONE, StepState.DONE, StepState.CURRENT, StepState.TODO, StepState.TODO), departed.map { it.state })
        assertEquals("2026-09-29T13:12:00Z", departed[2].at)
        assertNull(departed[1].at) // "Safarga tayyorlanmoqda" has no time on the DTO: none is invented

        val completed = BookingRules.ladder(booking("completed"))
        assertTrue(completed.all { it.state == StepState.DONE })
    }

    @Test
    fun pickedUpSitsOnTheDepartedStep_andCancelledIsOffTheLadder() {
        assertEquals(2, BookingRules.ladderIndex("picked_up"))
        assertEquals(2, BookingRules.ladderIndex("in_transit"))
        assertNull(BookingRules.ladderIndex("cancelled"))
        assertNull(BookingRules.ladderIndex("return_required"))
        val cancelled = BookingRules.ladder(booking("cancelled"))
        assertEquals(StepState.DONE, cancelled[0].state)
        assertTrue(cancelled.drop(1).all { it.state == StepState.TODO })
    }

    // -- plate, phone, reputation -------------------------------------------------------------------------------

    @Test
    fun plateIsMaskedUntilTheServerSendsTheFullNumber() {
        val masked = BookingRules.plate(booking().driver!!.vehicle)
        assertEquals(PlateView("01 A ••• KA", full = false), masked)
        val full = BookingRules.plate(booking(plateNumber = "01 A 452 KA").driver!!.vehicle)
        assertEquals(PlateView("01 A 452 KA", full = true), full)
    }

    @Test
    fun phoneOnlyWhenVisibleAndSent() {
        assertFalse(BookingRules.phone(booking().driver, booking().contact).visible)
        // A number without the visibility flag is not shown (defensive: the flag is the rule).
        val b1 = booking(phone = "+998900001010", phonesVisible = false)
        assertNull(BookingRules.phone(b1.driver, b1.contact).number)
        val b2 = booking(phone = "+998900001010", phonesVisible = true)
        assertEquals("+998900001010", BookingRules.phone(b2.driver, b2.contact).number)
        assertEquals("tel:+998900001010", BookingRules.dialUri("+998 90 000 10 10"))
    }

    @Test
    fun reputationIsARealAverageOrNew_neverAnInventedScore() {
        fun rep(avg: Double?, count: Long) = ReputationDTO(averageRating = avg, completedBookings = 112, completedTrips = 64,
            label = if (count > 0) uz.elchi.app.api.generated.ReputationLabel.RATED else uz.elchi.app.api.generated.ReputationLabel.NEW_VERIFIED,
            ratingCount = count, serviceType = uz.elchi.app.api.generated.ServiceType.PARCEL, userId = "usr_d")
        assertEquals(ReputationLine.Rated("4,7", 38, 112), BookingRules.reputation(rep(4.66, 38), Locale.forLanguageTag("uz")))
        assertEquals(ReputationLine.Rated("4,7", 38, 112), BookingRules.reputation(rep(4.66, 38), Locale.forLanguageTag("ru")))
        assertEquals(ReputationLine.Unrated, BookingRules.reputation(rep(null, 0), Locale.ROOT))
        assertEquals(ReputationLine.Unrated, BookingRules.reputation(rep(4.5, 0), Locale.ROOT))
        assertEquals(ReputationLine.Unrated, BookingRules.reputation(null, Locale.ROOT))
    }

    // -- tracking -----------------------------------------------------------------------------------------------

    @Test
    fun grantTtlChipsAreMinutesWithinTheServerRange() {
        assertEquals(listOf(15, 60, 180, 360, 720, 1440), BookingRules.GRANT_TTL_MINUTES)
        assertEquals(60, BookingRules.GRANT_TTL_DEFAULT)
        assertEquals(15L, BookingRules.grantTtlMinutes(5))
        assertEquals(1440L, BookingRules.grantTtlMinutes(5000))
        assertEquals(180L, BookingRules.grantTtlMinutes(180))
    }

    @Test
    fun relativeGrantUrlsResolveAgainstTheApiOrigin() {
        assertEquals("http://10.0.2.2:8000/api/v2/public/tracking/abc", BookingRules.absoluteUrl("http://10.0.2.2:8000/api/v1", "/api/v2/public/tracking/abc"))
        assertEquals("https://api.elchigo.uz/t/abc", BookingRules.absoluteUrl("https://api.elchigo.uz/api/v1", "t/abc"))
        assertEquals("https://elchigo.uz/t/abc", BookingRules.absoluteUrl("http://10.0.2.2:8000/api/v1", "https://elchigo.uz/t/abc"))
    }

    @Test
    fun socketUrlIsDerivedFromTheApiBase() {
        assertEquals("ws://10.0.2.2:8000/api/v2/ws", trackingSocketUrl("http://10.0.2.2:8000/api/v1"))
        assertEquals("wss://api.elchigo.uz/api/v2/ws", trackingSocketUrl("https://api.elchigo.uz/api/v1"))
        assertEquals("ws://192.168.0.170:8000/api/v2/ws", trackingSocketUrl("http://192.168.0.170:8000/api/v1/"))
    }

    @Test
    fun freshnessIsReAgedOnThePhoneClock_andOnlyEverDowngraded() {
        // Fresh from the server, 10 s old: fresh.
        assertEquals(TrackingFreshness.FRESH, BookingRules.effectiveFreshness(TrackingFreshness.FRESH, point("2026-09-29T12:59:50Z"), now))
        // The server said fresh 45 s ago and the socket went quiet: delayed, then lost.
        assertEquals(TrackingFreshness.DELAYED, BookingRules.effectiveFreshness(TrackingFreshness.FRESH, point("2026-09-29T12:59:15Z"), now))
        assertEquals(TrackingFreshness.LOST, BookingRules.effectiveFreshness(TrackingFreshness.FRESH, point("2026-09-29T12:57:00Z"), now))
        // A phone clock behind the server never upgrades: the server's "lost" stays lost, "delayed" stays delayed.
        assertEquals(TrackingFreshness.LOST, BookingRules.effectiveFreshness(TrackingFreshness.LOST, point("2026-09-29T13:00:05Z"), now))
        assertEquals(TrackingFreshness.DELAYED, BookingRules.effectiveFreshness(TrackingFreshness.DELAYED, point("2026-09-29T12:59:59Z"), now))
        // No point: nothing to claim.
        assertEquals(TrackingFreshness.NO_DATA, BookingRules.effectiveFreshness(TrackingFreshness.FRESH, null, now))
        // Boundaries: 30 s is still fresh, 120 s still delayed. Offsets other than Z are read.
        assertEquals(TrackingFreshness.FRESH, BookingRules.localFreshness(Instant.parse("2026-09-29T12:59:30Z"), now))
        assertEquals(TrackingFreshness.DELAYED, BookingRules.localFreshness(Instant.parse("2026-09-29T12:58:00Z"), now))
        assertEquals(TrackingFreshness.DELAYED, BookingRules.effectiveFreshness(TrackingFreshness.FRESH, point("2026-09-29T17:59:00+05:00"), now))
    }

    // -- chat ---------------------------------------------------------------------------------------------------

    @Test
    fun chatPagesAndPollsMergeByIdOldestFirst() {
        val first = listOf(message("m3", "2026-09-29T12:03:00Z"), message("m2", "2026-09-29T12:02:00Z"))
        val older = listOf(message("m1", "2026-09-29T12:01:00Z"))
        val poll = listOf(message("m4", "2026-09-29T12:04:00Z"), message("m3", "2026-09-29T12:03:00Z", hidden = true))
        val merged = BookingRules.mergeMessages(BookingRules.mergeMessages(BookingRules.mergeMessages(emptyList(), first), older), poll)
        assertEquals(listOf("m1", "m2", "m3", "m4"), merged.map { it.id })
        // The newer copy wins: m3 was hidden by an operator since the first read.
        assertEquals(uz.elchi.app.api.generated.ChatModerationStatus.HIDDEN_BY_STAFF, merged.first { it.id == "m3" }.moderationStatus)
        // Same second: ordered by id, stable.
        val tie = BookingRules.mergeMessages(emptyList(), listOf(message("b", "2026-09-29T12:00:00Z"), message("a", "2026-09-29T12:00:00Z")))
        assertEquals(listOf("a", "b"), tie.map { it.id })
    }

    @Test
    fun newMessagesCountOnlyTheOtherSide() {
        val before = listOf(message("m1", "2026-09-29T12:01:00Z"))
        val after = before + message("m2", "2026-09-29T12:02:00Z", mine = true) + message("m3", "2026-09-29T12:03:00Z")
        assertEquals(1, BookingRules.newFromOthers(before, after))
        assertEquals(0, BookingRules.newFromOthers(after, after))
    }

    @Test
    fun supportMessagesHideStaffNotesAndSortWithAnyOffset() {
        val messages = listOf(
            SupportMessageDTO(author = "operator", createdAt = "2026-09-29T18:06:00+05:00", id = "s2", text = "reply"),
            SupportMessageDTO(author = "me", createdAt = "2026-09-29T13:05:00Z", id = "s1", text = "question"),
            SupportMessageDTO(author = "operator", createdAt = "2026-09-29T13:07:00Z", id = "s3", text = "internal", staffOnly = true),
        )
        assertEquals(listOf("s1", "s2"), BookingRules.supportMessages(messages).map { it.id })
        assertEquals("support.status.waiting", BookingRules.supportStatusKey("waiting"))
    }

    // -- amendments ---------------------------------------------------------------------------------------------

    @Test
    fun amendmentTurnsAndExpiry() {
        val theirs = BookingRules.amendmentActions(amendment(author = "driver"), "confirmed", now)
        assertEquals(AmendmentActions(open = true, canAccept = true, canReject = true, canWithdraw = false), theirs)
        val mine = BookingRules.amendmentActions(amendment(author = "client"), "confirmed", now)
        assertEquals(AmendmentActions(open = true, canAccept = false, canReject = false, canWithdraw = true), mine)
        // Past its 2 h: closed at once, shown as expired before the server's sweep.
        val lapsed = amendment(expires = "2026-09-29T12:59:59Z")
        assertFalse(BookingRules.amendmentActions(lapsed, "confirmed", now).open)
        assertEquals("expired", BookingRules.amendmentDisplayStatus(lapsed, now))
        // A driver's proposal stays "proposed" after boarding, but nothing can be done with it then.
        assertFalse(BookingRules.amendmentActions(amendment(), "awaiting_pickup", now).open)
        assertEquals("proposed", BookingRules.amendmentDisplayStatus(amendment(), now))
        assertFalse(BookingRules.amendmentActions(amendment(status = "accepted"), "confirmed", now).open)
    }

    @Test
    fun oneOpenAmendmentAtATime_andPriceMustChange() {
        assertTrue(BookingRules.hasOpenAmendment(listOf(amendment(status = "withdrawn"), amendment()), "confirmed", now))
        assertFalse(BookingRules.hasOpenAmendment(listOf(amendment(status = "withdrawn")), "confirmed", now))
        assertFalse(BookingRules.hasOpenAmendment(listOf(amendment()), "in_transit", now))
        assertNull(BookingRules.amendmentPrice("120000", 12_000_000))
        assertEquals(13_000_000L, BookingRules.amendmentPrice("130000", 12_000_000))
        assertNull(BookingRules.amendmentPrice("", 12_000_000))
        assertEquals("client.amendment.statusAccepted", BookingRules.amendmentStatusKey("accepted"))
        assertEquals("status.withdrawn", BookingRules.amendmentStatusKey("withdrawn"))
        assertEquals(Tone.OK, BookingRules.amendmentTone("accepted"))
        assertEquals(Tone.WARN, BookingRules.amendmentTone("proposed"))
        assertEquals(Tone.GRAY, BookingRules.amendmentTone("expired"))
    }

    // -- DTO ----------------------------------------------------------------------------------------------------

    @Test
    fun clientBookingDecodesTheStage04Fields() {
        val b = booking(
            status = "cancelled",
            cancelled = """{"by_side":"driver","reason_code":"vehicle_problem","fault_side":null,"at":"2026-09-25T13:40:00Z"}""",
            extra = ""","no_show_review":{"status":"pending","reported_at":"2026-09-25T13:00:00Z"},"parcel_photo":{"file_id":"f1","url":"/api/v1/files/x","content_type":"image/jpeg","expires_at":"2026-09-29T14:00:00Z"}""",
        )
        assertEquals(3L, b.version)
        assertEquals("usr_d", b.driver?.id)
        assertEquals("Chevrolet Cobalt", b.driver?.vehicle?.makeModel)
        assertEquals("driver", b.cancelled?.bySide)
        assertEquals("vehicle_problem", b.cancelled?.reasonCode)
        assertEquals("pending", b.noShowReview?.status)
        assertEquals("/api/v1/files/x", b.parcelPhoto?.url)
        assertEquals("lst_1", b.listingIds?.request)
    }
}
