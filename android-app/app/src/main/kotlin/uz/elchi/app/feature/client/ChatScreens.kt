package uz.elchi.app.feature.client

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import uz.elchi.app.R
import uz.elchi.app.api.ApiException
import uz.elchi.app.api.generated.ApiWarning
import uz.elchi.app.api.generated.ChatMessageDTO
import uz.elchi.app.api.generated.ChatModerationStatus
import uz.elchi.app.api.generated.QuickReplyCode
import uz.elchi.app.api.generated.SupportMessageDTO
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.BubbleKind
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.CardRow
import uz.elchi.app.ui.components.ChatBubble
import uz.elchi.app.ui.components.Composer
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.EmptyState
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.RoundIconButton
import uz.elchi.app.ui.components.SystemBarIcons
import uz.elchi.app.ui.components.TitleBar
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import java.time.LocalDate
import java.time.format.DateTimeFormatter

/** Runs [block] while the screen is at least started: leaving it or backgrounding the app stops it. */
@Composable
internal fun WhileStarted(key: Any, block: suspend () -> Unit) {
    val owner = LocalLifecycleOwner.current
    LaunchedEffect(owner, key) { owner.lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { block() } }
}

/** `08:15` today, `27.09, 08:15` on another day (Tashkent). */
internal fun chatTime(value: String?): String? {
    val time = OrderRules.tashkent(value) ?: return null
    val today = LocalDate.now(ParcelRules.TASHKENT)
    return if (time.toLocalDate() == today) time.format(DateTimeFormatter.ofPattern("HH:mm")) else ParcelRules.displayShort(time)
}

/** The list is at (or next to) its end: a new message may bring it along without taking the reader's place. */
private fun LazyListState.atEnd(): Boolean {
    val info = layoutInfo
    val last = info.visibleItemsInfo.lastOrNull() ?: return true
    return last.index >= info.totalItemsCount - 2
}

/** Title bar, a pull-to-refresh list with the "Yangi xabar" pill over it, and the footer on the white strip. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ChatFrame(
    title: String,
    onBack: () -> Unit,
    list: LazyListState,
    refreshing: Boolean,
    onRefresh: () -> Unit,
    unseen: Int,
    onPill: () -> Unit,
    /** Round icon buttons at the right of the title bar (the support chat's refresh). */
    actions: (@Composable () -> Unit)? = null,
    /** The line under the title (design 04: "Jasur · Chevrolet Cobalt"). */
    subtitle: String? = null,
    /** A strip under the title that stays put (the driver's GPS bar while the trip runs). */
    top: (@Composable () -> Unit)? = null,
    footer: (@Composable () -> Unit)?,
    content: LazyListScope.() -> Unit,
) {
    val c = Elchi.colors
    SystemBarIcons(dark = !c.isDark)
    Column(Modifier.fillMaxSize().background(c.page).imePadding()) {
        Column(Modifier.statusBarsPadding()) {
            TitleBar(onBack, t(R.string.common_back), title, trailing = actions, subtitle = subtitle)
            top?.invoke()
        }
        Box(Modifier.weight(1f)) {
            PullToRefreshBox(isRefreshing = refreshing, onRefresh = onRefresh, modifier = Modifier.fillMaxSize()) {
                LazyColumn(
                    Modifier.fillMaxSize(),
                    state = list,
                    contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 6.dp, bottom = 16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                    content = content,
                )
            }
            if (unseen > 0) {
                Text(
                    t(R.string.notification_chat_message_created_title),
                    Modifier
                        .align(Alignment.BottomCenter)
                        .padding(bottom = 12.dp)
                        .shadow(8.dp, CircleShape, ambientColor = c.shadow, spotColor = c.shadow)
                        .clip(CircleShape)
                        .background(c.brand)
                        .clickable(role = Role.Button, onClick = onPill)
                        .heightIn(min = 36.dp)
                        .padding(horizontal = 16.dp, vertical = 9.dp),
                    style = Elchi.type.label,
                    color = c.onBrand,
                )
            }
        }
        if (footer != null) {
            Column(Modifier.fillMaxWidth().background(c.card)) {
                Box(Modifier.fillMaxWidth().height(1.dp).background(c.line))
                Column(Modifier.navigationBarsPadding().padding(start = 16.dp, end = 16.dp, top = 10.dp, bottom = 8.dp)) { footer() }
            }
        } else {
            Box(Modifier.navigationBarsPadding())
        }
    }
}

// -- booking-chat ------------------------------------------------------------------------------------------------

/**
 * `booking-chat` "Xabarlar": the booking chat, oldest at the top ("Oldingi xabarlar" reads further back), the
 * driver's messages on the left under "Haydovchi", the client's on the right. Polled while open; a message that
 * arrives while the reader is further up shows the "Yangi xabar" pill instead of moving the list.
 */
@Composable
fun BookingChatScreen(
    vm: BookingChatViewModel,
    onBack: () -> Unit,
    /** The driver's chat (Stage 09): its quick replies, the other side named "Mijoz", the GPS bar on top. */
    side: BookingSide = BookingSide.CLIENT,
    top: (@Composable () -> Unit)? = null,
) {
    val s by vm.state.collectAsStateWithLifecycle()
    val list = rememberLazyListState()
    val atEnd by remember { derivedStateOf { list.atEnd() } }
    WhileStarted(vm) { vm.watch() }
    val lastIndex = { (list.layoutInfo.totalItemsCount - 1).coerceAtLeast(0) }
    LaunchedEffect(s.scrollNonce) { if (s.scrollNonce > 0) list.animateScrollToItem(lastIndex()) }
    LaunchedEffect(s.unseen, atEnd) {
        if (s.unseen > 0 && atEnd) {
            list.animateScrollToItem(lastIndex())
            vm.markSeen()
        }
    }
    val chat = s.chat
    val booking = s.booking
    val driver = booking?.driver?.takeIf { side == BookingSide.CLIENT }
    ChatFrame(
        title = t(R.string.bookingChat_title),
        subtitle = driver?.let { listOf(it.displayName, it.vehicle.makeModel).filter(String::isNotBlank).joinToString(" · ") },
        onBack = onBack,
        list = list,
        refreshing = s.refreshing && s.loaded,
        onRefresh = vm::refresh,
        unseen = if (atEnd) 0 else s.unseen,
        onPill = { vm.markSeen() },
        top = top,
        footer = when {
            chat == null -> null
            // The server's `writable` decides (Q100: open 24 h after the end), not the status; the reason in words.
            !chat.writable -> ({
                val body = if (booking?.serviceStatus == "cancelled") R.string.client_chat_closedCancelled else R.string.chat_closedBody
                Note(t(body), tone = Tone.GRAY, title = t(R.string.chat_closedTitle))
            })
            else -> ({
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    chatTime(chat.writableUntil)?.let { Text("${t(R.string.chat_closesSoon)} $it", style = Elchi.type.caption, color = Elchi.colors.muted) }
                    Composer(
                        value = s.draft,
                        onValueChange = vm::setDraft,
                        placeholder = t(R.string.bookingChat_placeholder),
                        sendLabel = t(R.string.common_send),
                        onSend = vm::sendDraft,
                        // Q100: each side's quick replies; "price agreed" is never offered in a booking chat.
                        chips = quickReplies(side).map { code -> t(quickReplyLabel(code)) to { vm.sendQuick(code) } },
                        hint = t(R.string.bookingChat_autoMaskNote),
                    )
                }
            })
        },
    ) {
        if (!s.loaded) {
            item { s.loadError?.let { LoadFailed(t(R.string.bookingChat_title), it, vm::refresh) } ?: LoadingLine(t(R.string.common_loading)) }
            return@ChatFrame
        }
        if (s.olderCursor != null) {
            item(key = "older") {
                Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                    ElchiButton(t(R.string.bookingChat_olderMessages), vm::loadOlder, size = ButtonSize.MEDIUM, variant = ButtonVariant.GHOST, icon = ElchiIcon.CHEV_U, loading = s.loadingOlder)
                }
            }
        }
        // Design 04: the chat opens with the agreement ("Kelishuv tuzildi · 27.09, 08:12") once the oldest page is here.
        if (s.olderCursor == null && booking != null) {
            item(key = "agreed") {
                val at = OrderRules.tashkent(booking.createdAt)?.let(ParcelRules::displayShort)
                ChatBubble(BubbleKind.SYSTEM, listOfNotNull(t(R.string.notification_booking_accepted_title), at).joinToString(" · "))
            }
        }
        // A closed chat with nothing in it needs no "write here" hint: the footer says it is closed.
        if (s.messages.isEmpty() && s.outgoing.isEmpty() && chat?.writable != false) {
            item(key = "empty") { EmptyState(ElchiIcon.CHAT, t(R.string.bookingChat_emptyTitle), description = t(R.string.bookingChat_emptySubtitle)) }
        }
        items(s.messages, key = { it.id }) { message ->
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                MessageBubble(message, side)
                s.warnings[message.id]?.let { WarningNotes(it) }
            }
        }
        items(s.outgoing, key = { "out-${it.localId}" }) { message -> OutgoingBubble(message, onRetry = { vm.retry(message.localId) }, onDiscard = { vm.discard(message.localId) }) }
        // Closed: when it stopped accepting messages, under the last one.
        if (chat != null && !chat.writable) {
            chatTime(chat.writableUntil)?.let { until ->
                item(key = "closed-at") { ChatBubble(BubbleKind.SYSTEM, t(R.string.client_chat_openUntil, "time" to until)) }
            }
        }
    }
}

/** The client: "Bekatdaman", "Bekatni aniqlashtiraylik"; the driver also "5 daqiqada yetaman" (design booking-chat). */
internal fun quickReplies(side: BookingSide): List<QuickReplyCode> = when (side) {
    BookingSide.CLIENT -> listOf(QuickReplyCode.AT_STOP, QuickReplyCode.CLARIFY_STOP)
    BookingSide.DRIVER -> listOf(QuickReplyCode.ARRIVING_IN_5_MIN, QuickReplyCode.AT_STOP, QuickReplyCode.CLARIFY_STOP)
}

private fun quickReplyLabel(code: QuickReplyCode): Int = when (code) {
    QuickReplyCode.AT_STOP -> R.string.quickReply_at_stop
    QuickReplyCode.CLARIFY_STOP -> R.string.quickReply_clarify_stop
    QuickReplyCode.ARRIVING_IN_5_MIN -> R.string.quickReply_arriving_in_5_min
    QuickReplyCode.PRICE_AGREED, QuickReplyCode.UNKNOWN -> R.string.quickReply_price_agreed
}

@Composable
private fun MessageBubble(message: ChatMessageDTO, side: BookingSide) {
    val hidden = message.moderationStatus == ChatModerationStatus.HIDDEN_BY_STAFF
    // A quick reply is a code: its words come from this app's dictionary, in the reader's language.
    val text = when {
        hidden -> t(R.string.bookingChat_hiddenByStaff)
        message.quickReplyCode != null && message.quickReplyCode != QuickReplyCode.UNKNOWN -> tOrNull("quickReply.${message.quickReplyCode.value}") ?: message.text.orEmpty()
        else -> message.text.orEmpty()
    }
    ChatBubble(
        kind = when {
            hidden -> BubbleKind.HIDDEN
            message.isMine -> BubbleKind.MINE
            else -> BubbleKind.THEIRS
        },
        text = text,
        label = if (!message.isMine && !hidden) t(if (side == BookingSide.DRIVER) R.string.safety_clientTitle else R.string.safety_driverTitle) else null,
        time = chatTime(message.createdAt),
    )
}

/** Being sent (with "Yuborilmoqda...") or failed: "Yuborilmadi: “…”", why, and a retry with the same message. */
@Composable
private fun OutgoingBubble(message: OutgoingMessage, onRetry: () -> Unit, onDiscard: () -> Unit) {
    val text = message.text ?: message.quickReply?.let { tOrNull("quickReply.$it") }.orEmpty()
    if (!message.failed) {
        ChatBubble(BubbleKind.MINE, text, time = t(R.string.common_sending))
        return
    }
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Note(
            listOfNotNull(t(R.string.bookingChat_notSent, "text" to "“$text”"), message.error?.let { chatErrorText(it) }).joinToString(" · "),
            tone = Tone.ERR,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ElchiButton(t(R.string.common_retry), onRetry, Modifier.weight(1f).height(44.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM, icon = ElchiIcon.REFRESH, horizontalPadding = 10.dp)
            ElchiButton(t(R.string.client_chat_discard), onDiscard, Modifier.weight(1f).height(44.dp), ButtonVariant.GHOST, ButtonSize.MEDIUM, horizontalPadding = 10.dp)
        }
    }
}

/** RATE_LIMITED says when to try again (Q83: 20 a minute); the rest is the dictionary's sentence. */
@Composable
internal fun chatErrorText(error: Throwable): String {
    val api = error as? ApiException
    if (api?.code == "RATE_LIMITED") {
        BookingRules.retryAfterSeconds(api.details)?.let { return t(R.string.client_chat_rateLimited, "seconds" to it) }
    }
    return errorText(error)
}

/** CONTACT_INFO_MASKED and the like: the message went through, with contacts hidden. */
@Composable
private fun WarningNotes(warnings: List<ApiWarning>) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        warnings.forEach { Note(tOrNull("warning.${it.code}") ?: it.message, tone = Tone.WARN) }
    }
}

// -- support thread ----------------------------------------------------------------------------------------------

/**
 * "Yordam / shikoyat": the operator chat of this booking (Q141/Q146). No phone line is shown - the pilot has none
 * (Q87) - and no answer time is promised. A closed thread stays readable; "Yangi murojaat" starts another.
 */
@Composable
fun SupportChatScreen(vm: SupportViewModel, onBack: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    val list = rememberLazyListState()
    WhileStarted(vm) { vm.watch() }
    LaunchedEffect(s.scrollNonce) { if (s.scrollNonce > 0) list.animateScrollToItem((list.layoutInfo.totalItemsCount - 1).coerceAtLeast(0)) }
    val thread = s.thread
    val toast = LocalFlowToast.current
    val refreshed = t(R.string.client_booking_refreshed)
    ChatFrame(
        title = t(R.string.support_threadTitle),
        onBack = onBack,
        list = list,
        refreshing = s.refreshing && s.loaded,
        onRefresh = vm::refresh,
        unseen = 0,
        onPill = {},
        actions = {
            RoundIconButton(ElchiIcon.REFRESH, t(R.string.support_refresh), {
                vm.refresh()
                toast.show(refreshed)
            })
        },
        footer = when {
            !s.loaded -> null
            s.canWrite -> ({
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    s.sendError?.let { error ->
                        Note(listOf(t(R.string.bookingChat_notSent, "text" to "“${s.draft.trim()}”"), chatErrorText(error)).joinToString(" · "), tone = Tone.ERR)
                    }
                    Composer(
                        value = s.draft,
                        onValueChange = vm::setDraft,
                        placeholder = t(if (thread == null || s.startingNew) R.string.support_messagePlaceholder else R.string.support_draftLabel),
                        sendLabel = t(R.string.support_send),
                        onSend = vm::send,
                        hint = t(R.string.bookingChat_autoMaskNote),
                        sending = s.sending,
                    )
                }
            })
            else -> ({
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Note(t(R.string.client_support_closedText), tone = Tone.GRAY, title = t(R.string.support_status_closed))
                    ElchiButton(t(R.string.client_support_newThread), vm::startNew, Modifier.fillMaxWidth(), icon = ElchiIcon.PLUS)
                }
            })
        },
    ) {
        if (!s.loaded) {
            item { s.loadError?.let { LoadFailed(t(R.string.support_threadTitle), it, vm::refresh) } ?: LoadingLine(t(R.string.common_loading)) }
            return@ChatFrame
        }
        if (thread == null || (s.startingNew && thread.status == SupportViewModel.CLOSED)) {
            item(key = "intro") {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    // Design 04: "Holat · Yangi murojaat" before the first message.
                    ElchiCard { CardRow(t(R.string.support_statusLabel), t(R.string.client_support_newThread), first = true, strong = true) }
                    Note(t(R.string.support_noPhoneLine), tone = Tone.BLUE, title = t(R.string.support_cardTitle))
                    EmptyState(ElchiIcon.HEAD, t(R.string.support_threadTitle), description = t(R.string.support_emptyThread))
                    Text(t(R.string.support_noPromise), style = Elchi.type.caption, color = Elchi.colors.muted)
                }
            }
            return@ChatFrame
        }
        item(key = "status") {
            ElchiCard {
                CardRow(
                    t(R.string.support_statusLabel),
                    tOrNull(BookingRules.supportStatusKey(thread.staffStatus)) ?: thread.staffStatus,
                    first = true,
                    detail = t(R.string.support_noPromise),
                    strong = true,
                )
            }
        }
        items(BookingRules.supportMessages(thread.messages), key = { it.id }) { SupportBubble(it) }
        if (s.warnings.isNotEmpty()) item(key = "warnings") { Note(t(R.string.support_masked), tone = Tone.WARN) }
    }
}

@Composable
private fun SupportBubble(message: SupportMessageDTO) {
    when (message.author) {
        "me" -> ChatBubble(BubbleKind.MINE, message.text, time = chatTime(message.createdAt))
        "operator" -> ChatBubble(BubbleKind.OPERATOR, message.text, label = t(R.string.support_operator), time = chatTime(message.createdAt))
        else -> ChatBubble(BubbleKind.SYSTEM, listOfNotNull(message.text, chatTime(message.createdAt)).joinToString(" · "))
    }
}
