package uz.elchi.app.feature.client

import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import androidx.core.net.toUri
import androidx.activity.compose.LocalActivity
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentHeight
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.layout
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import uz.elchi.app.R
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.BookingClientDTO
import uz.elchi.app.api.generated.BookingPromoClientDTO
import uz.elchi.app.api.generated.ContactDetails
import uz.elchi.app.api.generated.ReputationDTO
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.CardHeader
import uz.elchi.app.ui.components.CardRow
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiIconView
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.map.ElchiMap
import uz.elchi.app.ui.map.GeoPoint
import uz.elchi.app.ui.map.MapFocus
import uz.elchi.app.ui.map.MapKitSupport
import uz.elchi.app.ui.map.MapMarker
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone
import java.util.Locale

// Design 04 "Elchi Bron" - the booking detail's own blocks: the map hero, the sheet card, the notices, the driver
// card, the star card and the fixed driver bar. The commands stay in BookingScreens.kt.

private val SHEET_LIFT = 34.dp

/**
 * The 150dp hero (design `goTrack` button): the two ends on a still map with a straight line (no road geometry is
 * sent, 1.1 BLOCKED), or a drawn route when there is no usable map or no coordinates. The whole hero opens the
 * tracking screen; the pill's dot is green only while the service runs - a status, never a GPS claim.
 */
@Composable
internal fun BookingHero(booking: BookingClientDTO, onTracking: () -> Unit) {
    val c = Elchi.colors
    var usable by remember { mutableStateOf(MapKitSupport.likelyAvailable) }
    val markers = remember(booking.id) {
        listOfNotNull(
            booking.pickup.point?.let { MapMarker(GeoPoint(it.lat, it.lng), MapMarker.Kind.ORIGIN) },
            booking.dropoff.point?.let { MapMarker(GeoPoint(it.lat, it.lng), MapMarker.Kind.DESTINATION) },
        )
    }
    val openLabel = t(R.string.client_booking_openTracking)
    Box(Modifier.fillMaxWidth().height(150.dp).clip(RoundedCornerShape(24.dp)).background(if (c.isDark) c.field else Color(0xFFE9EDF1))) {
        if (usable && markers.size == 2) {
            val route = remember(markers) { listOf(markers[0].point, markers[1].point) }
            val focus = remember(markers) { MapFocus.Fit(markers.map { it.point }) }
            ElchiMap(
                Modifier.fillMaxSize(),
                markers = markers,
                route = route,
                focus = focus,
                padding = PaddingValues(start = 28.dp, end = 28.dp, top = 20.dp, bottom = 48.dp),
                logoBottom = 40.dp,
                interactive = false,
                onAvailability = { usable = it },
                placeholderTitle = t(R.string.client_map_unavailable),
            )
        } else {
            DrawnRoute(Modifier.fillMaxSize().padding(bottom = SHEET_LIFT))
        }
        // One tap target over the still map: the map itself never takes the touch.
        Box(
            Modifier.fillMaxSize().clickable(role = Role.Button, onClick = onTracking).semantics { contentDescription = openLabel },
        )
        Row(
            Modifier
                .align(Alignment.BottomEnd)
                .padding(end = 12.dp, bottom = SHEET_LIFT + 12.dp)
                .shadow(8.dp, CircleShape, ambientColor = c.shadow, spotColor = c.shadow)
                .clip(CircleShape)
                .background(c.card)
                .padding(horizontal = 12.dp, vertical = 7.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            val running = BookingRules.serviceRunning(booking.serviceStatus)
            Box(Modifier.size(8.dp).clip(CircleShape).background(if (running) c.tone(Tone.OK).fg else Color(0xFF9AA6B5)))
            Text(t(R.string.bookingDetail_tracking), style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold, fontSize = 12.5.sp), color = c.text)
        }
    }
}

/** The design's overlay curve (start ring, end dot) when no map can be drawn: a picture of a route, not a position. */
@Composable
private fun DrawnRoute(modifier: Modifier) {
    val c = Elchi.colors
    val brand = c.brand
    val pin = c.pin
    val card = c.card
    Canvas(modifier) {
        val w = size.width
        val h = size.height
        val start = Offset(w * 0.11f, h * 0.78f)
        val end = Offset(w * 0.89f, h * 0.24f)
        val path = Path().apply {
            moveTo(start.x, start.y)
            cubicTo(w * 0.31f, h * 0.68f, w * 0.42f, h * 0.42f, w * 0.59f, h * 0.37f)
            quadraticTo(w * 0.80f, h * 0.28f, end.x, end.y)
        }
        drawPath(path, brand, style = Stroke(width = 5.dp.toPx(), cap = StrokeCap.Round))
        drawCircle(card, 9.dp.toPx(), start)
        drawCircle(brand, 9.dp.toPx(), start, style = Stroke(4.dp.toPx()))
        drawCircle(pin, 10.dp.toPx(), end)
    }
}

/**
 * The sheet card over the hero (design `margin-top:-34px`): the price and "Holat" with the badge (no public booking
 * code exists, 1.2 BLOCKED), the 5-dot tracker, created / planned arrival with the places, then the facts grid
 * (Pochta with the 92dp photo column) and the fare note the design leaves unbound (kept, 1.9).
 */
@Composable
internal fun BookingSheet(booking: BookingClientDTO, s: BookingViewModel.State, ru: Boolean, languageTag: String) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(28.dp)
    val taxi = TaxiRules.isPassenger(booking.serviceType)
    Column(
        Modifier
            .fillMaxWidth()
            .layout { measurable, constraints ->
                val placeable = measurable.measure(constraints)
                val lift = SHEET_LIFT.roundToPx()
                layout(placeable.width, placeable.height - lift) { placeable.place(0, -lift) }
            }
            .shadow(12.dp, shape, ambientColor = c.shadow, spotColor = c.shadow)
            .clip(shape)
            .background(c.card)
            .padding(start = 18.dp, end = 18.dp, top = 20.dp, bottom = 20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Box(Modifier.fillMaxWidth()) {
            Box(Modifier.align(Alignment.TopCenter).offset(y = (-12).dp).width(44.dp).height(5.dp).clip(CircleShape).background(c.outline))
        }
        Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(t(R.string.common_price), style = Elchi.type.caption, color = c.muted)
                // Q103: with a discount the client hands over the cash due. Taksi: "2 × 150 000 so'm".
                val price = if (taxi && booking.promo == null) seatsPrice(booking.quantity, booking.unitPriceMinor) else soum(booking.promo?.cashDueMinor ?: booking.totalMinor)
                Text(price, style = Elchi.type.section.copy(fontSize = 20.sp, lineHeight = 25.sp), color = c.text, maxLines = 1, softWrap = false)
            }
            // The badge takes what is left and wraps ("Operator yetkazilganini qayd etdi"); the price never breaks.
            Column(Modifier.weight(1f), horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(t(R.string.support_statusLabel), style = Elchi.type.caption, color = c.muted)
                val colors = c.tone(OrderRules.clientBookingTone(booking.serviceType, booking.serviceStatus))
                Text(
                    tOrNull(OrderRules.bookingStatusKey(booking.serviceType, booking.serviceStatus)) ?: booking.serviceStatus,
                    Modifier.clip(RoundedCornerShape(16.dp)).background(colors.bg).padding(horizontal = 14.dp, vertical = 7.dp),
                    style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold, fontSize = 12.5.sp, lineHeight = 16.sp),
                    color = colors.fg,
                    textAlign = TextAlign.End,
                )
            }
        }
        BookingTracker(booking)
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    OrderRules.dayMonth(booking.createdAt, languageTag)?.let { t(R.string.client_booking_createdAt, "date" to it) } ?: t(R.string.ui_from),
                    style = Elchi.type.caption,
                    color = c.muted,
                )
                Text(OrderRules.shortEnd(booking.pickup.point, ru), style = Elchi.type.secondary.copy(fontWeight = FontWeight.Medium, fontSize = 15.sp), color = c.text)
            }
            Column(Modifier.weight(1f), horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(4.dp)) {
                // Only the planned arrival the trip carries - never an ETA (the pilot has none).
                Text(
                    OrderRules.dayMonth(booking.dropoff.plannedArrivalAt, languageTag)?.let { t(R.string.client_booking_plannedArrival, "date" to it) } ?: t(R.string.ui_to),
                    style = Elchi.type.caption,
                    color = c.muted,
                    textAlign = TextAlign.End,
                )
                Text(OrderRules.shortEnd(booking.dropoff.point, ru), style = Elchi.type.secondary.copy(fontWeight = FontWeight.Medium, fontSize = 15.sp), color = c.text, textAlign = TextAlign.End)
            }
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(if (c.isDark) c.line else Color(0xFFEEF1F5)))
        BookingFacts(booking, s, ru, languageTag)
        Text(t(R.string.bookingDetail_fareNote), style = Elchi.type.caption, color = c.muted)
    }
}

/**
 * Five dots joined by dotted lines, the rungs of the tracking ladder; the current one ringed. Cancelled (or any
 * off-ladder status): "agreed" done, the second dot a red cross (design `stepNodes`).
 */
@Composable
private fun BookingTracker(booking: BookingClientDTO) {
    val c = Elchi.colors
    val ladder = BookingRules.ladder(booking)
    val step = BookingRules.trackerStep(booking)
    val names = ladder.map { tOrNull(it.key) ?: it.step.name }
    val idle = if (c.isDark) c.field else Color(0xFFEEF1F5)
    val stopped = step == null
    val described = if (stopped) listOf(names.first(), tOrNull(OrderRules.bookingStatusKey(booking.serviceType, booking.serviceStatus)) ?: booking.serviceStatus) else names.take(step + 1)
    Row(
        Modifier.fillMaxWidth().semantics { contentDescription = described.joinToString(" · ") },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        names.forEachIndexed { i, _ ->
            val done = if (stopped) i == 0 else i <= step
            val crossed = stopped && i == 1
            Box(
                Modifier
                    .size(26.dp)
                    .clip(CircleShape)
                    .background(
                        when {
                            done -> c.brand
                            crossed -> c.tone(Tone.ERR).bg
                            else -> idle
                        },
                    )
                    .then(if (!stopped && i == step) Modifier.border(3.dp, if (c.isDark) Color(0xFF0E3354) else Color(0xFFBFE3FF), CircleShape) else Modifier),
                contentAlignment = Alignment.Center,
            ) {
                ElchiIconView(if (crossed) ElchiIcon.X else ElchiIcon.CHECK, if (crossed) c.tone(Tone.ERR).fg else if (done) c.onBrand else c.placeholder, size = 13.dp)
            }
            if (i < names.lastIndex) {
                val reached = if (stopped) false else i < step
                DottedLine(if (reached) c.brand else c.outline, Modifier.weight(1f).padding(horizontal = 4.dp))
            }
        }
    }
}

/**
 * The design's facts, two columns. Pochta: Qayerdan, Qayerga, Qabul qiluvchi (name; the phone under it), Yakuniy narx,
 * Miqdor, Og'irlik (+ the photo column) and the pickup window. Taksi: Qayerdan, Qayerga, Yakuniy narx, O'rinlar,
 * Olib ketish - the passenger's name does not exist on the booking (only counts, 1.5 BLOCKED).
 */
@Composable
private fun BookingFacts(booking: BookingClientDTO, s: BookingViewModel.State, ru: Boolean, languageTag: String) {
    val taxi = TaxiRules.isPassenger(booking.serviceType)
    val cash = soum(booking.promo?.cashDueMinor ?: booking.totalMinor)
    val window = pickupWindow(booking.pickup.windowStart, booking.pickup.windowEnd, languageTag) ?: "—"
    val facts = buildList {
        add(Triple(t(R.string.ui_from), OrderRules.fullEnd(booking.pickup.point, ru), null))
        add(Triple(t(R.string.ui_to), OrderRules.fullEnd(booking.dropoff.point, ru), null))
        if (taxi) {
            add(Triple(t(R.string.client_booking_finalPrice), cash, null))
            add(Triple(t(R.string.client_taxi_seats), t(R.string.orderForm_review_peopleCount, "count" to booking.quantity), t(R.string.orderForm_review_seatNegotiated)))
            add(Triple(t(R.string.driverBid_pickupWindow), window, null))
        } else {
            val receiver: ContactDetails? = s.receiver
            add(Triple(t(R.string.driverBooking_receiver), receiver?.name?.trim()?.takeIf { it.isNotEmpty() } ?: "—", receiver?.phone?.takeIf { it.isNotBlank() }?.let(::displayPhone)))
            add(Triple(t(R.string.client_booking_finalPrice), cash, null))
            val category = booking.parcelCategory
            val count = t(R.string.tripDetail_seatsValue, "count" to booking.quantity)
            add(Triple(t(R.string.amendment_quantityLabel), category?.let { "$count · ${categoryName(it, ru)}" } ?: count, null))
            category?.let { add(Triple(t(R.string.client_booking_weight), t(R.string.client_booking_weightUpTo, "weight" to BookingRules.weightKg(it.maxWeightG)), null)) }
            add(Triple(t(R.string.driverBid_pickupWindow), window, null))
        }
    }
    val photo = !taxi && booking.parcelPhoto != null
    val rows = facts.chunked(2)
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            rows.forEach { pair ->
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    pair.forEach { (k, v, d) -> Fact(k, v, Modifier.weight(1f), d) }
                    if (pair.size == 1) Spacer(Modifier.weight(1f))
                }
            }
        }
        if (photo) BookingPhotoColumn(s)
    }
}

/** `29 sen, 09:00–18:00` (Tashkent); the full dates when the window spans days. */
internal fun pickupWindow(start: String?, end: String?, languageTag: String): String? {
    val s = OrderRules.tashkent(start) ?: return null
    val e = OrderRules.tashkent(end)
    val day = OrderRules.dayMonth(start, languageTag) ?: return null
    val hm = java.time.format.DateTimeFormatter.ofPattern("HH:mm")
    return when {
        e == null -> "$day, ${s.format(hm)}"
        e.toLocalDate() == s.toLocalDate() -> "$day, ${s.format(hm)}–${e.format(hm)}"
        else -> OrderRules.windowText(start, end)
    }
}

@Composable
private fun BookingPhotoColumn(s: BookingViewModel.State) {
    val c = Elchi.colors
    Box(Modifier.width(92.dp).height(150.dp).clip(RoundedCornerShape(20.dp)).background(c.field), contentAlignment = Alignment.Center) {
        val photo = s.photo
        when {
            photo != null -> {
                val image = remember(photo) { photo.asImageBitmap() }
                Image(image, t(R.string.app_photo_alt), Modifier.fillMaxSize(), contentScale = ContentScale.Crop)
            }
            s.photoFailed -> Text(t(R.string.app_photo_failed), Modifier.padding(6.dp), style = Elchi.type.caption.copy(fontSize = 10.5.sp, lineHeight = 14.sp), color = c.muted, textAlign = TextAlign.Center)
            else -> androidx.compose.material3.CircularProgressIndicator(Modifier.size(20.dp), color = c.brand, strokeWidth = 2.dp)
        }
    }
}

/** The design's notices under the card: cancelled (who, when, why), on the way, delivered / arrived, blocked. */
@Composable
internal fun BookingStatusNotices(booking: BookingClientDTO, s: BookingViewModel.State) {
    when (BookingRules.statusNotice(booking.serviceType, booking.serviceStatus)) {
        StatusNoticeKind.CANCELLED -> {
            val c = booking.cancelled
            val parts = listOfNotNull(
                c?.bySide?.let { BookingRules.bySideKey(it) }?.let { tOrNull(it) },
                OrderRules.tashkent(c?.at)?.let { ParcelRules.displayShort(it) },
                BookingRules.cancelReasonKey(c?.reasonCode)?.let { tOrNull(it) },
            )
            StatusNotice(listOf(t(R.string.bookingCancel_cancelledBy), parts.joinToString(" · ")).filter { it.isNotEmpty() }.joinToString(": "), Tone.ERR)
        }
        StatusNoticeKind.ON_THE_WAY -> StatusNotice(t(R.string.client_booking_noticeOnTheWay), Tone.BLUE)
        StatusNoticeKind.DELIVERED -> StatusNotice(t(R.string.client_booking_noticeDelivered), Tone.OK)
        StatusNoticeKind.ARRIVED -> StatusNotice(t(R.string.client_booking_noticeArrived), Tone.OK)
        null -> Unit
    }
    if (BookingRules.reviewPending(booking.noShowReview)) StatusNotice(t(R.string.bookingCancel_reviewPending), Tone.WARN)
    if (s.blocked) StatusNotice(t(R.string.client_booking_driverBlocked), Tone.WARN)
}

/**
 * The compact "Haydovchi va avtomobil" card the design leaves unbound (`driverRows`, kept by decision 1.9): the car,
 * the plate (masked until Q64 opens it) and the phone (Q44/Q142: only while the server shows it; "Yopilgan" once the
 * booking is over and the phones are hidden again). Name and reputation are on the driver bar.
 */
@Composable
internal fun DriverInfoCard(booking: BookingClientDTO) {
    val driver = booking.driver ?: return
    val phone = BookingRules.phone(driver, booking.contact)
    val plate = BookingRules.plate(driver.vehicle)
    val dial = rememberDial()
    ElchiCard {
        CardHeader(t(R.string.client_bookingDetail_driverCard), badge = if (phone.visible) t(R.string.client_bookingDetail_contactOpen) else null, badgeTone = Tone.OK)
        val vehicle = driver.vehicle
        CardRow(
            t(R.string.tripDetail_vehicle),
            listOf(vehicle.makeModel, vehicle.color).filter { it.isNotBlank() }.joinToString(" · "),
            first = true,
            detail = t(R.string.app_rivalBoard_vehicleSeats, "vehicle" to (tOrNull("vehicleClass.${vehicle.vehicleClass}") ?: vehicle.vehicleClass), "seats" to vehicle.seatCapacity),
        )
        CardRow(
            t(R.string.driverProfileForm_plateNumber),
            plate.text,
            // Q75: a cancelled booking never gets the full plate - no promise of it then.
            detail = when {
                plate.full -> t(R.string.client_bookingDetail_plateOpen)
                BookingRules.isTerminal(booking.serviceStatus) -> null
                else -> t(R.string.client_bookingDetail_plateLater)
            },
        )
        val number = phone.number
        when {
            number != null -> CardRow(t(R.string.driverBooking_phone), displayPhone(number), trailing = t(R.string.client_bookingDetail_call), onTrailing = { dial(number) })
            BookingRules.callLock(booking.serviceType, booking.serviceStatus) == CallLock.CLOSED ->
                CardRow(t(R.string.driverBooking_phone), t(R.string.client_booking_phoneClosed), muted = true)
            else -> {
                val later = if (TaxiRules.isPassenger(booking.serviceType)) R.string.driverBooking_phoneHidden else R.string.client_bookingDetail_phoneLater
                CardRow(t(R.string.driverBooking_phone), t(later), detail = t(R.string.client_bookingDetail_phoneChatOnly), muted = true)
            }
        }
    }
}

/** The phone's dialer with the number filled in (never a call placed by the app). */
@Composable
private fun rememberDial(): (String) -> Unit {
    val context = LocalContext.current
    val activity = LocalActivity.current
    return { number ->
        val dial = Intent(Intent.ACTION_DIAL, BookingRules.dialUri(number).toUri())
        activity?.startActivity(dial) ?: context.startActivity(dial.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }
}

/** "Bonus bilan hisob" - only on a discounted booking (Q103: never a fake discount, 1.7 BLOCKED otherwise). */
@Composable
internal fun BookingPromoBlock(promo: BookingPromoClientDTO) {
    val c = Elchi.colors
    val ok = c.tone(Tone.OK).fg
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(if (c.isDark) c.field else Color(0xFFF3F5F8)).border(1.dp, c.line, RoundedCornerShape(16.dp))
            .padding(horizontal = 14.dp, vertical = 6.dp),
    ) {
        Text(t(R.string.promoScreen_moneyTitle), Modifier.padding(top = 8.dp, bottom = 2.dp), style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold), color = c.text)
        MoneyLine(t(R.string.promo_line_agreedPrice), soum(promo.fareMinor), c.text)
        MoneyLine(t(R.string.promo_line_bonusDiscount), "−${soum(promo.passengerDiscountMinor)}", ok)
        Box(Modifier.fillMaxWidth().height(1.dp).background(c.line))
        MoneyLine(t(R.string.client_booking_finalPrice), soum(promo.cashDueMinor), c.text, strong = true)
    }
    Text(t(R.string.promoScreen_clientCovers), style = Elchi.type.caption, color = c.muted)
}

@Composable
private fun MoneyLine(key: String, value: String, color: Color, strong: Boolean = false) {
    val style = Elchi.type.label.copy(fontWeight = if (strong) FontWeight.SemiBold else FontWeight.Normal)
    Row(Modifier.fillMaxWidth().padding(vertical = 7.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(key, Modifier.weight(1f), style = style, color = color)
        Text(value, style = style, color = color, maxLines = 1)
    }
}

/**
 * The tracking link made with the bar's share icon, while this screen lives (the server returns the URL once):
 * when it ends, and "Havolani bekor qilish" (the design leaves `revokeTrack` unbound; it stays reachable).
 */
@Composable
internal fun ActiveShareCard(vm: BookingViewModel, s: BookingViewModel.State) {
    val grant = s.grant ?: return
    val c = Elchi.colors
    ElchiCard(padding = PaddingValues(horizontal = 16.dp, vertical = 12.dp)) {
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(t(R.string.tracking_shareTitle), style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold), color = c.text)
            s.grantUrl?.let { Text(it, style = Elchi.type.caption.copy(fontFamily = FontFamily.Monospace), color = c.muted, maxLines = 1, overflow = TextOverflow.Ellipsis) }
            Text(t(R.string.trackingShare_validUntil, "time" to (OrderRules.dayTime(grant.expiresAt) ?: grant.expiresAt)), style = Elchi.type.caption, color = c.muted)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ElchiButton(t(R.string.client_share_send), vm::shareTracking, Modifier.weight(1f).height(44.dp), ButtonVariant.SOFT, ButtonSize.MEDIUM, icon = ElchiIcon.SHARE, horizontalPadding = 10.dp)
                ElchiButton(t(R.string.client_share_revoke), vm::revokeGrant, Modifier.weight(1f).height(44.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM, enabled = !s.granting, horizontalPadding = 10.dp, maxLines = 2)
            }
        }
    }
}

/** "Haydovchini baholang" with five small stars (design `quickStars`): a tap opens the rating with those stars. */
@Composable
internal fun RatingStarCard(onRate: (Int) -> Unit) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(20.dp)
    Row(
        Modifier.fillMaxWidth().shadow(12.dp, shape, ambientColor = c.shadow, spotColor = c.shadow).clip(shape).background(c.card)
            .padding(start = 16.dp, end = 10.dp, top = 10.dp, bottom = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text(t(R.string.rating_titleDriver), Modifier.weight(1f), style = Elchi.type.secondary.copy(fontWeight = FontWeight.Medium), color = c.text)
        Row {
            (1..5).forEach { n ->
                val label = t(R.string.bookingRating_starsAria, "value" to n)
                Box(
                    Modifier.size(width = 32.dp, height = 44.dp).clickable(role = Role.Button) { onRate(n) }.semantics { contentDescription = label },
                    contentAlignment = Alignment.Center,
                ) { SmallStar(if (c.isDark) c.outline else Color(0xFFD5DCE5)) }
            }
        }
    }
}

@Composable
private fun SmallStar(color: Color) {
    Canvas(Modifier.size(26.dp)) {
        val cx = size.width / 2
        val cy = size.height / 2
        val outer = size.minDimension / 2
        val inner = outer * 0.45f
        val path = Path()
        for (k in 0 until 10) {
            val r = if (k % 2 == 0) outer else inner
            val a = Math.toRadians(-90.0 + k * 36.0)
            val x = cx + (r * kotlin.math.cos(a)).toFloat()
            val y = cy + (r * kotlin.math.sin(a)).toFloat() + outer * 0.06f
            if (k == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }
        path.close()
        drawPath(path, color)
    }
}

/** "Xavfsizlik haqida xabar berish" as the design's row card: shield in a circle, chevron. Last, apart from support. */
@Composable
internal fun SafetyRowCard(onClick: () -> Unit) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(22.dp)
    Row(
        Modifier.fillMaxWidth().shadow(12.dp, shape, ambientColor = c.shadow, spotColor = c.shadow).clip(shape).background(c.card)
            .clickable(role = Role.Button, onClick = onClick).padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Box(Modifier.size(38.dp).clip(CircleShape).background(if (c.isDark) c.field else Color(0xFFEEF4FA)), contentAlignment = Alignment.Center) {
            ElchiIconView(ElchiIcon.SHIELD, c.accentText, size = 18.dp)
        }
        Text(t(R.string.safety_menuTitle), Modifier.weight(1f), style = Elchi.type.secondary.copy(fontWeight = FontWeight.SemiBold), color = c.text)
        ElchiIconView(ElchiIcon.CHEV_R, c.placeholder, size = 16.dp)
    }
}

/**
 * The fixed driver bar (design 1.8): initials, first name, "Haydovchi · ★ 4,7 · Cobalt 01 A ••• KA", the call button
 * (blue only while the server shows the phone; otherwise grey and its tap says when it opens) and the chat with the
 * local unread count.
 */
@Composable
internal fun DriverBar(booking: BookingClientDTO, reputation: ReputationDTO?, unread: Int, languageTag: String, onChat: () -> Unit, onLockedCall: (String) -> Unit) {
    val driver = booking.driver ?: return
    val c = Elchi.colors
    val phone = BookingRules.phone(driver, booking.contact)
    val dial = rememberDial()
    val plate = BookingRules.plate(driver.vehicle).text
    val rating = when (val line = BookingRules.reputation(reputation, Locale.forLanguageTag(languageTag))) {
        is ReputationLine.Rated -> "★ ${line.average}"
        ReputationLine.Unrated -> if (reputation != null) t(R.string.ratingBucket_new_verified) else null
    }
    val sub = listOfNotNull(t(R.string.safety_driverTitle), rating, "${driver.vehicle.makeModel} $plate".trim()).joinToString(" · ")
    val locked = when (BookingRules.callLock(booking.serviceType, booking.serviceStatus)) {
        CallLock.CLOSED -> t(R.string.client_booking_callClosed)
        CallLock.TAXI -> t(R.string.client_booking_callLockedTaxi)
        CallLock.PARCEL -> t(R.string.client_booking_callLockedParcel)
    }
    val callLabel = t(R.string.client_legacy_call)
    val chatLabel = t(R.string.bookingDetail_messages)
    Row(
        Modifier.fillMaxWidth().shadow(12.dp, CircleShape, ambientColor = c.shadow, spotColor = c.shadow).clip(CircleShape).background(c.card).padding(8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Box(Modifier.size(52.dp).clip(CircleShape).background(c.soft), contentAlignment = Alignment.Center) {
            Text(BookingRules.initials(driver.displayName), style = Elchi.type.bodyStrong.copy(fontSize = 16.sp), color = c.softText)
        }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
            Text(driver.displayName, style = Elchi.type.body.copy(fontWeight = FontWeight.Medium), color = c.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(sub, style = Elchi.type.caption, color = c.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        val number = phone.number
        Box(
            Modifier.size(52.dp).clip(CircleShape).background(if (number != null) c.brand else c.field)
                .clickable(role = Role.Button) { if (number != null) dial(number) else onLockedCall(locked) }
                .semantics { contentDescription = if (number != null) callLabel else "$callLabel. $locked" },
            contentAlignment = Alignment.Center,
        ) { ElchiIconView(ElchiIcon.PHONE, if (number != null) c.onBrand else c.placeholder, size = 22.dp) }
        Box(Modifier.size(52.dp)) {
            Box(
                Modifier.fillMaxSize().clip(CircleShape).background(c.card).border(1.dp, c.line, CircleShape)
                    .clickable(role = Role.Button, onClick = onChat)
                    .semantics { contentDescription = if (unread > 0) "$chatLabel ($unread)" else chatLabel },
                contentAlignment = Alignment.Center,
            ) { ElchiIconView(ElchiIcon.CHAT, c.text, size = 22.dp) }
            if (unread > 0) {
                Text(
                    unread.toString(),
                    Modifier.align(Alignment.TopEnd).offset(x = 2.dp, y = (-2).dp).defaultMinSize(minWidth = 20.dp).height(20.dp)
                        .clip(CircleShape).background(c.card).padding(2.dp).clip(CircleShape).background(Color(0xFFE0413A))
                        .padding(horizontal = 4.dp).wrapContentHeight(Alignment.CenterVertically),
                    style = Elchi.type.badge.copy(fontWeight = FontWeight.Bold, fontSize = 10.sp, lineHeight = 12.sp),
                    color = Color.White,
                    textAlign = TextAlign.Center,
                    maxLines = 1,
                )
            }
        }
    }
}

// -- toasts ---------------------------------------------------------------------------------------------------------

/**
 * Design 04 says the outcome of a command as a toast ("Bron bekor qilindi · ikkinchi tomonga xabar yuborildi",
 * "Rahmat! Bahoingiz yuborildi", ...). The client's flow has the toast host; the driver's screens keep their banner.
 */
@Composable
internal fun BookingNoticeToast(vm: BookingViewModel, s: BookingViewModel.State) {
    if (vm.side != BookingSide.CLIENT) return
    val toast = LocalFlowToast.current
    val notice = s.notice
    val text = notice?.let { clientNoticeText(it, s.noticePrice) }
    LaunchedEffect(notice) {
        if (notice != null && text != null) {
            toast.show(text)
            vm.consumeNoticeOnly()
        }
    }
    LaunchedEffect(s.warnings) {
        if (s.warnings.isNotEmpty()) {
            delay(NOTICE_SHOWN_MS)
            vm.consumeNotice()
        }
    }
}

@Composable
private fun clientNoticeText(notice: BookingNotice, price: Long?): String = when (notice) {
    BookingNotice.DRIVER_CHOSEN -> t(R.string.listingBids_driverChosen)
    BookingNotice.CANCELLED -> t(R.string.client_booking_cancelledToast)
    BookingNotice.AMENDMENT_SENT -> t(R.string.amendment_sent)
    BookingNotice.AMENDMENT_ACCEPTED -> price?.let { t(R.string.client_booking_amendAcceptedPrice, "price" to soum(it)) } ?: t(R.string.amendment_accepted)
    BookingNotice.AMENDMENT_REJECTED -> t(R.string.proposal_rejected)
    BookingNotice.AMENDMENT_WITHDRAWN -> t(R.string.amendment_withdrawn)
    BookingNotice.RATED -> t(R.string.client_booking_rateThanks)
    BookingNotice.ARRIVED -> t(R.string.driver_booking_arrived)
    BookingNotice.COMPLETED -> t(R.string.client_taxi_completed)
    BookingNotice.STATUS_UPDATED -> t(R.string.driverBooking_statusUpdated)
    BookingNotice.NO_SHOW_SENT -> t(R.string.driver_noShow_sent)
    BookingNotice.CASH_RECORDED -> t(R.string.driverBooking_cashRecorded)
    BookingNotice.CASH_ACKNOWLEDGED -> t(R.string.client_booking_cashConfirmed)
    BookingNotice.CASH_CONTESTED -> t(R.string.client_booking_cashContestSent)
}

/**
 * The bar's share icon: the phone's share sheet with the bare link (title "Elchi kuzatuv"); without one the link is
 * copied ("Kuzatuv havolasi nusxalandi"). Refusals (too early, finished) are toasts.
 */
@Composable
internal fun ShareTrackingEffects(vm: BookingViewModel, s: BookingViewModel.State) {
    val context = LocalContext.current
    val activity = LocalActivity.current
    val toast = LocalFlowToast.current
    val title = t(R.string.client_booking_shareSheetTitle)
    val copied = t(R.string.client_booking_trackingLinkCopied)
    LaunchedEffect(s.shareNow) {
        val url = s.shareNow ?: return@LaunchedEffect
        vm.consumeShare()
        val chooser = Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, url), title)
        try {
            activity?.startActivity(chooser) ?: context.startActivity(chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (e: ActivityNotFoundException) {
            (context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("ELCHI", url))
            toast.show(copied)
        }
    }
    val error = s.shareError?.let { grantErrorText(it) }
    LaunchedEffect(s.shareError) {
        if (error != null) {
            toast.show(error)
            vm.consumeShare()
        }
    }
}

/** grant_too_early says from when a link can be made; a finished booking says the window is closed. */
@Composable
internal fun grantErrorText(error: Throwable): String {
    val api = error as? ApiException ?: return errorText(error)
    val reason = BookingRules.detailsReason(api.details)
    if (reason == "grant_too_early") {
        val from = BookingRules.detailsString(api.details, "issuable_from")?.takeIf { OrderRules.parseInstant(it) != null }
        return if (from != null) t(R.string.client_trackingShare_tooEarly, "time" to (OrderRules.dayTime(from) ?: from)) else t(R.string.client_trackingShare_tooEarlyNoTime)
    }
    if (api.code == "INVALID_STATE_TRANSITION") return t(R.string.client_trackingShare_finished)
    if (api.code == "FORBIDDEN" && reason == "booking_owner_only") return t(R.string.client_trackingShare_ownerOnly)
    return errorText(error)
}
