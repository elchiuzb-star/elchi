package uz.elchi.app.feature.client

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import uz.elchi.app.R
import uz.elchi.app.api.generated.ApiWarning
import uz.elchi.app.api.generated.PriceBasis
import uz.elchi.app.api.generated.ProposalPromoClientDTO
import uz.elchi.app.api.generated.ProposalThreadDTO
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.Banner
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiField
import uz.elchi.app.ui.components.ElchiIconView
import uz.elchi.app.ui.components.MoneyBlock
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.ElchiShape
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone
import java.time.Instant

// The offer card of BOSQICH 03 ("Elchi Takliflar"), shared by the listing detail's inline board and "Takliflarim".

/** What a tap on an offer card does; [board] runs the commands, the screen only says which thread. */
internal class OfferHandlers(
    val board: OfferBoard,
    val onAccept: (ProposalThreadDTO) -> Unit = board::askAccept,
)

/**
 * One driver's offer (design `bidItems`): "Haydovchi #N", the badge of the chosen sort (or "Yangi" / "Qarshi
 * taklif"), the price; a grey box with the window, the anonymous driver summary (Q40) and the state line; then the
 * action row (reject, another price, choose / accept), the inline counter form, or the small withdraw button.
 * A closed offer is faded and says why; nothing on it can be pressed.
 *
 * [route] is the first grey-box line in "Takliflarim" (its threads span listings). [listingDay] ("30.09") drops the
 * day from the window when it is the listing's own. [paused]: the listing takes no accept or counter
 * (`LISTING_NOT_OPEN`, RULE 5.11) - only rejecting stays.
 */
@Composable
internal fun OfferCard(
    thread: ProposalThreadDTO,
    board: OfferBoard.State,
    handlers: OfferHandlers,
    now: Instant,
    ru: Boolean,
    badge: OfferBadge? = null,
    fresh: Boolean = false,
    previousTotal: Long? = null,
    route: String? = null,
    listingDay: String? = null,
    paused: Boolean = false,
    /** The client's own window (start, end): a driver's time proposal is read against it (ADR-0027, Q153). */
    requestWindow: Pair<String?, String?>? = null,
) {
    val c = Elchi.colors
    val version = thread.currentVersion
    val actions = OrderRules.negotiationActions(thread, now)
    val closed = version == null || !actions.open
    val driverCountered = !closed && OrderRules.driverCountered(thread)
    // The design shows one badge: the sort's first, then "Yangi", then "Qarshi taklif".
    val shownBadge: Pair<String, Tone>? = when {
        closed -> null
        badge == OfferBadge.CHEAPEST -> t(R.string.client_listingBids_cheapest) to Tone.OK
        badge == OfferBadge.FASTEST -> t(R.string.client_listingBids_sortFastest) to Tone.BLUE
        badge == OfferBadge.RATED -> t(R.string.client_listingBids_sortRating) to Tone.BLUE
        fresh && actions.theirTurn -> t(R.string.client_notifications_new) to Tone.ERR
        driverCountered -> t(R.string.client_offers_badgeCounter) to Tone.WARN
        else -> null
    }
    val shape = RoundedCornerShape(ElchiShape.card)
    val highlighted = badge == OfferBadge.CHEAPEST && !closed
    Column(
        Modifier
            .fillMaxWidth()
            .alpha(if (closed) 0.72f else 1f)
            .shadow(12.dp, shape, ambientColor = c.shadow, spotColor = c.shadow)
            .clip(shape)
            .background(c.card)
            .then(if (highlighted) Modifier.border(2.dp, c.brand, shape) else Modifier)
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(driverLabel(thread), style = Elchi.type.bodyStrong, color = c.text, maxLines = 1)
            shownBadge?.let { (text, tone) -> OfferPill(text, tone) }
            Spacer(Modifier.weight(1f))
            version?.let {
                Text(
                    soum(it.totalMinor),
                    style = Elchi.type.bodyStrong.copy(fontSize = 17.sp, lineHeight = 22.sp),
                    color = if (closed) c.placeholder else c.accentText,
                    maxLines = 1,
                )
            }
        }
        OfferFacts(thread, actions, now, ru, closed, driverCountered, previousTotal, route, listingDay, requestWindow)
        if (version == null || closed) return@Column
        val busy = board.busyThread == thread.id
        val otherBusy = board.busyThread != null && !busy
        when {
            !actions.theirTurn -> {
                // The client's own counter waits for the driver: it can be taken back.
                ElchiButton(
                    t(R.string.proposals_withdraw),
                    { handlers.board.withdraw(thread) },
                    Modifier.align(Alignment.End).height(36.dp),
                    ButtonVariant.NEUTRAL,
                    ButtonSize.MEDIUM,
                    enabled = actions.canWithdraw && !otherBusy,
                    loading = busy,
                    horizontalPadding = 14.dp,
                )
            }
            paused -> {
                Note(t(R.string.client_listingBids_pausedNote), tone = Tone.WARN)
                ElchiButton(
                    t(R.string.proposal_reject), { handlers.board.reject(thread) }, Modifier.fillMaxWidth().height(44.dp), ButtonVariant.DANGER_SOFT, ButtonSize.MEDIUM,
                    enabled = actions.canReject && !otherBusy, loading = busy,
                )
            }
            board.counterFor == thread.id -> CounterForm(thread, board, handlers.board, busy)
            else -> {
                val quote = version.promoQuote as? ProposalPromoClientDTO
                if (quote != null) {
                    // Q104: only with a server quote, never pre-ticked (RULE 5.14).
                    val ticked = thread.id in board.acceptBonus
                    MoneyBlock(
                        promoRows(version.totalMinor, quote, ticked, offer = true),
                        check = t(R.string.promoScreen_useBonusShort, "amount" to soum(quote.passengerDiscountMinor)),
                        checked = ticked,
                        onCheck = { handlers.board.toggleAcceptBonus(thread.id) },
                    )
                    if (ticked) Text(t(R.string.client_offers_bonusCovered), style = Elchi.type.caption, color = c.muted)
                } else {
                    NoDiscountNote(version.promoUnavailableReason)
                }
                ActionRow(thread, actions, driverCountered, busy, board.busyCommand, otherBusy, handlers)
            }
        }
        if (board.errorThread == thread.id) board.error?.let { Note(offerErrorText(it), tone = Tone.ERR) }
    }
}

/** The badge pill of the card's head (no dot, as in the design's `x.badge`). */
@Composable
private fun OfferPill(text: String, tone: Tone) {
    val colors = Elchi.colors.tone(tone)
    Text(
        text,
        Modifier.clip(CircleShape).background(colors.bg).padding(horizontal = 9.dp, vertical = 3.dp),
        style = Elchi.type.badge,
        color = colors.fg,
        maxLines = 1,
    )
}

/** The grey box: route (Takliflarim), window · driver, per-seat price, message, and the line of the offer's state. */
@Composable
private fun OfferFacts(
    thread: ProposalThreadDTO,
    actions: NegotiationActions,
    now: Instant,
    ru: Boolean,
    closed: Boolean,
    driverCountered: Boolean,
    previousTotal: Long?,
    route: String?,
    listingDay: String?,
    requestWindow: Pair<String?, String?>?,
) {
    val c = Elchi.colors
    val version = thread.currentVersion
    val warn = c.tone(Tone.WARN).fg
    val proposal = timeProposalText(version, requestWindow)
    val body = if (c.isDark) c.text.copy(alpha = 0.82f) else Color(0xFF3A4556)
    val lines = buildList {
        route?.let { add(it to c.text) }
        if (version != null) {
            val window = OrderRules.offerWindow(version.pickupWindowStart, version.pickupWindowEnd, listingDay)
            val summary = thread.driverSummary?.let { driverSummary(it) }
            listOfNotNull(window, summary).joinToString(" · ").takeIf { it.isNotEmpty() }?.let { add(it to body) }
            // Q153: the driver offers another pickup time than the client asked for.
            proposal?.let { add(it to warn) }
            // Taksi: the offer is per person - "2 × 160 000 so'm" under the total.
            if (version.priceBasis == PriceBasis.PER_SEAT) add(seatsPrice(version.quantity, version.unitPriceMinor) to body)
            version.message?.takeIf { it.isNotBlank() }?.let { add("“${it.trim()}”" to c.text) }
        }
        when {
            closed -> add(closedReason(thread, now) to c.muted)
            version == null -> Unit
            !actions.theirTurn -> add(t(R.string.client_offers_myCounterWaiting, "price" to soum(version.totalMinor)) to c.accentText)
            else -> {
                // 5.6: "(sizniki ...)" needs the client's earlier price, read with the thread's versions.
                if (driverCountered && previousTotal != null) {
                    add(t(R.string.client_offers_driverCounter, "price" to soum(version.totalMinor), "mine" to soum(previousTotal)) to warn)
                }
                OrderRules.secondsLeft(version, now)?.let { add(countdownText(it) to warn) }
            }
        }
    }
    if (lines.isEmpty()) return
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(if (c.isDark) c.field else Color(0xFFF6F8FA)).padding(horizontal = 12.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.spacedBy(3.dp),
    ) {
        lines.forEach { (text, color) -> Text(text, style = Elchi.type.caption.copy(fontSize = 12.5.sp, lineHeight = 18.sp), color = color) }
    }
}

/**
 * Round ✕ (reject), "Boshqa narx · N" (greyed at 0: a tap says the limit is reached), and "Tanlash" / "Qabul
 * qilish" (the driver answered the client's counter). When the labels do not fit one row (Russian), the primary
 * action takes its own row under the other two - never an ellipsis.
 */
@Composable
private fun ActionRow(
    thread: ProposalThreadDTO,
    actions: NegotiationActions,
    driverCountered: Boolean,
    busy: Boolean,
    command: OfferCommand?,
    otherBusy: Boolean,
    handlers: OfferHandlers,
) {
    val c = Elchi.colors
    val toast = LocalFlowToast.current
    val limitText = t(R.string.client_offers_counterLimit)
    val rejectLabel = t(R.string.proposal_reject)
    val counterLabel = t(R.string.client_offers_counterButton, "count" to actions.revisionsLeft)
    val primaryLabel = t(if (driverCountered) R.string.amendment_accept else R.string.confirmDialog_selectDriver_confirm)
    val measurer = rememberTextMeasurer()
    val style = Elchi.type.buttonSmall
    val reject: @Composable () -> Unit = {
        val err = c.tone(Tone.ERR)
        Box(
            Modifier
                .size(42.dp)
                .clip(CircleShape)
                .background(if (actions.canReject && !otherBusy) err.bg else c.field)
                .clickable(enabled = actions.canReject && !busy && !otherBusy, role = Role.Button) { handlers.board.reject(thread) }
                .semantics { contentDescription = rejectLabel },
            contentAlignment = Alignment.Center,
        ) {
            if (busy && command == OfferCommand.REJECT) {
                androidx.compose.material3.CircularProgressIndicator(Modifier.size(18.dp), color = err.fg, strokeWidth = 2.dp)
            } else {
                ElchiIconView(ElchiIcon.X, if (actions.canReject && !otherBusy) err.fg else c.placeholder, size = 18.dp)
            }
        }
    }
    val counter: @Composable (Modifier) -> Unit = { m ->
        ElchiButton(
            counterLabel,
            { if (actions.canCounter) handlers.board.openCounter(thread) else toast.show(limitText) },
            m.height(42.dp),
            ButtonVariant.NEUTRAL,
            ButtonSize.MEDIUM,
            enabled = !busy && !otherBusy,
            dimmed = !actions.canCounter,
            horizontalPadding = 10.dp,
        )
    }
    val primary: @Composable (Modifier) -> Unit = { m ->
        ElchiButton(primaryLabel, { handlers.onAccept(thread) }, m.height(42.dp), size = ButtonSize.MEDIUM, enabled = actions.canAccept && !otherBusy && (!busy || command == OfferCommand.ACCEPT), loading = busy && command == OfferCommand.ACCEPT, horizontalPadding = 10.dp)
    }
    BoxWithConstraints(Modifier.fillMaxWidth()) {
        val density = LocalDensity.current
        val counterWidth = with(density) { measurer.measure(counterLabel, style).size.width.toDp() } + 20.dp
        val primaryWidth = with(density) { measurer.measure(primaryLabel, style).size.width.toDp() } + 20.dp
        val rest = maxWidth - 42.dp - 16.dp
        val oneRow = counterWidth <= rest * (1f / 2.2f) && primaryWidth <= rest * (1.2f / 2.2f)
        if (oneRow) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                reject()
                counter(Modifier.weight(1f))
                primary(Modifier.weight(1.2f))
            }
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    reject()
                    counter(Modifier.weight(1f))
                }
                primary(Modifier.fillMaxWidth())
            }
        }
    }
}

/**
 * The inline "another price" form: the price (per person for a `per_seat` Taksi offer, §6), "Jami: ..." under it,
 * the bonus preview for that price (or why there is none), send / cancel. Errors show after a tap on "Yuborish".
 */
@Composable
private fun CounterForm(thread: ProposalThreadDTO, state: OfferBoard.State, board: OfferBoard, busy: Boolean) {
    val c = Elchi.colors
    val version = thread.currentVersion ?: return
    val units = OrderRules.counterUnits(version)
    val price = board.counterPrice(thread)
    val typed = ParcelRules.soumToMinor(state.counterDigits)
    val quote = state.counterPreview?.quote
    NoDiscountNote(state.counterPreview?.noDiscountReason)
    val error = when (state.counterProblem) {
        CounterProblem.EMPTY -> t(R.string.listingOwner_invalid_price)
        CounterProblem.SAME -> t(R.string.client_offers_counterSame)
        null -> null
    }
    ElchiField(
        state.counterDigits,
        { board.setCounterDigits(thread, it) },
        label = t(if (units.perSeat) R.string.amendment_seatPriceLabel else R.string.listingBids_yourPrice),
        placeholder = ParcelRules.groupThousands(ParcelRules.minorToSoum(units.base)),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Done),
        visualTransformation = ThousandsTransformation,
        suffix = t(R.string.common_soum),
        minHeight = 48.dp,
        // RULE §6: no "Haydovchi 1 marta javob beradi" - the driver has revisions of its own.
        hint = "${t(R.string.common_total)}: ${typed?.let { soum(units.total(it)) } ?: "—"}",
        error = error,
    )
    if (quote != null && price != null) {
        MoneyBlock(
            promoRows(units.total(price), quote, state.counterBonus, offer = true),
            check = t(R.string.promoScreen_useBonusShort, "amount" to soum(quote.passengerDiscountMinor)),
            checked = state.counterBonus,
            onCheck = board::setCounterBonus,
        )
        Text(t(R.string.client_listingBids_bonusOptIn), style = Elchi.type.caption, color = c.muted)
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        ElchiButton(t(R.string.common_send), { board.sendCounter(thread) }, Modifier.weight(1f).height(44.dp), size = ButtonSize.MEDIUM, loading = busy, horizontalPadding = 10.dp)
        ElchiButton(t(R.string.common_cancel), board::closeCounter, Modifier.weight(1f).height(44.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM, enabled = !busy, horizontalPadding = 10.dp)
    }
}

/**
 * The outcome of the last offer command: the design's toast ("Haydovchi #3 taklifi rad etildi", "Qarshi taklif
 * yuborildi: 135 000 so'm", "Qarshi taklif qaytarib olindi"), then cleared.
 */
@Composable
internal fun OfferNoticeToast(notice: OfferNotice?, consume: () -> Unit) {
    val toast = LocalFlowToast.current
    val text = when (notice) {
        is OfferNotice.CounterSent -> t(R.string.client_offers_counterSentPrice, "price" to soum(notice.totalMinor))
        is OfferNotice.Rejected -> notice.driverNumber?.let { t(R.string.client_offers_rejectedDriver, "number" to it) } ?: t(R.string.proposal_rejected)
        OfferNotice.Withdrawn -> t(R.string.client_offers_counterWithdrawn)
        null -> null
    }
    LaunchedEffect(notice) {
        if (text != null) {
            toast.show(text)
            consume()
        }
    }
}

/** Q90: a price outside the corridor's usual range is advice - the offer went through. Strips under the bar. */
@Composable
internal fun OfferWarnings(warnings: List<ApiWarning>, consume: () -> Unit) {
    LaunchedEffect(warnings) {
        if (warnings.isNotEmpty()) {
            delay(NOTICE_SHOWN_MS)
            consume()
        }
    }
    warnings.forEach { Banner(tOrNull("warning.${it.code}") ?: it.message, Tone.WARN) }
}

/** The empty board on the listing detail: a small card with the tag icon (design `bidsEmpty`). */
@Composable
internal fun OffersWaitCard() {
    val c = Elchi.colors
    Row(
        Modifier
            .fillMaxWidth()
            .shadow(10.dp, RoundedCornerShape(18.dp), ambientColor = c.shadow, spotColor = c.shadow)
            .clip(RoundedCornerShape(18.dp))
            .background(c.card)
            .padding(14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Box(Modifier.size(38.dp).clip(CircleShape).background(if (c.isDark) c.soft else Color(0xFFEEF4FA)), contentAlignment = Alignment.Center) {
            ElchiIconView(ElchiIcon.TAG, c.accentText, size = 18.dp)
        }
        Text(t(R.string.client_offers_waitHint), style = Elchi.type.label.copy(fontWeight = FontWeight.Normal, lineHeight = 19.sp), color = c.muted)
    }
}
