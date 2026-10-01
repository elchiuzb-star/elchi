package uz.elchi.app.feature.driver

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
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
import uz.elchi.app.ui.components.ElchiField
import uz.elchi.app.ui.components.EmptyState
import uz.elchi.app.ui.components.ItemCard
import uz.elchi.app.ui.components.Note
import uz.elchi.app.ui.components.SectionTitle
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
fun WalletScreen(vm: WalletViewModel, onBack: () -> Unit, onHelp: () -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    LifecycleResumeEffect(vm) {
        vm.refresh()
        onPauseOrDispose { }
    }
    StepScaffold(title = t(R.string.income_title), onBack = onBack, onRefresh = vm::refresh, refreshing = s.refreshing && s.wallet is Load.Ready) {
        Balance(s)
        Chart(s)
        TopupForm(vm, s, onHelp)
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

/** Seven bars of captured commission (Tashkent days); empty state when nothing was captured. */
@Composable
private fun Chart(s: WalletViewModel.State) {
    val c = Elchi.colors
    ElchiCard(padding = PaddingValues(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(t(R.string.driver_wallet_chartTitle), Modifier.weight(1f), style = Elchi.type.bodyStrong, color = c.text)
        }
        // The sum of the movements read (the ledger's own captures), "—" until they are read.
        (s.lines as? Load.Ready)?.value?.let { lines ->
            Text(soum(WalletRules.tiles(lines).capturedMinor), style = Elchi.type.section.copy(fontWeight = FontWeight.SemiBold), color = c.text)
        }
        when (val lines = s.lines) {
            Load.Loading -> LoadingLine(t(R.string.common_loading))
            is Load.Failed -> Note(errorText(lines.error), Modifier.padding(top = 8.dp), tone = Tone.ERR)
            is Load.Ready -> {
                val chart = WalletRules.chart(lines.value, Instant.now())
                if (WalletRules.chartEmpty(chart)) {
                    Text(t(R.string.income_chartEmpty), Modifier.fillMaxWidth().padding(vertical = 24.dp), style = Elchi.type.label, color = c.muted, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                } else {
                    val max = chart.maxOf { it.minor }.coerceAtLeast(1)
                    val dayFormat = DateTimeFormatter.ofPattern("dd.MM")
                    Row(Modifier.fillMaxWidth().height(120.dp).padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.Bottom) {
                        chart.forEach { day ->
                            val label = "${day.day.format(dayFormat)}: ${soum(day.minor)}"
                            Column(Modifier.weight(1f).fillMaxHeight().semantics { contentDescription = label }, verticalArrangement = Arrangement.Bottom, horizontalAlignment = Alignment.CenterHorizontally) {
                                val fraction = (day.minor.toFloat() / max).coerceIn(0.03f, 1f)
                                Box(Modifier.fillMaxWidth().weight(1f), contentAlignment = Alignment.BottomCenter) {
                                    Box(Modifier.fillMaxWidth().fillMaxHeight(fraction).clip(RoundedCornerShape(6.dp)).background(if (day.minor > 0) c.brand else c.field))
                                }
                                Text(day.day.format(dayFormat), Modifier.padding(top = 4.dp), style = Elchi.type.caption.copy(fontSize = 10.sp), color = c.muted, maxLines = 1)
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
private fun TopupForm(vm: WalletViewModel, s: WalletViewModel.State, onHelp: () -> Unit) {
    SectionTitle(t(R.string.income_topupTitle), description = t(R.string.income_topupNote))
    // No bank details exist in the system: the operator gives them (never invented here).
    Note(t(R.string.driver_wallet_requisitesNote), tone = Tone.BLUE)
    ElchiButton(t(R.string.driverProfile_action_support), onHelp, Modifier.fillMaxWidth().height(46.dp), ButtonVariant.NEUTRAL, ButtonSize.MEDIUM, icon = ElchiIcon.HEAD)
    val form = s.form
    ElchiField(
        form.amount,
        { text -> vm.edit { it.copy(amount = text.filter(Char::isDigit).trimStart('0').take(10)) } },
        label = t(R.string.income_amountLabel),
        placeholder = "100 000",
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Next),
        visualTransformation = ThousandsTransformation,
        // Only a typed amount the request cannot carry is refused in words; an empty field just waits.
        error = if (form.amount.isNotEmpty() && WalletRules.topupBody(form.amount, form.method, "", "") == null) t(R.string.driver_wallet_amountInvalid) else null,
    )
    Text(t(R.string.driver_wallet_methodLabel), style = Elchi.type.label, color = Elchi.colors.text)
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
    ElchiButton(
        t(R.string.income_topupSend),
        vm::sendTopup,
        Modifier.fillMaxWidth(),
        enabled = WalletRules.topupBody(form.amount, form.method, form.payerReference, form.note) != null,
        loading = s.sending,
    )
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
        rightColor = if (credit) Elchi.colors.tone(Tone.OK).fg else c.text,
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
