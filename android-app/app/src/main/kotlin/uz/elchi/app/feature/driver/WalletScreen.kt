package uz.elchi.app.feature.driver

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.elchi.app.R
import uz.elchi.app.api.generated.LedgerLineDTO
import uz.elchi.app.feature.client.Load
import uz.elchi.app.feature.client.LoadFailed
import uz.elchi.app.feature.client.LoadingLine
import uz.elchi.app.feature.client.OrderRules
import uz.elchi.app.feature.client.ParcelRules
import uz.elchi.app.feature.client.StatTiles
import uz.elchi.app.feature.client.StepScaffold
import uz.elchi.app.feature.client.ThousandsTransformation
import uz.elchi.app.feature.client.soum
import uz.elchi.app.i18n.errorText
import uz.elchi.app.i18n.t
import uz.elchi.app.i18n.tOrNull
import uz.elchi.app.ui.components.ButtonSize
import uz.elchi.app.ui.components.ButtonVariant
import uz.elchi.app.ui.components.Chip
import uz.elchi.app.ui.components.ElchiButton
import uz.elchi.app.ui.components.ElchiCard
import uz.elchi.app.ui.components.ElchiDialog
import uz.elchi.app.ui.components.ElchiField
import uz.elchi.app.ui.components.EmptyState
import uz.elchi.app.ui.components.ItemCard
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.SectionTitle
import uz.elchi.app.ui.components.Segmented
import uz.elchi.app.ui.icons.ElchiIcon
import uz.elchi.app.ui.theme.Elchi
import uz.elchi.app.ui.theme.Tone
import uz.elchi.app.ui.theme.tone
import java.time.Instant
import java.time.format.DateTimeFormatter

/**
 * `driver-income` "Komissiya balansi": what can pay ELCHI's commission now (the fare is cash between the client and
 * the driver and never here), the held / reversed / topped-up sums the ledger recorded, the commission captured in
 * the last 7 days, the top-up request (no invented bank details: the operator gives them, `driver.wallet.requisitesNote`),
 * the requests and the movements.
 */
@Composable
fun WalletScreen(
    vm: WalletViewModel,
    onBack: () -> Unit,
    onHelp: () -> Unit,
    /** The signed-in driver's phone: the transfer's payment purpose (design 09 2.7). */
    phone: String? = null,
) {
    val s by vm.state.collectAsStateWithLifecycle()
    LifecycleResumeEffect(vm) {
        vm.refresh()
        onPauseOrDispose { }
    }
    StepScaffold(title = t(R.string.income_title), onBack = onBack, onRefresh = vm::refresh, refreshing = s.refreshing && s.wallet is Load.Ready) {
        Balance(s)
        Chart(s)
        TopupForm(vm, s, onHelp, phone)
        Requests(s)
        Movements(vm, s)
    }
}

@Composable
private fun Balance(s: WalletViewModel.State) {
    val c = Elchi.colors
    val wallet = (s.wallet as? Load.Ready)?.value
    ElchiCard(padding = PaddingValues(16.dp)) {
        Text(t(R.string.income_available), style = Elchi.type.label, color = c.muted)
        Text(
            wallet?.let { soum(it.availableMinor) } ?: "—",
            Modifier.padding(top = 2.dp),
            style = Elchi.type.title.copy(fontSize = 30.sp, lineHeight = 36.sp, fontWeight = FontWeight.Bold),
            color = c.text,
        )
        Text(t(R.string.income_balanceNote), Modifier.padding(top = 4.dp), style = Elchi.type.caption, color = c.muted)
    }
    (s.wallet as? Load.Failed)?.let { LoadFailed(t(R.string.income_title), it.error, {}) }
    // Sums only from movements that were read: "—" until then, never a made-up zero.
    val tiles = (s.lines as? Load.Ready)?.value?.let(WalletRules::tiles)
    StatTiles(
        listOf(
            Triple(0, t(R.string.income_held), wallet?.let { soum(it.heldMinor) } ?: "—"),
            Triple(1, t(R.string.income_reversed), tiles?.let { soum(it.reversedMinor) } ?: "—"),
        ),
    )
    StatTiles(
        listOf(
            Triple(2, t(R.string.income_topups), tiles?.let { soum(it.topupsMinor) } ?: "—"),
            Triple(3, t(R.string.income_pendingTopups), wallet?.let { soum(it.pendingTopupsMinor) } ?: "—"),
        ),
    )
}

/**
 * "Ushlangan komissiya" with the "7 kun / 6 oy" toggle (design 09 2.3): seven Tashkent days or six calendar months of
 * captured commission, summed from the movements already loaded. A tap on a bar says its value (2.4).
 */
@Composable
private fun Chart(s: WalletViewModel.State) {
    val c = Elchi.colors
    var period by rememberSaveable { mutableStateOf(ChartPeriod.DAILY) }
    var picked by rememberSaveable(period) { mutableStateOf<Int?>(null) }
    ElchiCard(padding = PaddingValues(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(t(R.string.income_capturedTitle), Modifier.weight(1f), style = Elchi.type.bodyStrong, color = c.text)
            Segmented(
                listOf(ChartPeriod.DAILY to t(R.string.income_period_daily), ChartPeriod.MONTHLY to t(R.string.income_period_monthly)),
                selected = period,
                onSelect = { period = it },
                modifier = Modifier.width(150.dp),
            )
        }
        when (val lines = s.lines) {
            Load.Loading -> LoadingLine(t(R.string.common_loading))
            is Load.Failed -> Note(errorText(lines.error), Modifier.padding(top = 8.dp), tone = Tone.ERR)
            is Load.Ready -> {
                val now = Instant.now()
                val bars: List<Pair<String, Long>> = if (period == ChartPeriod.DAILY) {
                    val dayFormat = DateTimeFormatter.ofPattern("dd.MM")
                    WalletRules.chart(lines.value, now).map { it.day.format(dayFormat) to it.minor }
                } else {
                    val monthFormat = DateTimeFormatter.ofPattern("MM.yy")
                    WalletRules.monthly(lines.value, now).map { it.month.format(monthFormat) to it.minor }
                }
                // The sum of the bars shown (the ledger's own captures in this period).
                Text(soum(bars.sumOf { it.second }), Modifier.padding(top = 4.dp), style = Elchi.type.section.copy(fontWeight = FontWeight.SemiBold), color = c.text)
                if (bars.all { it.second == 0L }) {
                    Text(t(R.string.income_chartEmpty), Modifier.fillMaxWidth().padding(vertical = 24.dp), style = Elchi.type.label, color = c.muted, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                } else {
                    val max = bars.maxOf { it.second }.coerceAtLeast(1)
                    Row(Modifier.fillMaxWidth().height(140.dp).padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.Bottom) {
                        bars.forEachIndexed { i, (label, minor) ->
                            val described = "$label: ${soum(minor)}"
                            val selected = picked == i
                            Column(
                                Modifier.weight(1f).fillMaxHeight().semantics { contentDescription = described }
                                    .clickable(role = Role.Button) { picked = if (selected) null else i },
                                verticalArrangement = Arrangement.Bottom,
                                horizontalAlignment = Alignment.CenterHorizontally,
                            ) {
                                Text(
                                    if (selected) soum(minor) else "",
                                    style = Elchi.type.caption.copy(fontSize = 9.5.sp, fontWeight = FontWeight.SemiBold),
                                    color = c.text,
                                    maxLines = 1,
                                    softWrap = false,
                                )
                                val fraction = (minor.toFloat() / max).coerceIn(0.03f, 1f)
                                Box(Modifier.fillMaxWidth().weight(1f), contentAlignment = Alignment.BottomCenter) {
                                    val color = when {
                                        minor == 0L -> c.field
                                        selected -> c.navy
                                        else -> c.brand
                                    }
                                    Box(Modifier.fillMaxWidth().fillMaxHeight(fraction).clip(RoundedCornerShape(6.dp)).background(color))
                                }
                                Text(label, Modifier.padding(top = 4.dp), style = Elchi.type.caption.copy(fontSize = 10.sp), color = c.muted, maxLines = 1)
                            }
                        }
                    }
                }
            }
        }
        Text(t(R.string.income_chartNote), Modifier.padding(top = 8.dp), style = Elchi.type.caption, color = c.muted)
    }
}

@Composable
private fun TopupForm(vm: WalletViewModel, s: WalletViewModel.State, onHelp: () -> Unit, phone: String?) {
    val c = Elchi.colors
    var confirm by rememberSaveable { mutableStateOf(false) }
    SectionTitle(t(R.string.income_topupTitle), description = t(R.string.income_topupNote))
    // No bank details exist in the system: the operator gives them (never invented here, 2.6 BLOCKED).
    Note(t(R.string.driver_wallet_requisitesNote), tone = Tone.BLUE)
    // The part of the design's requisites card that is real: the driver's own number as the payment purpose (2.7).
    WalletRules.paymentPurposePhone(phone)?.let { purpose -> PaymentPurpose(purpose) }
    ElchiButton(t(R.string.driverProfile_action_support), onHelp, Modifier.fillMaxWidth().height(46.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM, icon = ElchiIcon.HEAD)
    val form = s.form
    ElchiField(
        form.amount,
        { text -> vm.edit { it.copy(amount = text.filter(Char::isDigit).trimStart('0').take(10)) } },
        label = t(R.string.income_amountLabel),
        placeholder = "100 000",
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Next),
        visualTransformation = ThousandsTransformation,
        suffix = t(R.string.common_soum),
        // Only a typed amount the request cannot carry is refused in words; an empty field just waits.
        error = if (form.amount.isNotEmpty() && WalletRules.topupBody(form.amount, form.method, "", "") == null) t(R.string.driver_wallet_amountInvalid) else null,
    )
    // Q17: above the two-person threshold a second finance approver is needed (design 09 2.10).
    if (WalletRules.largeAmount(form.amount)) {
        Text(t(R.string.driver_v3wallet_largeAmount), style = Elchi.type.caption, color = c.tone(Tone.WARN).fg)
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        WalletRules.PRESETS.forEach { preset ->
            val digits = preset.toString()
            Chip(soumPlain(preset), form.amount == digits, { vm.edit { it.copy(amount = digits) } }, filled = true)
        }
    }
    Text(t(R.string.driver_wallet_methodLabel), style = Elchi.type.label, color = c.text)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        WalletRules.METHODS.forEach { method ->
            Chip(methodLabel(method), form.method == method, { vm.edit { it.copy(method = method) } }, filled = true)
        }
    }
    ElchiField(
        form.payerReference,
        { text -> vm.edit { it.copy(payerReference = text.take(WalletRules.PAYER_REFERENCE_MAX)) } },
        label = t(R.string.driver_wallet_payerReference),
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
    )
    ElchiField(
        form.note,
        { text -> vm.edit { it.copy(note = text.take(WalletRules.NOTE_MAX)) } },
        label = t(R.string.driver_wallet_noteLabel),
        singleLine = false,
        minHeight = 72.dp,
        keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
    )
    s.sendError?.let { Note(errorText(it), tone = Tone.ERR) }
    val body = WalletRules.topupBody(form.amount, form.method, form.payerReference, form.note)
    ElchiButton(
        t(R.string.income_topupSend),
        { confirm = true },
        Modifier.fillMaxWidth(),
        enabled = body != null,
        loading = s.sending,
    )
    // Design 09 2.14: the request reaches a finance person - one check before it goes.
    if (confirm && body != null) {
        ElchiDialog(
            title = t(R.string.driver_v3wallet_confirmTitle, "amount" to soum(body.amountMinor)),
            text = t(R.string.driver_v3wallet_confirmText),
            confirm = t(R.string.driver_v3wallet_confirmYes),
            onConfirm = {
                confirm = false
                vm.sendTopup()
            },
            onDismiss = { confirm = false },
            dismiss = t(R.string.confirmDialog_back),
        )
    }
}

/** "50 000" - a preset chip's number without the currency (design 09 2.11). */
private fun soumPlain(soum: Long): String = String.format(java.util.Locale.ROOT, "%,d", soum).replace(',', ' ')

/** "To'lov maqsadi: 90 777 11 22" with a copy action. */
@Composable
private fun PaymentPurpose(purpose: String) {
    val c = Elchi.colors
    val context = LocalContext.current
    var copied by remember { mutableStateOf(false) }
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(c.field).padding(start = 14.dp, end = 6.dp, top = 6.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(t(R.string.driver_v3wallet_paymentPurpose, "phone" to purpose), Modifier.weight(1f), style = Elchi.type.label, color = c.text)
        ElchiButton(
            t(if (copied) R.string.promoScreen_copied else R.string.promoScreen_copy),
            {
                (context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("ELCHI", purpose.replace(" ", "")))
                copied = true
            },
            Modifier.height(40.dp),
            ButtonVariant.GHOST,
            ButtonSize.MEDIUM,
            icon = ElchiIcon.COPY,
            horizontalPadding = 10.dp,
        )
    }
}

@Composable
private fun methodLabel(method: String): String = when (method) {
    "cash_desk" -> t(R.string.driver_wallet_method_cash_desk)
    else -> t(R.string.driver_wallet_method_bank_transfer)
}

@Composable
private fun Requests(s: WalletViewModel.State) {
    SectionTitle(t(R.string.income_requestsTitle))
    when (val topups = s.topups) {
        Load.Loading -> LoadingLine(t(R.string.common_loading))
        is Load.Failed -> LoadFailed(t(R.string.income_requestsTitle), topups.error, {})
        is Load.Ready -> if (topups.value.isEmpty()) {
            EmptyState(ElchiIcon.WALLET, t(R.string.income_requestsEmpty), description = t(R.string.income_requestsEmptyHint))
        } else {
            topups.value.forEach { topup ->
                ItemCard(
                    title = soum(topup.amountMinor),
                    sub = listOfNotNull(OrderRules.tashkent(topup.createdAt)?.let(ParcelRules::displayShort), methodLabel(topup.method)).joinToString(" · "),
                    badge = (tOrNull(WalletRules.topupStatusKey(topup.status)) ?: topup.status.value) to WalletRules.topupTone(topup.status),
                )
            }
        }
    }
}

@Composable
private fun Movements(vm: WalletViewModel, s: WalletViewModel.State) {
    SectionTitle(t(R.string.driver_wallet_transactionsTitle))
    when (val lines = s.lines) {
        Load.Loading -> LoadingLine(t(R.string.common_loading))
        is Load.Failed -> LoadFailed(t(R.string.driver_wallet_transactionsTitle), lines.error, vm::refresh)
        is Load.Ready -> if (lines.value.isEmpty()) {
            Text(t(R.string.driver_wallet_transactionsEmpty), style = Elchi.type.label, color = Elchi.colors.muted)
        } else {
            lines.value.forEach { MovementRow(it) }
            if (s.linesCursor != null) {
                ElchiButton(t(R.string.blockReport_loadMore), vm::loadMore, Modifier.fillMaxWidth().height(44.dp), ButtonVariant.GHOST, ButtonSize.MEDIUM, loading = s.loadingMore)
            }
        }
    }
}

@Composable
private fun MovementRow(line: LedgerLineDTO) {
    val c = Elchi.colors
    val credit = line.direction == WalletRules.CREDIT
    ItemCard(
        title = kindLabel(line.kind),
        sub = OrderRules.tashkent(line.occurredAt)?.let(ParcelRules::displayShort),
        meta = t(R.string.driver_wallet_balanceAfter, "amount" to soum(line.balanceAfterMinor)),
        right = "${WalletRules.signed(line)}${soum(line.amountMinor)}",
        // Design 09 2.20: what the balance gained in green, what it lost in red.
        rightColor = if (credit) Elchi.colors.tone(Tone.OK).fg else c.tone(Tone.ERR).fg,
    )
}

@Composable
private fun kindLabel(kind: String): String = when (kind) {
    WalletRules.KIND_TOPUP -> t(R.string.driver_wallet_kind_topup)
    WalletRules.KIND_CAPTURE -> t(R.string.driver_wallet_kind_commission_capture)
    WalletRules.KIND_REVERSAL -> t(R.string.driver_wallet_kind_reversal)
    WalletRules.KIND_ADJUSTMENT -> t(R.string.driver_wallet_kind_adjustment)
    else -> kind
}
