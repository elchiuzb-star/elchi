package uz.elchi.app.feature.driver

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.elchi.app.R
import uz.elchi.app.api.generated.ActorSide
import uz.elchi.app.api.generated.ApiWarning
import uz.elchi.app.api.generated.ListingOfferDTO
import uz.elchi.app.api.generated.ListingPublicDTO
import uz.elchi.app.api.generated.ListingStatus
import uz.elchi.app.api.generated.PriceBasis
import uz.elchi.app.api.generated.ProposalThreadDTO
import uz.elchi.app.api.generated.ServiceType
import uz.elchi.app.api.generated.TripDTO
import uz.elchi.app.feature.client.Load
import uz.elchi.app.feature.client.LoadFailed
import uz.elchi.app.feature.client.LoadingLine
import uz.elchi.app.feature.client.OrderRules
import uz.elchi.app.feature.client.StepScaffold
import uz.elchi.app.feature.client.categoryLimits
import uz.elchi.app.feature.client.categoryName
import uz.elchi.app.feature.client.rememberNow
import uz.elchi.app.feature.client.ParcelRules
import uz.elchi.app.feature.client.seatsLine
import uz.elchi.app.feature.client.seatsPrice
import uz.elchi.app.feature.client.soum
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.CardHeader
import uz.elchi.app.ui.components.CardRow
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiDialog
import uz.elchi.app.ui.components.ElchiField
import uz.elchi.app.ui.components.EmptyState
import uz.elchi.app.ui.components.ItemCard
import uz.elchi.app.ui.components.ItemLine
import uz.elchi.app.ui.components.ListCard
import uz.elchi.app.ui.components.ListRow
import uz.elchi.app.ui.components.LoadingState
import uz.elchi.app.ui.components.MoneyBlock
import uz.elchi.app.ui.components.MoneyRow
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.Segmented
import uz.elchi.app.ui.components.SelectField
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone
import java.time.Instant

// -- shared pieces ------------------------------------------------------------------------------------------------

/** "1 soat 12 daqiqa" → "Taklif 1 soat 12 daqiqa amal qiladi". */
@Composable
internal fun expiresText(seconds: Long): String {
    val (hours, minutes) = OfferRules.expiryParts(seconds)
    val time = when {
        hours > 0 && minutes > 0 -> t(R.string.app_duration_hoursMinutes, "hours" to hours, "minutes" to minutes)
        hours > 0 -> t(R.string.app_duration_hours, "hours" to hours)
        else -> t(R.string.app_duration_minutes, "minutes" to minutes)
    }
    return t(R.string.driver_proposals_expiresIn, "time" to time)
}

@Composable
internal fun threadLineText(line: ThreadLine): Pair<String, Tone> = when (line) {
    ThreadLine.Countered -> t(R.string.negotiation_clientCountered) to Tone.WARN
    ThreadLine.Waiting -> t(R.string.negotiation_waitingForAnswer) to Tone.BLUE
    ThreadLine.Accepted -> (tOrNull("proposalStatus.accepted") ?: "accepted").replaceFirstChar { it.uppercase() } to Tone.OK
    is ThreadLine.Closed -> t(R.string.proposals_closed, "status" to (tOrNull(line.statusKey) ?: line.statusKey.substringAfter('.'))) to Tone.GRAY
}

/** The commission estimate block (W11): an estimate under today's policy, held only on accept - never money. */
@Composable
internal fun FeeBlock(fee: FeeEstimate) {
    when (fee) {
        FeeEstimate.None -> Unit
        FeeEstimate.Loading -> LoadingLine(t(R.string.common_loading))
        FeeEstimate.Unavailable -> Note(t(R.string.commissionPreview_unavailable), tone = Tone.GRAY)
        is FeeEstimate.Ready -> ElchiCard(padding = PaddingValues(horizontal = 16.dp, vertical = 12.dp)) {
            Text(t(R.string.commissionPreview_title), style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold), color = Elchi.colors.text)
            Text(
                t(R.string.commissionPreview_line, "amount" to soum(fee.quote.commissionMinor), "percent" to OfferRules.percent(fee.quote.feeBps), "total" to soum(fee.totalMinor)),
                Modifier.padding(top = 4.dp),
                style = Elchi.type.secondary,
                color = Elchi.colors.text,
            )
            Text(t(R.string.commissionPreview_note), Modifier.padding(top = 4.dp), style = Elchi.type.caption, color = Elchi.colors.muted)
        }
    }
}

/** One send-time warning as a note; the band warning carries its floor and ceiling (Q90: advice, not a block). */
@Composable
internal fun WarningNote(warning: ApiWarning) {
    val text = tOrNull("warning.${warning.code}") ?: warning.message
    val band = if (warning.code == OfferRules.PRICE_OUTSIDE_REFERENCE) OfferRules.band(warning) else null to null
    val bandText = if (band.first != null && band.second != null) t(R.string.driver_bid_priceBand, "floor" to soum(band.first!!), "ceiling" to soum(band.second!!)) else null
    Note(listOfNotNull(text, bandText).joinToString("\n"), tone = Tone.WARN)
}

// -- driver-bid -------------------------------------------------------------------------------------------------

/** `driver-bid` "Narx taklif qiling". */
@Composable
fun BidScreen(
    vm: BidViewModel,
    trips: TripsViewModel,
    driver: DriverViewModel,
    nav: DriverNav,
    onBack: () -> Unit,
    onAddTrip: () -> Unit,
    onThread: (String) -> Unit,
) {
    val s by vm.state.collectAsStateWithLifecycle()
    val ts by trips.state.collectAsStateWithLifecycle()
    val ds by driver.state.collectAsStateWithLifecycle()
    LaunchedEffect(s.openThread) {
        s.openThread?.let {
            vm.opened()
            onThread(it)
        }
    }
    val listing = (s.listing as? Load.Ready)?.value
    val trip = listing?.let { vm.trip(ts.list, it) }
    val window = listing?.let { OfferRules.pickupWindow(trip, it) }
    val status = ds.status
    // Before the listing is read only the gate is known; FORM stands for "not the gate" until then.
    val view = OfferRules.bidView(status, listing?.status ?: ListingStatus.PUBLISHED)
    StepScaffold(
        title = t(R.string.driverBid_title),
        onBack = onBack,
        footer = if (view == BidView.FORM && listing != null) {
            {
                ElchiButton(
                    t(R.string.driverBid_send), { vm.send(trip) }, Modifier.fillMaxWidth(),
                    enabled = window != null && (s.price.toLongOrNull() ?: 0) > 0, loading = s.sending,
                )
            }
        } else null,
    ) {
        if (view == BidView.GATE && status != null) {
            // Q96 one screen deeper: a stale feed, a revoked approval or a link from the public page (Stage 10) can
            // land here; the price field must not say it.
            VerificationGate(status, onDocuments = nav.onDocuments, onProfile = nav.onProfileForm, onSupport = nav.onHelp)
            return@StepScaffold
        }
        when (val l = s.listing) {
            Load.Loading -> LoadingState(count = 2)
            is Load.Failed -> LoadFailed(t(R.string.driverBid_title), l.error) { onBack() }
            is Load.Ready -> {
                RequestSummary(l.value)
                if (view == BidView.CLOSED) {
                    // A link to a listing that is no longer open (the public page's own sentence): no board, no form.
                    Note(t(R.string.publicShare_closedHint), tone = Tone.GRAY)
                    return@StepScaffold
                }
                RivalBoard(s.board, vm::loadBoard)
                TripChoice(vm, ts, trip, window, onAddTrip)
                // Taksi: the chosen trip has fewer free seats than the request needs - say so and let another be picked.
                if (OfferRules.capacityShort(s.error)) {
                    val count = l.value.quantity
                    Note(
                        t(R.string.driverBid_capacityUnavailable, "count" to count),
                        tone = Tone.ERR,
                    )
                }
                val perSeat = l.value.priceBasis == PriceBasis.PER_SEAT
                ElchiField(
                    s.price, vm::setPrice,
                    // Taksi: the offer is per person; the total for all of them shows under the field.
                    label = t(R.string.driverBid_priceLabel) + if (perSeat) " " + t(R.string.listingEdit_perSeatSuffix).trim() else "",
                    hint = if (perSeat) ParcelRules.soumToMinor(s.price)?.let { "${seatsPrice(l.value.quantity, it)} = ${soum(it * l.value.quantity)}" } else null,
                    placeholder = t(R.string.driverBid_pricePlaceholder),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                )
                ElchiButton(
                    t(R.string.driver_bid_acceptClientPrice, "price" to soum(l.value.totalMinor)), { vm.send(trip, clientPrice = true) },
                    Modifier.fillMaxWidth(), ButtonVariant.SOFT, enabled = window != null && !s.sending, maxLines = 2,
                )
                FeeBlock(s.fee)
                Text(t(R.string.driverBid_noHoldNote), style = Elchi.type.caption.copy(fontSize = 12.sp), color = Elchi.colors.muted)
            }
        }
    }
}

@Composable
private fun RequestSummary(listing: ListingPublicDTO) {
    val c = Elchi.colors
    val ru = appRu()
    val start = OrderRules.parseInstant(listing.departureWindowStart)
    val end = OrderRules.parseInstant(listing.departureWindowEnd)
    ElchiCard(padding = PaddingValues(horizontal = 16.dp, vertical = 14.dp), background = if (c.isDark) c.field else Color(0xFFEEF1F5)) {
        Text("${FeedRules.endName(listing.originStop, listing.originPoint, ru)} → ${FeedRules.endName(listing.destinationStop, listing.destinationPoint, ru)}", style = Elchi.type.bodyStrong, color = c.text)
        Text(t(R.string.driverBid_clientPrice, "price" to soum(listing.totalMinor)), Modifier.padding(top = 4.dp), style = Elchi.type.label, color = c.muted)
        val what = if (listing.serviceType == ServiceType.PARCEL) listing.parcelCategory?.let { "${categoryName(it, ru)} · ${categoryLimits(it)}" } else seatsLine(listing.quantity, listing.unitPriceMinor)
        what?.let { Text(it, style = Elchi.type.caption, color = c.muted) }
        if (start != null && end != null) {
            val sameDay = start.atZone(uz.elchi.app.feature.client.ParcelRules.TASHKENT).toLocalDate() == end.atZone(uz.elchi.app.feature.client.ParcelRules.TASHKENT).toLocalDate()
            Text(t(R.string.driverBid_departure, "start" to DriverTime.dayClock(start), "end" to if (sameDay) DriverTime.clock(end) else DriverTime.dayClock(end)), style = Elchi.type.caption, color = c.muted)
        }
    }
}

/** Q40/Q95: the anonymous current offers; the endpoint closed (404) → nothing shown, offering still works. */
@Composable
private fun RivalBoard(board: Load<BoardSummary>?, onRetry: () -> Unit) {
    val c = Elchi.colors
    when (board) {
        null -> Unit
        Load.Loading -> LoadingLine(t(R.string.common_loading))
        is Load.Failed -> Note(errorText(board.error), tone = Tone.GRAY)
        is Load.Ready -> {
            val b = board.value
            if (b.count == 0) {
                Note(t(R.string.app_rivalBoard_empty), tone = Tone.GRAY)
                return
            }
            ElchiCard {
                CardHeader(t(R.string.app_rivalBoard_title), badge = t(R.string.app_rivalBoard_count, "count" to b.count))
                b.cheapestMinor?.let { CardRow(t(R.string.app_rivalBoard_cheapest), soum(it), first = true, strong = true) }
                b.rows.forEach { row -> RivalRow(row) }
                b.mine?.let {
                    Text(
                        t(R.string.app_rivalBoard_mine, "price" to soum(it.totalMinor)),
                        Modifier.padding(vertical = 10.dp),
                        style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold),
                        color = c.accentText,
                    )
                }
            }
        }
    }
}

@Composable
private fun RivalRow(row: ListingOfferDTO) {
    val vehicle = tOrNull("vehicleClass.${row.vehicleClass}") ?: row.vehicleClass
    val bucket = row.ratingBucket?.let { tOrNull("ratingBucket.${it.value}") }
    val count = row.ratingCount ?: 0
    // A group, never a number (U6); with no ratings the sentence says so instead of a made-up score.
    val rating = when {
        bucket != null && count > 0 -> t(R.string.app_rivalBoard_ratings, "bucket" to bucket, "count" to count)
        else -> t(R.string.ratingBucket_new_verified)
    }
    val label = Regex("#(\\d+)").find(row.label)?.groupValues?.get(1)?.let { t(R.string.client_listingBids_driver, "number" to it) } ?: row.label
    val window = OrderRules.parseInstant(row.pickupWindowStart)?.let { a -> OrderRules.parseInstant(row.pickupWindowEnd)?.let { b -> DriverTime.range(a, b) } }
    CardRow(
        key = label + if (row.isMine) " ★" else "",
        value = soum(row.totalMinor),
        // Taksi: each rival's price per person too ("2 × 160 000 so'm").
        detail = listOfNotNull(
            if (row.priceBasis == PriceBasis.PER_SEAT) seatsPrice(row.quantity, row.unitPriceMinor) else null,
            t(R.string.app_rivalBoard_vehicleSeats, "vehicle" to vehicle, "seats" to row.seatCapacity), window, rating,
        ).joinToString(" · "),
        strong = true,
    )
}

@Composable
private fun TripChoice(vm: BidViewModel, ts: TripsViewModel.State, trip: TripDTO?, window: PickupWindow?, onAddTrip: () -> Unit) {
    val ru = appRu()
    val candidates = vm.candidates(ts.list)
    if (ts.trips is Load.Loading) {
        LoadingLine(t(R.string.common_loading))
        return
    }
    SelectField(
        label = t(R.string.driverBid_trip),
        value = trip?.id,
        options = candidates.map { c ->
            c.id to "${TripRules.routeTitle(c, ru)} · ${OrderRules.parseInstant(c.plannedStartAt)?.let(DriverTime::dayClock).orEmpty()}"
        },
        onSelect = vm::pickTrip,
        placeholder = t(if (candidates.isEmpty()) R.string.driverBid_noPlannedTrips else R.string.driverBid_tripPlaceholder),
    )
    if (candidates.isEmpty()) {
        Note(t(R.string.driverBid_planTripFirst), tone = Tone.ERR)
        ElchiButton(t(R.string.driverRoutes_addRoute), onAddTrip, Modifier.fillMaxWidth().height(46.dp), ButtonVariant.SOFT, ButtonSize.MEDIUM, icon = ElchiIcon.PLUS)
        return
    }
    if (trip != null && window == null) Note(t(R.string.driverBid_tripWindowMismatch), tone = Tone.ERR)
    if (window != null) {
        val c = Elchi.colors
        ElchiCard(padding = PaddingValues(horizontal = 16.dp, vertical = 12.dp), background = if (c.isDark) c.field else Color(0xFFEAF5FF)) {
            Text(t(R.string.driverBid_pickupWindow), style = Elchi.type.caption.copy(fontWeight = FontWeight.SemiBold), color = c.accentText)
            Text(DriverTime.range(window.start, window.end), Modifier.padding(top = 2.dp), style = Elchi.type.bodyStrong, color = c.text)
        }
    }
}

// -- driver-proposals -------------------------------------------------------------------------------------------

/** The Orders tab's / home's entry to "Takliflarim": how many are open and whether a client answered. */
@Composable
internal fun ProposalsEntry(vm: ProposalsViewModel, onOpen: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val now by rememberNow()
    val open = s.open
    val countered = open.count { OfferRules.line(it, now) == ThreadLine.Countered }
    val description = when {
        countered > 0 -> "${t(R.string.negotiation_clientCountered)} · $countered"
        open.isNotEmpty() -> "${t(R.string.negotiation_waitingForAnswer)} · ${open.size}"
        else -> t(R.string.proposals_emptyDriver)
    }
    ListCard {
        ListRow(t(R.string.proposals_title), icon = ElchiIcon.TAG, description = description, first = true, onClick = onOpen)
    }
}

/** `driver-proposals` "Takliflarim": Open · Accepted · Closed. */
@Composable
fun ProposalsScreen(vm: ProposalsViewModel, onBack: () -> Unit, onThread: (String) -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val now by rememberNow()
    val ru = appRu()
    LaunchedEffect(Unit) { vm.refresh() }
    StepScaffold(title = t(R.string.proposals_title), onBack = onBack, onRefresh = { vm.refresh() }, refreshing = s.refreshing && s.current is Load.Ready) {
        Segmented(
            listOf(
                ProposalTab.OPEN to t(R.string.publicShare_open),
                ProposalTab.ACCEPTED to t(R.string.client_amendment_statusAccepted),
                ProposalTab.CLOSED to t(R.string.client_amendment_statusClosed),
            ),
            s.tab,
            vm::pick,
        )
        when (val list = s.current) {
            Load.Loading -> LoadingState(count = 2)
            is Load.Failed -> LoadFailed(t(R.string.proposals_title), list.error) { vm.refresh() }
            is Load.Ready -> if (list.value.isEmpty()) {
                EmptyState(ElchiIcon.TAG, t(R.string.proposals_empty), description = t(R.string.proposals_emptyDriver))
            } else {
                list.value.forEach { thread -> ThreadCard(thread, now, ru) { onThread(thread.id) } }
            }
        }
    }
}

@Composable
private fun ThreadCard(thread: ProposalThreadDTO, now: Instant, ru: Boolean, onClick: () -> Unit) {
    val c = Elchi.colors
    val v = thread.currentVersion
    // A countdown that reaches zero is read again: the server may already have closed it.
    val (lineText, tone) = threadLineText(OfferRules.line(thread, now))
    val left = OfferRules.secondsLeft(thread, now)
    ItemCard(
        title = OfferRules.routeTitle(thread, ru),
        icon = ElchiIcon.PIN,
        sub = v?.let { OrderRules.dayRange(it.pickupWindowStart, it.pickupWindowEnd) },
        lines = listOfNotNull(
            ItemLine(lineText, c.tone(tone).fg),
            left?.let { ItemLine(expiresText(it), c.tone(Tone.WARN).fg) },
        ),
        right = v?.let { soum(it.totalMinor) },
        rightColor = c.accentText,
        onClick = onClick,
    )
}

// -- proposal thread --------------------------------------------------------------------------------------------

/** One negotiation: the latest state, its history, and the moves allowed by the turn (web `auction.ts`). */
@Composable
fun ProposalThreadScreen(vm: ProposalThreadViewModel, onBack: () -> Unit, onBooking: (String) -> Unit = {}) {
    val s by vm.state.collectAsStateWithLifecycle()
    val now by rememberNow()
    val ru = appRu()
    var confirmAccept by remember { mutableStateOf(false) }
    var confirmWithdraw by remember { mutableStateOf(false) }
    var countering by remember { mutableStateOf(false) }
    LaunchedEffect(s.reconfirm) {
        if (s.reconfirm) {
            vm.reconfirmShown()
            confirmAccept = true
        }
    }
    // The countdown ran out on screen: read the thread again (the server may have expired it already).
    val thread = (s.thread as? Load.Ready)?.value
    val expired = thread?.let { OfferRules.actions(it, now).expiredLocally } == true
    LaunchedEffect(expired) { if (expired) vm.refresh() }
    StepScaffold(title = t(R.string.proposals_title), onBack = onBack, onRefresh = vm::refresh, refreshing = s.refreshing && s.thread is Load.Ready) {
        when (val load = s.thread) {
            Load.Loading -> LoadingState(count = 2)
            is Load.Failed -> LoadFailed(t(R.string.proposals_title), load.error, vm::refresh)
            is Load.Ready -> {
                val t0 = load.value
                val v = t0.currentVersion
                val actions = OfferRules.actions(t0, now)
                val (lineText, tone) = threadLineText(OfferRules.line(t0, now))
                ElchiCard(padding = PaddingValues(horizontal = 16.dp, vertical = 14.dp)) {
                    Text(OfferRules.routeTitle(t0, ru), style = Elchi.type.bodyStrong, color = Elchi.colors.text)
                    v?.let { ver ->
                        OrderRules.parseInstant(ver.pickupWindowStart)?.let { a -> OrderRules.parseInstant(ver.pickupWindowEnd)?.let { b -> DriverTime.range(a, b) } }?.let {
                            Text("${t(R.string.driverBid_pickupWindow)}: $it", Modifier.padding(top = 4.dp), style = Elchi.type.caption, color = Elchi.colors.muted)
                        }
                        Text(soum(ver.totalMinor), Modifier.padding(top = 6.dp), style = Elchi.type.section.copy(fontWeight = FontWeight.SemiBold), color = Elchi.colors.accentText)
                    }
                    Text(lineText, Modifier.padding(top = 6.dp), style = Elchi.type.label.copy(fontWeight = FontWeight.SemiBold), color = Elchi.colors.tone(tone).fg)
                    OfferRules.secondsLeft(t0, now)?.let { Text(expiresText(it), style = Elchi.type.caption, color = Elchi.colors.tone(Tone.WARN).fg) }
                }
                vm.sentWarnings.forEach { WarningNote(it) }
                (s.bookingId ?: t0.bookingId)?.let { bookingId ->
                    // Stage 09: the booking exists as a screen now - its chat is where the meeting point is agreed (Q100).
                    Note(t(R.string.driver_proposals_bookingReady), tone = Tone.OK)
                    ElchiButton(t(R.string.driverBooking_title), { onBooking(bookingId) }, Modifier.fillMaxWidth(), ButtonVariant.SOFT, icon = ElchiIcon.CLIP)
                }
                if (s.notice == ThreadNotice.TERMS_CHANGED) Note(t(R.string.client_listingBids_termsChanged), tone = Tone.WARN)
                if (actions.open && actions.theirTurn && v != null) {
                    val promo = OfferRules.driverPromo(v)
                    if (promo != null) {
                        MoneyBlock(
                            listOf(
                                MoneyRow(t(R.string.promo_line_offerPrice), soum(promo.fareMinor)),
                                MoneyRow(t(R.string.promo_line_cashFromClient), soum(promo.cashToCollectMinor), strong = true),
                                MoneyRow(t(R.string.promo_line_discountCovered), soum(promo.passengerDiscountCoveredMinor)),
                                MoneyRow(t(R.string.promo_line_chargedFromBalance), soum(promo.commissionChargedMinor)),
                                MoneyRow(t(R.string.promo_line_creditToUse), "−" + soum(promo.driverCreditMinor), color = Elchi.colors.tone(Tone.OK).fg),
                                MoneyRow(t(R.string.promo_line_youKeep), soum(promo.driverKeepsMinor), strong = true),
                            ),
                        )
                    } else {
                        FeeBlock(s.fee)
                    }
                    ElchiButton(t(R.string.proposals_acceptClientPrice), { confirmAccept = true }, Modifier.fillMaxWidth(), loading = s.busy)
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        ElchiButton(t(R.string.proposal_reject), vm::reject, Modifier.weight(1f).height(48.dp), ButtonVariant.DANGER_SOFT, ButtonSize.MEDIUM, enabled = !s.busy, horizontalPadding = 10.dp)
                        if (actions.canCounter) {
                            ElchiButton(
                                t(R.string.proposals_counterAnother, "count" to actions.revisionsLeft), { countering = !countering },
                                Modifier.weight(1f).height(48.dp), ButtonVariant.SOFT, ButtonSize.MEDIUM, enabled = !s.busy, horizontalPadding = 10.dp, maxLines = 2,
                            )
                        }
                    }
                    if (!actions.canCounter) Text(t(R.string.proposals_noRevisionsLeft), style = Elchi.type.caption, color = Elchi.colors.muted)
                    if (countering && actions.canCounter) {
                        ElchiField(
                            s.counterPrice, vm::setCounterPrice,
                            label = t(R.string.proposals_newPrice),
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        )
                        ElchiButton(
                            t(R.string.common_send), {
                                countering = false
                                vm.counter()
                            },
                            Modifier.fillMaxWidth(), enabled = (s.counterPrice.toLongOrNull() ?: 0) > 0 && !s.busy,
                        )
                    }
                } else if (actions.open && actions.canWithdraw) {
                    FeeBlock(s.fee)
                    ElchiButton(t(R.string.proposals_withdraw), { confirmWithdraw = true }, Modifier.fillMaxWidth(), ButtonVariant.NEUTRAL, loading = s.busy)
                }
                History(t0)
            }
        }
    }
    if (confirmAccept) {
        val v = thread?.currentVersion
        ElchiDialog(
            title = t(R.string.proposals_acceptClientPrice),
            text = v?.let { soum(it.totalMinor) } ?: "—",
            confirm = t(R.string.common_confirm),
            onConfirm = {
                confirmAccept = false
                vm.accept()
            },
            onDismiss = { confirmAccept = false },
            dismiss = t(R.string.confirmDialog_back),
        )
    }
    if (confirmWithdraw) {
        ElchiDialog(
            title = t(R.string.proposals_withdraw),
            text = t(R.string.confirmDialog_cancelOrder_text),
            confirm = t(R.string.proposals_withdraw),
            onConfirm = {
                confirmWithdraw = false
                vm.withdraw()
            },
            onDismiss = { confirmWithdraw = false },
            confirmVariant = ButtonVariant.DANGER,
            dismiss = t(R.string.confirmDialog_back),
        )
    }
}

/** Every version, oldest first: who, the price, the window, when. */
@Composable
private fun History(thread: ProposalThreadDTO) {
    val versions = OfferRules.history(thread)
    if (versions.isEmpty()) return
    ElchiCard {
        CardHeader(t(R.string.client_amendment_history))
        versions.forEachIndexed { i, v ->
            val who = when (v.authorSide) {
                ActorSide.CLIENT -> t(R.string.dispute_side_client)
                ActorSide.DRIVER -> Regex("#(\\d+)").find(thread.driver.label)?.groupValues?.get(1)?.let { t(R.string.client_listingBids_driver, "number" to it) } ?: thread.driver.label
                else -> v.authorSide.value
            }
            val window = OrderRules.parseInstant(v.pickupWindowStart)?.let { a -> OrderRules.parseInstant(v.pickupWindowEnd)?.let { b -> DriverTime.range(a, b) } }
            val at = OrderRules.parseInstant(v.createdAt)?.let(DriverTime::dayClock)
            CardRow(
                key = listOfNotNull(who, at).joinToString(" · "),
                value = soum(v.totalMinor),
                first = i == 0,
                detail = listOfNotNull(window, tOrNull("proposalStatus.${v.status.value}").takeIf { v.status.value != "active" }).joinToString(" · ").ifEmpty { null },
                strong = v.id == thread.currentVersion?.id,
            )
        }
    }
}
