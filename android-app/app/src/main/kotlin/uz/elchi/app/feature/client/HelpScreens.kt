package uz.elchi.app.feature.client

import android.content.Intent
import androidx.core.net.toUri
import androidx.activity.compose.LocalActivity
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.elchi.app.R
import uz.elchi.app.api.generated.BlockDTO
import uz.elchi.app.api.generated.SupportThreadDTO
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiDialog
import uz.elchi.app.ui.components.ElchiField
import uz.elchi.app.ui.components.ElchiIconView
import uz.elchi.app.ui.components.EmptyState
import uz.elchi.app.ui.components.ItemCard
import uz.elchi.app.ui.components.ListCard
import uz.elchi.app.ui.components.ListRow
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.RoundIconButton
import uz.elchi.app.ui.components.SectionTitle
import uz.elchi.app.ui.components.SkeletonCard
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone

// -- support ------------------------------------------------------------------------------------------------------

/** Which questions the Help screen answers: the client's (Stage 05) or the driver's (Stage 07). */
enum class FaqSet { CLIENT, DRIVER }

/**
 * `support` "Yordam": the support line only when the server has one (Q87: none in the pilot, and no hours or answer
 * times are promised), a ticket form, my tickets (they get no replies - no thread screen), the operator
 * conversations, and the FAQ.
 */
@Composable
fun HelpScreen(vm: HelpViewModel, onBack: () -> Unit, onThreads: () -> Unit, onThread: (String) -> Unit, faq: FaqSet = FaqSet.CLIENT) {
    val s by vm.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val activity = LocalActivity.current
    StepScaffold(title = t(R.string.support_title), onBack = onBack, onRefresh = vm::refresh, refreshing = s.refreshing && s.tickets !is Load.Loading) {
        val phone = s.contacts?.takeIf { it.available }?.phone?.takeIf { it.isNotBlank() }
        if (phone != null) {
            ElchiCard(padding = PaddingValues(16.dp)) {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(t(R.string.support_cardTitle), style = Elchi.type.bodyStrong, color = Elchi.colors.text)
                    ElchiButton(displayPhone(phone), {
                        val dial = Intent(Intent.ACTION_DIAL, BookingRules.dialUri(phone).toUri())
                        runCatching { activity?.startActivity(dial) ?: context.startActivity(dial.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                    }, Modifier.fillMaxWidth(), ButtonVariant.SOFT, ButtonSize.MEDIUM, icon = ElchiIcon.PHONE)
                }
            }
        } else {
            Note(t(R.string.support_noPhoneLine), tone = Tone.BLUE, title = t(R.string.support_cardTitle))
        }

        SectionTitle(t(R.string.support_newTicket))
        ElchiField(
            value = s.draft,
            onValueChange = vm::setDraft,
            placeholder = t(R.string.support_messagePlaceholder),
            singleLine = false,
            minHeight = 110.dp,
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
            // Design 05: "Kamida 5 ta belgi yozing" while too little is typed; the masking note otherwise.
            hint = t(if (SafetyRules.ticketTooShort(s.draft)) R.string.client_help_minChars else R.string.bookingChat_autoMaskNote),
        )
        if (s.sent) Note(t(R.string.support_ticketSent), tone = Tone.OK)
        s.sendError?.let { Note(errorText(it), tone = Tone.ERR) }
        ElchiButton(t(R.string.support_send), vm::send, Modifier.fillMaxWidth(), enabled = SafetyRules.ticketReady(s.draft), loading = s.sending)

        // Tickets get no replies (spec §5) - their own section, named apart from the operator conversations below.
        SectionTitle(t(R.string.client_help_ticketsTitle))
        when (val tickets = s.tickets) {
            Load.Loading -> SkeletonCard(t(R.string.common_loading), lines = 2)
            is Load.Failed -> LoadFailed(t(R.string.client_help_ticketsTitle), tickets.error, vm::refresh)
            is Load.Ready -> if (tickets.value.isEmpty()) {
                Note(t(R.string.support_noThreadsTitle), tone = Tone.GRAY)
            } else {
                tickets.value.forEach { ticket ->
                    ItemCard(
                        title = SafetyRules.ticketTitle(ticket.message) ?: t(R.string.support_cardTitle),
                        badge = SafetyRules.ticketStatusKey(ticket.status)?.let { key -> tOrNull(key)?.let { it to SafetyRules.ticketTone(ticket.status) } },
                        sub = PromoRules.date(ticket.createdAt),
                    )
                }
            }
        }

        // Design 05: "Murojaatlarim" + "Hammasi (n)", then the newest conversation; the row only while there is none.
        val threads = (s.threads as? Load.Ready)?.value.orEmpty()
        if (threads.isNotEmpty()) {
            SectionTitle(t(R.string.support_myThreads), action = t(R.string.client_help_allThreads, "count" to threads.size), onAction = onThreads)
            SupportThreadCard(threads.first(), onClick = { onThread(threads.first().id) })
        } else {
            ListCard {
                ListRow(t(R.string.support_myThreads), icon = ElchiIcon.FILE, description = t(R.string.support_myThreadsHint), first = true, onClick = onThreads)
            }
        }

        SectionTitle(t(R.string.support_faqTitle))
        Faq(
            when (faq) {
                FaqSet.CLIENT -> listOf(
                    t(R.string.support_faq1Question) to t(R.string.support_faq1Answer),
                    t(R.string.support_faq2Question) to t(R.string.support_faq2Answer),
                    t(R.string.support_faq3Question) to t(R.string.support_faq3Answer),
                    // Q142: a parcel's phones open when the trip departs, not at pick-up.
                    t(R.string.support_faq4Question) to t(R.string.client_help_faq4Answer),
                )
                FaqSet.DRIVER -> listOf(
                    t(R.string.driver_faq1Question) to t(R.string.driver_faq1Answer),
                    t(R.string.driver_faq2Question) to t(R.string.driver_faq2Answer),
                    t(R.string.driver_faq3Question) to t(R.string.driver_faq3Answer),
                    t(R.string.driver_faq4Question) to t(R.string.driver_faq4Answer),
                )
            },
        )
    }
}

/** The prototype's `faq`: one card, a question per row, one answer open at a time (the first to start with). */
@Composable
private fun Faq(items: List<Pair<String, String>>) {
    var open by rememberSaveable { mutableIntStateOf(0) }
    val c = Elchi.colors
    ElchiCard(padding = PaddingValues(horizontal = 16.dp, vertical = 4.dp)) {
        items.forEachIndexed { i, (question, answer) ->
            if (i > 0) Spacer(Modifier.fillMaxWidth().height(1.dp).background(c.field))
            val expanded = open == i
            Column(
                Modifier
                    .fillMaxWidth()
                    .heightIn(min = 48.dp)
                    .clickable(role = Role.Button) { open = if (expanded) -1 else i }
                    .semantics { stateDescription = if (expanded) "+" else "-" }
                    .padding(vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(question, Modifier.weight(1f), style = Elchi.type.secondary.copy(fontWeight = FontWeight.Medium), color = c.text)
                    ElchiIconView(if (expanded) ElchiIcon.CHEV_U else ElchiIcon.CHEV_D, c.muted, size = 16.dp)
                }
                if (expanded) Text(answer, style = Elchi.type.label.copy(fontWeight = FontWeight.Normal), color = c.muted)
            }
        }
    }
}

// -- my-support-threads -------------------------------------------------------------------------------------------

/** `my-support-threads` "Murojaatlarim": every operator conversation; a row opens the Stage 04 thread screen. */
@Composable
fun SupportThreadsScreen(vm: SupportThreadsViewModel, onBack: () -> Unit, onThread: (String) -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    // Read again whenever the screen shows (after an answer was read or written in a thread).
    LaunchedEffect(Unit) { vm.refresh() }
    StepScaffold(
        title = t(R.string.support_myThreads),
        onBack = onBack,
        onRefresh = { vm.refresh() },
        refreshing = s.refreshing && s.threads is Load.Ready,
        actions = { RoundIconButton(ElchiIcon.REFRESH, t(R.string.support_refresh), { vm.refresh(announce = true) }, loading = s.refreshing) },
    ) {
        when (val threads = s.threads) {
            Load.Loading -> repeat(2) { SkeletonCard(t(R.string.common_loading), lines = 2) }
            is Load.Failed -> LoadFailed(t(R.string.support_myThreads), threads.error, { vm.refresh() })
            is Load.Ready -> if (threads.value.isEmpty()) {
                EmptyState(ElchiIcon.HEAD, t(R.string.support_noThreadsTitle), Modifier.padding(top = 24.dp), description = t(R.string.support_noThreadsHint))
            } else {
                threads.value.forEach { thread -> SupportThreadCard(thread, onClick = { onThread(thread.id) }) }
                // Design 05: the booking button's note stays under a list too, not only on the empty state.
                Note(t(R.string.support_noThreadsHint), tone = Tone.GRAY)
            }
        }
    }
}

/** One operator conversation: title, the staff status badge, "n xabar · date". */
@Composable
private fun SupportThreadCard(thread: SupportThreadDTO, onClick: () -> Unit) {
    ItemCard(
        title = t(R.string.support_threadTitle),
        badge = (tOrNull(BookingRules.supportStatusKey(thread.staffStatus)) ?: thread.staffStatus) to SafetyRules.threadTone(thread.staffStatus),
        sub = t(R.string.support_threadMeta, "count" to thread.messageCount, "date" to (PromoRules.date(thread.createdAt) ?: "")),
        onClick = onClick,
    )
}

// -- safety-center ------------------------------------------------------------------------------------------------

/**
 * `safety-center` "Bloklanganlar va shikoyatlarim": the people I blocked (with "Chiqarish" after a confirmation)
 * and my reports with their review state. A refused unblock keeps the row and says why.
 */
@Composable
fun SafetyCenterScreen(vm: SafetyCenterViewModel, onBack: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    var confirm by rememberSaveable { mutableStateOf<String?>(null) }
    StepScaffold(title = t(R.string.safety_centerTitle), onBack = onBack, onRefresh = vm::refresh, refreshing = s.refreshing && s.blocks !is Load.Loading) {
        Note(t(R.string.safety_centerDescription), tone = Tone.GRAY)

        SectionTitle(t(R.string.client_safety_blocksTitle))
        when (val blocks = s.blocks) {
            Load.Loading -> SkeletonCard(t(R.string.common_loading), lines = 2)
            is Load.Failed -> LoadFailed(t(R.string.blockReport_blockTitle), blocks.error, vm::refresh)
            is Load.Ready -> if (blocks.value.isEmpty()) {
                Note(t(R.string.blockReport_blocksEmpty), tone = Tone.GRAY)
            } else {
                ListCard {
                    blocks.value.forEachIndexed { i, block -> BlockRow(block, first = i == 0, busy = s.unblocking == block.userId, onUnblock = { confirm = block.userId }) }
                }
            }
        }
        s.unblockError?.let { (_, error) -> Note(t(R.string.client_safety_unblockFailed, "error" to errorText(error)), tone = Tone.ERR) }

        SectionTitle(t(R.string.blockReport_myReportsTitle))
        val reports = s.reports
        when {
            !reports.loaded -> SkeletonCard(t(R.string.common_loading), lines = 2)
            reports.error != null -> LoadFailed(t(R.string.blockReport_myReportsTitle), reports.error, vm::refresh)
            reports.items.isEmpty() -> Note(t(R.string.blockReport_myReportsEmpty), tone = Tone.GRAY)
            else -> {
                reports.items.forEach { report ->
                    val subject = tOrNull("blockReport.subject.${report.subjectType.value}")
                    ItemCard(
                        title = tOrNull("blockReport.reason.${report.reasonCode.value}") ?: report.reasonCode.value,
                        badge = tOrNull(SafetyRules.reportStatusKey(report.status))?.let { it to SafetyRules.reportTone(report.status) },
                        sub = listOfNotNull(subject, PromoRules.date(report.createdAt)).joinToString(" · "),
                    )
                }
                if (reports.next != null) {
                    ElchiButton(t(R.string.blockReport_loadMore), vm::loadMoreReports, Modifier.fillMaxWidth(), ButtonVariant.GHOST, ButtonSize.MEDIUM, icon = ElchiIcon.REFRESH, loading = reports.loadingMore)
                }
            }
        }
    }
    // Design 05: unblocking is not destructive - a primary button. No name: the block DTO carries only the id.
    confirm?.let { userId ->
        ElchiDialog(
            title = t(R.string.client_profile_unblockTitle),
            text = t(R.string.client_profile_unblockText),
            confirm = t(R.string.blockReport_unblock),
            onConfirm = {
                confirm = null
                vm.unblock(userId)
            },
            onDismiss = { confirm = null },
            confirmVariant = ButtonVariant.PRIMARY,
            dismiss = t(R.string.confirmDialog_back),
            stacked = true,
        )
    }
}

@Composable
private fun BlockRow(block: BlockDTO, first: Boolean, busy: Boolean, onUnblock: () -> Unit) {
    val c = Elchi.colors
    val date = PromoRules.date(block.createdAt).orEmpty()
    Column {
        if (!first) Spacer(Modifier.fillMaxWidth().height(1.dp).background(c.field))
        Row(
            Modifier.fillMaxWidth().heightIn(min = 64.dp).padding(horizontal = 14.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            ElchiIconView(ElchiIcon.USER, c.accentText, size = 18.dp)
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
                Text(t(R.string.blockReport_subject_user), style = Elchi.type.secondary.copy(fontWeight = FontWeight.SemiBold), color = c.text)
                Text(t(R.string.client_safety_blockedAt, "date" to date), style = Elchi.type.caption, color = c.muted)
            }
            ElchiButton(t(R.string.blockReport_unblockShort), onUnblock, Modifier.height(40.dp), ButtonVariant.DANGER_SOFT, ButtonSize.MEDIUM, loading = busy, horizontalPadding = 14.dp)
        }
    }
}
