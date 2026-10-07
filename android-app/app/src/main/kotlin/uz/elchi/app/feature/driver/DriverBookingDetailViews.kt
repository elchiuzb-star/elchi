package uz.elchi.app.feature.driver

import android.content.Intent
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
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.net.toUri
import uz.elchi.app.R
import uz.elchi.app.api.BookingClientDTO
import uz.elchi.app.api.DriverBookingDTO
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.feature.client.BookingRules
import uz.elchi.app.feature.client.BookingViewModel
import uz.elchi.app.feature.client.DottedLine
import uz.elchi.app.feature.client.Fact
import uz.elchi.app.feature.client.OrderRules
import uz.elchi.app.feature.client.TaxiRules
import uz.elchi.app.feature.client.categoryName
import uz.elchi.app.feature.client.displayPhone
import uz.elchi.app.feature.client.pickupWindow
import uz.elchi.app.feature.client.seatsPrice
import uz.elchi.app.feature.client.soum
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
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

// Design 08 "Elchi Haydovchi Bron": the driver's booking detail in the client's design-04 layout - the map hero, the
// sheet card (price, badge, the 5-dot ladder, the two ends, the facts) and the fixed contact bar (call + chat).

private val SHEET_LIFT = 34.dp

/**
 * The 150dp hero: the two ends on a still map (or a drawn route), the whole hero opens "Kuzatuv". The pill reads
 * this phone's own tracker (design 08 2.1): "Jonli" while the service runs and the trip is being sent, "GPS o'chiq"
 * while it runs and nothing is sent, otherwise "Kuzatuv".
 */
@Composable
internal fun DriverBookingHero(booking: BookingClientDTO, chip: HeroChip, onTracking: () -> Unit) {
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
        Box(Modifier.fillMaxSize().clickable(role = Role.Button, onClick = onTracking).semantics { contentDescription = openLabel })
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
            val (dot, label) = when (chip) {
                HeroChip.LIVE -> c.tone(Tone.OK).fg to t(R.string.driver_v3bkg_chipLive)
                HeroChip.GPS_OFF -> Color(0xFFE0A100) to t(R.string.driver_v3bkg_chipGpsOff)
                HeroChip.TRACKING -> Color(0xFF9AA6B5) to t(R.string.bookingDetail_tracking)
            }
            Box(Modifier.size(8.dp).clip(CircleShape).background(dot))
            Text(label, style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold, fontSize = 12.5.sp), color = c.text)
        }
    }
}

/** A picture of a route (start ring, end dot) when no map can be drawn - never a position. */
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
 * The sheet over the hero: "Narx" (no public booking code exists, 2.2 BLOCKED) and "Holat" with the driver's badge,
 * the ladder, "Olib ketish, {date}" / "Taxminan, {date}" with the two ends, then the facts grid (Taksi with the
 * passenger's name; Pochta with the receiver once the trip departed and the photo column) and the driver-only money
 * lines under it (the cash to collect, the commission, Q103).
 */
@Composable
internal fun DriverBookingSheet(booking: BookingClientDTO, view: DriverBookingDTO, s: BookingViewModel.State, ru: Boolean, languageTag: String) {
    val c = Elchi.colors
    val shape = RoundedCornerShape(28.dp)
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
                val price = if (DriverBookingRules.seatsPriced(view)) seatsPrice(view.quantity, view.unitPriceMinor) else soum(view.totalMinor)
                Text(price, style = Elchi.type.section.copy(fontSize = 20.sp, lineHeight = 25.sp), color = c.text, maxLines = 1, softWrap = false)
            }
            Column(Modifier.weight(1f), horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(t(R.string.support_statusLabel), style = Elchi.type.caption, color = c.muted)
                val status = view.serviceStatus
                val colors = c.tone(DriverBookingRules.badgeTone(view.serviceType, status, view.noShowReview))
                Text(
                    tOrNull(DriverBookingRules.badgeKey(view.serviceType, status, review = view.noShowReview)) ?: status,
                    Modifier.clip(RoundedCornerShape(16.dp)).background(colors.bg).padding(horizontal = 14.dp, vertical = 7.dp),
                    style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold, fontSize = 12.5.sp, lineHeight = 16.sp),
                    color = colors.fg,
                    textAlign = TextAlign.End,
                )
            }
        }
        DriverLadder(booking, BookingRules.reviewPending(view.noShowReview))
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    OrderRules.dayMonth(view.pickup.windowStart, languageTag)?.let { t(R.string.driver_v3bkg_pickupOn, "date" to it) } ?: t(R.string.ui_from),
                    style = Elchi.type.caption,
                    color = c.muted,
                )
                Text(OrderRules.shortEnd(view.pickup.point, ru), style = Elchi.type.secondary.copy(fontWeight = FontWeight.Medium, fontSize = 15.sp), color = c.text)
            }
            Column(Modifier.weight(1f), horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(4.dp)) {
                // Only the planned arrival the trip carries - never an ETA.
                Text(
                    OrderRules.dayMonth(view.dropoff.plannedArrivalAt, languageTag)?.let { t(R.string.client_booking_plannedArrival, "date" to it) } ?: t(R.string.ui_to),
                    style = Elchi.type.caption,
                    color = c.muted,
                    textAlign = TextAlign.End,
                )
                Text(OrderRules.shortEnd(view.dropoff.point, ru), style = Elchi.type.secondary.copy(fontWeight = FontWeight.Medium, fontSize = 15.sp), color = c.text, textAlign = TextAlign.End)
            }
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(if (c.isDark) c.line else Color(0xFFEEF1F5)))
        DriverFacts(view, s, ru, languageTag)
        MoneyLines(view)
    }
}

/**
 * The five dots. A cancelled or off-ladder booking: "agreed" done and the second dot crossed (as the client's). While
 * the operator reviews the driver's "Mijoz kelmadi" (Q7) the current dot is crossed (design 08 5.6).
 */
@Composable
private fun DriverLadder(booking: BookingClientDTO, reviewPending: Boolean) {
    val c = Elchi.colors
    val ladder = BookingRules.ladder(booking)
    val step = BookingRules.trackerStep(booking)
    val names = ladder.map { tOrNull(it.key) ?: it.step.name }
    val idle = if (c.isDark) c.field else Color(0xFFEEF1F5)
    val crossAt = when {
        step == null -> 1
        reviewPending -> step
        else -> null
    }
    val doneUpTo = when {
        step == null -> 0
        reviewPending -> step - 1
        else -> step
    }
    val described = if (crossAt != null) {
        names.take(doneUpTo + 1) + (tOrNull(DriverBookingRules.badgeKey(booking.serviceType, booking.serviceStatus, review = booking.noShowReview)) ?: booking.serviceStatus)
    } else {
        names.take(doneUpTo + 1)
    }
    Row(Modifier.fillMaxWidth().semantics { contentDescription = described.joinToString(" · ") }, verticalAlignment = Alignment.CenterVertically) {
        names.forEachIndexed { i, _ ->
            val crossed = i == crossAt
            val done = !crossed && i <= doneUpTo
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
                    .then(if (crossAt == null && i == step) Modifier.border(3.dp, if (c.isDark) Color(0xFF0E3354) else Color(0xFFBFE3FF), CircleShape) else Modifier),
                contentAlignment = Alignment.Center,
            ) {
                ElchiIconView(if (crossed) ElchiIcon.X else ElchiIcon.CHECK, if (crossed) c.tone(Tone.ERR).fg else if (done) c.onBrand else c.placeholder, size = 13.dp)
            }
            if (i < names.lastIndex) {
                DottedLine(if (i < doneUpTo) c.brand else c.outline, Modifier.weight(1f).padding(horizontal = 4.dp))
            }
        }
    }
}

/**
 * Taksi: Qayerdan, Qayerga, Yo'lovchi (the client's name), Yakuniy narx, O'rinlar, Olib ketish. Pochta: Qayerdan,
 * Qayerga, Qabul qiluvchi (the name and phone only after departure, Q142), Yakuniy narx, Miqdor, Og'irlik, Olib
 * ketish, and the 92dp photo column.
 */
@Composable
private fun DriverFacts(view: DriverBookingDTO, s: BookingViewModel.State, ru: Boolean, languageTag: String) {
    val taxi = TaxiRules.isPassenger(view.serviceType)
    val price = soum(view.totalMinor)
    val window = pickupWindow(view.pickup.windowStart, view.pickup.windowEnd, languageTag) ?: "—"
    val facts = buildList {
        add(Triple(t(R.string.ui_from), OrderRules.fullEnd(view.pickup.point, ru), null))
        add(Triple(t(R.string.ui_to), OrderRules.fullEnd(view.dropoff.point, ru), null))
        if (taxi) {
            add(Triple(t(R.string.client_taxi_passenger), view.client?.displayName?.takeIf { it.isNotBlank() } ?: t(R.string.driver_booking_clientFallback), null))
            add(Triple(t(R.string.client_booking_finalPrice), price, null))
            add(Triple(t(R.string.client_taxi_seats), t(R.string.orderForm_review_peopleCount, "count" to view.quantity), t(R.string.orderForm_review_seatNegotiated)))
            add(Triple(t(R.string.driverBid_pickupWindow), window, null))
        } else {
            val receiver = when (val r = DriverBookingRules.receiver(view)) {
                is ReceiverView.Visible -> Triple(t(R.string.driverBooking_receiver), r.name ?: displayPhone(r.phone), if (r.name != null) displayPhone(r.phone) else null)
                is ReceiverView.Hidden -> Triple(t(R.string.driverBooking_receiver), "—", t(R.string.driverBooking_receiverHidden))
            }
            add(receiver)
            add(Triple(t(R.string.client_booking_finalPrice), price, null))
            val category = view.parcelCategory
            val count = t(R.string.tripDetail_seatsValue, "count" to view.quantity)
            add(Triple(t(R.string.amendment_quantityLabel), category?.let { "$count · ${categoryName(it, ru)}" } ?: count, null))
            category?.let { add(Triple(t(R.string.client_booking_weight), t(R.string.client_booking_weightUpTo, "weight" to BookingRules.weightKg(it.maxWeightG)), null)) }
            add(Triple(t(R.string.driverBid_pickupWindow), window, null))
        }
    }
    val photo = !taxi && view.parcelPhoto != null
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            facts.chunked(2).forEach { pair ->
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    pair.forEach { (k, v, d) -> Fact(k, v, Modifier.weight(1f), d) }
                    if (pair.size == 1) Spacer(Modifier.weight(1f))
                }
            }
        }
        if (photo) PhotoColumn(s)
    }
}

/** What the driver collects in cash and what the balance is charged (Q103) - kept under the grid (design 08 2.5). */
@Composable
private fun MoneyLines(view: DriverBookingDTO) {
    val c = Elchi.colors
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(
            t(R.string.driverBooking_fareCash, "amount" to soum(DriverBookingRules.cashToCollectMinor(view))),
            style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold),
            color = c.text,
        )
        DriverBookingRules.commissionMinor(view)?.takeIf { view.serviceStatus != "cancelled" }?.let { commission ->
            val bps = view.fee?.feeBps?.takeIf { it > 0 && view.promo == null }
            val value = if (bps != null) t(R.string.driver_booking_commissionValue, "amount" to soum(commission), "percent" to DriverBookingRules.percent(bps)) else soum(commission)
            Text("${t(R.string.driver_booking_commission)}: $value", style = Elchi.type.caption, color = c.muted)
        }
    }
}

@Composable
private fun PhotoColumn(s: BookingViewModel.State) {
    val c = Elchi.colors
    Box(Modifier.width(92.dp).height(150.dp).clip(RoundedCornerShape(20.dp)).background(c.field), contentAlignment = Alignment.Center) {
        val photo = s.photo
        when {
            photo != null -> {
                val image = remember(photo) { photo.asImageBitmap() }
                Image(image, t(R.string.app_photo_alt), Modifier.fillMaxSize(), contentScale = ContentScale.Crop)
            }
            s.photoFailed -> Text(t(R.string.app_photo_failed), Modifier.padding(6.dp), style = Elchi.type.caption.copy(fontSize = 10.5.sp, lineHeight = 14.sp), color = c.muted, textAlign = TextAlign.Center)
            else -> CircularProgressIndicator(Modifier.size(20.dp), color = c.brand, strokeWidth = 2.dp)
        }
    }
}

/**
 * The fixed contact bar (design 08 2.8): initials, the client's name, "Yo'lovchi · 2 kishi · raqam yopiq" (or the
 * number once it opened), the call button - brand only with a number (Taksi: the client after boarding; Pochta: the
 * receiver after departure; never the sender, Q44/Q142), otherwise grey and its tap says when it opens - and the chat
 * with the local unread count.
 */
@Composable
internal fun ClientContactBar(view: DriverBookingDTO, unread: Int, onChat: () -> Unit, onLockedCall: (String) -> Unit) {
    val c = Elchi.colors
    val context = LocalContext.current
    val activity = LocalActivity.current
    val call = DriverBookingRules.clientCall(view)
    val name = view.client?.displayName?.takeIf { it.isNotBlank() } ?: t(R.string.driver_booking_clientFallback)
    val taxi = view.serviceType != ServiceType.PARCEL
    val phoneText = (call as? ClientCall.Open)?.phone?.let(::displayPhone) ?: t(R.string.driver_v3bkg_phoneClosedShort)
    val sub = if (taxi) {
        listOf(t(R.string.client_taxi_passenger), t(R.string.orderForm_review_peopleCount, "count" to view.quantity), phoneText)
    } else {
        val receiver = (DriverBookingRules.receiver(view) as? ReceiverView.Visible)?.name
        listOfNotNull(t(R.string.driverFeed_modeParcel), receiver?.let { "${t(R.string.driverBooking_receiver)}: $it" }, phoneText)
    }.joinToString(" · ")
    val locked = when (call) {
        is ClientCall.Open -> null
        ClientCall.AfterBoard -> t(R.string.driver_trip_phoneAfterBoard)
        ClientCall.AtDeparture -> t(R.string.client_booking_callLockedParcel)
        ClientCall.Closed -> t(R.string.client_booking_callClosed)
    }
    val callLabel = t(R.string.client_legacy_call)
    val chatLabel = t(R.string.bookingDetail_messages)
    Row(
        Modifier.fillMaxWidth().shadow(12.dp, CircleShape, ambientColor = c.shadow, spotColor = c.shadow).clip(CircleShape).background(c.card).padding(8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Box(Modifier.size(52.dp).clip(CircleShape).background(c.soft), contentAlignment = Alignment.Center) {
            Text(BookingRules.initials(name), style = Elchi.type.bodyStrong.copy(fontSize = 16.sp), color = c.softText)
        }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
            Text(name, style = Elchi.type.body.copy(fontWeight = FontWeight.Medium), color = c.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(sub, style = Elchi.type.caption, color = c.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        val number = (call as? ClientCall.Open)?.phone
        Box(
            Modifier.size(52.dp).clip(CircleShape).background(if (number != null) c.brand else c.field)
                .clickable(role = Role.Button) {
                    if (number != null) {
                        val dial = Intent(Intent.ACTION_DIAL, BookingRules.dialUri(number).toUri())
                        activity?.startActivity(dial) ?: context.startActivity(dial.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                    } else {
                        locked?.let(onLockedCall)
                    }
                }
                .semantics { contentDescription = if (locked == null) callLabel else "$callLabel. $locked" },
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
